# Safari Cookie Auth Skill for old Mac

在不使用 Chromium、Chrome DevTools、Playwright 或 Selenium 浏览器封装的前提下，把当前 macOS 用户 Safari 的登录 cookie 复制到一个 `safaridriver` 会话中。

这是“读取 Safari cookie + 新建 Safari WebDriver 会话 + 注入 cookie”，不是让 `safaridriver` 直接接管用户正在使用的 Safari 窗口。

<img width="1672" height="941" alt="原理" src="https://github.com/user-attachments/assets/5af44198-ff4a-47ab-8fb1-9e2b505d8fc4" />

## 适用目标

- macOS 上只有 Safari/safaridriver 可用的旧机器
- 已经在普通 Safari 中登录的网站
- 需要使用 Safari 的 WebKit 行为继续浏览或执行页面操作
- 不想启动 Chromium 或维护 Chrome profile

不适合依赖 localStorage、IndexedDB、WebAuthn/passkey、设备指纹或额外运行时 token 的登录流程。

## 文件

```text
safari-cookie-auth/
├── SKILL.md
├── README.md
└── scripts/
    ├── safari_cookie.py       # 读取并解析 BinaryCookies
    └── inject_template.py     # 启动 safaridriver 并注入
```

脚本只使用 Python 标准库。

## 一次性准备

### 1. 确认 Safari 与 safaridriver

```bash
safaridriver --version
safaridriver --help
python3 --version
```

### 2. 开启 WebDriver

Safari 12 及以后优先使用：

```bash
safaridriver --enable
```

如果系统显示授权提示，完成一次授权即可。较老的 macOS/Safari 需要在 Safari 的 Develop 菜单中开启 **Allow Remote Automation**。

### 3. 允许读取 Safari 数据

新版 macOS 可能要求给实际运行脚本的 Terminal、Claude、Codex 或其他宿主程序授予 Full Disk Access。文件存在但读取时报 `PermissionError` 时，先处理这个权限，不要修改 cookie 文件权限。

## Cookie 文件位置

默认扫描顺序：

```text
~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies
~/Library/Cookies/Cookies.binarycookies
```

前者是沙盒化 Safari 的常见位置，后者主要用于旧版系统和升级后的旧布局。Safari 17+ 的非默认 profile 具有独立 cookie 数据；当前模板面向默认 profile，使用其他 profile 时需把其 BinaryCookies 文件作为解析输入接入。

## 环节一：读取与筛选

```bash
python3 scripts/safari_cookie.py example.com
```

脚本执行以下操作：

1. 依次检查两个 Safari cookie 文件路径。
2. 读取文件头，确认 magic 为 `cook`。
3. 读取大端序页数和页大小。
4. 遍历每页的 cookie offset。
5. 按 BinaryCookies 的小端序字段读取 flags、URL/domain、name、path、value、expiry。
6. 将 Mac epoch（2001-01-01）转换为 Unix 时间。
7. 将 URL 形式或裸 domain 统一成裸小写 domain。
8. 丢弃已过期 cookie。
9. 按父域匹配目标，例如 `api.example.com` 会匹配 `example.com` 的 cookie。

默认输出 cookie 名称、值前缀、过期时间和 flags。自用调试时可以输出完整 JSON：

```bash
python3 scripts/safari_cookie.py example.com --json
```

只查看当前文件中有哪些 domain：

```bash
python3 scripts/safari_cookie.py --domains
```

## 环节二：直接调用 API

```bash
python3 scripts/safari_cookie.py example.com --curl
python3 scripts/safari_cookie.py example.com --test https://example.com/api/user/info
```

`--curl` 输出由当前有效 cookie 组成的 `Cookie:` header；`--test` 使用系统 `curl` 发起一次 GET。这个路径没有浏览器页面、JavaScript、localStorage 或 WebKit 行为，只适合服务端确实使用 cookie 完成认证的 API。

Python 调用：

```python
import sys
sys.path.insert(0, "scripts")
from safari_cookie import get_cookies_for_domain, format_cookie_header

cookies = get_cookies_for_domain("example.com")
header = format_cookie_header(cookies)
```

## 环节三：启动独立 SafariDriver

复制模板并修改：

```python
TARGET_DOMAIN = "example.com"
PORT = 4448
```

运行：

```bash
python3 scripts/inject_template.py
```

