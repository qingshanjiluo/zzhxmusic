# nichijou.cn 每日登录（完善版）使用说明

主脚本：**`daily_login.py`**（旧版 `checkin.py` / `checkin_group.py` 保留作参考，不再维护）。

## 它比旧版完善在哪里

| 能力 | 旧版 | daily_login.py |
|------|------|----------------|
| 登录（昵称@密码） | ✅ | ✅（选择器容错 + 等待真实元素而非固定 sleep） |
| 签到/抽奖币到账确认 | ❌ 只看登录框消失 | ✅ 解码 WS gzip 帧，抓 `message` 事件里的「恭喜连续第N天签到，获得X个抽奖币」，解析连签天数与币数 |
| 弹窗处理 | 固定 sleep + 盲点按钮 | ✅ MutationObserver 全弹窗留档（通知公告/签到toast/popModal/原生dialog），再定点关闭「知道了/确定」 |
| IP 感知 | 一句注释 | ✅ 每账号记录真实出口 IP + 代理预探测 + `_ip_ledger` 台账（分发按账号判定，IP/设备指纹用于风控，轮换防聚拢） |
| 重复执行 | 每次都全量登录 | ✅ `daily_state.json` 账号×自然日去重，当天已领自动跳过（`--force` 可重跑） |
| 失败处理 | 无 | ✅ 重试 2 次且自动换线路，失败自动截图到 `daily_debug/` |

## 快速使用

```bash
cd F:\study\code\nichijou ai\daily-checkin

python daily_login.py                 # 全部账号（proxies.txt 池轮换）
python daily_login.py --group A       # 只跑 A 组（1-4 号，兼容 ACCOUNT_GROUP 环境变量）
python daily_login.py --only 车老师    # 只跑昵称含“车老师”的
python daily_login.py --force         # 忽略今日已领状态重跑
python daily_login.py --no-proxy      # 直连
python daily_login.py --proxy socks5://127.0.0.1:10818   # 指定代理（需先在跑，见下）
python daily_login.py --headed        # 有头调试
```

结果与留痕：
- `checkin_results.json` —— 本次全部结果（状态/奖励文本/币数/uid/IP/弹窗快照）
- `daily_state.json` —— 账号×日状态 + `_ip_ledger` 今日发币 IP 台账
- `daily_login_log.txt` —— 追加式日志（UTF-8）
- `daily_debug/` —— 失败截图

状态取值：`rewarded`(🪙新领币) / `already`(✅服务端确认已领) / `logged_in_no_reward`(🔁登录正常但被静默拒发：账号已领过或IP冷却) / `cooling`(🧊所有出口IP处于发放冷却，本轮不登录) / `fail`(❌)。

## 抽奖币余额查询（check_coins.py）

**手动**：进**任意房间** → 「关于本站」弹窗 → 「我的道具」→ 抽奖币数量（抽奖房则是
右上角杯子图标「我的道具」，进房即自动查询）。

⚠️ propBag 无 HTTP 接口，只能在房间 WS 上查。`check_coins.py` 的制胜链路（9/13 晚实测
12/12 全部成功，~30s/账号）：登录（头像被占自动换下一张，以 `connectSuccess` 帧为硬标准）
→ 通过 `WebSocket.prototype.send` 钩子复用 **app 自己的活 socket** → 在该 socket 上
**gzip 直发** `tryEnterRoom` → `enterRoom` → `getPropBag` → 收 `syncPropBag`。
（服务端 `isCompress=True`，**明文帧会被静默丢弃**——这是此前直发全部失败的根因。）
结果落盘 `coins_balance.json`（含 registered/全部道具清单）。当日快照（9/13）：
zzhx=7、最中幻想=1(另有音乐卡9等道具)、牛来=3、四方之极/青山寂落/哒哒哒/嘟嘟嘟/车老师Pro=1、
万兽无疆/醉翁/周杰伦/梦=0。协议细节见 `nichijou_api_docs.md` §15。

## xray 备用代理（可选）

```powershell
# 启动（监听 10818 socks5 / 10819 http，出口日本节点）
Start-Process -FilePath ".\xray\xray.exe" -ArgumentList "-config","config_test.json" `
  -WorkingDirectory ".\xray" -WindowStyle Hidden
# 验证出口 IP
curl.exe -s --socks5-hostname 127.0.0.1:10818 https://api.ip.sb/ip
```

## 首次登录捕获工具（研究用）

```bash
python capture_first_login.py --nick "某账号@密码"   # 全量捕获弹窗/HTTP/WS帧
python analyze_capture.py                            # 解析最新 capture_session 报告
python decode_ws.py                                  # gzip 解码 WS 帧
```

捕获结论（机制详见 `nichijou_api_docs.md` 第 14 节）：
登录 → WS connectSuccess → 前端自动发 `hello`（带设备指纹）→ **服务端即完成每日登录检测并分发抽奖币**（toast「恭喜连续第N天签到，获得X个抽奖币」）；前端无任何 IP 探测，**IP 由服务端在连接层读取**。实测分发按 **IP×时间窗** 限量（约每 IP 每 25-30 分钟 1 枚；全新游客号从刚发过币的 IP 登录也会被静默拒发），被拒时服务端不发送任何解释消息。

## 调度模型（重要）

发币限量在【出口 IP】侧（每 IP 日额≈1 枚）。2026-09-25 起接入**节点舰队**彻底解决：

```
订阅(subs_url.txt, 密钥不入库) → fetch_subs.py 解析 ~70 个 vless-reality 节点
  → xray_fleet.py 生成 config_fleet.json(每节点一个本地 socks 端口 21300+i)
  → 启动 xray.exe + curl 健康探测 → fleet_ports.json(端口↔出口IP)
  → daily_login 自动把 70 个新鲜 IP 并入代理池, 一号一 IP 连发
```

实测 9/25：10 个账号 14 分钟全部领到（每人独立 IP），主号/已领账号自动跳过。
`_ip_ledger` 仍按 IP 记账（同 IP 30 分钟冷却自动跳过）；主号永远排第一。

## 定时任务（已注册）

- **GitHub Actions**（`.github/workflows/nichijou-daily-checkin.yml`，仓库根目录才生效！）：
  每天 UTC 16:05（北京 00:05）runner 全新 Azure IP 签主号。
- **本地计划任务** `Nichijou主号签到-0030` / `-1230`（S4U，错过自动补跑）：
  调 `checkin_main.py` = 确保舰队在线 → 全部账号一号一 IP 签到。
  入口中文参数写在 UTF-8 源码里，规避 cmd GBK 坑。
- 手动全量：`python checkin_main.py`（推荐，自动管舰队）
  或 `python daily_login.py`（需先 `python xray_fleet.py` 起舰队）。
