# 3H Lifecycle for People and Service Accounts

Status: core engine built (session T3-S02). The identity-proofing gate, separation-of-duties rules and
access attestation are not built yet; they come in T3-S03.

## What it does

When a company hires, moves or loses staff, their computer accounts must change to match. Doing that by hand is how
people end up with access they should no longer have (a classic cause of account takeover and of audit findings).
This project is a small Python program that reads an HR file and makes the directory match it.

The "directory" here is **Keycloak**, an open-source identity server. It stands in for a corporate directory such
as Microsoft Entra. Everything runs on a local test server with made-up data for a fictional credit union, Maple
Harbour (`mapleharbour.example`).

Words used below:

- **Joiner**: someone new. The engine creates their account and puts them in the right groups.
- **Mover**: someone who already has an account and changes department or job title. Their groups are made equal to
  what the new role needs: missing groups are added and groups they no longer need are removed.
- **Leaver**: someone who left. Their account is **disabled, never deleted**. Their group memberships are kept
  as evidence, and the engine records the date in an attribute called `disabled_on`.
- **Service account**: an account used by a program, not a person (for example a nightly job). Here each one is
  a Keycloak "client" with an owner, a purpose and an expiry date.
- **Group**: a named set of permissions in Keycloak. `roles-map.yaml` says which groups each department and job
  title gets (for example the job title *Payments Officer* gets `payments-initiate`).
- **Managed group**: a group the engine is allowed to add or remove. `roles-map.yaml` lists them all in
  `managed_groups`, including old groups no longer handed out. Any group not on that list is never touched.
- **Idempotent** (safe to repeat): running the engine twice with the same HR file changes nothing the second
  time. This is what makes it safe to run on a schedule or after a crash.

How it works, in two steps so nothing changes by accident:

1. `plan` reads Keycloak (read-only), compares it with the HR file and prints a table of what would change.
2. `apply` makes those changes and prints a count per action type. `apply --dry-run` behaves exactly like `plan`.

Rules that came out of design decisions:

- A joiner whose start date is still in the future is created **disabled**, with a marker attribute
  `pending_start=<start date>`. On or after that date, the next run enables the account and removes the marker.
  Only an account carrying the marker is ever enabled by the engine, so an account that an administrator disabled is
  never switched back on (it is reported as `SKIPPED`; this also covers a re-hire, which needs a person to review it).
- A leaver is disabled **now**, even if their end date is still in the future. The plan says `leaves on <date>`
  or `left <date>`. This fails safe: better to cut access early than late.
- A service account whose expiry date has passed is created **disabled**, or switched to disabled if it was
  enabled. The plan shows `expired on <date>`. The engine **never switches a disabled service account back
  on**, even if the owner later extends the expiry date or the date is still in the future: the plan says
  `SKIPPED disabled by an admin <client id>` and a person enables it by hand.
- A joiner whose account already exists and is enabled before the start date is disabled until then
  (`disable until start <date>`), with the same marker.
- A mover whose account is disabled still gets their group changes, so the record stays accurate; the plan line
  ends with `(account disabled)`. The account stays disabled.
- A mover or leaver with no account in Keycloak is reported as `SKIPPED unknown user <employee id>` and never
  created by accident.
- Anyone who gains the `privileged` group (powerful admin access) has `PRIVILEGED` at the end of their plan line.
- The Keycloak username is the lower-case employee id, which does not change when a name changes.

## How to run it

All commands run from the repository root. You need Python 3.12 or newer.

```bash
# 1. One-time: a private Python environment (never install packages system-wide)
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

# 2. Start a local Keycloak (about 45 seconds the first time) in the background
nohup env KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD=dev-only-not-secret \
  /opt/keycloak/bin/kc.sh start-dev --http-port=8080 > /tmp/keycloak.log 2>&1 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/realms/master   # wait for 200

# 3. Create the realm, groups, role and the eight existing staff accounts (safe to run again)
bash 3h-lifecycle/scripts/keycloak-dev.sh
#    Add --reset to delete realm maple-harbour first and start clean. It refuses to run
#    against anything but localhost.

# 4. See what would change, then change it, then see that nothing is left to do
export PYTHONPATH=3h-lifecycle
FILES="--feed 3h-lifecycle/hr/hr-feed.csv --service-accounts 3h-lifecycle/hr/service-accounts.csv --realm maple-harbour"
python -m lifecycle plan  $FILES --today 2026-10-22
python -m lifecycle apply $FILES --today 2026-10-22
python -m lifecycle plan  $FILES --today 2026-10-22     # prints "nothing to do"

# 5. Later: pretend it is after the joiners' start dates and apply again
python -m lifecycle apply $FILES --today 2026-11-20
```

