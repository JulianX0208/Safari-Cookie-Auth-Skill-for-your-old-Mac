#!/usr/bin/env python3
"""
safaridriver cookie 注入模板。
用法: 复制本文件，修改 TARGET_DOMAIN 和后续导航逻辑。

关键: 先导航让服务器设空 cookie → 删除空 cookie → 注入真实 cookie → 刷新。
"""
import json, subprocess, time, urllib.request, sys, os
from urllib.parse import quote

# --- 配置 ---
TARGET_DOMAIN = "example.com"  # ← 改成你要操作的域名
PORT = 4448
DRIVER_PROTOCOL = "w3c"

# --- 导入 cookie 提取器 ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safari_cookie import get_cookies_for_domain

# --- WebDriver 工具函数 ---
def cmd(method, path, body=None):
    url = f"http://localhost:{PORT}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def require_cmd(method, path, body=None):
    result = cmd(method, path, body)
    if "error" in result:
        raise RuntimeError(f"{method} {path}: {result['error']}")
    if result.get("status") not in (None, 0):
        raise RuntimeError(f"{method} {path}: {result}")
    value = result.get("value")
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"{method} {path}: {value}")
    return result


def wait_until_ready(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if "error" not in cmd("GET", "/status"):
            return
        time.sleep(0.1)
    raise RuntimeError("safaridriver did not become ready")

def js(session, script):
    endpoint = "execute/sync" if DRIVER_PROTOCOL == "w3c" else "execute"
    return require_cmd("POST", f"/session/{session}/{endpoint}",
                       {"script": script, "args": []}).get("value")

def screenshot(session, filepath):
    import base64
    ss = cmd("GET", f"/session/{session}/screenshot")
    if ss.get("value"):
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(ss["value"]))

# --- 注入流程 ---
def create_authenticated_session():
    """启动 safaridriver 并注入 Safari cookie，返回 (session_id, process)。"""
    global DRIVER_PROTOCOL
    cookies = get_cookies_for_domain(TARGET_DOMAIN)
    if not cookies:
        print(f"❌ No cookies for {TARGET_DOMAIN}. Login in Safari first.")
        sys.exit(1)

    # 启动 safaridriver
    proc = subprocess.Popen(
        ["safaridriver", "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_until_ready()
    except Exception:
        proc.terminate()
        raise

    # 创建 session
    r = cmd("POST", "/session", {"capabilities": {"alwaysMatch": {"browserName": "safari"}}})
    sid = r.get("value", {}).get("sessionId") if isinstance(r.get("value"), dict) else None
    if sid:
        DRIVER_PROTOCOL = "w3c"
    else:
        # Safari 11.1 and earlier expose the legacy JSON Wire protocol.
        r = require_cmd("POST", "/session", {"desiredCapabilities": {"browserName": "safari"}})
        sid = r.get("sessionId") or r.get("value", {}).get("sessionId")
        DRIVER_PROTOCOL = "legacy"
    if not sid:
        print(f"❌ Failed to create session: {r}")
        proc.terminate()
        sys.exit(1)

    # Step 1: 导航到目标站（让服务器设空 session cookie）
    try:
        # Step 1-3: visit each cookie host, remove same-name server cookies, then inject.
        by_domain = {}
        for c in cookies:
            by_domain.setdefault(c['domain'], []).append(c)
        for domain, domain_cookies in by_domain.items():
            require_cmd("POST", f"/session/{sid}/url", {"url": f"https://{domain}"})
            time.sleep(0.2)
            for c in domain_cookies:
                require_cmd("DELETE", f"/session/{sid}/cookie/{quote(c['name'], safe='')}")
            for c in domain_cookies:
                cookie_body = {
                    "name": c['name'],
                    "value": c['value'],
                    "path": c.get('path') or '/',
                    "secure": bool(c.get('secure')),
                    "httpOnly": bool(c.get('httponly')),
                }
                if not c['name'].startswith('__Host-'):
                    cookie_body['domain'] = c['domain']
                if c.get('expiry_ts'):
                    cookie_body['expiry'] = c['expiry_ts']
                require_cmd("POST", f"/session/{sid}/cookie", {"cookie": cookie_body})

        # Step 4: return to the requested host and refresh with the imported jar.
        require_cmd("POST", f"/session/{sid}/url", {"url": f"https://{TARGET_DOMAIN}"})
        require_cmd("POST", f"/session/{sid}/refresh", {})
        time.sleep(3)
    except Exception:
        cmd("DELETE", f"/session/{sid}")
        proc.terminate()
        raise

    return sid, proc


# --- 使用示例 ---
if __name__ == '__main__':
    print(f"Creating authenticated session for {TARGET_DOMAIN}...")
    sid, proc = create_authenticated_session()
    print(f"✅ Session: {sid}")
    print(f"   Port: {PORT}")
    print(f"   PID: {proc.pid}")

    # 在这里添加你的导航和操作逻辑
    # 例: 验证登录状态
    api_result = js(sid, f"""
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'https://{TARGET_DOMAIN}/api/user/info', false);
    xhr.withCredentials = true;
    xhr.send();
    return xhr.responseText.substring(0, 200);
    """)
    print(f"\nAPI test: {api_result}")

    print(f"\nSession alive. Close with:")
    print(f"  curl -s -X DELETE http://localhost:{PORT}/session/{sid}")
