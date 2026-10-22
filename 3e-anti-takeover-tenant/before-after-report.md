# 3E before / after report

Template for Eojin to fill in on his own PC while configuring the trial tenant. Nothing here has been filled in yet: the tenant is not configured.

Rules for filling it in:
- Fictional names only (`mapleharbour.example`). Never write the tenant ID, the tenant's default domain name, a real email, or any object ID.
- Evidence means a screenshot file name. Blur or crop any tenant name or ID before the screenshot is committed.
- If a control needed P1 and P1 was not available, write "not configured — needs P1" under After and say so under "What I could not do and why".

## Header

- Tenant: Maple Harbour Credit Union (fictional name only)
- Licence obtained: TODO (Business Basic trial / Business Premium trial / Entra ID P1 or P2 trial / none; write what Microsoft actually offered)
- Trial start date: TODO
- Recurring billing confirmed OFF on: TODO
- Configuration dates: TODO
- Export run on: TODO
- Trial lapse date: TODO

## Control 1: Passkeys / phishing-resistant MFA for all staff

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 2: Authentication strengths: require phishing-resistant methods for admins

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 3: Conditional Access: block legacy authentication

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 4: Conditional Access: require strong authentication for admins

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 5: Conditional Access: sign-in from a new device for privileged roles requires strong re-authentication

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 6: Temporary Access Pass (TAP) issued only after verified identity (out-of-band callback, per Track 1)

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 7: Self-service password reset with strong methods only

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Control 8: Two break-glass accounts (emergency admin accounts) excluded from Conditional Access, stored offline

- **Before:** TODO (setting value, or screenshot file name)
- **After:** TODO
- **Evidence:** TODO (screenshot file name, blurred)
- **Date:** TODO
- **Needed P1?:** TODO (yes / no / unsure)

## Test accounts

All fictional Maple Harbour staff. Record only the role and the purpose here; passwords never go in this repo.

| Role | Display name (fictional) | Sign-in name | Purpose |
|---|---|---|---|
| Standard user | TODO | TODO@mapleharbour.example | Sign in after each policy is switched on |
| Admin | TODO | TODO@mapleharbour.example | Test the admin-only rules |
| Break-glass 1 | TODO | TODO@mapleharbour.example | Emergency access, excluded from Conditional Access, password stored offline |
| Break-glass 2 | TODO | TODO@mapleharbour.example | Second emergency account, stored separately from the first |

Note: a trial tenant normally gives accounts a default domain you do not control. Whether the `mapleharbour.example` sign-in names can be used as written is `TODO(verify on the day)`. If they cannot, write "default domain (not recorded)" here instead of the real name.

## What I could not do and why

TODO (for each control not configured: which one, what stopped it, for example "needed P1, not offered")
