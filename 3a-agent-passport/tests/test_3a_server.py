"""Unit tests for the MCP server and its token checks. No Keycloak: tokens are minted here with a
throwaway RSA key (pyjwt) and the server's verifier is given that key's public half."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from passport_support import (
    KID,
    audit_lines,
    call_tools,
    jwks_of,
    make_env,
    mint,
    new_key,
    post_initialize,
    result_text,
    run_session,
)

import server


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def proposal_files(env):
    folder = env.settings.proposals_dir
    return sorted(folder.glob("*.json")) if folder.exists() else []


PROPOSE = ("propose_change", {"request_id": "REQ-001", "change": ["payments-initiate"],
                              "justification": "Moved to the payments team."})


# ---- AC2: the menu ------------------------------------------------------------------------

def test_tool_list_is_exactly_the_two_tools(env):
    async def work(client):
        return {tool.name for tool in (await client.list_tools()).tools}
    assert run_session(env, mint(env), work) == {"list_requests", "propose_change"}


# ---- AC3: token checks --------------------------------------------------------------------

def test_no_token_is_unauthorized(env):
    assert post_initialize(env, None) == 401
    assert audit_lines(env) == []   # stated limit: the SDK rejects it before our code runs


@pytest.mark.parametrize("reason, kwargs", [
    ("invalid audience", {"aud": "someone-else"}),
    ("invalid audience", {"aud": "approve-cli"}),
    ("not an access token", {"typ": "ID"}),   # an ID token's aud is its client id; typ keeps it out
    ("token expired", {"expires_in": -10}),
    ("invalid issuer", {"iss": "http://keycloak.test/realms/other"}),
    ("unsupported algorithm", {"alg": "HS256"}),
    ("unsupported algorithm", {"alg": "none"}),
    ("invalid signature", {"key": "other"}),          # right kid, wrong private key
    ("unknown key id", {"kid": "not-in-the-jwks"}),
    ("no client id", {"drop": ("azp",)}),
    ("invalid token", {"drop": ("sub",)}),
    ("invalid token", {"drop": ("exp",)}),
])
def test_bad_tokens_are_rejected_and_audited(env, reason, kwargs):
    if kwargs.get("key") == "other":
        kwargs = {**kwargs, "key": new_key()}
    assert post_initialize(env, mint(env, **kwargs)) == 401
    lines = audit_lines(env)
    assert len(lines) == 1
    assert lines[0]["decision"] == "deny" and lines[0]["tool"] == "-"
    assert lines[0]["reason"] == reason
    assert lines[0]["caller"] == {"client_id": None, "subject": None}


def test_garbage_token_is_rejected(env):
    assert post_initialize(env, "not.a.jwt") == 401
    assert [line["reason"] for line in audit_lines(env)] == ["malformed token"]


def test_client_id_falls_back_to_client_id_claim(env):
    token = mint(env, drop=("azp",), extra={"client_id": "agent-access-assistant"})
    access = asyncio.run(env.verifier.verify_token(token))
    assert access is not None and access.client_id == "agent-access-assistant"
    assert set(access.scopes) == {"requests:read", "requests:propose"}
    assert access.resource == "agent-passport" and access.subject == "service-account-agent"


def test_valid_token_is_accepted(env):
    assert post_initialize(env, mint(env)) == 200
    assert audit_lines(env) == []   # a good token with no tool call writes nothing


def test_token_without_read_scope_is_forbidden_by_the_sdk(env):
    token = mint(env, scope="requests:propose")
    assert post_initialize(env, token) == 403
    assert audit_lines(env) == []   # stated limit: rejected by the SDK before our code runs


def test_missing_propose_scope_is_a_tool_error_naming_the_scope(env):
    (result,) = call_tools(env, mint(env, scope="requests:read"), [PROPOSE])
    assert result.is_error
    assert "requests:propose" in result_text(result)
    assert proposal_files(env) == []
    (line,) = audit_lines(env)
    assert (line["tool"], line["decision"], line["reason"]) == (
        "propose_change", "deny", "missing scope requests:propose")


# ---- list_requests ------------------------------------------------------------------------

def test_list_requests_returns_the_pending_requests(env):
    (result,) = call_tools(env, mint(env), [("list_requests", {})])
    assert not result.is_error
    requests = result.structured_content["requests"]
    assert len(requests) == 8
    assert {"id", "requester", "requested_groups", "reason", "channel"} <= set(requests[0])


def test_list_requests_with_missing_file_is_a_tool_error(env):
    env.settings.requests_file.unlink()
    (result,) = call_tools(env, mint(env), [("list_requests", {})])
    assert result.is_error and "requests unavailable" in result_text(result)
    assert audit_lines(env)[-1]["decision"] == "deny"


# ---- propose_change -----------------------------------------------------------------------

def test_valid_proposal_is_written_with_the_requester_from_pending_json(env):
    (result,) = call_tools(env, mint(env), [PROPOSE])
    assert not result.is_error
    (path,) = proposal_files(env)
    proposal = json.loads(path.read_text("utf-8"))
    assert path.stem == proposal["id"] == result.structured_content["proposal_id"]
    assert proposal["requester"] == "e3001"            # REQ-001's requester in pending.json
    assert proposal["request_id"] == "REQ-001"
    assert proposal["proposed_groups"] == ["payments-initiate"]
    assert proposal["status"] == "pending"
    assert proposal["created_by"] == "agent-access-assistant"
    assert proposal["created_at"].endswith("Z")
    assert not list(env.settings.proposals_dir.glob(".*.tmp"))   # the atomic write left no temp file
    assert audit_lines(env)[-1]["decision"] == "allow"


def test_the_agent_cannot_name_the_requester(env):
    # propose_change has no requester argument; an extra one is not passed through.
    async def work(client):
        tool = next(t for t in (await client.list_tools()).tools if t.name == "propose_change")
        return set(tool.input_schema["properties"])
    assert run_session(env, mint(env), work) == {"request_id", "change", "justification"}


def test_an_extra_requester_argument_cannot_change_the_requester(env):
    # Tell the tool the proposal is "for" someone else. Either the call is an error, or the
    # requester written down is still the one from pending.json (REQ-001 -> e3001).
    arguments = {**PROPOSE[1], "requester": "e2001"}
    (result,) = call_tools(env, mint(env), [("propose_change", arguments)])
    files = proposal_files(env)
    if result.is_error:
        assert files == []
    else:
        (path,) = files
        assert json.loads(path.read_text("utf-8"))["requester"] == "e3001"


@pytest.mark.parametrize("reason, arguments", [
    ("unknown request", {"request_id": "REQ-999", "change": ["finance"], "justification": "x"}),
    ("group not managed", {"request_id": "REQ-001", "change": ["domain-admins"], "justification": "x"}),
    ("group not managed", {"request_id": "REQ-001", "change": ["finance", "root"], "justification": "x"}),
    ("group not requested: privileged",   # REQ-001 asked only for payments-initiate
     {"request_id": "REQ-001", "change": ["privileged"], "justification": "x"}),
    ("group not requested: finance",
     {"request_id": "REQ-001", "change": ["payments-initiate", "finance"], "justification": "x"}),
    ("invalid change list", {"request_id": "REQ-001", "change": [], "justification": "x"}),
    ("invalid change list", {"request_id": "REQ-001", "change": ["finance"] * 11, "justification": "x"}),
    ("invalid justification", {"request_id": "REQ-001", "change": ["finance"], "justification": "  "}),
    ("invalid justification", {"request_id": "REQ-001", "change": ["finance"],
                               "justification": "y" * 2001}),
])
def test_invalid_proposals_are_denied_and_write_nothing(env, reason, arguments):
    (result,) = call_tools(env, mint(env), [("propose_change", arguments)])
    assert result.is_error and reason in result_text(result)
    assert proposal_files(env) == []
    (line,) = audit_lines(env)
    assert (line["decision"], line["reason"]) == ("deny", reason)


def test_denial_text_does_not_echo_what_the_caller_sent(env):
    arguments = {"request_id": "REQ-ECHO-ME", "change": ["finance"], "justification": "x"}
    (result,) = call_tools(env, mint(env), [("propose_change", arguments)])
    assert "REQ-ECHO-ME" not in result_text(result)


# ---- AC5: audit ---------------------------------------------------------------------------

def test_one_audit_line_per_call_that_reaches_a_tool_or_the_verifier(env):
    secret_text = "SECRET-JUSTIFICATION-TEXT-12345"
    read_only = mint(env, scope="requests:read")
    full = mint(env)
    before = len(audit_lines(env))
    assert before == 0

    call_tools(env, read_only, [
        ("list_requests", {}),                                                 # allow
        ("propose_change", {"request_id": "REQ-001", "change": ["finance"],
                            "justification": secret_text}),                    # deny: scope
    ])
    call_tools(env, full, [
        ("propose_change", {"request_id": "REQ-004", "change": ["finance"],
                            "justification": secret_text}),                    # allow
        ("propose_change", {"request_id": "REQ-004", "change": ["nope"],
                            "justification": secret_text}),                    # deny: group
    ])
    assert post_initialize(env, mint(env, aud="wrong")) == 401                 # verifier line
    assert post_initialize(env, None) == 401                                   # no line (SDK)

    lines = audit_lines(env)
    assert len(lines) - before == 5
    assert [(line["tool"], line["decision"]) for line in lines] == [
        ("list_requests", "allow"), ("propose_change", "deny"),
        ("propose_change", "allow"), ("propose_change", "deny"), ("-", "deny")]
    for line in lines:
        assert set(line) == {"ts", "caller", "tool", "args_sha256", "decision", "reason"}

    text = env.settings.audit_file.read_text("utf-8")
    for forbidden in (secret_text, "REQ-004", "nope", read_only, full):
        assert forbidden not in text
    expected = hashlib.sha256(json.dumps(
        {"change": ["finance"], "justification": secret_text, "request_id": "REQ-004"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert lines[2]["args_sha256"] == expected
    assert lines[2]["caller"] == {"client_id": "agent-access-assistant",
                                  "subject": "service-account-agent"}


# ---- verifier internals -------------------------------------------------------------------

def test_jwks_is_cached_and_refetched_at_most_once_a_minute():
    key, other = new_key(), new_key()
    calls, now = [], [1000.0]

    def source():
        calls.append(now[0])
        return jwks_of((KID, key))

    verifier = server.KeycloakTokenVerifier(
        issuer="http://keycloak.test/realms/maple-harbour", audience="agent-passport",
        jwks_source=source, clock=lambda: now[0])
    env = SimpleNamespace(settings=server.Settings(kc_url="http://keycloak.test"), key=key)
    good = mint(env)
    unknown = mint(env, key=other, kid="rotated-key")

    assert asyncio.run(verifier.verify_token(good)) is not None
    assert asyncio.run(verifier.verify_token(good)) is not None
    assert len(calls) == 1                                   # cached
    for _ in range(3):
        assert asyncio.run(verifier.verify_token(unknown)) is None
    assert len(calls) == 1                                   # an unknown kid inside the minute: no refetch
    now[0] += 61
    assert asyncio.run(verifier.verify_token(unknown)) is None
    assert len(calls) == 2                                   # allowed again after a minute


def test_unreachable_keycloak_fails_closed():
    def source():
        raise OSError("connection refused")

    seen = []
    verifier = server.KeycloakTokenVerifier(
        issuer="http://keycloak.test/realms/maple-harbour", audience="agent-passport",
        jwks_source=source, on_reject=seen.append)
    key = new_key()
    env = SimpleNamespace(settings=server.Settings(kc_url="http://keycloak.test"), key=key)
    assert asyncio.run(verifier.verify_token(mint(env))) is None
    assert seen == ["signing keys unavailable"]


def test_keycloak_style_jwks_with_an_encryption_key_is_handled():
    key = new_key()
    jwks = jwks_of((KID, key))
    jwks["keys"].append({"kid": "enc", "kty": "RSA", "alg": "RSA-OAEP", "use": "enc",
                         "n": "AQAB", "e": "AQAB"})
    assert set(server._keys_from_jwks(jwks)) == {KID}


def test_settings_defaults_live_inside_the_passport_folder(monkeypatch):
    for name in ("AGENT_PASSPORT_REQUESTS", "AGENT_PASSPORT_PROPOSALS", "AGENT_PASSPORT_AUDIT",
                 "KC_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = server.Settings()
    assert settings.kc_url == "http://localhost:8080"
    assert settings.issuer == "http://localhost:8080/realms/maple-harbour"
    assert settings.jwks_url.endswith("/realms/maple-harbour/protocol/openid-connect/certs")
    for path in (settings.requests_file, settings.proposals_dir, settings.audit_file):
        assert server.HERE in path.parents
