#!/usr/bin/env python3
"""fbline 订阅 → 本地 xray 节点舰队。
- 生成 config_fleet.json: 每个节点一个本地 socks 入站(21300+i) → 对应 vless-reality 出站
- 启动/重启 xray.exe(只杀本脚本启动的实例)
- 并发健康探测每个端口(api.ipify.org) → fleet_ports.json (daily_login 读它组代理池)

用法: python xray_fleet.py [--no-spawn]   # --no-spawn 只生成配置不启动
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fetch_subs

HERE = Path(__file__).resolve().parent
XRAY = HERE / "xray" / "xray.exe"
FLEET_CFG = HERE / "xray" / "config_fleet.json"
FLEET_PORTS = HERE / "fleet_ports.json"
MARKER = "config_fleet.json"          # 用于识别本脚本的 xray 实例
PORT_BASE = 21300
HEALTH_URL = "https://api.ipify.org"
BAD_NAMES = ("剩余", "邀请", "有问题", "请关注", "官网", "到期")


def _curl_ip(port, timeout=12):
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "--max-time", str(timeout), "--connect-timeout", "6",
             "--proxy", f"socks5://127.0.0.1:{port}", HEALTH_URL],
            capture_output=True, text=True, timeout=timeout + 5)
        ip = r.stdout.strip()
        return ip if ip and ip.count(".") == 3 else None
    except Exception:
        return None


def build_config():
    nodes = fetch_subs.fetch_subscription_nodes()
    # 去重(信息行与真实节点同 host:port) + 剔除纯公告名
    seen, real = set(), []
    for n in nodes:
        key = (n["host"], n["port"])
        if key in seen:
            continue
        if any(b in n["name"] for b in BAD_NAMES) and len(real) > 0 and key in seen:
            continue
        seen.add(key)
        real.append(n)
    real = [n for n in real
            if not any(b in n["name"] for b in BAD_NAMES) or n.get("port") not in (443,)]
    # 上面 info 行(host=sg-13:443)已被去重逻辑并入真实节点, 这里再兜底:
    dedup = {}
    for n in nodes:
        dedup.setdefault((n["host"], n["port"]), n)
    real = [n for (h, p), n in dedup.items()
            if not any(b in n["name"] for b in BAD_NAMES)]
    real.sort(key=lambda n: n["name"])

    inbounds, outbounds, rules, mapping = [], [], [], []
    for i, n in enumerate(real):
        port = PORT_BASE + i
        tag_in, tag_out = f"in{i}", f"out{i}"
        inbounds.append({
            "tag": tag_in, "listen": "127.0.0.1", "port": port,
            "protocol": "socks", "settings": {"udp": False}})
        outbounds.append({
            "tag": tag_out, "protocol": "vless",
            "settings": {"vnext": [{
                "address": n["host"], "port": n["port"],
                "users": [{"id": n["uuid"], "encryption": "none",
                           "flow": n["flow"] or ""}]}]},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "serverName": n["sni"], "fingerprint": n["fp"] or "chrome",
                    "publicKey": n["pbk"], "shortId": n["sid"], "spiderX": ""}}})
        rules.append({"inboundTag": [tag_in], "outboundTag": tag_out})
        mapping.append({"port": port, "name": n["name"], "host": n["host"],
                        "node_port": n["port"]})

    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds + [{"tag": "direct", "protocol": "freedom"}],
        "routing": {"rules": rules},
    }
    FLEET_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return mapping


def kill_fleet():
    """只杀命令行含 config_fleet.json 的 xray 实例(不动用户自己的 xray)。"""
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='xray.exe'\" | "
             "Where-Object { $_.CommandLine -match 'config_fleet' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, text=True, timeout=30)
        return ps.returncode == 0
    except Exception:
        return False


def spawn():
    kill_fleet()
    time.sleep(1)
    subprocess.Popen(
        [str(XRAY), "run", "-c", str(FLEET_CFG)],
        cwd=str(XRAY.parent),
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)   # 等 xray 起来


def health_check(mapping, workers=12):
    def check(m):
        m["ip"] = _curl_ip(m["port"])
        return m
    with ThreadPoolExecutor(max_workers=workers) as ex:
        done = list(ex.map(check, mapping))
    alive = [m for m in done if m["ip"]]
    dead = [m for m in done if not m["ip"]]
    FLEET_PORTS.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return alive, dead


def ensure_fleet(force=False):
    """给 checkin_main 调: 舰队健康(≤2h)就直接用, 否则重建。返回 alive 列表。"""
    if not force and FLEET_PORTS.exists():
        age = time.time() - FLEET_PORTS.stat().st_mtime
        if age < 2 * 3600:
            data = json.loads(FLEET_PORTS.read_text(encoding="utf-8"))
            alive = [m for m in data if m.get("ip")]
            if alive:
                # 抽样3端口确认 xray 进程仍在(缓存新鲜≠进程活着)
                ok = sum(1 for m in alive[:3] if _curl_ip(m["port"], 6))
                if ok >= 2:
                    return alive
    mapping = build_config()
    spawn()
    alive, dead = health_check(mapping)
    print(f"舰队: {len(alive)} 存活 / {len(dead)} 失联 (配置 {FLEET_CFG.name})")
    return alive


if __name__ == "__main__":
    alive = ensure_fleet(force="--refresh" in sys.argv or "--no-spawn" not in sys.argv)
    print(f"\n存活 {len(alive)} 个节点(出口IP):")
    for m in alive[:30]:
        print(f"  :{m['port']:<6} {m['ip']:<16} {m['name'][:20]}")
    if len(alive) > 30:
        print(f"  … 共 {len(alive)} 个, 全表见 {FLEET_PORTS.name}")
