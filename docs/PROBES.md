# Probes — td-3-iam

### 2026-10-22 (T3-S01)

## Probe 2026-10-22T09:58Z
- arch: x86_64
- cpus: 4  memory: 15 GB
- avx2 flags: 4
- python: Python 3.13.16
- java: Picked up JAVA_TOOL_OPTIONS: [proxy settings removed before commit — they list internal proxy hosts]
- docker:   not available
- pwsh: 7.6.7
- keycloak: /opt/keycloak Keycloak 26.8.1
- reach https://repo1.maven.org/maven2/ -> HTTP 200
- reach https://mcr.microsoft.com/v2/ -> HTTP 200
- reach https://packages.microsoft.com/ -> HTTP 200
- reach https://pypi.org/simple/ -> HTTP 200
- reach https://www.powershellgallery.com/ -> HTTP 000
- reach https://graph.microsoft.com/v1.0/ -> HTTP 000
- reach https://management.azure.com/ -> HTTP 000

Notes on this run (added by the director, not by `probe.sh`): the `java:` line's proxy host list was removed before commit (it names internal hosts); `docker:` and `keycloak:` each printed over two lines and are joined here. This probe ran in one cloud session shared with the hub and the other three tracks (Eojin's D0 launch), on the same machine where the Track 1, 3 and 4 setup scripts had just run.

What the two lines that matter for Track 3 mean:
- `pwsh: 7.6.7` — PowerShell 7 is installed (by `environment/setup.sh`), so this session can syntax-check `export-config.ps1` with PowerShell's own parser. PowerShell Gallery is still blocked (`HTTP 000`), so PSScriptAnalyzer and the Microsoft Graph modules run only in the `pwsh-lint` CI job or on Eojin's PC.
- `keycloak: /opt/keycloak Keycloak 26.8.1` — Keycloak is installed, so T3-S02 is not blocked. No caveat needed for either line.
- `graph.microsoft.com` and `management.azure.com` answer `HTTP 000` (blocked), as the safety rules require: nothing in this session can reach a tenant.
