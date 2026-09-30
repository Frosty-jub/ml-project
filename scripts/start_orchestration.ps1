param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports/orchestration | Out-Null
Start-Transcript -Path reports/orchestration/bootstrap_powershell.txt -Force
function Invoke-Docker {
    $DockerArgs = $args
    Write-Host ('PS> docker ' + ($DockerArgs -join ' ')) -ForegroundColor Cyan
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw ('docker failed: ' + ($DockerArgs -join ' ')) }
}
try {
    $revision = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Run bootstrap from a Git checkout' }
    $dirty = [bool](git status --porcelain)
    Invoke-Docker compose -f orchestration/airflow/compose.yaml build --build-arg "PROJECT_GIT_COMMIT=$revision" --build-arg "PROJECT_GIT_DIRTY=$dirty" airflow
    if (-not $BuildOnly) {
        Invoke-Docker compose -f orchestration/airflow/compose.yaml up -d
        $ready = $false
        for ($attempt=0; $attempt -lt 90; $attempt++) {
            try {
                $version = Invoke-RestMethod http://127.0.0.1:18090/api/v2/version -TimeoutSec 3
                Write-Host ('Airflow ready: ' + ($version | ConvertTo-Json -Compress)) -ForegroundColor Green
                $ready = $true
                break
            } catch { Write-Host 'Waiting for Airflow startup...' }
            Start-Sleep -Seconds 5
        }
        if (-not $ready) { throw 'Airflow did not start within the allowed time' }
        Invoke-Docker compose -f orchestration/airflow/compose.yaml ps
    }
    Write-Host 'BOOTSTRAP COMPLETE' -ForegroundColor Green
} finally { Stop-Transcript }
