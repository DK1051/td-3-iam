"""A thin client for the Keycloak Admin REST API (the web interface Keycloak offers to programs).

It offers only the calls the engine needs. There is deliberately NO call that deletes a user:
leavers are disabled so their record stays as evidence.

Settings come from environment variables:
  KC_URL             default http://localhost:8080
  KC_ADMIN_USER      default admin
  KC_ADMIN_PASSWORD  default dev-only-not-secret (a documented throwaway for a local test server)

The admin token is kept in memory only. Error messages carry the HTTP method, the status code
and the path with ids replaced by {id}; they never include a response body, because bodies can
contain ids and these logs can end up public.
"""

import os
import re

import httpx

_ID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class KeycloakError(Exception):
    """A call to Keycloak failed. The message has the method, status and path, never a body."""


def _safe_path(path: str) -> str:
    return _ID_PATTERN.sub("{id}", path)


def _one_value_each(attributes: dict | None) -> dict[str, str]:
    """Keycloak stores every user attribute as a list; the engine wants one value per name."""
    return {name: (values[0] if isinstance(values, list) and values else str(values))
            for name, values in (attributes or {}).items()}


class KeycloakClient:
    def __init__(self, realm: str, transport: httpx.BaseTransport | None = None):
        self.realm = realm
        self._admin_user = os.environ.get("KC_ADMIN_USER", "admin")
        self._admin_password = os.environ.get("KC_ADMIN_PASSWORD", "dev-only-not-secret")
        self._http = httpx.Client(
            base_url=os.environ.get("KC_URL", "http://localhost:8080"),
            timeout=15.0,
            transport=transport,
        )
        self._token: str | None = None  # in memory only; never printed or logged

    # ---- plumbing -------------------------------------------------------------------------

    def _get_token(self) -> str:
        path = "/realms/master/protocol/openid-connect/token"
        form = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self._admin_user,
            "password": self._admin_password,
        }
        try:
            response = self._http.post(path, data=form)
        except httpx.HTTPError as exc:
            raise KeycloakError(f"POST {path} failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise KeycloakError(f"POST {path} -> HTTP {response.status_code}")
        self._token = response.json()["access_token"]
        return self._token

    def _request(self, method: str, path: str, *, params=None, body=None, ok=(200,)):
        """Send one admin call. Gets a token first, and once more if Keycloak says it expired."""
        for attempt in (1, 2):
            token = self._token or self._get_token()
            try:
                response = self._http.request(
                    method, path, params=params, json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise KeycloakError(
                    f"{method} {_safe_path(path)} failed: {type(exc).__name__}"
                ) from None
            if response.status_code == 401 and attempt == 1:
                self._token = None  # admin tokens are short-lived; fetch a fresh one and retry
                continue
            if response.status_code not in ok:
                raise KeycloakError(
                    f"{method} {_safe_path(path)} -> HTTP {response.status_code}"
                )
            return response

    def _admin(self, suffix: str) -> str:
        return f"/admin/realms/{self.realm}{suffix}"

    # ---- users ----------------------------------------------------------------------------

    def get_user_by_username(self, username: str) -> dict | None:
        response = self._request("GET", self._admin("/users"),
                                 params={"username": username, "exact": "true"})
        for user in response.json():
            if user["username"] == username.lower():
                user["attributes"] = _one_value_each(user.get("attributes"))
                return user
        return None

    def create_user(self, username: str, *, email: str, first_name: str, last_name: str,
                    enabled: bool = True, attributes: dict | None = None) -> str:
        """Create a user and return its id."""
        body = {
            "username": username, "email": email, "firstName": first_name,
            "lastName": last_name, "enabled": enabled,
            "attributes": {name: [value] for name, value in (attributes or {}).items()},
        }
        response = self._request("POST", self._admin("/users"), body=body, ok=(201,))
        return response.headers["Location"].rstrip("/").split("/")[-1]

    def update_user(self, user_id: str, *, enabled: bool | None = None,
                    attributes: dict | None = None,
                    remove_attributes: list[str] | None = None) -> None:
        """Change the enabled flag, set attributes and/or remove some; others are kept."""
        path = self._admin(f"/users/{user_id}")
        user = self._request("GET", path).json()
        if enabled is not None:
            user["enabled"] = enabled
        merged = _one_value_each(user.get("attributes"))
        merged.update(attributes or {})
        for name in remove_attributes or []:
            merged.pop(name, None)
        user["attributes"] = {name: [value] for name, value in merged.items()}
        self._request("PUT", path, body=user, ok=(204,))

    # ---- groups ---------------------------------------------------------------------------

    def list_groups(self) -> list[dict]:
        return self._request("GET", self._admin("/groups"), params={"max": "1000"}).json()

    def user_groups(self, user_id: str) -> list[dict]:
        return self._request("GET", self._admin(f"/users/{user_id}/groups")).json()

    def add_user_to_group(self, user_id: str, group_id: str) -> None:
        self._request("PUT", self._admin(f"/users/{user_id}/groups/{group_id}"), ok=(204,))

    def remove_user_from_group(self, user_id: str, group_id: str) -> None:
        self._request("DELETE", self._admin(f"/users/{user_id}/groups/{group_id}"), ok=(204,))

    # ---- service accounts (Keycloak "clients") ---------------------------------------------

    def get_client_by_client_id(self, client_id: str) -> dict | None:
        response = self._request("GET", self._admin("/clients"), params={"clientId": client_id})
        for client in response.json():
            if client["clientId"] == client_id:
                return client
        return None

    def create_client(self, client_id: str, *, enabled: bool, attributes: dict) -> str:
        """Create a service-account client (no browser login, no public use) and return its id."""
        body = {
            "clientId": client_id,
            "enabled": enabled,
            "serviceAccountsEnabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "attributes": dict(attributes),
        }
        response = self._request("POST", self._admin("/clients"), body=body, ok=(201,))
        return response.headers["Location"].rstrip("/").split("/")[-1]

    def update_client(self, client_uuid: str, *, enabled: bool | None = None,
                      attributes: dict | None = None) -> None:
        path = self._admin(f"/clients/{client_uuid}")
        client = self._request("GET", path).json()
        if enabled is not None:
            client["enabled"] = enabled
        client["attributes"] = {**client.get("attributes", {}), **(attributes or {})}
        self._request("PUT", path, body=client, ok=(204,))
