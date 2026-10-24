"""Command line: `PYTHONPATH=3h-lifecycle python -m lifecycle plan|apply ...` (run from the repo root).

  plan   shows what would change and changes nothing.
  apply  makes the changes, then prints a count per action type and writes
         reports/blocked-joiners.md. `apply --dry-run` behaves exactly like `plan`.
  sod    checks the three separation-of-duties rules against the feed and the directory as it
         would look after `apply`; prints violations and exits 1 if there are any, else 0.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from lifecycle import engine, reports, sod
from lifecycle.feed import FeedError, load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient, KeycloakError

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROLES_MAP = PROJECT_DIR / "roles-map.yaml"
DEFAULT_SOD_RULES = PROJECT_DIR / "sod-rules.yaml"
DEFAULT_REPORTS = PROJECT_DIR / "reports"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifecycle", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "sod"):
        sub = commands.add_parser(name)
        sub.add_argument("--feed", required=True, help="path to hr-feed.csv")
        sub.add_argument("--service-accounts", required=True, help="path to service-accounts.csv")
        sub.add_argument("--realm", required=True, help="Keycloak realm, e.g. maple-harbour")
        sub.add_argument("--roles-map", default=str(DEFAULT_ROLES_MAP))
        sub.add_argument("--today", type=date.fromisoformat, default=None,
                         help="pretend today is this date (YYYY-MM-DD); for tests and demos")
        if name == "apply":
            sub.add_argument("--dry-run", action="store_true",
                             help="show the plan and change nothing")
            sub.add_argument("--reports-dir", default=str(DEFAULT_REPORTS),
                             help="where blocked-joiners.md is written")
        if name == "sod":
            sub.add_argument("--sod-rules", default=str(DEFAULT_SOD_RULES))
    return parser


def run_sod(args, feed, service_accounts, roles_map, state) -> int:
    """Print every separation-of-duties violation; exit code 1 if there is any."""
    rules = sod.load_rules(args.sod_rules)
    projected = engine.projected_groups(feed, roles_map, state)
    violations = sod.evaluate(rules, feed, service_accounts, projected, state.users)
    if not violations:
        print("SoD check: no violations.")
        return 0
    for violation in violations:
        print(f"{violation.rule_id}  {violation.subject}: {violation.reason}")
    print(f"SoD check: {len(violations)} violation(s).")
    return 1


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
        roles_map = engine.load_roles_map(args.roles_map)
        kc = kc_factory(args.realm)
        state = engine.read_state(kc, feed, service_accounts)
        today = args.today or date.today()
        if args.command == "sod":
            return run_sod(args, feed, service_accounts, roles_map, state)
        actions = engine.plan(feed, service_accounts, roles_map, state, today)
        print(engine.format_plan(actions))
        if args.command == "apply" and not args.dry_run:
            done = engine.apply(actions, kc)
            path = reports.write_blocked_report(actions, args.reports_dir)
            print(f"Wrote {path.name} to {path.parent}")
            if done:
                print("Applied: " + ", ".join(f"{kind}={count}" for kind, count in done.items()))
            else:
                print("Applied 0 changes.")
    except (FeedError, engine.EngineError, sod.SodError, KeycloakError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last resort: show the type only, never the text
        print(f"ERROR: unexpected {type(exc).__name__}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
