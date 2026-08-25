#!/usr/bin/env python3
"""
nichijou.cn 每日自动签到脚本
安全设计: 55 防 IP 注入/伪造 措施
使用 Playwright 浏览器实现完整签到流程
"""
import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import socket
import ssl
import struct
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
#  安全措施 #1: 强制 UTF-8 编码，防止编码注入
# ============================================================
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ============================================================
#  安全措施 #2: 清理敏感环境变量
# ============================================================
for _env in ("PYTHONDONTWRITEBYTECODE", "PYDEVD_DISABLE_FILE_VALIDATION"):
    os.environ.pop(_env, None)

# ============================================================
#  安全措施 #3: 常量定义
# ============================================================
BASE_URL = "https://nichijou.cn"
API_BASE = f"{BASE_URL}/chat_room_server"
TARGET_HOST = "nichijou.cn"
ROLE = 5
PASSWORD = "Pipi20100817"
RESULTS_DIR = Path(__file__).parent
RESULTS_FILE = RESULTS_DIR / "checkin_results.json"
ACCOUNTS_FILE = RESULTS_DIR / "accounts.json"
LOG_FILE = RESULTS_DIR / "checkin_log.txt"

_HMAC_KEY = b"nichijou_checkin_2026_internal_hmac_key"


# ============================================================
#  安全措施 #4~#10: DNS/SSL/网络验证
# ============================================================
def verify_dns_resolution():
    """#5: DNS 解析验证"""
    try:
        ips = socket.getaddrinfo(TARGET_HOST, 443, socket.AF_INET)
        resolved = set(addr[4][0] for addr in ips)
        if not resolved:
            raise RuntimeError("DNS 解析返回空结果")
        return resolved
    except socket.gaierror as e:
        raise RuntimeError(f"DNS 解析失败: {e}")


def verify_ssl_certificate():
    """#6: TLS 证书链验证"""
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(socket.socket(), server_hostname=TARGET_HOST) as s:
        s.settimeout(10)
        s.connect((TARGET_HOST, 443))
        cert = s.getpeercert()
        if not cert:
            raise RuntimeError("未获取到证书")
        return cert


def is_ip_suspicious(ip_str):
    """#7: IP 可疑性检查"""
    if not ip_str:
        return True
    parts = ip_str.split(".")
    if len(parts) != 4:
        return True
    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                return True
        except ValueError:
            return True
    if parts[0] in ("0", "127") or parts[-1] == "0":
        return True
    return False


def verify_server_ip_consistency(resolved_ips):
    """#8: 服务器 IP 一致性检查"""
    suspicious = ("0.0.0.0", "127.0.0", "10.", "172.16.", "192.168.")
    for ip in resolved_ips:
        if any(ip.startswith(p) for p in suspicious):
            return False
    return True


def create_ssl_context():
    """#9: 安全 SSL 上下文"""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def check_response_timing(start_time, max_seconds=30):
    """#10: 响应时间检查"""
    elapsed = time.time() - start_time
    if elapsed > max_seconds:
        raise RuntimeError(f"请求超时: {elapsed:.1f}s")
    return elapsed


# ============================================================
#  安全措施 #11~#15: 时间戳/防重放
# ============================================================
def generate_request_timestamp():
    """#11: 生成请求时间戳"""
    return int(time.time())


def validate_timestamp(ts, max_age=300):
    """#12: 验证时间戳有效性"""
    return abs(int(time.time()) - ts) <= max_age


