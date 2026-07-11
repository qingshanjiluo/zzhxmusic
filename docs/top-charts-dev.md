# `--top-charts` 排行榜下载功能 开发文档

## 概述

为智能下载器（`smart_downloader.py`）新增 `--top-charts` 排行榜下载功能，支持从 QQ 音乐和网易云音乐获取排行榜歌曲列表，并下载到本地。

## 设计原则

1. **零耦合**：排行榜功能不依赖 `musicdl` 库，仅使用 `requests` HTTP 请求获取榜单数据
2. **可扩展**：新增排行榜只需在 `TOP_CHARTS` 字典中添加条目，无需修改代码逻辑
3. **别名系统**：支持中文别名（热歌榜）和英文别名（hot）查找，用户无需记忆键名
4. **模块级分离**：`TOP_CHARTS` 和 `list_top_charts()` 为模块级常量/函数，避免实例化 `SmartDownloader` 时才初始化

## 文件变更

### [`batch-music-downloader/src/smart_downloader.py`](../src/smart_downloader.py)

#### 1. 模块级常量 `TOP_CHARTS` (行 ~66)

```python
TOP_CHARTS = {
    'qq_hot': {'name': 'QQ热歌榜', 'source': 'QQ', ...},
    'netease_hot': {'name': '网易云热歌榜', 'source': 'Netease', ...},
    ...
}
TOP_CHARTS_ALIASES = {
    '热歌榜': 'qq_hot', 'hot': 'qq_hot', ...
}
```

- **位置**：`class SmartDownloader` 之前，模块加载时即可访问
- **格式**：每个条目包含 `name`（显示名）、`source`（API 标识）、`api`（请求 URL）、`params`（查询参数）
- **QQ API**：`https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?topid={id}&format=json`
- **网易云 API**：`https://music.163.com/api/playlist/detail?id={id}`

#### 2. 模块级函数 `list_top_charts()` (行 ~112)

```python
def list_top_charts():
    """列出所有可用的排行榜（模块级函数，不依赖 musicdl）"""
```

- 遍历 `TOP_CHARTS`，按音源分组展示
- 输出示例：
  ```
  ============================================================
    可用排行榜列表
  ============================================================
    QQ音乐:
      qq_hot                QQ热歌榜
      qq_new                QQ新歌榜
      ...
    网易云音乐:
      netease_hot           网易云热歌榜
      ...
  ```

#### 3. `SmartDownloader.list_top_charts()` (行 ~276)

```python
def list_top_charts(self):
    """列出所有可用的排行榜（委托模块级函数）"""
    list_top_charts()  # 直接委托
```

#### 4. `SmartDownloader.get_top_chart()` (行 ~280)

```python
def get_top_chart(self, chart_key: str, limit: int = 0) -> List[Dict[str, str]]:
```

**参数**：
- `chart_key`：排行榜键名（如 `qq_hot`）或别名（如 `热歌榜`, `hot`）
- `limit`：限制返回数量，0=全部

**返回值**：`[{'title': str, 'artist': str}, ...]`

**解析逻辑**：

QQ 音乐榜：
```python
data.get('songlist', [])[i]['data']['songname']  # 歌名
data['songlist'][i]['data']['singer'][j]['name']  # 歌手（数组）
```

网易云榜：
```python
data['result']['tracks'][i]['name']       # 歌名
data['result']['tracks'][i]['artists'][j]['name']  # 歌手（数组）
```

**错误处理**：
- `requests.exceptions.Timeout` → 打印超时信息
- `requests.exceptions.ConnectionError` → 打印连接失败
- 通用异常 → 打印错误信息

#### 5. CLI 参数 (行 ~991)

```python
parser.add_argument('--top-charts', type=str, default='',
    help='下载指定排行榜（如 qq_hot, netease_new, 热歌榜）')
parser.add_argument('--list-top-charts', action='store_true',
    help='列出所有可用的排行榜')
parser.add_argument('--chart-limit', type=int, default=0,
    help='排行榜模式下限制获取的歌曲数量（0=全部）')
```

#### 6. Main 路由逻辑 (行 ~1055)

```python
# 先处理纯展示模式（排行榜不需要 musicdl）
if args.list_top_charts:
    list_top_charts()
    sys.exit(0)

# 收集歌曲阶段
if args.file:
    ...
elif args.text:
    ...
elif args.playlist_url:
    ...
elif args.top_charts:
    downloader = SmartDownloader(...)
    songs = downloader.get_top_chart(args.top_charts, limit=args.chart_limit)
    if not songs:
        sys.exit(1)
else:
    parser.print_help()
    sys.exit(1)
```

### 3. `musicdl` 导入改为可选 (行 ~46)

