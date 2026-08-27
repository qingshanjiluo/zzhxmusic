#!/usr/bin/env python3
"""测试完整签到流程 - 通过代理"""
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

        # 关闭通知弹窗
        print("=== 关闭通知弹窗 ===")
        await page.evaluate("""() => {
            document.querySelectorAll('button, a').forEach(el => {
                if (el.textContent.trim() === '知道了') el.click();
            });
        }""")
        await asyncio.sleep(2)

        # 查找签到相关元素
        print("=== 查找签到元素 ===")
        checkin_elements = await page.evaluate("""() => {
            const results = [];
            // 查找所有按钮和链接
            document.querySelectorAll('button, a, [class*="sign"], [class*="check"], [class*="reward"], [class*="daily"]').forEach(el => {
                const text = el.textContent.trim();
                if (text && text.length < 50) {
                    results.push({
                        tag: el.tagName,
                        text: text,
                        class: el.className.substring(0, 80),
                        id: el.id || ''
                    });
                }
            });
            return results;
        }""")
        for item in checkin_elements:
            print(f"  [{item['tag']}] {item['text'][:50]} (class={item['class'][:30]})")

        # 查找右上角头像区域
        print("=== 查找头像区域 ===")
        avatar_area = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('[class*="avatar"], [class*="Avatar"], [class*="user"], [class*="User"], [class*="info"], [class*="Info"]').forEach(el => {
                if (el.textContent.trim().length < 100) {
                    results.push({
                        tag: el.tagName,
                        text: el.textContent.trim().substring(0, 80),
                        class: el.className.substring(0, 80)
                    });
                }
            });
            return results;
        }""")
        for item in avatar_area:
            print(f"  [{item['tag']}] {item['text'][:60]} (class={item['class'][:30]})")

        await page.screenshot(path="checkin_proxy_3.png")
        print("截图: checkin_proxy_3.png")

        await browser.close()

asyncio.run(main())