#!/usr/bin/env python3
"""
Tải file từ Bizfly Drive share link bằng HTTP GET trực tiếp.

Bizfly Drive là Nextcloud — endpoint /s/<token>/download trả raw file.
Pattern URL được hỗ trợ:
  - https://<host>/s/<token>
  - https://<host>/index.php/s/<token>
  - https://<host>/apps/onlyoffice/s/<token>
  - https://<host>/apps/<anything>/s/<token>

Không cần browser, không cần Camoufox/Playwright (giữ deps tối thiểu).

Usage:
  python3 fetch_document.py <url> <output_dir>
Output:
  stdout: path file đã tải (1 dòng) → exit 0
  stderr: log
  exit 1: fail
"""
import sys, os, re, urllib.request, urllib.parse, ssl

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"

BIZFLY_RE = re.compile(
    r'^(https?://[^/]+)(?:/index\.php)?(?:/apps/[^/]+)?/s/([A-Za-z0-9_-]+)/?(?:[/?#].*)?$'
)

def log(*args):
    print(*args, file=sys.stderr)

def rewrite_to_download(url):
    m = BIZFLY_RE.match(url.strip())
    if not m:
        return None
    base, token = m.group(1), m.group(2)
    return f"{base}/s/{token}/download"

def filename_from_response(resp, default='document.docx'):
    cd = resp.headers.get('Content-Disposition', '')
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return m.group(1)
    return default

def main(url, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    dl_url = rewrite_to_download(url)
    if not dl_url:
        log(f"ERROR: không nhận diện được Bizfly share URL: {url}")
        sys.exit(1)
    log(f"  download: {dl_url}")
    req = urllib.request.Request(dl_url, headers={'User-Agent': UA})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            ctype = resp.headers.get('Content-Type', '')
            if ctype.startswith('text/html'):
                log(f"ERROR: server trả HTML (có thể link sai/hết hạn): {ctype}")
                sys.exit(1)
            fname = filename_from_response(resp)
            path = os.path.join(output_dir, fname)
            with open(path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            size = os.path.getsize(path)
            log(f"  saved {fname} ({size} bytes)")
            print(path)
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: fetch_document.py <url> <output_dir>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
