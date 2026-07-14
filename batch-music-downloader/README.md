# Smart Downloader - 智能音乐下载器

基于 GitHub Actions 的全自动音乐下载工具，支持 **AI 智能音乐助手**，用自然语言描述你的需求，AI 自动发现并下载歌曲。

---

## 🚀 快速开始

### 🤖 AI 智能音乐助手（推荐）

用自然语言描述你想听的歌，AI 自动完成搜索→发现→下载全过程。

```bash
# 本地运行
python src/ai_assistant.py --task "帮我找周杰伦的中国风歌曲和洛天依的歌曲并下载"

# 指定音源和音质
python src/ai_assistant.py --task "下载QQ热歌榜前30首" --quality mp3 --workers 5

# 仅发现不下载
python src/ai_assistant.py --task "推荐好听的民谣歌曲" --no-download

# 使用 DeepSeek AI 增强理解
python src/ai_assistant.py --task "推荐类似周杰伦风格的歌手" --deepseek-key sk-xxx

# 查看可用工具列表
python src/ai_assistant.py --list-tools
```

#### AI 助手架构

```
用户输入（自然语言）
       ↓
┌─────────────────────────────┐
│  AI Assistant (ai_assistant) │ ← 任务编排器
└─────────────────────────────┘
       ↓
┌──────────────────┐  ┌────────────────────┐  ┌──────────────────┐
│  SearchTools      │  │  MusicDiscovery    │  │  SmartDownloader │
│  (网络搜索)        │  │  (智能发现引擎)     │  │  (下载引擎)      │
│  DuckDuckGo免费   │  │  · 内置歌手库       │  │  · 并发下载      │
│  SerpAPI可选      │  │  · 排行榜发现       │  │  · 音质回退      │
│  Google/Bing可选  │  │  · 风格/相似发现    │  │  · 源级熔断      │
└──────────────────┘  │  · 网络搜索发现      │  │  · ZIP打包       │
                       └────────────────────┘  └──────────────────┘
```

### 传统下载方式

```bash
pip install -r requirements.txt

# 从文件下载
python src/smart_downloader.py --file song-queue.txt

# 手动输入
python src/smart_downloader.py --text "七里香,周杰伦;稻香,周杰伦;童话,光良"

# 排行榜下载
python src/smart_downloader.py --top-charts qq_hot --chart-limit 20
```

---

## 🔧 模块说明

### 模块结构

```
batch-music-downloader/
├── src/
│   ├── ai_assistant.py          # 🤖 AI 智能助手（核心编排器）
│   ├── smart_downloader.py      # 📥 音乐下载引擎（V2）
│   ├── music_discovery.py       # 🎵 音乐发现引擎
│   ├── search_tools.py          # 🔍 网络搜索工具
│   └── generate_charts_report.py# 📊 排行榜报告生成
├── .github/workflows/
│   ├── ai-music-assistant.yml   # 🤖 AI 智能助手工作流
│   ├── smart-download.yml       # 歌曲列表下载工作流
│   ├── playlist-download.yml    # 歌单下载工作流
│   ├── top-charts-download.yml  # 热歌榜下载工作流
│   └── list-charts.yml          # 列榜单工作流
├── song-queue.txt               # 歌曲队列文件
└── requirements.txt             # 依赖清单
```

### AI 智能助手 ([`src/ai_assistant.py`](src/ai_assistant.py))

核心编排器，接收自然语言任务，自动完成：
- **任务理解**：分析用户意图（歌手、风格、排行榜）
- **歌曲发现**：综合调用搜索、排行榜、内置库发现歌曲
- **执行规划**：制定下载计划
- **自动下载**：调用 `smart_downloader` 执行
- **任务报告**：生成完整的执行总结

### 音乐发现引擎 ([`src/music_discovery.py`](src/music_discovery.py))

内置丰富的音乐知识库：
- 12+ 位知名歌手及其热门歌曲
- 16+ 种音乐风格识别
- 30+ 首中国风歌曲库
- 支持排行榜发现、网络搜索发现、相似歌手发现

### 网络搜索工具 ([`src/search_tools.py`](src/search_tools.py))

无需 API 密钥即可使用 DuckDuckGo 免费搜索：
- `search_web()` - 通用网络搜索
- `search_music_news()` - 音乐资讯
- `fetch_page_content()` - 网页内容提取
- 支持 SerpAPI / Google Custom Search / Bing Search（可选）

### 下载引擎 ([`src/smart_downloader.py`](src/smart_downloader.py))

