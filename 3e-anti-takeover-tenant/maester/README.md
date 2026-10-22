# Maester (optional)

Maester is an open-source test suite for Microsoft Entra settings: it runs a long list of checks against a tenant (for example "is legacy authentication blocked?") and reports which ones pass or fail. It would give 3E a second, independent view of the controls that `before-after-report.md` records by hand.

Maester can run on a schedule in GitHub Actions and sign in to the tenant with OIDC (OpenID Connect: GitHub proves its identity to Microsoft for each run, so no password or secret is stored in the repository). Microsoft's side of that setup is described on Maester's page for it: https://maester.dev/docs/monitoring/github. `TODO(verify on the day)`: that the page and its steps are still current.

Setting it up is Eojin's own, optional work, done with his own tenant account on his own PC. It is not part of any session's acceptance criteria, and no workflow file exists in this repo. If it is ever added, it must use no stored secrets and print no tenant or object IDs in the (public) CI logs.