- `--today YYYY-MM-DD` pretends it is that day (default: the real date). It decides whether a joiner has started
  and whether a service account has expired, so use it to get repeatable demos and tests.
- Settings come from environment variables: `KC_URL` (default `http://localhost:8080`), `KC_ADMIN_USER`
  (default `admin`) and `KC_ADMIN_PASSWORD` (default `dev-only-not-secret`, a documented throwaway for a local
  test server that is deleted with the session and never used anywhere else).
- The engine refuses `--realm master` (Keycloak's own admin realm).
- Files: `hr/hr-feed.csv` (12 fictional rows), `hr/service-accounts.csv` (4 rows), `roles-map.yaml`.

Tests:

```bash
ruff check .          # style and mistakes
pytest -q             # unit tests; the Keycloak tests are skipped (with the reason) if no Keycloak is running
pytest -q -m keycloak # integration tests; needs the local Keycloak from step 2
```

The unit tests use an in-memory stand-in for Keycloak, so they need no network. The integration tests rebuild
the realm (`keycloak-dev.sh --reset`), so they only run against a local server. They cannot run in GitHub Actions
(no Keycloak there), so CI covers the unit tests only. If Keycloak is up, plain `pytest -q` runs the integration
tests too and takes about a minute.

## What Eojin did vs what Claude did

Eojin decided:

- An already-expired service account is created **disabled** (not enabled with a warning).
- A leaver is disabled **immediately**, even when the end date is in the future.
- A joiner with a future start date is created **disabled until the start date**, using an engine-owned marker.
  This changes the original brief's acceptance criterion "6 joiners enabled": right after the first `apply` the
  joiners are disabled and become enabled once their start date has come.
- The engine may only change groups listed in `managed_groups`, including retired ones.

Claude (with Eojin's review) wrote the engine, the Keycloak client, the HR file reader, the dev setup script, the
sample data, the tests and this document. The sample data is entirely fictional. A second AI reviewer read the
code partway through and its findings were handled (see `docs/verify/T3-S02.md`).

## Results

Run on 2026-10-22 against Keycloak 26.8.1 (local dev server):

```
$ ruff check .
All checks passed!

$ pytest -q            # Keycloak unreachable (KC_URL=http://localhost:9): integration tests skipped
66 passed, 9 skipped in 0.38s

$ pytest -q -m keycloak
9 passed, 66 deselected in 62.96s (0:01:02)
```

A manual run on the sample files: `plan` showed 6 create_user, 3 move_user, 3 disable_user, 4 create_client;
`apply` did them; a second `plan` printed "nothing to do" and a second `apply` printed "Applied 0 changes."

## Limits

- No identity-proofing gate (blocking joiners whose checks are not done), no separation-of-duties rules and no
  attestation (quarterly access review) yet: all T3-S03.
- Leavers who are still named as somebody's `manager_id` or as a service account's `owner` are not flagged yet
  (T3-S03).
- Local dev server only. The admin password is a documented throwaway. No real tenant or Azure subscription is touched.
- Disabling an account does not end sessions that are already open and does not revoke offline tokens.
- The engine is idempotent only if the realm allows custom user attributes ("unmanaged attributes" set to
  ENABLED, which `keycloak-dev.sh` does). Otherwise Keycloak silently drops them and the plan would never reach zero.
- Keycloak stores each attribute as a list; the engine reads and writes only the first value of each.
- Expired service accounts are created or kept disabled; this is not a full guarantee that nothing can use
  them, because it depends on Keycloak's own settings.
- Do not turn on debug logging for the `httpx` or `httpcore` libraries: it would log the Authorization header,
  which holds the admin token.
- The sample feed's dates are in 2026; with a different real date use `--today` to reproduce the output above.
