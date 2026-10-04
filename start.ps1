param([switch]$WebOnly, [string]$ProjectPath)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run the one-time Python setup in README.md first.' }
if (-not (Test-Path -LiteralPath 'frontend\node_modules\vite\bin\vite.js')) { throw 'Run npm ci in frontend once; see README.md.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 20.19+ first.' }
$terminalDir = if ($ProjectPath) { (Resolve-Path -LiteralPath $ProjectPath).Path } else { $PSScriptRoot }
if (-not $WebOnly) {
    & '.\.venv\Scripts\python.exe' -c 'import tkinter'
    if ($LASTEXITCODE -ne 0) { throw 'Python Tkinter is required for the floating companion. Use -WebOnly to start just the workspace.' }
}
$backendJob = Start-Job -ArgumentList $PSScriptRoot -ScriptBlock {
    param($projectDir)
    Set-Location (Join-Path $projectDir 'backend')
    & (Join-Path $projectDir '.venv\Scripts\python.exe') -m uvicorn app.main:app --host 127.0.0.1 --port 8000 2>&1 | ForEach-Object { "$($_)" }
}
$frontendJob = Start-Job -ArgumentList $PSScriptRoot -ScriptBlock {
    param($projectDir)
    Set-Location (Join-Path $projectDir 'frontend')
    node node_modules\vite\bin\vite.js --host 127.0.0.1 --strictPort 2>&1 | ForEach-Object { "$($_)" }
}
 $desktopJob = $null
Write-Host 'RoboDoctor: http://127.0.0.1:5173 · Ctrl+C to stop'
try {
    if (-not $WebOnly) {
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            try { Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/workspace' -TimeoutSec 1 | Out-Null; break }
            catch { Start-Sleep -Seconds 1 }
        }
        $desktopJob = Start-Job -ArgumentList $PSScriptRoot,$terminalDir -ScriptBlock {
            param($projectDir,$terminalDir)
            Set-Location $projectDir
            & (Join-Path $projectDir '.venv\Scripts\python.exe') -m companion.desktop --cwd $terminalDir 2>&1 | ForEach-Object { "$($_)" }
        }
        Write-Host 'Floating companion started. Double-click to inspect; right-click to open the managed terminal.'
    }
    while ($backendJob.State -eq 'Running' -and $frontendJob.State -eq 'Running') {
        Receive-Job $backendJob, $frontendJob
        if ($desktopJob) { Receive-Job $desktopJob }
        Start-Sleep -Seconds 1
    }
    Receive-Job $backendJob, $frontendJob
    Write-Warning 'A server stopped; shutting down RoboDoctor.'
} finally {
    Stop-Job $backendJob, $frontendJob
    Remove-Job $backendJob, $frontendJob
    if ($desktopJob) { Stop-Job $desktopJob; Remove-Job $desktopJob }
}