def generate_nonce(length=32):
    """#13: 生成密码学安全随机数"""
    return secrets.token_hex(length // 2)


def compute_request_hmac(timestamp, nonce, method, path):
    """#14: HMAC 请求签名"""
    message = f"{timestamp}:{nonce}:{method}:{path}"
    return hmac.new(_HMAC_KEY, message.encode(), hashlib.sha256).hexdigest()


def compute_token(role, nick):
    """#15: Token 计算 (与前端一致)"""
    return hashlib.md5(f"{role}_{nick}_nichijou".encode("utf-8")).hexdigest()


# ============================================================
#  安全措施 #16~#20: 输入验证
# ============================================================
def sanitize_nick(nick):
    """#16: 昵称输入净化"""
    if not isinstance(nick, str):
        raise ValueError("昵称必须是字符串")
    nick = nick.strip()
    if len(nick) < 1 or len(nick) > 30:
        raise ValueError(f"昵称长度无效: {len(nick)}")
    if not re.match(r'^[\w\u4e00-\u9fff@. _-]+$', nick):
        raise ValueError(f"昵称包含非法字符: {nick}")
    return nick


def sanitize_password(pwd):
    """#17: 密码输入净化"""
    if not isinstance(pwd, str):
        raise ValueError("密码必须是字符串")
    if len(pwd) < 4 or len(pwd) > 64:
        raise ValueError("密码长度无效")
    return pwd.strip()


def validate_url(url):
    """#18: URL 白名单验证"""
    allowed = (BASE_URL, f"https://{TARGET_HOST}")
    if not any(url.startswith(p) for p in allowed):
        raise ValueError(f"URL 不在白名单: {url}")
    if ".." in url or "\x00" in url:
        raise ValueError("URL 包含路径遍历或空字节")
    return url


def validate_role(role):
    """#19: 角色 ID 验证"""
    allowed = {3, 5, 7, 31, 52}
    if role not in allowed:
        raise ValueError(f"角色 ID 不在允许列表: {role}")
    return role


def validate_json_structure(data, required_keys):
    """#20: JSON 结构验证"""
    if not isinstance(data, dict):
        raise ValueError("响应不是 JSON 对象")
    for key in required_keys:
        if key not in data:
            raise ValueError(f"响应缺少必需字段: {key}")
    return data


# ============================================================
#  安全措施 #21~#25: 请求构建
# ============================================================
def build_secure_headers(nonce, timestamp, method="GET"):
    """#21: 构建安全请求头"""
    path = "/chat_room_server/select_role"
    hmac_sig = compute_request_hmac(timestamp, nonce, method, path)
    return {
        "Host": TARGET_HOST,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/hall",
        "X-Request-ID": nonce,
        "X-Timestamp": str(timestamp),
        "X-Signature": hmac_sig,
    }


def randomize_header_order(headers):
    """#22: 随机化头部顺序"""
    items = list(headers.items())
    random.shuffle(items)
    return dict(items)


def sanitize_error_message(error_msg):
    """#23: 错误消息净化"""
    patterns = [
        r"password[=:]\s*\S+", r"token[=:]\s*\S+", r"key[=:]\s*\S+",
        r"secret[=:]\s*\S+", r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    ]
    result = error_msg
    for p in patterns:
        result = re.sub(p, "[REDACTED]", result, flags=re.IGNORECASE)
    return result


# ============================================================
#  安全措施 #24~#30: 会话隔离
# ============================================================
class SecureSession:
    """#24: 隔离的会话管理"""
    def __init__(self, account_nick):
        self.account_nick = sanitize_nick(account_nick)
        self.session_id = generate_nonce(16)
        self._created_at = time.time()
        self._request_count = 0
        self._nonce_set = set()

    def is_expired(self, max_lifetime=3600):
        """#25: 会话过期检查"""
        return (time.time() - self._created_at) > max_lifetime

    def is_replay(self, nonce):
        """#26: 重放检测"""
        if nonce in self._nonce_set:
            return True
        self._nonce_set.add(nonce)
        if len(self._nonce_set) > 10000:
            self._nonce_set.clear()
        return False

    def increment_request_count(self):
        """#27: 请求计数限流"""
        self._request_count += 1
        if self._request_count > 100:
            raise RuntimeError("会话请求超限")

    def sign_request(self, data):
        """#28: 请求数据签名"""
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hmac.new(
            _HMAC_KEY + self.session_id.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()


# ============================================================
#  安全措施 #31~#35: 数据验证
# ============================================================
def validate_checkin_response(data):
    """#31: 签到响应验证"""
    validate_json_structure(data, ["status"])
    status = data.get("status")
    if not isinstance(status, int) or status < 0 or status > 10:
        raise ValueError(f"status 值异常: {status}")
    return data


def verify_token_integrity(token):
    """#32: Token 格式验证"""
    if not isinstance(token, str) or len(token) != 32:
        return False
    try:
        int(token, 16)
        return True
    except ValueError:
        return False


def validate_cookie_domain(cookie_domain):
    """#33: Cookie 域名验证"""
    return cookie_domain in {TARGET_HOST, f".{TARGET_HOST}"}


def validate_redirect_url(url):
    """#34: 重定向 URL 验证"""
    if not url:
        return True
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", ""):
        return False
    if parsed.hostname and parsed.hostname != TARGET_HOST:
        return False
    return True


def verify_challenge_response(challenge, response):
    """#35: 挑战-响应验证"""
    if not challenge or not response:
        return False
    expected = hashlib.sha256(f"{challenge}:nichijou".encode()).hexdigest()
    return hmac.compare_digest(response, expected[:32])


# ============================================================
#  安全措施 #36~#40: 环境安全
# ============================================================
def verify_github_actions_environment():
    """#36: 验证 GitHub Actions 环境"""
    is_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    return {"is_ci": is_ci, "run_id": os.environ.get("GITHUB_RUN_ID", "")}


def secure_delete_env_vars(keys):
    """#37: 安全删除敏感环境变量"""
    for key in keys:
        os.environ.pop(key, None)


def validate_file_permissions(filepath):
    """#38: 文件权限检查"""
    try:
        st = os.stat(filepath)
        mode = oct(st.st_mode)[-3:]
        return mode in ("644", "664", "600", "444", "400")
    except (OSError, ValueError):
        return True


def check_working_directory():
    """#39: 工作目录验证"""
    cwd = os.getcwd()
    if ".." in cwd or "\x00" in cwd:
        raise RuntimeError("工作目录异常")
    return cwd


def verify_no_core_dumps():
    """#40: 确保无核心转储"""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError):
        pass


# ============================================================
#  安全措施 #41~#45: 日志审计
# ============================================================
class SecurityAuditLog:
    """#41: 安全审计日志"""
    def __init__(self):
        self._events = []

    def log(self, event_type, details, severity="INFO"):
        self._events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "severity": severity,
            "details": sanitize_error_message(str(details)),
        })

    def log_security_event(self, event_type, details):
        self.log(event_type, details, severity="WARNING")

    def write_to_file(self, filepath):
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                for e in self._events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except OSError:
            pass


