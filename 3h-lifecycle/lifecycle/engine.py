"""The 3H engine: work out what must change in Keycloak, then change it.

Two separate steps, so that nothing changes by accident:
  1. read_state() looks at Keycloak (read-only) and plan() compares it with the HR feed. plan()
     is a plain function: it returns a list of Actions and touches nothing.
  2. apply() carries the actions out.

The engine is idempotent (safe to repeat): plan() only produces an action when Keycloak differs
from the feed, so once apply() has run, a second plan() returns an empty list.

Leavers are disabled, never deleted. There is no delete-user call anywhere in this program.

Controls added in T3-S03 (see sod-rules.yaml and lifecycle/sod.py):
  - proofing gate: a joiner is created only when all three identity checks are true, and no
    joiner or mover row may have the same requester and approver (leaver rows are never blocked,
    because blocking a leaver would keep their access alive);
  - SOD-2: a person who would end up in both payments groups is skipped, nothing half-applied;
  - SOD-3: a service account without an active owner is never created, and is disabled if it
    already exists.
"""

import warnings
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from lifecycle import sod
from lifecycle.feed import Feed, Joiner, ServiceAccount
from lifecycle.kc import KeycloakError

# The kinds of action. SKIPPED is only a report line: apply() never carries it out.
CREATE_USER = "create_user"
MOVE_USER = "move_user"
DISABLE_USER = "disable_user"
ENABLE_USER = "enable_user"
CREATE_CLIENT = "create_client"
UPDATE_CLIENT = "update_client"
END_SESSIONS = "end_sessions"
SKIPPED = "skipped"
BLOCKED = "blocked"   # a row the controls refuse (proofing gate, requester = approver, SOD-3)
WARNING = "warning"   # something a person should look at (for example a manager who has left)
REPORT_ONLY = (SKIPPED, BLOCKED, WARNING)  # lines in the plan that apply() never carries out

# Keycloak's own clients. They are never reported as service accounts.
BUILTIN_CLIENTS = {"account", "account-console", "admin-cli", "broker", "realm-management",
                   "security-admin-console"}

# The three identity checks a joiner needs before an account is created.
PROOFING_CHECKS = ("id_checked_live_video", "references_contacted", "education_verified")
# Set on a service account the engine disabled because its owner is missing or gone (SOD-3).
DISABLED_FOR_SOD3 = "disabled_by_engine"


# Groups that give powerful access. The plan flags any person who gains one, so a reviewer
# looking at the table cannot miss it.
PRIVILEGED_GROUPS = {"privileged"}
PRIVILEGED_FLAG = " PRIVILEGED"

# Marker the engine puts on a joiner it created DISABLED because their start date is still ahead.
# The value is the start date. Only an account with this marker is ever enabled by the engine, so
# an account that an administrator disabled is never switched back on.
PENDING_START = "pending_start"


class EngineError(Exception):
    """Something is wrong with the roles map or with the directory the plan needs."""


@dataclass
class Action:
    kind: str       # one of the constants above
    target: str     # employee id or service-account (client) id
    summary: str    # one line shown in the plan table
    details: dict = field(default_factory=dict)  # everything apply() needs


# ---- roles map ----------------------------------------------------------------------------

class RolesMapWarning(UserWarning):
    """roles-map.yaml is valid but contains something a reviewer should know about."""


@dataclass
class RolesMap:
    departments: dict[str, list[str]]
    job_titles: dict[str, list[str]]
    # Every group the engine may add or remove, including old ones the map no longer hands out.
    managed_groups: set[str]

    def groups_for(self, department: str, job_title: str) -> set[str]:
        """Groups for a person = groups of their department + groups of their job title."""
        if department not in self.departments:
            raise EngineError(f"department '{department}' is not in roles-map.yaml")
        if job_title not in self.job_titles:
            raise EngineError(f"job title '{job_title}' is not in roles-map.yaml")
        return set(self.departments[department]) | set(self.job_titles[job_title])

    def conflicting_pairs(self) -> list[tuple[str, str]]:
        """Department + job title pairs whose groups include BOTH payment groups. Anyone given
        such a pair is stopped by SOD-2; the pair is legal in the file but worth a look."""
        pairs = []
        for department in self.departments:
            for job_title in self.job_titles:
                if sod.has_payment_conflict(self.groups_for(department, job_title)):
                    pairs.append((department, job_title))
        return pairs

    def assigned_groups(self) -> set[str]:
        """Every group the map gives to somebody."""
        names: set[str] = set()
        for groups in [*self.departments.values(), *self.job_titles.values()]:
            names.update(groups)
        return names


