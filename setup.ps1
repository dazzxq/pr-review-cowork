#Requires -Version 5.0
<#
.SYNOPSIS
    Setup PR Review Agent - Cowork-Lite (Windows PowerShell)

.DESCRIPTION
    Idempotent: chay lai an toan, skip step da xong.
    Pure ASCII, khong dung 'python -c' voi inner quotes (PS 5.1 quote bug).
    Detect Python qua --version, kiem markitdown qua 'pip list --format=freeze'.

.NOTES
    Neu PowerShell block script, dan 1 dong:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\setup.ps1
#>

# KHONG dung $ErrorActionPreference='Stop' -- PS 5.1 + native stderr = false positive halt.
# Check $LASTEXITCODE thu cong tai cac diem critical.
Set-Location -Path $PSScriptRoot

Write-Host "=== PR Review Agent - Cowork-Lite Setup ==="
Write-Host ""

# --- Helper: tim Python 3.10+ qua --version (khong dung -c) ----------------
function Find-Python {
    # Moi entry: array @(cmd, preargs...). py launcher (Windows official) > pythonX.Y > python.
    $tries = @(
        @('py', '-3.13'),
        @('py', '-3.12'),
        @('py', '-3.11'),
        @('py', '-3.10'),
        @('python3.13'),
        @('python3.12'),
        @('python3.11'),
        @('python3.10'),
        @('python')
    )
    foreach ($t in $tries) {
        $cmd = $t[0]
        $preargs = if ($t.Count -gt 1) { $t[1..($t.Count - 1)] } else { @() }
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
        try {
            $out = & $cmd @($preargs + '--version') 2>&1 | Out-String
            if ($out -match 'Python\s+(\d+)\.(\d+)\.(\d+)') {
                $maj = [int]$Matches[1]
                $min = [int]$Matches[2]
                $patch = [int]$Matches[3]
                if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 10)) {
                    return @{
                        Cmd     = $cmd
                        PreArgs = $preargs
                        Version = "$maj.$min.$patch"
                    }
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

# --- 1. Tim Python 3.10+ ---------------------------------------------------
$Python = Find-Python
if ($null -eq $Python) {
    Write-Host "[ERROR] Khong tim thay Python 3.10+ (markitdown yeu cau)." -ForegroundColor Red
    Write-Host ""
    Write-Host "   Tai tu: https://www.python.org/downloads/"
    Write-Host "   Khi cai: tick 'Add Python to PATH' va 'py launcher'"
    exit 1
}
$PyDisplay = ($Python.Cmd + ' ' + ($Python.PreArgs -join ' ')).Trim()
Write-Host "[OK] Python $($Python.Version) ($PyDisplay)" -ForegroundColor Green

# --- 2. Tao venv (idempotent) ---------------------------------------------
$VenvPython = '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    if (Test-Path '.venv') {
        Write-Host "[WARN] .venv\ khong hop le - tao lai" -ForegroundColor Yellow
        Remove-Item -Recurse -Force '.venv'
    } else {
        Write-Host "-> Tao venv tai .venv\"
    }
    & $Python.Cmd @($Python.PreArgs + @('-m', 'venv', '.venv'))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        Write-Host "[ERROR] Tao venv that bai (exit code: $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

# Verify venv version (qua --version, khong -c)
$venvOut = & $VenvPython --version 2>&1 | Out-String
if ($venvOut -match 'Python\s+(\d+)\.(\d+)') {
    $vMaj = [int]$Matches[1]
    $vMin = [int]$Matches[2]
    if ($vMaj -lt 3 -or ($vMaj -eq 3 -and $vMin -lt 10)) {
        Write-Host "[WARN] venv dang dung Python $vMaj.$vMin qua cu - tao lai" -ForegroundColor Yellow
        Remove-Item -Recurse -Force '.venv'
        & $Python.Cmd @($Python.PreArgs + @('-m', 'venv', '.venv'))
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Re-tao venv that bai" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "[OK] venv san sang (.venv\, Python $vMaj.$vMin)" -ForegroundColor Green
} else {
    Write-Host "[WARN] Khong parse duoc venv version: $venvOut" -ForegroundColor Yellow
}

# --- 3. Cai markitdown (kiem qua pip list --format=freeze, khong dung -c) -
$pipList = & $VenvPython -m pip list --format=freeze 2>&1 | Out-String
if ($pipList -match 'markitdown==(\S+)') {
    Write-Host "[OK] markitdown da cai (v$($Matches[1]))" -ForegroundColor Green
} else {
    Write-Host "-> Cai markitdown + deps (co the mat 1-2 phut)..."
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip install that bai (exit code: $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "   Thu chay thu cong de xem loi:" -ForegroundColor Yellow
        Write-Host "   $VenvPython -m pip install -r requirements.txt"
        exit 1
    }
    $pipList2 = & $VenvPython -m pip list --format=freeze 2>&1 | Out-String
    if ($pipList2 -match 'markitdown==(\S+)') {
        Write-Host "[OK] markitdown da cai (v$($Matches[1]))" -ForegroundColor Green
    } else {
        Write-Host "[WARN] markitdown khong xuat hien sau pip install -- chay '$VenvPython -m pip list' de check" -ForegroundColor Yellow
    }
}

# --- 4. Tao .env tu template ----------------------------------------------
if (Test-Path '.env') {
    Write-Host "[OK] .env da co (giu nguyen config hien tai)" -ForegroundColor Green
} elseif (Test-Path '.env.example') {
    Copy-Item '.env.example' '.env'
    Write-Host "-> Da tao .env tu .env.example. Mac dinh SEND_MODE=false (chi tao draft)."
    Write-Host "   Bat send mode: edit .env, set SEND_MODE=true + dien SENDER_EMAIL/SENDER_APP_PASSWORD."
}

# --- 5. In huong dan ------------------------------------------------------
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
Write-Host "    ""test the cowork network reachability""   # Check egress"
Write-Host "    ""test the smtp send config""              # Check creds"
Write-Host ""
Write-Host "  Hoac chay local:"
Write-Host "    .venv\Scripts\python.exe scripts\test_cowork_network.py"
Write-Host "    .venv\Scripts\python.exe scripts\test_send.py --dry-run"
Write-Host ""
Write-Host "Audit log: xem trong Cowork conversation, moi run la 1 session o Routines tab."
