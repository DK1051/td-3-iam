"""Approve one proposal: the only place where the Agent Passport changes the directory.

Usage:  MANAGER_TOKEN=<manager access token> python scripts/approve.py <proposal-id>

A proposal (written by the MCP server when the AI assistant calls propose_change) changes nothing
by itself. A human manager runs this script. It re-checks everything instead of trusting the
proposal file (DESIGN.md section 6), in this order:

  1. MANAGER_TOKEN is set                                         else exit 2
  2. the token is valid for audience "approve-cli" (same verifier class as the server)  else exit 3
  3. the token's realm roles include "manager"                    else exit 3
  4. the proposal exists, is still "pending", and matches pending.json       else exit 4
  5. separation-of-duties (SoD) rules from 3H's lifecycle.sod hold            else exit 5
  6. apply with the 3H Keycloak client; a Keycloak error part-way -> "partial", exit 6

Checks 1-5 change nothing. Step 6 audits each group it adds, so a partial apply is visible.
Known limit: two people approving the same proposal at the same moment are not locked against
each other (check, then write); fine for a one-person demo.

Settings: KC_URL, KC_ADMIN_USER, KC_ADMIN_PASSWORD (3H client), AGENT_PASSPORT_* (see server.py).
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PASSPORT_DIR = HERE.parent
for _path in (PASSPORT_DIR, PASSPORT_DIR.parent / "3h-lifecycle"):  # so it runs from anywhere
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

from audit import AuditLog
from lifecycle import sod
from lifecycle.kc import KeycloakClient, KeycloakError
from server import (
    REALM,
    Settings,
    TokenRejected,
    _atomic_write_json,
    load_requests,
    make_verifier,
    managed_groups,
)

# TODO(verify): the audience mapper in keycloak-agent.sh really puts "approve-cli" into aud of a
# password-grant token for the public client approve-cli (checked by the integration test).
APPROVE_AUDIENCE = "approve-cli"
TOOL = "approve.py"
EXIT_OK, EXIT_NO_TOKEN, EXIT_DENIED, EXIT_BAD_PROPOSAL, EXIT_SOD, EXIT_PARTIAL = 0, 2, 3, 4, 5, 6


class Stop(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(proposal_id: str, *, token: str | None, settings: Settings, verifier, kc,
        allowed_groups: set[str]) -> int:
    """Do the whole approval. Returns the exit code; prints short messages (never token text)."""
    audit = AuditLog(settings.audit_file)
    caller: dict = {"client_id": None, "subject": None}
    try:
        claims = _check_token(token, verifier, caller)
        proposal, path, request = _load_proposal(proposal_id, settings)
        user, group_ids, current = _check_sod(proposal, request, claims, kc, allowed_groups)
    except Stop as stop:
        audit.record(tool=TOOL, decision="deny", reason=stop.reason, args={"proposal_id": proposal_id},
                     client_id=caller["client_id"], subject=caller["subject"])
        print(f"refused: {stop.reason}", file=sys.stderr)
        return stop.code
    except KeycloakError as exc:  # reading the directory failed; nothing has been changed yet
        audit.record(tool=TOOL, decision="deny", reason="directory unreachable",
                     args={"proposal_id": proposal_id},
                     client_id=caller["client_id"], subject=caller["subject"])
        print(f"directory error, nothing changed: {exc}", file=sys.stderr)
        return EXIT_PARTIAL

    return _apply(proposal, path, user, group_ids, current, claims, caller, audit, kc)


def _check_token(token: str | None, verifier, caller: dict) -> dict:
    if not token:
        raise Stop(EXIT_NO_TOKEN, "MANAGER_TOKEN is not set")
    try:
        access = asyncio.run(verifier.verify(token))
    except TokenRejected as exc:
        raise Stop(EXIT_DENIED, f"token rejected: {exc}") from None
    except Exception:  # noqa: BLE001 - any failure while checking a token is a refusal
        raise Stop(EXIT_DENIED, "token rejected: token check failed") from None
    caller.update(client_id=access.client_id, subject=access.subject)
    claims = access.claims or {}
    # TODO(verify): Keycloak lists realm roles under realm_access.roles in an access token.
    roles = (claims.get("realm_access") or {}).get("roles") or []
    if "manager" not in roles:
        raise Stop(EXIT_DENIED, "token lacks the manager role")
    return claims


def _load_proposal(proposal_id: str, settings: Settings) -> tuple[dict, Path, dict]:
    try:
        parsed = uuid.UUID(proposal_id)
    except (ValueError, AttributeError):
        raise Stop(EXIT_BAD_PROPOSAL, "proposal id is not a UUID") from None
    if str(parsed) != proposal_id.lower():  # only the plain form: no braces, urn: prefix, ../
        raise Stop(EXIT_BAD_PROPOSAL, "proposal id is not a UUID")
    path = Path(settings.proposals_dir) / f"{parsed}.json"
    try:
        proposal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Stop(EXIT_BAD_PROPOSAL, "proposal not found or unreadable") from None
    if not isinstance(proposal, dict) or proposal.get("id") != str(parsed):
        raise Stop(EXIT_BAD_PROPOSAL, "proposal file does not match its id")
    if proposal.get("status") != "pending":
        raise Stop(EXIT_BAD_PROPOSAL, "proposal is not pending")
    # The proposal file is not trusted on its own: compare it with the request in pending.json.
    try:
        requests = load_requests(settings.requests_file)
    except Exception:  # noqa: BLE001 - load_requests raises only Denied; refuse on anything
        raise Stop(EXIT_BAD_PROPOSAL, "requests file unavailable") from None
    request = next((r for r in requests if r.get("id") == proposal.get("request_id")), None)
    if request is None:
        raise Stop(EXIT_BAD_PROPOSAL, "request not in pending.json")
    if proposal.get("requester") != request.get("requester"):
        raise Stop(EXIT_BAD_PROPOSAL, "requester differs from pending.json")
    groups = proposal.get("proposed_groups")
    # Interpretation of "groups match": the proposal may only ask for groups the request named.
    if (not isinstance(groups, list) or not groups or not all(isinstance(g, str) for g in groups)
            or not set(groups) <= set(request.get("requested_groups", []))):
        raise Stop(EXIT_BAD_PROPOSAL, "groups differ from pending.json")
    return proposal, path, request


def _check_sod(proposal: dict, request: dict, claims: dict, kc, allowed_groups: set[str]):
    """Return (requester's directory record, {group name: group id}, the requester's current
    group names) or raise Stop(EXIT_SOD)."""
    # TODO(verify): preferred_username is in a password-grant access token (profile scope).
    approver = claims.get("preferred_username")
    if not isinstance(approver, str) or not approver:
        raise Stop(EXIT_SOD, "token has no preferred_username")  # fail closed (design step 5)
    approver = approver.lower()
    requester = request["requester"].lower()
    groups = proposal["proposed_groups"]
    # SOD-1: nobody approves their own access.
    pair = SimpleNamespace(requested_by=requester, approved_by=approver)
    if sod.requester_equals_approver(pair):
        raise Stop(EXIT_SOD, "SOD-1: approver is the requester")
    outside = [g for g in groups if g not in allowed_groups]
    if outside:
        raise Stop(EXIT_SOD, "a proposed group is not managed by 3H")

    user = kc.get_user_by_username(requester)
    users = {requester: SimpleNamespace(enabled=user["enabled"], attributes=user["attributes"])
             } if user else {}
    status = sod.person_status(requester, set(), users)
    if status != "active":
        raise Stop(EXIT_SOD, f"requester {sod.PROBLEM_TEXT[status]}")

    directory_groups = {g["name"]: g["id"] for g in kc.list_groups()}
    if any(g not in directory_groups for g in groups):
        raise Stop(EXIT_SOD, "a proposed group is not in the directory")
    current = {g["name"] for g in kc.user_groups(user["id"])}
    # SOD-2: nobody holds payments-initiate and payments-approve together.
    if sod.has_payment_conflict(current | set(groups)):
        raise Stop(EXIT_SOD, "SOD-2: would hold payments-initiate and payments-approve together")
    return user, {name: directory_groups[name] for name in groups}, current


def _apply(proposal: dict, path: Path, user: dict, group_ids: dict[str, str], current: set[str],
           claims: dict, caller: dict, audit: AuditLog, kc) -> int:
    base_args = {"proposal_id": proposal["id"]}
    added: list[str] = []
    for name, group_id in group_ids.items():
        if name in current:
            continue
        try:
            kc.add_user_to_group(user["id"], group_id)
        except KeycloakError as exc:
            audit.record(tool=TOOL, decision="deny", reason=f"keycloak error while adding {name}",
                         args={**base_args, "group": name}, **_who(caller))
            _atomic_write_json(path, {**proposal, "status": "partial", "applied_groups": added,
                                      "failed_at": _now()})
            print(f"PARTIAL: added {added or 'nothing'}, then Keycloak failed: {exc}",
                  file=sys.stderr)
            return EXIT_PARTIAL
        added.append(name)
        audit.record(tool=TOOL, decision="allow", reason=f"added to group {name}",
                     args={**base_args, "group": name}, **_who(caller))
    _atomic_write_json(path, {
        **proposal, "status": "approved", "applied_groups": added,
        "approved_by": {"subject": claims["sub"], "username": claims["preferred_username"]},
        "approved_at": _now(),
    })
    audit.record(tool=TOOL, decision="allow", reason="proposal approved", args=base_args,
                 **_who(caller))
    print(f"approved {proposal['id']}: added {', '.join(added) or 'no new groups'}")
    return EXIT_OK


def _who(caller: dict) -> dict:
    return {"client_id": caller["client_id"], "subject": caller["subject"]}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: MANAGER_TOKEN=... python scripts/approve.py <proposal-id>", file=sys.stderr)
        return EXIT_BAD_PROPOSAL
    settings = Settings()
    return run(
        argv[1], token=os.environ.get("MANAGER_TOKEN"), settings=settings,
        verifier=make_verifier(settings, audience=APPROVE_AUDIENCE),
        kc=KeycloakClient(REALM), allowed_groups=managed_groups(),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
