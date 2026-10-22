# 3E controls

These controls are **aligned to** the cited Canadian guidance (OSFI Guideline B-13 section 3.2.7, the Cyber Centre's baseline cyber security controls, and the Cyber Centre alert AL26-010). "Aligned to" means each control was chosen to serve the same goal as the text it cites. It is not a statement that any organisation meets, or has been checked against, those documents.

Reading the table:
- **Licence** is the Microsoft tier the control needs. `P1` = Microsoft Entra ID P1 (Conditional Access, authentication strengths); `P2` = Entra ID P2 (risk-based policies); `Free` = included without a paid tier (for example sign-in logs); `TODO(verify)` = the tier has not been confirmed and is not guessed. If P1 is not available, the control is marked "not configured — needs P1" in `before-after-report.md`.
- **OSFI B-13 §3.2.7** quotes one of five phrases from that section. The match between a control and a phrase is Claude's judgement, to be reviewed by Eojin; several controls fit more than one phrase. `TODO(verify): phrases checked against the current B-13 text`.
- **Cyber Centre baseline control** is `#5` (strong user authentication) or `#12` (access control). `TODO(verify)`: re-check both numbers against the Cyber Centre's current baseline controls page.
- **AL26-010 recommendation** quotes the alert as reproduced in `README.md`. Where a control only supports the quote indirectly, the cell says "indirect".

| Control | What it stops (plain English) | Licence | OSFI B-13 §3.2.7 | Cyber Centre baseline control | AL26-010 recommendation |
|---|---|---|---|---|---|
| Passkeys / phishing-resistant MFA for all staff | A stolen or reset password is not enough to sign in, and a fake sign-in page cannot capture the second check | TODO(verify) | "Implementing MFA across external-facing channels and privileged accounts" | #5 (strong user authentication) | "convince support staff to reset MFA or enroll attacker-controlled devices" (the reset gains the caller little if sign-in needs a device-bound passkey) |
| Authentication strengths: require phishing-resistant methods for admins | An admin cannot be let in with a weak method such as a text-message code | P1 | "Implementing MFA across external-facing channels and privileged accounts" | #5 (strong user authentication) | "restrict and closely monitor MFA reset, recovery, and device re-enrolment processes" (indirect) |
| Conditional Access: block legacy authentication | Old sign-in protocols that cannot do MFA are closed, so a password alone cannot get in through them | P1 | "Implementing MFA across external-facing channels and privileged accounts" | #5 (strong user authentication) | "restrict and closely monitor MFA reset, recovery, and device re-enrolment processes" (indirect) |
| Conditional Access: require strong authentication for admins | Admin accounts always face a strong sign-in check, whatever device or place they come from | P1 | "Implementing MFA across external-facing channels and privileged accounts" | #5 (strong user authentication) | "enhanced verification and approval" |
| Conditional Access: sign-in from a new device for privileged roles requires strong re-authentication | A caller who enrols a new device after a fake reset must pass a strong check again before using admin rights | P1 | "Implementing MFA across external-facing channels and privileged accounts" | #12 (access control) | "convince support staff to reset MFA or enroll attacker-controlled devices" |
| Temporary Access Pass (TAP) issued only after verified identity (out-of-band callback, per Track 1) | A one-time sign-in code is handed out only after the person was verified by a call back on a known number, not on the caller's word | TODO(verify) | "Implementing MFA across external-facing channels and privileged accounts" (indirect) | #12 (access control) | "out-of-band verification procedures for identity-related requests" |
| Self-service password reset with strong methods only | Staff reset their own password without calling the helpdesk, and only with methods a caller cannot talk their way past | TODO(verify) | "Implementing MFA across external-facing channels and privileged accounts" | #5 (strong user authentication) | "restrict and closely monitor MFA reset, recovery, and device re-enrolment processes" |
| Two break-glass accounts (emergency admin accounts) excluded from Conditional Access, stored offline | A strict policy or a mistake cannot lock everyone out of the tenant, and the emergency passwords are not sitting where an attacker can reach them | Free | "Managing privileged account credentials using a secure vault" | #12 (access control) | "restrict and closely monitor MFA reset, recovery, and device re-enrolment processes" (indirect) |

Notes on the table:
- The break-glass row is marked `Free` because creating the accounts and reading their sign-in logs costs nothing extra. Excluding them from Conditional Access policies is only possible once those policies exist, which needs P1.
- Passkeys, TAP and self-service password reset stay `TODO(verify)` until Eojin sees on the day which tier each one needs.

## Glossary

- **Conditional Access**: rules of the form "if a sign-in matches these conditions (who, from where, on what device), then require this (for example a strong second check) or block it". Needs P1.
- **Authentication strength**: a named list of sign-in methods that count as strong enough for a given rule. Conditional Access can require a specific strength.
- **Phishing-resistant**: a sign-in method that cannot be tricked out of the user on a fake site, because the secret never leaves the user's device or is tied to the real site's address (passkeys and security keys are examples).
- **TAP (Temporary Access Pass)**: a short-lived code an admin issues so a user can sign in and register a new method, used here only after the person's identity is verified out of band.
- **Break-glass account**: an emergency administrator account kept outside the normal rules and used only if everything else is locked. Its password is stored offline and every use is a reportable event.
- **Legacy authentication**: older sign-in protocols (for example basic username-and-password over old mail protocols) that cannot ask for a second check, so attackers use them to skip MFA.
