#!/usr/bin/env bash
# Cloud environment setup: PowerShell (needed from T3-S01), then Keycloak 26.8.1 (needed from T3-S02). Java 21 is preinstalled.
# Stays under about 5 minutes so the environment can be cached; a WARN line means "slow or missing", never a failed session.
if ! command -v pwsh >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  . /etc/os-release 2>/dev/null
  ( apt-get update -qq && apt-get install -y -qq wget apt-transport-https \
    && wget -q -O /tmp/pmp.deb "https://packages.microsoft.com/config/${ID:-ubuntu}/${VERSION_ID:-24.04}/packages-microsoft-prod.deb" \
    && dpkg -i /tmp/pmp.deb && apt-get update -qq && apt-get install -y -qq powershell ) || echo "WARN pwsh install failed"
fi
KC=26.8.1
if [ ! -x /opt/keycloak/bin/kc.sh ]; then
  mkdir -p /opt/keycloak
  curl -fsSL --max-time 120 -o /tmp/kc.tgz "https://github.com/keycloak/keycloak/releases/download/${KC}/keycloak-${KC}.tar.gz" \
    || curl -fsSL --max-time 120 -o /tmp/kc.tgz "https://repo1.maven.org/maven2/org/keycloak/keycloak-quarkus-dist/${KC}/keycloak-quarkus-dist-${KC}.tar.gz" \
    || echo "WARN keycloak download failed"
  [ -s /tmp/kc.tgz ] && tar -xzf /tmp/kc.tgz -C /opt/keycloak --strip-components=1 && rm -f /tmp/kc.tgz
fi
exit 0
