$ErrorActionPreference = "SilentlyContinue"
$projectRoot = "C:\Users\91948\Desktop\IPCS\ipcs projects\legal research project\legal-ai-assistant"
$datasetDir = Join-Path $projectRoot "datasets\generated"
$backendDir = Join-Path $projectRoot "backend\data"
$host.UI.RawUI.WindowTitle = "Legal AI Assistant - Live Monitor"
while ($true) {
    Clear-Host
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "       LEGAL AI ASSISTANT - LIVE DEVELOPMENT MONITOR" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ("Updated: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Write-Host ""
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        Write-Host ("Backend (FastAPI) : HTTP " + [int]$r.StatusCode + " - RUNNING") -ForegroundColor Green
    } catch {
        Write-Host "Backend (FastAPI) : NOT RESPONDING" -ForegroundColor Red
    }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" -TimeoutSec 2
        Write-Host ("Frontend (React)  : HTTP " + [int]$r.StatusCode + " - RUNNING") -ForegroundColor Green
    } catch {
        Write-Host "Frontend (React)  : NOT RESPONDING" -ForegroundColor Red
    }
    $files = @(Get-ChildItem -LiteralPath $datasetDir -Filter "*.jsonl" -File)
    $rows = 0
    foreach ($f in $files) {
        $rows += (Get-Content -LiteralPath $f.FullName | Measure-Object -Line).Lines
    }
    Write-Host ""
    Write-Host ("Dataset files found : " + $files.Count)
    Write-Host ("JSONL sample records: " + $rows)
    Write-Host ""
    $db = Join-Path $backendDir "legal_ai.sqlite3"
    if (Test-Path $db) {
        Write-Host "Application database: present"
    } else {
        Write-Host "Application database: not found"
    }
    Write-Host ""
    Write-Host "This monitor checks service availability and dataset files."
    Write-Host "It does not claim documents are indexed or AI answers are verified."
    Write-Host "Press Ctrl+C in this window to stop monitoring." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}

[executed on device: NIDHIN (47c41d4b-ef60-4c09-8668-4cc72e1eff30)]