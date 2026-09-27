param([string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $PythonExecutable) {
    $taskAnaconda = Join-Path $env:USERPROFILE 'anaconda3\python.exe'
    if (Test-Path -LiteralPath $taskAnaconda) { $PythonExecutable = $taskAnaconda }
    else { $PythonExecutable = 'python' }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $PythonExecutable -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create a Python environment' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Failed to install dependencies' }
if (-not $env:MODEL_DIR -and -not (Test-Path -LiteralPath 'artifacts\demo\model.joblib')) {
    & '.\.venv\Scripts\python.exe' -m scripts.train_demo
    if ($LASTEXITCODE -ne 0) { throw 'Failed to generate the demonstration model' }
}
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 18005 --workers 1 --no-access-log
