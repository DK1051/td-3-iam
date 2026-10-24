"""Integration tests for the T3-S03 controls against a real local Keycloak (skipped when none).

Run with a Keycloak dev server up:  pytest -q -m keycloak
One module-wide setup rebuilds the realm, gives a seeded leaver a normal and an offline login
token, applies the extended sample feed once (--today 2026-10-22), and then the tests look at
what Keycloak holds. The last tests change Keycloak further, so they come last.
"""

import contextlib
import io
import os
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from lifecycle import engine
from lifecycle.__main__ import main
from lifecycle.feed import load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient

pytestmark = pytest.mark.keycloak

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "tests" / "fixtures" / "feed-v2.csv"
ACCOUNTS = ROOT / "tests" / "fixtures" / "service-accounts-v2.csv"
CLEAN_FEED = ROOT / "hr" / "fixtures" / "clean-feed.csv"
CLEAN_ACCOUNTS = ROOT / "hr" / "fixtures" / "clean-service-accounts.csv"
DEV_SCRIPT = ROOT / "scripts" / "keycloak-dev.sh"
REALM = "maple-harbour"
TEST_CLIENT = "lifecycle-test-client"   # created by this test only; the engine never sees it
KC_URL = os.environ.get("KC_URL", "http://localhost:8080")


def cli_args(feed=FEED, accounts=ACCOUNTS, today="2026-10-22"):
    return ["--feed", str(feed), "--service-accounts", str(accounts), "--realm", REALM,
            "--today", today]


def run_cli(*args):
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = main(list(args))
    return code, printed.getvalue()


def user_id(kc, username):
    return kc.get_user_by_username(username)["id"]


def admin_get(kc, path):
    return kc._request("GET", f"/admin/realms/{REALM}{path}").json()


def log_in(username, password, scope):
    """Direct-grant login as the test client; returns the refresh token."""
    response = httpx.post(f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token", timeout=15, data={
        "grant_type": "password", "client_id": TEST_CLIENT, "username": username,
        "password": password, "scope": scope})
    assert response.status_code == 200
    return response.json()["refresh_token"]


def refresh_status(refresh_token):
    response = httpx.post(f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token", timeout=15, data={
        "grant_type": "refresh_token", "client_id": TEST_CLIENT, "refresh_token": refresh_token})
    return response.status_code


def client_credentials_status(kc, client_id):
    """Ask for a token as the service account itself (never prints the secret)."""
    uuid = kc.get_client_by_client_id(client_id)["id"]
    secret = admin_get(kc, f"/clients/{uuid}/client-secret")["value"]
    response = httpx.post(f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token", timeout=15,
                          data={"grant_type": "client_credentials", "client_id": client_id,
                                "client_secret": secret})
    return response.status_code


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    env = {**os.environ, "PYTHON": sys.executable}
    subprocess.run(["bash", str(DEV_SCRIPT), "--reset"], check=True, env=env, timeout=600,
                   stdout=subprocess.DEVNULL)
    kc = KeycloakClient(REALM)

    # A test-only public client that allows username/password login, so the test can obtain
    # tokens for a seeded leaver. The password is random per run and never printed.
    kc._request("POST", f"/admin/realms/{REALM}/clients", ok=(201,), body={
        "clientId": TEST_CLIENT, "publicClient": True, "directAccessGrantsEnabled": True,
        "standardFlowEnabled": False})
    password = secrets.token_urlsafe(16)
    leaver_id = user_id(kc, "e4001")
    kc._request("PUT", f"/admin/realms/{REALM}/users/{leaver_id}/reset-password", ok=(204,),
                body={"type": "password", "value": password, "temporary": False})
    normal = log_in("e4001", password, "openid")
    offline = log_in("e4001", password, "openid offline_access")
    before = (refresh_status(normal), refresh_status(offline))   # proves the tokens work

    # An attribute the engine does not manage, with two values (to prove nothing is lost).
    mover_id = user_id(kc, "e3001")
    rep = admin_get(kc, f"/users/{mover_id}")
    rep["attributes"]["team"] = ["payments-floor", "night-shift"]
    kc._request("PUT", f"/admin/realms/{REALM}/users/{mover_id}", body=rep, ok=(204,))

    reports = tmp_path_factory.mktemp("reports")
    code, output = run_cli("apply", *cli_args(), "--reports-dir", str(reports))
    assert code == 0
    return {"kc": kc, "normal": normal, "offline": offline, "before": before,
            "output": output, "reports": reports, "leaver_id": leaver_id}


@pytest.fixture
def kc(world):
    return world["kc"]


# ---- G1: sessions and offline tokens ---------------------------------------------------------

def test_g1_tokens_worked_before_and_are_refused_after_the_leaver_is_disabled(world):
    assert world["before"] == (200, 200)
    assert refresh_status(world["normal"]) == 400
    assert refresh_status(world["offline"]) == 400


def test_g1_the_leavers_sessions_and_offline_tokens_are_gone_not_just_blocked(world, kc):
    uid = world["leaver_id"]
    assert admin_get(kc, f"/users/{uid}/sessions") == []
    assert admin_get(kc, f"/users/{uid}/consents") == []     # no client still holds an offline token
    assert kc.get_user_by_username("e4001")["attributes"]["disabled_on"] == "2026-10-16"


# ---- G3: attributes the engine does not manage survive an update ------------------------------

def test_g3_a_two_value_attribute_survives_the_mover_update(kc):
    rep = admin_get(kc, f"/users/{user_id(kc, 'e3001')}")
    assert rep["attributes"]["team"] == ["payments-floor", "night-shift"]
    assert rep["attributes"]["job_title"] == ["Payments Officer"]    # the engine's own key changed


