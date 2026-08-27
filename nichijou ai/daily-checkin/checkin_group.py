#!/usr/bin/env python3
"""
nichijou.cn 每日自动签到脚本 (分组版)
根据 ACCOUNT_GROUP 环境变量签到不同账号组
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://nichijou.cn"
RESULTS_DIR = Path(__file__).parent
RESULTS_FILE = RESULTS_DIR / "checkin_results.json"
ACCOUNTS_FILE = RESULTS_DIR / "accounts.json"

# 账号分组: A=前4个, B=中间4个, C=后4个
GROUP_MAP = {
    "A": [0, 1, 2, 3],
    "B": [4, 5, 6, 7],
    "C": [8, 9, 10, 11],
}


async def login_account(page, nick):
    """登录单个账号"""
    await page.goto(f"{BASE_URL}/hall", timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(3)

    # 点击头像打开登录框
    await page.evaluate("""() => {
        const img = document.querySelector('.avatarBoxImg[alt="32"]');
        if (img) img.click();
    }""")
    await asyncio.sleep(1)

    # 输入昵称
    await page.evaluate("""(nick) => {
        const input = document.querySelector('.loginBoxNickInput');
        if (input) {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, nick);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }""", nick)
    await asyncio.sleep(1)

    # 点击登录
    await page.evaluate("""() => {
        const btn = document.querySelector('.loginBoxBtnEnter:not([disabled])');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(3)

    # 等待登录完成
    for _ in range(10):
        has_box = await page.evaluate("() => !!document.querySelector('.loginBoxCard')")
        if not has_box:
            break
        await asyncio.sleep(1)

    # 获取登录后的昵称
    login_nick = await page.evaluate("""() => {
        const m = document.cookie.match(/nick=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }""")

    return login_nick


async def checkin_account(account):
    """签到单个账号"""
    from playwright.async_api import async_playwright

    nick_full = account.get("nick", "")
    nick_part = nick_full.split("@")[0] if "@" in nick_full else nick_full

    result = {
        "nick": nick_full,
        "success": False,
        "message": "",
        "timestamp": datetime.now().isoformat(),
    }

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

            login_nick = await login_account(page, nick_part)

            if login_nick and nick_part in login_nick:
                result["success"] = True
                result["message"] = f"登录成功 (nick={login_nick})"
            else:
                result["message"] = f"登录失败 (got={login_nick})"

            await browser.close()

    except Exception as e:
        result["message"] = f"错误: {str(e)[:200]}"

    return result


async def main():
    group = os.environ.get("ACCOUNT_GROUP", "A")
    print("=" * 50)
    print("  nichijou.cn 每日自动签到")
    print(f"  分组: {group}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        all_accounts = json.load(f)

    indices = GROUP_MAP.get(group, [])
    accounts = [all_accounts[i] for i in indices if i < len(all_accounts)]

    print(f"本组账号数: {len(accounts)}")

    results = []
    for i, account in enumerate(accounts, 1):
        nick_display = account.get("nick", "?")
        print(f"\n[{i}/{len(accounts)}] {nick_display}")

        if i > 1:
            await asyncio.sleep(3)
            print(f"  延迟 3s")

        result = await checkin_account(account)
        results.append(result)

        status = "✅" if result["success"] else "❌"
        print(f"  {status} {result['message']}")

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success_count = sum(1 for r in results if r["success"])
    print(f"\n{'=' * 50}")
    print(f"  完成: {success_count}/{len(results)} 成功")
    print(f"{'=' * 50}")

    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
