"""Command line: `PYTHONPATH=3h-lifecycle python -m lifecycle plan|apply ...` (run from the repo root).

  plan   shows what would change and changes nothing.
  apply  makes the changes, then prints a count per action type.
         `apply --dry-run` behaves exactly like `plan`.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from lifecycle import engine
from lifecycle.feed import FeedError, load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient, KeycloakError

DEFAULT_ROLES_MAP = Path(__file__).resolve().parent.parent / "roles-map.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifecycle", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
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
    return parser


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
        actions = engine.plan(feed, service_accounts, roles_map, state, args.today or date.today())
        print(engine.format_plan(actions))
        if args.command == "apply" and not args.dry_run:
            done = engine.apply(actions, kc)
            if done:
                print("Applied: " + ", ".join(f"{kind}={count}" for kind, count in done.items()))
            else:
                print("Applied 0 changes.")
    except (FeedError, engine.EngineError, KeycloakError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last resort: show the type only, never the text
        print(f"ERROR: unexpected {type(exc).__name__}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
