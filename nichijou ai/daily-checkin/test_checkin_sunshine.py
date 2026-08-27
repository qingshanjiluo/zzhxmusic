#!/usr/bin/env python3
"""测试签到 - 检查登录前后阳光变化"""
import asyncio, sys, os, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

PROXY = "socks5://127.0.0.1:10808"

async def get_sunshine(page, nick):
    """通过API获取阳光"""
    try:
        return await page.evaluate("""async (nick) => {
            const resp = await fetch('https://nichijou.cn/chat_room_server/get_hall_info');
            const data = await resp.json();
            const users = (data.data || {}).userList || [];
            for (const u of users) {
                if (u.nick === nick) return (u.extInfo || {}).power || 0;
            }
            return -1;
        }""", nick) or 0
    except:
        return -1

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": PROXY},
            args=["--no-sandbox"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        print("=== 打开页面 ===")
        await page.goto("https://nichijou.cn/hall", timeout=30000)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)

        print("=== 登录 zzhx ===")
        await page.evaluate("""() => {
            const img = document.querySelector('.avatarBoxImg[alt="32"]');
            if (img) img.click();
        }""")
        await asyncio.sleep(1)
        await page.evaluate("""() => {
            const input = document.querySelector('.loginBoxNickInput');
            if (input) {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(input, 'zzhx@Pipi20100817');
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }""")
        await asyncio.sleep(1)
        await page.evaluate("""() => {
            const btn = document.querySelector('.loginBoxBtnEnter:not([disabled])');
            if (btn) btn.click();
        }""")
        await asyncio.sleep(5)

        # 关闭弹窗
        await page.evaluate("""() => {
            document.querySelectorAll('button, a').forEach(el => {
                if (el.textContent.trim() === '知道了') el.click();
            });
        }""")
        await asyncio.sleep(2)

        # 获取登录后昵称
        login_nick = await page.evaluate("""() => {
            const m = document.cookie.match(/nick=([^;]+)/);
            return m ? decodeURIComponent(m[1]) : '';
        }""")
        print(f"登录昵称: {login_nick}")

        # 检查阳光
        sunshine = await get_sunshine(page, login_nick)
        print(f"当前阳光: {sunshine}")

        # 检查WebSocket消息
        print("=== 检查页面上的奖励/签到提示 ===")
        notices = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('[class*="message"], [class*="Message"], [class*="toast"], [class*="Toast"], [class*="notice"], [class*="Notice"], [class*="reward"], [class*="Reward"]').forEach(el => {
                const text = el.textContent.trim();
                if (text && text.length > 0 && text.length < 200) {
                    results.push(text);
                }
            });
            return results;
        }""")
        for n in notices:
            print(f"  {n}")

        await page.screenshot(path="checkin_sunshine.png")
        print("截图: checkin_sunshine.png")

        await browser.close()

asyncio.run(main())