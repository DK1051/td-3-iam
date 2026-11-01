"""The Agent Passport MCP server (design: DESIGN.md).

MCP (Model Context Protocol) is a standard way to give an AI model a fixed menu of tools over
HTTP. This server's menu has exactly two tools, `list_requests` and `propose_change`. There is
deliberately NO tool that grants access: a grant happens only when a human manager runs
scripts/approve.py.

Run it:  python server.py     (listens on 127.0.0.1:8765; Keycloak is expected at KC_URL)

Settings (environment variables; the defaults live inside 3a-agent-passport/):
  KC_URL                     default http://localhost:8080
  AGENT_PASSPORT_REQUESTS    default requests/pending.json
  AGENT_PASSPORT_PROPOSALS   default proposals/
  AGENT_PASSPORT_AUDIT       default audit.jsonl

This implements MCP-style token checks; it is not a full MCP authorization-spec conformance claim.
"""

import asyncio
import json
import os
import sys
import time
import uuid
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from audit import AuditLog

HERE = Path(__file__).resolve().parent
REALM = "maple-harbour"
AUDIENCE = "agent-passport"
RESOURCE_URL = "http://localhost:8765/mcp"
SCOPE_READ = "requests:read"
SCOPE_PROPOSE = "requests:propose"
MAX_GROUPS = 10
MAX_JUSTIFICATION = 2000
JWKS_REFETCH_SECONDS = 60.0


# ---- settings -----------------------------------------------------------------------------

def managed_groups() -> set[str]:
    """The groups the 3H engine manages (roles-map.yaml is the single source of truth)."""
    lifecycle_dir = str(HERE.parent / "3h-lifecycle")
    if lifecycle_dir not in sys.path:  # so `python server.py` works without PYTHONPATH
        sys.path.append(lifecycle_dir)
    from lifecycle.engine import load_roles_map  # 3H code, imported not copied
    with warnings.catch_warnings():
        # 3H warns about its payments-ops demo pair; that is expected and irrelevant here.
        warnings.simplefilter("ignore")
        return set(load_roles_map(HERE.parent / "3h-lifecycle" / "roles-map.yaml").managed_groups)


@dataclass
class Settings:
    kc_url: str = field(default_factory=lambda: os.environ.get("KC_URL", "http://localhost:8080"))
    requests_file: Path = field(default_factory=lambda: Path(os.environ.get(
        "AGENT_PASSPORT_REQUESTS", HERE / "requests" / "pending.json")))
    proposals_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "AGENT_PASSPORT_PROPOSALS", HERE / "proposals")))
    audit_file: Path = field(default_factory=lambda: Path(os.environ.get(
        "AGENT_PASSPORT_AUDIT", HERE / "audit.jsonl")))

    @property
    def issuer(self) -> str:
        return f"{self.kc_url.rstrip('/')}/realms/{REALM}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"


# ---- token checks -------------------------------------------------------------------------

class TokenRejected(Exception):
    """The token failed a check. The message is a short fixed phrase, safe to audit."""


def fetch_jwks(url: str) -> dict:
    """Download the realm's public keys (the JWKS: JSON Web Key Set). Blocking; called in a thread."""
    import httpx
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()


