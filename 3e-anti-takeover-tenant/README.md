# 3E Anti-Takeover Tenant

Part of the [td-3-iam](../README.md) track of the Takeover Defense portfolio. Status: **scaffolded, Eojin is configuring the tenant.**

## What it does

Attackers phone an IT helpdesk, pretend to be an employee and talk the agent into resetting a password or MFA (multi-factor authentication, the second check that proves it is really you). The Canadian Cyber Centre's alert AL26-010 describes exactly this. 3E answers the question: *what settings would make a stolen reset worthless?*

It sets up a trial Microsoft 365 / Microsoft Entra tenant (one organisation's own copy of Microsoft's identity service) for the fictional Maple Harbour Credit Union (`mapleharbour.example`) and aims to turn on eight controls: phishing-resistant sign-in with passkeys, authentication strengths for admins, three Conditional Access rules (block legacy sign-in, strong sign-in for admins, strong re-check on a new device), Temporary Access Pass issued only after a call-back, self-service password reset with strong methods, and two emergency break-glass accounts. `controls.md` lists each control, what it stops, the licence it needs, and the Canadian guidance it is aligned to (OSFI B-13 section 3.2.7, Cyber Centre baseline controls, AL26-010). "Aligned to" only means the control was chosen to serve the same goal; it is not a claim of meeting any standard.

The evidence is a before/after report with screenshots, plus a read-only script that exports the tenant's configuration.

## How to run it

All of this happens on Eojin's own PC and browser, never in a cloud session.

1. Follow `TRIAL-RUNBOOK.md` to start the trial. Do the billing steps (recurring billing OFF, buy nothing) on day 1, before configuring anything.
2. Follow `CONFIGURE.md` to switch the controls on in the safe order. Fill in `before-after-report.md` as you go.
3. Install PowerShell 7, then the Microsoft Graph modules named in the header of `scripts/export-config.ps1` (`TODO(verify)`: exact module names). In PowerShell 7, run the sign-in command shown in that header, then from the repository root:
   `pwsh ./3e-anti-takeover-tenant/scripts/export-config.ps1`
   The script only reads, and writes JSON files into `export/`, which is git-ignored because the files contain tenant and object IDs. Never commit them.
4. Optional: `maester/README.md` describes an automated test suite Eojin may set up later.

## What Eojin did vs what Claude did

| Claude (AI-written, checked by a verifier) | Eojin |
|---|---|
| The runbook, configure guide, controls table, report template, the export script and these READMEs. The script was checked only with PowerShell's syntax parser; Claude never connected to Microsoft. | Starts the trial, creates the fictional test accounts, configures each control, takes and blurs the screenshots, fills in the report, runs the export script, decides what to publish. |

Every `TODO(verify)` marker in these files is something that depends on what Microsoft shows on the day; Eojin resolves them while following the guides.

## Results

Not yet configured. The before/after report is an empty template; this section will be filled in from it once the tenant has been set up.

## Limits

- It is a trial tenant with fictional accounts for a fictional company, not a production setup.
- Which controls can be switched on depends on the licence the trial offers; anything needing Entra ID P1 is marked "not configured — needs P1" if P1 is not available.
- Menu paths, licence tiers for passkeys, Temporary Access Pass and self-service password reset, and the cmdlet and module names are unverified until Eojin checks them on the day.
- The export script has been syntax-checked only. It has never been run against a tenant by Claude, and a PowerShell linter runs on the pull request.
- No evidence is committed that shows tenant names or IDs.
