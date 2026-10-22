#!/usr/bin/env bash
# keycloak-dev.sh - prepares a LOCAL, throwaway Keycloak dev server for the 3H lifecycle engine.
#
# It creates (and can safely be run again, because "already exists" is not an error):
#   - the realm "maple-harbour" with custom user attributes allowed
#   - the groups named in roles-map.yaml and the realm role "manager"
#   - the eight fictional staff accounts that already exist before the HR feed runs:
#     2 managers, 3 movers (in their OLD groups) and 3 leavers (still enabled)
#
# Usage: keycloak-dev.sh [--reset]
#   --reset  first DELETES the realm maple-harbour (local servers only), so you start clean.
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

# Run kcadm with our private config file. It reads nothing from the keyboard (< /dev/null), so it
# can never swallow the lines of a loop. The "Picked up JAVA_TOOL_OPTIONS" noise is dropped.
ERROR_FILE="$(mktemp)"
trap 'rm -f "$CONFIG_FILE" "$ERROR_FILE"' EXIT
kc() {
  local status=0
  "$KCADM" "$@" --config "$CONFIG_FILE" 2> "$ERROR_FILE" < /dev/null || status=$?
  grep -v '^Picked up JAVA_TOOL_OPTIONS' "$ERROR_FILE" >&2 || true
  return "$status"
}

# Run a "create" command and say what happened. Sets CREATED=1 when something new was made and
# CREATED=0 when the thing already existed (Keycloak answers "exists" or HTTP 409 Conflict).
# Any other failure stops the script. With the 2nd argument "strict", "exists" is an error too:
# used for users, where "exists" can mean a DIFFERENT user already has the same email.
create_if_missing() {
  local label="$1" mode="$2"; shift 2
  local output
  if output="$(kc "$@" 2>&1)"; then
    CREATED=1; echo "created: $label"
  elif [ "$mode" != strict ] && grep -qiE "exist|409|conflict" <<<"$output"; then
    CREATED=0; echo "already exists: $label"
  else
    echo "FAILED: $label" >&2
    # Show the last line only: it is the error message, never a token.
    tail -n 1 <<<"$output" >&2
    exit 1
  fi
}

# Look up one value (an id) with a "get ... --format csv --noquotes" command.
lookup() { kc "$@" --format csv --noquotes | head -n 1; }

echo "Logging in to $KC_URL as ${KC_ADMIN_USER:-admin} (password from the environment)"
kc config credentials --server "$KC_URL" --realm master --user "${KC_ADMIN_USER:-admin}" > /dev/null

if [ "${1:-}" = "--reset" ]; then
  case "$KC_URL" in
    http://localhost:*|http://127.0.0.1:*) ;;
    *) echo "REFUSED: --reset only works on a local server, not $KC_URL" >&2; exit 1 ;;
  esac
  if kc delete "realms/$REALM" > /dev/null 2>&1; then echo "deleted: realm $REALM"; fi
fi

create_if_missing "realm $REALM" lenient create realms -s realm="$REALM" -s enabled=true

# Keycloak 24+ drops custom user attributes unless the realm's user profile allows them.
kc update users/profile -r "$REALM" -s unmanagedAttributePolicy=ENABLED
echo "user profile: custom (unmanaged) attributes enabled"

# The groups come from roles-map.yaml, so the file stays the single source of truth.
GROUPS_TO_MAKE="$(PYTHONPATH="$LIFECYCLE_DIR" "$PYTHON" -c "
from lifecycle.engine import load_roles_map
print('\n'.join(sorted(load_roles_map('$LIFECYCLE_DIR/roles-map.yaml').all_groups())))")"
while IFS= read -r group; do
  create_if_missing "group $group" lenient create groups -r "$REALM" -s name="$group"
done <<<"$GROUPS_TO_MAKE"

# One lookup table of "group id,group name" lines, so memberships below match names exactly.
GROUP_TABLE="$(kc get groups -r "$REALM" --fields id,name --format csv --noquotes)"

create_if_missing "realm role manager" lenient create roles -r "$REALM" -s name=manager \
  -s 'description=Appears as somebody'"'"'s manager in the HR feed (seeded here only)'

# The pre-existing staff.
# employee id|first|last|department|job title|manager id|groups|manager role
# The Keycloak username is the employee id in lower case; emails are fictional.
SEED_USERS='
E1001|Elena|Marchetti|finance|Finance Manager||finance,payments-approve|yes
E1002|Samuel|Adeyemi|it|IT Manager||it|yes
E3001|Aisha|Rahman|member-services|Teller|E1001|member-services|no
E3002|Jonas|Weber|finance|Payments Officer|E1001|finance,payments-initiate|no
E3003|Mei-Lin|Wong|it|Helpdesk Analyst|E1002|it,helpdesk|no
E4001|Oliver|Grant|finance|Payments Officer|E1001|finance,payments-initiate|no
E4002|Fatima|Haddad|member-services|Teller|E1001|member-services|no
E4003|Dmitri|Kovac|it|IT Administrator|E1002|it,privileged|no
'
while IFS='|' read -r employee_id first last department title manager_id groups manager_role; do
  [ -z "$employee_id" ] && continue
  username="$(echo "$employee_id" | tr '[:upper:]' '[:lower:]')"
  email="$(echo "$first.$last" | tr '[:upper:]' '[:lower:]' | tr -d '-')@mapleharbour.example"
  manager_option=()
  if [ -n "$manager_id" ]; then manager_option=(-s "attributes.manager_id=$manager_id"); fi

  # Look the username up first. If it is there, leave the user alone. If it is not, creating it
  # must work: "exists" at that point means another user has the same email, which is an error.
  existing_id="$(lookup get users -r "$REALM" -q "username=$username" -q exact=true --fields id)"
  if [ -n "$existing_id" ]; then
    echo "already exists: user $username"
    continue
  fi
  create_if_missing "user $username" strict create users -r "$REALM" \
    -s username="$username" -s enabled=true -s email="$email" \
    -s firstName="$first" -s lastName="$last" \
    -s "attributes.employee_id=$employee_id" -s "attributes.department=$department" \
    -s "attributes.job_title=$title" "${manager_option[@]}"

  # Memberships and the role are only set for a newly created user, so running this script
  # again never undoes changes the engine has made since.
  user_id="$(lookup get users -r "$REALM" -q "username=$username" -q exact=true --fields id)"
  IFS=',' read -ra group_list <<<"$groups"
  for group in "${group_list[@]}"; do
    group_id="$(awk -F, -v name="$group" '$2 == name { print $1 }' <<<"$GROUP_TABLE")"
    kc update "users/$user_id/groups/$group_id" -r "$REALM" \
      -s "realm=$REALM" -s "userId=$user_id" -s "groupId=$group_id" -n
  done
  if [ "$manager_role" = yes ]; then
    kc add-roles -r "$REALM" --uusername "$username" --rolename manager
  fi
done <<<"$SEED_USERS"

echo "Done. Realm $REALM is ready."
