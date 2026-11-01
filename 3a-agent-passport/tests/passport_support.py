"""Helpers for the Agent Passport unit tests: a throwaway RSA key, token minting, an in-process
client for the MCP server, and a copy of the sample requests in a temporary folder."""

import asyncio
import importlib.util
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import server

PASSPORT = Path(__file__).resolve().parents[1]
KID = "test-key-1"
MCP_URL = "http://127.0.0.1:8765/mcp"


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_of(*keys_by_kid):
    """A JWKS (the public-key list Keycloak publishes) for [(kid, private key), ...]."""
    entries = []
    for kid, key in keys_by_kid:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        entries.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": entries}


def make_env(tmp_path):
    """Settings pointing at tmp_path, a key, and a server whose verifier trusts only that key."""
    requests_file = tmp_path / "pending.json"
    shutil.copy(PASSPORT / "requests" / "pending.json", requests_file)
    settings = server.Settings(
        kc_url="http://keycloak.test", requests_file=requests_file,
        proposals_dir=tmp_path / "proposals", audit_file=tmp_path / "audit.jsonl",
    )
    key = new_key()
    audit = server.AuditLog(settings.audit_file)
    verifier = server.make_verifier(settings, audit, jwks_source=lambda: jwks_of((KID, key)))
    return SimpleNamespace(
        settings=settings, key=key, audit=audit, verifier=verifier,
        server=server.build_server(settings, verifier),
    )


def mint(env, *, key=None, kid=KID, alg="RS256", aud=server.AUDIENCE, iss=None, typ="Bearer",
         scope="requests:read requests:propose", expires_in=300, azp="agent-access-assistant",
         sub="service-account-agent", drop=(), extra=None):
    """Mint a token. `drop` lists claims to leave out; `extra` adds or overrides claims."""
    claims = {
        "iss": iss or env.settings.issuer, "aud": aud, "sub": sub, "typ": typ, "azp": azp,
        "scope": scope, "exp": int(time.time()) + expires_in, "iat": int(time.time()),
        **(extra or {}),
    }
    for name in drop:
        claims.pop(name, None)
    if alg == "RS256":
        return jwt.encode(claims, key or env.key, algorithm="RS256", headers={"kid": kid})
    if alg == "HS256":
        return jwt.encode(claims, "x" * 48, algorithm="HS256", headers={"kid": kid})
    return jwt.encode(claims, None, algorithm="none", headers={"kid": kid})


def audit_lines(env) -> list[dict]:
    if not env.settings.audit_file.exists():
        return []
    return [json.loads(line) for line in env.settings.audit_file.read_text("utf-8").splitlines()]


def _http(app, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                              base_url="http://127.0.0.1:8765", headers=headers)


def post_initialize(env, token) -> int:
    """Send a raw MCP 'initialize' request and return the HTTP status (401 = rejected)."""
    async def go():
        app = env.server.streamable_http_app()
        async with app.router.lifespan_context(app), _http(app, token) as http:
            response = await http.post(
                "/mcp", headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}})
            return response.status_code
    return asyncio.run(go())


def run_session(env, token, work):
    """Open an MCP client session with this token and run `work(client)` (an async function)."""
    async def go():
        app = env.server.streamable_http_app()
        async with app.router.lifespan_context(app), _http(app, token) as http:
            transport = streamable_http_client(MCP_URL, http_client=http)
            async with Client(transport) as client:
                return await work(client)
    return asyncio.run(go())


def call_tools(env, token, calls):
    """Make [(tool name, arguments), ...] in one session; returns the list of results."""
    async def work(client):
        return [await client.call_tool(name, args) for name, args in calls]
    return run_session(env, token, work)


def result_text(result) -> str:
    return " ".join(block.text for block in result.content if hasattr(block, "text"))


def load_approve():
    """Import scripts/approve.py (a script, not a package module) by its file path."""
    # importlib lets us load a Python file from a path we choose, without putting it on sys.path.
    spec = importlib.util.spec_from_file_location("approve_script",
                                                  PASSPORT / "scripts" / "approve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