def load_roles_map(path: str | Path) -> RolesMap:
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    try:
        roles_map = RolesMap(departments=data["departments"], job_titles=data["job_titles"],
                             managed_groups=set(data["managed_groups"]))
    except (TypeError, KeyError):
        raise EngineError(
            "roles-map.yaml needs 'departments', 'job_titles' and 'managed_groups' sections"
        ) from None
    unlisted = roles_map.assigned_groups() - roles_map.managed_groups
    if unlisted:
        raise EngineError("roles-map.yaml hands out group(s) missing from managed_groups: "
                          + ", ".join(sorted(unlisted)))
    for department, job_title in roles_map.conflicting_pairs():
        warnings.warn(
            f"roles-map.yaml: department '{department}' + job title '{job_title}' would give "
            "both payment groups; SOD-2 will stop anyone given that pair", RolesMapWarning,
            stacklevel=2)
    return roles_map


# ---- reading the current state ------------------------------------------------------------

@dataclass
class UserState:
    id: str
    enabled: bool
    attributes: dict[str, str]
    groups: set[str]
    name: str = ""
    # Only looked up for disabled accounts: does a login session or offline token still exist?
    live_access: bool = False


@dataclass
class State:
    # key: lower-case employee id (people in the feed, plus the managers and service-account
    # owners they name); None means "no such account"
    users: dict[str, UserState | None]
    clients: dict[str, dict | None]      # key: client id; None means "no such client"
    group_ids: dict[str, str]            # group name -> group id
    # usernames (lower case) found in each payment group, read straight from the directory
    payment_members: dict[str, set[str]] = field(default_factory=dict)
    # service-account clients in the directory that are not in the CSV (reported, never changed)
    other_clients: list[dict] = field(default_factory=list)

    def user(self, employee_id: str) -> UserState | None:
        return self.users.get(employee_id.lower())


def username_for(employee_id: str) -> str:
    """The Keycloak username is the employee id (lower case): it never changes if a name does."""
    return employee_id.lower()


def read_state(kc, feed: Feed, service_accounts: list[ServiceAccount]) -> State:
    """Look up (read-only) everything in Keycloak that the feed talks about: the people in it,
    the managers, requesters and approvers it names, the owners of service accounts, who is in
    the payment groups, and service-account clients that are not in the CSV."""
    group_ids = {group["name"]: group["id"] for group in kc.list_groups()}
    movers_and_joiners = [*feed.joiners, *feed.movers]
    ids = [person.employee_id for person in [*movers_and_joiners, *feed.leavers]]
    for person in movers_and_joiners:
        ids += [person.manager_id, person.requested_by, person.approved_by]
    ids += [account.owner for account in service_accounts if account.owner]

    listed = {account.client_id for account in service_accounts}
    other_clients = [
        client for client in kc.list_clients()
        if client["clientId"] not in listed and client["clientId"] not in BUILTIN_CLIENTS
        and (client.get("serviceAccountsEnabled") or (client.get("attributes") or {}).get("owner"))
    ]
    ids += [(c.get("attributes") or {}).get("owner", "") for c in other_clients]

    users: dict[str, UserState | None] = {}
    for employee_id in ids:
        key = employee_id.lower()
        if not key or key in users:
            continue
        user = kc.get_user_by_username(username_for(employee_id))
        if user is None:
            users[key] = None
            continue
        groups = {group["name"] for group in kc.user_groups(user["id"])}
        live = False
        if not user["enabled"]:
            live = bool(kc.user_sessions(user["id"]) or kc.consent_clients(user["id"]))
        users[key] = UserState(
            id=user["id"], enabled=user["enabled"], attributes=user.get("attributes", {}),
            groups=groups, name=f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
            live_access=live,
        )
    clients = {acct.client_id: kc.get_client_by_client_id(acct.client_id)
               for acct in service_accounts}
    payment_members = {
        name: {member["username"].lower() for member in kc.group_members(group_ids[name])}
        for name in (sod.PAYMENTS_INITIATE, sod.PAYMENTS_APPROVE) if name in group_ids
    }
    return State(users=users, clients=clients, group_ids=group_ids,
                 payment_members=payment_members, other_clients=other_clients)


