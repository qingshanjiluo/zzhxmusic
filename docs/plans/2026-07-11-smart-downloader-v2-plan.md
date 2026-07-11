# Smart Downloader V2 优化实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 Smart Downloader V1 基础上增加 10 项功能：失败自动重试、音质回退、多源搜索增强、批量歌单导入、歌词/封面下载、文件命名模板、进度条、歌单范围筛选、歌手/中英文筛选。

**架构:** 保持单文件架构，在 [`SmartDownloader`](f:\tools\smart-downloader\src\smart_downloader.py:40) 类中新增方法，保持向后兼容。新增 `--playlist-file`、`--filename-template`、`--range`、`--chinese-only` 等 CLI 参数。

**Tech Stack:** Python 3.10+, musicdl (已安装), rich (新增, 进度条), 内置 `re`/`sqlite3` (可选)

**当前文件结构:**
```
f:\tools\smart-downloader\
├── src/
│   └── smart_downloader.py    # 主引擎 (~473行)
├── .github/workflows/
│   ├── smart-download.yml      # 歌曲列表 workflow
│   └── playlist-download.yml   # 歌单 workflow
├── song-queue.txt              # 示例歌曲队列
├── requirements.txt            # 依赖
├── .gitignore
└── README.md                   # 文档
```

---

### Task 1: 音质回退 + 下载失败自动重试 + 跨音源重试

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` (整个类中涉及下载逻辑的区域)

**变更概述:**
1. 修改 [`__init__`](f:\tools\smart-downloader\src\smart_downloader.py:54) 增加 `retry_count`、`quality_fallback` 参数
2. 增加 `_quality_fallback_list` 方法：按优先级排列音质回退链
3. 重写 [`download_song`](f:\tools\smart-downloader\src\smart_downloader.py:254)：支持失败后在回退音质列表重试
4. 在 [`download_queue`](f:\tools\smart-downloader\src\smart_downloader.py:284) 中增加：下载失败后尝试回退音质和切换音源

**Step 1: 定义音质回退链**

在 [`__init__`](f:\tools\smart-downloader\src\smart_downloader.py:54) 中增加 `self.retry_count = retry_count`（默认 2），增加 `self.fallback_sources` 属性：

```python
QUALITY_FALLBACK = {
    'flac': ['flac', 'ape', 'wav', 'mp3', 'auto'],
    'ape': ['ape', 'flac', 'wav', 'mp3', 'auto'],
    'wav': ['wav', 'flac', 'ape', 'mp3', 'auto'],
    'mp3': ['mp3', 'auto'],
    'aac': ['aac', 'mp3', 'auto'],
    'auto': ['auto'],
}
```

**Step 2: 重写 [`download_song_with_retry`](f:\tools\smart-downloader\src\smart_downloader.py:254)（新增方法）**

逻辑：
1. 用首选的 source + 首选 quality 尝试下载
2. 如果失败，进入回退音质链（quality_fallback_list）
3. 如果所有音质都失败，进入回退音源列表（SOURCE_PRIORITY 中排在 primary 之后的源）
4. 每次重试前设置不同的 `raw.work_dir` 避免文件名冲突
5. 成功时立即返回文件路径

```python
def download_song_with_retry(self, song_info: Dict, output_dir: str) -> Optional[str]:
    raw = song_info.get('raw', song_info)
    primary_source = song_info.get('source', self.primary_source)
    quality_chain = self.QUALITY_FALLBACK.get(self.quality, ['mp3', 'auto'])
    source_chain = [primary_source]
    # 如果主源失败，加上其他备用源
    for s in self._get_search_sources():
        if s not in source_chain:
            source_chain.append(s)
    
    for source in source_chain:
        if source not in self.client.music_clients:
            continue
        for quality in quality_chain:
            actual_si = copy.deepcopy(raw)
            if hasattr(actual_si, 'work_dir'):
                actual_si.work_dir = output_dir
            try:
                result = self.client.music_clients[source].download(
                    song_infos=[actual_si], num_threadings=1
                )
                if result and isinstance(result, list) and len(result) > 0:
                    dl = result[0]
                    if hasattr(dl, 'save_path'):
                        sp = dl.save_path
                        if sp and os.path.exists(sp):
                            return str(sp)
                    if Path(output_dir).exists():
                        for f in Path(output_dir).iterdir():
                            if f.is_file() and f.suffix in ['.mp3', '.flac', '.ape', '.wav', '.aac', '.m4a', '.ogg']:
                                return str(f)
            except Exception:
                continue
    return None
