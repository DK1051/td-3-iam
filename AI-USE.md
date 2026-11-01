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
- T3-S02 director (Opus 5.5): checked Needs, planned, asked Eojin the design choices, started Keycloak, logged caveats, opened the PR.
- T3-S02 `builder` (Sonnet 5.5): closed the T3-S01 export-script gap; wrote the feed parser, Keycloak client, engine and CLI, `keycloak-dev.sh`, the sample feed, 60 unit tests and 9 integration tests, and the 3H README.
- T3-S02 `redteam` (Fable 5.1): mid-review (16 items + 3 design choices), all handled. `verifier` (Opus 5.5): final check, `docs/verify/T3-S02.md`.
- T3-S03 director (Opus 5.5): planned the gap fixes, asked Eojin the design choices, started Keycloak, logged caveats, opened the PR.
- T3-S03 `builder` (Sonnet 5.5): closed the three open gaps (sessions and offline tokens, ownerless/owner-left service accounts, multi-valued attributes), extended the feed, built the proofing gate, the three SoD rules, attestation and expiry, the integration tests and the final 3H README.
- T3-S03 `redteam` (Fable 5.1): mid-review (11 items + 1 design choice), all handled. `verifier` (Opus 5.5): final check, `docs/verify/T3-S03.md`.
- T3-C1 director (Opus 5.5): taught the 3H walk-through, ran the demo against the fake Keycloak (real Keycloak not installed), asked and graded the ten interview questions, wrote the exercise test first and typed Eojin's dictated fix. `chores` (Haiku 5.5): `docs/learning/T3-C1.md`. `verifier` (Opus 5.5): `docs/verify/T3-C1.md`.

Eojin
- Decided: expired service accounts created disabled; leavers disabled at once; joiners disabled until their start date; an explicit `managed_groups` list; service accounts with no active owner fail closed; lost-manager staff go to `unassigned.md`; a malformed row is blocked on its own. Still to do: check each feed row's planned action, write one mover and one leaver row for T3-C1, record the credit balance.
- T3-C1: answered the ten interview questions himself (5/20, AI-graded); dictated the OVERDUE leaver implementation (commits authored by Eojin; passed on the second attempt, after Claude explained the answer in plain English). Claude added only connecting code, listed in the learning note.

## 3A Agent Passport
Claude (models used)
- T3-S04 (framework only): the director (Opus) wrote `DESIGN.md` and the README and integrated the work; `redteam` (Fable) reviewed the design before any code and the code mid-build (it saw only the design, brief, CLAUDE.md and the diff, never request text); `builder` (Sonnet) wrote the server, verifier, audit, `approve.py`, the Keycloak script, the `access-assistant` subagent, the harness and all tests, and applied the mid-review fixes; `verifier` (Opus) ran the regression and acceptance checks (`docs/verify/T3-S04.md`). No model evaluation ran.

Eojin
- T3-S04: approved the scoped build (framework now, evaluation after his A+ exam). Still to do: write the 30 malicious requests in `cases/`, run the evaluation and the approvals, record the cost numbers.
