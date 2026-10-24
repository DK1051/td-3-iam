"""Helpers shared by the unit tests: file locations, a fixed "today", planning and feed editing."""

from datetime import date
from pathlib import Path

from lifecycle import engine
from lifecycle.feed import load_feed, load_service_accounts

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
ROLES_MAP = ROOT / "roles-map.yaml"
SOD_RULES = ROOT / "sod-rules.yaml"
TODAY = date(2026, 10, 22)   # before every joiner's start date
LATER = date(2026, 11, 20)


def make_plan(fake, feed, accounts, roles_map, today=TODAY):
    state = engine.read_state(fake, feed, accounts)
    return engine.plan(feed, accounts, roles_map, state, today)


def edited_feed(tmp_path, source, *replacements):
    """Copy a feed CSV into tmp_path with text replacements applied, and parse it."""
    text = (FIXTURES / source).read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "feed.csv"
    path.write_text(text, encoding="utf-8")
    return load_feed(path)


def load_v2():
    return load_feed(FIXTURES / "feed-v2.csv"), load_service_accounts(
        FIXTURES / "service-accounts-v2.csv")


def about(actions, target):
    return [a for a in actions if a.target == target]
