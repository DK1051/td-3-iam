"""Markdown reports written by `apply`.

blocked-joiners.md lists every joiner (and mover) the proofing gate refused, with the reason, so
a person can chase the missing checks. It holds only what is already in the HR feed.
"""

from pathlib import Path

from lifecycle.engine import BLOCKED, Action

BLOCKED_FILE = "blocked-joiners.md"


def write_blocked_report(actions: list[Action], directory: str | Path) -> Path:
    """Write <directory>/blocked-joiners.md (replacing any older file) and return its path."""
    rows = [a for a in actions if a.kind == BLOCKED and "row" in a.details]
    lines = [
        "# Blocked joiners",
        "",
        ("These rows of the HR feed were refused by the proofing gate, so no account was created "
         "or changed. Fix the missing checks in the feed and run `apply` again."),
        "",
    ]
    for row_type, title in (("joiner", "Joiners"), ("mover", "Movers")):
        section = sorted((a for a in rows if a.details["row"] == row_type), key=lambda a: a.target)
        lines.append(f"## {title}")
        lines.append("")
        if not section:
            lines += [f"None. Every {row_type} row passed the gate.", ""]
            continue
        lines += ["| Employee | Name | Department | Job title | Reason |", "|---|---|---|---|---|"]
        for action in section:
            d = action.details
            name = f"{d['first_name']} {d['last_name']}"
            lines.append(f"| {action.target} | {name} | {d['department']} | {d['job_title']} | "
                         f"{'; '.join(d['reasons'])} |")
        lines.append("")
    path = Path(directory) / BLOCKED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