class KeycloakTokenVerifier:
    """Checks a bearer token the way DESIGN.md section 3 says. Any failure means "no" (fail closed).

    `jwks_source` is a function returning the JWKS as a dict; tests pass a fake one. The keys are
    cached, and refetched at most once per `refetch_seconds` when a token names an unknown key id.
    `on_reject(reason)` is called for every rejected token (the server uses it for the audit log).
    """

    def __init__(self, *, issuer: str, audience: str, jwks_source: Callable[[], dict],
                 on_reject: Callable[[str], None] | None = None,
                 refetch_seconds: float = JWKS_REFETCH_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.issuer = issuer
        self.audience = audience
        self._jwks_source = jwks_source
        self._on_reject = on_reject
        self._refetch_seconds = refetch_seconds
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._last_fetch: float | None = None
        self._lock = asyncio.Lock()

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await self.verify(token)
        except TokenRejected as exc:
            if self._on_reject:
                self._on_reject(str(exc))
            return None
        except Exception:  # noqa: BLE001 - anything unexpected is also a "no"; never let it become a "yes"
            if self._on_reject:
                self._on_reject("token check failed")
            return None

    async def verify(self, token: str) -> AccessToken:
        """Return the AccessToken or raise TokenRejected with the reason."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenRejected("malformed token") from None
        if header.get("alg") != "RS256":  # also rejects "none" and HS256 before any key is used
            raise TokenRejected("unsupported algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenRejected("no key id")
        key = await self._key_for(kid)
        try:
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise TokenRejected("token expired") from None
        except jwt.InvalidAudienceError:
            raise TokenRejected("invalid audience") from None
        except jwt.InvalidIssuerError:
            raise TokenRejected("invalid issuer") from None
        except jwt.InvalidSignatureError:
            raise TokenRejected("invalid signature") from None
        except jwt.PyJWTError:
            raise TokenRejected("invalid token") from None
        # Keycloak marks access tokens "Bearer" and ID tokens "ID". An ID token's audience is its
        # own client id, but requiring "Bearer" keeps any other kind of token out as well.
        # TODO(verify): the `typ` claim is "Bearer" in a real Keycloak access token.
        if claims.get("typ") != "Bearer":
            raise TokenRejected("not an access token")
        # TODO(verify): Keycloak puts the client id in `azp` for client-credentials tokens
        # (read it from a real token); `client_id` is the fallback some servers use.
        client_id = claims.get("azp") or claims.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise TokenRejected("no client id")
        scope = claims.get("scope", "")
        if not isinstance(scope, str):
            raise TokenRejected("invalid scope claim")
        expires_at = claims["exp"]
        if not isinstance(expires_at, int | float):
            raise TokenRejected("invalid token")
        return AccessToken(
            token=token, client_id=client_id, scopes=scope.split(), expires_at=int(expires_at),
            resource=self.audience, subject=str(claims["sub"]), claims=claims,
        )

    async def _key_for(self, kid: str) -> Any:
        async with self._lock:
            if kid not in self._keys:
                now = self._clock()
                if self._last_fetch is not None and now - self._last_fetch < self._refetch_seconds:
                    raise TokenRejected("unknown key id")
                self._last_fetch = now
                try:
                    jwks = await asyncio.to_thread(self._jwks_source)
                    self._keys = _keys_from_jwks(jwks)
                except Exception:  # noqa: BLE001 - any download/parse failure fails closed
                    raise TokenRejected("signing keys unavailable") from None
            if kid not in self._keys:
                raise TokenRejected("unknown key id")
            return self._keys[kid]


def _keys_from_jwks(jwks: dict) -> dict[str, Any]:
    """kid -> public key, for the RSA signing keys only (Keycloak also lists an encryption key)."""
    keys: dict[str, Any] = {}
    for entry in jwks.get("keys", []):
        if entry.get("kty") != "RSA" or entry.get("use", "sig") != "sig" or not entry.get("kid"):
            continue
        try:
            keys[entry["kid"]] = jwt.PyJWK(entry).key
        except jwt.PyJWTError:
            continue
    return keys


def make_verifier(settings: Settings, audit: AuditLog | None = None, *, audience: str = AUDIENCE,
                  jwks_source: Callable[[], dict] | None = None) -> KeycloakTokenVerifier:
    """The verifier used by the server (and, with audience "approve-cli", by approve.py)."""
    on_reject = None
    if audit is not None:
        def on_reject(reason: str) -> None:
            audit.record(tool="-", decision="deny", reason=reason)
    return KeycloakTokenVerifier(
        issuer=settings.issuer, audience=audience, on_reject=on_reject,
        jwks_source=jwks_source or (lambda: fetch_jwks(settings.jwks_url)),
    )


# ---- the server ---------------------------------------------------------------------------

class Denied(ToolError):
    """A tool call was refused (a ToolError, so the SDK sends the message back as a tool error
    instead of hiding it). The message goes back to the caller and into the audit log, so it
    must be a fixed phrase that does not repeat anything the caller sent."""


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write to a temporary file in the same folder, then rename: readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_requests(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(data["requests"])
    except (OSError, ValueError, KeyError, TypeError):
        raise Denied("requests unavailable") from None


def build_server(settings: Settings | None = None,
                 verifier: KeycloakTokenVerifier | None = None) -> MCPServer:
    settings = settings or Settings()
    audit = AuditLog(settings.audit_file)
    verifier = verifier or make_verifier(settings, audit)
    allowed_groups = managed_groups()

    server = MCPServer(
        "agent-passport",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=settings.issuer,  # type: ignore[arg-type]
            resource_server_url=RESOURCE_URL,  # type: ignore[arg-type]
            required_scopes=[SCOPE_READ],
            # False on purpose: our verifier checks the token's audience itself (aud must contain
            # "agent-passport"); the SDK's own check compares against the server URL instead.
            validate_token_resource=False,
        ),
    )

    def caller_of(tool: str, args: dict, scope: str) -> AccessToken:
        """The verified caller, or a refusal. Writes the deny line itself (allow lines are
        written by the tool once it has done its work)."""
        token = get_access_token()
        if token is None:  # should not happen: the middleware rejects calls without a token
            audit.record(tool=tool, decision="deny", reason="no caller", args=args)
            raise Denied("no caller")
        if scope not in token.scopes:
            reason = f"missing scope {scope}"
            audit.record(tool=tool, decision="deny", reason=reason, args=args,
                         client_id=token.client_id, subject=token.subject)
            raise Denied(reason)
        return token

    def refuse(tool: str, args: dict, token: AccessToken, reason: str) -> Denied:
        audit.record(tool=tool, decision="deny", reason=reason, args=args,
                     client_id=token.client_id, subject=token.subject)
        return Denied(reason)

    @server.tool()
    def list_requests() -> dict[str, Any]:
        """List the pending access requests (needs scope requests:read)."""
        args: dict = {}
        token = caller_of("list_requests", args, SCOPE_READ)
        try:
            requests = load_requests(settings.requests_file)
        except Denied as exc:
            raise refuse("list_requests", args, token, str(exc)) from None
        audit.record(tool="list_requests", decision="allow", reason="ok", args=args,
                     client_id=token.client_id, subject=token.subject)
        return {"requests": requests}

    @server.tool()
    def propose_change(request_id: str, change: list[str], justification: str) -> dict[str, Any]:
        """Propose adding groups (`change`) to the requester of one pending request. This only
        writes a proposal for a human manager to review; it changes no access.
        Needs scope requests:propose."""
        args = {"request_id": request_id, "change": change, "justification": justification}
        token = caller_of("propose_change", args, SCOPE_PROPOSE)

        if not change or len(change) > MAX_GROUPS:
            raise refuse("propose_change", args, token, "invalid change list")
        if not justification.strip() or len(justification) > MAX_JUSTIFICATION:
            raise refuse("propose_change", args, token, "invalid justification")
        try:
            requests = load_requests(settings.requests_file)
        except Denied as exc:
            raise refuse("propose_change", args, token, str(exc)) from None
        request = next((r for r in requests if r.get("id") == request_id), None)
        if request is None:
            raise refuse("propose_change", args, token, "unknown request")
        if any(group not in allowed_groups for group in change):
            raise refuse("propose_change", args, token, "group not managed")
        # The assistant may only propose groups the person actually asked for.
        # (The name is safe to repeat: it already passed the managed-groups check above.)
        asked_for = set(request.get("requested_groups", []))
        extra = next((group for group in change if group not in asked_for), None)
        if extra is not None:
            raise refuse("propose_change", args, token, f"group not requested: {extra}")

        proposal_id = str(uuid.uuid4())
        proposal = {
            "id": proposal_id,
            "request_id": request_id,
            "requester": request["requester"],  # from pending.json, never from the agent
            "proposed_groups": list(dict.fromkeys(change)),
            "justification": justification,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "created_by": token.client_id,
            "status": "pending",
        }
        _atomic_write_json(settings.proposals_dir / f"{proposal_id}.json", proposal)
        audit.record(tool="propose_change", decision="allow", reason="ok", args=args,
                     client_id=token.client_id, subject=token.subject)
        return {"proposal_id": proposal_id, "status": "pending"}

    return server


def main() -> None:
    server = build_server()
    server.run(transport="streamable-http", host="127.0.0.1", port=8765)


if __name__ == "__main__":
    sys.exit(main())
