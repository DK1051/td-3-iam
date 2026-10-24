"""Separation-of-duties (SoD) rules: the three checks named in sod-rules.yaml.

This module never talks to Keycloak. The engine hands it what the directory would look like once
the feed has been applied ("projected state"), so a conflict is reported before `apply`.

  SOD-1  requester and approver differ          (checked on the feed: joiner and mover rows)
  SOD-2  nobody holds payments-initiate and payments-approve together   (projected groups)
  SOD-3  every service account has an owner who is a current, enabled employee

Leaver rows are not checked: switching access off is always allowed, because holding it back
would keep the access alive.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from lifecycle.feed import Feed, ServiceAccount

PAYMENTS_INITIATE = "payments-initiate"
PAYMENTS_APPROVE = "payments-approve"

# What an owner or manager can be: "active", or one of these problems.
LEFT, DISABLED, UNKNOWN, PENDING = "left", "disabled", "unknown", "pending"
PROBLEM_TEXT = {
    LEFT: "has left",
    DISABLED: "is disabled",
    UNKNOWN: "is not in the directory",
    PENDING: "has not started yet",
}


class SodError(Exception):
    """sod-rules.yaml is not the file the program expects."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    plain_english: str
    check: str


@dataclass(frozen=True)
class Violation:
    rule_id: str
    subject: str    # employee id or service-account client id
    reason: str     # plain English


# ---- small building blocks (also used by the engine) --------------------------------------

def requester_equals_approver(person) -> bool:
    return person.requested_by.lower() == person.approved_by.lower()


def has_payment_conflict(groups: set[str]) -> bool:
    return PAYMENTS_INITIATE in groups and PAYMENTS_APPROVE in groups


def person_status(employee_id: str, leaver_ids: set[str], users: dict) -> str:
    """Is this employee a current, enabled person? `users` maps lower-case employee id to the
    account state (or None). Someone leaving in this feed counts as already gone."""
    key = employee_id.lower()
    if key in leaver_ids:
        return LEFT
    user = users.get(key)
    if user is None:
        return UNKNOWN
    if not user.enabled:
        return PENDING if "pending_start" in user.attributes else DISABLED
    return "active"


def leaver_ids_of(feed: Feed) -> set[str]:
    return {leaver.employee_id.lower() for leaver in feed.leavers}


def owner_problem(owner: str, leaver_ids: set[str], users: dict) -> str | None:
    """None when the owner is fine, otherwise a plain-English reason."""
    if owner == "":
        return "has no owner"
    status = person_status(owner, leaver_ids, users)
    return None if status == "active" else f"owner {owner} {PROBLEM_TEXT[status]}"


# ---- the rules file -----------------------------------------------------------------------

CHECKS = ("requester-not-approver", "no-initiate-and-approve", "service-account-has-active-owner")
EXPECTED_IDS = ["SOD-1", "SOD-2", "SOD-3"]


def load_rules(path: str | Path) -> list[Rule]:
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    try:
        rules = [Rule(id=r["id"], title=r["title"], plain_english=" ".join(r["plain_english"].split()),
                      check=r["check"]) for r in data["rules"]]
    except (TypeError, KeyError, AttributeError):
        raise SodError("sod-rules.yaml: every rule needs id, title, plain_english and check") from None
    if [rule.id for rule in rules] != EXPECTED_IDS:
        raise SodError("sod-rules.yaml must contain exactly the rules SOD-1, SOD-2, SOD-3")
    unknown = [rule.check for rule in rules if rule.check not in CHECKS]
    if unknown:
        raise SodError(f"sod-rules.yaml: unknown check {unknown[0]}")
    return rules


# ---- evaluating ---------------------------------------------------------------------------

def evaluate(rules: list[Rule], feed: Feed, service_accounts: list[ServiceAccount],
             projected_groups: dict[str, set[str]], users: dict) -> list[Violation]:
    """Return every violation. `projected_groups` maps employee id to the groups the person
    would have after the feed is applied; `users` is the directory state (see person_status)."""
    violations: list[Violation] = []
    leavers = leaver_ids_of(feed)
    for rule in rules:
        if rule.check == "requester-not-approver":
            for person in [*feed.joiners, *feed.movers]:
                if requester_equals_approver(person):
                    violations.append(Violation(
                        rule.id, person.employee_id,
                        f"requested and approved by the same person ({person.requested_by})"))
        elif rule.check == "no-initiate-and-approve":
            for person in [*feed.joiners, *feed.movers]:
                if has_payment_conflict(projected_groups[person.employee_id]):
                    violations.append(Violation(
                        rule.id, person.employee_id,
                        f"would be in both {PAYMENTS_INITIATE} and {PAYMENTS_APPROVE}"))
        else:
            for account in service_accounts:
                problem = owner_problem(account.owner, leavers, users)
                if problem:
                    violations.append(Violation(rule.id, account.client_id,
                                                f"service account {problem}"))
    return violations
