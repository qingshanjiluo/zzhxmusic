#!/usr/bin/env python3
"""批量注册 nichijou 新账号（舰队版）。
流程: 游客登录(任意空闲头像) → 进低人气房发消息刷阳光到≥110 →
房内发 /password_<密码> 注册 → 记录结果(增量落盘 register_result_0925.json)。
每个号走不同的舰队节点 IP, 降低同 IP 关联。
"""
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_coins import HOOK_JS  # noqa: E402  prototype.send 钩子 + __sendRaw/__sendComp
from daily_login import decode_ws_frame  # noqa: E402

HERE = Path(__file__).resolve().parent
NEW_ACCOUNTS = ["中", "6", "雅", "善", "想", "美", "洛天依", "miku"]
PASSWORD = "Pipi20100817"
RESULT_FILE = HERE / "register_result_0925.json"
DBG = HERE / "daily_debug"
SUN_TARGET = 110
MSG_POOL = ["6", "嗯", "好", "ok", "1", "来了", "冲", "赞", "棒", "nice",
            "good", "哈哈", "嘿嘿", "哦哦", "是的", "对", "可以", "听歌",
            "这首歌不错", "好听", "前排", "打卡", "来了来了", "支持",
            "今天也在听歌", "晚安", "午安", "有人吗", "新来的", "日常真好看"]
SUN_TARGET = 110
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def load_fleet():
    data = json.loads((HERE / "fleet_ports.json").read_text(encoding="utf-8"))
    return [m for m in data if m.get("ip")]


async def clear_all(page):
    await page.evaluate("""() => {
        document.querySelectorAll('.ant-message, .ant-message-notice, .ant-message-notice-wrapper, .ant-message-notice-container').forEach(el => el.remove());
        document.querySelectorAll('[class*="errmordalGrid"], [class*="errmodal"], #connectError, .comBlurMask, .comFullAbsDiv').forEach(el => el.remove());
        document.querySelectorAll('button, a').forEach(btn => {
            if (btn.textContent.trim() === '知道了') btn.click();
        });
    }""")


async def get_sunshine(page, my_nick):
    try:
        return await page.evaluate("""async (nick) => {
            try {
                const resp = await fetch('https://nichijou.cn/chat_room_server/get_hall_info');
                const data = await resp.json();
                const users = (data.data || {}).userList || [];
                for (const u of users) {
                    if (u.nick === nick) return (u.extInfo || {}).power || 0;
                }
                return 0;
            } catch(e) { return 0; }
        }""", my_nick) or 0
    except Exception:
        return 0


async def pick_room(page):
    """低人气非密码普通房 → (title, id); --room N 可强制指定"""
    if "--room" in sys.argv:
        try:
            rid = int(sys.argv[sys.argv.index("--room") + 1])
            return "東雲研究所", rid
        except Exception:
            pass
    try:
        rooms = await page.evaluate("""async () => {
            const r = await fetch('https://nichijou.cn/chat_room_server/get_hall_info');
            return ((await r.json()).data || {}).roomList || [];
        }""")
        cands = [r for r in rooms
                 if r.get("roomType") != "lottery"
                 and not r.get("hasPassword")
                 and (r.get("userCurrent") or 0) <= 3
                 and (r.get("userLimit") or 99) > (r.get("userCurrent") or 0)]
        if cands:
            cands.sort(key=lambda r: r.get("userCurrent") or 0)
            c = cands[0]
            return c.get("title"), c.get("id")
    except Exception:
        pass
    return "東雲研究所", 1


async def wait_connected(page, timeout=25):
    """登录框消失≠WS已连上: 等 __socks 出现活 socket(hello/connectSuccess 完成再+2s)"""
    for _ in range(timeout * 2):
        try:
            n = await page.evaluate(
                "() => (window.__socks || []).filter(w => w.readyState === 1).length")
        except Exception:
            n = 0
        if n:
            await asyncio.sleep(2)   # 缓冲: 等 connectSuccess/syncHallInfo 到齐
            return True
        await asyncio.sleep(0.5)
    return False