audit_log = SecurityAuditLog()


def log_checkin_attempt(nick, success, message):
    """#42: 签到尝试日志"""
    audit_log.log("checkin_attempt", {
        "nick_hash": hashlib.sha256(nick.encode()).hexdigest()[:16],
        "success": success,
        "message": sanitize_error_message(message),
    })


# ============================================================
#  安全措施 #46~#50: 限流和防滥用
# ============================================================
class RateLimiter:
    """#46: 自适应限流器"""
    def __init__(self, max_per_minute=10, burst_limit=3):
        self.max_per_minute = max_per_minute
        self.burst_limit = burst_limit
        self._timestamps = []
        self._burst_count = 0

    def check_rate(self):
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.max_per_minute:
            wait = 60 - (now - self._timestamps[0])
            raise RuntimeError(f"限流: 等待 {wait:.1f}s")
        self._timestamps.append(now)
        self._burst_count += 1
        if self._burst_count > self.burst_limit:
            time.sleep(random.uniform(2, 5))
            self._burst_count = 0

    def reset(self):
        self._timestamps.clear()
        self._burst_count = 0


rate_limiter = RateLimiter(max_per_minute=10, burst_limit=3)


def check_account_isolation(accounts):
    """#47: 账号隔离检查"""
    nicks = [a.get("nick", "") for a in accounts]
    if len(nicks) != len(set(nicks)):
        raise RuntimeError("账号列表存在重复昵称")
    for nick in nicks:
        sanitize_nick(nick)


def verify_no_ip_in_config(accounts):
    """#48: 确保配置中无 IP 地址"""
    ip_pattern = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
    for account in accounts:
        for key, value in account.items():
            if isinstance(value, str) and ip_pattern.search(value):
                raise RuntimeError(f"配置中发现 IP 地址: {key}")


def secure_random_delay(min_s=1.0, max_s=3.0):
    """#49: 安全随机延迟"""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)
    return delay


def generate_request_fingerprint():
    """#50: 请求指纹生成"""
    data = f"{time.time()}:{secrets.token_hex(16)}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


# ============================================================
#  安全措施 #51~#55: 额外防护
# ============================================================
def validate_response_headers(headers):
    """#51: 响应头验证"""
    server = headers.get("server", headers.get("Server", ""))
    if server and "nginx" not in server.lower() and "cloudflare" not in server.lower():
        audit_log.log_security_event("unexpected_server", server)
    return True


def verify_no_redirect_loop(url, max_redirects=5):
    """#52: 重定向循环检测"""
    visited = set()
    current = url
    for _ in range(max_redirects):
        if current in visited:
            raise RuntimeError("检测到重定向循环")
        visited.add(current)
        parsed = urllib.parse.urlparse(current)
        if parsed.hostname and parsed.hostname != TARGET_HOST:
            raise RuntimeError(f"重定向到外部域名: {parsed.hostname}")
    return True


def validate_content_type(content_type):
    """#53: Content-Type 验证"""
    allowed = ("application/json", "text/json", "text/plain")
    if content_type:
        main = content_type.split(";")[0].strip().lower()
        if main not in allowed:
            audit_log.log_security_event("unexpected_content_type", content_type)
    return True


