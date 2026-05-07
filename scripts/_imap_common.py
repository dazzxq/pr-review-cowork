"""IMAP common helpers — shared bởi 4 scripts (search, get_thread, check_drafted,
create_draft).

Hardened sau 4 rounds Codex plan review:
- enable_utf8_if_supported (RFC 6855) cho query có Vietnamese
- quote_mailbox + quote_search_arg cho consistent quoting
- select_mailbox wrapper với fail-fast typ check
- parse_appenduid (RFC 4315 UIDPLUS) — defensive iteration cho mọi response variant
- make_dedup_key + normalize_body_for_hash — race-safe idempotency

NOTE: fetch_email_body.py chưa migrate sang module này — defer sang commit riêng
sau khi 4 scripts mới stable. Code duplication tạm thời chấp nhận để giảm blast
radius migration.
"""
from __future__ import annotations

import hashlib
import imaplib
import os
import re
import ssl
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────────
THREAD_ID_RE = re.compile(r'^[0-9a-fA-F]{1,16}$')
ALL_MAIL_FALLBACKS = ['[Gmail]/All Mail', '[Gmail]/Tất cả thư', 'INBOX']
DRAFTS_FALLBACKS = ['[Gmail]/Drafts', '[Gmail]/Bản nháp', 'Drafts']
CHARSET_FALLBACKS = ['utf-8', 'cp1252', 'iso-8859-1', 'gb18030']
DEDUP_HEADER = 'X-Cowork-Dedup-Key'

ENV_FILE = Path(__file__).resolve().parent.parent / '.env'


# ── Exceptions ──────────────────────────────────────────────────────────────
class ImapTransientError(Exception):
    """IMAP infra/parse/metadata failures.

    Caller map → exit 7 để vào retry+circuit-breaker. Phân biệt với None return
    (= thread thật sự empty / data issue → exit 5).
    """
    pass