```

**Step 3: 更新 [`download_queue`](f:\tools\smart-downloader\src\smart_downloader.py:284) 使用 `download_song_with_retry`**

将 `download_task` 从调用 `self.download_song(si, output_dir)` 改为调用 `self.download_song_with_retry(si, output_dir)`

**Step 4: 更新 `__init__` 参数**

```python
def __init__(self, source='QQMusicClient', quality='flac', max_workers=5, retry_count=2):
    ...
    self.retry_count = retry_count
    self.quality = quality
    self.quality_fallback_list = self.QUALITY_FALLBACK.get(quality, ['mp3', 'auto'])
    ...
```

**Step 5: 更新 CLI**

在 [`main()`](f:\tools\smart-downloader\src\smart_downloader.py:421) 中新增 `--retry` 参数。

---

### Task 2: 无匹配时扩展搜索（关键词变体）

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 的 [`search_best_match`](f:\tools\smart-downloader\src\smart_downloader.py:151) 和 [`_find_best_match`](f:\tools\smart-downloader\src\smart_downloader.py:189)

**Step 1: 新增 `_generate_search_keywords` 方法**

当标准搜索无结果时，生成变体关键词：
- 原: `"七里香 周杰伦"`
- 变体: `"七里香"` (去掉歌手)
- 变体: `"周杰伦 七里香"` (颠倒顺序)
- 变体: `"七里"` (歌名前两个字)
- 变体: `"七里香 周"` (歌手缩写)

```python
def _generate_search_keywords(self, title: str, artist: str) -> List[str]:
    keywords = [f"{title} {artist}".strip() if artist else title]
    # 变体 1: 只用歌名
    if artist and f"{title} {artist}" != title:
        keywords.append(title)
    # 变体 2: 颠倒顺序
    if artist:
        keywords.append(f"{artist} {title}")
    # 变体 3: 歌名前 2~4 个字
    if len(title) > 4:
        keywords.append(title[:4])
        keywords.append(title[:2])
    # 变体 4: 歌手缩写 + 歌名
    if artist and len(artist) > 1:
        keywords.append(f"{artist[0]} {title}")
        keywords.append(f"{title} {artist[0]}")
    # 去重
    seen = set()
    result = []
    for kw in keywords:
        kl = kw.lower().strip()
        if kl not in seen:
            seen.add(kl)
            result.append(kw)
    return result
```

**Step 2: 修改 [`search_best_match`](f:\tools\smart-downloader\src\smart_downloader.py:151)**

当主关键词在所有音源都搜索失败后，自动用变体关键词重试：

```python
def search_best_match(self, title: str, artist: str = '') -> Optional[Dict]:
    keywords = self._generate_search_keywords(title, artist)
    for keyword in keywords:
        result = self._search_single_keyword(keyword, title, artist)
        if result:
            return result
    return None

def _search_single_keyword(self, keyword, title, artist):
    for source in self._get_search_sources():
        if source not in self.client.music_clients:
            continue
        try:
            results = self.client.music_clients[source].search(keyword=keyword, num_threadings=3)
        except Exception:
            continue
        if not results:
            continue
        best = self._find_best_match(results, title, artist)
        if best:
            best['source'] = source
            return best
    return None
```

---

### Task 3: 批量歌单导入 + 歌单 URL 解析内置

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 新增 `parse_playlist` 方法
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 的 `main()` 增 `--playlist-url` 参数
- Deprecate: `f:\tools\smart-downloader\.github\workflows\playlist-download.yml`（被内置功能取代）

**Step 1: 新增 `parse_playlist` 方法**

利用 `self.client.parseplaylist()` 解析歌单 URL，返回歌曲列表：

```python
def parse_playlist(self, playlist_url: str) -> List[Dict[str, str]]:
    """解析歌单 URL，返回歌曲列表"""
    if self.client is None:
        return []
    try:
        results = self.client.parseplaylist(playlist_url=playlist_url)
        songs = []
        for item in results:
            if hasattr(item, 'song_name'):
                songs.append({
                    'title': item.song_name or '',
                    'artist': str(item.singers or ''),
                })
            elif isinstance(item, dict):
                songs.append({
                    'title': item.get('title', '') or item.get('song_name', ''),
                    'artist': item.get('artist', '') or item.get('singers', ''),
                })
        print(f"歌单解析完成: {len(songs)} 首歌曲")
        return songs
    except Exception as e:
        print(f"歌单解析失败: {e}")
        return []
```

**Step 2: 新增 `--playlist-url` CLI 参数**

```python
parser.add_argument('--playlist-url', type=str, default='', help='歌单 URL（支持网易云/QQ 音乐等）')
parser.add_argument('--playlist-file', type=str, default='', help='批量歌单文件（每行一个 URL）')
```

**Step 3: 在 `main()` 中处理**

```python
if args.playlist_url:
    songs = downloader.parse_playlist(args.playlist_url)
