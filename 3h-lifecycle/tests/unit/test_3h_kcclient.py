"""Tests for lifecycle.kc using httpx's built-in mock transport (still no network)."""

import json

import httpx
import pytest

from lifecycle.kc import KeycloakClient, KeycloakError

USER_ID = "3f1c9e0a-5b7d-4c2e-9a41-0d6e8b7f2a11"
TOKEN = "super-secret-token-value"
BODY_TEXT = "BODY-WITH-OBJECT-ID-9999"


def client_with(handler):
    return KeycloakClient("maple-harbour", transport=httpx.MockTransport(handler))


def token_response():
    return httpx.Response(200, json={"access_token": TOKEN})


def test_token_request_uses_the_admin_cli_password_grant():
    seen = {}

    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            seen["form"] = request.content.decode()
            return token_response()
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=[])

    assert client_with(handler).get_user_by_username("e1") is None
    assert "grant_type=password" in seen["form"] and "client_id=admin-cli" in seen["form"]
    assert seen["auth"] == f"Bearer {TOKEN}"


def test_expired_token_is_replaced_once():
    calls = {"tokens": 0, "users": 0}

    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            calls["tokens"] += 1
            return token_response()
        calls["users"] += 1
        return httpx.Response(401) if calls["users"] == 1 else httpx.Response(200, json=[])

    assert client_with(handler).get_user_by_username("e1") is None
    assert calls == {"tokens": 2, "users": 2}


def test_errors_carry_method_status_and_path_but_no_ids_body_or_token():
    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            return token_response()
        return httpx.Response(500, text=BODY_TEXT)

    with pytest.raises(KeycloakError) as error:
        client_with(handler).add_user_to_group(USER_ID, USER_ID)
    message = str(error.value)
    assert message == ("PUT /admin/realms/maple-harbour/users/{id}/groups/{id} -> HTTP 500")
    for secret in (USER_ID, BODY_TEXT, TOKEN):
        assert secret not in message


def test_failed_login_message_has_only_the_status():
    def handler(request):
        return httpx.Response(401, text=BODY_TEXT)

    with pytest.raises(KeycloakError) as error:
        client_with(handler).list_groups()
    assert str(error.value) == "POST /realms/master/protocol/openid-connect/token -> HTTP 401"


def test_network_failure_names_only_the_exception_type():
    def handler(request):
        raise httpx.ConnectError("connection refused to some-internal-host")

    with pytest.raises(KeycloakError) as error:
        client_with(handler).list_groups()
    assert str(error.value).endswith("failed: ConnectError")
    assert "internal-host" not in str(error.value)


def test_attributes_are_flattened_on_read_and_listed_on_write():
    sent = {}

    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            return token_response()
        if request.method == "GET" and request.url.path.endswith("/users"):
            return httpx.Response(200, json=[{"id": USER_ID, "username": "e1", "enabled": True,
                                              "attributes": {"department": ["it"]}}])
        if request.method == "GET":
            return httpx.Response(200, json={"id": USER_ID, "enabled": True,
                                             "attributes": {"department": ["it"]}})
        sent["body"] = json.loads(request.content)
        return httpx.Response(204)

    kc = client_with(handler)
    assert kc.get_user_by_username("E1")["attributes"] == {"department": "it"}
    kc.update_user(USER_ID, enabled=False, attributes={"disabled_on": "2026-10-16"})
    assert sent["body"]["enabled"] is False
    assert sent["body"]["attributes"] == {"department": ["it"], "disabled_on": ["2026-10-16"]}


def test_create_user_returns_the_id_from_the_location_header():
    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            return token_response()
        return httpx.Response(201, headers={"Location": f"http://x/admin/realms/r/users/{USER_ID}"})

    kc = client_with(handler)
    assert kc.create_user("e1", email="a@mapleharbour.example", first_name="A", last_name="B") == USER_ID


def test_create_client_asks_for_a_service_account_with_no_browser_login():
    sent = {}

    def handler(request):
        if request.url.path.endswith("/openid-connect/token"):
            return token_response()
        sent["body"] = json.loads(request.content)
        return httpx.Response(201, headers={"Location": "http://x/clients/abc"})

    client_with(handler).create_client("svc-x", enabled=False, attributes={"owner": "E1001"})
    assert sent["body"] == {"clientId": "svc-x", "enabled": False, "serviceAccountsEnabled": True,
                            "publicClient": False, "standardFlowEnabled": False,
                            "attributes": {"owner": "E1001"}}
