# Verify: T3-S01 follow-up (tenant name `northpine-demo`)

Date: 2026-10-22. Verifier: Claude (Opus 5.5). Branch `claude/friendly-heisenberg-seafff`, PR #2.
Compared against `origin/main` (8a4b085, which already contains the merged T3-S01 PR). The local `main` branch is stale (6e5acfe) and would show the whole T3-S01 diff, so it was not used.

## Review findings

The diff is 3 files, 3 added lines and 2 removed: `TRIAL-RUNBOOK.md` (sign-up step), `before-after-report.md` (header), `docs/CAVEATS.md` (one line).

- No bugs, and no unsafe patterns. Markdown only.
- No mid-review was required for this two-line follow-up.
- Tenant-name coverage: in `3e-anti-takeover-tenant/`, the only places that give the tenant a name are `TRIAL-RUNBOOK.md:18` and `before-after-report.md:12`. Both say `northpine-demo`. The other "Maple Harbour" lines (`README.md:9`, `TRIAL-RUNBOOK.md:8`) describe the fictional company the tenant is for, not the tenant's name. The tenant-name grep found no `Maple Harbour … tenant` or `tenant … Maple Harbour` naming.
- Default domain kept as a different, unpublished string. **AI judgement: this is consistent with the rules.** The default domain (`<prefix>.onmicrosoft.com`) is a tenant identifier. Anyone can look it up publicly and get the tenant ID from it. So publishing it would amount to publishing a tenant ID, which CLAUDE.md's safety rules forbid. It would also break the runbook safety box and T3-S01 AC9. The organisation name is a display label, and the decision ("tenant name") most naturally means that label. The runbook also covers the case where the sign-up form suggests a default domain based on the organisation name ("if it does, change it"). The new CAVEATS line correctly asks Eojin to confirm (needs Eojin: yes).
- Minor note, no fix needed: `before-after-report.md:7` still says to blur "any tenant name or ID" in screenshots. Now that the organisation name is public this is over-cautious, but harmless. The default domain still has to be blurred.

## Regression

| Check | origin/main | branch |
|---|---|---|
| `ruff check .` | All checks passed! (no Python files) | All checks passed! (no Python files) |
| `pytest -q` | n/a (no tests) | rc 5 "no tests ran", which CI accepts |

Nothing that passed on main fails now. Secrets and real-data grep of the added lines (password, secret, token, key patterns, GUIDs, `onmicrosoft`, real email domains, long random strings): the only hits were the file-path header lines, which are false positives. `northpine-demo` is a made-up label, not a domain or an email.

## Criteria re-run

- AC1 PASS: every phrase count is at least 1. Business Basic 4, Business Premium 3, Entra ID P1 3, Billing 2, Your products 2, recurring billing 5, OFF 3, buy nothing 3, day 1 1, day 25 2, 7 days 1, Entra Free 2.
- AC3 PASS: `grep -ri compliant 3e-anti-takeover-tenant/` returned nothing (rc=1). The `aligned to` count in controls.md is 1.
- AC9 PASS: the `onmicrosoft\.com|<GUID>` grep on `3e-anti-takeover-tenant/` returned nothing (rc=1).
- Decision applied ("northpine-demo everywhere a tenant name appears"): PASS (code check by grep), plus AI judgement on the default-domain split. Eojin still has to confirm the split (see CAVEATS).

Verdict: PASS. New caveat: none beyond the existing "needs Eojin: yes" line on the default-domain choice.