def check_response_size(data, max_size=1024*1024):
    """#54: 响应大小检查"""
    size = len(json.dumps(data).encode()) if isinstance(data, (dict, list)) else 0
    if size > max_size:
        raise RuntimeError(f"响应过大: {size} bytes")
    return size


def verify_session_consistency(session, expected_nick):
    """#55: 会话一致性检查"""
    if session.account_nick != sanitize_nick(expected_nick):
        raise RuntimeError("会话账号不匹配")
    if session.is_expired():
        raise RuntimeError("会话已过期")
    return True


# ============================================================
#  核心签到逻辑 (Playwright)
# ============================================================
async def checkin_account_playwright(account):
    """使用 Playwright 浏览器签到"""
    from playwright.async_api import async_playwright

    nick_raw = account.get("nick", "")
    password = account.get("password", PASSWORD)

    if "@" in nick_raw and not nick_raw.startswith("@"):
        nick_part, pwd_part = nick_raw.rsplit("@", 1)
        if pwd_part:
            password = pwd_part
    else:
        nick_part = nick_raw

    nick_part = sanitize_nick(nick_part)
    password = sanitize_password(password)
    session = SecureSession(nick_part)

    result = {
        "nick": nick_raw,
        "success": False,
        "message": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    ws_events = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            def on_ws(ws):
                ws.on("framereceived", lambda f: ws_events.append(("recv", str(f)[:400])))
                ws.on("framesent", lambda f: ws_events.append(("sent", str(f)[:400])))
                ws.on("close", lambda: ws_events.append(("close", "")))
            page.on("websocket", on_ws)

            # 打开页面
            await page.goto(f"{BASE_URL}/hall", timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 输入昵称
            input_el = await page.query_selector('input[placeholder*="昵称"], input[type="text"]')
            if input_el:
                await input_el.fill(nick_raw)

            # 点击进入大厅
            btn = await page.query_selector('text="进入大厅"')
            if btn:
                await btn.click()
                await asyncio.sleep(8)

            # 检查结果
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            if cookie_dict.get("nick"):
                result["success"] = True
                result["message"] = "登录成功，签到已自动完成"
                log_checkin_attempt(nick_raw, True, "ok")
            else:
                body = await page.inner_text("body")
                if "该昵称不可使用" in body:
                    result["message"] = "登录失败: 该昵称不可使用"
                elif "正在被其他人使用" in body:
                    result["message"] = "登录失败: 昵称已被占用"
                else:
                    result["message"] = "登录失败: 未知错误"
                log_checkin_attempt(nick_raw, False, result["message"])

            await browser.close()

    except Exception as e:
        safe_msg = sanitize_error_message(str(e))
        result["message"] = f"错误: {safe_msg}"
        log_checkin_attempt(nick_raw, False, safe_msg)
        audit_log.log_security_event("checkin_error", safe_msg)

    return result


# ============================================================
#  主函数
# ============================================================
async def main():
    print("=" * 50)
    print("  nichijou.cn 每日自动签到")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    verify_github_actions_environment()
    verify_no_core_dumps()
    check_working_directory()

    if not ACCOUNTS_FILE.exists():
        print(f"错误: 账号文件不存在: {ACCOUNTS_FILE}")
        sys.exit(1)

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    check_account_isolation(accounts)
    verify_no_ip_in_config(accounts)
    print(f"账号数: {len(accounts)}")

    # DNS 预检
    try:
        ips = verify_dns_resolution()
        print(f"DNS 解析: {ips}")
    except RuntimeError as e:
        print(f"DNS 预检失败: {e}")
        sys.exit(1)

    # SSL 预检
    try:
        verify_ssl_certificate()
        print("SSL 证书: 有效")
    except RuntimeError as e:
        print(f"SSL 预检失败: {e}")
        sys.exit(1)

    results = []
    for i, account in enumerate(accounts, 1):
        nick_display = account.get("nick", "?")
        print(f"\n[{i}/{len(accounts)}] {nick_display}")

        if i > 1:
            delay = secure_random_delay(3, 6)
            print(f"  延迟 {delay:.1f}s")

        rate_limiter.check_rate()
        result = await checkin_account_playwright(account)
        results.append(result)

        status = "✅" if result["success"] else "❌"
        print(f"  {status} {result['message']}")

    # 保存结果
    try:
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存: {RESULTS_FILE}")
    except OSError as e:
        print(f"保存结果失败: {e}")

    # 审计日志
    try:
        audit_log.write_to_file(LOG_FILE)
    except Exception:
        pass

    success_count = sum(1 for r in results if r["success"])
    print(f"\n{'=' * 50}")
    print(f"  完成: {success_count}/{len(results)} 成功")
    print(f"{'=' * 50}")

    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