async def ws_send(page, obj):
    """复用 app 活 socket 发帧(服务端 isCompress=True, gzip 优先)"""
    return await page.evaluate("""async (s) => {
        const n = (window.__socks || []).filter(w => w.readyState === 1).length;
        if (!n) return 0;
        try { return await window.__sendComp(s, 'gzip'); }
        catch (e) { return window.__sendRaw(s); }
    }""", json.dumps(obj, ensure_ascii=False))


async def enter_room_chain(page, room_id, tries=3, frames=None):
    """活 socket 直发 tryEnterRoom→enterRoom, SPA 原地切房, 等聊天框出现"""
    if not await wait_connected(page):
        print(f"    [diag] 25s 内 socket 未出现", flush=True)
        return False
    for _ in range(tries):
        socks = await page.evaluate(
            "() => (window.__socks || []).filter(w => w.readyState === 1).length")
        if not socks:
            await asyncio.sleep(1.5)
            continue
        await ws_send(page, {"cmd": "tryEnterRoom", "id": room_id, "content": ""})
        await asyncio.sleep(1.2)
        await ws_send(page, {"cmd": "enterRoom", "id": room_id})
        try:
            await page.wait_for_selector("textarea.rc-textarea", timeout=12000)
            await clear_all(page)
            await asyncio.sleep(0.5)
            return True
        except Exception:
            if frames is not None:
                print(f"    [diag] 尝试后帧尾: {frames[-10:]}", flush=True)
            await asyncio.sleep(1.5)
    try:
        socks = await page.evaluate("() => (window.__socks||[]).map(w=>w.readyState)")
        print(f"    [diag] 全败: socks={socks} url={page.url[:70]}", flush=True)
        DBG.mkdir(exist_ok=True)
        await page.screenshot(path=str(DBG / f"regfail_{int(time.time())}.png"))
    except Exception:
        pass
    return False


async def enter_room(page, room_id, frames=None):
    """进房: 直发链路优先, URL 直进兜底; 等到聊天框才算成功"""
    if await enter_room_chain(page, room_id, frames=frames):
        return True
    try:
        await page.goto(f"https://nichijou.cn/hall?roomId={room_id}",
                        timeout=45000, wait_until="domcontentloaded")
    except Exception:
        pass
    try:
        await page.wait_for_selector("textarea.rc-textarea", timeout=14000)
        await clear_all(page)
        await asyncio.sleep(0.6)
        return True
    except Exception:
        return False


async def guest_login(page, nick):
    """游客登录, 头像被占自动回退。成功返回 True"""
    alts = await page.evaluate(
        """() => [...new Set([...document.querySelectorAll('.avatarBoxImg')]
             .map(e => e.alt))].filter(a => a && a !== '8')""")
    if not alts:
        return False
    order = (["32"] if "32" in alts else []) + [a for a in alts if a != "32"]
    for alt in order[:6]:
        await page.evaluate(
            """(a) => { const i = document.querySelector(`.avatarBoxImg[alt="${a}"]`);
                 i && i.click(); }""", alt)
        try:
            await page.wait_for_selector(".loginBoxNickInput", timeout=6000)
        except Exception:
            continue
        await page.evaluate("""(nick) => {
            const input = document.querySelector('.loginBoxNickInput');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, nick);
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }""", nick)
        await asyncio.sleep(0.6)
        await page.evaluate(
            "() => { const b = document.querySelector('.loginBoxBtnEnter:not([disabled])');"
            " if (b) b.click(); }")
        for _ in range(8):
            await asyncio.sleep(0.7)
            if not await page.evaluate("() => !!document.querySelector('.loginBoxCard')"):
                return True
        await clear_all(page)   # 头像被占等提示 → 换下一个
    return False


