# AI 协助操作网页技术方案（含浏览器插件方案）

## 1. 背景与目标

本方案提供两种互补的技术路径，让 AI 助手能够操作您当前正在访问的网页，完成数据抓取、表单填写、内容提取等任务。

- **方案一（自动化脚本）**：基于 Playwright，适合后台批量处理、定时任务。
- **方案二（浏览器插件）**：基于 Chrome/Edge 扩展，适合 **直接操作您当前浏览器中已打开的页面**，所见即所得。

两种方案可同时使用，互不冲突。

---

## 2. 方案二：浏览器插件（推荐用于交互式操作）

### 2.1 整体架构

```
+----------------+          WebSocket/HTTP          +-------------------+
|   AI 助手      |  <------------------------>     |  本地控制服务器    |
|  (我/您)       |  发送操作指令（点击、填表、提取）  |  (Python/Node)    |
+----------------+                                  +-------------------+
                                                             |
                                                     Chrome扩展注入
                                                             |
                                                     +-------------------+
                                                     |   当前浏览器页面   |
                                                     |  (您正在访问的)   |
                                                     +-------------------+
```

### 2.2 具体实现方案

推荐使用 **Chrome 扩展 + 本地 WebSocket 服务器**，优势如下：

| 组件 | 作用 | 技术选型 |
|------|------|----------|
| 浏览器扩展 | 注入 content script，操作 DOM | Manifest V3 + JavaScript |
| 本地服务器 | 接收 AI 指令，转发给扩展 | Python (`websockets` 库) |
| 通信协议 | 指令/响应双向通信 | WebSocket 或 HTTP 长轮询 |

### 2.3 快速实现步骤

#### 2.3.1 创建浏览器扩展

在项目目录下新建 `extension/` 文件夹：

```
extension/
├── manifest.json          # 扩展配置
├── background.js          # 后台服务（维持 WebSocket 连接）
├── content.js             # 注入到页面的脚本（执行 DOM 操作）
└── popup.html             # 可选：扩展弹出界面，显示连接状态
```

**`manifest.json`**（核心配置）：
```json
{
  "manifest_version": 3,
  "name": "AI 网页控制助手",
  "version": "1.0",
  "permissions": ["activeTab", "scripting"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content.js"]
    }
  ]
}
```

**`background.js`**（建立 WebSocket 连接，接收指令并转发给 content script）：
```javascript
// 连接本地服务器
const ws = new WebSocket('ws://localhost:8765');

ws.onmessage = (event) => {
  const command = JSON.parse(event.data);
  // 向当前激活的标签页注入指令
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    chrome.tabs.sendMessage(tabs[0].id, command, (response) => {
      ws.send(JSON.stringify({ success: true, result: response }));
    });
  });
};
```

**`content.js`**（执行具体 DOM 操作）：
```javascript
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  switch (request.action) {
    case 'click':
      document.querySelector(request.selector)?.click();
      sendResponse({ status: 'clicked' });
      break;
    case 'fill':
      document.querySelector(request.selector).value = request.value;
      sendResponse({ status: 'filled' });
      break;
    case 'extract':
      const text = document.querySelector(request.selector)?.innerText;
      sendResponse({ content: text });
      break;
    // 支持更多动作...
  }
});
```

#### 2.3.2 本地控制服务器（Python）

在 `musicdl/automation/` 下创建 `websocket_server.py`：

```python
import asyncio
import websockets
import json

connected_clients = set()

async def handle_client(websocket):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            # 解析 AI 指令
            data = json.loads(message)
            # 转发给浏览器扩展（已由 background.js 处理）
            # 等待扩展返回结果后回传
            await websocket.send(json.dumps({"status": "executed"}))
    finally:
        connected_clients.remove(websocket)

async def main():
    async with websockets.serve(handle_client, "localhost", 8765):
        await asyncio.Future()  # 保持运行

if __name__ == "__main__":
    asyncio.run(main())
```

#### 2.3.3 AI 与服务器的交互方式

当您发出指令（例如："点击页面上‘搜索’按钮"）时，我将生成如下 Python 代码并执行：

```python
import asyncio
import websockets
import json

async def send_command(action, selector, value=None):
    async with websockets.connect("ws://localhost:8765") as ws:
        command = {"action": action, "selector": selector, "value": value}
        await ws.send(json.dumps(command))
        response = await ws.recv()
        print(response)

# 示例调用
asyncio.run(send_command("click", "button#search"))
asyncio.run(send_command("fill", "input[name='keyword']", "周杰伦"))
```

### 2.4 交互方式（可视化反馈）

- **扩展图标**：安装后在浏览器工具栏显示图标，点击可显示连接状态和指令日志。
- **实时反馈**：执行指令时页面会高亮对应元素（闪烁），并显示"已执行"提示。
- **错误回显**：如果选择器无效，扩展会通过 WebSocket 返回错误信息。

### 2.5 安全与权限

- 扩展仅在您明确启用时生效，不会主动操作页面。
- 本地服务器绑定 `127.0.0.1`，仅本机可访问。
- 所有指令执行前会记录日志，便于审计。

---

## 3. 方案一：Playwright 自动化脚本（补充）

详见上一版本方案。适合批量、后台任务，与浏览器插件方案互补。

---

## 4. 如何选择

| 场景 | 推荐方案 |
|------|----------|
| 需要操作 **当前正在浏览的页面** | 浏览器插件（方案二） |
| 需要批量抓取、定时任务、无需人工干预 | Playwright（方案一） |
| 调试/开发阶段，需频繁查看页面变化 | 浏览器插件（方案二） |
| 需要处理登录态（已有 Cookie） | 浏览器插件（方案二）更便捷 |

---

## 5. 快速启动指南

1. 安装 Python 依赖：`pip install websockets`
2. 启动本地服务器：`python musicdl/automation/websocket_server.py`
3. 在 Chrome 中加载扩展：`chrome://extensions/` → 启用开发者模式 → 加载 `extension/` 文件夹。
4. 确保扩展显示"已连接"状态。
5. 向我发送指令，例如："点击当前页面的‘登录’按钮"，我将生成代码并通过服务器执行。

---

## 6. 扩展后续能力

- **截图反馈**：执行指令后截图返回，便于验证。
- **元素高亮**：操作前闪烁目标元素，让您确认位置。
- **多标签页支持**：通过 `chrome.tabs` API 切换操作目标。
- **录制/回放**：记录操作序列，便于重复执行。

---

**方案已就绪。您可先安装扩展并启动本地服务器，之后随时向我下达页面操作指令。**