# ── Env loading ─────────────────────────────────────────────────────────────
def load_env() -> None:
    """Load <repo_root>/.env vào os.environ (idempotent — không override existing)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


def get_creds() -> tuple[str | None, str | None]:
    """Trả (email, password). Backward-compat: ưu tiên GMAIL_*, fallback SENDER_*."""
    email_addr = os.environ.get('GMAIL_EMAIL') or os.environ.get('SENDER_EMAIL')
    password = os.environ.get('GMAIL_APP_PASSWORD') or os.environ.get('SENDER_APP_PASSWORD')
    return email_addr, password


# ── Connection ──────────────────────────────────────────────────────────────
def imap_login(
    host: str | None = None,
    port: int | None = None,
    email_addr: str | None = None,
    password: str | None = None,
) -> imaplib.IMAP4_SSL:
    """Login IMAP4_SSL + return connection.

    Defaults từ env (IMAP_HOST=imap.gmail.com, IMAP_PORT=993, GMAIL_*).
    Raises imaplib.IMAP4.error (auth) hoặc OSError/ssl.SSLError (network).

    Sets conn._encoding = 'utf-8' để imaplib accept str args với non-ASCII
    (e.g. mailbox name "[Gmail]/Tất cả thư" trong locale tiếng Việt). Default
    Python imaplib dùng ASCII → fail UnicodeEncodeError.
    """
    host = host or os.environ.get('IMAP_HOST', 'imap.gmail.com')
    port = port or int(os.environ.get('IMAP_PORT', '993'))
    if email_addr is None or password is None:
        env_email, env_password = get_creds()
        email_addr = email_addr or env_email
        password = password or env_password
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=30)
    conn.login(email_addr, password)
    # Override default ASCII encoding để handle Vietnamese mailbox names + queries.
    # Gmail support UTF-8 commands sau ENABLE UTF8=ACCEPT, nhưng imaplib không
    # auto-switch encoding. Set thủ công ngay sau login (an toàn cho cả case
    # ENABLE fail vì server vẫn accept UTF-8 raw).
    conn._encoding = 'utf-8'
    return conn


def safe_logout(conn: imaplib.IMAP4_SSL) -> None:
    """Logout, swallow errors (cleanup path không nên fail toàn run)."""
    try:
        conn.logout()
    except Exception:
        pass


# ── UTF-8 / Quoting ─────────────────────────────────────────────────────────
def enable_utf8_if_supported(conn: imaplib.IMAP4_SSL) -> bool:
    """ENABLE UTF8=ACCEPT (RFC 6855) — cần cho query có Vietnamese.

    Gmail support extension này. Nếu server không support, ENABLE return BAD —
    fallback sang RFC 2047 encoded ASCII (caller responsibility).

    Returns True nếu enabled, False nếu fallback.
    """
    try:
        typ, data = conn._simple_command('ENABLE', 'UTF8=ACCEPT')
        if typ == 'OK':
            # Đọc untagged response để clear buffer
            try:
                conn._untagged_response(typ, data, 'ENABLED')
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def quote_mailbox(name: str) -> str:
    """Quote mailbox name cho IMAP commands (handle space, special chars).

    Gmail mailbox names có khoảng trắng (e.g. "[Gmail]/All Mail") cần quote.
    Backslash + double-quote trong tên (rare) cần escape.
    """
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def quote_search_arg(arg: str | bytes) -> str:
    """Quote 1 IMAP search argument (e.g. X-GM-RAW value).

    Cho non-ASCII (Vietnamese), assume UTF-8 ENABLED — server accept raw bytes.
    """
    if isinstance(arg, bytes):
        arg = arg.decode('utf-8', errors='replace')
    escaped = arg.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


# ── Mailbox resolution ──────────────────────────────────────────────────────
def resolve_special_use_mailbox(
    conn: imaplib.IMAP4_SSL,
    flag_bytes: bytes,
    fallbacks: list[str] | None = None,
) -> str | None:
    """Resolve mailbox via LIST SPECIAL-USE flag (locale-independent).

    Args:
        flag_bytes: e.g. b'\\\\All' or b'\\\\Drafts'
        fallbacks: list mailbox names tries nếu SPECIAL-USE không match (optional)

    Returns: mailbox name (str) hoặc None.
    """
    typ, data = conn.list('""', '*')
    if typ == 'OK' and data:
        for line in data:
            if not line:
                continue
            if isinstance(line, tuple):
                line = line[0]
            if not isinstance(line, bytes):
                continue
            if flag_bytes not in line:
                continue
            quoted = re.findall(rb'"([^"]+)"', line)
            if quoted:
                return quoted[-1].decode('utf-8', errors='replace')
            tail = line.rstrip()
            m = re.search(rb'(\S+)$', tail)
            if m:
                return m.group(1).decode('utf-8', errors='replace')
    # SPECIAL-USE không match → caller decide có thử fallbacks không
    return None


def select_mailbox(
    conn: imaplib.IMAP4_SSL,
    mailbox: str,
    readonly: bool = True,
) -> tuple[str, list]:
    """Wrapper conn.select() với quoted name + fail-fast nếu typ != OK.

    Raises ImapTransientError nếu select fail.
    """
    typ, data = conn.select(quote_mailbox(mailbox), readonly=readonly)
    if typ != 'OK':
        raise ImapTransientError(f'SELECT "{mailbox}" returned typ={typ}')
    return typ, data


# ── Dedup key (idempotency cho draft creation) ─────────────────────────────
def normalize_body_for_hash(body_text: str) -> str:
    """Normalize body trước khi hash để dedup stable across whitespace differences.

    - CRLF/CR → LF
    - Strip trailing whitespace mỗi line (preserve internal indentation)
    - Strip leading/trailing blank lines

    KHÔNG normalize internal spacing/case — content thực sự khác phải generate
    key khác.
    """
    s = body_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in s.split('\n')]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def make_dedup_key(thread_id_hex: str, body_text: str) -> str:
    """Tạo dedup key cho draft idempotency.

    Format: <thread_id_hex>:<sha256(normalized_body)[:16]>
    16 hex = 64-bit space → collision negligible cho use case ~720 drafts/ngày.
    """
    normalized = normalize_body_for_hash(body_text)
    body_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]
    return f'{thread_id_hex}:{body_hash}'


# ── APPENDUID parsing (RFC 4315 UIDPLUS) ────────────────────────────────────
def parse_appenduid(append_data: list) -> bytes | None:
    """Parse APPENDUID từ APPEND response — defensive parsing.

    Gmail có thể trả APPENDUID trong tagged hoặc untagged response, bytes hoặc
    tuple format tùy imaplib version. Iterate ALL response parts để robust.

    RFC 4315: response chứa `[APPENDUID <uidvalidity> <uid>]`. Ví dụ:
        b'[APPENDUID 1234567890 42] (Success)'

    Returns: bytes UID hoặc None nếu không parse được.
    """
    if not append_data:
        return None
    parts = []
    for item in append_data:
        if isinstance(item, bytes):
            parts.append(item)
        elif isinstance(item, tuple):
            for sub in item:
                if isinstance(sub, bytes):
                    parts.append(sub)
                elif isinstance(sub, str):
                    parts.append(sub.encode('utf-8', errors='replace'))
        elif isinstance(item, str):
            parts.append(item.encode('utf-8', errors='replace'))
    if not parts:
        return None
    combined = b' '.join(parts)
    m = re.search(rb'APPENDUID\s+\d+\s+(\d+)', combined, re.IGNORECASE)
    return m.group(1) if m else None


# ── CLI helpers ─────────────────────────────────────────────────────────────
def fail(code: int, msg: str) -> None:
    """Print error to stderr + exit with code."""
    import sys
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(code)
