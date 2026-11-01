"""Shared pytest setup for the Agent Passport tests.

- Puts 3H's unit-test folder on the import path, so the tests reuse 3H's in-memory Keycloak fake
  (tests/unit/fake_keycloak.py) instead of copying it.
- Skips the `keycloak` integration tests, with a reason, when no local Keycloak is running. Same
  check as 3h-lifecycle/tests/conftest.py (GET /realms/master, 2-second timeout, local only).
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "3h-lifecycle" / "tests" / "unit"))


def why_keycloak_is_unusable() -> str | None:
    """None when Keycloak can be used, otherwise the reason to show next to 'skipped'."""
    url = os.environ.get("KC_URL", "http://localhost:8080")
    if urlparse(url).hostname not in ("localhost", "127.0.0.1"):
        return f"integration tests only run against a local Keycloak, not {url}"
    try:
        status = httpx.get(f"{url}/realms/master", timeout=2.0).status_code
    except httpx.HTTPError as exc:
        return (f"no Keycloak at {url} ({type(exc).__name__}); start it, then run "
                "3h-lifecycle/scripts/keycloak-dev.sh and 3a-agent-passport/scripts/keycloak-agent.sh")
    if status != 200:
        return f"Keycloak at {url} answered HTTP {status}, not 200; wait until it has started"
    return None


def pytest_collection_modifyitems(config, items):
    keycloak_items = [item for item in items if "keycloak" in item.keywords]
    if not keycloak_items:
        return
    reason = why_keycloak_is_unusable()
    if reason:
        for item in keycloak_items:
            item.add_marker(pytest.mark.skip(reason=reason))
