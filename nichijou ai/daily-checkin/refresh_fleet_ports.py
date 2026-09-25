#!/usr/bin/env python3
"""只做健康复检: 读现有 fleet_ports.json → 逐端口 curl 复检出口IP → 回写(刷新时间戳)。
不重建配置、不重启 xray, 因此不会打断正在使用舰队的其他任务。
用法: python refresh_fleet_ports.py
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from register_fleet import _port_alive

HERE = Path(__file__).resolve().parent
FP = HERE / "fleet_ports.json"

data = json.loads(FP.read_text(encoding="utf-8"))
print(f"复检 {len(data)} 个端口…", flush=True)


def chk(m):
    ip = _port_alive(m["port"])
    return {**m, "ip": ip}


with ThreadPoolExecutor(max_workers=16) as ex:
    out = list(ex.map(chk, data))

alive = [m for m in out if m.get("ip")]
FP.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"存活 {len(alive)}/{len(out)}, 已刷新 {FP.name}")
print("前5个:", [(m["port"], m["ip"], m["name"][:12]) for m in alive[:5]])
