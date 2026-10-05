[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$ProjectPath = '',
    [switch]$SkipAuth
)
$ErrorActionPreference = 'Stop'
$checks = [ordered]@{}
foreach ($name in @('git', 'python', 'codex', 'claude')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    $checks[$name] = [ordered]@{ installed = [bool]$command }
}
if ($ProjectPath) {
    $checks['project'] = @{ exists = (Test-Path -LiteralPath $ProjectPath -PathType Container) }
}
if (-not $SkipAuth) {
    # Capture output locally; never emit account details or credential contents.
    if ($checks['codex'].installed) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $codexText = (& codex login status 2>&1 | Out-String)
        $codexExit = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        $checks['codex']['authenticated'] = ($codexExit -eq 0 -and $codexText -match '(?i)logged in' -and $codexText -notmatch '(?i)not logged in')
        $codexText = $null
    }
    if ($checks['claude'].installed) {
        try {
            $claudeText = (& claude auth status 2>$null | Out-String)
            $claudeStatus = $claudeText | ConvertFrom-Json
            $checks['claude']['authenticated'] = ($claudeStatus.loggedIn -eq $true)
            $checks['claude']['auth_method'] = $claudeStatus.authMethod
            $checks['claude']['subscription'] = $claudeStatus.subscriptionType
        } catch {
            $checks['claude']['authenticated'] = $false
            $checks['claude']['reason'] = 'status_unavailable'
        } finally { $claudeText = $null; $claudeStatus = $null }
    }
}
$missing = @($checks.Keys | Where-Object {
    ($checks[$_].Contains('installed') -and -not $checks[$_].installed) -or
    ($checks[$_].Contains('authenticated') -and -not $checks[$_].authenticated) -or
    ($checks[$_].Contains('exists') -and -not $checks[$_].exists)
})
$report = [ordered]@{
    kind = 'local_readiness_only'
    checked_at = [DateTime]::UtcNow.ToString('o')
    status = $(if ($missing.Count) { 'BLOCKED' } elseif ($SkipAuth) { 'INCOMPLETE' } else { 'READY_FOR_SMOKE_TEST' })
    checks = $checks
    blockers = $missing
    live_rag_verified = $false
    github_runner_registered = $false
    release_ready = $false
}
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutput
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
if (Test-Path -LiteralPath $resolvedOutput) { throw 'Refusing to overwrite an existing readiness report.' }
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resolvedOutput -Encoding utf8
# Only a small, non-sensitive summary is printed.
[ordered]@{ status = $report.status; blockers = $missing; release_ready = $false } | ConvertTo-Json -Compress
if ($missing.Count) { exit 2 }
if ($SkipAuth) { exit 3 }
exit 0