```python
MUSICDL_AVAILABLE = False
MusicClient = None
try:
    from musicdl.musicdl import MusicClient
    MUSICDL_AVAILABLE = True
except ImportError:
    try:
        from musicdl import musicdl as _musicdl_mod
        MusicClient = _musicdl_mod.MusicClient
        MUSICDL_AVAILABLE = True
    except (ImportError, AttributeError):
        pass  # 排行榜功能仍可正常使用
```

- 不再 `sys.exit(1)`，改为 `MUSICDL_AVAILABLE = False`
- `_init_client()` 检查此标志：`if not MUSICDL_AVAILABLE: return`
- 用户看到 `"警告: musicdl 未安装，仅排行榜功能可用"`

### 4. Windows GBK 兼容性修复

替换所有无法在 GBK 终端显示的 Unicode 字符：

| 原字符 | 替换为 |
|--------|--------|
| `▶` | `==>` |
| `─` | `-` |
| `├─` | `+-` |
| `│` | `|` |
| `└─` | `+-` |
| `✓` | `[OK]` |
| `✗` | `[X]` |
| `✅` | `[OK]` |
| `❌` | `[FAIL]` |
| `⏭️` | `[SKIP]` |
| `❓` | `[NF]` |

## 支持的排行榜

### QQ 音乐 (6 个)

| 键名 | 显示名 | topid |
|------|--------|-------|
| `qq_hot` | QQ热歌榜 | 4 |
| `qq_new` | QQ新歌榜 | 27 |
| `qq_pop` | QQ流行榜 | 26 |
| `qq_mainland` | QQ内地榜 | 5 |
| `qq_europe` | QQ欧美榜 | 3 |
| `qq_korea` | QQ韩国榜 | 16 |

### 网易云音乐 (4 个)

| 键名 | 显示名 | playlist id |
|------|--------|-------------|
| `netease_hot` | 网易云热歌榜 | 3778678 |
| `netease_new` | 网易云新歌榜 | 3779629 |
| `netease_soar` | 网易云飙升榜 | 19723756 |
| `netease_orig` | 网易云原创榜 | 2884035 |

## 别名系统

```python
TOP_CHARTS_ALIASES = {
    '热歌榜': 'qq_hot',      'hot': 'qq_hot',
    '新歌榜': 'qq_new',      'new': 'qq_new',
    '流行榜': 'qq_pop',      'pop': 'qq_pop',
    '内地榜': 'qq_mainland', '欧美榜': 'qq_europe',
    '韩国榜': 'qq_korea',
    '飙升榜': 'netease_soar', 'soar': 'netease_soar',
    '原创榜': 'netease_orig', 'orig': 'netease_orig',
    '网易云热歌榜': 'netease_hot', '网易云新歌榜': 'netease_new',
}
```

支持三种别名格式：
- 中文全称：`热歌榜`, `新歌榜`, `飙升榜`...
- 英文简称：`hot`, `new`, `soar`...
- 平台前缀：`网易云热歌榜`, `网易云新歌榜`...

## 使用示例

```bash
# 列出可用排行榜
python smart_downloader.py --list-top-charts

# 下载 QQ 热歌榜前 20 首（使用键名）
python smart_downloader.py --top-charts qq_hot --chart-limit 20

# 使用中文别名
python smart_downloader.py --top-charts 热歌榜 --chart-limit 10

# 下载网易云飙升榜全部歌曲
python smart_downloader.py --top-charts netease_soar

# 排行榜 + 品质 + 输出目录
python smart_downloader.py --top-charts 新歌榜 --chart-limit 50 -q mp3 -o ./top50
```

## 测试验证

```bash
# 1. 语法检查
python -m py_compile smart_downloader.py

# 2. 列表展示（不需 musicdl）
python smart_downloader.py --list-top-charts

# 3. 获取数据 + 下载（需 musicdl）
python smart_downloader.py --top-charts qq_hot --chart-limit 5

# 4. 别名解析测试
python smart_downloader.py --top-charts 热歌榜 --chart-limit 3
python smart_downloader.py --top-charts hot --chart-limit 3
```

## 扩展指南

添加新的排行榜只需在 `TOP_CHARTS` 中添加条目：

```python
# 示例：新增 Kugou 飙升榜
'kugou_soar': {
    'name': '酷狗飙升榜',
    'source': 'Kugou',
    'api': 'https://www.kugou.com/yy/rank/home/...',
    'params': {'json': 'true'},
}
```

然后在 `ALIASES` 中注册别名：

```python
'酷狗飙升榜': 'kugou_soar', 'ksoar': 'kugou_soar',
```

如果 API 返回格式不同，需要在 `get_top_chart()` 中添加新的解析分支。

## 约束条件

| 项目 | 值 |
|------|-----|
| 依赖 | `requests`（标准库） |
| musicdl 依赖 | **否**（排行榜独立可用） |
| 并发 | 无（单次 HTTP 请求） |
| 限流 | 无（官方公开 API） |
| 超时 | 15 秒 |
