param(
    [ValidateSet('normal','bad_data','bad_quality','monitoring')][string]$Scenario = 'normal',
    [string]$RunId = ('acceptance_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*$')][string]$ComposeProject = 'ml-orchestration'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports/orchestration | Out-Null
Start-Transcript -Path ('reports/orchestration/' + $RunId + '_powershell.txt') -Force
$composeFiles = @('-p',$ComposeProject,'-f','orchestration/airflow/compose.yaml')
function Invoke-Docker {
    Write-Host ('PS> docker ' + ($args -join ' ')) -ForegroundColor Cyan
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed' }
}
try {
    Invoke-Docker compose @composeFiles exec -T airflow chown -R airflow:root /opt/airflow-state
    $dag = if ($Scenario -eq 'monitoring') { 'demand_monitoring' } else { 'demand_forecasting_e2e' }
    $dagScenario = if ($Scenario -eq 'monitoring') {'normal'} else {$Scenario}
    Invoke-Docker compose @composeFiles exec -T --user airflow airflow airflow dags unpause $dag
    Invoke-Docker compose @composeFiles exec -T --user airflow airflow python /project/orchestration/airflow/trigger.py $RunId $dag $dagScenario
    $done = $false
    for ($i=0; $i -lt 360; $i++) {
        Write-Host ('PS> airflow dags list-runs -o json ' + $dag) -ForegroundColor Cyan
        $raw = docker compose @composeFiles exec -T --user airflow airflow airflow dags list-runs -o json $dag
        if ($LASTEXITCODE -ne 0) { throw 'Could not read DAG state' }
        $runs = ($raw -join "`n") | ConvertFrom-Json
        $run = $runs | Where-Object { $_.run_id -eq $RunId }
        Write-Host ($run | ConvertTo-Json -Compress)
        if ($run.state -in @('success','failed')) { $done = $true; break }
        Start-Sleep -Seconds 10
    }
    if (-not $done) { throw 'DAG did not finish in 60 minutes' }
    Write-Host ('PS> airflow tasks states-for-dag-run -o json ' + $dag + ' ' + $RunId) -ForegroundColor Cyan
    $taskRaw = docker compose @composeFiles exec -T --user airflow airflow airflow tasks states-for-dag-run -o json $dag $RunId
    if ($LASTEXITCODE -ne 0) { throw 'Could not read task states' }
    Write-Host ($taskRaw -join "`n")
    Invoke-Docker compose @composeFiles cp airflow:/project/reports/orchestration/. reports/orchestration/
    $evidenceDir = 'reports/orchestration/' + $RunId
    New-Item -ItemType Directory -Force $evidenceDir | Out-Null
    $run | ConvertTo-Json -Depth 10 | Set-Content ($evidenceDir + '/airflow_run.json') -Encoding utf8
    ($taskRaw -join "`n") | Set-Content ($evidenceDir + '/airflow_tasks.json') -Encoding utf8
    New-Item -ItemType Directory -Force ($evidenceDir + '/task_logs') | Out-Null
    Invoke-Docker compose @composeFiles cp ('airflow:/opt/airflow-state/logs/dag_id=' + $dag + '/run_id=' + $RunId + '/.') ($evidenceDir + '/task_logs/')
    $expected = if ($Scenario -in @('bad_data','bad_quality')) {'failed'} else {'success'}
    if ($run.state -ne $expected) { throw ('Unexpected DAG state: ' + $run.state + '; expected ' + $expected) }
    if ($Scenario -in @('bad_data','bad_quality')) {
        $summary = Get-Content ('reports/orchestration/' + $RunId + '/summary.json') -Raw | ConvertFrom-Json
        if (-not $summary.production_unchanged) { throw 'Failed run changed production' }
        if ($summary.steps.register_models.status -ne 'not_run') { throw 'Failed gate reached registration' }
        $expectedFailure = if ($Scenario -eq 'bad_data') { 'prepare_data' } else { 'candidate_quality_gate' }
        if ($summary.steps.$expectedFailure.status -ne 'failed') { throw ('Failure did not occur at ' + $expectedFailure) }
        if ($summary.steps.initialize.status -ne 'success') { throw 'Failure fixture did not initialize' }
        if (-not (Test-Path ($evidenceDir + '/failure_alert.json'))) { throw 'Failure alert is missing' }
    }
    @{ scenario = $Scenario; run_id = $RunId; expected_state = $expected; actual_state = $run.state;
       passed = $true; checked_at = (Get-Date).ToUniversalTime().ToString('o') } |
        ConvertTo-Json | Set-Content ($evidenceDir + '/acceptance.json') -Encoding utf8
    Write-Host ('ACCEPTANCE PASSED: ' + $Scenario + ' / ' + $RunId) -ForegroundColor Green
} finally { Stop-Transcript }