def directory_overlap(feed: Feed, state: State) -> set[str]:
    """Usernames in BOTH payment groups right now who are not in the feed (the feed's own
    people are judged by their projected groups instead)."""
    both = (state.payment_members.get(sod.PAYMENTS_INITIATE, set())
            & state.payment_members.get(sod.PAYMENTS_APPROVE, set()))
    in_feed = {username_for(p.employee_id) for p in [*feed.joiners, *feed.movers, *feed.leavers]}
    return both - in_feed


# ---- planning -----------------------------------------------------------------------------

def _wanted_groups(roles_map: RolesMap, employee_id: str, department: str, job_title: str):
    try:
        return roles_map.groups_for(department, job_title)
    except EngineError as exc:
        raise EngineError(f"{employee_id}: {exc}") from None


def _person_attributes(person) -> dict[str, str]:
    return {
        "employee_id": person.employee_id,
        "department": person.department,
        "job_title": person.job_title,
        "manager_id": person.manager_id,
    }


def projected_groups(feed: Feed, roles_map: RolesMap, state: State) -> dict[str, set[str]]:
    """The groups each joiner and mover would have after the feed is applied: the groups the
    engine does not manage stay as they are, the managed ones become exactly what the map says."""
    result: dict[str, set[str]] = {}
    for person in [*feed.joiners, *feed.movers]:
        wanted = _wanted_groups(roles_map, person.employee_id, person.department,
                                person.job_title)
        user = state.user(person.employee_id)
        kept = (user.groups - roles_map.managed_groups) if user else set()
        result[person.employee_id] = kept | wanted
    return result


def _blocked_reasons(person, leaver_ids: set[str], users: dict) -> list[str]:
    """Why the proofing gate refuses this joiner or mover row (empty list: it passes)."""
    reasons = []
    if isinstance(person, Joiner):
        missing = [name for name in PROOFING_CHECKS if not getattr(person, name)]
        if missing:
            reasons.append("proofing incomplete - " + ", ".join(missing))
    reasons += sod.approval_problems(person, leaver_ids, users)
    return reasons


def _blocked_action(person, row: str, reasons: list[str]) -> Action:
    return Action(
        kind=BLOCKED, target=person.employee_id,
        summary=f"BLOCKED {row} {person.employee_id}: " + "; ".join(reasons),
        details={"row": row, "first_name": person.first_name, "last_name": person.last_name,
                 "department": person.department, "job_title": person.job_title,
                 "reasons": reasons},
    )


def _sod2_skip(person, row: str, groups: set[str]) -> Action | None:
    """SOD-2 fails closed: nothing at all is applied to this person."""
    if not sod.has_payment_conflict(groups):
        return None
    return Action(
        kind=SKIPPED, target=person.employee_id,
        summary=(f"SKIPPED {row} {person.employee_id}: SOD-2 would hold both "
                 f"{sod.PAYMENTS_INITIATE} and {sod.PAYMENTS_APPROVE}; nothing applied"),
    )


def _describe_groups(add: set[str], remove: set[str]) -> str:
    parts = [f"+{name}" for name in sorted(add)] + [f"-{name}" for name in sorted(remove)]
    return " ".join(parts)


def _plan_existing_user(person, user: UserState, wanted: set[str], roles_map: RolesMap,
                        extra_attributes: dict | None = None):
    """Compare an existing account with the feed. Returns a move_user action, or None."""
    wanted_attributes = {**_person_attributes(person), **(extra_attributes or {})}
    changed = {name: value for name, value in wanted_attributes.items()
               if user.attributes.get(name) != value}
    add = wanted - user.groups
    # Only managed groups are ever removed; any other group is left alone.
    remove = (user.groups & roles_map.managed_groups) - wanted
    if not (changed or add or remove):
        return None
    pieces = []
    if add or remove:
        pieces.append("groups " + _describe_groups(add, remove))
    if changed:
        pieces.append("attributes " + ", ".join(sorted(changed)))
    flag = PRIVILEGED_FLAG if add & PRIVILEGED_GROUPS else ""
    return Action(
        kind=MOVE_USER, target=person.employee_id,
        summary=f"{username_for(person.employee_id)}: " + "; ".join(pieces) + flag,
        details={"user_id": user.id, "attributes": changed,
                 "add": sorted(add), "remove": sorted(remove)},
    )


