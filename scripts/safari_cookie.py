#!/usr/bin/env python3
"""
Safari Cookie Extractor — 解析 Cookies.binarycookies，提取指定域名的 cookie。
用法:
  python3 safari_cookie.py <domain>           # 列出 cookie
  python3 safari_cookie.py <domain> --curl     # 输出 curl header
  python3 safari_cookie.py <domain> --test URL # 测试 API
"""
import struct, sys, os, json
from datetime import datetime
from urllib.parse import urlsplit

COOKIE_PATHS = [
    os.path.expanduser("~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"),
    os.path.expanduser("~/Library/Cookies/Cookies.binarycookies"),
]
MAC_EPOCH_OFFSET = (datetime(2001, 1, 1) - datetime(1970, 1, 1)).total_seconds()


def find_cookie_file():
    for p in COOKIE_PATHS:
        if os.path.isfile(p):
            return p
    return None


def _read_cstring(data, offset):
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('utf-8', errors='replace')


def _normalize_domain(raw):
    """BinaryCookies implementations may store a URL or a bare domain."""
    raw = raw.strip()
    parsed = urlsplit(raw if '://' in raw else f'//{raw}')
    return (parsed.hostname or raw).lstrip('.').lower()


def parse_binarycookies(filepath=None):
    if filepath is None:
        filepath = find_cookie_file()
    if not filepath:
        return []
    with open(filepath, 'rb') as f:
        data = f.read()
    if data[:4] != b'cook':
        return []
    num_pages = struct.unpack('>I', data[4:8])[0]
    page_sizes = [struct.unpack('>I', data[8 + i * 4:12 + i * 4])[0] for i in range(num_pages)]
    offset = 8 + num_pages * 4
    all_cookies = []
    for psize in page_sizes:
        page = data[offset:offset + psize]
        offset += psize
        if len(page) < 8:
            continue
        num_cookies = struct.unpack('<I', page[4:8])[0]
        cookie_offsets = [struct.unpack('<I', page[8 + ci * 4:12 + ci * 4])[0] for ci in range(num_cookies)]
        for co in cookie_offsets:
            try:
                flags = struct.unpack('<I', page[co + 4:co + 8])[0]
                url_off = struct.unpack('<I', page[co + 16:co + 20])[0]
                name_off = struct.unpack('<I', page[co + 20:co + 24])[0]
                path_off = struct.unpack('<I', page[co + 24:co + 28])[0]
                value_off = struct.unpack('<I', page[co + 28:co + 32])[0]
                expiry_raw = struct.unpack('<d', page[co + 40:co + 48])[0]
                domain = _normalize_domain(_read_cstring(page, co + url_off))
                name = _read_cstring(page, co + name_off)
                path = _read_cstring(page, co + path_off)
                value = _read_cstring(page, co + value_off)
                expired = False
                expiry_ts = None
                if 0 < expiry_raw < 1e10:
                    expiry_ts = int(expiry_raw + MAC_EPOCH_OFFSET)
                    expiry_dt = datetime.fromtimestamp(expiry_ts)
                    expired = expiry_dt < datetime.now()
                    expiry_str = expiry_dt.strftime('%Y-%m-%d %H:%M')
                else:
                    expiry_str = "session"
                all_cookies.append({
                    'domain': domain, 'name': name, 'path': path or '/', 'value': value,
                    'expiry_ts': expiry_ts,
                    'expiry': expiry_str, 'expired': expired,
                    'secure': bool(flags & 0x01), 'httponly': bool(flags & 0x04),
                    'raw_flags': flags,
                })
            except Exception:
                continue
    return all_cookies


def _match_domain(cookie_domain, target):
    cd = cookie_domain.lstrip('.')
    td = target.lstrip('.')
    return cd == td or td.endswith('.' + cd)


def get_cookies_for_domain(target_domain):
    all_cookies = parse_binarycookies()
    return [c for c in all_cookies
            if _match_domain(c['domain'], target_domain) and not c['expired']]


def format_cookie_header(cookies):
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def list_all_domains():
    all_cookies = parse_binarycookies()
    domains = {}
    for c in all_cookies:
        if not c['expired']:
            domains.setdefault(c['domain'], 0)
            domains[c['domain']] += 1
    return domains


# --- CLI ---
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == '--domains':
        for d, n in sorted(list_all_domains().items()):
            print(f"  {d:40s} ({n})")
        sys.exit(0)

    target = sys.argv[1]
    cookies = get_cookies_for_domain(target)

    if not cookies:
        print(f"No active cookies for {target}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cookies)} active cookies for {target}:\n")
    for c in cookies:
        flags = []
        if c['secure']: flags.append("Secure")
        if c['httponly']: flags.append("HttpOnly")
        print(f"  {c['name']:30s} = {c['value'][:60]:60s}  exp: {c['expiry']}  [{', '.join(flags) or 'plain'}]")

    header = format_cookie_header(cookies)

    if '--curl' in sys.argv:
        print(f"\nCookie: {header}")

    if '--json' in sys.argv:
        print(json.dumps(cookies, indent=2, ensure_ascii=False))

    if '--test' in sys.argv:
        idx = sys.argv.index('--test')
        test_url = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else f"https://{target}/"
        import subprocess
        result = subprocess.run(
            ['curl', '-s', '-H', f'Cookie: {header}', test_url],
            capture_output=True, text=True, timeout=10
        )
        print(f"\nGET {test_url}\n{result.stdout[:500]}")
