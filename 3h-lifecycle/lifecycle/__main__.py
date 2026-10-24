"""Command line: `PYTHONPATH=3h-lifecycle python -m lifecycle <command> ...` (run from the repo root).

  plan    shows what would change and changes nothing.
  apply   makes the changes, then prints a count per action type and writes
          reports/blocked-joiners.md. `apply --dry-run` behaves exactly like `plan`.
  sod     checks the three separation-of-duties rules against the feed and the directory as it
          would look after `apply`; prints violations and exits 1 if there are any, else 0.
  attest  writes the quarterly attestation files (one per manager, plus unassigned.md).

Exit codes: 0 fine, 1 `sod` found violations, 2 bad input or a Keycloak error, 3 unexpected
error, 4 `apply` finished but some actions failed (see the lines it printed).
"""

import argparse
import sys
import warnings
from datetime import date
from pathlib import Path

from lifecycle import attest, engine, expiry, reports, sod
from lifecycle.feed import FeedError, load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient, KeycloakError

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROLES_MAP = PROJECT_DIR / "roles-map.yaml"
DEFAULT_SOD_RULES = PROJECT_DIR / "sod-rules.yaml"
DEFAULT_REPORTS = PROJECT_DIR / "reports"
DEFAULT_ATTESTATION = DEFAULT_REPORTS / "attestation"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifecycle", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "sod", "attest"):
        sub = commands.add_parser(name)
        sub.add_argument("--feed", required=True, help="path to hr-feed.csv")
        sub.add_argument("--service-accounts", required=True, help="path to service-accounts.csv")
        sub.add_argument("--realm", required=True, help="Keycloak realm, e.g. maple-harbour")
        sub.add_argument("--roles-map", default=str(DEFAULT_ROLES_MAP))
        sub.add_argument("--today", type=date.fromisoformat, default=None,
                         help="pretend today is this date (YYYY-MM-DD); also LIFECYCLE_TODAY")
        if name == "apply":
            sub.add_argument("--dry-run", action="store_true",
                             help="show the plan and change nothing")
            sub.add_argument("--reports-dir", default=str(DEFAULT_REPORTS),
                             help="where blocked-joiners.md is written")
        if name == "sod":
            sub.add_argument("--sod-rules", default=str(DEFAULT_SOD_RULES))
        if name == "attest":
            sub.add_argument("--quarter", required=True, help="for example 2026-Q4")
            sub.add_argument("--out", default=str(DEFAULT_ATTESTATION),
                             help="folder for the attestation files")
    return parser


def run_sod(args, feed, service_accounts, roles_map, state) -> int:
    """Print every separation-of-duties violation; exit code 1 if there is any."""
    rules = sod.load_rules(args.sod_rules)
    projected = engine.projected_groups(feed, roles_map, state)
    violations = sod.evaluate(
        rules, feed, service_accounts, projected, state.users,
        directory_overlap=engine.directory_overlap(feed, state),
        unlisted_clients=state.other_clients,
    )
    if not violations:
        print("SoD check: no violations.")
        return 0
    for violation in violations:
        print(f"{violation.rule_id}  {violation.subject}: {violation.reason}")
    print(f"SoD check: {len(violations)} violation(s).")
    return 1


def print_expiry_warnings(service_accounts, today) -> None:
    lines = expiry.expiry_warnings(service_accounts, today)
    if lines:
        print("Expiry warnings:")
        for line in lines:
            print(f"  {line}")


def main(argv: list[str] | None = None, kc_factory=KeycloakClient) -> int:
    args = build_parser().parse_args(argv)
    if args.realm == "master":
        # "master" is Keycloak's own admin realm; the engine must never create people in it.
        print("ERROR: --realm master is not allowed; use the HR realm, e.g. maple-harbour",
              file=sys.stderr)
        return 2
    try:
        feed = load_feed(args.feed)
        service_accounts = load_service_accounts(args.service_accounts)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", engine.RolesMapWarning)
            roles_map = engine.load_roles_map(args.roles_map)
        for note in caught:
            print(f"NOTE: {note.message}", file=sys.stderr)
        today = expiry.resolve_today(args.today)
        kc = kc_factory(args.realm)
        state = engine.read_state(kc, feed, service_accounts)
        if args.command == "sod":
            return run_sod(args, feed, service_accounts, roles_map, state)
        if args.command == "attest":
            files = attest.build_attestation(feed, service_accounts, state, args.quarter, today)
            written = attest.write_attestation(files, args.out)
            print(f"Wrote {len(written)} attestation file(s) to {args.out}: "
                  + ", ".join(path.name for path in written))
            print_expiry_warnings(service_accounts, today)
            return 0
        actions = engine.plan(feed, service_accounts, roles_map, state, today)
        print(engine.format_plan(actions))
        print_expiry_warnings(service_accounts, today)
        if args.command == "apply" and not args.dry_run:
            done = engine.apply(actions, kc)
            path = reports.write_blocked_report(actions, args.reports_dir)
            print(f"Wrote {path.name} to {path.parent}")
            print(engine.format_applied(done))
            if done.failures:
                for kind, target, message in done.failures:
                    print(f"FAILED {kind} {target}: {message}", file=sys.stderr)
                print(f"ERROR: {len(done.failures)} action(s) failed; the rest were applied. "
                      "Run `apply` again after fixing the cause.", file=sys.stderr)
                return 4
    except (FeedError, engine.EngineError, sod.SodError, attest.AttestError, expiry.ExpiryError,
            KeycloakError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last resort: show the type only, never the text
        print(f"ERROR: unexpected {type(exc).__name__}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