def plan(feed: Feed, service_accounts: list[ServiceAccount], roles_map: RolesMap,
         state: State, today: date) -> list[Action]:
    """Compare the feed with the current state. Returns what must change; changes nothing.

    The order matters because apply() works down the list and a later step can fail: access is
    SWITCHED OFF first (leavers, then service accounts without an owner), and only then are
    people moved, created and given anything new."""
    # Work out every person's wanted groups first, and stop early if one does not exist.
    wanted_by_person = {
        person.employee_id: _wanted_groups(roles_map, person.employee_id,
                                           person.department, person.job_title)
        for person in [*feed.joiners, *feed.movers]
    }
    missing = {name for groups in wanted_by_person.values() for name in groups
               if name not in state.group_ids}
    if missing:
        raise EngineError("group(s) not found in the realm: " + ", ".join(sorted(missing))
                          + " (run scripts/keycloak-dev.sh first)")

    projected = projected_groups(feed, roles_map, state)
    leaver_ids = sod.leaver_ids_of(feed)

    leaver_actions = _plan_leavers(feed, state, today)
    owner_disables: list[Action] = []   # service accounts switched off for SOD-3
    client_actions: list[Action] = []   # the other service-account lines
    for account in service_accounts:
        problem = sod.owner_problem(account.owner, leaver_ids, state.users)
        found = _plan_service_account(account, state.clients[account.client_id], today, problem)
        for action in found:
            is_disable = (action.kind == UPDATE_CLIENT and action.details.get("enabled") is False
                          and problem)
            (owner_disables if is_disable else client_actions).append(action)
    mover_actions = _plan_movers(feed, state, roles_map, wanted_by_person, projected, leaver_ids)
    joiner_actions = _plan_joiners(feed, state, roles_map, wanted_by_person, projected,
                                   leaver_ids, today)
    warning_actions = _plan_manager_warnings(feed, state, leaver_ids)
    return (leaver_actions + owner_disables + mover_actions + joiner_actions + client_actions
            + _bad_row_actions(feed, service_accounts) + warning_actions)


def bad_row_lines(feed: Feed, service_accounts) -> list[str]:
    """One 'BLOCKED row ...' line per malformed CSV row (the same text the plan shows)."""
    lines = []
    for bad in [*feed.bad_rows, *getattr(service_accounts, "bad_rows", [])]:
        kind = "row" if bad.source == "feed" else "service-account row"
        lines.append(f"BLOCKED {kind} {bad.line} {bad.who}: {bad.reason}")
    return lines


def _bad_row_actions(feed: Feed, service_accounts) -> list[Action]:
    """Malformed rows are reported and skipped; every other row still runs."""
    actions = []
    for bad in [*feed.bad_rows, *getattr(service_accounts, "bad_rows", [])]:
        kind = "row" if bad.source == "feed" else "service-account row"
        actions.append(Action(
            kind=BLOCKED, target=bad.who if bad.who != "?" else f"line {bad.line}",
            summary=f"BLOCKED {kind} {bad.line} {bad.who}: {bad.reason}",
            details={"row": "unreadable", "source": bad.source, "line": bad.line,
                     "who": bad.who, "reason": bad.reason},
        ))
    return actions


def _plan_leavers(feed: Feed, state: State, today: date) -> list[Action]:
    actions = []
    for leaver in feed.leavers:
        user = state.user(leaver.employee_id)
        if user is None:
            actions.append(Action(
                kind=SKIPPED, target=leaver.employee_id,
                summary=f"SKIPPED unknown user {leaver.employee_id}",
            ))
            continue
        left_on = leaver.end_date.isoformat()
        # Also redo the job if the account is off but a session or offline token still exists.
        if user.enabled or user.attributes.get("disabled_on") != left_on or user.live_access:
            actions.append(Action(
                kind=DISABLE_USER, target=leaver.employee_id,
                summary=(f"{username_for(leaver.employee_id)}: disable now "
                         f"({'leaves on' if leaver.end_date > today else 'left'} {left_on}); "
                         "groups kept as evidence"),
                details={"user_id": user.id, "attributes": {"disabled_on": left_on}},
            ))
    return actions


