"""The 3H engine: work out what must change in Keycloak, then change it.

Two separate steps, so that nothing changes by accident:
  1. read_state() looks at Keycloak (read-only) and plan() compares it with the HR feed. plan()
     is a plain function: it returns a list of Actions and touches nothing.
  2. apply() carries the actions out.

The engine is idempotent (safe to repeat): plan() only produces an action when Keycloak differs
from the feed, so once apply() has run, a second plan() returns an empty list.

Leavers are disabled, never deleted. There is no delete-user call anywhere in this program.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from lifecycle.feed import Feed, ServiceAccount

# The kinds of action. SKIPPED is only a report line: apply() never carries it out.
CREATE_USER = "create_user"
MOVE_USER = "move_user"
DISABLE_USER = "disable_user"
ENABLE_USER = "enable_user"
CREATE_CLIENT = "create_client"
UPDATE_CLIENT = "update_client"
SKIPPED = "skipped"


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
    return roles_map


# ---- reading the current state ------------------------------------------------------------

@dataclass
class UserState:
    id: str
    enabled: bool
    attributes: dict[str, str]
    groups: set[str]


@dataclass
class State:
    users: dict[str, UserState | None]   # key: employee id; None means "no such account"
    clients: dict[str, dict | None]      # key: client id; None means "no such client"
    group_ids: dict[str, str]            # group name -> group id


def username_for(employee_id: str) -> str:
    """The Keycloak username is the employee id (lower case): it never changes if a name does."""
    return employee_id.lower()


def read_state(kc, feed: Feed, service_accounts: list[ServiceAccount]) -> State:
    """Look up (read-only) everything in Keycloak that the feed talks about."""
    group_ids = {group["name"]: group["id"] for group in kc.list_groups()}
    users: dict[str, UserState | None] = {}
    for person in [*feed.joiners, *feed.movers, *feed.leavers]:
        user = kc.get_user_by_username(username_for(person.employee_id))
        if user is None:
            users[person.employee_id] = None
            continue
        groups = {group["name"] for group in kc.user_groups(user["id"])}
        users[person.employee_id] = UserState(
            id=user["id"], enabled=user["enabled"],
            attributes=user.get("attributes", {}), groups=groups,
        )
    clients = {acct.client_id: kc.get_client_by_client_id(acct.client_id)
               for acct in service_accounts}
    return State(users=users, clients=clients, group_ids=group_ids)


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
    """Compare the feed with the current state. Returns what must change; changes nothing."""
    actions: list[Action] = []

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

    for joiner in feed.joiners:
        user = state.users[joiner.employee_id]
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
            actions.append(Action(
                kind=SKIPPED, target=joiner.employee_id,
                summary=f"SKIPPED joiner {joiner.employee_id}: account exists but is disabled "
                        "(a re-hire needs a person to review it)",
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

    for mover in feed.movers:
        user = state.users[mover.employee_id]
        if user is None:
            actions.append(Action(
                kind=SKIPPED, target=mover.employee_id,
                summary=f"SKIPPED unknown user {mover.employee_id}",
            ))
            continue
        move = _plan_existing_user(mover, user, wanted_by_person[mover.employee_id], roles_map)
        if move:
            if not user.enabled:
                # Groups are still corrected (so the record stays accurate), but say so.
                move.summary += " (account disabled)"
            actions.append(move)

    for leaver in feed.leavers:
        user = state.users[leaver.employee_id]
        if user is None:
            actions.append(Action(
                kind=SKIPPED, target=leaver.employee_id,
                summary=f"SKIPPED unknown user {leaver.employee_id}",
            ))
            continue
        left_on = leaver.end_date.isoformat()
        if user.enabled or user.attributes.get("disabled_on") != left_on:
            actions.append(Action(
                kind=DISABLE_USER, target=leaver.employee_id,
                summary=(f"{username_for(leaver.employee_id)}: disable now "
                         f"({'leaves on' if leaver.end_date > today else 'left'} {left_on}); "
                         "groups kept as evidence"),
                details={"user_id": user.id, "attributes": {"disabled_on": left_on}},
            ))

    for account in service_accounts:
        actions.extend(_plan_service_account(account, state.clients[account.client_id], today))
    return actions


def _plan_service_account(account: ServiceAccount, client: dict | None,
                          today: date) -> list[Action]:
    """An account whose expiry date has passed is created or switched to disabled. A client that
    is already disabled is never switched back on by the engine."""
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

def apply(actions: list[Action], kc) -> Counter:
    """Carry out the actions. Returns how many of each kind were done (skips are not counted)."""
    done: Counter = Counter()
    group_ids = {group["name"]: group["id"] for group in kc.list_groups()}
    for action in actions:
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
            kc.update_user(d["user_id"], enabled=False, attributes=d["attributes"])
        elif action.kind == CREATE_CLIENT:
            kc.create_client(action.target, enabled=d["enabled"], attributes=d["attributes"])
        elif action.kind == UPDATE_CLIENT:
            kc.update_client(d["client_uuid"], enabled=d["enabled"], attributes=d["attributes"])
        else:
            continue  # SKIPPED lines are only reports
        done[action.kind] += 1
    return done


# ---- printing -----------------------------------------------------------------------------

def format_plan(actions: list[Action]) -> str:
    """The plan as a text table, followed by one summary line."""
    if not actions:
        return "Plan: nothing to do - Keycloak already matches the feed."
    width = max(len(action.kind) for action in actions)
    lines = [f"{'ACTION'.ljust(width)}  {'TARGET'.ljust(22)}  DETAIL"]
    for action in actions:
        lines.append(f"{action.kind.ljust(width)}  {action.target.ljust(22)}  {action.summary}")
    counts = Counter(action.kind for action in actions)
    lines.append("Plan: " + ", ".join(f"{count} {kind}" for kind, count in counts.items()))
    return "\n".join(lines)