- 串行逐源搜索，搜到即停
- 音质自动回退（flac→ape→wav→mp3→auto）
- 跨音源重试 + 源级熔断
- 歌名/歌手变体搜索
- 并发队列下载、自动打包

---

## 🐙 GitHub Actions 使用

### 1. AI 智能助手工作流（推荐，browser-act 搜索）

进入 **Actions** → **🤖 AI 智能音乐助手** → **Run workflow**

| 参数 | 说明 |
|------|------|
| 🎯 任务目标 | 用自然语言描述你的需求 |
| 🔊 首选音源 | QQMusicClient / NeteaseMusicClient |
| 🎵 音质 | flac / mp3 / ape / wav / aac |
| 📊 最大歌曲数 | 限制发现的歌曲数量 |
| ⚡ 并发下载数 | 同时下载的歌曲数 |
| 🔍 仅发现模式 | 只搜索不下载 |

> **建议配置仓库 Secrets（可选但推荐）**：
> - `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` - 启用 AI 智能理解
> - `SERPAPI_KEY` - 增强网络搜索能力

### 2. 传统工作流

| 工作流 | 说明 |
|--------|------|
| `智能歌曲下载` | 从 song-queue.txt 或手动输入下载 |
| `歌单下载` | 输入歌单 URL 解析下载 |
| `热歌榜下载` | 从排行榜下载，支持定时自动运行 |
| `列出音源榜单` | 查看可用排行榜 |

### 设置 Secrets（用于 AI 增强）

1. GitHub 仓库 → **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**
3. 添加以下密钥（均为可选）：

| Secret 名称 | 说明 | 必填 |
|-------------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（推荐） | 否 |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 否 |
| `BROWSERACT_API_KEY` | BrowserAct API key（免费注册，用于 stealth 浏览器搜索） | 否 |

> **关于搜索**: 默认使用 `browser-act` chrome 模式搜索 Google（无需任何 API key）。
> 如果注册 BrowserAct 并设置 `BROWSERACT_API_KEY`，将自动启用 stealth-extract 模式，
> 可突破反爬虫机制搜索 Google/Bing 等引擎。
> SerpAPI 已不再需要使用。

---

## 💡 使用示例

### AI 助手示例

```bash
# 自然语言驱动
python src/ai_assistant.py --task "找一些陈奕迅和林俊杰的经典歌曲"
python src/ai_assistant.py --task "我喜欢民谣和独立音乐，推荐一些"

# 排行榜 + 高级选项
python src/ai_assistant.py --task "从QQ热歌榜下载前20首" --quality mp3 --workers 5

# 智能歌手发现
python src/ai_assistant.py --task "找和洛天依风格相似的虚拟歌手歌曲"
```

### 音乐发现引擎示例

```bash
# 按口味发现
python src/music_discovery.py --taste "我喜欢周杰伦的中国风和洛天依的电音" --save

# 发现歌手热门歌曲
python src/music_discovery.py --artist "周杰伦" --max-songs 30

# 按风格发现
python src/music_discovery.py --style "民谣" --save

# 从排行榜发现
python src/music_discovery.py --chart qq_hot --max-songs 50

# 列出内置歌手库
python src/music_discovery.py --list-artists
```

### 搜索工具示例

```bash
# 测试网络搜索
python -m src.search_tools

# 命令行使用
python src/ai_assistant.py --task "搜索最近流行的英文歌曲" --no-download
```

---

## ⚙️ 高级配置

### 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `BROWSERACT_API_KEY` | BrowserAct API key（免费注册，用于 stealth 浏览器搜索） |
| `SERPAPI_KEY` | （保留向后兼容）SerpAPI 密钥，已不推荐使用 |
| `GOOGLE_API_KEY` | Google Custom Search API 密钥 |
| `GOOGLE_CSE_ID` | Google Custom Search Engine ID |
| `BING_API_KEY` | Bing Search API 密钥 |

### 扩展内置知识库

编辑 [`src/music_discovery.py`](src/music_discovery.py) 中的 `BUILTIN_ARTISTS` 字典即可添加自定义歌手和歌曲。

---

## 📝 技术栈

- **Python 3.11+**
- [musicdl](https://github.com/CharlesPikachu/musicdl) - 多音源音乐搜索下载库
- **GitHub Actions** - 持续集成/自动化运行
- **browser-act** - 无头浏览器搜索（Google/Bing，无需 API key）
- **DuckDuckGo** - 零配置搜索后备
- **DeepSeek / OpenAI API** - AI 增强理解（可选）