def _plan_movers(feed: Feed, state: State, roles_map: RolesMap, wanted_by_person: dict,
                 projected: dict, leaver_ids: set[str]) -> list[Action]:
    actions = []
    for mover in feed.movers:
        reasons = _blocked_reasons(mover, leaver_ids, state.users)
        if reasons:
            actions.append(_blocked_action(mover, "mover", reasons))
            continue
        user = state.user(mover.employee_id)
        if user is None:
            actions.append(Action(
                kind=SKIPPED, target=mover.employee_id,
                summary=f"SKIPPED unknown user {mover.employee_id}",
            ))
            continue
        skip = _sod2_skip(mover, "mover", projected[mover.employee_id])
        if skip:
            actions.append(skip)
            continue
        move = _plan_existing_user(mover, user, wanted_by_person[mover.employee_id], roles_map)
        if move:
            if not user.enabled:
                # Groups are still corrected (so the record stays accurate), but say so.
                move.summary += " (account disabled)"
            actions.append(move)
    return actions


def _plan_joiners(feed: Feed, state: State, roles_map: RolesMap, wanted_by_person: dict,
                  projected: dict, leaver_ids: set[str], today: date) -> list[Action]:
    actions = []
    for joiner in feed.joiners:
        reasons = _blocked_reasons(joiner, leaver_ids, state.users)
        if reasons:
            actions.append(_blocked_action(joiner, "joiner", reasons))
            continue
        skip = _sod2_skip(joiner, "joiner", projected[joiner.employee_id])
        if skip:
            actions.append(skip)
            continue
        user = state.user(joiner.employee_id)
        wanted = wanted_by_person[joiner.employee_id]
        starts = joiner.start_date.isoformat()
        if user is None:
            # A joiner whose first day is still ahead is created DISABLED, with the marker.
            waiting = joiner.start_date > today
            attributes = _person_attributes(joiner)
            if waiting:
                attributes[PENDING_START] = starts
            state_text = f"create DISABLED until {starts}" if waiting else "create enabled"
            actions.append(Action(
                kind=CREATE_USER, target=joiner.employee_id,
                summary=(f"{username_for(joiner.employee_id)}: {state_text}; "
                         f"groups {', '.join(sorted(wanted)) or '(none)'}"
                         + (PRIVILEGED_FLAG if wanted & PRIVILEGED_GROUPS else "")),
                details={
                    "username": username_for(joiner.employee_id),
                    "email": joiner.email, "first_name": joiner.first_name,
                    "last_name": joiner.last_name, "enabled": not waiting,
                    "attributes": attributes, "groups": sorted(wanted),
                },
            ))
            continue
        waiting_for_start = (not user.enabled) and PENDING_START in user.attributes
        if not user.enabled and not waiting_for_start:
            # Disabled by someone else: never switched back on by the engine. But make sure the
            # account really is dead (no session or offline token left). No marker is written,
            # so it stays "disabled by a person" and is not enabled at the start date.
            if user.live_access:
                actions.append(Action(
                    kind=END_SESSIONS, target=joiner.employee_id,
                    summary=f"SKIPPED joiner {joiner.employee_id}: account is disabled, needs "
                            "review (sessions ended)",
                    details={"user_id": user.id},
                ))
            else:
                actions.append(Action(
                    kind=SKIPPED, target=joiner.employee_id,
                    summary=f"SKIPPED joiner {joiner.employee_id}: account exists but is "
                            "disabled (needs review before a re-hire)",
                ))
            continue
        if user.enabled and joiner.start_date > today:
            # Already enabled although the first day is still ahead: switch off until then.
            actions.append(Action(
                kind=DISABLE_USER, target=joiner.employee_id,
                summary=f"{username_for(joiner.employee_id)}: disable until start {starts}",
                details={"user_id": user.id, "attributes": {PENDING_START: starts}},
            ))
        extra = None
        if waiting_for_start:
            if joiner.start_date <= today:
                when = "starts today" if joiner.start_date == today else f"started {starts}"
                actions.append(Action(
                    kind=ENABLE_USER, target=joiner.employee_id,
                    summary=f"{username_for(joiner.employee_id)}: enable ({when})",
                    details={"user_id": user.id, "remove_attributes": [PENDING_START]},
                ))
            else:
                extra = {PENDING_START: starts}  # the start date may have moved in the feed
        # The account already exists (for example a half-finished earlier run): fix drift.
        move = _plan_existing_user(joiner, user, wanted, roles_map, extra)
        if move:
            actions.append(move)
    return actions


