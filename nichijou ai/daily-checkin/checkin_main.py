#!/usr/bin/env python3
"""全体账号定时签到入口（Windows 计划任务调用）。
先确保 xray 节点舰队在线（订阅→70节点→本地socks端口），再跑 daily_login 全量。
中文账号名写在本 UTF-8 源码里，规避 cmd 传参 GBK 编码坑。
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import xray_fleet
    alive = xray_fleet.ensure_fleet()
    print(f"[fleet] {len(alive)} 个节点在线")
    sys.argv = ["daily_login.py"]
except Exception as e:
    # 舰队不可用 → 回退本地代理池/直连, 保底只签主号
    print(f"[fleet] 舰队不可用({e})，回退主号模式")
    sys.argv = ["daily_login.py", "--only", "最中幻想"]

runpy.run_path(str(HERE / "daily_login.py"), run_name="__main__")