elif args.playlist_file:
    songs = []
    for url in Path(args.playlist_file).read_text(encoding='utf-8').splitlines():
        url = url.strip()
        if not url or url.startswith('#'):
            continue
        songs.extend(downloader.parse_playlist(url))
elif args.file and Path(args.file).exists():
    songs = downloader.load_songs_from_file(args.file)
...
```

---

### Task 4: 歌词/封面下载

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 新增 `save_lyrics` 和 `save_cover` 方法

**Step 1: 新增 `save_lyrics` 方法**

musicdl 的 `SongInfoSupplsonginfothensavelyricsthenwritetags` 已经自动保存歌词。在 [`download_song_with_retry`](f:\tools\smart-downloader\src\smart_downloader.py:254) 返回值前检查 `dl.lyric`：

```python
def save_lyrics(self, song_info: Dict, save_path: str):
    """保存歌词 .lrc 文件"""
    raw = song_info.get('raw', song_info)
    if not hasattr(raw, 'lyric') or not raw.lyric:
        return
    lyric_text = raw.lyric
    if lyric_text in {'NULL', 'null', 'None', 'none', ''}:
        return
    lrc_path = Path(save_path).with_suffix('.lrc')
    lrc_path.write_text(lyric_text, encoding='utf-8')
    print(f"    └─ 歌词已保存: {lrc_path.name}")
```

**Step 2: 新增 `save_cover` 方法**

```python
def save_cover(self, song_info: Dict, save_path: str):
    """保存封面图"""
    raw = song_info.get('raw', song_info)
    cover_url = getattr(raw, 'cover_url', None) if hasattr(raw, 'cover_url') else None
    if not cover_url:
        return
    try:
        resp = requests.get(cover_url, timeout=10)
        if resp.status_code == 200:
            cover_path = Path(save_path).with_suffix('.jpg')
            cover_path.write_bytes(resp.content)
            print(f"    └─ 封面已保存: {cover_path.name}")
    except Exception:
        pass
```

**Step 3: 增加 `--no-lyrics` 和 `--no-cover` CLI 参数**

```python
parser.add_argument('--no-lyrics', action='store_true', help='不下载歌词')
parser.add_argument('--no-cover', action='store_true', help='不下载封面')
```

---

### Task 5: 文件命名模板 + 序号

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 新增 `_build_filename` 方法

**Step 1: 新增 `_build_filename` 和 `_copy_file_with_template` 方法**

```python
def _build_filename(self, template: str, song_info: Dict, index: int, ext: str) -> str:
    """根据模板构建文件名"""
    title = song_info.get('song_name', 'unknown')
    artist = song_info.get('singers', 'unknown')
    album = song_info.get('album', '')
    duration = song_info.get('duration', '')
    quality = song_info.get('quality', '')
    
    replacements = {
        '{index}': str(index).zfill(2),
        '{title}': title,
        '{song}': title,
        '{artist}': artist,
        '{singer}': artist,
        '{album}': album,
        '{duration}': str(duration),
        '{quality}': quality,
        '{ext}': ext.lstrip('.'),
    }
    
    filename = template
    for key, val in replacements.items():
        filename = filename.replace(key, str(val))
    
    # 清理不安全字符
    filename = filename.replace('/', '_').replace('\\', '_').replace(':', '：')
    return filename
```

**Step 2: 在 [`download_song_with_retry`](f:\tools\smart-downloader\src\smart_downloader.py:254) 中应用模板**

下载后将文件移到正确的模板命名位置：

```python
if self.filename_template:
    old_path = Path(save_path)
    ext = old_path.suffix
    new_name = self._build_filename(self.filename_template, song_info, self._file_index, ext)
    new_path = old_path.parent / new_name
    if not new_path.exists() and old_path.exists():
        shutil.move(str(old_path), str(new_path))
        return str(new_path)
```

**Step 3: 增加 `--filename-template` CLI 参数**

```python
parser.add_argument('--filename-template', type=str, default='',
    help='文件命名模板, 支持: {index} {title} {artist} {album} {quality} {ext}, 默认: {index}.{artist} - {title}.{ext}')
