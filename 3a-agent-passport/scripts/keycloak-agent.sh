#!/usr/bin/env bash
# keycloak-agent.sh - adds the Agent Passport identities to the LOCAL, throwaway Keycloak dev server.
#
# Run 3h-lifecycle/scripts/keycloak-dev.sh first (it creates the realm maple-harbour and the realm
# role "manager"). This script can safely be run again: "already exists" is not an error, and
# the throwaway secret/password are set again every time.
#
# It creates, in realm maple-harbour:
#   - client scopes requests:read and requests:propose (they show up in the token's "scope" claim)
#   - the confidential client agent-access-assistant (the AI assistant's own identity: it logs in with
#     the client credentials grant, i.e. its own id and secret, no person involved)
#       * serviceAccountsEnabled=true, secret = the documented throwaway dev-only-not-secret
#       * default scopes: requests:read and requests:propose (plus Keycloak's built-in ones)
#       * an audience mapper that puts "agent-passport" into the token's aud (the MCP server checks it)
#   - the user manager.demo (fictional) with the realm role manager, password = the same throwaway
#   - the public client approve-cli (direct access grants = password login, used to get a manager
#     token for scripts/approve.py) with an audience mapper that puts "approve-cli" into aud
#
# Settings (environment variables): KC_URL, KC_ADMIN_USER, KC_ADMIN_PASSWORD, KCADM, as in
# keycloak-dev.sh. The admin password reaches kcadm through KC_CLI_PASSWORD, not a command line.
# The throwaway secret and password below ARE on kcadm command lines (kcadm has no other way to set
# a password); they protect nothing: this server is local and is deleted afterwards.
#
# Prints object names only, never a token or a secret.
#
# TODO(verify): written without a Keycloak to run it against (none in the authoring session). Check
# on first run: the kcadm option syntax, that the secret update takes effect, and the token claims
# (azp, typ, scope, aud, realm_access.roles) with the integration tests.

set -euo pipefail

REALM=maple-harbour
KC_URL="${KC_URL:-http://localhost:8080}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
THROWAWAY=dev-only-not-secret
AGENT_CLIENT=agent-access-assistant
APPROVE_CLIENT=approve-cli
MANAGER_USER=manager.demo

export KC_CLI_PASSWORD="${KC_ADMIN_PASSWORD:-dev-only-not-secret}"
CONFIG_FILE="$(mktemp)"
ERROR_FILE="$(mktemp)"
trap 'rm -f "$CONFIG_FILE" "$ERROR_FILE"' EXIT

# Run kcadm with our private config file, reading nothing from the keyboard.
kc() {
  local status=0
  "$KCADM" "$@" --config "$CONFIG_FILE" 2> "$ERROR_FILE" < /dev/null || status=$?
  grep -v '^Picked up JAVA_TOOL_OPTIONS' "$ERROR_FILE" >&2 || true
  return "$status"
}

# Run a "create" command and say what happened ("exists" or HTTP 409 Conflict is fine).
create_if_missing() {
  local label="$1"; shift
  local output
  if output="$(kc "$@" 2>&1)"; then
    echo "created: $label"
  elif grep -qiE "exist|409|conflict" <<<"$output"; then
    echo "already exists: $label"
  else
    echo "FAILED: $label" >&2
    tail -n 1 <<<"$output" >&2   # the last line is the error message, never a token
    exit 1
  fi
}

lookup() { kc "$@" --format csv --noquotes | head -n 1; }

echo "Logging in to $KC_URL as ${KC_ADMIN_USER:-admin} (password from the environment)"
kc config credentials --server "$KC_URL" --realm master --user "${KC_ADMIN_USER:-admin}" > /dev/null

if [ -z "$(lookup get "realms/$REALM" --fields realm)" ]; then
  echo "FAILED: realm $REALM not found; run 3h-lifecycle/scripts/keycloak-dev.sh first" >&2
  exit 1
fi
if [ -z "$(lookup get roles/manager -r "$REALM" --fields name)" ]; then
  echo "FAILED: realm role manager not found; run 3h-lifecycle/scripts/keycloak-dev.sh first" >&2
  exit 1
fi

# ---- client scopes ------------------------------------------------------------------------
for scope in requests:read requests:propose; do
  create_if_missing "client scope $scope" create client-scopes -r "$REALM" \
    -s name="$scope" -s protocol=openid-connect \
    -s 'attributes."include.in.token.scope"=true' \
    -s 'attributes."display.on.consent.screen"=false'
done
SCOPE_TABLE="$(kc get client-scopes -r "$REALM" --fields id,name --format csv --noquotes)"
scope_id() { awk -F, -v name="$1" '$2 == name { print $1 }' <<<"$SCOPE_TABLE"; }

# A token audience mapper: "put <audience> into aud of the access token" (not the ID token).
add_audience_mapper() {   # client uuid, mapper name, audience
  create_if_missing "audience mapper $2" create "clients/$1/protocol-mappers/models" -r "$REALM" \
    -s name="$2" -s protocol=openid-connect -s protocolMapper=oidc-audience-mapper \
    -s consentRequired=false \
    -s "config.\"included.custom.audience\"=$3" \
    -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=false'
}

# ---- the assistant's client ---------------------------------------------------------------
create_if_missing "client $AGENT_CLIENT" create clients -r "$REALM" \
  -s clientId="$AGENT_CLIENT" -s enabled=true -s publicClient=false \
  -s clientAuthenticatorType=client-secret -s serviceAccountsEnabled=true \
  -s standardFlowEnabled=false -s directAccessGrantsEnabled=false
AGENT_ID="$(lookup get clients -r "$REALM" -q clientId="$AGENT_CLIENT" --fields id)"
kc update "clients/$AGENT_ID" -r "$REALM" -s secret="$THROWAWAY"
echo "set: throwaway secret of client $AGENT_CLIENT"
for scope in requests:read requests:propose; do
  kc update "clients/$AGENT_ID/default-client-scopes/$(scope_id "$scope")" -r "$REALM" \
    -s "realm=$REALM" -s "clientId=$AGENT_ID" -s "clientScopeId=$(scope_id "$scope")" -n
  echo "default scope of $AGENT_CLIENT: $scope"
done
add_audience_mapper "$AGENT_ID" agent-passport-audience agent-passport

# ---- the demo manager and the approve-cli client ------------------------------------------
create_if_missing "user $MANAGER_USER" create users -r "$REALM" \
  -s username="$MANAGER_USER" -s enabled=true -s email="$MANAGER_USER@mapleharbour.example" \
  -s firstName=Manager -s lastName=Demo
kc set-password -r "$REALM" --username "$MANAGER_USER" --new-password "$THROWAWAY"
echo "set: throwaway password of user $MANAGER_USER"
kc add-roles -r "$REALM" --uusername "$MANAGER_USER" --rolename manager
echo "realm role manager: $MANAGER_USER"

create_if_missing "client $APPROVE_CLIENT" create clients -r "$REALM" \
  -s clientId="$APPROVE_CLIENT" -s enabled=true -s publicClient=true \
  -s directAccessGrantsEnabled=true -s standardFlowEnabled=false -s serviceAccountsEnabled=false
APPROVE_ID="$(lookup get clients -r "$REALM" -q clientId="$APPROVE_CLIENT" --fields id)"
add_audience_mapper "$APPROVE_ID" approve-cli-audience "$APPROVE_CLIENT"

echo "Done. Agent Passport identities are ready in realm $REALM."
