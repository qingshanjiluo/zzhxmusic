#!/usr/bin/env python3
"""
通过代理访问nichijou.cn测试签到
使用vless订阅转换为本地SOCKS5代理
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SUB_URL = "https://liangxin.xyz/api/v1/liangxin?OwO=a82c11d10a4713202f99c70bc589f79d"
XRAY_DIR = Path(__file__).parent / "xray"
XRAY_EXE = XRAY_DIR / "xray.exe"
SOCKS_PORT = 10818
HTTP_PORT = 10819


def fetch_sub():
    """获取订阅内容"""
    import urllib.request
    import base64
    req = urllib.request.Request(SUB_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    # base64解码
    decoded = base64.b64decode(data).decode("utf-8")
    nodes = [line.strip() for line in decoded.split("\n") if line.strip().startswith("vless://")]
    return nodes


def parse_vless(url):
    """解析vless链接"""
    # vless://uuid@host:port?params#name
    without_proto = url.replace("vless://", "")
    hash_idx = without_proto.find("#")
    name = urllib.parse.unquote(without_proto[hash_idx+1:]) if hash_idx >= 0 else ""
    without_hash = without_proto[:hash_idx] if hash_idx >= 0 else without_proto
    
    at_idx = without_hash.find("@")
    uuid = without_hash[:at_idx]
    rest = without_hash[at_idx+1:]
    
    query_idx = rest.find("?")
    host_port = rest[:query_idx]
    query_str = rest[query_idx+1:] if query_idx >= 0 else ""
    
    colon_idx = host_port.rfind(":")
    server = host_port[:colon_idx]
    port = int(host_port[colon_idx+1:])
    
    params = dict(urllib.parse.parse_qsl(query_str))
    
    return {
        "name": name,
        "server": server,
        "port": port,
        "uuid": uuid,
        "type": params.get("type", "tcp"),
        "host": params.get("host", ""),
        "path": params.get("path", ""),
        "security": params.get("security", "tls"),
        "sni": params.get("sni", ""),
        "fp": params.get("fp", ""),
    }


def gen_xray_config(node, socks_port, http_port):
    """生成xray配置"""
    stream = {}
    net = node["type"]
    
    if net == "ws":
        stream["network"] = "ws"
        stream["wsSettings"] = {
            "path": node["path"],
            "headers": {"Host": node["host"]},
        }
    elif net == "tcp":
        stream["network"] = "tcp"
    elif net == "h2":
        stream["network"] = "h2"
        stream["h2Settings"] = {"path": node["path"]}
    
    if node["security"] == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "serverName": node["sni"] or node["host"],
            "fingerprint": node["fp"] or "chrome",
        }
    
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks",
                "port": socks_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True},
            },
            {
                "tag": "http",
                "port": http_port,
                "listen": "127.0.0.1",
                "protocol": "http",
            },
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": node["server"],
                            "port": node["port"],
                            "users": [
                                {
                                    "id": node["uuid"],
                                    "encryption": "none",
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": stream,
            }
        ],
    }
    return config


async def main():
    print("=== 获取代理订阅 ===")
    nodes = fetch_sub()
    print(f"获取到 {len(nodes)} 个节点")
    
    # 解析前5个节点
    parsed = []
    for node_url in nodes[:10]:
        try:
            node = parse_vless(node_url)
            parsed.append((node_url, node))
            print(f"  {node['name']}: {node['server']}:{node['port']} ({node['type']}/{node['security']})")
        except Exception as e:
            pass
    
    if not parsed:
        print("无可用节点")
        return
    
    # 选择一个节点测试
    test_node_url, test_node = parsed[0]
    print(f"\n=== 测试节点: {test_node['name']} ===")
    
    # 生成配置
    config = gen_xray_config(test_node, SOCKS_PORT, HTTP_PORT)
    config_path = XRAY_DIR / "config_test.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"配置已保存: {config_path}")
    print(f"SOCKS5: 127.0.0.1:{SOCKS_PORT}")
    print(f"HTTP: 127.0.0.1:{HTTP_PORT}")
    
    # 启动xray
    print("\n=== 启动代理 ===")
    if not XRAY_EXE.exists():
        print(f"xray不存在: {XRAY_EXE}")
        print("请下载xray-core: https://github.com/XTLS/Xray-core/releases")
        return
    
    proc = subprocess.Popen(
        [str(XRAY_EXE), "run", "-c", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    time.sleep(3)
    
    if proc.poll() is not None:
        print("xray启动失败")
        return
    
    print("xray已启动")
    
    # 测试代理
    print("\n=== 测试代理连接 ===")
    try:
        import urllib.request
        proxy = urllib.request.ProxyHandler({
            "http": f"socks5://127.0.0.1:{SOCKS_PORT}",
            "https": f"socks5://127.0.0.1:{SOCKS_PORT}",
        })
        opener = urllib.request.build_opener(proxy)
        opener.addheaders = [{"User-Agent": "Mozilla/5.0"}]
        
        # 测试IP
        resp = opener.open("https://httpbin.org/ip", timeout=10)
        ip_info = json.loads(resp.read())
        print(f"代理IP: {ip_info.get('origin', 'unknown')}")
        
        # 测试nichijou
        resp = opener.open("https://nichijou.cn/hall", timeout=15)
        print(f"nichijou.cn/hall: {resp.status}")
        
    except Exception as e:
        print(f"代理测试失败: {e}")
    
    proc.terminate()
    proc.wait()
    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
