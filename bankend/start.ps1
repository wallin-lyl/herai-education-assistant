$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} elseif (Test-Path -LiteralPath $localPython) {
    $python = $localPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = 'python'
} else {
    throw '未找到 Python。请先安装 Python 并运行 pip install -r requirements.txt。'
}

& $python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
