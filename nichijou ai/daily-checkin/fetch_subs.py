#!/usr/bin/env python3
"""xytc 机场订阅 → vless 节点列表解析。
用法:
  python fetch_subs.py            # 打印节点概要
  python fetch_subs.py --full     # 打印完整参数
可被 daily_login 导入: fetch_subscription_nodes() -> [dict]
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

# 订阅地址含密钥, 不入库: 读本地 subs_url.txt 或环境变量 NICHIJOU_SUB_URL
_SUB_FILE = Path(__file__).resolve().parent / "subs_url.txt"
UA = "v2rayN/6.23"
CACHE = Path(__file__).resolve().parent / "subs_cache.json"


def _sub_url():
    u = os.environ.get("NICHIJOU_SUB_URL", "").strip()
    if u:
        return u
    if _SUB_FILE.exists():
        u = _SUB_FILE.read_text(encoding="utf-8").strip()
        if u:
            return u
    raise SystemExit("缺订阅地址: 写入 subs_url.txt 或设 NICHIJOU_SUB_URL")


def _http_get(url, ua=UA, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_vless(link):
    """vless://uuid@host:port?params#name -> dict"""
    assert link.startswith("vless://"), link[:40]
    body = link[len("vless://"):]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    if "/" in body:
        body = body.split("/", 1)[0] if "?" not in body else body
    # uuid@host:port?query
    q = ""
    if "?" in body:
        body, q = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    host, port = hostport.rsplit(":", 1)
    p = parse_qs(q)
    g = lambda k, d="": unquote(p.get(k, [d])[0])
    return {
        "name": unquote(frag) or f"{host}:{port}",
        "uuid": userinfo,
        "host": host,
        "port": int(port),
        "security": g("security", "tls"),
        "encryption": g("encryption", "none"),
        "net": g("type", g("network", "tcp")),
        "sni": g("sni") or host,
        "fp": g("fp", "chrome"),
        "pbk": g("pbk"),
        "sid": g("sid"),
        "flow": g("flow"),
        "path": g("path"),
        "serviceName": g("serviceName"),
        "mode": g("mode"),
    }


def fetch_subscription_nodes(force=False):
    """拉取订阅并解析全部 vless 节点；带 5 分钟本地缓存。"""
    if not force and CACHE.exists():
        age = __import__("time").time() - CACHE.stat().st_mtime
        if age < 300:
            return json.loads(CACHE.read_text(encoding="utf-8"))
    raw = _http_get(_sub_url()).strip().lstrip("\ufeff").replace("\n", "").replace("\r", "")
    txt = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
    links = [l.strip() for l in txt.splitlines() if l.strip()]
    nodes = []
    for l in links:
        try:
            if l.startswith("vless://"):
                nodes.append(parse_vless(l))
        except Exception as e:
            print(f"  解析失败: {l[:60]}… ({e})", file=sys.stderr)
    CACHE.write_text(json.dumps(nodes, ensure_ascii=False, indent=1), encoding="utf-8")
    return nodes


if __name__ == "__main__":
    ns = fetch_subscription_nodes(force="--force" in sys.argv)
    print(f"节点数: {len(ns)}")
    full = "--full" in sys.argv
    for i, n in enumerate(ns):
        if full:
            print(json.dumps(n, ensure_ascii=False))
        else:
            print(f"  [{i}] {n['name']:<22} {n['host']}:{n['port']} "
                  f"net={n['net']} sec={n['security']} sni={n['sni'][:30]}")
