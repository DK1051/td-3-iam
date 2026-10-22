#!/usr/bin/env bash
# keycloak-dev.sh - prepares a LOCAL, throwaway Keycloak dev server for the 3H lifecycle engine.
#
# It creates (and can safely be run again, because "already exists" is not an error):
#   - the realm "maple-harbour" with custom user attributes allowed
#   - the groups named in roles-map.yaml and the realm role "manager"
#   - the eight fictional staff accounts that already exist before the HR feed runs:
#     2 managers, 3 movers (in their OLD groups) and 3 leavers (still enabled)
#
# Settings (environment variables):
#   KC_URL             default http://localhost:8080
#   KC_ADMIN_USER      default admin
#   KC_ADMIN_PASSWORD  default dev-only-not-secret (a documented throwaway for a local test server)
#   KCADM              default /opt/keycloak/bin/kcadm.sh
#   PYTHON             default: .venv/bin/python in the repo if it exists, else python3
#
# The password reaches kcadm through the KC_CLI_PASSWORD environment variable, so it never
# appears on a command line (and so not in `ps`). kcadm keeps its login token in a temporary
# file that this script deletes when it ends; tokens are never printed.

set -euo pipefail

REALM=maple-harbour
KC_URL="${KC_URL:-http://localhost:8080}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIFECYCLE_DIR="$(dirname "$HERE")"
REPO_ROOT="$(dirname "$LIFECYCLE_DIR")"
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$REPO_ROOT/.venv/bin/python" ]; then PYTHON="$REPO_ROOT/.venv/bin/python"; else PYTHON=python3; fi
fi

export KC_CLI_PASSWORD="${KC_ADMIN_PASSWORD:-dev-only-not-secret}"
CONFIG_FILE="$(mktemp)"
trap 'rm -f "$CONFIG_FILE"' EXIT

# Run kcadm with our private config file. The "Picked up JAVA_TOOL_OPTIONS" noise is dropped.
kc() { "$KCADM" "$@" --config "$CONFIG_FILE" 2> >(grep -v '^Picked up JAVA_TOOL_OPTIONS' >&2); }

# Run a "create" command; treat "already exists" as fine. Any other failure stops the script.
# Sets CREATED=1 when something new was made, 0 when it already existed.
create_if_missing() {
  local label="$1"; shift
  local output
  if output="$(kc "$@" 2>&1)"; then
    CREATED=1; echo "created: $label"
  elif grep -qi "exist" <<<"$output"; then
    CREATED=0; echo "already exists: $label"
  else
    echo "FAILED: $label" >&2
    # Show the last line only: it is the error message, never a token.
    tail -n 1 <<<"$output" | grep -v '^Picked up' >&2 || true
    exit 1
  fi
}

# Look up one value (an id) with a "get ... --format csv --noquotes" command.
lookup() { kc "$@" --format csv --noquotes | head -n 1; }

echo "Logging in to $KC_URL as ${KC_ADMIN_USER:-admin} (password from the environment)"
kc config credentials --server "$KC_URL" --realm master --user "${KC_ADMIN_USER:-admin}" > /dev/null

create_if_missing "realm $REALM" create realms -s realm="$REALM" -s enabled=true

# Keycloak 24+ drops custom user attributes unless the realm's user profile allows them.
kc update users/profile -r "$REALM" -s unmanagedAttributePolicy=ENABLED
echo "user profile: custom (unmanaged) attributes enabled"

# The groups come from roles-map.yaml, so the file stays the single source of truth.
GROUPS_TO_MAKE="$(PYTHONPATH="$LIFECYCLE_DIR" "$PYTHON" -c "
from lifecycle.engine import load_roles_map
print('\n'.join(sorted(load_roles_map('$LIFECYCLE_DIR/roles-map.yaml').all_groups())))")"
while IFS= read -r group; do
  create_if_missing "group $group" create groups -r "$REALM" -s name="$group"
done <<<"$GROUPS_TO_MAKE"

# One lookup table of "group id,group name" lines, so memberships below match names exactly.
GROUP_TABLE="$(kc get groups -r "$REALM" --fields id,name --format csv --noquotes)"

create_if_missing "realm role manager" create roles -r "$REALM" -s name=manager \
  -s 'description=Appears as somebody'"'"'s manager in the HR feed (seeded here only)'

# The pre-existing staff. username|first|last|department|job title|manager id|groups|manager role
# Usernames are the lower-case employee ids; emails are fictional (mapleharbour.example).
SEED_USERS='
e1001|Elena|Marchetti|finance|Finance Manager||finance,payments-approve|yes
e1002|Samuel|Adeyemi|it|IT Manager||it|yes
e3001|Aisha|Rahman|member-services|Teller|E1001|member-services|no
e3002|Jonas|Weber|finance|Payments Officer|E1001|finance,payments-initiate|no
e3003|Mei-Lin|Wong|it|Helpdesk Analyst|E1002|it,helpdesk|no
e4001|Oliver|Grant|finance|Payments Officer|E1001|finance,payments-initiate|no
e4002|Fatima|Haddad|member-services|Teller|E1001|member-services|no
e4003|Dmitri|Kovac|it|IT Administrator|E1002|it,privileged|no
'
while IFS='|' read -r username first last department title manager_id groups manager_role; do
  [ -z "$username" ] && continue
  email="$(tr '[:upper:]' '[:lower:]' <<<"$first.$last" | tr -d '-')@mapleharbour.example"
  create_if_missing "user $username" create users -r "$REALM" \
    -s username="$username" -s enabled=true -s email="$email" \
    -s firstName="$first" -s lastName="$last" \
    -s "attributes.employee_id=${username^^}" -s "attributes.department=$department" \
    -s "attributes.job_title=$title" ${manager_id:+-s "attributes.manager_id=$manager_id"}
  # Memberships and the role are only set for a newly created user, so running this script
  # again never undoes changes the engine has made since.
  if [ "$CREATED" = 1 ]; then
    user_id="$(lookup get users -r "$REALM" -q "username=$username" --fields id)"
    IFS=',' read -ra group_list <<<"$groups"
    for group in "${group_list[@]}"; do
      group_id="$(awk -F, -v name="$group" '$2 == name { print $1 }' <<<"$GROUP_TABLE")"
      kc update "users/$user_id/groups/$group_id" -r "$REALM" \
        -s "realm=$REALM" -s "userId=$user_id" -s "groupId=$group_id" -n
    done
    if [ "$manager_role" = yes ]; then
      kc add-roles -r "$REALM" --uusername "$username" --rolename manager
    fi
  fi
done <<<"$SEED_USERS"

echo "Done. Realm $REALM is ready."
