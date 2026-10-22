# export-config.ps1 - READ-ONLY export of the trial tenant's identity configuration.
#
# What it does: reads Conditional Access policies, named locations, authentication
# method settings, authentication strengths and directory-role membership, and saves
# each as a JSON file under 3e-anti-takeover-tenant/export/ so Eojin can attach the
# evidence to before-after-report.md. It changes nothing in the tenant.
#
# BEFORE YOU RUN IT (on Eojin's own PC, in PowerShell 7, never in a cloud session):
#   1. Install the Microsoft Graph modules once. TODO(verify): the exact module names on
#      the day. Expected: Microsoft.Graph.Authentication,
#      Microsoft.Graph.Identity.SignIns, Microsoft.Graph.Identity.DirectoryManagement.
#   2. Sign in yourself with read-only permissions:
#        Connect-MgGraph -Scopes Policy.Read.All,Directory.Read.All
#      TODO(verify): that these two scopes are enough for every cmdlet below.
#   3. Run this script (any folder works; it finds export/ from its own location):
#        pwsh ./3e-anti-takeover-tenant/scripts/export-config.ps1
#
# This script never signs in for you. It checks Get-MgContext and stops if you are not
# connected.
#
# Cmdlets used (all read-only "Get" cmdlets). TODO(verify): every cmdlet and module name
# below on the day; they were written from memory without access to Microsoft's docs:
#   Get-MgIdentityConditionalAccessPolicy
#   Get-MgIdentityConditionalAccessNamedLocation
#   Get-MgPolicyAuthenticationMethodPolicy
#   Get-MgPolicyAuthenticationStrengthPolicy
#   Get-MgDirectoryRole  together with  Get-MgDirectoryRoleMember
#
# WARNING: the JSON files contain your tenant ID and object IDs (IDs of users, groups
# and policies). They stay on your PC. The export/ folder is git-ignored on purpose:
# never commit, paste or screenshot them. Blur any ID before sharing a picture.

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The only place this script writes: the git-ignored export folder inside the repo.
# It is found from this script's own location, so it does not matter where you run it from.
$exportDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..' 'export'))

# Stop early if the user has not connected. The message points to the header above
# instead of naming the connect command, so this script contains no sign-in call.
if (-not (Get-Command Get-MgContext -ErrorAction SilentlyContinue)) { Write-Output 'Install the modules named in this script''s header first (step 1).'; exit 1 }
$context = Get-MgContext
if ($null -eq $context) {
    Write-Output 'Not connected to Microsoft Graph. Run the connect command shown in this script''s header (step 2), then run this script again.'
    exit 1
}

if (-not (Test-Path -Path $exportDir -PathType Container)) {
    Write-Output "Export folder not found: $exportDir. Check that the 3e-anti-takeover-tenant/export/ folder exists."
    exit 1
}

Write-Output 'WARNING: the exported files contain tenant and object IDs. Keep them on this PC; do not commit or share them.'

function Save-Export {
    # Writes one JSON file under the export folder and prints a one-line count.
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Items
    )
    $path = Join-Path -Path $exportDir -ChildPath ($Name + '.json')
    ConvertTo-Json -InputObject $Items -Depth 10 -AsArray | Set-Content -Path $path -Encoding utf8
    Write-Output ('{0}: {1} item(s) exported' -f $Name, @($Items).Count)
}

# Print only the exception type, never the message: Graph error bodies can contain object IDs
# and these logs can end up public.
function Write-ExportFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord
    )
    Write-Output ('{0}: FAILED ({1}); skipped' -f $Name, $ErrorRecord.Exception.GetType().Name)
}

try {
    Save-Export -Name 'conditional-access-policies' -Items @(Get-MgIdentityConditionalAccessPolicy -All)
}
catch { Write-ExportFailure -Name 'conditional-access-policies' -ErrorRecord $_ }

try {
    Save-Export -Name 'named-locations' -Items @(Get-MgIdentityConditionalAccessNamedLocation -All)
}
catch { Write-ExportFailure -Name 'named-locations' -ErrorRecord $_ }

try {
    # One settings object, not a list.
    Save-Export -Name 'authentication-method-policy' -Items @(Get-MgPolicyAuthenticationMethodPolicy)
}
catch { Write-ExportFailure -Name 'authentication-method-policy' -ErrorRecord $_ }

try {
    Save-Export -Name 'authentication-strengths' -Items @(Get-MgPolicyAuthenticationStrengthPolicy -All)
}
catch { Write-ExportFailure -Name 'authentication-strengths' -ErrorRecord $_ }

try {
    # Directory roles that are activated in the tenant, each with its members.
    $roleReport = @()
    foreach ($role in @(Get-MgDirectoryRole -All)) {
        $members = @(Get-MgDirectoryRoleMember -DirectoryRoleId $role.Id -All)
        $roleReport += [pscustomobject]@{
            RoleName    = $role.DisplayName
            RoleId      = $role.Id
            MemberCount = $members.Count
            MemberIds   = @($members | ForEach-Object { $_.Id })
        }
    }
    Save-Export -Name 'directory-role-members' -Items $roleReport
}
catch { Write-ExportFailure -Name 'directory-role-members' -ErrorRecord $_ }

Write-Output 'Done. Files are in 3e-anti-takeover-tenant/export/ (local only, git-ignored).'
