---
name: safari-cookie-auth
description: 从 Safari 本地 cookie 文件提取登录态，注入 safaridriver 或直接 curl 调用 API。当用户需要"用已登录的网站 / 操作已登录的账号 / 自动化登录态网站 / cookie 提取 / safari 登录"时使用。无需 Chrome，无需手动复制 cookie。
license: MIT
metadata:
  author: Julian
  tested: 2026-09-11
  tested_on: macOS 12.7.6, Safari 17.6
---

# safari-cookie-auth

从 Safari 本地 `Cookies.binarycookies` 提取登录态 cookie，用于：
1. **curl 直调 API** — 最轻最快
2. **safaridriver 注入** — 需要浏览器交互时

## 核心原理

Safari 的默认 profile cookie 通常位于：

```
~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies
```

- 新版优先使用容器路径；旧版回退到 `~/Library/Cookies/Cookies.binarycookies`
- 所有目标域名 cookie 一次读取，换账号后再次读取即可得到新值
- 不需要第三方 Python 包；但 macOS 的 Full Disk Access/TCC 仍可能阻止读取

safaridriver **不继承**日常 Safari 登录态（独立沙盒实例），但可以通过注入 cookie 解决。

## 前置（一次性）

新系统优先运行：

```bash
safaridriver --enable
```

macOS Sierra 及更早系统需要在 Safari 的 Develop 菜单中开启 Allow Remote Automation；Safari 12+ 使用 W3C WebDriver，Safari 11.1 及更早版本由模板自动尝试 legacy JSON Wire session。

仅 safaridriver 注入需要；纯 curl 调用不需要。

## 用法

### 1. 提取 cookie 并 curl 调 API

```bash
python3 ~/.claude/skills/safari-cookie-auth/scripts/safari_cookie.py <domain>
# 例: python3 ~/.claude/skills/safari-cookie-auth/scripts/safari_cookie.py example.com

# 输出 curl 命令
python3 ~/.claude/skills/safari-cookie-auth/scripts/safari_cookie.py example.com --curl

# 直接测试 API
python3 ~/.claude/skills/safari-cookie-auth/scripts/safari_cookie.py example.com --test https://example.com/api/user/info
```

### 2. Python 中调用

```python
import sys; sys.path.insert(0, os.path.expanduser("~/.claude/skills/safari-cookie-auth/scripts"))
from safari_cookie import get_cookies_for_domain, format_cookie_header

cookies = get_cookies_for_domain("example.com")
header = format_cookie_header(cookies)
# 用于 requests: requests.get(url, headers={"Cookie": header})
# 用于 curl: curl -H "Cookie: {header}" {url}
```

### 3. safaridriver 注入（需要浏览器交互时）

关键步骤（**顺序不能错**）：

```
1. 启动 safaridriver
2. 创建 session
3. 导航到目标网站（让服务器设它自己的空 session cookie）
4. 按 cookie domain 分组并导航到对应 host
5. 删除服务器设的同名 cookie: DELETE /session/{sid}/cookie/{name}
6. 注入真实 cookie: POST /session/{sid}/cookie（保留 domain、path、secure、httpOnly、expiry）
7. 回到目标 host 并刷新页面: POST /session/{sid}/refresh
8. 验证认证状态
```

**双 cookie 冲突**（最常见的坑）：服务器会给未登录访客设一个空 session cookie（domain 不带点），和你注入的 cookie（可能带点）形成两个同名 cookie。浏览器发送时精确域名优先，导致空 session 覆盖真实认证。**必须先删再注。**

完整注入代码模板见 `scripts/inject_template.py`。
完整的安装、操作链路、旧 macOS 兼容矩阵和故障定位见 `README.md`。

## 适用边界

| 维度 | 边界 |
|------|------|
| 操作系统 | macOS only（依赖 `Cookies.binarycookies` 和 `safaridriver`） |
| 浏览器 | Safari only |
| cookie 来源 | 仅当前 macOS 用户，不跨用户、不跨机器 |
| 认证方式 | ✅ cookie-based auth 通用；❌ 纯 Bearer JWT（存 localStorage）不适用 |
| 网站类型 | ✅ 普通 SPA/传统站均可；⚠️ Cloudflare/reCAPTCHA/高级反 bot 会拦截 safaridriver |
| HTTPS | 按源 cookie 保留 `secure`；目标站若只支持 HTTPS，使用 HTTPS 导航 |
| 多子域名 | 提取器按父域匹配，模板按实际 cookie domain 分组注入 |
| Safari Profiles | Safari 17+ 的非默认 profile 可能使用独立 cookie 文件，当前默认扫描器不自动枚举 profile |
| cookie 生命周期 | session cookie 关浏览器即失效；持久 cookie 看网站设置 |
| cookie 过期后 | 需用户在 Safari 重新登录一次 |
| AppleScript 控制 Safari | ❌ 需额外权限且不稳定，不推荐 |

## 安全边界

- **仅限本机当前用户**的 Safari cookie
- **仅限用户已登录**的账号
- 默认 CLI 会显示 cookie 值前缀；`--curl`/`--json`/`--test` 会按用途输出或发送 cookie，适合自用调试
- 不用于未授权的账号或系统