模板的完整执行顺序：

1. 从 Safari BinaryCookies 读取目标域名下所有有效 cookie。
2. 启动 `safaridriver --port 4448`。
3. 轮询 `GET /status`，等待 driver 真正就绪。
4. 先尝试 W3C `POST /session`。
5. 如果失败，再尝试旧版 JSON Wire 的 `desiredCapabilities`。
6. 按实际 cookie domain 分组。
7. 导航到该 domain 的 HTTPS 根页面，让服务器建立它自己的访客 cookie。
8. 对每个待注入 cookie，调用 `DELETE /session/{sid}/cookie/{name}`，清掉同名访客 cookie。
9. 调用 `POST /session/{sid}/cookie` 注入真实值。
10. 保留原 cookie 的 `path`、`secure`、`httpOnly` 和有效期；`__Host-` cookie 不附带 domain。
11. 对每个子域重复上述过程，避免 WebDriver 的当前文档 domain 校验失败。
12. 回到 `TARGET_DOMAIN`，刷新页面。
13. 使用同一个 session 执行页面 JavaScript，模板默认请求 `/api/user/info` 作为认证检查示例。

成功后 session 不会自动关闭。终端会显示关闭命令：

```bash
curl -s -X DELETE http://localhost:4448/session/SESSION_ID
```

## 旧 macOS 兼容矩阵

| Safari/系统情况 | 结果 |
|---|---|
| Safari 12+ | 使用 W3C WebDriver，主路径 |
| Safari 11.1 及更早 | 尝试 legacy JSON Wire session；页面能力依赖旧 driver |
| macOS Sierra 及更早 | 通常需要 GUI 开启 Allow Remote Automation |
| 没有 Full Disk Access 的新版 macOS | 可能能看到文件，但不能读取内容 |
| Safari 17+ 非默认 profile | 需要手动指定对应 profile 的 cookie 文件 |

cookie 注入只能解决“身份凭据不在新会话里”的问题，不能让旧 Safari 获得新浏览器才有的 JavaScript、CSS 或 Web API 能力。

## 以秀米为例

先在普通 Safari 中登录秀米，再把目标改为：

```python
TARGET_DOMAIN = "xiumi.us"
```

建议验证顺序：

1. 先运行 `safari_cookie.py xiumi.us`，确认能读到有效 cookie。
2. 先访问登录后只读页面，确认没有跳回登录页。
3. 再访问 `https://xiumi.us/studio/v5` 编辑器。
4. 最后测试新建、保存、上传等有副作用操作。

如果普通页面已登录、编辑器仍未登录，优先检查编辑器实际使用的子域名、localStorage、CSRF token 和额外 API token，而不是重复注入同一批 cookie。

## 故障定位

### `No active cookies`

- Safari 实际使用了另一个 profile。
- 登录 cookie 已过期或是 session cookie。
- 目标 domain 写错。
- 当前进程没有读取 Safari 容器的权限。

### `PermissionError`

给运行脚本的宿主程序授予 Full Disk Access，然后完全重启该宿主程序再试。

### `safaridriver did not become ready`

检查：

```bash
lsof -nP -iTCP:4448 -sTCP:LISTEN
safaridriver --version
```

如果 4448 已被其他 driver 占用，修改 `PORT`。

### 注入后仍然未登录

按顺序排查：

1. cookie 是否属于实际访问的 domain。
2. cookie 的 path 是否覆盖当前 URL。
3. 是否需要额外子域名 cookie。
4. 是否依赖 localStorage/IndexedDB/CSRF/token。
5. 旧 Safari 是否已经无法运行目标站点当前前端。
6. 页面是否被 Cloudflare、验证码或其他反自动化机制拦截。

### 只部分注入

新版模板会在任一 WebDriver 操作失败时抛错。查看失败的 HTTP 方法和 endpoint；重点检查当前页面 domain、`__Host-` cookie、过期时间以及旧版 driver 协议。

## 设计取舍

- 保留单次全文件读取，避免每个 cookie 重新扫描文件。
- 保留标准库实现，不引入 Selenium/Playwright。
- 保留固定端口和简单模板，方便旧 macOS 手动排查。
- 用短等待和状态轮询替代固定的 driver 启动等待。
- 不伪造 `secure`/`httpOnly` 属性，避免认证语义被改变。

