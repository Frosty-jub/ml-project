param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*$')][string]$ComposeProject = ('ml-orchestration-clean-' + (Get-Date -Format 'yyyyMMddHHmmss')),
    [string]$RunId = ('acceptance_clean_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [int]$AirflowPort = 18091,
    [int]$CandidatePort = 18026,
    [int]$ProductionPort = 18025
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$savedPorts = @($env:AIRFLOW_PORT, $env:CANDIDATE_PORT, $env:PRODUCTION_PORT)
$composeFiles = @('-p', $ComposeProject, '-f', 'orchestration/airflow/compose.yaml')
$evidenceDir = 'reports/orchestration/' + $RunId
New-Item -ItemType Directory -Force $evidenceDir | Out-Null
try {
    $env:AIRFLOW_PORT = [string]$AirflowPort
    $env:CANDIDATE_PORT = [string]$CandidatePort
    $env:PRODUCTION_PORT = [string]$ProductionPort
    Write-Host ('PS> docker volume ls --filter label=com.docker.compose.project=' + $ComposeProject) -ForegroundColor Cyan
    $existing = docker volume ls --filter ('label=com.docker.compose.project=' + $ComposeProject) --format '{{.Name}}'
    if ($LASTEXITCODE -ne 0 -or $existing) { throw 'Choose a new project name; existing volumes are preserved' }
    $imageId = docker image inspect demand-orchestration:local --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0) { throw 'Build the image with start_orchestration.ps1 -BuildOnly first' }
    @{ project = $ComposeProject; existing_volumes = @($existing); image_id = $imageId;
       started_at = (Get-Date).ToUniversalTime().ToString('o') } |
        ConvertTo-Json | Set-Content ($evidenceDir + '/clean_preflight.json') -Encoding utf8
    Write-Host ('PS> docker compose ' + ($composeFiles -join ' ') + ' up -d --no-build') -ForegroundColor Cyan
    docker compose @composeFiles up -d --no-build
    if ($LASTEXITCODE -ne 0) { throw 'Clean bootstrap failed' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            Invoke-RestMethod ('http://127.0.0.1:' + $AirflowPort + '/api/v2/version') -TimeoutSec 3
            $ready = $true
            break
        } catch { }
        Start-Sleep -Seconds 5
    }
    if (-not $ready) { throw 'Clean Airflow did not start' }
    & "$PSScriptRoot/verify_orchestration.ps1" -Scenario normal -RunId $RunId -ComposeProject $ComposeProject
    Write-Host ('PS> docker compose ' + ($composeFiles -join ' ') + ' stop') -ForegroundColor Cyan
    docker compose @composeFiles stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the extra acceptance stack' }
} finally {
    $env:AIRFLOW_PORT, $env:CANDIDATE_PORT, $env:PRODUCTION_PORT = $savedPorts
}
