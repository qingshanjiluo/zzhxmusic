#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐 Token 获取工具

启动有头浏览器，打开 music.163.com 登录页，用户手动登录后自动提取 cookies，
输出为 NETEASE_COOKIES 可直接使用的 JSON 字符串。

支持三种模式（按优先级自动选择）：
  1. selenium + Chrome/Edge（自动下载 webdriver）
  2. 手动登录 + 浏览器控制台提取（纯 Python 交互）
  3. 输出脚本引导

用法:
  python tools/get_netease_token.py
  python tools/get_netease_token.py --output ./netease_cookies.json
  python tools/get_netease_token.py --manual    # 强制使用手动模式
  python tools/get_netease_token.py --browser edge   # 指定 Edge 浏览器

依赖（可选）:
  pip install selenium webdriver-manager   # 自动模式需要
"""

import sys
import os
import json
import time
import re
import argparse
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path


# ============================================================
# 常量
# ============================================================
NETEASE_URL = 'https://music.163.com'
COOKIE_DOMAIN = 'music.163.com'
REQUIRED_COOKIES = ['MUSIC_U', '__csrf']
OUTPUT_FILENAME = 'netease_cookies.json'


# ============================================================
# 模式1: Selenium 自动模式
# ============================================================
def _check_selenium() -> bool:
    """检测 selenium 是否可用"""
    try:
        import selenium
        return True
    except ImportError:
        return False


def _try_find_chrome() -> str:
    """在 Windows 上查找 Chrome 可执行文件路径"""
    import winreg
    possible_paths = [
        os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]
    for path in possible_paths:
        expanded = os.path.expandvars(path)
        if os.path.isfile(expanded):
            return expanded
    # 尝试从注册表读取
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe')
        value, _ = winreg.QueryValueEx(key, '')
        winreg.CloseKey(key)
        if os.path.isfile(value):
            return value
    except (OSError, FileNotFoundError):
        pass
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe')
        value, _ = winreg.QueryValueEx(key, '')
        winreg.CloseKey(key)
        if os.path.isfile(value):
            return value
    except (OSError, FileNotFoundError):
        pass
    return ''


def _try_find_edge() -> str:
    """在 Windows 上查找 Edge 可执行文件路径"""
    possible_paths = [
        os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
        os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for path in possible_paths:
        expanded = os.path.expandvars(path)
        if os.path.isfile(expanded):
            return expanded
    return ''


def fetch_with_selenium(browser_type: str = 'auto', output_path: str = '') -> bool:
    """
    使用 selenium 打开有头浏览器，用户登录后自动提取 cookies
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # ---- 确定浏览器 ----
    browser_type = browser_type.lower()
    if browser_type == 'auto' or browser_type == 'chrome':
        chrome_path = _try_find_chrome()
        edge_path = _try_find_edge()
        if chrome_path:
            browser_type = 'chrome'
        elif edge_path:
            browser_type = 'edge'
        else:
            print('[!] 未找到 Chrome 或 Edge，尝试使用 selenium 默认路径...')
            browser_type = 'chrome'
    elif browser_type == 'edge':
        if not _try_find_edge():
            print('[!] 未找到 Edge，尝试使用 selenium 默认路径...')

    # ---- 配置浏览器选项 ----
    print(f'\n[*] 使用浏览器: {browser_type}')
    print('[*] 正在启动浏览器（请不要关闭此窗口）...')

    if browser_type == 'edge':
        options = EdgeOptions()
        options.use_chromium = True
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        prefs = {
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False,
        }
        options.add_experimental_option('prefs', prefs)
        options.add_argument('--disable-blink-features=AutomationControlled')
        driver = webdriver.Edge(options=options)
    else:
        options = ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        prefs = {
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False,
        }
        options.add_experimental_option('prefs', prefs)
        options.add_argument('--disable-blink-features=AutomationControlled')
        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            # 尝试 webdriver-manager 自动下载
            try:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            except ImportError:
                print('[!] webdriver-manager 未安装，尝试默认 ChromeDriver...')
                raise

    # ---- 打开网易云音乐 ----
    driver.get(NETEASE_URL)
    print(f'\n[*] 已打开 {NETEASE_URL}')
    print('[*] 请在浏览器中完成登录（支持二维码/手机号/邮箱登录）')
    print('[*] 检测到登录成功后，将自动提取 cookies...')
    print('[*] 按 Ctrl+C 可随时中断\n')

    # ---- 等待用户登录 ----
    logged_in = False
    cookies_before = set()
    try:
        # 先获取初始 cookies（未登录状态）
        for c in driver.get_cookies():
            if c.get('domain', '').endswith(COOKIE_DOMAIN):
                cookies_before.add(c['name'])
    except Exception:
        pass

    # 轮询检测登录状态
    max_wait_seconds = 600  # 最多等 10 分钟
    poll_interval = 2       # 每 2 秒检测一次
    start_time = time.time()
    detected_cookies = {}

    try:
        while time.time() - start_time < max_wait_seconds:
            time.sleep(poll_interval)
            all_cookies = driver.get_cookies()
            current_names = set()
            for c in all_cookies:
                if c.get('domain', '').endswith(COOKIE_DOMAIN):
                    current_names.add(c['name'])

            # 检测到新的关键 cookie => 已登录
            new_cookies = current_names - cookies_before
            if REQUIRED_COOKIES[0] in current_names or REQUIRED_COOKIES[1] in current_names:
                logged_in = True
                # 提取所有 domain 匹配的 cookie
                for c in all_cookies:
                    if c.get('domain', '').endswith(COOKIE_DOMAIN):
                        detected_cookies[c['name']] = c['value']
                print(f'\n[✓] 检测到登录成功！关键 cookie 存在: '
                      f'MUSIC_U={REQUIRED_COOKIES[0] in current_names}, '
                      f'__csrf={REQUIRED_COOKIES[1] in current_names}')
                break

            # 进度提示
            elapsed = int(time.time() - start_time)
            if elapsed > 0 and elapsed % 30 == 0:
                print(f'    ...等待登录中，已等待 {elapsed} 秒...')

    except KeyboardInterrupt:
        print('\n\n[!] 用户中断')
        driver.quit()
        return False
    except Exception as e:
        print(f'\n[!] 提取 cookies 时出错: {e}')
        driver.quit()
        return False

    if not logged_in or not detected_cookies:
        print('\n[!] 未检测到登录，请重试')
        driver.quit()
        return False

    # ---- 格式化输出 cookies ----
    cookies_dict = detected_cookies
    output = _format_output(cookies_dict, output_path)

    print(f'\n[*] 共提取 {len(cookies_dict)} 个 cookie 字段')
    print(f'[*] 关键字段: MUSIC_U={"已获取 ✓" if "MUSIC_U" in cookies_dict else "缺失 ✗"}')
    print(f'                __csrf={"已获取 ✓" if "__csrf" in cookies_dict else "缺失 ✗"}')

    if output:
        print(f'\n[✓] 已将 cookies 保存至: {output}')

    driver.quit()
    return True


