"""The audit log: one JSON line per call, appended and flushed straight away.

A line looks like this (design section 7):
  {"ts": "...Z", "caller": {"client_id": ..., "subject": ...}, "tool": "propose_change",
   "args_sha256": "<hex>", "decision": "allow" | "deny", "reason": "..."}

The arguments are never written, only their SHA-256 fingerprint (a one-way summary: the same
arguments always give the same fingerprint, but the text cannot be read back from it). Request
text may carry injected instructions or personal-looking data, so it stays out of the log. Tokens
are never written either. `reason` is always a short fixed phrase chosen by our own code, never
text that came from a caller.
"""

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path


def args_fingerprint(args: dict | None) -> str | None:
    """SHA-256 of the arguments as canonical JSON (sorted keys, no spaces). None if no arguments
    apply (for example a rejected token, where no tool was reached)."""
    if args is None:
        return None
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, *, tool: str, decision: str, reason: str, client_id: str | None = None,
               subject: str | None = None, args: dict | None = None) -> None:
        if decision not in ("allow", "deny"):
            raise ValueError("decision must be 'allow' or 'deny'")
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "caller": {"client_id": client_id, "subject": subject},
            "tool": tool,
            "args_sha256": args_fingerprint(args),
            "decision": decision,
            "reason": reason,
        }
        text = json.dumps(line, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:  # append mode
                handle.write(text)
                handle.flush()
