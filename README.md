# td-3-iam — Track 3 · IAM (Microsoft SC-300)

Part of the **Takeover Defense** portfolio by Eojin Kim ([hub repo: takeover-defense](https://github.com/DK1051/takeover-defense)).

Criminals have learned that the easiest way into a company is not to hack a computer but to phone the IT helpdesk, pretend to be an employee, and talk the agent into resetting that employee's password or their "MFA" (multi-factor authentication: the second check, such as a phone prompt, that proves it is really you). Once the reset goes through, the attacker owns the account. This repo is the third layer of defence: **identity and access management (IAM)**, the rules that decide what an account is allowed to do and how it is created, changed and removed. The three projects here, built for a fictional 50-person credit union in Toronto (Maple Harbour Credit Union, `mapleharbour.example`), are designed so that even a successful fake reset gains the attacker almost nothing.

## Status

**3E scaffolded (T3-S01) — Eojin is configuring the tenant; 3H core engine built (T3-S02); 3A is still planned.** Every project below is scaffolded and built in short, directed Claude Code sessions (see `docs/RUN-SHEET.md` for the schedule and `docs/briefs/` for what each session must deliver). This line is updated at the end of every session.

## Projects

| Level | Project | Folder | What it shows | Status |
|---|---|---|---|---|
| Easy | **3E Anti-Takeover Tenant** | `3e-anti-takeover-tenant/` | A trial Microsoft 365 / Microsoft Entra "tenant" (one organisation's own copy of Microsoft's identity service) locked down against reset-based takeover: phishing-resistant sign-in, Conditional Access rules, break-glass accounts, a before/after report, and a read-only configuration export script. Controls are mapped to Canadian guidance (OSFI B-13, Cyber Centre baseline controls, AL26-010) as "aligned to" — never a compliance claim. | Scaffolded — Eojin is configuring the tenant |
| Hard | **3H Lifecycle for People and Service Accounts** | `3h-lifecycle/` | A Python engine that reads an HR feed (joiners, movers, leavers) and creates, moves or disables accounts in Keycloak (an open-source identity server used here as a stand-in for a corporate directory). Nobody is created until their identity was verified; managers get a quarterly access review; three separation-of-duties rules; every service account has an owner and an expiry date. | Built (T3-S02, T3-S03) — class pending |
| Hard + AI | **3A Agent Passport** | `3a-agent-passport/` | An AI "access assistant" that talks to the 3H engine through an MCP server (Model Context Protocol: a standard way to give an AI model a fixed menu of tools). The assistant can list requests and *propose* a change; it has no tool that grants anything. Grants happen only when a human runs an approval script with a manager's token. Tested against 30 malicious requests (English and Korean) written by Eojin. | Planned — first project to cut if time or credit runs short |

## Why this track exists

- **The alert.** The Canadian Centre for Cyber Security's alert [AL26-010](https://www.cyber.gc.ca/en/alerts-advisories/al26-010-cyber-criminals-social-engineering-enabled-compromise-enterprise-saas-environments) (May 1, 2026) warns that attackers "convince support staff to reset MFA or enroll attacker-controlled devices" and recommends "out-of-band verification procedures for identity-related requests" and to "restrict and closely monitor MFA reset, recovery, and device re-enrolment processes" with "enhanced verification and approval".
- **The case study.** The group publicly known as Scattered Spider used exactly this playbook; two members were sentenced to 5.5 years in July 2026 for the 2024 Transport for London attack. Public incidents with the same pattern: MGM Resorts (2023), Clorox (2023, *alleged* in Clorox's lawsuit against Cognizant), Marks & Spencer and Co-op (2025).
- **This track's job.** Track 1 stops the reset at the helpdesk, Track 2 catches a reset that slipped through, Track 4 limits the damage in the cloud. Track 3 makes the stolen reset worthless: strong sign-in that a password alone cannot pass, accounts that only exist after identity proofing, access that is reviewed and expires, and an AI helper that cannot grant access even if it is tricked.

## Eojin's inputs (deadlines are days after kit upload, D0)

| Needed by | What | Where |
|---|---|---|
| after T3-S01 (D1) | Start the Microsoft trial on his own PC following `3e-anti-takeover-tenant/TRIAL-RUNBOOK.md`; configure the controls; fill the before/after report; run the read-only export locally. | his PC only — nothing from the tenant is committed |
| before T3-S04 (D9) | 30 malicious access requests (English + Korean), one YAML file each, format in `docs/briefs/T3-S04.md`. | `3a-agent-passport/cases/` |
| T3-C1 (D6), T3-C2 (D10) | Attend the class sessions and answer the ten "why" questions for each project. | `docs/learning/` |

## How this repo is built

Each session is a Claude Code cloud session directed by Eojin with short prompts (`go T3-S02`, `status`, `probe`, `class T3-C1`, `wrap`); the rules are in `CLAUDE.md`. Roles: a director model plans and integrates; a `builder` writes code and tests; `chores` does mechanical work; a `verifier` checks every acceptance criterion and writes a report that it cannot edit away; a `redteam` reviewer gates the AI project's design before it is built. Honesty rule: everything in this repo is produced with AI assistance, everything is checked, and Eojin can rebuild and explain it (the class transcripts in `docs/learning/` are the evidence). `AI-USE.md` says per project what Claude did and what Eojin did.

## How to verify my work

- `docs/verify/<ID>.md` — the verifier's PASS / FAIL / NEEDS-EOJIN report for each session, with the command output it relied on.
- `docs/learning/<ID>.md` — class transcripts: Eojin's answers to the "why" questions, graded honestly.
- `docs/CAVEATS.md` and `COSTS.md` — what went differently from the plan, and what each session cost.
- The commit history: one branch and one pull request per session, squash-merged by Eojin.
- CI (`.github/workflows/ci.yml`): `ruff` lint, `pytest`, a gitleaks secret scan, and PSScriptAnalyzer for PowerShell.

## Safety and data

Every company, person, phone number and email in this repo is fictional (Maple Harbour Credit Union, `mapleharbour.example`, `555-01xx` numbers). No cloud session ever connects to a real Microsoft tenant; the PowerShell export is read-only and runs only on Eojin's PC, and its output folder is git-ignored. No passwords, tokens, keys, tenant or subscription IDs are committed; the only password in the repo is the documented throwaway for a local Keycloak test server. Real incidents are cited only from public reporting. Defensive purpose only: the "malicious requests" for 3A are written by Eojin, run only against our own test server, and contain no exploit code.

## Local setup

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
ruff check . && pytest -q
```

Keycloak (for 3H and 3A) runs locally on http://localhost:8080; the start command is in `docs/briefs/T3-S02.md`. The cloud environment installs Keycloak and PowerShell with `environment/setup.sh`; `bash scripts/probe.sh` shows what the machine can reach.

## Licence

MIT — see `LICENSE`.
