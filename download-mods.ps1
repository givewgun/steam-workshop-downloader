[CmdletBinding()]
param(
    [ValidatePattern('^[1-9][0-9]*$')][string]$AppId,
    [Alias('Items', 'Collection')][string[]]$Source,
    [Alias('Manifest')][string[]]$ListFile,
    [ValidatePattern('^[A-Za-z0-9_]+$')][string]$SteamUser = 'anonymous',
    [string]$SteamCmdPath,
    [string]$OutputDirectory,
    [ValidateRange(0, 2147483647)][int]$TimeoutSeconds = 0,
    [switch]$PrepareOnly,
    [switch]$SkipUnavailable,
    [switch]$RecursiveCollections
)
$ErrorActionPreference = 'Stop'
if (-not $SteamCmdPath) { $SteamCmdPath = Join-Path $PSScriptRoot 'steamcmd.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'runs' }
if (-not $Source -and -not $ListFile) {
    if (-not $AppId) { $AppId = Read-Host 'Steam game App ID (blank to detect from Workshop items)' }
    $choice = Read-Host 'Workshop item/collection links or IDs, or path to a TXT/JSON list'
    if ([string]::IsNullOrWhiteSpace($choice)) { throw 'A Workshop source or list file is required.' }
    if (Test-Path -LiteralPath $choice -PathType Leaf) { $ListFile = @($choice) }
    else { $Source = @($choice) }
    if (-not $PrepareOnly -and -not $PSBoundParameters.ContainsKey('SteamUser')) {
        $account = Read-Host 'Steam account name (blank for anonymous)'
        if ($account) { $SteamUser = $account }
    }
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.10+ is required. Install Python and enable its PATH option.' }
$arguments = @((Join-Path $PSScriptRoot 'workshop.py'), '--steamcmd', $SteamCmdPath,
    '--output', $OutputDirectory, '--steam-user', $SteamUser, '--timeout-seconds', "$TimeoutSeconds")
if ($AppId) { $arguments += @('--app-id', $AppId) }
foreach ($file in $ListFile) { $arguments += @('--list', $file) }
if ($PrepareOnly) { $arguments += '--prepare-only' }
if ($SkipUnavailable) { $arguments += '--skip-unavailable' }
if ($RecursiveCollections) { $arguments += '--recursive-collections' }
$arguments += '--'
foreach ($item in $Source) { $arguments += $item }
& $python.Source @arguments
exit $LASTEXITCODE
