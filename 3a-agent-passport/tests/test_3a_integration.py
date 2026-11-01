"""Integration tests against a REAL local Keycloak (skipped, with a reason, when there is none).

Before running: start Keycloak, then
  3h-lifecycle/scripts/keycloak-dev.sh && 3a-agent-passport/scripts/keycloak-agent.sh
Run with:  pytest -q -m keycloak

These tests read real tokens, so they also settle the TODO(verify) items in server.py: the client
id claim (azp), the token type (typ), the audience and the scope claim format.
Only the documented throwaway secret/password (dev-only-not-secret) is used.
"""

import json
import os
import shutil
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
from passport_support import PASSPORT, call_tools, load_approve, post_initialize, run_session

import server
from lifecycle.kc import KeycloakClient

pytestmark = pytest.mark.keycloak

THROWAWAY = "dev-only-not-secret"
KC_URL = os.environ.get("KC_URL", "http://localhost:8080")
TOKEN_URL = f"{KC_URL}/realms/maple-harbour/protocol/openid-connect/token"
# Scopes Keycloak gives every new client; AC4 ignores them. Listed explicitly so a stray extra
# scope on the assistant's client (for example an admin scope) fails the test.
BUILT_IN_SCOPES = {"acr", "address", "basic", "email", "microprofile-jwt", "offline_access",
                   "organization", "phone", "profile", "roles", "service_account", "web-origins"}
ASSISTANT_SCOPES = {"requests:read", "requests:propose"}


def agent_token() -> str:
    response = httpx.post(TOKEN_URL, data={
        "grant_type": "client_credentials", "client_id": "agent-access-assistant",
        "client_secret": THROWAWAY}, timeout=10)
    assert response.status_code == 200, f"token request -> HTTP {response.status_code}"
    return response.json()["access_token"]


def manager_token() -> str:
    response = httpx.post(TOKEN_URL, data={
        "grant_type": "password", "client_id": "approve-cli", "username": "manager.demo",
        "password": THROWAWAY}, timeout=10)
    assert response.status_code == 200, f"token request -> HTTP {response.status_code}"
    return response.json()["access_token"]


def claims_of(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})   # reading only, not trusting


@pytest.fixture
def env(tmp_path):
    """The real server code with the REAL verifier (it downloads Keycloak's keys), temp files."""
    requests_file = tmp_path / "pending.json"
    shutil.copy(PASSPORT / "requests" / "pending.json", requests_file)
    settings = server.Settings(kc_url=KC_URL, requests_file=requests_file,
                               proposals_dir=tmp_path / "proposals",
                               audit_file=tmp_path / "audit.jsonl")
    audit = server.AuditLog(settings.audit_file)
    verifier = server.make_verifier(settings, audit)
    return SimpleNamespace(settings=settings, audit=audit, verifier=verifier,
                           server=server.build_server(settings, verifier))


def test_real_token_has_the_claims_server_py_relies_on():
    claims = claims_of(agent_token())
    assert claims["typ"] == "Bearer"                         # settles TODO(verify): typ
    assert claims["azp"] == "agent-access-assistant"          # settles TODO(verify): azp
    audience = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    assert "agent-passport" in audience
    assert claims["iss"] == f"{KC_URL}/realms/maple-harbour"


def test_scope_claim_contains_both_assistant_scopes_and_nothing_custom_besides():
    scopes = set(claims_of(agent_token())["scope"].split())
    assert ASSISTANT_SCOPES <= scopes
    assert scopes - BUILT_IN_SCOPES == ASSISTANT_SCOPES


def test_valid_real_token_can_list_and_propose(env):
    results = call_tools(env, agent_token(), [
        ("list_requests", {}),
        ("propose_change", {"request_id": "REQ-001", "change": ["payments-initiate"],
                            "justification": "Integration test."}),
    ])
    assert [r.is_error for r in results] == [False, False]
    (path,) = list(env.settings.proposals_dir.glob("*.json"))
    proposal = json.loads(path.read_text("utf-8"))
    assert proposal["requester"] == "e3001" and proposal["created_by"] == "agent-access-assistant"
    lines = [json.loads(line) for line in env.settings.audit_file.read_text("utf-8").splitlines()]
    assert [(line["tool"], line["decision"]) for line in lines] == [
        ("list_requests", "allow"), ("propose_change", "allow")]
    assert lines[0]["caller"]["client_id"] == "agent-access-assistant"


def test_tool_list_over_a_real_token_is_still_exactly_two(env):
    async def work(client):
        return {tool.name for tool in (await client.list_tools()).tools}
    assert run_session(env, agent_token(), work) == {"list_requests", "propose_change"}


def test_manager_token_is_not_accepted_by_the_mcp_server(env):
    # approve-cli's audience is "approve-cli", not "agent-passport"
    assert post_initialize(env, manager_token()) == 401


def admin_token() -> str:
    response = httpx.post(f"{KC_URL}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_ADMIN_USER", "admin"),
        "password": os.environ.get("KC_ADMIN_PASSWORD", THROWAWAY)}, timeout=10)
    assert response.status_code == 200
    return response.json()["access_token"]


def test_ac4_default_client_scopes_of_the_assistant():
    headers = {"Authorization": f"Bearer {admin_token()}"}
    base = f"{KC_URL}/admin/realms/maple-harbour"
    clients = httpx.get(f"{base}/clients", params={"clientId": "agent-access-assistant"},
                        headers=headers, timeout=10).json()
    (client,) = [c for c in clients if c["clientId"] == "agent-access-assistant"]
    scopes = httpx.get(f"{base}/clients/{client['id']}/default-client-scopes",
                       headers=headers, timeout=10).json()
    names = {scope["name"] for scope in scopes}
    assert names - BUILT_IN_SCOPES == ASSISTANT_SCOPES
    assert client["serviceAccountsEnabled"] is True and client["publicClient"] is False


def test_approve_success_path_with_a_real_manager_token(env):
    approve = load_approve()
    (propose,) = call_tools(env, agent_token(), [
        ("propose_change", {"request_id": "REQ-001", "change": ["payments-initiate"],
                            "justification": "Integration test."})])
    proposal_id = propose.structured_content["proposal_id"]
    kc = KeycloakClient("maple-harbour")
    user = kc.get_user_by_username("e3001")
    held_before = {g["name"] for g in kc.user_groups(user["id"])}
    try:
        code = approve.run(
            proposal_id, token=manager_token(), settings=env.settings,
            verifier=server.make_verifier(env.settings, audience="approve-cli"),
            kc=kc, allowed_groups=server.managed_groups())
        assert code == approve.EXIT_OK
        assert "payments-initiate" in {g["name"] for g in kc.user_groups(user["id"])}
        proposal = json.loads(
            (env.settings.proposals_dir / f"{proposal_id}.json").read_text("utf-8"))
        assert proposal["status"] == "approved"
        assert proposal["approved_by"]["username"] == "manager.demo"
        assert uuid.UUID(proposal["approved_by"]["subject"])
    finally:
        if "payments-initiate" not in held_before:       # put the directory back as it was
            group = next(g for g in kc.list_groups() if g["name"] == "payments-initiate")
            kc.remove_user_from_group(user["id"], group["id"])


def test_approve_refuses_the_assistants_own_token(env):
    approve = load_approve()
    proposal_id = str(uuid.uuid4())
    code = approve.run(
        proposal_id, token=agent_token(), settings=env.settings,
        verifier=server.make_verifier(env.settings, audience="approve-cli"),
        kc=KeycloakClient("maple-harbour"), allowed_groups=server.managed_groups())
    assert code == approve.EXIT_DENIED
