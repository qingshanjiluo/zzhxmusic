#!/usr/bin/env python3
"""
nichijou.cn 抽奖币余额查询（任意房间版）
====================================================================
原理（bundle 逆向 + 实测）:
  propBag 没有 HTTP 接口，但【任何房间】的房间 WS 都能查:
  A. 抽奖房: 进房即自动 sendReq {"cmd":"getPropBag"}
     (wsConnectRoom: "lottery"===r && cmdGetLotteryState() + cmdGetPropBag())
  B. 普通房(音乐/电影/你画我猜…): 房间页「关于本站」(#btnK) 弹窗里有
     「我的道具」图标(.aboutMeRewardEntry) → onOpenPropBag → cmdGetPropBag
  服务端回帧: {"event":"syncPropBag","propBag":{"registered":true,
             "items":[{"propId":"lottery_coin","count":N}, ...]}}
  未注册(游客)账号会回 registered:false（"注册后才能使用道具功能"）
  抽奖房还额外推 syncLotteryRoomInfo(含全服奖池 coinPool)。

音乐房常年有人开着 → 白天不用等抽奖房开放即可查余额。

用法:
  python check_coins.py                      # 默认 zzhx@...，代理自动
  python check_coins.py --nick 青山寂落@Pipi20100817
  python check_coins.py --all                # 遍历 accounts.json 逐个查
  python check_coins.py --all --watch        # 失败(如全员进房受限)定时重试
  python check_coins.py --headed --no-proxy
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from daily_login import (BASE_URL, UA, decode_ws_frame, pick_proxy,  # noqa: E402
                         load_proxy_pool)

ACCOUNTS_FILE = HERE / "accounts.json"
RESULT_FILE = HERE / "coins_balance.json"

EVENT_KEYS = ("syncPropBag", "syncLotteryRoomInfo", "message", "connectSuccess",
              "tryEnterRoomResult", "syncRoomInfo", "hallUserUpdate", "syncHallInfo")
REJECT_WORDS = ("暂未开放", "休息", "关门", "已满", "进入房间失败", "密码", "禁止")

# 路径3兜底: hook WebSocket 构造器，直接经 app 的活 socket 发帧
# （大厅 React sendReq 有 isConnect 门控，偶发点了不发帧；服务端只认 socket）
HOOK_JS = """
window.__socks = [];
(() => {
  // 不替换构造器；包 prototype.send，任何 app 发出的帧都会把其实例登记进来
  const origSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function(data) {
    if (!window.__socks.includes(this)) window.__socks.push(this);
    return origSend.apply(this, arguments);
  };
})();
window.__sendRaw = (s) => {
  const o = window.__socks.filter(w => w.readyState === 1);
  o.forEach(w => w.send(s)); return o.length;
};
window.__sendComp = async (s, fmt) => {
  const cs = new CompressionStream(fmt);
  const buf = await new Response(new Blob([new TextEncoder().encode(s)])
    .stream().pipeThrough(cs)).arrayBuffer();
  const o = window.__socks.filter(w => w.readyState === 1);
  o.forEach(w => w.send(buf)); return o.length;
};
"""


async def query_one(nick_full: str, password_unused, proxy_server, headed: bool):
    from playwright.async_api import async_playwright
    out = {"nick": nick_full, "time": datetime.now().isoformat(timespec="seconds"),
           "lottery_coin": None, "items": None, "registered": None,
           "coinPool": None, "room": None, "entry_kind": None, "role_used": None,
           "status": "fail", "detail": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            proxy={"server": proxy_server} if proxy_server else None,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        try:
            ctx = await browser.new_context(viewport={"width": 1280, "height": 720},
                                            user_agent=UA, locale="zh-CN",
                                            timezone_id="Asia/Shanghai")
            await ctx.add_init_script(HOOK_JS)
            page = await ctx.new_page()
            page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

            events = []
            rawlog = []

            def on_ws(ws):
                def on_recv(payload):
                    kind, obj = decode_ws_frame(payload)
                    ev = obj.get("event") if kind == "json" else kind
                    rawlog.append("↓" + str(ev)[:40])
                    if kind == "json" and obj.get("event") in EVENT_KEYS:
                        events.append(obj)
                def on_sent(payload):
                    kind, obj = decode_ws_frame(payload)
                    cm = obj.get("cmd") if kind == "json" else "?"
                    if cm != "hb":
                        rawlog.append("↑" + str(cm)[:30])
                    if kind == "json" and obj.get("cmd") in ("tryEnterRoom", "getPropBag"):
                        events.append({"event": "_sent_" + obj["cmd"]})
                ws.on("framereceived", on_recv)
                ws.on("framesent", on_sent)
            page.on("websocket", on_ws)

            # ---------- 登录（头像被占时自动换 role 重试）----------
            # 实测: role=32 可能被他人占用(select_role status=1"正在被其他人使用")；
            # 奖励/余额跟人(nick@密码)走，role 只是本次会话头像。
            await page.goto(f"{BASE_URL}/hall", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.wait_for_selector(".avatarBoxImg", timeout=20000)
            await asyncio.sleep(1.0)
            alts = await page.evaluate("""() => [...new Set(
                [...document.querySelectorAll('.avatarBoxImg')].map(e => e.alt)
                )].filter(a => a && a !== '8' && a !== '')""")
            # 注册账号优先用32号头像(发币判定疑似与绑定头像有关)；
            # 32不在本次releaseRole或被占用时回退其他头像（14:42实测其他role可正常登录）。
            order = alts[:1] if "32" not in alts else ["32"] + [a for a in alts if a != "32"]
            logged_in = False
            for alt in order[:4]:
                print(f"    · 登录尝试 role={alt}…", flush=True)
                resp_box = {}

                async def on_resp(r):
                    if "select_role" in r.url:
                        try:
                            resp_box["body"] = await r.json()
                        except Exception:
                            pass
                page.on("response", on_resp)
                try:
                    await page.evaluate("""(alt) => {
                        const img = document.querySelector(`.avatarBoxImg[alt="${alt}"]`);
                        if (img) img.click();
                    }""", alt)
                    await page.wait_for_selector(".loginBoxNickInput", timeout=8000)
                    await page.evaluate("""(nick) => {
                        const input = document.querySelector('.loginBoxNickInput');
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(input, nick);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }""", nick_full)
                    await asyncio.sleep(0.4)
                    await page.evaluate("""() => {
                        document.querySelector('.loginBoxBtnEnter:not([disabled])').click();
                    }""")
                    await asyncio.sleep(3)
                    body = resp_box.get("body") or {}
                    if body.get("status") == 0:
                        # select_role status0 有竞态谎言 —— 以 connectSuccess 帧为准
                        t_end = asyncio.get_event_loop().time() + 8
                        got = False
                        while asyncio.get_event_loop().time() < t_end:
                            if any(e.get("event") == "connectSuccess" for e in events):
                                got = True
                                break
                            await asyncio.sleep(0.4)
                        if got:
                            logged_in = True
                            out["role_used"] = int(alt)
                            break
                        out.setdefault("role_errs", []).append(
                            f"role{alt}:WS拒绝(头像已被占/403)")
                    else:
                        out.setdefault("role_errs", []).append(
                            f"role{alt}:{body.get('msg')}")
                finally:
                    page.remove_listener("response", on_resp)
                try:  # 换头像重开
                    await page.goto(f"{BASE_URL}/hall", timeout=30000)
                    await page.wait_for_selector(".avatarBoxImg", timeout=15000)
                    await asyncio.sleep(1.2)
                except Exception:
                    break
            await asyncio.sleep(2)  # 等 WS connectSuccess
            if not logged_in:
                errs = out.get("role_errs") or []
                if any(("被其他人使用" in e or "WS拒绝" in e) for e in errs):
                    out["status"] = "avatar_busy"
                    out["detail"] = f"32号头像被占用: {errs}"
                else:
                    out["detail"] = f"登录失败(头像全被拒): {errs}"
                return out

            async def dsend(obj, mode):
                s = json.dumps(obj, ensure_ascii=False)
                try:
                    if mode == "plain":
                        return await page.evaluate("(x)=>window.__sendRaw(x)", s)
                    return await page.evaluate("([x,f])=>window.__sendComp(x,f)",
                                               [s, mode])
                except Exception:
                    return 0

            async def wait_bag(rounds=5):
                for _ in range(rounds):
                    await asyncio.sleep(0.6)
                    got = next((e for e in reversed(events)
                                if e.get("event") == "syncPropBag"), None)
                    if got:
                        return got
                return None

            # ---------- 大厅直发 getPropBag 捷径（不等进房；服务端可能直接认） ----------
            print("    · 大厅直发 getPropBag…", flush=True)
            print("    · __socks 状态:",
                  await page.evaluate(
                      "() => window.__socks.map(w => w.readyState)"), flush=True)
            def parse_bag(bag, res):
                pb = bag.get("propBag") or {}
                res["registered"] = pb.get("registered")
                items = pb.get("items") or []
                res["items"] = [{"propId": i.get("propId") or i.get("type"),
                                 "count": i.get("count")} for i in items]
                coin = next((i for i in items
                             if (i.get("propId") or i.get("type")) == "lottery_coin"), None)
                res["lottery_coin"] = int(coin.get("count") or 0) if coin else 0
                res["status"] = "ok"
                info = next((e for e in reversed(events)
                             if e.get("event") == "syncLotteryRoomInfo"), None)
                if info:
                    res["coinPool"] = (info.get("lotteryRoomInfo") or {}).get("coinPool")
                return res

            bag_h = None
            tried = []
            free_rooms = []
            try:
                hall0 = await page.evaluate("""async () => {
                    const r = await Promise.race([
                        fetch('https://nichijou.cn/chat_room_server/get_hall_info'),
                        new Promise((_, j) => setTimeout(() => j('t'), 12000))]);
                    return (await r.json()).data?.roomList || [];
                }""")
                free_rooms = [x for x in hall0 if not x.get("hasPassword")
                              and (x.get("userLimit") or 99) > (x.get("userCurrent") or 0)]
                free_rooms.sort(key=lambda x: -(x.get("userCurrent") or 0))
            except Exception:
                pass

            async def wait_ev(name, iters, base=0):
                for _ in range(iters):
                    await asyncio.sleep(0.5)
                    got = next((e for e in reversed(events[base:])
                                if e.get("event") == name), None)
                    if got:
                        return got
                return None

            for room0 in (free_rooms[:3] or [{"id": 4, "title": "经典粤语"},
                                             {"id": 13, "title": "摸鱼者联盟"}]):
                if bag_h:
                    break
                for m0 in ("gzip", "deflate"):
                    if bag_h:
                        break
                    if not await dsend({"cmd": "tryEnterRoom", "id": room0["id"],
                                        "content": ""}, m0):
                        continue
                    ter = await wait_ev("tryEnterRoomResult", 6, len(events) - 1)
                    tried.append(f"enter {room0.get('title')}#{room0.get('id')}/{m0}:"
                                 f"{ter.get('isOk') if ter else '无应答'}")
                    if ter and not ter.get("isOk"):
                        break  # 服务端明拒, 换下一间房
                    await dsend({"cmd": "enterRoom", "id": room0["id"]}, m0)
                    await asyncio.sleep(1.0)
                    await dsend({"cmd": "getPropBag"}, m0)
                    bag_h = await wait_bag(6)
                    tried.append(f"bag/{m0}:{'✅' if bag_h else 'silent'}")
            out["direct_log"] = ["大厅链路: " + " | ".join(tried)]
            print("    · " + out["direct_log"][0], flush=True)
            if bag_h:
                out["entry_kind"] = "direct-ws-chain"
                out["room"] = {"id": room0.get("id"), "title": room0.get("title"),
                               "type": room0.get("roomType")}
                return parse_bag(bag_h, out)

            async def back_to_hall():
                await page.goto(f"{BASE_URL}/hall", timeout=30000)
                await page.wait_for_selector(".hallRoomItemCard", timeout=15000)
                await asyncio.sleep(1.5)

            async def dismiss_notice():
                await page.evaluate("""() => {
                    document.querySelectorAll('button').forEach(b => {
                        if ((b.textContent||'').trim() === '知道了') b.click();
                    });
                }""")

            async def toasts():
                return await page.evaluate("""() => Array.from(document.querySelectorAll(
                    '.ant-message-notice-content')).map(e => e.textContent.trim())""")

            # ---------- 房间候选: 抽奖房优先, 再取人多的普通房 ----------
            await dismiss_notice()
            await asyncio.sleep(1.0)
            hall = await page.evaluate("""async () => {
                const t = new Promise((_, rej) => setTimeout(() => rej('t'), 15000));
                const r = await Promise.race([
                    fetch('https://nichijou.cn/chat_room_server/get_hall_info'), t]);
                return await Promise.race([r.json(), t]);
            }""")
            if not isinstance(hall, dict):
                out["detail"] = "get_hall_info 获取失败"
                return out
            rooms = (hall.get("data") or {}).get("roomList") or []
            # 优先用 syncHallInfo 帧里的房间表（含 hasPassword 等实时字段）
            si = next((e for e in reversed(events)
                       if e.get("event") == "syncHallInfo"), None)
            if si:
                rooms = si.get("roomList") or (si.get("hallInfo") or {}).get("roomList") or rooms
            out["room_fields"] = sorted(rooms[0].keys())[:14] if rooms else []
            lotteries = [rm for rm in rooms if rm.get("roomType") == "lottery"
                         and not rm.get("hasPassword")]
            others = [rm for rm in rooms if rm.get("roomType") != "lottery"
                      and not rm.get("hasPassword")  # 密码房: 点卡只弹密码框,不发帧!
                      and (rm.get("userLimit") or 0) > (rm.get("userCurrent") or 0)]
            others.sort(key=lambda rm: -(rm.get("userCurrent") or 0))
            cands = lotteries + others[:2]
            if not cands:
                out["detail"] = "没有可进入的房间候选"
                return out

            bag = None
            last_err = ""

            async def wait_room(iters):
                """轮询进房结果: 服务端拒帧/toast 或 房间UI出现。返回(kind,t_seen,newr)"""
                kind, t_seen, newr = None, [], []
                for _ in range(iters):
                    await asyncio.sleep(0.5)
                    await dismiss_notice()
                    if await page.evaluate("""() => [...document.querySelectorAll(
                        '.ant-modal-content')].some(m => (m.textContent||'').includes('密码')
                        && getComputedStyle(m).display !== 'none')"""):
                        t_seen.append("密码房弹窗(跳过)")
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(0.5)
                        break
                    for x in await toasts():
                        if x not in t_seen:
                            t_seen.append(x)
                    newr = [e for e in events[n_enter:]
                            if e.get("event") == "tryEnterRoomResult"]
                    if newr and not newr[-1].get("isOk"):
                        break
                    if any(any(w in x for w in REJECT_WORDS) for x in t_seen):
                        break
                    if await page.query_selector(".lotteryRoomActionButtonBag"):
                        kind = "lottery"
                        break
                    if await page.query_selector("#btnK") \
                            and await page.query_selector(".rc-textarea"):
                        kind = "general"
                        break
                return kind, t_seen, newr

            for room in cands:
                print(f"    · 进房尝试: {room['title']}#{room['id']}…", flush=True)
                n_enter = sum(1 for e in events if e.get("event") == "tryEnterRoomResult")
                # 路径1: 真实鼠标点房间卡（JS 合成 click 有时不冒泡到 React；
                # 10:55 实测 UI 登录后真实点击能触发 tryEnterRoom）
                box = await page.evaluate("""(title) => {
                    const cards = [...document.querySelectorAll('.hallRoomItemCard')];
                    const card = cards.find(c => {
                        const t = c.querySelector('.hallRoomTitle');
                        return t && t.textContent.trim() === title;
                    });
                    if (!card) return null;
                    card.scrollIntoView({block: 'center'});
                    const r = card.getBoundingClientRect();
                    if (r.y < 5 || r.y > 700) return null;
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                }""", room["title"])
                if box:
                    await page.mouse.click(box["x"], box["y"])
                else:
                    await page.evaluate("""(title) => {
                        const cards = [...document.querySelectorAll('.hallRoomItemCard')];
                        const card = cards.find(c => {
                            const t = c.querySelector('.hallRoomTitle');
                            return t && t.textContent.trim() === title;
                        });
                        if (card) card.click();
                    }""", room["title"])
                kind, t_seen, newr = await wait_room(12)  # 6s
                if kind is None:
                    n_sent = sum(1 for e in events
                                 if e.get("event") == "_sent_tryEnterRoom")
                    last_err = (f"进 {room['title']}#{room['id']} "
                                f"{'被拒' if (newr and not newr[-1].get('isOk')) else '无反应'} "
                                f"(sent={n_sent}, toast={t_seen[-2:]})")
                    continue

                out["room"] = {"id": room["id"], "title": room["title"],
                               "type": room.get("roomType"),
                               "users": room.get("userCurrent")}
                out["entry_kind"] = kind

                # ---------- 触发 getPropBag ----------
                if kind == "lottery":
                    # 进房已自动 getPropBag；保险再点一次背包按钮
                    try:
                        await page.click(".lotteryRoomActionButtonBag")
                    except Exception:
                        pass
                else:
                    try:
                        await page.click("#btnK", timeout=5000)
                        await page.wait_for_selector(".aboutMeRewardEntry", timeout=8000)
                        await page.click(".aboutMeRewardEntry", timeout=5000)
                    except Exception:
                        last_err = f"{room['title']}: 关于本站/我的道具点击失败"
                        try:
                            await back_to_hall()
                        except Exception:
                            break
                        continue

                for _ in range(10):
                    await asyncio.sleep(0.7)
                    bag = next((e for e in reversed(events)
                                if e.get("event") == "syncPropBag"), None)
                    if bag:
                        break
                if bag:
                    break
                last_err = f"{room['title']}: 未收到 syncPropBag"
                try:
                    await back_to_hall()
                except Exception:
                    break

            # ---------- 路径3: WS直发兜底（dsend/wait_bag 已在前面定义） ----------
            if not bag and events:
                # app 自己收到的 syncHallInfo 里有真相: isCompress
                si_f = next((e for e in reversed(events)
                             if e.get("event") == "syncHallInfo"), None)
                is_comp = ((si_f or {}).get("hallInfo") or {}).get("isCompress")
                print(f"    · hallInfo.isCompress = {is_comp}", flush=True)
                modes = (["gzip", "deflate"] if is_comp else ["plain"]) + \
                        [m for m in ("plain", "gzip", "deflate")
                         if m not in (["gzip", "deflate"] if is_comp else ["plain"])]
                ds = []
                ds.append(f"isCompress={is_comp}")
                for m in modes[:2]:
                    if await dsend({"cmd": "getPropBag"}, m):
                        bag = await wait_bag(6)
                        ds.append(f"hall直发/{m}→" + ("bag✅" if bag else "silent"))
                        if bag:
                            out["entry_kind"] = "direct-ws-hall"
                            break
                if not bag:
                    for room in cands[:2]:
                        for m in modes[:2]:
                            n = await dsend({"cmd": "tryEnterRoom",
                                             "id": room["id"], "content": ""}, m)
                            await asyncio.sleep(1.8)
                            await dsend({"cmd": "getPropBag"}, m)
                            bag = await wait_bag(4)
                            ds.append(f"{room['title']}#{room['id']}/{m}:n={n}"
                                      + ("→bag" if bag else "→silent"))
                            if bag:
                                out["entry_kind"] = f"direct-ws-{m}"
                                out["room"] = {"id": room["id"],
                                               "title": room["title"]}
                                break
                        if bag:
                            break
                out["direct_log"] = ds[:8]

            if not bag:
                if last_err and any(w in last_err for w in ("暂未开放", "休息", "关门")):
                    out["status"] = "room_closed"
                out["detail"] = (last_err or "全部候选房间失败") + \
                    f" | 原始帧尾:{rawlog[-10:]}"
                return out

            # ---------- 解析 ----------
            return parse_bag(bag, out)
        finally:
            await browser.close()
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nick", default="zzhx@Pipi20100817")
    ap.add_argument("--all", action="store_true", help="遍历 accounts.json 全部账号")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--watch", action="store_true",
                    help="房间不可用时持续重试（默认每5分钟，最多3小时）")
    ap.add_argument("--interval-min", type=int, default=5)
    ap.add_argument("--max-wait-min", type=int, default=180)
    args = ap.parse_args()

    pool = load_proxy_pool() or [pick_proxy(True)] or [None]
    if args.no_proxy:
        pool = [None]

    if args.all:
        accounts = [a["nick"] for a in json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))]
    else:
        accounts = [args.nick]

    final_by_nick = {}
    t_wait = 0.0
    while True:
        todo = [n for n in accounts if n not in final_by_nick
                or final_by_nick[n]["status"] not in ("ok", "fail")]
        any_retryable = False
        for i, nick in enumerate(todo, 1):
            proxy = pool[(i - 1) % len(pool)]
            print(f"\n[{i}/{len(todo)}] {nick.split('@')[0]}  (via {proxy or '直连'})",
                  flush=True)
            try:
                r = await asyncio.wait_for(
                    query_one(nick, None, proxy, args.headed), timeout=300)
            except Exception as e:
                r = {"nick": nick, "time": datetime.now().isoformat(timespec="seconds"),
                     "lottery_coin": None, "items": None, "registered": None,
                     "coinPool": None, "room": None, "status": "error",
                     "detail": f"异常/超时: {str(e)[:150]}"}
            final_by_nick[nick] = r
            icon = {"ok": "🪙", "room_closed": "🚪", "avatar_busy": "🎭",
                    "error": "⏱", "fail": "❌"}.get(r["status"], "❓")
            if r["status"] == "ok":
                _rm = r.get("room") or {}
                via = (f"{_rm.get('title')}#{_rm.get('id')}({r.get('entry_kind')})"
                       if _rm else f"{r.get('entry_kind')}")
                print(f"  {icon} 抽奖币余额 = {r['lottery_coin']}  "
                      f"(registered={r['registered']}, coinPool={r['coinPool']}, 经 {via})")
                print(f"     背包: {json.dumps(r['items'], ensure_ascii=False)[:220]}")
            else:
                print(f"  {icon} {r['detail']}")
                any_retryable = True
            if len(todo) > 1:
                await asyncio.sleep(4)
        if not (args.watch and any_retryable) or t_wait >= args.max_wait_min * 60:
            if args.watch and any_retryable:
                print(f"⏱ 等待超过 {args.max_wait_min} 分钟仍有账号未查到，放弃")
            break
        t_wait += args.interval_min * 60
        print(f"🚪 有账号未查到，{args.interval_min}分钟后重试"
              f"（已等{int(t_wait//60)}分钟/上限{args.max_wait_min}）", flush=True)
        await asyncio.sleep(args.interval_min * 60)

    results = [final_by_nick[n] for n in accounts if n in final_by_nick]
    merged = []
    if RESULT_FILE.exists():
        try:
            merged = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        except Exception:
            merged = []
    today = datetime.now().strftime("%Y-%m-%d")
    merged = [m for m in merged if not (m.get("nick") in {r["nick"] for r in results}
                                        and str(m.get("time", "")).startswith(today))]
    merged.extend(results)
    RESULT_FILE.write_text(json.dumps(merged[-200:], ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"\n已保存 -> {RESULT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
