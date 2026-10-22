# Caveats found during execution

A caveat is anything that turned out different from the plan: a missing tool, a limit, a wrong assumption, a cheaper path. One line each, newest at the bottom. `status` reads the last 5 lines.

Line format:
`- YYYY-MM-DD <ID> | what happened | impact: this session / <later IDs> / plan | what I did | needs Eojin: yes/no`
- 2026-10-22 T3-S01 | Ran in one cloud session with the hub and the other tracks (Eojin's D0 launch, no plan-approval stop); this session can push only to `claude/friendly-heisenberg-seafff`, not the brief's branch name | impact: this session | used that branch; one PR | needs Eojin: no
- 2026-10-22 T3-S01 | Credit balances not available during the unattended run; the usage menu shows one combined number for all five D0 sessions | impact: this session | placeholders in `COSTS.md`; record the combined number in the hub `COSTS.md` | needs Eojin: yes
- 2026-10-22 T3-S01 | Probe: `pwsh: 7.6.7` and `keycloak: … 26.8.1` both installed, so no caveat for step 7 or T3-S02; PowerShell Gallery blocked (HTTP 000) as expected | impact: none | parser check run here; PSScriptAnalyzer left to the `pwsh-lint` CI job | needs Eojin: no
- 2026-10-22 T3-S01 | Brief's Day is D1; it ran on D0 at Eojin's request | impact: plan | none | needs Eojin: no
- 2026-10-22 T3-S01 | OSFI B-13 and AL26-010 mappings in `controls.md` are the builder's judgement (weak links marked "(indirect)"); Cyber Centre control numbers #5/#12 carry a TODO(verify) | impact: this session | stated in `controls.md` | needs Eojin: yes (review the mapping)
- 2026-10-22 T3-S01 | Redteam mid-review: 2 must-fix lockout traps in `CONFIGURE.md` (admin strong-auth policy on before any admin had a passkey; break-glass tested only at the end) plus cost, privacy and mapping fixes | impact: this session | all 14 items applied; section order kept | needs Eojin: no
- 2026-10-22 T3-S01 | Verifier found `ConvertTo-Json -InputObject … -AsArray` wrapped every export in an extra array (`[[…]]`); also the script prints "Done." even if every export failed | impact: this session | removed `-AsArray` (checked: 2 items, 1 item and 0 items give a flat array); the "Done" wording left as is because each failure is printed | needs Eojin: no
- 2026-10-22 T3-S01 follow-up | Eojin chose the made-up tenant organisation name `northpine-demo`; it now appears in `TRIAL-RUNBOOK.md` and `before-after-report.md`. Publishing it as the default-domain name too would put the tenant's built-in address in this public repo, which the runbook's safety box forbids | impact: 3E setup | runbook says to use a different, unpublished string for the default-domain name | needs Eojin: yes (confirm, or say if you want the default domain to be `northpine-demo` as well)
