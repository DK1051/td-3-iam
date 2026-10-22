# What Claude did vs what Eojin did

Honesty rule for this repo: every line of code and every document was produced in a Claude Code session that Eojin directed, and then checked by a `verifier` subagent (report in `docs/verify/`) and, for the AI project, a `redteam` review. Eojin's own work is listed under "Eojin" and is the part he can rebuild and explain in an interview (see `docs/learning/`). Each project section is filled in at the `wrap` of the sessions that touched it.

## 3E Anti-Takeover Tenant
Claude (models used)
- T3-S01 director (Opus 5.5): probe and notes, caveats, run sheet, PR.
- T3-S01 `builder` (Sonnet 5.5): `TRIAL-RUNBOOK.md`, `controls.md`, `before-after-report.md`, `CONFIGURE.md`, the read-only `scripts/export-config.ps1` (checked with PowerShell's parser only), `maester/README.md`, the 3E README and the repo README status. Nothing was configured and nothing connected to Microsoft.
- T3-S01 `redteam` (Fable 5.1): mid-review. `verifier` (Opus 5.5): final check, `docs/verify/T3-S01.md`.

Eojin
- To do: follow `TRIAL-RUNBOOK.md` on your own PC (billing OFF on day 1), configure the controls with `CONFIGURE.md`, fill `before-after-report.md`, run `export-config.ps1` locally, and read the `pwsh-lint` CI result on the PR.

## 3H Lifecycle for People and Service Accounts
Claude (models used)
- (to be filled at wrap)

Eojin
- (to be filled at wrap)

## 3A Agent Passport
Claude (models used)
- (to be filled at wrap)

Eojin
- (to be filled at wrap)
