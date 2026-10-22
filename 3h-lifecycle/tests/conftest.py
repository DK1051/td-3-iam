"""Shared pytest setup: skip the Keycloak integration tests when no local Keycloak is running.

The check is a GET on /realms/master with a 2-second timeout. The address comes from KC_URL
(default http://localhost:8080), the same variable the engine uses.
"""

import os
from urllib.parse import urlparse

import httpx
import pytest


def keycloak_url() -> str:
    return os.environ.get("KC_URL", "http://localhost:8080")


def why_keycloak_is_unusable() -> str | None:
    """Returns None when Keycloak can be used, otherwise the reason to show next to 'skipped'."""
    url = keycloak_url()
    if urlparse(url).hostname not in ("localhost", "127.0.0.1"):
        # The integration tests delete and rebuild the realm, so they only run against a local server.
        return f"integration tests only run against a local Keycloak, not {url}"
    try:
        status = httpx.get(f"{url}/realms/master", timeout=2.0).status_code
    except httpx.HTTPError as exc:
        return f"no Keycloak at {url} ({type(exc).__name__}); start it, see 3h-lifecycle/README.md"
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
