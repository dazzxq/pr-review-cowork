#Requires -Version 5.0
<#
.SYNOPSIS
    Setup PR Review Agent — Cowork-Lite (Windows PowerShell)

.DESCRIPTION
    Mirror logic của setup.sh nhưng native PowerShell. Idempotent — chạy lại
    an toàn không hỏng gì.

    Tìm Python 3.10+ → tạo .venv → cài markitdown → copy .env từ template.

.NOTES
    Nếu PowerShell block script: chạy 1 lần
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    rồi chạy lại .\setup.ps1
#>

$ErrorActionPreference = 'Stop'
# Đảm bảo console hiển thị tiếng Việt có dấu đúng (UTF-8)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot

Write-Host "=== PR Review Agent — Cowork-Lite Setup ==="
Write-Host ""

# ── 1. Tìm Python 3.10+ ────────────────────────────────────────────────────
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
# Thứ tự: py launcher (Windows official) → python3.X → python
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
    Write-Host "❌ Không tìm thấy Python 3.10+ (markitdown yêu cầu)." -ForegroundColor Red
    Write-Host ""
    Write-Host "   Tải từ: https://www.python.org/downloads/"
    Write-Host "   Khi cài: tick ""Add Python to PATH"" + ""py launcher"""
    Write-Host ""
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $cur = & python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
        Write-Host "   (Hiện tại có python = $cur — quá cũ.)"
    }
    exit 1
}

$PyArgs = $Python.PreArgs
$PyVer = & $Python.Cmd @($PyArgs + @('-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'))
$PyDisplay = ($Python.Cmd + ' ' + ($PyArgs -join ' ')).Trim()
Write-Host "✓ Python $PyVer ($PyDisplay)" -ForegroundColor Green

# ── 2. Tạo venv ────────────────────────────────────────────────────────────
$VenvPython = Join-Path '.venv' 'Scripts\python.exe'

if (-not (Test-Path '.venv')) {
    Write-Host "→ Tạo venv tại .venv\"
    & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
} elseif (-not (Test-Path $VenvPython)) {
    Write-Host "⚠️  .venv\ không hợp lệ — tạo lại" -ForegroundColor Yellow
    Remove-Item -Recurse -Force '.venv'
    & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
} else {
    $VenvVer = & $VenvPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    & $VenvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ venv đã có (.venv\, Python $VenvVer)" -ForegroundColor Green
    } else {
        Write-Host "⚠️  venv đang dùng Python $VenvVer quá cũ — tạo lại" -ForegroundColor Yellow
        Remove-Item -Recurse -Force '.venv'
        & $Python.Cmd @($PyArgs + @('-m', 'venv', '.venv'))
    }
}

# ── 3. Cài markitdown (skip nếu đã có) ─────────────────────────────────────
& $VenvPython -c "import markitdown" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $MdVer = & $VenvPython -c "from importlib.metadata import version; print(version('markitdown'))" 2>$null
    Write-Host "✓ markitdown đã cài (v$MdVer)" -ForegroundColor Green
} else {
    Write-Host "→ Cài markitdown + deps..."
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -r requirements.txt
    $MdVer = & $VenvPython -c "from importlib.metadata import version; print(version('markitdown'))" 2>$null
    Write-Host "✓ markitdown đã cài (v$MdVer)" -ForegroundColor Green
}

# ── 4. Tạo .env từ template (skip nếu đã có) ──────────────────────────────
if (Test-Path '.env') {
    Write-Host "✓ .env đã có (giữ nguyên config hiện tại)" -ForegroundColor Green
} elseif (Test-Path '.env.example') {
    Copy-Item '.env.example' '.env'
    Write-Host "→ Đã tạo .env từ .env.example. Mặc định SEND_MODE=false (chỉ tạo draft)."
    Write-Host "  Bật send mode: edit .env, set SEND_MODE=true + điền SENDER_EMAIL/SENDER_APP_PASSWORD."
}

# ── 5. In hướng dẫn ────────────────────────────────────────────────────────
$Cwd = (Get-Location).Path
Write-Host ""
Write-Host "✓ Setup xong." -ForegroundColor Green
Write-Host ""
Write-Host "=== Bước tiếp theo trong Cowork ==="
Write-Host "1. Mở Claude Desktop → tab Cowork"
Write-Host "2. Settings → Connectors → Connect Gmail (OAuth, 1 click)"
Write-Host "3. Trust folder: $Cwd"
Write-Host "4. Trong Cowork session, gõ:"
Write-Host "   ""Schedule a task every 10 minutes that runs the skill at $Cwd\SKILL.md"""
Write-Host "5. Click Run now → approve các permission Bash/Gmail → 'Always allow' từng tool"
Write-Host ""
Write-Host "=== Test trước khi bật production ==="
Write-Host "  Trong Cowork conversation gõ:"
Write-Host "    ""test the cowork network reachability""   # Bước 1: check egress"
Write-Host "    ""test the smtp send config""              # Bước 2: check creds"
Write-Host ""
Write-Host "  Hoặc chạy local (chỉ test máy bạn, không phản ánh Cowork sandbox):"
Write-Host "    .venv\Scripts\python.exe scripts\test_cowork_network.py"
Write-Host "    .venv\Scripts\python.exe scripts\test_send.py --dry-run"
Write-Host ""
Write-Host "Audit log: xem trong Cowork conversation, mỗi run là 1 session ở Routines tab."