async def back_to_hall(page):
    await clear_all(page)
    await asyncio.sleep(0.4)
    await page.evaluate("() => { const b = document.querySelector('#btnJ'); if (b) b.click(); }")
    await asyncio.sleep(1.4)
    await page.evaluate(
        "() => { const b = document.querySelector('.modalBtn.comBtn.btnTypeDanger');"
        " if (b) b.click(); }")
    await asyncio.sleep(1.8)
    await clear_all(page)
    await asyncio.sleep(0.8)


async def send_msgs(page, count):
    """拟人化节奏: 慢打字 + 2.5-6s 随机间隔, 避免触发禁言/降权"""
    sent = 0
    for _ in range(count):
        try:
            await page.evaluate(
                "() => document.querySelector('textarea.rc-textarea').focus()")
            await asyncio.sleep(0.05)
            await page.keyboard.type(random.choice(MSG_POOL),
                                     delay=random.randint(60, 150))
            await page.keyboard.press("Enter")
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(random.uniform(2.5, 6.0))
    return sent


def _port_alive(port, timeout=8):
    """curl 探测端口是否可用, 返回出口IP或None"""
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "--max-time", str(timeout),
             "--proxy", f"socks5://127.0.0.1:{port}", "https://api.ipify.org"],
            capture_output=True, text=True, timeout=timeout + 5)
        ip = r.stdout.strip()
        return ip if ip and ip.count(".") == 3 else None
    except Exception:
        return None


async def process_account(p, nick, proxy, idx):
    tag = f"[{idx+1}/{len(NEW_ACCOUNTS)}] {nick}"
    print(f"\n===== {tag} via {proxy} =====", flush=True)
    res = {"nick": nick, "proxy": proxy, "status": "start"}
    # ⚠️ 必须用 launch 级代理: chromium 对 context 级 SOCKS 的 WS 支持不可靠
    browser = await p.chromium.launch(
        headless=True, proxy={"server": proxy} if proxy else None,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 720}, user_agent=UA, locale="zh-CN")
    await ctx.add_init_script(HOOK_JS)
    page = await ctx.new_page()
    frames = []

    def _on_ws(ws):
        def _recv(pl):
            try:
                k, o = decode_ws_frame(pl)
                frames.append(("↓", str(o.get("event") if isinstance(o, dict) else k)[:40]))
            except Exception:
                frames.append(("↓", "<bin>"))

        def _sent(pl):
            try:
                k, o = decode_ws_frame(pl)
                frames.append(("↑", str(o.get("cmd") if isinstance(o, dict) else k)[:40]))
            except Exception:
                frames.append(("↑", "<bin>"))
        ws.on("framereceived", _recv)
        ws.on("framesent", _sent)
    page.on("websocket", _on_ws)
    try:
        await page.goto("https://nichijou.cn/hall", timeout=60000)
        await page.wait_for_selector(".avatarBoxImg", timeout=25000)
        await asyncio.sleep(1.5)
        if not await guest_login(page, nick):
            res["status"] = "login_fail"
            return res
        await asyncio.sleep(2)
        my_nick = await page.evaluate(
            "() => { const m = document.cookie.match(/nick=([^;]+)/);"
            " return m ? decodeURIComponent(m[1]) : ''; }")
        sun0 = await get_sunshine(page, my_nick)
        print(f"  游客登录成功 nick={my_nick} 阳光={sun0}", flush=True)
        res["guest_nick"] = my_nick
        res["sunshine"] = sun0

        room_title, room_id = await pick_room(page)
        print(f"  刷阳光 → {room_title}#{room_id}", flush=True)
        total, rounds, fails = 0, 0, 0
        while sun0 < SUN_TARGET and rounds < 40:
            if not await enter_room(page, room_id, frames=frames):
                fails += 1
                print(f"    进房无聊天框({fails}/4), 重试", flush=True)
                if fails >= 4:
                    res["status"] = "no_textarea"
                    return res
                await asyncio.sleep(2)
                continue
            fails = 0
            total += await send_msgs(page, 5)
            rounds += 1
            sun0 = await get_sunshine(page, my_nick)
            print(f"    round{rounds}: sent={total} sun={sun0}", flush=True)
            if sun0 < SUN_TARGET:
                await asyncio.sleep(random.uniform(8, 15))
        res["sunshine"] = sun0
        res["msgs"] = total
        if sun0 < 100:
            res["status"] = "insufficient_sunshine"
            return res

        # 注册: URL 直进房间发 /password_
        if not await enter_room(page, room_id, frames=frames):
            res["status"] = "no_textarea"
            return res
        await clear_all(page)
        await asyncio.sleep(1)
        ta = await page.query_selector("textarea.rc-textarea")
        if not ta:
            res["status"] = "no_textarea"
            return res
        await page.evaluate(
            "() => document.querySelector('textarea.rc-textarea').focus()")
        await asyncio.sleep(0.3)
        await page.keyboard.type(f"/password_{PASSWORD}", delay=random.randint(50, 110))
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        # 轮询捕捉回应(最多 12s): 服务端提示 / 阳光变化
        msgs, sun_after = [], sun0
        for _ in range(12):
            await asyncio.sleep(1)
            msgs = await page.evaluate(
                "() => Array.from(document.querySelectorAll('.ant-message-notice'))"
                ".map(m => m.textContent)")
            sun_after = await get_sunshine(page, my_nick)
            if msgs or sun_after < sun0:
                break
        print(f"  注册回应: {msgs} (sun {sun0}→{sun_after})", flush=True)
        res["reg_msgs"] = [m[:60] for m in msgs]
        sun_after = await get_sunshine(page, my_nick)
        res["sun_after"] = sun_after
        if any("成功" in m for m in msgs):
            res["status"] = "success"
        elif any("已注册" in m for m in msgs):
            res["status"] = "already"
        elif sun_after < sun0:
            res["status"] = "success"   # 阳光被扣 = 注册成功
        else:
            res["status"] = "unknown"
        return res
    except Exception as e:
        res["status"] = "error"
        res["error"] = str(e)[:160]
        return res
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass


