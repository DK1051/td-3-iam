"""Quarterly attestation: one Markdown file per manager listing everything they answer for.

A manager ticks "keep" or "revoke" for each person and service account. The engine never acts
on those ticks by itself; a person reads them and makes the change (acting on a "revoke"
automatically would need a signed approval, which is outside this project).

Files written to the output folder:
  <manager_id>.md   one per manager in the feed (and per active service-account owner)
  unassigned.md     staff whose manager has left / is disabled / not found, and service
                    accounts with no active owner: nobody can attest these until reassigned
"""

import re
from datetime import date
from pathlib import Path

from lifecycle import sod
from lifecycle.engine import State, UserState
from lifecycle.expiry import expiry_flag
from lifecycle.feed import Feed, ServiceAccount
from lifecycle.mdtext import cell

BOXES = "[ ] keep  [ ] revoke"
QUARTER_PATTERN = re.compile(r"\d{4}-Q[1-4]")
HEADINGS = ("# Access attestation", "# Unassigned")   # first lines of the files we write


class AttestError(Exception):
    """The attestation could not be built (for example a malformed quarter)."""


def check_quarter(quarter: str) -> str:
    if not QUARTER_PATTERN.fullmatch(quarter):
        raise AttestError(f"--quarter must look like 2026-Q4, not '{quarter}'")
    return quarter


def _enabled_text(user: UserState | None) -> str:
    if user is None:
        return "no account"
    if user.enabled:
        return "yes"
    if "pending_start" in user.attributes:
        return f"no (starts {user.attributes['pending_start']})"
    if "disabled_on" in user.attributes:
        return f"no (disabled {user.attributes['disabled_on']})"
    return "no (disabled)"


def _people_rows(people, state: State) -> tuple[list[str], list[str]]:
    """Table rows for people, and warnings about them."""
    rows, warnings = [], []
    for person in sorted(people, key=lambda p: p.employee_id):
        user = state.user(person.employee_id)
        title = user.attributes.get("job_title", "") if user else getattr(person, "job_title", "")
        groups = ", ".join(sorted(user.groups)) if user and user.groups else "-"
        rows.append(f"| {cell(person.employee_id)} | "
                    f"{cell(person.first_name)} {cell(person.last_name)} | {cell(title)} | "
                    f"{cell(groups)} | {_enabled_text(user)} | {BOXES} |")
        if user is None:
            warnings.append(f"{person.employee_id} has no account in the directory "
                            "(blocked by a control, or not created yet)")
    return rows, warnings


def _account_rows(accounts: list[ServiceAccount], state: State, today: date):
    rows, warnings = [], []
    for account in sorted(accounts, key=lambda a: a.client_id):
        client = state.clients.get(account.client_id)
        status = "not created" if client is None else ("enabled" if client["enabled"]
                                                       else "disabled")
        flag = expiry_flag(account.expires_on, today)
        shown = f"{status}, {flag}" if flag else status
        rows.append(f"| {cell(account.client_id)} | {cell(account.purpose)} | "
                    f"{account.expires_on.isoformat()} | {shown} | {BOXES} |")
        if flag:
            warnings.append(f"{account.client_id}: {flag} (expires_on "
                            f"{account.expires_on.isoformat()})")
    return rows, warnings


def _table(header: str, rows: list[str], empty: str) -> list[str]:
    if not rows:
        return [empty, ""]
    columns = header.count("|") - 1
    return [header, "|" + "---|" * columns, *rows, ""]


