"""Markdown reports written by `apply`.

blocked-joiners.md lists every row the controls refused - joiners and movers stopped by the
proofing gate, and rows that could not be read at all - with the reason, so a person can fix
them. It holds only what is already in the HR files. (The file name is kept from the first
version, which only listed joiners.)
"""

from pathlib import Path

from lifecycle.engine import BLOCKED, Action

BLOCKED_FILE = "blocked-joiners.md"


def write_blocked_report(actions: list[Action], directory: str | Path) -> Path:
    """Write <directory>/blocked-joiners.md (replacing any older file) and return its path."""
    rows = [a for a in actions if a.kind == BLOCKED and a.details.get("row") in ("joiner", "mover")]
    lines = [
        "# Blocked rows",
        "",
        ("These rows of the HR files were refused, so nothing was created or changed for them. "
         "Fix the feed and run `apply` again. Every other row was still processed."),
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
    unreadable = sorted((a for a in actions if a.kind == BLOCKED
                         and a.details.get("row") == "unreadable"),
                        key=lambda a: (a.details["source"], a.details["line"]))
    lines.append("## Rows that could not be read")
    lines.append("")
    if not unreadable:
        lines += ["None. Every row could be read.", ""]
    else:
        lines += ["| File | Line | Who | Problem |", "|---|---|---|---|"]
        for action in unreadable:
            d = action.details
            lines.append(f"| {d['source']} | {d['line']} | {d['who']} | {d['reason']} |")
        lines.append("")
    path = Path(directory) / BLOCKED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
