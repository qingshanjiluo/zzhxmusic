#!/usr/bin/env python3
"""
nichijou.cn 每日登录（完善版）
====================================================================
机制（由 capture_first_login.py 首次登录捕获逆向确认）:
  1. 登录检测: select_role -> WS enter(token=MD5("{role}_{nick}_nichijou"))
     -> connectSuccess -> 前端自动发送 hello 指令(带设备指纹 userKey/
     heartbeat/firstTime/newUser) -> 服务端据此完成每日签到判定
  2. 抽奖币分发: 服务端在 hello 后推送
     {"event":"message","title":"success","value":"恭喜连续第N天签到，获得X个抽奖币"}
     前端渲染为 ant-message toast；币进入 propBag(lottery_coin)
  3. IP 获取: 前端无任何 IP 探测请求(已验证HTTP全在站内) —— 服务端
     直接读取 WS/HTTP 连接源 IP，并配合 hello 指令中的设备指纹
     (localStorage userKey 设备ID / heartbeat / firstTime/newUser + 屏幕/时区)。
     实测(2026-09-13): 分发按【IP×时间窗】限量 —— 全新游客从"刚发过币的IP"
     登录同样被静默拒发；同 IP 两枚之间间隔≥25分钟成功、≤16分钟失败。
     被拒时服务端完全静默(无解释消息)。→ 本脚本按 ~30 分钟/IP 的发放冷却
     调度 + 代理池轮换 + 每账号全新上下文(新 userKey)。
      ⚠️ 已证伪(2026-09-13晚): "发币只认绑定头像32"不成立 —— 32恢复后可用
      role=32 登录仍被静默拒0币(周杰伦/梦实测)。限量维度是【出口IP×时间窗】,
      与头像无关。故头像策略=被占即回退, 不死等32; 补齐靠 cron 跨冷却窗口多轮。

本脚本功能:
  - 全新上下文模拟第一次登录，WS 帧 gzip 解码，捕获全部弹窗
    (通知公告 modal / 签到 toast / popModal / 原生 dialog)
  - 精确判定: 抽奖币到账(连签天数+币数) / 静默拒发 / 登录失败
  - 发放冷却调度: _ip_ledger 记录每IP最近发币时间，冷却期零登录跳过，
    定时任务(cron)每 GRANT_COOLDOWN_MIN(默认30) 分钟跑一轮自动补齐全部账号
  - 记录出口 IP + uid + role + 弹窗快照; 账号×日去重(--force 重跑)
  - 代理池轮换 (proxies.txt / PROXY_POOL / --proxy) + 启动预探测
  - 失败自动重试并换线路，失败截图到 daily_debug/
  - 支持分组 (兼容旧版 ACCOUNT_GROUP 环境变量: A/B/C)

用法:
  python daily_login.py                    # 全部账号
  python daily_login.py --group B          # 只跑 B 组
  python daily_login.py --only zzhx        # 只跑昵称含 zzhx 的
  python daily_login.py --force            # 忽略今日已签到状态
  python daily_login.py --no-proxy         # 强制直连
  python daily_login.py --headed           # 有头调试
"""
import asyncio
import gzip
import json
import os
import random
import re
import socket
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://nichijou.cn"
HERE = Path(__file__).parent
ACCOUNTS_FILE = HERE / "accounts.json"
RESULTS_FILE = HERE / "checkin_results.json"
STATE_FILE = HERE / "daily_state.json"
LOG_FILE = HERE / "daily_login_log.txt"
DEBUG_DIR = HERE / "daily_debug"