def _plan_manager_warnings(feed: Feed, state: State, leaver_ids: set[str]) -> list[Action]:
    """Staff whose manager has left, is disabled, has not started or cannot be found."""
    actions = []
    for person in [*feed.joiners, *feed.movers]:
        status = sod.person_status(person.manager_id, leaver_ids, state.users)
        if status == "active":
            continue
        what = {sod.LEFT: "has left", sod.DISABLED: "has left", sod.PENDING: "has not started yet",
                sod.UNKNOWN: "not found"}[status]
        actions.append(Action(
            kind=WARNING, target=person.employee_id,
            summary=(f"WARNING manager {what} - reassign {person.employee_id} "
                     f"(manager {person.manager_id})"),
            details={"manager_id": person.manager_id, "status": status},
        ))
    return actions


def _plan_service_account(account: ServiceAccount, client: dict | None, today: date,
                          owner_problem: str | None = None) -> list[Action]:
    """An account whose expiry date has passed is created or switched to disabled. A client that
    is already disabled is never switched back on by the engine.

    owner_problem (SOD-3): when set, the account has no active owner. It is then never created,
    and an existing enabled one is disabled (with a marker saying the engine did it)."""
    if owner_problem:
        reason = f"SOD-3: {owner_problem}"
        if client is None:
            return [Action(kind=BLOCKED, target=account.client_id,
                           summary=f"BLOCKED service account {account.client_id}: {reason}; "
                                   "not created")]
        if client["enabled"]:
            return [Action(
                kind=UPDATE_CLIENT, target=account.client_id,
                summary=f"{account.client_id}: disable ({reason}); stays off until someone "
                        "takes ownership",
                details={"client_uuid": client["id"], "enabled": False,
                         "attributes": {DISABLED_FOR_SOD3: "SOD-3 no active owner"}},
            )]
        return [Action(
            kind=SKIPPED, target=account.client_id,
            summary=f"SKIPPED already disabled {account.client_id} ({reason}; not re-enabled)",
        )]
    expired = account.expires_on < today
    enabled = not expired
    attributes = {"owner": account.owner, "purpose": account.purpose,
                  "expires_on": account.expires_on.isoformat()}
    note = f"expired on {account.expires_on.isoformat()}" if expired else "enabled"
    if client is None:
        return [Action(
            kind=CREATE_CLIENT, target=account.client_id,
            summary=(f"{account.client_id}: create {'DISABLED, ' if expired else ''}{note}; "
                     f"owner {account.owner}"),
            details={"enabled": enabled, "attributes": attributes},
        )]
    current = client.get("attributes", {})
    changed = {name: value for name, value in attributes.items() if current.get(name) != value}
    if not client["enabled"] and enabled:
        # Never switch a disabled client back on: it may have been disabled on purpose (by an
        # administrator, or by this engine when it expired). Turning it on again is a human
        # decision. Owner, purpose and expiry from the CSV are still kept up to date.
        report = Action(
            kind=SKIPPED, target=account.client_id,
            summary=f"SKIPPED already disabled {account.client_id} (not re-enabled)",
        )
        if not changed:
            return [report]
        update = Action(
            kind=UPDATE_CLIENT, target=account.client_id,
            summary=f"update attributes (stays disabled) {account.client_id}",
            details={"client_uuid": client["id"], "enabled": None, "attributes": changed},
        )
        return [update, report]
    if client["enabled"] == enabled and not changed:
        return []
    pieces = []
    if client["enabled"] != enabled:
        pieces.append(f"enabled -> {str(enabled).lower()} ({note})")
    if changed:
        pieces.append("attributes " + ", ".join(sorted(changed)))
    return [Action(
        kind=UPDATE_CLIENT, target=account.client_id,
        summary=f"{account.client_id}: " + "; ".join(pieces),
        details={"client_uuid": client["id"],
                 "enabled": enabled if client["enabled"] != enabled else None,
                 "attributes": changed},
    )]


