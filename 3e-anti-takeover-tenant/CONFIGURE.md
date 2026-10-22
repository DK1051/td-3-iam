# 3E configure guide: switch the controls on safely

Eojin follows this on his own PC, in the trial tenant, after `TRIAL-RUNBOOK.md` (billing steps first). It is planned for two 2-hour slots (D4 and D8 in `docs/RUN-SHEET.md`). Claude wrote it from general knowledge without seeing Microsoft's screens, so **every menu path below is `TODO(verify on the day)`**: if a label differs, trust the screen and note the difference in `before-after-report.md`.

Never write the tenant ID, the tenant's default domain name, real emails or passwords in this repo. Use `mapleharbour.example` names only.

## The safe order, and why

Strong rules can lock you out of your own tenant. So the order is:

1. Create the two emergency (break-glass) accounts first, so there is always a way back in.
2. Create every Conditional Access policy in **Report-only** mode (it logs what the policy *would* have done but blocks nothing), each one excluding the break-glass accounts.
3. Turn **security defaults** (Microsoft's one-switch bundle of basic protections) off, because they stop Conditional Access policies from being switched on.
4. Switch the policies **On** one at a time, signing in as the test user after each one.
5. Then set up the remaining controls.

Each section says which row of `controls.md` it covers. Keep `before-after-report.md` open: fill in **Before** before you change a setting, and **After**, **Evidence** and **Date** straight after.

If a section needs P1 (Conditional Access and authentication strengths) and you only have Entra Free, skip it and write "not configured — needs P1" in the report.

---

## 1. Two break-glass accounts (controls.md row 8)

What it does: creates two emergency administrator accounts that no Conditional Access rule can block, so a bad policy cannot lock everyone out.

1. Entra admin centre → Users → New user → Create new user. `TODO(verify on the day)`
2. Create `breakglass1@mapleharbour.example` and `breakglass2@mapleharbour.example` (fictional display names; use the tenant's real default domain only on screen, never in this repo; `TODO(verify on the day)` which domain the form allows).
3. Give each a long random password from a password generator. Write each on paper (or store in an offline password vault) in separate places. Never type either into this repo, a chat or a cloud session.
4. Assign the highest administrator role the tenant needs for emergencies. `TODO(verify on the day)`: the role name and its menu path (Entra admin centre → Roles & admins).
5. Record in the report: creation date and "excluded from all Conditional Access policies (done in sections 3 to 5)".
6. Do not use these accounts for daily work. Plan to test each once, near the end, and note the sign-in in the log. `TODO(verify on the day)`: where sign-in logs are (Entra admin centre → Monitoring and health → Sign-in logs).

## 2. Authentication strength for admins (controls.md row 2)

What it does: defines which sign-in methods count as "strong" for admins, so later policies can require them. Needs P1.

1. Entra admin centre → Protection → Authentication methods → Authentication strengths. `TODO(verify on the day)`
2. Look at the built-in strengths first; a built-in phishing-resistant strength may already exist. `TODO(verify on the day)`: name and contents.
3. If it fits, use it as is. Otherwise create a custom strength that lists only phishing-resistant methods (passkeys and security keys). `TODO(verify on the day)`
4. Record the strength name in the report, or "not configured — needs P1".

## 3. Conditional Access: block legacy authentication, Report-only (controls.md row 3)

What it does: closes old sign-in routes that cannot ask for a second check. Needs P1. Create it in Report-only mode now; switching it on comes in section 7.

1. Entra admin centre → Protection → Conditional Access → Policies → New policy. `TODO(verify on the day)`
2. Name it `MH-block-legacy-auth`.
3. Users: include all users; **exclude** the two break-glass accounts. `TODO(verify on the day)`
4. Target resources: all resources. Conditions → Client apps: select the legacy ("other clients") types. `TODO(verify on the day)`
5. Grant: Block access.
6. Enable policy: **Report-only**. Save.

## 4. Conditional Access: require strong authentication for admins, Report-only (controls.md row 4)

What it does: whenever an admin signs in, they must pass the strong method from section 2. Needs P1.

1. Conditional Access → Policies → New policy, named `MH-admins-strong-auth`. `TODO(verify on the day)`
2. Users: include directory roles (select the admin roles you use in the test); **exclude** the two break-glass accounts. `TODO(verify on the day)`
3. Target resources: all resources.
4. Grant: Require authentication strength → the strength from section 2. `TODO(verify on the day)`
5. Enable policy: **Report-only**. Save.

## 5. Conditional Access: new device for privileged roles needs strong re-authentication, Report-only (controls.md row 5)

What it does: an admin signing in from a device the tenant has not seen must pass the strong check again. This blocks the "attacker enrols a new device after a fake reset" step in AL26-010. Needs P1.

1. Conditional Access → Policies → New policy, named `MH-admins-new-device-reauth`. `TODO(verify on the day)`
2. Users: the same admin roles; **exclude** both break-glass accounts.
3. Conditions and controls: the exact way to express "a device not seen before" and "re-authenticate" (device filters, sign-in frequency, authentication strength) is `TODO(verify on the day)`. Do not guess: read what Microsoft offers, pick the closest option, and describe in the report what you chose and what it does not cover.
4. Enable policy: **Report-only**. Save.

## 6. Security defaults off (prerequisite, not a row of controls.md)

What it does: security defaults and Conditional Access policies cannot be used together, so security defaults must be disabled before policies can be switched on. Do this only after sections 1 to 5 are done and the break-glass accounts exist.

1. Entra admin centre → Overview → Properties → **Manage security defaults** → **Disabled**. `TODO(verify on the day)`
2. Write down in the report the reason you choose if Microsoft asks for one.
3. From now until section 7 finishes, the tenant has fewer protections than before. Keep this window short.

## 7. Switch the policies On, one at a time (controls.md rows 3, 4, 5)

What it does: turns the Report-only policies into enforced ones, with a real sign-in test after each.

For each of `MH-block-legacy-auth`, then `MH-admins-strong-auth`, then `MH-admins-new-device-reauth`, in that order:

1. Open the Report-only results first (sign-in logs → Conditional Access tab) and check the policy would not have blocked the break-glass accounts. `TODO(verify on the day)`
2. Set Enable policy to **On**. `TODO(verify on the day)`
3. In a private browser window, sign in as the standard test user, then as the admin test user. Note what happened.
4. If anything is wrong, switch the policy back to Report-only or Off, and use a break-glass account if you are locked out.
5. Fill **After**, **Evidence** and **Date** in the report for the matching control, then move to the next policy.

## 8. Passkeys / phishing-resistant MFA for all staff (controls.md row 1)

What it does: lets staff sign in with a passkey (a sign-in secret tied to their device that a fake website cannot capture).

1. Entra admin centre → Protection → Authentication methods → Policies → passkey / FIDO2 method → enable for a test group. `TODO(verify on the day)`: the method's exact name and the licence tier it needs (`controls.md` marks it `TODO(verify)`).
2. Register a passkey for the standard test user and sign in with it. `TODO(verify on the day)`
3. Record the licence tier you actually needed in the report.

## 9. Temporary Access Pass issued only after verified identity (controls.md row 6)

What it does: a Temporary Access Pass (TAP) is a short-lived code an admin issues so a user can sign in and register a new method. Our rule: issue it only after the Track 1 call-back check proves who is asking.

1. Authentication methods → Policies → Temporary Access Pass → enable for the test group, one-time use, shortest lifetime offered. `TODO(verify on the day)`: setting names, the licence tier needed.
2. As the admin test user, issue a TAP to the standard test user: Users → the user → Authentication methods → Add → Temporary Access Pass. `TODO(verify on the day)`
3. Write the verification step you followed (the out-of-band call-back from Track 1) in the report; the TAP is not issued until it is done.

## 10. Self-service password reset with strong methods only (controls.md row 7)

What it does: staff reset their own password without the helpdesk, and only with methods a caller cannot talk their way past.

1. Entra admin centre → Protection → Password reset → Properties → enable for a test group. `TODO(verify on the day)`
2. Authentication methods: require two methods and untick the weak ones (for example security questions, if offered). `TODO(verify on the day)`
3. Test as the standard user from a private window. Record the licence tier the feature needed (`TODO(verify on the day)`).

---

## After all ten sections

1. Re-check recurring billing is still OFF (see `TRIAL-RUNBOOK.md`).
2. Test each break-glass account once and log it, then store the passwords offline again.
3. Run `scripts/export-config.ps1` (see the 3E README) and keep its output on your PC.
4. Finish `before-after-report.md`, including "What I could not do and why".