# ============================================================
# 模式2: 纯交互手动模式
# ============================================================
def fetch_manual(output_path: str = '') -> bool:
    """
    打开浏览器后，指导用户在开发者工具中粘贴代码提取 cookies
    """
    print(f'\n{"="*60}')
    print('  手动获取 Netease Cookies 模式')
    print(f'{"="*60}\n')

    print('步骤 1: 打开浏览器，访问 https://music.163.com')
    print('步骤 2: 完成登录')
    print('步骤 3: 按 F12 打开开发者工具 → Console（控制台）')
    print('步骤 4: 粘贴以下代码并回车:\n')
    print('=' * 60)
    js_code = '''(function() {
    const cookies = document.cookie.split('; ');
    const result = {};
    cookies.forEach(c => {
        const [k, ...v] = c.split('=');
        result[k] = v.join('=');
    });
    // 同时获取 localStorage 中的 MUSIC_U（如果有）
    try {
        const mu = localStorage.getItem('MUSIC_U');
        if (mu) result['MUSIC_U'] = mu;
    } catch(e) {}
    const json = JSON.stringify(result, null, 2);
    console.log(json);
    /* 尝试自动复制到剪贴板 */
    try {
        const el = document.createElement('textarea');
        el.value = json;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        console.log('✓ 已复制到剪贴板！');
    } catch(e) { /* ignore */ }
    return json;
})()'''
    print(js_code)
    print('=' * 60)
    print()
    print('步骤 5: 将输出的 JSON 字符串复制保存')

    # 询问是否已经拿到 cookies
    resp = input('\n[?] 已经拿到 cookies JSON 了吗？(y/N): ').strip().lower()
    if resp == 'y':
        raw = input('[?] 粘贴 JSON 字符串: ').strip()
        try:
            cookies_dict = json.loads(raw)
            output = _format_output(cookies_dict, output_path)
            if output:
                print(f'\n[✓] 已保存至: {output}')
            return True
        except json.JSONDecodeError as e:
            print(f'[!] JSON 解析失败: {e}')
            # fallback: 手动输入
            print('[!] 请手动输入关键 cookie 值:')
            musit_u = input('  MUSIC_U: ').strip()
            csrf = input('  __csrf: ').strip()
        return False

    # 自动打开浏览器
    print('\n[*] 正在为你打开浏览器...')
    webbrowser.open(NETEASE_URL)

    # 生成输出脚本文件
    script_path = os.path.join(os.path.dirname(output_path or '.'), 'extract_cookies.js')
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(js_code)
    print(f'[*] JS 提取脚本已保存至: {os.path.abspath(script_path)}')
    print('[!] 登录后打开 Console，粘贴该文件内容即可提取')

    return False


