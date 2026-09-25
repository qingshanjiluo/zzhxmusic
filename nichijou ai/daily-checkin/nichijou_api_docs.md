# Nichijou.cn API 逆向工程文档

> 基于 JS bundle `index-i6Emi9l5.js` (1.24MB) 逆向分析
> 更新时间: 2026-08-26

---

## 目录
1. [基础信息](#1-基础信息)
2. [认证流程](#2-认证流程)
3. [HTTP API 端点](#3-http-api-端点)
4. [WebSocket 连接](#4-websocket-连接)
5. [大厅 WS 命令](#5-大厅-ws-命令)
6. [大厅 WS 事件](#6-大厅-ws-事件)
7. [房间 WS 命令](#7-房间-ws-命令)
8. [房间 WS 事件](#8-房间-ws-事件)
9. [阳光/道具系统](#9-阳光道具系统)
10. [房间类型](#10-房间类型)
11. [角色系统](#11-角色系统)
12. [前端架构](#12-前端架构)
13. [已知问题](#13-已知问题)

---

## 1. 基础信息

| 项目 | 值 |
|------|-----|
| 域名 | `nichijou.cn` |
| 主 JS Bundle | `https://nichijou.cn/assets/index-i6Emi9l5.js` |
| 文件服务器 | `https://nichijou-1300531302.cos.ap-guangzhou.myqcloud.com` |
| API 基础路径 | `/chat_room_server/` |
| DNS 解析 | `152.32.173.185` |
| 前端框架 | React (类组件 + Redux) |
| 构建工具 | Vite |

---

## 2. 认证流程

### 2.1 登录流程 (select_role)

```
用户输入昵称 → 点击"进入大厅" → POST /chat_room_server/select_role
→ 服务端返回 {status, msg, role, nick}
→ 前端计算 token = MD5("{role}_{nick}_nichijou")
→ 保存 cookies: nick, role, token
→ 初始化 WebSocket 连接
```

### 2.2 Token 计算

```javascript
// JS 源码中的 token 计算逻辑
token = MD5(`${role}_${nick}_nichijou`)
// 例如: MD5("31_zzhx@Pipi20100817_nichijou")
```

### 2.3 Cookies

| Cookie | 说明 | 示例 |
|--------|------|------|
| `nick` | URL 编码的昵称 | `zzhx%40Pipi20100817` |
| `role` | 角色 ID | `31` |
| `token` | MD5 认证 token | `fd4f7b561d4b9c62c27cb2c1e721ffa3` |

### 2.4 登录 API

```
POST https://nichijou.cn/chat_room_server/select_role
Content-Type: application/x-www-form-urlencoded

nick={昵称}&role={角色ID}
```

**返回:**
```json
{
  "status": 0,        // 0=成功
  "msg": "success",
  "role": 31,
  "nick": "zzhx@Pipi20100817"
}
```

### 2.5 游客 vs 注册账号

| 类型 | 输入格式 | 角色 | 说明 |
|------|----------|------|------|
| 游客 | 纯昵称 (如 `青山寂落`) | 9 | 无密码，临时角色 |
| 注册账号 | `昵称@密码` (如 `zzhx@Pipi20100817`) | 3-52 不等 | 有密码，固定角色 |

---

## 3. HTTP API 端点

### 3.1 获取首页信息

```
GET https://nichijou.cn/chat_room_server/get_homepage_info
```

**返回:**
```json
{
  "status": 0,
  "fileServerHost": "https://nichijou-1300531302.cos.ap-guangzhou.myqcloud.com",
  "syncTime": 1234567890
}
```

### 3.2 获取大厅信息

```
GET https://nichijou.cn/chat_room_server/get_hall_info
```

**返回:**
```json
{
  "status": 0,
  "list": [
    {
      "id": 10000,
      "title": "流行歌分享",
      "desc": "分享最近热门的音乐",
      "roomType": "music",
      "coverId": 9,
      "userCurrent": 2,
      "userLimit": 16,
      "isPlaying": true,
      "hasPassword": false,
      "playingMusic": { "title": "Hug me(Remix版)" },
      "userList": [...]
    }
  ],
  "syncTime": 1234567890,
  "fileServerHost": "...",
  "isCompress": false
}
```

### 3.3 选择角色

```
POST https://nichijou.cn/chat_room_server/select_role
Content-Type: application/x-www-form-urlencoded

nick={昵称}&role={角色ID}
```

### 3.4 搜索歌曲

```
GET https://nichijou.cn/chat_room_server/search_song?keyword={关键词}
```

### 3.5 上传资源入口

```
GET https://nichijou.cn/chat_room_server/upload_entry
```

### 3.6 资源上传

```
POST https://nichijou.cn/chat_room_server/asset_upload_entry
Content-Type: multipart/form-data
```

### 3.7 获取通知

```
GET https://nichijou.cn/chat_room_server/get_notify
```

---

## 4. WebSocket 连接

### 4.1 大厅 WebSocket

```
WSS: wss://nichijou.cn/chat_room_server/enter?nick={nick}&role={role}&token={token}
```

**连接成功后服务端推送:**
```json
{"event": "connectSuccess", "uid": 12345, "nick": "xxx", "role": 31}
```

**心跳:**
```json
// 服务端 → 客户端
{"event": "ping", "timestamp": 1234567890}

// 客户端 → 服务端
{"cmd": "pong", "timestamp": 1234567890}
```

### 4.2 房间 WebSocket

进入房间后建立新的 WS 连接，用于房间内消息。

### 4.3 消息编码

消息可能经过 gzip + base64 编码:

```javascript
// 解码
function decode_ws_msg(data) {
    try {
        return JSON.parse(data);  // 直接 JSON
    } catch {}
    try {
        const decoded = atob(data);
        return JSON.parse(pako.gzip(decoded, { to: 'string' }));
    } catch {}
}
```

### 4.4 另一个 WS (广播)

```
WSS: wss://uc.nichijou.cn/chat_room_server/join_bc_server?groupType=1
```

---

## 5. 大厅 WS 命令

通过大厅 WebSocket 发送的命令:

| 命令 | 参数 | 说明 |
|------|------|------|
| `hello` | - | 握手 |
| `hb` | - | 心跳 |
| `pong` | `timestamp` | 心跳回复 |
| `tryEnterRoom` | `id`, `content`(密码) | 请求进入房间 |
| `confirmBackToHall` | - | 确认返回大厅 |
| `sendChatMsg` | `content` | 发送聊天消息 |
| `backToHall` | - | 返回大厅 |
| `sendPhoto` | - | 发送图片 |

### 5.1 进入房间

```json
// 客户端发送
{"cmd": "tryEnterRoom", "id": 10000, "content": ""}

// 服务端响应
{"event": "tryEnterRoomResult", "resultId": "xxx", "isOk": true, "title": "流行歌分享", "value": "music"}
```

**密码房间:**
```json
{"cmd": "tryEnterRoom", "id": 10000, "content": "123456"}
```

### 5.2 发送聊天消息

```json
{"cmd": "sendChatMsg", "content": "hello"}
```

---

## 6. 大厅 WS 事件

服务端推送的事件:

| 事件 | 说明 |
|------|------|
| `connectSuccess` | 连接成功，包含 uid, nick, role |
| `syncHallInfo` | 同步大厅信息 (房间列表、用户列表等) |
| `tryEnterRoomResult` | 进入房间结果 |
| `confirmBackToHall` | 确认返回大厅 |
| `hallUserUpdate` | 大厅用户更新 |
| `beybey` | 断开连接 |
| `popModal` | 弹出模态框 |
| `popModalByID` | 按 ID 弹出模态框 |
| `message` | 通用消息 (success/warn/error/info) |
| `ping` | 心跳 |
| `playAutom` | 自动播放音乐 |
| `sendAnimate` | 发送动画 |
| `recallMessage` | 撤回消息 |
| `coverMessage` | 覆盖消息 |
| `firework` | 烟花效果 |
| `showUserConfetti` | 用户彩带 |
| `showRoomConfetti` | 房间彩带 |
| `redirect` | 重定向 |
| `setFrameKey` | 设置帧密钥 |

---

## 7. 房间 WS 命令

进入房间后可用的命令:

### 7.1 基础命令

| 命令 | 参数 | 说明 |
|------|------|------|
| `enterRoom` | `id` | 进入房间 (房间内WS) |
| `getPlayingItem` | - | 获取当前播放项 |
| `getSongList` | - | 获取歌曲列表 |
| `getSongWindow` | `index` | 获取歌曲窗口 |
| `sendChatMsg` | `content` | 发送聊天消息 |
| `backToHall` | - | 返回大厅 |
| `hb` | - | 心跳 |
| `pong` | `timestamp` | 心跳回复 |

### 7.2 音乐控制

| 命令 | 参数 | 说明 |
|------|------|------|
| `play` | - | 播放 |
| `pause` | - | 暂停 |
| `nextSong` | - | 下一首 |
| `previousSong` | - | 上一首 |
| `changeProgress` | `progress` | 改变进度 |
| `insertOrder` | - | 插入订单 |
| `playById` | `id` | 按 ID 播放 |
| `insertNewMusic` | - | 插入新音乐 |
| `addNewMusic` | - | 添加新音乐 |
| `addTempMusicByCard` | `id` | 通过卡片添加临时音乐 |
| `deleteMusic` | `id`, `title` | 删除音乐 |
| `syncProgress` | - | 同步进度 |

### 7.3 道具系统

| 命令 | 参数 | 说明 |
|------|------|------|
| `getPropBag` | - | 获取道具背包 |
| `useProp` | - | 使用道具 |
| `sendGift` | - | 发送礼物 |

### 7.4 抽奖/彩票房间

| 命令 | 参数 | 说明 |
|------|------|------|
| `getLotteryState` | - | 获取抽奖状态 |
| `lotteryStart` | - | 开始抽奖 |
| `lotteryInsertCoin` | - | 投币 |
| `lotteryTakeSeat` | - | 就座 |
| `lotteryLeaveSeat` | - | 离座 |
| `lotteryAnimationComplete` | - | 动画完成 |
| `lotteryMysteryAnimationComplete` | - | 神秘奖动画完成 |

### 7.5 你画我猜房间

| 命令 | 参数 | 说明 |
|------|------|------|
| `startGame` | - | 开始游戏 |
| `selectTopic` | - | 选择主题 |
| `skipRound` | - | 跳过回合 |
| `setReady` | - | 设置准备 |
| `cancelReady` | - | 取消准备 |
| `joinQueue` | - | 加入队列 |
| `cancelQueue` | - | 取消队列 |
| `newMovie` | - | 新影片 |
| `removeMovie` | - | 移除影片 |

### 7.6 办公室/管理

| 命令 | 参数 | 说明 |
|------|------|------|
| `getOfficeDashboard` | - | 获取管理面板 |
| `officeReviewRoomCreate` | `requestId`, `action` | 审核房间创建 |
| `officeUpdateManagedRoom` | - | 更新管理房间 |
| `officeExportPlaylist` | `roomId` | 导出播放列表 |
| `officeImportPlaylist` | `roomId`, `songList` | 导入播放列表 |
| `officeCreateRewardCode` | - | 创建奖励码 |
| `officeDeleteBlacklist` | `timestamp` | 删除黑名单 |
| `officeUnbindRole` | `nick`, `roleId` | 解绑角色 |
| `officeReviewAssetApplication` | `requestId`, `action` | 审核资产申请 |
| `updateRemoteSetting` | `key`, `id`, `content` | 更新远程设置 |
| `getPlayList` | - | 获取播放列表 |

### 7.7 房间创建

| 命令 | 参数 | 说明 |
|------|------|------|
| `createRoomByCard` | `content` | 通过道具卡创建房间 |
| `beginAssetApplicationUpload` | - | 开始资产申请上传 |
| `submitAssetApplication` | - | 提交资产申请 |

---

## 8. 房间 WS 事件

房间内服务端推送的事件:

### 8.1 基础事件

| 事件 | 说明 |
|------|------|
| `ping` | 心跳 |
| `enterRoomResult` | 进入房间结果 |
| `syncRoomInfo` | 同步房间信息 |
| `syncChatMessage` | 同步聊天消息 |
| `syncEventMessage` | 同步事件消息 |
| `confirmBackToHall` | 确认返回大厅 |
| `beybey` | 断开连接 |
| `message` | 通用消息 |
| `recallMessage` | 撤回消息 |
| `coverMessage` | 覆盖消息 |
| `redirect` | 重定向 |
| `setFrameKey` | 设置帧密钥 |
| `popModal` | 弹出模态框 |
| `popModalByID` | 按 ID 弹出模态框 |

### 8.2 音乐事件

| 事件 | 说明 |
|------|------|
| `syncPlayingItem` | 同步当前播放项 |
| `syncSongList` | 同步歌曲列表 |
| `syncSongWindow` | 同步歌曲窗口 |
| `syncPlayList` | 同步播放列表 |
| `playAutom` | 自动播放 |
| `downloadMusic` | 下载音乐 |

### 8.3 视频事件

| 事件 | 说明 |
|------|------|
| `syncPlayingMovie` | 同步播放影片 |

### 8.4 动画/特效

| 事件 | 说明 |
|------|------|
| `sendAnimate` | 发送动画 |
| `firework` | 烟花效果 |
| `showUserConfetti` | 用户彩带 |
| `showRoomConfetti` | 房间彩带 |

### 8.5 道具/办公

| 事件 | 说明 |
|------|------|
| `syncPropBag` | 同步道具背包 |
| `syncOfficeDashboard` | 同步管理面板 |
| `officePlaylistExport` | 播放列表导出 |
| `assetApplicationUploadReady` | 资产上传就绪 |
| `createRoomByCardResult` | 创建房间结果 |
| `roomPasswordSetResult` | 房间密码设置结果 |

### 8.6 抽奖事件

| 事件 | 说明 |
|------|------|
| `syncLotteryRoomInfo` | 同步抽奖房间信息 |
| `lotteryRoundStart` | 抽奖回合开始 |
| `lotteryRoundEnd` | 抽奖回合结束 |
| `lotteryMysteryStart` | 神秘奖开始 |
| `lotteryRoomNotice` | 抽奖房间通知 |

### 8.7 你画我猜事件

| 事件 | 说明 |
|------|------|
| `syncDrawRoomInfo` | 同步画房信息 |
| `syncDrawWsConnectURL` | 同步画WS连接URL |
| `drawTopicSelect` | 主题选择 |
| `drawRoundStart` | 回合开始 |
| `drawCorrectAnswer` | 正确答案 |
| `drawRoundResult` | 回合结果 |
| `drawGiftEvent` | 礼物事件 |
| `drawGameResult` | 游戏结果 |
| `drawTimeExtended` | 时间延长 |

---

## 9. 阳光/道具系统

### 9.1 阳光值字段

**阳光值 = `extInfo.power`**

每个用户对象中都包含 `extInfo.power` 字段，这就是该用户的阳光值。

```json
// 用户对象结构
{
  "uid": 251663,
  "role": 51,
  "nick": "游客001",
  "roomId": 3,
  "isRoomMgr": true,
  "isAdmin": false,
  "extInfo": {
    "power": 16017  // ← 这就是阳光值
  }
}
```

### 9.2 查询阳光值的方法

#### 方法 1: HTTP API (推荐)

```
GET https://nichijou.cn/chat_room_server/get_hall_info
```

返回的 `userList` 中包含所有在线用户的阳光值:

```json
{
  "status": 0,
  "data": {
    "userList": [
      {
        "uid": 251663,
        "role": 51,
        "nick": "游客001",
        "extInfo": { "power": 16017 }
      }
    ]
  }
}
```

**注意**: 只有当前在线的用户才会出现在 `userList` 中。

#### 方法 2: 大厅 WS 事件

连接大厅 WebSocket 后，服务端推送 `syncHallInfo` 事件，包含完整用户列表:

```json
{"event": "syncHallInfo", "userList": [...]}
```

#### 方法 3: 房间内查看

进入房间后，房间 WS 推送 `syncRoomInfo`，包含房间内用户信息和阳光值。

### 9.3 阳光获取方式

| 方式 | 说明 | 阳光值 |
|------|------|--------|
| 每日签到 | 登录即自动签到 (checkin.py 已实现) | +N |
| 发消息 | 在房间内发送聊天消息 | +N |
| 抽奖 | 彩票房间投入 lottery_coin | 可变 |
| 道具卡 | 使用道具卡创建房间等 | -N |

### 9.4 道具系统

#### 获取道具背包

```json
// 客户端发送 (需要房间内 WS)
{"cmd": "getPropBag"}

// 服务端返回
{"event": "syncPropBag", "propBag": {"items": [...]}}
```

#### 道具类型

| 道具 ID | 名称 | 说明 |
|---------|------|------|
| `lottery_coin` | 抽奖币 | 用于彩票房间投币 |
| `createRoom` | 创建房间卡 | 创建用户自定义房间 |
| 其他 | - | 待补充 |

### 9.5 在线用户阳光值示例 (2026-08-26)

| 昵称 | 角色 | 阳光值 | 所在房间 |
|------|------|--------|----------|
| 游客768 | 36 | 43,822 | 经典粤语 |
| 白宇喵喵喵 | 10003 | 20,054 | 大大怪将军的敢死队 |
| 游客001 | 51 | 16,017 | 流行歌分享 |
| 好的 | 10002 | 10,593 | Mångata |
| 法外狂徒 | 14 | 9,750 | 流行歌分享 |
| 诗诗酱 | 3 | 9,489 | 摸鱼者联盟 |
| 游客9527 | 29 | 9,303 | 大大怪将军的敢死队 |
| 我一直在哭 | 70 | 9,189 | 欧美音乐专区 |
| Miii | 58 | 8,073 | 大大怪将军的敢死队 |
| 小玖 | 53 | 6,715 | 纯音乐专区 |
| 六六 | 2 | 669 | 流行歌分享 |
| 吾先生 | 28 | 562 | 大大怪将军的敢死队 |
| 梦游 | 26 | 405 | 大大怪将军的敢死队 |
| bai | 21 | 164 | 纯音乐专区 |
| kl | 44 | 29 | 摸鱼者联盟 |
| Pogacha | 67 | 23 | 東雲研究所 |
| 游客800 | 17 | 9 | 爵士乐鉴赏 |
| 江 | 60 | 1 | 東雲研究所 |
- 其他道具...

### 9.3 注册账号 (设置密码)

在音乐房发送:
```
/password_你的密码
```

设置成功后，下次登录需使用 `昵称@密码` 格式。
成功回应: `创建帐号成功,下次登录请填写昵称 "X@密码"` + `恭喜获得14天日常新人头像框` + `消耗法力100`（注册消耗 100 阳光）。

**批量注册实测要点（2026-09-25，register_fleet.py）**:
- **游客阳光不跨会话**: 游客 uid 每次连接都变，刷到的阳光随断线丢失。
  必须同一会话内一次刷到 ≥110 再立即发 `/password_`（约 110 条聊天消息）。
- **节奏必须拟人化**: ~0.7s/条的机器连发会被降权（阳光收益 1/条 → 0.2/条）
  甚至疑似禁言（`/password_` 无任何回应）。安全节奏: 每条 2.5-6s 随机间隔 +
  消息内容多样化，5 条一轮、轮间歇 8-15s。
- **进房不要用 JS 点击房间卡**（React isConnect 门控会静默吞掉）: 在 app 自己的
  WS 上直发 `tryEnterRoom→enterRoom`（§15.4 链路），SPA 原地切房最可靠。
- **必须 launch 级代理**: chromium 对 context 级 SOCKS 代理的 WebSocket 支持不可靠，
  会导致登录后 socket 迟迟不出现。
- 登录框消失 ≠ WS 已连上: 慢节点握手要 4-6s，需等 `__socks` 出现活 socket
  再操作，否则直发帧全部被服务端忽略。
- 纯数字/单字符昵称可能登录失败（"6" 实测 login_fail）；已被注册的昵称游客
  登录会进入异常状态（"古月方源/大爱仙尊/幻想" 实测进房失败，换名即好）。

---

## 10. 房间类型

| roomType | 说明 | 封面图 |
|----------|------|--------|
| `music` | 音乐房 | cover_1.webp |
| `draw` | 你画我猜 | cover_2.webp |
| `lottery` | 彩票/抽奖房 | cover_3.webp |
| `movie` | 电影房 | - |
| `office` | 办公室/管理房 | - |

---

## 11. 角色系统

### 11.1 已知角色 ID

| 角色 | ID | 说明 |
|------|-----|------|
| 游客 | 9 | 临时角色，纯昵称登录 |
| 普通用户 | 3, 5, 16, 18, 20, 30, 31, 52, 63 | 注册账号 |
| VIP | - | VIP 房间标记 |
| 管理员 | isAdmin=true | 办公室权限 |

### 11.2 角色属性

```json
{
  "uid": 12345,
  "nick": "zzhx",
  "role": 31,
  "extInfo": {
    "listenHell": false
  }
}
```

---

## 12. 前端架构

### 12.1 技术栈

- React (类组件 + Redux)
- Redux-Saga (副作用管理)
- Vite (构建)
- Ant Design (UI 组件)

### 12.2 状态管理

```javascript
// Redux store 结构
{
  global: {
    myUid: 12345,
    myNick: "zzhx",
    myRole: 31,
    hallInfo: {
      roomList: [...],
      userCurrent: 20,
      userLimit: 100,
      isCompress: false,
      fileServerHost: "..."
    },
    fileServerHost: "...",
    wsCon: WebSocket,
    isConnect: true,
    roomID: null,
    roomType: null,
    clientType: "pc" // or "mobile"
  }
}
```

### 12.3 LocalStorage

| Key | 说明 |
|-----|------|
| `heartbeat` | 心跳时间戳 |
| `token` | 认证 token |
| `notify_show_records` | 通知显示记录 |
| `room_password_{roomId}_{nick}` | 房间密码缓存 (JSON) |

---

## 13. 已知问题

### 13.1 WebSocket 连接问题

**现象**: 服务器接受 WS 升级请求但不发送任何数据

**影响**:
- 无法获取大厅信息 (syncHallInfo)
- 无法进入房间 (tryEnterRoom)
- 无法发送消息 (sendChatMsg)
- 无法获取阳光/道具信息

**可能原因**: 服务器 WS 处理器故障或维护中

### 13.2 房间进入流程

```
1. 大厅 WS 连接 → 接收 syncHallInfo
2. 用户点击房间卡片
3. 发送 tryEnterRoom 命令
4. 服务端返回 enterRoomResult
5. 成功后连接房间 WS
6. 房间内可用 sendChatMsg 等命令
```

**当前阻塞点**: 第 1 步大厅 WS 无法连接

### 13.3 安全措施

- DNS 验证
- SSL 证书固定
- HMAC 签名
- Nonce 生成
- 速率限制
- 输入清理
- 会话隔离
- 审计日志

---

## 附录: 完整房间列表 API

```javascript
// 获取大厅信息 (含所有房间)
GET /chat_room_server/get_hall_info

// 返回结构
{
  status: 0,
  list: [
    {
      id: number,           // 房间 ID
      title: string,        // 房间标题
      desc: string,         // 描述
      roomType: string,     // 类型: music/draw/lottery/movie/office
      coverId: number,      // 封面图片 ID
      isOpen: boolean,      // 是否开放
      isPlaying: boolean,   // 是否在播放
      isPublic: boolean,    // 是否公开
      isAdmin: boolean,     // 是否管理房
      hasPassword: boolean, // 是否有密码
      userCurrent: number,  // 当前人数
      userLimit: number,    // 人数上限
      playingMusic: {       // 当前播放音乐
        title: string
      },
      userList: [           // 用户列表
        { uid: number, nick: string, role: number }
      ],
      createdRoomInfo: {}   // 创建者信息
    }
  ],
  syncTime: number,         // 同步时间
  fileServerHost: string,   // 文件服务器地址
  isCompress: boolean       // 是否压缩
}
```

---

## 14. 登录检测 → 抽奖币分发 → IP 获取（2026-09-13 首次登录实测捕获确认）

> 证据来源: `capture_first_login.py` 全量捕获（HTTP 106条 / WS帧解码 / MutationObserver 弹窗），
> 报告存于 `capture_session/<ts>/capture_report.json`。

### 14.1 第一次登录出现的全部弹窗（按时间序）

| # | 弹窗 | 来源 | 形态 | 处理 |
|---|------|------|------|------|
| 1 | 登录框「选择角色 / 进入大厅 / 当前在线人数」 | 前端 `loginBoxTemplate` | React modal | 输入 `昵称@密码` 点进入 |
| 2 | 「通知公告」(如: 系统更新通知…) | `GET /chat_room_server/get_notify` | `comModalCard errmodalCard notifyCardGrid` | 点「知道了」；已见 id 记入 `localStorage.notify_show_records`，同 id 只弹一次 |
| 3 | **「恭喜连续第 N 天签到，获得 X 个抽奖币」** | WS `message` 事件（`hello` 后服务端推送） | `ant-message-notice-content` toast | 自动消失；即签到+发币凭证 |
| 4 | 原生 alert/confirm | `wsBeybey`/错误 | 浏览器 dialog | 捕获时 0 次触发 |
| - | `popModal{title,value}` | WS 事件 | `vX(value,title)` modal | 本次未触发，监听已留档 |

### 14.2 登录检测与抽奖币分发链路

```
select_role?nick=昵称@密码&role=R   → status:0
WS wss://…/enter?nick=&role=&token=MD5("{R}_{nick}_nichijou")   ← 已验证: MD5("32_zzhx@Pipi20100817_nichijou")=640380bd…
  << {"event":"connectSuccess","uid":259157,"nick":"zzhx","resultId":32}
  >> {"cmd":"hello","content":"{屏宽}x{屏高};{视口};pc;{timeGap};{heartbeat距今|firstTime};{lastNick|newUser};",
      "title":"{localStorage.frameKey}","key":"{localStorage.userKey}"}
  << {"event":"message","title":"success","value":"恭喜连续第 N 天签到，获得 X 个抽奖币"}   ← 分发判定完成
```

- **触发器 = `hello` 指令**：服务端收到 hello 即做每日登录检测，无需任何显式“签到”请求。
- 币进入背包 `syncPropBag.items[propId=lottery_coin].count`（彩票房内可见可 `lotteryInsertCoin` 使用）。

### 14.3 对 IP 的获取方式

- 前端 bundle 全文 **0** 处 IP 探测（无 ip138/myip/getIP…，106 条 HTTP 全部落在 nichijou.cn 站内）。
- 服务端在 **连接层直接读取 HTTP/WS 源 IP**（对代理透明），并叠加 hello 携带的
  **设备指纹**（localStorage `userKey` 10位随机设备ID + `heartbeat` 间隔 + firstTime/newUser + 屏幕/时区）。
- **实测分发规则 = IP×时间窗限量（非账号绑定）**，关键实验（2026-09-13，UTC）：
  - 09:40 `zzhx`@IP-A → 🪙；10:05 `青山寂落`@IP-A → 🪙（同 IP 第 2 枚，间隔 25 分钟）
  - 09:48 `最中幻想`@IP-A → 静默（距上枚仅 8 分钟）；IP-B 同理 09:53 🪙 后 09:56 起静默
  - **10:21 全新游客号(测试甲928)@IP-A → 静默**（距 10:05 仅 16 分钟）→ 排除账号因素，
    证明门控在 IP 侧；两 IP 各观测到 ≥2 枚/日，间隔 ≥25 分钟可再发 → 冷却窗口 ∈ (16, 25] 分钟
  - 分发时服务端推送 `message/success` toast；被拒时**完全静默**（无任何解释消息，09:48 实测）
- 运营结论（`daily_login.py` 已内置）：**每 IP 每 ~30 分钟最多 1 枚**；cron 每 30 分钟跑一轮，
  脚本自动做发放冷却台账（`_ip_ledger.last_grant`）、IP 轮换、静默账号降权（tries 排序），
  全部 IP 冷却时零登录快速退出；每账号仍是全新浏览器上下文（新 userKey 设备指纹）。

### 14.4 每日登录工具

`daily_login.py`（完善版，取代 checkin.py/checkin_group.py 的判定盲区）：
WS gzip 解码实时确认发币、弹窗全捕获+自动关闭、账号×日去重、代理池轮换与预探测、
失败换线重试、`_ip_ledger`/`checkin_results.json` 留痕。详见 `DAILY_LOGIN.md`。

---

## 15. 抽奖币余额查询（propBag）

### 15.1 协议（bundle 逆向 + 实测）

- **没有 HTTP 接口**，走**当前房间的 WS**（即大厅那条 `enter?nick=..&role=..&token=..`
  连接本身，`model.wsCon`；进房不换 socket，房间组件只是重绑 `onmessage` 再发
  `{cmd:"enterRoom", id}`——见 bundle `componentDidMount`@1203466）。
- **任何房间都能查**（不止抽奖房）：
  - 抽奖房：进房自动 `sendReq({cmd:"getPropBag"})`
    （`wsConnectRoom`: `"lottery"===r && (cmdGetLotteryState() + cmdPropBag())`@1186665）
  - 普通房（音乐/电影/你画我猜…）：房间页左下角 `#btnK`（「关于本站」@1056455）
    → 弹窗内 `.aboutMeRewardEntry`（「我的道具」@1043255）→ `onOpenPropBag()`
    → `sendReq({cmd:"getPropBag"})`
- 服务端回帧：
  ```json
  {"event": "syncPropBag",
   "propBag": {"registered": true,
               "items": [{"propId": "lottery_coin", "count": 3}, ...]}}
  ```
  - 未注册（游客）→ `registered:false`，前端 toast「注册后才能使用道具功能」
  - 余额 = `items` 里 `propId/type=="lottery_coin"` 的 `count`；
    抽奖房另有 `syncLotteryRoomInfo.coinPool`（全服奖池）可顺带读取。

### 15.2 进房协议与实测坑（2026-09-13）

- 大厅点房间卡 → `{cmd:"tryEnterRoom", id, content:""}`（有密码房先弹密码框，
  **不发帧**）→ 回 `tryEnterRoomResult{isOk,title}` → isOk 时 `history.push('/room?id=N')`。
- 免点击进房正门：**`/hall?roomId=N`**（bundle `tryEnterRoom` setTimeout(cmdEnterRoom,1e3)@1009262）。
- 实测 `#20 幸运值测试房`（lottery 唯一在榜房）：`tryEnterRoomResult` 拒
  **"抽奖房暂未开放"**，房主历史公告提示约 20:00–24:00（北京时间）开放；音乐房常年可进。
- ⚠️ 自动化大坑（今日多轮实测）：
  1. `select_role` status0 会**说谎**（头像瞬时被占）→ 登录判定的唯一硬标准是
     WS 收到 `connectSuccess` 帧；被占时 enter 握手直接 403/500。
  2. 前端 `sendReq` 有 `isConnect && wsCon` 门控——WS 帧虽到达但 Redux 未置位时
     点房间卡**静默不发帧**（无任何报错）。对策：`add_init_script` 里包
     **`WebSocket.prototype.send`**（在首个 send 如 hello 时把 `this` 记入 `__socks`）
     复用 app 活 socket 直接 `send`。⚠️ 包**构造器**抓不到——app 的 socket 早于脚本建好。
  3. **服务端 `hallInfo.isCompress=true`**（实测）：app 自身所有发送都 `pako.gzip`
     （真 gzip 容器）。**明文帧被服务端静默丢弃、无报错**——这是此前所有直发失败的根因。
     用 `CompressionStream("gzip")` 生成同格式二进制即可。

### 15.4 制胜链路（2026-09-13 晚实测 12/12 全部成功，~30s/账号）

登录后**不跳房页**（SPA 跳转会清空 `__socks`），直接在 app 活 socket 上 gzip 连发：
`tryEnterRoom{id}` →（等 `tryEnterRoomResult.isOk=true`）→ `enterRoom{id}` → `getPropBag`
→ 收 `syncPropBag`。`entry_kind=direct-ws-chain`，`registered=true`、`lottery_coin` 到账。
实测余额快照：zzhx=7、最中幻想=1(另有 pigeon_card/music_card 等)、牛来=3、
四方之极/青山寂落/哒哒哒/嘟嘟嘟/车老师Pro=1、万兽无疆/醉翁/周杰伦/梦=0（当日未领且命中 IP 发放限量）。

### 15.3 查询工具 `check_coins.py`

```powershell
python check_coins.py                  # 默认查 zzhx
python check_coins.py --all            # 遍历 accounts.json 全部账号
python check_coins.py --nick 青山寂落@Pipi20100817
python check_coins.py --all --watch --interval-min 10 --max-wait-min 300
```

流程（当前版本）：登录（头像被占自动换下一张，帧门槛校验）→ **直发链路 §15.4**
（gzip tryEnterRoom→enterRoom→getPropBag，首选"经典粤语#4"等常开音乐房）→ 收
`syncPropBag` 落盘。UI 点卡路径（房间卡→`#btnK`→`.aboutMeRewardEntry`）保留为降级。
关门返回 `room_closed`（🚪），`--watch` 只重试未查到的账号；
结果追加保存到 `coins_balance.json`。
手动查看：任意房间 → 「关于本站」→ 「我的道具」；抽奖房则是右上角杯子图标。

---

*文档基于 nichijou.cn JS bundle 逆向分析生成；第 14/15 节为实测捕获证据补充*