def build_attestation(feed: Feed, service_accounts: list[ServiceAccount], state: State,
                      quarter: str, today: date) -> dict[str, str]:
    """Returns {file name: Markdown text}. Pure: reads nothing, writes nothing."""
    quarter = check_quarter(quarter)
    leavers = sod.leaver_ids_of(feed)
    people = [*feed.joiners, *feed.movers, *feed.leavers]

    reports: dict[str, list] = {}       # manager id (lower case) -> direct reports
    spelling: dict[str, str] = {}
    for person in people:
        if person.manager_id:
            key = person.manager_id.lower()
            reports.setdefault(key, []).append(person)
            spelling.setdefault(key, person.manager_id)

    owned: dict[str, list[ServiceAccount]] = {}
    unowned_accounts: list[tuple[ServiceAccount, str]] = []
    for account in service_accounts:
        problem = sod.owner_problem(account.owner, leavers, state.users)
        if problem:
            unowned_accounts.append((account, problem))
        else:
            owned.setdefault(account.owner.lower(), []).append(account)
            spelling.setdefault(account.owner.lower(), account.owner)

    files: dict[str, str] = {}
    unassigned_staff: list[tuple[object, str, str]] = []
    for key in sorted(set(reports) | set(owned)):
        status = sod.person_status(spelling[key], leavers, state.users)
        manager_id = spelling[key]
        if status != "active":
            for person in reports.get(key, []):
                unassigned_staff.append((person, sod.MANAGER_TEXT[status], manager_id))
            continue
        manager = state.user(manager_id)
        name = manager.name if manager and manager.name else manager_id
        people_rows, warnings = _people_rows(reports.get(key, []), state)
        account_rows, account_warnings = _account_rows(owned.get(key, []), state, today)
        lines = [
            f"# Access attestation - {name} ({manager_id})",
            "",
            f"- Manager: {name} ({manager_id})",
            f"- Quarter: {quarter}",
            f"- Generated: {today.isoformat()}",
            "",
            ("Tick **keep** or **revoke** on every line. Nothing is changed automatically: "
             "a person reads your answers and acts on them."),
            "",
            "## Direct reports",
            "",
            *_table("| Employee | Name | Job title | Groups | Enabled? | Decision |", people_rows,
                    "You have no direct reports in this quarter's feed."),
            "## Service accounts you own",
            "",
            *_table("| Client id | Purpose | Expires on | Status | Decision |", account_rows,
                    "You own no service accounts."),
            "## Warnings",
            "",
            *([f"- {w}" for w in [*account_warnings, *warnings]] or ["- None."]),
            "",
        ]
        files[f"{manager_id}.md"] = "\n".join(lines)

    staff_rows = []
    for person, what, manager_id in sorted(unassigned_staff, key=lambda item: item[0].employee_id):
        staff_rows.append(f"| {cell(person.employee_id)} | "
                          f"{cell(person.first_name)} {cell(person.last_name)} | "
                          f"{what} - reassign {person.employee_id} (manager {manager_id}) |")
    account_rows = []
    for account, problem in sorted(unowned_accounts, key=lambda pair: pair[0].client_id):
        flag = expiry_flag(account.expires_on, today)
        account_rows.append(f"| {cell(account.client_id)} | {cell(account.purpose)} | "
                            f"{account.expires_on.isoformat()} | {flag or '-'} | "
                            f"service account {problem} - SOD-3 |")
    for client in state.other_clients:
        problem = sod.owner_problem((client.get("attributes") or {}).get("owner", ""), leavers,
                                    state.users)
        if problem:
            account_rows.append(f"| {cell(client['clientId'])} | (not in the CSV) | - | - | "
                                f"service account {problem} - SOD-3 |")
    files["unassigned.md"] = "\n".join([
        f"# Unassigned - quarter {quarter}",
        "",
        f"- Generated: {today.isoformat()}",
        "",
        "Nobody can attest these lines until somebody takes responsibility. Reassign them.",
        "",
        "## Staff whose manager has left, is disabled, has not started or cannot be found",
        "",
        *_table("| Employee | Name | Reason |", staff_rows, "None."),
        "## Service accounts with no active owner",
        "",
        *_table("| Client id | Purpose | Expires on | Expiry | Reason |", account_rows, "None."),
    ])
    return files


def write_attestation(files: dict[str, str], directory: str | Path) -> list[Path]:
    """Write the files, replacing attestation files from an earlier run that are no longer
    wanted (only files that start with one of our headings are ever removed)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.md"):
        first_line = old.read_text(encoding="utf-8").split("\n", 1)[0]
        if old.name not in files and first_line.startswith(HEADINGS):
            old.unlink()
    written = []
    for name, text in sorted(files.items()):
        path = directory / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written