# ---- applying -----------------------------------------------------------------------------

class ApplyResult(Counter):
    """How many actions of each kind were done, plus the ones that failed."""

    def __init__(self):
        super().__init__()
        self.failures: list[tuple[str, str, str]] = []   # (kind, target, safe error message)


def apply(actions: list[Action], kc) -> ApplyResult:
    """Carry out the actions in order. A Keycloak error on one action is recorded and the rest
    still run (so a failed create cannot stop a leaver being switched off). Skips, blocks and
    warnings are only reports and are not counted."""
    done = ApplyResult()
    group_ids = {group["name"]: group["id"] for group in kc.list_groups()}
    for action in actions:
        try:
            if _carry_out(action, kc, group_ids):
                done[action.kind] += 1
        except KeycloakError as exc:   # the message holds method, status and path, never a body
            done.failures.append((action.kind, action.target, str(exc)))
    return done


def _carry_out(action: Action, kc, group_ids: dict[str, str]) -> bool:
    """Do one action. Returns False for report-only lines."""
    d = action.details
    if action.kind == CREATE_USER:
        user_id = kc.create_user(
            d["username"], email=d["email"], first_name=d["first_name"],
            last_name=d["last_name"], enabled=d["enabled"], attributes=d["attributes"],
        )
        for name in d["groups"]:
            kc.add_user_to_group(user_id, group_ids[name])
    elif action.kind == MOVE_USER:
        if d["attributes"]:
            kc.update_user(d["user_id"], attributes=d["attributes"])
        for name in d["add"]:
            kc.add_user_to_group(d["user_id"], group_ids[name])
        for name in d["remove"]:
            kc.remove_user_from_group(d["user_id"], group_ids[name])
    elif action.kind == ENABLE_USER:
        kc.update_user(d["user_id"], enabled=True, remove_attributes=d["remove_attributes"])
    elif action.kind == DISABLE_USER:
        # Switch the account off, then end every session and offline token (disabling alone
        # leaves them in place, and they work again if the account is ever re-enabled).
        # The marker attribute is written LAST: if a step fails, the marker is missing, so
        # the next plan sees unfinished work and does all the steps again.
        kc.update_user(d["user_id"], enabled=False)
        kc.end_user_sessions(d["user_id"])
        kc.revoke_offline_tokens(d["user_id"])
        kc.update_user(d["user_id"], attributes=d["attributes"])
    elif action.kind == END_SESSIONS:
        kc.end_user_sessions(d["user_id"])
        kc.revoke_offline_tokens(d["user_id"])
    elif action.kind == CREATE_CLIENT:
        kc.create_client(action.target, enabled=d["enabled"], attributes=d["attributes"])
    elif action.kind == UPDATE_CLIENT:
        kc.update_client(d["client_uuid"], enabled=d["enabled"], attributes=d["attributes"])
    else:
        return False  # SKIPPED, BLOCKED and WARNING lines are only reports
    return True


# ---- printing -----------------------------------------------------------------------------

KIND_ORDER = [CREATE_USER, MOVE_USER, ENABLE_USER, DISABLE_USER, END_SESSIONS, CREATE_CLIENT,
              UPDATE_CLIENT, BLOCKED, SKIPPED, WARNING]


def format_plan(actions: list[Action]) -> str:
    """The plan as a text table, followed by one summary line."""
    if not actions:
        return "Plan: nothing to do - Keycloak already matches the feed."
    width = max(len(action.kind) for action in actions)
    lines = [f"{'ACTION'.ljust(width)}  {'TARGET'.ljust(22)}  DETAIL"]
    for action in actions:
        lines.append(f"{action.kind.ljust(width)}  {action.target.ljust(22)}  {action.summary}")
    counts = Counter(action.kind for action in actions)
    lines.append("Plan: " + ", ".join(f"{counts[kind]} {kind}" for kind in KIND_ORDER
                                      if counts[kind]))
    return "\n".join(lines)


def format_applied(done: Counter) -> str:
    """"Applied: create_user=6, ..." in a fixed order, or a line saying nothing changed."""
    if not done:
        return "Applied 0 changes."
    return "Applied: " + ", ".join(f"{kind}={done[kind]}" for kind in KIND_ORDER if done[kind])
