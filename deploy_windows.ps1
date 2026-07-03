# ==============================================================================
#  GEM Tender Intelligence System — Windows Native Deployment Assistant
#  Run this script as Administrator to configure Python environment, 
#  download NSSM, register services, and configure Windows Firewall.
# ==============================================================================

# Ensure Running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Please run this PowerShell script as Administrator!"
    Exit
}

$ProjectRoot = "F:\teneder evolution\tender"
Set-Location $ProjectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting GEM Tender Native Windows Deployment Helper     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# ── 1. Check Pre-requisites ───────────────────────────────────────────────────
Write-Host "`n[1/5] Checking pre-requisites..." -ForegroundColor Yellow

# Check Python
try {
    $pythonVer = python --version
    Write-Host "✔ Python found: $pythonVer" -ForegroundColor Green
} catch {
    Write-Warning "✖ Python not found on PATH. Please install Python 3.12 and check 'Add to PATH'."
}

# Check Tesseract OCR
$tesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (Test-Path $tesseractPath) {
    Write-Host "✔ Tesseract OCR found at $tesseractPath" -ForegroundColor Green
} else {
    Write-Warning "✖ Tesseract OCR not found. Please install it to default path: $tesseractPath"
}

# Check Poppler
$popplerOnPath = Get-Command pdftoppm -ErrorAction SilentlyContinue
if ($popplerOnPath) {
    Write-Host "✔ Poppler found on PATH" -ForegroundColor Green
} else {
    Write-Warning "✖ Poppler (pdftoppm) not found on PATH. Please add it for PDF parsing to work."
}

# ── 2. Initialize Python Virtual Environment ──────────────────────────────────
Write-Host "`n[2/5] Setting up Python Virtual Environment..." -ForegroundColor Yellow
if (-not (Test-Path ".\.venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
Write-Host "Installing/Upgrading Python dependencies..."
& ".\.venv\Scripts\pip.exe" install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r backend/requirements.txt
Write-Host "✔ Dependencies installed." -ForegroundColor Green

# ── 3. Download and Extract NSSM ──────────────────────────────────────────────
Write-Host "`n[3/5] Setting up NSSM (Non-Sucking Service Manager)..." -ForegroundColor Yellow
$nssmDest = "C:\Windows\System32\nssm.exe"
if (-not (Test-Path $nssmDest)) {
    Write-Host "Downloading NSSM..."
    $zipPath = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
    
    Write-Host "Extracting nssm.exe to System32..."
    Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\nssm-extracted" -Force
    Copy-Item -Path "$env:TEMP\nssm-extracted\nssm-2.24\win64\nssm.exe" -Destination $nssmDest -Force
    
    # Cleanup
    Remove-Item $zipPath -Force
    Remove-Item "$env:TEMP\nssm-extracted" -Recururse -Force
    Write-Host "✔ NSSM installed to $nssmDest" -ForegroundColor Green
} else {
    Write-Host "✔ NSSM already present in System32." -ForegroundColor Green
}

# ── 4. Setup Firewall Rules ──────────────────────────────────────────────────
Write-Host "`n[4/5] Setting up Windows Firewall rules..." -ForegroundColor Yellow
try {
    # Port 80 (HTTP)
    if (-not (Get-NetFirewallRule -Name "GEM_Tender_HTTP" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name "GEM_Tender_HTTP" -DisplayName "GEM Tender HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow | Out-Null
    }
    # Port 443 (HTTPS)
    if (-not (Get-NetFirewallRule -Name "GEM_Tender_HTTPS" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name "GEM_Tender_HTTPS" -DisplayName "GEM Tender HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow | Out-Null
    }
    # Block DBs and LLM from outside
    if (-not (Get-NetFirewallRule -Name "Block_MongoDB_External" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name "Block_MongoDB_External" -DisplayName "Block MongoDB External" -Direction Inbound -LocalPort 27017 -Protocol TCP -Action Block | Out-Null
    }
    if (-not (Get-NetFirewallRule -Name "Block_Redis_External" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name "Block_Redis_External" -DisplayName "Block Redis External" -Direction Inbound -LocalPort 6379 -Protocol TCP -Action Block | Out-Null
    }
    if (-not (Get-NetFirewallRule -Name "Block_Ollama_External" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name "Block_Ollama_External" -DisplayName "Block Ollama External" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Block | Out-Null
    }
    Write-Host "✔ Firewall rules successfully configured." -ForegroundColor Green
} catch {
    Write-Warning "✖ Failed to configure some firewall rules. Please review manually."
}

# ── 5. Final Instructions ─────────────────────────────────────────────────────
Write-Host "`n[5/5] Setup Helper Complete!" -ForegroundColor Yellow
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host " 1. Set up your real config values in .env"
Write-Host " 2. Register Windows services using:"
Write-Host "    nssm install GEM_Backend"
Write-Host "    nssm install GEM_Nginx"
Write-Host " 3. Verify service startup in Services.msc"
Write-Host "==========================================================" -ForegroundColor Cyan