# ---- proofing gate and report ----------------------------------------------------------------

def test_blocked_joiners_do_not_exist_in_keycloak(world, kc):
    for username in ("e2007", "e2008", "e2009", "e2010"):
        assert kc.get_user_by_username(username) is None, username
    assert kc.get_user_by_username("e2001") is not None


def test_blocked_joiners_report_lists_them_with_the_missing_checks(world):
    text = (world["reports"] / "blocked-joiners.md").read_text(encoding="utf-8")
    for needle in ("E2007", "id_checked_live_video", "E2008", "references_contacted", "E2009",
                   "education_verified", "E2010", "requester equals approver"):
        assert needle in text


# ---- SOD-2 fails closed -----------------------------------------------------------------------

def test_the_sod2_mover_was_not_applied_and_nobody_holds_both_payment_groups(world, kc):
    mover = kc.get_user_by_username("e3004")
    groups = {g["name"] for g in kc.user_groups(mover["id"])}
    assert groups == {"finance", "payments-initiate"}
    assert mover["attributes"]["job_title"] == "Payments Officer"
    ids = {g["name"]: g["id"] for g in kc.list_groups()}
    initiate = {u["username"] for u in admin_get(kc, f"/groups/{ids['payments-initiate']}/members")}
    approve = {u["username"] for u in admin_get(kc, f"/groups/{ids['payments-approve']}/members")}
    assert initiate & approve == set()
    assert "e3004" in initiate and "e3004" not in approve


# ---- SOD-3 and the sod command ------------------------------------------------------------------

def test_the_ownerless_service_account_was_never_created(kc):
    assert kc.get_client_by_client_id("svc-orphan-export") is None
    assert kc.get_client_by_client_id("svc-payments-batch")["enabled"] is True


def test_sod_command_exit_codes_against_the_live_directory(world):
    code, output = run_cli("sod", *cli_args())
    assert code == 1 and "SOD-1  E2010" in output and "SOD-2  E3004" in output
    assert "SOD-3  svc-orphan-export" in output
    code, output = run_cli("sod", *cli_args(CLEAN_FEED, CLEAN_ACCOUNTS))
    assert code == 0, output


def test_second_plan_has_nothing_to_change(world, kc):
    feed, accounts = load_feed(FEED), load_service_accounts(ACCOUNTS)
    state = engine.read_state(kc, feed, accounts)
    roles_map = engine.load_roles_map(ROOT / "roles-map.yaml")
    actions = engine.plan(feed, accounts, roles_map, state, date(2026, 10, 22))
    assert [a for a in actions if a.kind not in engine.REPORT_ONLY] == []


# ---- attestation ---------------------------------------------------------------------------------

def test_attest_writes_one_file_per_manager_plus_unassigned(world, tmp_path):
    out = tmp_path / "attestation"
    code, output = run_cli("attest", *cli_args(), "--quarter", "2026-Q4", "--out", str(out))
    assert code == 0 and "Wrote 3 attestation file(s)" in output
    assert sorted(p.name for p in out.glob("*.md")) == ["E1001.md", "E1002.md", "unassigned.md"]
    feed = load_feed(FEED)
    for manager_id in ("E1001", "E1002"):
        text = (out / f"{manager_id}.md").read_text(encoding="utf-8")
        reports = [p for p in [*feed.joiners, *feed.movers, *feed.leavers]
                   if p.manager_id == manager_id]
        owned = [a for a in load_service_accounts(ACCOUNTS) if a.owner == manager_id]
        assert text.count("[ ] keep  [ ] revoke") == len(reports) + len(owned)
    e1001 = (out / "E1001.md").read_text(encoding="utf-8")
    assert "no (disabled 2026-10-16)" in e1001            # the leaver, disabled, groups still listed
    assert "svc-orphan-export" in (out / "unassigned.md").read_text(encoding="utf-8")


# ---- these change Keycloak further, so they run last --------------------------------------------

def test_g1_the_old_tokens_stay_dead_even_if_the_account_is_switched_on_again(world, kc):
    # Disabling alone only blocks the tokens while the account is off; ending the sessions and
    # revoking the offline tokens kills them for good. Switch the account on to prove it.
    kc.update_user(world["leaver_id"], enabled=True)
    try:
        assert refresh_status(world["normal"]) == 400
        assert refresh_status(world["offline"]) == 400
    finally:
        kc.update_user(world["leaver_id"], enabled=False)


def test_g2_a_service_account_whose_owner_left_is_disabled_and_stays_disabled(world, kc, tmp_path):
    assert client_credentials_status(kc, "svc-payments-batch") == 200     # it works for now
    accounts = tmp_path / "accounts.csv"
    accounts.write_text(ACCOUNTS.read_text(encoding="utf-8").replace(
        "svc-payments-batch,E1001", "svc-payments-batch,E4001"), encoding="utf-8")
    code, output = run_cli("apply", *cli_args(accounts=accounts),
                           "--reports-dir", str(tmp_path / "r"))
    assert code == 0 and "update_client=1" in output
    client = kc.get_client_by_client_id("svc-payments-batch")
    assert client["enabled"] is False
    assert client["attributes"]["disabled_by_engine"] == "SOD-3 no active owner"
    assert client_credentials_status(kc, "svc-payments-batch") != 200     # no new tokens
    # Naming a healthy owner again does not switch it back on.
    code, output = run_cli("apply", *cli_args(), "--reports-dir", str(tmp_path / "r"))
    assert code == 0 and "Applied 0 changes." in output
    assert kc.get_client_by_client_id("svc-payments-batch")["enabled"] is False
