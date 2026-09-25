#!/usr/bin/env python3
"""把今日"已发过币"的出口IP标记为刚发过(冷却中), 
让 daily_login 轮换时优先选用从未发币的新鲜IP —— 保障新账号能领到当日额度。
用法: python mark_granted_cooling.py   (在跑签到前执行)
"""
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SF = HERE / "daily_state.json"
d = json.loads(SF.read_text(encoding="utf-8"))
led = d.setdefault("_ip_ledger", {})
last = led.setdefault("last_grant", {})
grants = led.get("grants", {})
now = time.time()
marked = []
for ip in list(last):
    last[ip] = now          # 统一标记为"刚刚发过" → 30分钟冷却窗口内被跳过
    marked.append(ip)
SF.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已标记 {len(marked)} 个已发币IP为冷却(本次轮换将跳过它们)")
print("今日发币IP:", ", ".join(sorted(grants)) if grants else "(grants 为空)")