PROXY_CANDIDATES = ["socks5://127.0.0.1:10808", "socks5://127.0.0.1:10818"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

GROUP_MAP = {"A": [0, 1, 2, 3], "B": [4, 5, 6, 7], "C": [8, 9, 10, 11]}

REWARD_RE = re.compile(r"连续第\s*(\d+)\s*天签到[，,]?\s*获得\s*(\d+)\s*个抽奖币")
ALREADY_RE = re.compile(r"已签到|已领取|明天再来|已经打卡")

# 弹窗监听（同 capture_first_login）
POPUP_WATCHER_JS = r"""
(() => {
  if (window.__popupWatcherInstalled) return;
  window.__popupWatcherInstalled = true;
  window.__popups = [];
  const seen = new Set();
  const push = (text, cls) => {
    const t = (text || '').replace(/\s+/g, ' ').trim();
    if (!t) return;
    const key = t.slice(0, 160);
    if (seen.has(key)) return;
    seen.add(key);
    window.__popups.push({text: t.slice(0, 500), cls: String(cls||'').slice(0,120),
                          iso: new Date().toISOString()});
  };
  const SELS = ['.ant-modal','.ant-message-notice-content','.ant-notification-notice',
                '[class*="notifyCard"]','[class*="errmodalCard"]','[class*="Modal"]',
                '[class*="modal"]','[class*="dialog"]'];
  const scan = (n) => {
    if (!n || n.nodeType !== 1) return;
    for (const s of SELS) {
      try { if (n.matches(s)) push(n.textContent, n.className);
            n.querySelectorAll(s).forEach(el => push(el.textContent, el.className)); } catch(e){}
    }
  };
  const start = () => new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) scan(n);
  }).observe(document.documentElement, {childList: true, subtree: true});
  if (document.documentElement) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
"""

DISMISS_JS = r"""
(() => {
  const clicked = [];
  document.querySelectorAll('.ant-modal button, [class*="notifyCard"] button, [class*="Modal"] button').forEach(b => {
    const t = (b.textContent || '').trim();
    if (['知道了','确定','关闭','取消'].includes(t)) { b.click(); clicked.push(t); }
  });
  return clicked;
})();
"""


def log_line(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print("  " + line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def decode_ws_frame(payload):
    """payload: bytes/str -> (kind, text_or_obj)"""
    raw = None
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        s = payload.strip()
        if s.startswith("b'") or s.startswith('b"'):
            try:
                import ast
                raw = ast.literal_eval(s)
            except Exception:
                pass
    if raw is None:
        try:
            return ("json", json.loads(payload))
        except Exception:
            return ("text", str(payload)[:500])
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            try:
                raw = zlib.decompressobj(31).decompress(raw)
            except Exception:
                return ("bin", repr(raw[:120]))
    txt = raw.decode("utf-8", "replace")
    try:
        return ("json", json.loads(txt))
    except Exception:
        return ("text", txt[:500])


IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b")

IP_ECHO_URLS = ("https://api.ip.sb/ip", "https://ifconfig.me/ip",
                "https://ipinfo.io/ip", "https://api.ipify.org")


async def detect_egress_ip(page):
    """在页面网络栈(含代理)内探测出口 IP，返回合法 IPv4 或 None"""
    for url in IP_ECHO_URLS:
        try:
            r = await page.request.get(url, timeout=8000)
            body = ((await r.text()) or "").strip()
            m = IPV4_RE.search(body)
            if m and m.group(0) not in ("127.0.0.1", "0.0.0.0"):
                return m.group(0)
        except Exception:
            continue
    return None


def fleet_ip_map():
    """本地 xray 节点舰队(xray_fleet.py 生成, 2h 内有效): {socks串: 出口IP}"""
    pf = HERE / "fleet_ports.json"
    try:
        if pf.exists() and (time.time() - pf.stat().st_mtime) < 2 * 3600:
            data = json.loads(pf.read_text(encoding="utf-8"))
            return {f"socks5://127.0.0.1:{m['port']}": m["ip"]
                    for m in data if m.get("ip")}
    except Exception:
        pass
    return {}


def load_proxy_pool():
    """代理池: 节点舰队 > 环境变量 PROXY_POOL(逗号分隔) > proxies.txt(每行一个)"""
    env = os.environ.get("PROXY_POOL")
    pool = [x.strip() for x in env.split(",") if x.strip()] if env else []
    pf = HERE / "proxies.txt"
    if not pool and pf.exists():
        pool = [ln.strip() for ln in pf.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
    fleet = list(fleet_ip_map())
    if fleet:
        pool = fleet + [p for p in pool if p not in fleet]
    return pool


def proxy_alive(cand: str) -> bool:
    try:
        port = int(cand.rsplit(":", 1)[1])
        s = socket.create_connection(("127.0.0.1", port), timeout=1.5)
        s.close()
        return True
    except (OSError, ValueError):
        return False


def pick_proxy(enable: bool):
    if not enable:
        return None
    env = os.environ.get("PROXY_SERVER")
    cands = [env] if env else PROXY_CANDIDATES
    for cand in cands:
        if proxy_alive(cand):
            return cand
    return None


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


async def run_account(nick_full: str, password: str, proxy_server, headed: bool):
    """登录一个账号并捕获弹窗/签到奖励。返回结果 dict。"""
    from playwright.async_api import async_playwright

    nick_part = nick_full.split("@")[0] if "@" in nick_full else nick_full
    res = {
        "nick": nick_full, "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().isoformat(timespec="seconds"),
        "logged_in": False, "uid": None, "role": None,
        "reward": None, "streak_days": None, "coins": None,
        "already_claimed": False, "status": "fail", "detail": "",
        "popups": [], "egress_ip": None, "errors": [], "ws_messages": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            proxy={"server": proxy_server} if proxy_server else None,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720}, user_agent=UA,
                locale="zh-CN", timezone_id="Asia/Shanghai",
            )
            await context.add_init_script(POPUP_WATCHER_JS)
            page = await context.new_page()
            page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

            ws_events = []
            ws_err = {"n": 0}
            def on_ws(ws):
                def on_recv(payload):
                    kind, obj = decode_ws_frame(payload)
                    if kind == "json":
                        ws_events.append(obj)
                def on_err(_):
                    ws_err["n"] += 1
                ws.on("framereceived", on_recv)
                ws.on("socketerror", on_err)
            page.on("websocket", on_ws)

            sel_box = {}
            async def on_selresp(r):
                if "select_role" in r.url:
                    try:
                        sel_box["body"] = await r.json()
                    except Exception:
                        pass
            page.on("response", on_selresp)

            await page.goto(f"{BASE_URL}/hall", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_selector(".avatarBoxImg", timeout=20000)
            await asyncio.sleep(1.5)

            # ---------- 登录：遍历大厅放出的头像，以 connectSuccess 帧为唯一标准 ----------
            # 实测: enter 握手 403 = 该头像在握手瞬间已被占用（select_role 的 status0
            # 存在竞态不可靠）。32 优先（历史上发币会话均为32，待对比验证），失败换下一个。
            logged = False
            tried_roles = []
            loop = asyncio.get_event_loop()
            for _pass in range(2):
                alts = await page.evaluate("""() => [...new Set(
                    [...document.querySelectorAll('.avatarBoxImg')].map(e => e.alt)
                    )].filter(a => a && a !== '8')""")
                order = (["32"] if "32" in alts else []) + \
                        [a for a in alts if a != "32" and a not in tried_roles]
                for alt in order[:6]:
                    tried_roles.append(alt)
                    sel_box.clear()
                    ws_err["n"] = 0
                    await page.evaluate("""(a) => {
                        const i = document.querySelector(`.avatarBoxImg[alt="${a}"]`);
                        if (i) i.click();
                    }""", alt)
                    try:
                        await page.wait_for_selector(".loginBoxNickInput", timeout=8000)
                    except Exception:
                        await page.goto(f"{BASE_URL}/hall", timeout=30000)
                        await page.wait_for_selector(".avatarBoxImg", timeout=15000)
                        continue
                    await page.evaluate("""(nick) => {
                        const input = document.querySelector('.loginBoxNickInput');
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(input, nick);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }""", nick_full)
                    await asyncio.sleep(0.5)
                    await page.evaluate("""() => {
                        document.querySelector('.loginBoxBtnEnter:not([disabled])').click();
                    }""")
                    t_end = loop.time() + 9
                    while loop.time() < t_end:
                        await asyncio.sleep(0.4)
                        if any(e.get("event") == "connectSuccess" for e in ws_events):
                            logged = True
                            break
                        if ws_err["n"]:
                            break  # 403: 头像已被占
                        sb = sel_box.get("body") or {}
                        if sb.get("status") == 1:
                            break  # select_role 明确说被占
                    if logged:
                        res["avatar_role"] = int(alt)
                        break
                    await page.goto(f"{BASE_URL}/hall", timeout=30000)
                    try:
                        await page.wait_for_selector(".avatarBoxImg", timeout=15000)
                    except Exception:
                        break
                    await asyncio.sleep(1.2)
                if logged:
                    break
            if not logged:
                res["status"] = "avatar_busy"
                res["detail"] = f"头像均被占(403/占用): 已试 {tried_roles}"
                return res

            # 等待 connectSuccess + 签到消息（最多 15s）
            t0 = asyncio.get_event_loop().time()
            seen_reward = False
            while asyncio.get_event_loop().time() - t0 < 15:
                await asyncio.sleep(1.0)
                for ev in ws_events:
                    if ev.get("event") == "connectSuccess":
                        res["logged_in"] = True
                        res["uid"] = ev.get("uid")
                        res["role"] = ev.get("resultId")
                        res["server_nick"] = ev.get("nick")
                    if ev.get("event") == "message":
                        val = str(ev.get("value", ""))
                        title = str(ev.get("title", ""))
                        res["ws_messages"].append({"title": title, "value": val[:200]})
                        if "抽奖币" in val or "签到" in val:
                            m = REWARD_RE.search(val)
                            res["reward"] = val
                            if m:
                                res["streak_days"] = int(m.group(1))
                                res["coins"] = int(m.group(2))
                            else:
                                res["coins"] = res["coins"] or 1
                            seen_reward = True
                        elif ALREADY_RE.search(val):
                            res["already_claimed"] = True
                            res["detail"] = f"消息: {val}"
                        elif title in ("error", "warn", "warning") and "签到" not in val:
                            res["errors"].append(f"[{title}] {val}")
                            if not res["logged_in"]:
                                res["detail"] = val
                if seen_reward and asyncio.get_event_loop().time() - t0 > 5:
                    break
                if res["logged_in"] and (res["already_claimed"] or res["errors"]) \
                        and asyncio.get_event_loop().time() - t0 > 6:
                    break

            # 弹窗快照 + 关闭通知公告
            await asyncio.sleep(1.0)
            popups = await page.evaluate("() => window.__popups || []")
            res["popups"] = [
                {"iso": x.get("iso", ""), "cls": x.get("cls", ""), "text": x.get("text", "")}
                for x in popups
                if "loginBox" not in x.get("cls", "")  # 过滤登录框本身
            ][:30]
            clicked = await page.evaluate(DISMISS_JS)
            if clicked:
                log_line(f"已点击弹窗按钮: {clicked}")
            await asyncio.sleep(1.0)
            clicked2 = await page.evaluate(DISMISS_JS)
            if clicked2:
                log_line(f"第二轮关闭: {clicked2}")

            # cookie 校验登录态
            cookies = await context.cookies()
            ck_nick = next((c["value"] for c in cookies if c["name"] == "nick"), "")
            ck_role = next((c["value"] for c in cookies if c["name"] == "role"), "")
            if not res["logged_in"]:
                res["logged_in"] = bool(ck_nick) and (nick_part in ck_nick)
            res["cookie_role"] = ck_role or None

            # 出口 IP（服务端看到的就是它 —— 登录分发判定的关键变量）
            res["egress_ip"] = await detect_egress_ip(page)

            # 状态判定
            if seen_reward:
                res["status"] = "rewarded"
            elif res["logged_in"] and res["already_claimed"]:
                res["status"] = "already"
            elif res["logged_in"]:
                res["status"] = "logged_in_no_reward"
                res["detail"] = res["detail"] or "登录成功但未见抽奖币分发消息（今日可能已在其它端发放）"
            else:
                res["status"] = "fail"
                res["detail"] = res["detail"] or "; ".join(res["errors"]) or "登录未完成"

            if res["status"] in ("fail",):
                DEBUG_DIR.mkdir(exist_ok=True)
                shot = DEBUG_DIR / f"fail_{nick_part}_{datetime.now().strftime('%H%M%S')}.png"
                try:
                    await page.screenshot(path=str(shot))
                    res["screenshot"] = str(shot)
                except Exception:
                    pass
        finally:
            await browser.close()

    return res


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=list(GROUP_MAP) + ["ALL"],
                    default=os.environ.get("ACCOUNT_GROUP", "ALL"))
    ap.add_argument("--only", default=None, help="只跑昵称包含此子串的账号")
    ap.add_argument("--force", action="store_true", help="今日已发奖励也重跑")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--proxy", default=None, help="覆盖代理地址，如 socks5://127.0.0.1:10818")
    ap.add_argument("--allow-direct", action="store_true", help="代理池用尽后允许直连兜底")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--retries", type=int, default=2)
    args = ap.parse_args()

    accounts = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    if args.group in GROUP_MAP:
        idx = GROUP_MAP[args.group]
        accounts = [accounts[i] for i in idx if i < len(accounts)]
    if args.only:
        accounts = [a for a in accounts if args.only in a["nick"]]

    # ---- 构建代理候选序列（轮换使用，每个账号尽量用未被今日"消耗"的出口IP）----
    pool = load_proxy_pool()
    if args.no_proxy:
        pool = []  # --no-proxy 必须清空池, 不能被 proxies.txt 绕过
    elif args.proxy:
        pool = [args.proxy]
    elif not pool and not args.no_proxy:
        single = pick_proxy(True)
        pool = [single] if single else []
    if args.allow_direct or not pool:
        pool = pool + [None]  # 直连兜底

    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    # 历史 IP 台账：分发存在【IP×时间窗】限制（实测2026-09-13：
    # 全新游客从当日已发的IP登录也被静默拒发；同IP两次成功发放间隔≥25分钟，
    # 间隔16分钟即被拒）→ 记录每个IP最近发放时间，冷却期内不再用该IP做无谓登录
    ip_ledger = state.setdefault("_ip_ledger", {})
    if ip_ledger.get("date") != today:
        ip_ledger.clear()
        ip_ledger["date"] = today
        ip_ledger["grants"] = {}
        ip_ledger["last_grant"] = {}
    granted_ips = ip_ledger.setdefault("grants", {})
    last_grant = ip_ledger.setdefault("last_grant", {})
    COOLDOWN_SEC = int(os.environ.get("GRANT_COOLDOWN_MIN", "30")) * 60
    proxy_ip_cache = {}  # 代理地址 -> 出口IP（本次运行内缓存）
    for v in state.values():
        if isinstance(v, dict) and v.get("date") == today and v.get("status") == "rewarded" \
                and v.get("egress_ip"):
            ts_iso = v.get("time")
            if ts_iso:
                try:
                    t = datetime.fromisoformat(ts_iso).timestamp()
                    if t > last_grant.get(v["egress_ip"], 0):
                        last_grant[v["egress_ip"]] = t
                except ValueError:
                    pass
            if v.get("proxy") and v["proxy"] != "直连":
                proxy_ip_cache.setdefault(v["proxy"], v["egress_ip"])
    for pk, pv in state.get("_proxy_ip", {}).items():
        proxy_ip_cache.setdefault(pk, pv)

    def record_grant(ip, nick_part):
        if ip:
            lst = granted_ips.setdefault(ip, [])
            if nick_part not in lst:
                lst.append(nick_part)
            last_grant[ip] = datetime.now().timestamp()
            save_state(state)

    def ip_in_cooling(ip):
        t = last_grant.get(ip)
        return bool(t) and (time.time() - t) < COOLDOWN_SEC

    def consumed_ips():
        return set(granted_ips)

    def ip_of(proxy):
        return proxy_ip_cache.get(proxy)

    def remember_ip(proxy, ip):
        if proxy is not None and ip:
            proxy_ip_cache[proxy] = ip
            pmap = state.setdefault("_proxy_ip", {})
            if pmap.get(proxy) != ip:
                pmap[proxy] = ip
                save_state(state)

    # ---- 启动预探测：为池内每个代理解析一次出口IP（避免浪费账号登录）----
    async def preflight_pool():
        from playwright.async_api import async_playwright
        dead = []
        async with async_playwright() as p:
            for pr in pool:
                if pr is None:
                    continue
                if pr in _fim:   # 舰队端口已 curl 探测过出口IP, 免浏览器复检
                    continue
                try:
                    browser = await p.chromium.launch(
                        headless=True, proxy={"server": pr},
                        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
                    ctx = await browser.new_context(user_agent=UA)
                    page = await ctx.new_page()
                    ip = await detect_egress_ip(page)
                    await browser.close()
                    if ip:
                        remember_ip(pr, ip)
                        g = len(granted_ips.get(ip, []))
                        cool = " 🧊冷却中" if ip_in_cooling(ip) else ""
                        log_line(f"预探测: {pr} → 出口IP {ip} 今发{g}币{cool}" if g
                                 else f"预探测: {pr} → 出口IP {ip}{cool}")
                    else:
                        dead.append(pr)
                        log_line(f"预探测: {pr} 拿不到出口IP → 移出池")
                except Exception as e:
                    dead.append(pr)
                    log_line(f"预探测 {pr} 失败(移出池): {str(e)[:100]}")
        # 剔除探测失败的死代理，避免每个账号撞 N 次重试
        for d in dead:
            while d in pool:
                pool.remove(d)
        if not pool:
            pool.append(None)  # 全死了退回直连

    pending_accs = [a for a in accounts
                    if not (state.get(a["nick"], {}).get("date") == today
                            and state.get(a["nick"], {}).get("status") == "rewarded")
                    or args.force]
    _fim = fleet_ip_map()
    for _p, _ip in _fim.items():
        if _p in pool:
            remember_ip(_p, _ip)   # 舰队 curl 已探测过, 直接入台账
    if pending_accs:
        await preflight_pool()

    print("=" * 60)
    print("  nichijou.cn 每日登录（完善版）")
    print(f"  组: {args.group} | 账号数: {len(accounts)}")
    _pool_show = [x or "直连" for x in pool]
    if len(_pool_show) > 6:
        _pool_show = _pool_show[:6] + [f"…共{len(_pool_show)}个"]
    print(f"  代理池: {_pool_show} | 今日发放IP台账: "
          + (", ".join(f"{ip}({len(v)})" for ip, v in granted_ips.items()) or "无"))
    print("=" * 60)

    results = []
    no_reward_accts = set()  # 本轮已被"干净IP"拒发的账号 = 账号级, 不再重试
    cursor = 0
    avatar_squat = False  # 32号头像被外部用户占用 → 本轮剩余账号全部短路
    # 尝试次数少的账号优先（可能已领的账号不再霸占发放窗口）
    def tries_of(a):
        s = state.get(a["nick"], {})
        return s.get("tries", 0) if s.get("date") == today else 0
    # 主号永远第一; 其余按尝试次数少者优先
    accounts = sorted(accounts,
                      key=lambda a: (0 if a["nick"].startswith("最中幻想") else 1,
                                     tries_of(a)))
    for i, acc in enumerate(accounts, 1):
        nick_full = acc["nick"]
        password = acc.get("password", "")
        nick_part = nick_full.split("@")[0]
        print(f"\n[{i}/{len(accounts)}] {nick_part}")

        st = state.get(nick_full, {})
        if st.get("date") == today and st.get("status") == "rewarded" and not args.force:
            log_line(f"今日已发放奖励（{st.get('reward')}），跳过。--force 可重跑")
            r = dict(st); r["skipped"] = True; r["nick"] = nick_full
            results.append(r)
            continue

        # 头像占用全局短路：12账号共用32号头像，一人被占=全员被占
        if avatar_squat:
            r = {"nick": nick_full, "date": today,
                 "time": datetime.now().isoformat(timespec="seconds"),
                 "logged_in": None, "uid": None, "reward": None, "streak_days": None,
                 "coins": None, "already_claimed": False, "status": "avatar_busy",
                 "detail": "32号头像被占用，未尝试（等释放后下轮cron自动补）",
                 "popups": [], "egress_ip": None, "errors": [], "ws_messages": [],
                 "proxy": "未尝试"}
            results.append(r)
            log_line("🎭 avatar_busy: " + r["detail"])
            continue

        # 冷却感知：优先选不在“发放冷却期”的出口IP；全部冷却则本轮不登录（留给下次cron）
        rotated = [pool[(cursor + t) % len(pool)] for t in range(len(pool))]
        fresh = [p for p in rotated if not (ip_of(p) and ip_in_cooling(ip_of(p)))]
        if not fresh:
            pool_ips = [x for x in (ip_of(p) for p in rotated)
                        if x and x in last_grant]
            if pool_ips:
                nxt = min(last_grant[ip] for ip in pool_ips) + COOLDOWN_SEC
                nxt_s = datetime.fromtimestamp(nxt).strftime("%H:%M")
            else:
                nxt_s = "稍后"
            r = {"nick": nick_full, "date": today,
                 "time": datetime.now().isoformat(timespec="seconds"),
                 "logged_in": None, "uid": None, "reward": None, "streak_days": None,
                 "coins": None, "already_claimed": False, "status": "cooling",
                 "detail": f"全部出口IP处于发放冷却(<{COOLDOWN_SEC//60}分钟)，下次可试≈"
                           + nxt_s,
                 "popups": [], "egress_ip": None, "errors": [], "ws_messages": [],
                 "proxy": "未尝试"}
            results.append(r)
            prev = state.get(nick_full, {})
            entry = {k: r.get(k) for k in
                     ("nick", "date", "time", "status", "uid", "egress_ip", "proxy")}
            entry["tries"] = prev.get("tries", 0) if prev.get("date") == today else 0
            state[nick_full] = entry
            save_state(state)
            log_line("🧊 cooling: " + r["detail"])
            continue
        proxy = fresh[0]
        cursor = (pool.index(proxy) + 1) % len(pool)
        r = None
        for attempt in range(1, args.retries + 2):
            try:
                r = await run_account(nick_full, password, proxy, args.headed)
            except Exception as e:
                r = {"nick": nick_full, "date": today, "logged_in": False,
                     "time": datetime.now().isoformat(timespec="seconds"),
                     "uid": None, "role": None, "egress_ip": None,
                     "popups": [], "ws_messages": [], "errors": [str(e)[:200]],
                     "status": "fail", "already_claimed": False,
                     "reward": None, "streak_days": None, "coins": None,
                     "detail": f"运行异常: {type(e).__name__}: {str(e)[:120]}",
                     "proxy": proxy}
            r["attempt"] = attempt
            r["proxy"] = proxy or "直连"
            remember_ip(proxy, r.get("egress_ip"))
            if r["status"] != "fail":
                break
            log_line(f"第{attempt}次失败: {r['detail'][:120]}")
            if attempt <= args.retries:
                others = [p for p in rotated if p != proxy
                          and not (ip_of(p) and ip_in_cooling(ip_of(p)))]
                proxy = others[0] if others else proxy
                await asyncio.sleep(random.uniform(3, 6))

        if r["status"] == "avatar_busy":
            avatar_squat = True
        if r["status"] == "rewarded":
            record_grant(r.get("egress_ip"), nick_part)
        elif r["status"] == "logged_in_no_reward" and not r["errors"]:
            ipx = r.get("egress_ip")
            if ipx and ipx in granted_ips:
                # 该IP今天确实发过币 → 这次静默可能是 IP 级限流, 冷却它
                r["detail"] = ("登录成功、hello 已发但未发币；本IP今日已发过币，"
                               "疑似 IP 级限量 → 该IP进冷却")
                last_grant[ipx] = time.time()
                save_state(state)
            else:
                # 全新IP也拒 → 是【账号级】拒发(已领/不符资格), 与IP无关。
                # 绝不给干净IP降温, 否则一个坏账号会误锁整池×30分钟。
                r["detail"] = ("登录成功、hello 已发但被拒；该IP今日从未发币 ⇒ "
                               "账号级拒发(该账号今天已领/不符资格), IP不受影响")
                no_reward_accts.add(nick_part)

        results.append(r)
        prev = state.get(nick_full, {})
        tries = prev.get("tries", 0) if prev.get("date") == today else 0
        if r["status"] in ("logged_in_no_reward", "already"):
            tries += 1
        elif r["status"] == "rewarded":
            tries = 0
        entry = {k: r.get(k) for k in
                 ("nick", "date", "time", "status", "reward", "streak_days", "coins",
                  "uid", "role", "egress_ip", "logged_in", "proxy")}
        entry["tries"] = tries
        state[nick_full] = entry
        save_state(state)

        icon = {"rewarded": "🪙", "already": "✅", "logged_in_no_reward": "🔁",
                "avatar_busy": "🎭", "fail": "❌"}.get(r["status"], "❓")
        extra = r.get("reward") or r.get("detail") or ""
        log_line(f"{icon} {r['status']} | uid={r.get('uid')} role={r.get('cookie_role')} "
                 f"IP={r.get('egress_ip')} via={r.get('proxy')} | {extra[:80]}")
        if r.get("popups"):
            log_line(f"   捕获弹窗x{len(r['popups'])}: "
                     + " ‖ ".join(p["text"][:40] for p in r["popups"][:4]))
        await asyncio.sleep(random.uniform(4, 8))

    RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    n_reward = sum(1 for r in results if r.get("status") == "rewarded")
    n_ok = sum(1 for r in results if r.get("status") in ("rewarded", "already", "logged_in_no_reward"))
    n_cool = sum(1 for r in results if r.get("status") == "cooling")
    n_squat = sum(1 for r in results if r.get("status") == "avatar_busy")
    total_coins = sum(r.get("coins") or 0 for r in results if r.get("status") == "rewarded")
    print("\n" + "=" * 60)
    print(f"  登录成功: {n_ok}/{len(results)} | 今日新领抽奖币: {n_reward}人 共{total_coins}币"
          + (f" | 🧊冷却待下次: {n_cool}" if n_cool else "")
          + (f" | 🎭头像被占: {n_squat}" if n_squat else ""))
    for r in results:
        mark = {"rewarded": "🪙", "already": "✅", "logged_in_no_reward": "🔁",
                "cooling": "🧊", "avatar_busy": "🎭", "fail": "❌"}
        print(f"   {mark.get(r.get('status'),'❓')} {r.get('nick','?').split('@')[0]:<10} "
              f"{r.get('status','?'):<18} {r.get('reward') or r.get('detail') or ''}")
    print("=" * 60)
    if n_cool:
        print(f"  🧊 有 {n_cool} 个账号因IP发放冷却未跑：定时任务(cron)每隔"
              f"{COOLDOWN_SEC//60}分钟再执行一次即可自动补齐")
    if n_squat:
        print("  🎭 32号头像被外部用户占用（全部账号绑定该头像）：下轮cron自动重试")
    # 仅当有真正失败(非rewarded/already/no_reward/cooling/avatar_busy)时返回1
    hard_fail = [r for r in results if r.get("status") not in
                 ("rewarded", "already", "logged_in_no_reward", "cooling", "avatar_busy")]
    return 0 if not hard_fail else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
