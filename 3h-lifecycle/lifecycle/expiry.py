"""Service-account expiry: which accounts are about to expire, and which already have.

"Today" is never read from the clock inside the checks. It is passed in, or comes from the
--today option, or from the LIFECYCLE_TODAY environment variable (YYYY-MM-DD), and only if
none of those is given does the program use the real date. That keeps tests repeatable.
"""

import os
from datetime import date, timedelta

from lifecycle.feed import ServiceAccount

SOON_DAYS = 30
EXPIRES_SOON = "EXPIRES SOON"
EXPIRED = "EXPIRED"


class ExpiryError(Exception):
    """LIFECYCLE_TODAY is not a date."""


def resolve_today(explicit: date | None = None) -> date:
    """--today wins, then LIFECYCLE_TODAY, then the real date."""
    if explicit is not None:
        return explicit
    text = os.environ.get("LIFECYCLE_TODAY", "").strip()
    if text:
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ExpiryError("LIFECYCLE_TODAY must be a date written as YYYY-MM-DD") from None
    return date.today()


def expiry_flag(expires_on: date, today: date) -> str | None:
    """EXPIRED once the date has passed, EXPIRES SOON within 30 days (the 30th day included),
    otherwise None."""
    if expires_on < today:
        return EXPIRED
    if expires_on <= today + timedelta(days=SOON_DAYS):
        return EXPIRES_SOON
    return None


def expiry_warnings(accounts: list[ServiceAccount], today: date) -> list[str]:
    """One plain line per account that is expired or expiring soon."""
    lines = []
    for account in accounts:
        flag = expiry_flag(account.expires_on, today)
        if flag:
            lines.append(f"{account.client_id}: {flag} (expires_on {account.expires_on.isoformat()})")
    return lines