async def main():
    fleet = load_fleet()
    print(f"舰队节点: {len(fleet)} 个可用", flush=True)
    nicks = list(NEW_ACCOUNTS)
    prev = []
    if "--retry-failed" in sys.argv and RESULT_FILE.exists():
        prev = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        nicks = [r["nick"] for r in prev
                 if r.get("status") not in ("success", "already")]
        print(f"重试失败账号: {nicks}", flush=True)
    results = list(prev)
    used = {r.get("proxy") for r in results if r.get("proxy")}
    # 并发预检端口存活(死节点直接跳过, 避免每个号白耗 3-4 分钟)
    cands = [x for x in fleet if f"socks5://127.0.0.1:{x['port']}" not in used]
    print(f"预检 {len(cands)} 个候选端口…", flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        alive = [x for x in ex.map(
            lambda x: x if _port_alive(x["port"]) else None, cands) if x]
    print(f"存活 {len(alive)}/{len(cands)}", flush=True)
    if not alive:
        alive = fleet
    async with async_playwright() as p:
        for idx, nick in enumerate(nicks):
            m = alive[idx % len(alive)]
            proxy = f"socks5://127.0.0.1:{m['port']}"
            print(f"  使用端口 {m['port']} ({m.get('name','')})", flush=True)
            try:
                r = await process_account(p, nick, proxy, idx)
            except Exception as e:
                r = {"nick": nick, "status": "error", "error": str(e)[:160]}
            r["node"] = m.get("name", "")
            results = [x for x in results if x.get("nick") != nick] + [r]
            print(f"  >>> {r['status']}", flush=True)
            RESULT_FILE.write_text(
                json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = sum(1 for r in results if r.get("status") in ("success", "already"))
    print(f"\n注册成功: {ok}/{len(results)} → {RESULT_FILE.name}", flush=True)
    for r in results:
        print(f"  {r['nick']:<8} {r.get('status','?'):<22} sun {r.get('sunshine','?')}→{r.get('sun_after','?')}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
