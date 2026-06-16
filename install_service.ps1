# Install Trading Platform as a Windows service via NSSM.
# Run as Administrator in PowerShell:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser  (once)
#   .\install_service.ps1

$ServiceName  = "TradingAPI"
$ProjectDir   = "D:\PROJECTS\WEBSITES\Trading"
$PythonExe    = "$ProjectDir\.venv\Scripts\python.exe"
$Script       = "$ProjectDir\run_api_prod.py"
$LogDir       = "$ProjectDir\logs\service"

# --- 1. Install NSSM if missing ---
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "Installing NSSM via winget..."
    winget install NSSM.NSSM --silent --accept-package-agreements --accept-source-agreements
    # Refresh PATH in current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "NSSM install failed. Download manually from https://nssm.cc/download and add to PATH."
    exit 1
}

# --- 2. Remove existing service if any ---
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing old service..."
    nssm stop  $ServiceName
    nssm remove $ServiceName confirm
    Start-Sleep -Seconds 2
}

# --- 3. Create log dir ---
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- 4. Install service ---
Write-Host "Installing service '$ServiceName'..."
nssm install $ServiceName $PythonExe $Script
nssm set $ServiceName AppDirectory  $ProjectDir
nssm set $ServiceName DisplayName   "Options Backtest Trading API"
nssm set $ServiceName Description   "FastAPI + React (port 8000). Auto-starts at login."
nssm set $ServiceName Start         SERVICE_AUTO_START
nssm set $ServiceName AppStdout     "$LogDir\stdout.log"
nssm set $ServiceName AppStderr     "$LogDir\stderr.log"
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 5000000

# --- 5. Start service ---
Write-Host "Starting service..."
nssm start $ServiceName

Start-Sleep -Seconds 3
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "Service RUNNING. App at http://localhost:8000"
} else {
    Write-Warning "Service not running. Check logs at $LogDir"
    Write-Host "To debug: nssm edit $ServiceName"
}

Write-Host ""
Write-Host "Useful commands:"
Write-Host "  nssm stop   $ServiceName"
Write-Host "  nssm start  $ServiceName"
Write-Host "  nssm restart $ServiceName"
Write-Host "  nssm edit   $ServiceName   (GUI config)"
Write-Host "  nssm remove $ServiceName confirm"