# ============================================================
# 模式3: 命令行交互提取
# ============================================================
def fetch_interactive(output_path: str = '') -> bool:
    """
    交互式手动输入各种 cookie
    """
    print(f'\n{"="*60}')
    print('  手动输入 Cookie 模式')
    print(f'{"="*60}\n')
    print('请从浏览器开发者工具中复制以下 cookie 值')
    print('(Application → Cookies → music.163.com)\n')

    cookies_dict = {}
    print('输入 cookie 名和值（直接回车结束输入）:')
    while True:
        name = input('  Cookie 名: ').strip()
        if not name:
            break
        value = input(f'  Cookie 值 ({name}): ').strip()
        if value:
            cookies_dict[name] = value
            print(f'    ✓ {name} 已记录')
        else:
            print('    跳过（值为空）')
        print()

    if not cookies_dict:
        print('[!] 未输入任何 cookie')
        return False

    # 检查关键字段
    has_music_u = 'MUSIC_U' in cookies_dict
    has_csrf = '__csrf' in cookies_dict

    print(f'\n[*] 共输入 {len(cookies_dict)} 个 cookie')
    print(f'[*] MUSIC_U: {"✓" if has_music_u else "✗（缺失，下载可能仍会 403）"}')
    print(f'[*] __csrf: {"✓" if has_csrf else "✗（可选）"}')

    output = _format_output(cookies_dict, output_path)
    if output:
        print(f'\n[✓] 已保存至: {output}')
    return True


# ============================================================
# 工具函数
# ============================================================
def _format_output(cookies_dict: dict, output_path: str = '') -> str:
    """将 cookies 字典格式化为 JSON 输出"""
    if not cookies_dict:
        return ''

    json_str = json.dumps(cookies_dict, ensure_ascii=False, indent=2)

    print(f'\n{"="*60}')
    print('  提取结果（可直接用作 NETEASE_COOKIES）')
    print(f'{"="*60}\n')
    print(json_str)
    print()

    # 输出单行版本（适合 CLI 参数）
    oneline = json.dumps(cookies_dict, ensure_ascii=False, separators=(',', ':'))
    print(f'  单行版（环境变量用）:')
    print(f'  {oneline[:120]}{"..." if len(oneline) > 120 else ""}')
    print()

    # 保存到文件
    if not output_path:
        output_path = OUTPUT_FILENAME
    output_path = os.path.abspath(output_path)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(cookies_dict, f, ensure_ascii=False, indent=2)
        print(f'  ✓ 已保存至: {output_path}')
        print(f'  ✓ 文件大小: {os.path.getsize(output_path)} 字节')

        # 显示下一步指引
        print(f'\n  下一步:')
        print(f'  1. 打开文件复制完整 JSON')
        print(f'  2. 在 GitHub 仓库 Settings → Secrets → Actions 添加')
        print(f'     Secret 名: NETEASE_COOKIES')
        print(f'     Secret 值: 粘贴 JSON 字符串')
        return output_path
    except Exception as e:
        print(f'  [!] 保存失败: {e}')
        # 复制到剪贴板（尝试）
        try:
            import pyperclip
            pyperclip.copy(json_str)
            print('  ✓ 已复制到剪贴板')
        except ImportError:
            print('  [!] 请手动复制以上 JSON')
        return ''


def _print_banner():
    """打印 Banner"""
    print(f'''
╔══════════════════════════════════════════╗
║     网易云音乐 Token 获取工具            ║
║     Netease Music Cookie Extractor       ║
╚══════════════════════════════════════════╝

本工具将帮助你获取网易云音乐的登录凭证（cookies），
用于在 CI 环境（GitHub Actions）中绕过 403 限流。
''')


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='网易云音乐 Token 获取工具 - 提取登录 cookies')
    parser.add_argument('--output', '-o', type=str, default='',
                        help=f'输出文件路径（默认当前目录下的 {OUTPUT_FILENAME}）')
    parser.add_argument('--manual', '-m', action='store_true',
                        help='强制使用手动模式（不启动 selenium）')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='手工逐个输入 cookie 值')
    parser.add_argument('--browser', '-b', type=str, default='auto',
                        choices=['auto', 'chrome', 'edge'],
                        help='指定浏览器类型（默认 auto）')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='静默输出（仅打印 JSON）')
    args = parser.parse_args()

    _print_banner()

    output_path = args.output
    success = False

    # ---- 模式选择 ----
    if args.interactive:
        print('[模式] 手工输入模式\n')
        success = fetch_interactive(output_path)
    elif args.manual:
        print('[模式] 纯手动引导模式\n')
        success = fetch_manual(output_path)
    elif _check_selenium():
        print('[模式] Selenium 自动化模式\n')
        success = fetch_with_selenium(
            browser_type=args.browser,
            output_path=output_path,
        )
    else:
        print('[!] selenium 未安装，自动切换到手动引导模式')
        print('    (安装依赖: pip install selenium webdriver-manager)\n')
        success = fetch_manual(output_path)

    # ---- 结果 ----
    if success:
        print(f'\n{"="*60}')
        print('  ✅ 完成！请将上述 JSON 设置为 GitHub Secret: NETEASE_COOKIES')
        print(f'{"="*60}\n')
        sys.exit(0)
    else:
        print(f'\n{"="*60}')
        print('  ❌ 未能获取 cookies')
        print('  建议: pip install selenium webdriver-manager 重新运行')
        print(f'{"="*60}\n')
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n[!] 用户中断')
        sys.exit(1)
    except Exception as e:
        print(f'\n[!] 错误: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