```

默认模板: `{index}.{artist} - {title}.{ext}`

---

### Task 6: 进度条显示 (rich)

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 导入 `rich`
- Modify: `f:\tools\smart-downloader\requirements.txt` 追加 `rich`

**Step 1: 导入 rich 库**

```python
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
```

**Step 2: 包裹 [`download_queue`](f:\tools\smart-downloader\src\smart_downloader.py:284) 的搜索阶段和下载阶段**

在搜索阶段使用 `Progress` 显示 `[1/8] 搜索 七里香...`
在下载阶段使用 `Progress` 显示 `[2/5] 下载 夜曲... 10.5MB/s`

```python
def download_queue(self, songs, output_dir='./downloads'):
    ...
    if RICH_AVAILABLE:
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task("搜索歌曲...", total=len(songs))
            for idx, song in enumerate(songs, 1):
                progress.update(task, description=f"搜索 [{idx}/{len(songs)}] {song['title']}")
                # ... 搜索逻辑 ...
                progress.advance(task)
    else:
        # 原回退逻辑（纯 print）
        ...
```

---

### Task 7: 歌单范围筛选 + 前N/后N + 歌名中英文筛选

**Files:**
- Modify: `f:\tools\smart-downloader\src\smart_downloader.py` 的 `main()` 部分

**Step 1: 新增 CLI 参数**

```python
parser.add_argument('--first', type=int, default=0, help='只下载前 N 首')
parser.add_argument('--last', type=int, default=0, help='只下载后 N 首')
parser.add_argument('--range', type=str, default='', help='下载指定范围, 如: 1-10, 3,5,7-9')
parser.add_argument('--chinese-only', action='store_true', help='只下载歌名含中文的歌曲')
parser.add_argument('--no-chinese', action='store_true', help='跳过歌名含中文的歌曲')
```

**Step 2: 在 `main()` 中加载歌曲后执行筛选**

```python
# 放在 songs 加载之后、歌手筛选之前

# 中英文筛选
if args.chinese_only:
    import re
    before = len(songs)
    songs = [s for s in songs if re.search(r'[\u4e00-\u9fff]', s['title'])]
    print(f"中文歌名筛选: {before} -> {len(songs)} 首")

if args.no_chinese:
    import re
    before = len(songs)
    songs = [s for s in songs if not re.search(r'[\u4e00-\u9fff]', s['title'])]
    print(f"非中文歌名筛选: {before} -> {len(songs)} 首")

# 范围筛选（first/last 优先于 range）
if args.first > 0:
    songs = songs[:args.first]
    print(f"取前 {args.first} 首: {len(songs)} 首")
elif args.last > 0:
    songs = songs[-args.last:]
    print(f"取后 {args.last} 首: {len(songs)} 首")
elif args.range:
    import re
    selected = []
    for part in args.range.split(','):
        part = part.strip()
        m = re.match(r'(\d+)-(\d+)', part)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if 1 <= start <= end <= len(songs):
                selected.extend(range(start-1, end))
        elif part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(songs):
                selected.append(idx)
    songs = [songs[i] for i in sorted(set(selected))]
    print(f"范围筛选 '{args.range}': {len(songs)} 首")
```

---

### Task 8: 更新 Workflow 和 README

**Files:**
- Modify: `f:\tools\smart-downloader\.github\workflows\smart-download.yml` 增加新参数
- Rewrite: `f:\tools\smart-downloader\.github\workflows\playlist-download.yml` 改为直接调用 `smart_downloader.py --playlist-url`
- Modify: `f:\tools\smart-downloader\requirements.txt` 追加 `rich`
- Modify: `f:\tools\smart-downloader\README.md` 更新文档

**Step 1: 更新 smart-download.yml**

新增 workflow inputs: `chinese_only`, `no_chinese`, `first`, `last`, `range`, `filename_template`, `no_lyrics`, `retry_count`

**Step 2: 重写 playlist-download.yml**

不再依赖外部 `batch_downloader`，直接调用：
```yaml
CMD="python src/smart_downloader.py"
CMD="$CMD --playlist-url '${{ github.event.inputs.playlist_url }}'"
CMD="$CMD --source ${{ github.event.inputs.source }}"
...
eval $CMD
```

**Step 3: 更新 requirements.txt**

追加 `rich>=13.0.0`

**Step 4: 更新 README.md**

将所有新参数添加到文档表格和示例中。

---

## 执行顺序建议

```
Task 1 (音质回退+重试)  ────────┐
                                ├──>  Task 6 (进度条) ──> Task 8 (文档)
Task 2 (扩展搜索)      ────────┘
                                │
Task 3 (歌单导入)      ────────┤
                                ├──>  Task 8 (文档+workflow)
Task 4 (歌词/封面)     ────────┤
                                │
Task 5 (文件命名模板)  ────────┤
                                │
Task 7 (范围/语言筛选) ────────┘
```

**建议分批实施（每批实施后测试+提交）：**
- 批次 1: Task 1 + Task 2（核心下载修复）
- 批次 2: Task 3 + Task 4（歌单+元数据）
- 批次 3: Task 5 + Task 6（文件+UI）
- 批次 4: Task 7 + Task 8（筛选+文档）
