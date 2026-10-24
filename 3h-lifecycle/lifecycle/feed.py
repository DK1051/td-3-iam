"""Read and check the two CSV files that drive the engine.

hr-feed.csv lists people: joiners (new staff), movers (changing role) and leavers.
service-accounts.csv lists accounts used by programs. Every problem raises a FeedError that
names the file, the row and the column, so whoever edits the CSV can find the mistake quickly.
"""

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

FEED_COLUMNS = [
    "employee_id", "action", "first_name", "last_name", "email", "department", "job_title",
    "manager_id", "start_date", "end_date", "requested_by", "approved_by",
    "id_checked_live_video", "references_contacted", "education_verified",
]
SERVICE_ACCOUNT_COLUMNS = ["client_id", "owner", "purpose", "expires_on"]


class FeedError(Exception):
    """A CSV file cannot be used at all (unreadable, wrong columns, duplicate ids)."""


class RowError(FeedError):
    """One row is malformed. load_feed and load_service_accounts do not stop for it: the row is
    recorded in `bad_rows`, the engine reports it as BLOCKED, and every other row still runs."""

    def __init__(self, filename: str, line: int, column: str, problem: str):
        super().__init__(f"{filename} row {line}, column '{column}': {problem}")
        self.line = line
        self.reason = f"column '{column}': {problem}"


@dataclass(frozen=True)
class BadRow:
    """A malformed row, with just enough to report it safely (who is '?' if the id is unusable)."""
    source: str     # "feed" or "service accounts"
    line: int       # line number in the CSV file, the header being line 1
    who: str
    reason: str


def _shown(value: str) -> str:
    """A value from the CSV made safe to print: control characters become \\x1b style escapes
    (a feed file could otherwise write terminal escape codes into the logs), and it is cut short."""
    escaped = value.encode("unicode_escape").decode("ascii")
    return escaped if len(escaped) <= 40 else escaped[:37] + "..."


def _who(row) -> str:
    raw = row.values.get(row.id_column, "").strip()
    return raw if re.fullmatch(r"[A-Za-z0-9._-]+", raw) else "?"


@dataclass(frozen=True)
class Joiner:
    """A new member of staff. The three verification flags are checked by the gate (T3-S03)."""
    employee_id: str
    first_name: str
    last_name: str
    email: str
    department: str
    job_title: str
    manager_id: str
    start_date: date
    requested_by: str
    approved_by: str
    id_checked_live_video: bool
    references_contacted: bool
    education_verified: bool


@dataclass(frozen=True)
class Mover:
    """Someone who already has an account and is changing department or job title."""
    employee_id: str
    first_name: str
    last_name: str
    email: str
    department: str
    job_title: str
    manager_id: str
    requested_by: str
    approved_by: str


@dataclass(frozen=True)
class Leaver:
    """Someone who left. Their account is disabled on end_date, never deleted."""
    employee_id: str
    first_name: str
    last_name: str
    end_date: date
    manager_id: str = ""   # optional; only used to list the leaver in the attestation


@dataclass(frozen=True)
class ServiceAccount:
    """An account used by a program, with a named owner, a purpose and an expiry date.
    owner is "" when the CSV leaves it empty; the engine never creates such an account (SOD-3)."""
    client_id: str
    owner: str
    purpose: str
    expires_on: date


@dataclass(frozen=True)
class Feed:
    joiners: list[Joiner]
    movers: list[Mover]
    leavers: list[Leaver]
    bad_rows: list[BadRow] = field(default_factory=list)   # malformed rows, not in the lists


class ServiceAccounts(list):
    """The list of service accounts read from the CSV, plus the malformed rows that were left out."""

    def __init__(self, accounts=(), bad_rows=()):
        super().__init__(accounts)
        self.bad_rows: list[BadRow] = list(bad_rows)


class _Row:
    """One CSV row plus helpers that raise a FeedError naming the row and column."""

    def __init__(self, filename: str, line: int, values: dict[str, str], id_column: str):
        self.filename = filename
        self.line = line
        self.values = values
        self.id_column = id_column

    def error(self, column: str, problem: str) -> RowError:
        return RowError(self.filename, self.line, column, problem)

    def text(self, column: str) -> str:
        value = self.values[column].strip()
        if value == "":
            raise self.error(column, "must not be empty")
        # Cc = control characters (tab, line break, ...); Cf = invisible format characters such as
        # the right-to-left override, which can make a name display differently from what it is.
        if any(unicodedata.category(char) in ("Cc", "Cf") for char in value):
            raise self.error(column, "must not contain a control or invisible formatting character")
        return value

    def identifier(self, column: str) -> str:
        """An id (employee, manager, client). It becomes a username and part of a web request,
        so only letters, digits, dot, underscore and hyphen are allowed."""
        value = self.text(column)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise self.error(column, f"'{_shown(value)}' may only contain letters, digits, '.', '_' and '-'")
        return value

    def day(self, column: str) -> date:
        value = self.text(column)
        # Only YYYY-MM-DD is accepted, so there is exactly one way to write a date.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise self.error(column, f"'{_shown(value)}' is not a date written as YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise self.error(column, f"'{_shown(value)}' is not a real calendar date") from None

    def flag(self, column: str) -> bool:
        value = self.values[column].strip()
        if value not in ("true", "false"):
            raise self.error(column, f"'{_shown(value)}' must be exactly 'true' or 'false'")
        return value == "true"

    def optional_flag(self, column: str) -> None:
        """Movers and leavers leave the verification columns empty; if filled they must be valid."""
        if self.values[column].strip() != "":
            self.flag(column)


