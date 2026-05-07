#Requires -Version 5.0
<#
.SYNOPSIS
    Setup PR Review Agent - Cowork-Lite (Windows PowerShell)

.DESCRIPTION
    Mirror logic cua setup.sh nhung native PowerShell. Idempotent - chay lai
    an toan khong hong gi.

    Tim Python 3.10+ -> tao .venv -> cai markitdown -> copy .env tu template.

    File nay co tinh dung ASCII thuan (khong dau, khong unicode dac biet)
    de tranh loi encoding tren PowerShell 5.1 mac dinh cua Windows 10/11.

.NOTES
    Neu PowerShell block script, dan 1 dong:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\setup.ps1
#>

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host "=== PR Review Agent - Cowork-Lite Setup ==="
Write-Host ""

# --- 1. Tim Python 3.10+ ---------------------------------------------------
function Test-PythonVersion {
    param([string]$Cmd, [string[]]$PreArgs = @())
    try {
        $argList = @() + $PreArgs + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)')
        & $Cmd @argList 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

$Python = $null
# Thu tu: py launcher (Windows official) -> python3.X -> python
$Candidates = @(
    @{ Cmd = 'py'; PreArgs = @('-3.13') },
    @{ Cmd = 'py'; PreArgs = @('-3.12') },
    @{ Cmd = 'py'; PreArgs = @('-3.11') },
    @{ Cmd = 'py'; PreArgs = @('-3.10') },
    @{ Cmd = 'python3.13'; PreArgs = @() },
    @{ Cmd = 'python3.12'; PreArgs = @() },
    @{ Cmd = 'python3.11'; PreArgs = @() },
    @{ Cmd = 'python3.10'; PreArgs = @() },
    @{ Cmd = 'python'; PreArgs = @() }
)

foreach ($c in $Candidates) {
    if (Test-PythonVersion -Cmd $c.Cmd -PreArgs $c.PreArgs) {
        $Python = $c
        break
    }
}

if ($null -eq $Python) {
    Write-Host "[ERROR] Khong tim thay Python 3.10+ (markitdown yeu cau)." -ForegroundColor Red
    Write-Host ""
    Write-Host "   Tai tu: https://www.python.org/downloads/"
    Write-Host "   Khi cai: tick 'Add Python to PATH' va 'py launcher'"
    Write-Host ""
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $cur = & python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
        Write-Host "   (Hien tai co python = $cur - qua cu.)"
    }
    exit 1
}

$PyArgs = $Python.PreArgs
$PyVer = & $Python.Cmd @($PyArgs + @('-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'))
$PyDisplay = ($Python.Cmd + ' ' + ($PyArgs -join ' ')).Trim()
Write-Host "[OK] Python $PyVer ($PyDisplay)" -ForegroundColor Green

# --- 2. Tao venv -----------------------------------------------------------
$VenvPython = Join-Path '.venv' 'Scripts\python.exe'

if (-not (Test-Path '.venv')) {
    Write-Host "-> Tao venv tai .venv\"
    & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
} elseif (-not (Test-Path $VenvPython)) {
    Write-Host "[WARN] .venv\ khong hop le - tao lai" -ForegroundColor Yellow
    Remove-Item -Recurse -Force '.venv'
    & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
} else {
    $VenvVer = & $VenvPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    & $VenvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] venv da co (.venv\, Python $VenvVer)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] venv dang dung Python $VenvVer qua cu - tao lai" -ForegroundColor Yellow
        Remove-Item -Recurse -Force '.venv'
        & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
    }
}

# --- 3. Cai markitdown (skip neu da co) ------------------------------------
& $VenvPython -c "import markitdown" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $MdVer = & $VenvPython -c "from importlib.metadata import version; print(version('markitdown'))" 2>$null
    Write-Host "[OK] markitdown da cai (v$MdVer)" -ForegroundColor Green
} else {
    Write-Host "-> Cai markitdown + deps..."
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -r requirements.txt
    $MdVer = & $VenvPython -c "from importlib.metadata import version; print(version('markitdown'))" 2>$null
    Write-Host "[OK] markitdown da cai (v$MdVer)" -ForegroundColor Green
}

# --- 4. Tao .env tu template (skip neu da co) ------------------------------
if (Test-Path '.env') {
    Write-Host "[OK] .env da co (giu nguyen config hien tai)" -ForegroundColor Green
} elseif (Test-Path '.env.example') {
    Copy-Item '.env.example' '.env'
    Write-Host "-> Da tao .env tu .env.example. Mac dinh SEND_MODE=false (chi tao draft)."
    Write-Host "   Bat send mode: edit .env, set SEND_MODE=true + dien SENDER_EMAIL/SENDER_APP_PASSWORD."
}

# --- 5. In huong dan -------------------------------------------------------
$Cwd = (Get-Location).Path
Write-Host ""
Write-Host "[OK] Setup xong." -ForegroundColor Green
Write-Host ""
Write-Host "=== Buoc tiep theo trong Cowork ==="
Write-Host "1. Mo Claude Desktop -> tab Cowork"
Write-Host "2. Settings -> Connectors -> Connect Gmail (OAuth, 1 click)"
Write-Host "3. Trust folder: $Cwd"
Write-Host "4. Trong Cowork session, go:"
Write-Host "   ""Schedule a task every 10 minutes that runs the skill at $Cwd\SKILL.md"""
Write-Host "5. Click Run now -> approve cac permission Bash/Gmail -> 'Always allow' tung tool"
Write-Host ""
Write-Host "=== Test truoc khi bat production ==="
Write-Host "  Trong Cowork conversation go:"
Write-Host "    ""test the cowork network reachability""   # Buoc 1: check egress"
Write-Host "    ""test the smtp send config""              # Buoc 2: check creds"
Write-Host ""
Write-Host "  Hoac chay local (chi test may ban, khong phan anh Cowork sandbox):"
Write-Host "    .venv\Scripts\python.exe scripts\test_cowork_network.py"
Write-Host "    .venv\Scripts\python.exe scripts\test_send.py --dry-run"
Write-Host ""
Write-Host "Audit log: xem trong Cowork conversation, moi run la 1 session o Routines tab."
