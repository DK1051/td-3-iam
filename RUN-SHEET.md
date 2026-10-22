# Run sheet — td-3-iam (Track 3 · IAM)

Day numbers are relative: D0 = the day Eojin uploads the kit. If D0 = Oct 22, then D1 = Oct 23, D2 = Oct 24, D3 = Oct 25, D6 = Oct 28, D9 = Oct 31, D10 = Nov 1; buffer D11–D13; hard stop D14 = Nov 5, 4:00 PM KST. Caps are planning numbers (total for this repo: $54 of the $250 credit); recalibrate after the hub's H00 and the first build. The full cross-repo table lives in the hub repo (`takeover-defense/docs/MASTER-RUN-SHEET.md`).

Status words: `TODO` → `IN PROGRESS` → `DONE (PR #n)`; or `BLOCKED (see CAVEATS)`; or `CUT (moved past Nov 5)`.

- [ ] T3-S01 · D1 · 3E scaffold + trial runbook · needs: kit · cap $5 · status: TODO
- [ ] T3-S02 · D2 · 3H engine core · needs: T3-S01 merged · cap $12 · status: TODO
- [ ] T3-S03 · D3 · 3H attestation, SoD, proofing gate · needs: T3-S02 merged · cap $10 · status: TODO
- [ ] T3-C1 · D6 · class 3H · needs: T3-S03 merged · cap $5 · status: TODO
- [ ] T3-S04 · D9 · 3A Agent Passport (redteam first) — FIRST TO CUT · needs: T3-S03 merged, Eojin's 30 requests (minimum 15, at least 5 in Korean) · cap $18 · status: TODO
- [ ] T3-C2 · D10 · class 3A · needs: T3-S04 merged · cap $4 · status: TODO

Cut order across the whole portfolio when time or credit runs short: T3-S04 first (then T1-S04, T4-S03, T4-S02, T2-S03). Never cut T3-S01.
