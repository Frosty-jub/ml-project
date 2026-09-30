param([ValidateSet('normal','bad_data','bad_quality')][string]$Scenario = 'normal')
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot/start_orchestration.ps1"
& "$PSScriptRoot/verify_orchestration.ps1" -Scenario $Scenario
