# 3E trial runbook: start the Microsoft trial safely

This is a checklist Eojin follows on his own PC and browser, after the T3-S01 pull request is merged. Tick each box as you go. Do the steps in this order: the billing steps come before any configuring.

> **Safety box (read first)**
> - Never paste the tenant ID, the tenant's default domain name (the long name that ends in "onmicrosoft" plus ".com"), the admin email, invoices, or any screenshot that shows an ID into this repo. Blur or crop the screenshot before you commit it.
> - Use a brand-new admin account on a brand-new tenant. Never use a personal mailbox or any account tied to your real life.
> - A **tenant** is one organisation's own copy of Microsoft's identity service. Ours is for a made-up company, Maple Harbour Credit Union (`mapleharbour.example`), so every name you type must be fictional and contain no personal data.
> - Nothing in this runbook is done by Claude. No cloud session ever signs in to your tenant.
> - Anything that depends on what Microsoft shows on the day (trial offers, menu names, prices, the refund window) is marked `TODO(verify on the day)`. Where the screen differs from this page, trust the screen and write the difference in `before-after-report.md`.

## Checklist

- [ ] **1. Start a Business Basic trial (the Korea path).**
  At the time the brief was written, Microsoft's Korean site offered a free trial only for **Microsoft 365 Business Basic**, so start a Business Basic trial first. `TODO(verify on the day)`: that the trial is still offered, its length and the exact page.
  Why: Business Basic is the route chosen for this project to get a real tenant, and a tenant is what everything else in 3E is configured in.
  - Sign up with a brand-new admin account on a brand-new tenant (never a personal mailbox).
  - Use **`northpine-demo`** as the tenant's organisation name. It is made up and unrelated to Maple Harbour, so this public repo does not point to your tenant by its company name. For the **default-domain name** (the part before the dot in the tenant's built-in address), choose a different random-looking string and do not write it in this repo, because that built-in address is what the safety box above tells you never to publish. Only the **display names** of the made-up people and company (Maple Harbour Credit Union, `mapleharbour.example`) use the Maple Harbour name. Keep no personal data. `TODO(verify on the day)`: which of these names the sign-up form lets you choose, and whether it suggests the default-domain name from the organisation name (if it does, change it).
  - If sign-up asks how many licences you need, choose the smallest number offered. `TODO(verify on the day)`.
  - If sign-up demands a payment card, **stop and decide** before entering anything: do not type a card in just to continue. Continue only if you have chosen to accept that risk and you do step 3 straight away. `TODO(verify on the day)`: whether a card is asked for at all.

- [ ] **2. Try to add a Business Premium trial or an Entra ID P1/P2 trial on top.**
  In the Microsoft 365 admin centre, look for a **Business Premium** trial or a **Microsoft Entra ID P1/P2** trial and start it if one is offered. `TODO(verify on the day)`: whether either is offered, and the menu path to find it.
  Why: P1 is the paid tier that unlocks Conditional Access (rules of the form "if this sign-in looks like X, require Y") and authentication strengths (a rule about which sign-in methods count as strong enough). P2 adds risk-based policies, which react to signals that a sign-in looks suspicious. Without P1 most of 3E cannot be switched on.
  - Write down in `before-after-report.md` which trial was offered, if any (the header block, "licence obtained").
  - If a screen asks how many licences to buy, it is a purchase screen: close it.

- [ ] **3. Day 1, before anything else: turn recurring billing OFF and buy nothing.**
  Go to **Billing** → **Your products** → click the subscription → turn **OFF** recurring billing. `TODO(verify on the day)`: the exact menu names and where the switch sits.
  Why: with recurring billing off, the trial ends on its own instead of charging a card at the end. We buy nothing, ever, in this project.
  - If any screen asks how many licences to buy, it is a purchase screen: close it, and buy nothing.
  - Repeat this check on every subscription you see under **Your products** (the Business Basic trial and any P1/P2 or Premium trial).
  - Screenshot the "recurring billing: off" state for your own records. Blur it before committing; it must not show IDs, invoices or card details.
  - If, after sign-up, no recurring-billing switch exists on the subscription, do not wait: cancel the subscription within the refund window (see step 4). `TODO(verify on the day)`: whether a switch exists, where cancel is, and the refund window.

- [ ] **4. Set two calendar reminders.**
  - On **day 1**: "confirm recurring billing is OFF".
  - On **day 25**: "export config, take screenshots, then let the trial lapse".
  - On **day 6** (inside the refund window): "check Billing → Bills shows no charge". `TODO(verify on the day)`: the menu name and whether a charge could show up by then.
  Why: refunds are only possible within **7 days** (`TODO(verify on the day)`: the current refund window), so the day-1 check is the real safety net. Day 25 is meant to leave time to collect evidence before the trial ends (`TODO(verify on the day)`: the trial length shown on the sign-up screen, and adjust the day-25 reminder if it differs).

- [ ] **5. Fallback if no P1 trial is possible: scope 3E to Entra Free.**
  If neither a Business Premium nor an Entra ID P1/P2 trial is available, restrict 3E to **Entra Free** features: sign-in logs, per-user MFA (multi-factor authentication, the second check that proves it is really you), and security defaults (Microsoft's one-switch bundle of basic protections). `TODO(verify on the day)`: what Entra Free includes on that day.
  - In `controls.md`, mark every control that needed P1 as "not configured — needs P1".
  - The report is still valid. It simply shows the licence boundary honestly, and that is itself a result worth writing up.

- [ ] **6. Hand-off note for Track 4.**
  The Azure free account for the `td-4-cloud` repo is created with this tenant's admin account, and only on the day 4E is configured, not earlier. Why: an Azure free account has its own clock and its own billing questions, so we start it only when it will be used.

- [ ] **7. Last, after day 25: let the trial lapse.**
  Run the read-only export (`scripts/export-config.ps1`, see the 3E README), keep the output on your PC only, finish the report, and do nothing that converts the trial to a paid plan.
