"""Integration tests: the real engine against a real local Keycloak (skipped when there is none).

Run with a Keycloak dev server up:  pytest -q -m keycloak
The tests rebuild the realm maple-harbour from scratch (keycloak-dev.sh --reset), apply the
committed sample feed with --today 2026-10-22 (before every joiner's start date), check what
Keycloak holds, and then apply again with --today 2026-11-20 (after every start date). The dates
are fixed so the result does not change as real time passes.

The tests run in file order: everything about the "before start" state comes first, because the
last fixture (after_start) changes Keycloak.
"""

import contextlib
import io
import os
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from lifecycle import engine
from lifecycle.__main__ import main
from lifecycle.feed import load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient

pytestmark = pytest.mark.keycloak

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "tests" / "fixtures" / "feed-v1.csv"
ACCOUNTS = ROOT / "tests" / "fixtures" / "service-accounts-v1.csv"
DEV_SCRIPT = ROOT / "scripts" / "keycloak-dev.sh"
TODAY = date(2026, 10, 22)
LATER = date(2026, 11, 20)
CLI_ARGS = ["--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
            "--realm", "maple-harbour", "--today", "2026-10-22"]
LATER_ARGS = [*CLI_ARGS[:-1], "2026-11-20"]


@pytest.fixture(scope="module")
def first_apply():
    """Rebuild the realm, apply the sample feed once, and keep the printed output."""
    env = {**os.environ, "PYTHON": sys.executable}
    subprocess.run(["bash", str(DEV_SCRIPT), "--reset"], check=True, env=env, timeout=600,
                   stdout=subprocess.DEVNULL)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = main(["apply", *CLI_ARGS])
    assert code == 0
    return printed.getvalue()


@pytest.fixture(scope="module")
def after_start(first_apply):
    """Apply again on 2026-11-20, after every joiner's start date. Changes Keycloak."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = main(["apply", *LATER_ARGS])
    assert code == 0
    return printed.getvalue()


@pytest.fixture
def kc():
    return KeycloakClient("maple-harbour")


def groups_of(kc, username):
    user = kc.get_user_by_username(username)
    return {group["name"] for group in kc.user_groups(user["id"])}


def test_first_apply_does_the_planned_work(first_apply):
    assert "Applied: create_user=6, move_user=3, disable_user=3, create_client=4" in first_apply


def test_joiners_exist_disabled_until_their_start_date_with_groups_and_attributes(first_apply,
                                                                                 kc):
    expected_groups = {
        "e2001": {"finance", "payments-initiate"},
        "e2002": {"member-services"},
        "e2003": {"it", "privileged"},
        "e2004": {"member-services"},
        "e2005": {"it", "helpdesk"},
        "e2006": {"finance", "payments-approve"},
    }
    for username, groups in expected_groups.items():
        user = kc.get_user_by_username(username)
        assert user["enabled"] is False, username               # start dates are in November
        assert user["attributes"]["pending_start"] >= "2026-11-02", username
        assert groups_of(kc, username) == groups, username
        assert user["attributes"]["employee_id"] == username.upper()
        assert {"department", "job_title", "manager_id"} <= set(user["attributes"]), username
        assert user["email"].endswith("@mapleharbour.example")


def test_leavers_are_disabled_with_a_date_and_still_present(first_apply, kc):
    for username, left_on in {"e4001": "2026-10-16", "e4002": "2026-10-09",
                              "e4003": "2026-10-21"}.items():
        user = kc.get_user_by_username(username)
        assert user is not None            # never deleted
        assert user["enabled"] is False
        assert user["attributes"]["disabled_on"] == left_on
    assert groups_of(kc, "e4003") == {"it", "privileged"}  # kept as evidence


def test_movers_have_exactly_the_mapped_groups(first_apply, kc):
    assert groups_of(kc, "e3001") == {"finance", "payments-initiate"}
    assert groups_of(kc, "e3002") == {"finance", "payments-approve"}
    assert groups_of(kc, "e3003") == {"it", "privileged"}
    assert kc.get_user_by_username("e3002")["attributes"]["job_title"] == "Finance Manager"
    assert kc.get_user_by_username("e3002")["enabled"] is True


def test_service_account_clients_have_attributes_and_the_expired_one_is_disabled(first_apply, kc):
    accounts = load_service_accounts(ACCOUNTS)
    assert len(accounts) == 4
    for account in accounts:
        client = kc.get_client_by_client_id(account.client_id)
        assert client is not None, account.client_id
        assert client["attributes"]["owner"] == account.owner
        assert client["attributes"]["purpose"] == account.purpose
        assert client["attributes"]["expires_on"] == account.expires_on.isoformat()
        assert client["serviceAccountsEnabled"] is True
        assert client["publicClient"] is False
        assert client["standardFlowEnabled"] is False
        assert client["enabled"] is (account.expires_on >= TODAY), account.client_id
    assert kc.get_client_by_client_id("svc-legacy-sync")["enabled"] is False


def test_plan_after_apply_is_empty(first_apply, kc):
    feed = load_feed(FEED)
    accounts = load_service_accounts(ACCOUNTS)
    state = engine.read_state(kc, feed, accounts)
    roles_map = engine.load_roles_map(ROOT / "roles-map.yaml")
    assert engine.plan(feed, accounts, roles_map, state, TODAY) == []


def test_applying_again_before_the_start_date_changes_nothing(first_apply, kc, capsys):
    assert main(["apply", *CLI_ARGS]) == 0
    assert "Applied 0 changes." in capsys.readouterr().out
    feed = load_feed(FEED)
    accounts = load_service_accounts(ACCOUNTS)
    state = engine.read_state(kc, feed, accounts)
    roles_map = engine.load_roles_map(ROOT / "roles-map.yaml")
    actions = engine.plan(feed, accounts, roles_map, state, TODAY)
    assert engine.apply(actions, kc) == Counter()


def test_after_the_start_dates_all_six_joiners_are_enabled_and_the_marker_is_gone(
        after_start, kc):
    assert "enable_user=6" in after_start
    assert "update_client=1" in after_start     # svc-report-export expired on 2026-11-15
    for username in ("e2001", "e2002", "e2003", "e2004", "e2005", "e2006"):
        user = kc.get_user_by_username(username)
        assert user["enabled"] is True, username
        assert "pending_start" not in user["attributes"], username
    assert groups_of(kc, "e2003") == {"it", "privileged"}
    assert kc.get_client_by_client_id("svc-report-export")["enabled"] is False


def test_plan_is_empty_after_the_start_dates_and_a_further_apply_does_nothing(
        after_start, kc, capsys):
    feed = load_feed(FEED)
    accounts = load_service_accounts(ACCOUNTS)
    state = engine.read_state(kc, feed, accounts)
    roles_map = engine.load_roles_map(ROOT / "roles-map.yaml")
    assert engine.plan(feed, accounts, roles_map, state, LATER) == []
    assert main(["apply", *LATER_ARGS]) == 0
    assert "Applied 0 changes." in capsys.readouterr().out