def _read_rows(path: str | Path, required_columns: list[str], id_column: str) -> list[_Row]:
    path = Path(path)
    try:
        handle = path.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise FeedError(f"cannot read {path.name}: {type(exc).__name__}") from None
    with handle:
        reader = csv.DictReader(handle)
        missing = [c for c in required_columns if c not in (reader.fieldnames or [])]
        if missing:
            raise FeedError(f"{path.name}: missing column(s): {', '.join(missing)}")
        rows = []
        for values in reader:
            if None in values or None in values.values():
                raise FeedError(f"{path.name} row {reader.line_num}: wrong number of columns")
            rows.append(_Row(path.name, reader.line_num, values, id_column))
        return rows


def _check_not_duplicate(row: _Row, seen: set[str], what: str) -> None:
    """Two rows with the same id are ambiguous (which one is right?), so the whole run stops."""
    raw = row.values[row.id_column].strip().lower()
    if raw and raw in seen:
        raise FeedError(f"{row.filename} row {row.line}, column '{row.id_column}': "
                        f"{_shown(raw)} appears more than once in the {what}")
    seen.add(raw)


def _parse_feed_row(row: _Row):
    """Turn one CSV row into a Joiner, Mover or Leaver, or raise RowError."""
    employee_id = row.identifier("employee_id")
    action = row.text("action")
    if action == "joiner":
        return Joiner(
            employee_id=employee_id,
            first_name=row.text("first_name"),
            last_name=row.text("last_name"),
            email=row.text("email"),
            department=row.text("department"),
            job_title=row.text("job_title"),
            manager_id=row.identifier("manager_id"),
            start_date=row.day("start_date"),
            requested_by=row.identifier("requested_by"),
            approved_by=row.identifier("approved_by"),
            id_checked_live_video=row.flag("id_checked_live_video"),
            references_contacted=row.flag("references_contacted"),
            education_verified=row.flag("education_verified"),
        )
    if action == "mover":
        for column in ("id_checked_live_video", "references_contacted", "education_verified"):
            row.optional_flag(column)
        return Mover(
            employee_id=employee_id,
            first_name=row.text("first_name"),
            last_name=row.text("last_name"),
            email=row.text("email"),
            department=row.text("department"),
            job_title=row.text("job_title"),
            manager_id=row.identifier("manager_id"),
            requested_by=row.identifier("requested_by"),
            approved_by=row.identifier("approved_by"),
        )
    if action == "leaver":
        for column in ("id_checked_live_video", "references_contacted", "education_verified"):
            row.optional_flag(column)
        return Leaver(
            employee_id=employee_id,
            first_name=row.text("first_name"),
            last_name=row.text("last_name"),
            end_date=row.day("end_date"),
            manager_id=row.identifier("manager_id") if row.values["manager_id"].strip() else "",
        )
    raise row.error("action", f"'{_shown(action)}' must be joiner, mover or leaver")


def load_feed(path: str | Path) -> Feed:
    """Parse hr-feed.csv into joiners, movers and leavers.

    A malformed row does not stop the run: it is left out and listed in `feed.bad_rows`.
    A structural problem (unreadable file, missing or extra columns, a duplicate employee id)
    raises FeedError."""
    feed = Feed(joiners=[], movers=[], leavers=[])
    seen: set[str] = set()
    for row in _read_rows(path, FEED_COLUMNS, "employee_id"):
        _check_not_duplicate(row, seen, "feed")
        try:
            person = _parse_feed_row(row)
        except RowError as exc:
            feed.bad_rows.append(BadRow("feed", row.line, _who(row), exc.reason))
            continue
        {Joiner: feed.joiners, Mover: feed.movers, Leaver: feed.leavers}[type(person)].append(person)
    return feed


def load_service_accounts(path: str | Path) -> ServiceAccounts:
    """Parse service-accounts.csv. Malformed rows are left out and listed in `.bad_rows`."""
    accounts = ServiceAccounts()
    seen: set[str] = set()
    for row in _read_rows(path, SERVICE_ACCOUNT_COLUMNS, "client_id"):
        _check_not_duplicate(row, seen, "file")
        try:
            accounts.append(ServiceAccount(
                client_id=row.identifier("client_id"),
                owner=row.identifier("owner") if row.values["owner"].strip() else "",
                purpose=row.text("purpose"),
                expires_on=row.day("expires_on"),
            ))
        except RowError as exc:
            accounts.bad_rows.append(BadRow("service accounts", row.line, _who(row), exc.reason))
    return accounts
