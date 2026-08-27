#!/usr/bin/env python3
"""通过代理测试签到流程"""
import asyncio, sys, os, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

PROXY = "socks5://127.0.0.1:10808"

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

        # 检查弹窗
        print("=== 检查弹窗 ===")
        popups = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('[class*="modal"], [class*="Modal"], [class*="dialog"], [class*="Dialog"], [class*="popup"], [class*="Popup"], [class*="notice"], [class*="Notice"]').forEach(el => {
                const style = getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    results.push({
                        tag: el.tagName,
                        cls: el.className.substring(0, 100),
                        text: el.textContent.substring(0, 300)
                    });
                }
            });
            return results;
        }""")
        for item in popups:
            print(f"  [{item['tag']}] {item['text'][:200]}")

        await page.screenshot(path="checkin_proxy_1.png")
        print("截图1: checkin_proxy_1.png")

        # 关闭弹窗
        await page.evaluate("""() => {
            document.querySelectorAll('button, a').forEach(el => {
                const text = el.textContent.trim();
                if (['知道了', '确定', '关闭', '×', 'X'].includes(text)) {
                    el.click();
                }
            });
        }""")
        await asyncio.sleep(2)
        await page.screenshot(path="checkin_proxy_2.png")
        print("截图2: checkin_proxy_2.png")

        nick = await page.evaluate("""() => {
            const m = document.cookie.match(/nick=([^;]+)/);
            return m ? decodeURIComponent(m[1]) : '';
        }""")
        role = await page.evaluate("""() => {
            const m = document.cookie.match(/role=([^;]+)/);
            return m ? m[1] : '';
        }""")
        print(f"Login: nick={nick}, role={role}")

        await browser.close()

asyncio.run(main())