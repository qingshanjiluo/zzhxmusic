# 智能音乐下载器 (Smart Downloader) 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**目标:** 创建一个基于 GitHub Actions 的全自动音乐下载工具，解决下载时间长、重复下载、不能排队三大痛点

**架构:** 
- 核心引擎 `smart_downloader.py` 实现串行逐源搜索（搜到即停）、内存去重、并发队列下载
- 两个独立的 GitHub Actions Workflow: `smart-download.yml`（歌曲列表模式）和 `playlist-download.yml`（歌单模式）
- 输入支持 `song-queue.txt` 文件和 workflow 参数两种方式
- 下载产物自动打包为 ZIP 上传到 Artifacts

**技术栈:** Python 3.11+, musicdl (音乐源库), GitHub Actions (CI/CD), zipfile (标准库打包)

**目录结构:**
```
batch-music-downloader/
├── .github/workflows/
│   ├── smart-download.yml           # 歌曲列表下载 workflow
│   └── playlist-download.yml        # 歌单下载 workflow
├── src/
│   ├── smart_downloader.py          # 核心引擎（新文件）
│   ├── batch_downloader.py          # 保留原文件
│   └── config.py                    # 保留原配置
├── song-queue.txt                   # 示例歌曲列表文件（新文件）
├── config.json                      # 保留原配置文件
├── requirements.txt                 # 更新依赖
└── README.md                        # 更新文档
```

---

### Task 1: 创建核心引擎 `smart_downloader.py`

**文件:**
- Create: `batch-music-downloader/src/smart_downloader.py`

**Step 1: 编写完整的 smart_downloader.py**

这是核心引擎，包含以下功能模块：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Downloader - 智能音乐下载器
基于 musicdl 实现自动化搜索、去重、排队下载

特性:
  - 串行逐源搜索，搜到符合条件的第一个结果即停（速度优先）
  - 基于歌名+歌手的内存去重（当次运行内不重复下载）
  - 并发队列下载，自动排队
  - 支持 song-queue.txt 文件和 workflow 参数两种输入
  - 下载报告自动生成
"""

import sys
import os
import json
import zipfile
import argparse
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 添加项目根目录到路径
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

try:
    from musicdl import musicdl
except ImportError:
    print("错误: 未安装 musicdl")
    print("请运行: pip install musicdl")
    sys.exit(1)


class SmartDownloader:
    """智能音乐下载器"""

    # 默认音源搜索优先级（串行搜索，搜到即停）
    SOURCE_PRIORITY = [
        'QQMusicClient',
        'NeteaseMusicClient',
        'KuwoMusicClient',
        'KugouMusicClient',
        'MiguMusicClient',
        'QianqianMusicClient',
        'SoundCloudClient',
        'YouTubeMusicClient',
    ]

    def __init__(self, source: str = 'QQMusicClient', quality: str = 'flac', max_workers: int = 5):
        """
        初始化下载器
        Args:
            source: 首选音源（搜不到时自动切换下一个）
            quality: 音质偏好
            max_workers: 最大并发下载数
        """
        self.primary_source = source
        self.quality = quality
        self.max_workers = max_workers
        self.client = None
        self.downloaded_set: Set[str] = set()  # 去重集合: "歌名|歌手"
        self.results = {
            'success': [],   # 成功下载的歌曲
            'failed': [],    # 下载失败的歌曲
            'skipped': [],   # 去重跳过的歌曲
            'notfound': [],  # 搜索不到的歌曲
        }
        self._init_client()

    def _init_client(self):
        """初始化 musicdl 客户端（懒加载，用到时才初始化具体音源）"""
        # 只初始化首选音源 + 备用音源
        all_sources = self._get_search_sources()
        init_cfg = {src: {'search_size_per_source': 5} for src in all_sources}
        try:
            self.client = musicdl.MusicClient(
                music_sources=all_sources,
                init_music_clients_cfg=init_cfg
            )
        except Exception as e:
            print(f"错误: 初始化客户端失败 - {e}")
            self.client = None

    def _get_search_sources(self) -> List[str]:
        """获取搜索音源列表（首选音源排第一）"""
        sources = [self.primary_source]
        for src in self.SOURCE_PRIORITY:
            if src != self.primary_source:
                sources.append(src)
        return sources

    # ========== 输入解析 ==========

    def load_songs_from_file(self, filepath: str) -> List[Dict[str, str]]:
        """
        从 song-queue.txt 文件读取歌曲列表
        格式: "歌名, 歌手" 或 "歌名 歌手" 或 "歌名\t歌手"
        支持 # 注释
        """
        songs = []
        filepath = Path(filepath)
        if not filepath.exists():
            print(f"错误: 文件不存在 - {filepath}")
            return songs

        # 尝试多种编码
        content = None
        for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312']:
            try:
                content = filepath.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            content = filepath.read_text(encoding='utf-8', errors='ignore')

        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 检测分隔符: 逗号 > 制表符 > 空格
            if ',' in line:
                parts = line.split(',', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                parts = line.split(' ', 1)

            title = parts[0].strip()
            artist = parts[1].strip() if len(parts) > 1 else ''

            if not title:
                print(f"警告: 第 {line_num} 行格式无效，已跳过: {line}")
                continue

            songs.append({'title': title, 'artist': artist})

        print(f"从文件加载了 {len(songs)} 首歌曲")
        return songs

    def load_songs_from_text(self, text: str) -> List[Dict[str, str]]:
        """
        从文本字符串读取歌曲列表
        支持多行，格式同上
        """
        songs = []
        for line_num, line in enumerate(text.strip().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ',' in line:
                parts = line.split(',', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                parts = line.split(' ', 1)

            title = parts[0].strip()
            artist = parts[1].strip() if len(parts) > 1 else ''

            if not title:
                continue

            songs.append({'title': title, 'artist': artist})

        print(f"从文本加载了 {len(songs)} 首歌曲")
        return songs

    # ========== 搜索（串行逐源，搜到即停） ==========

    def search_best_match(self, title: str, artist: str = '') -> Optional[Dict]:
        """
        串行逐源搜索，搜到第一个匹配结果即停止
        搜索策略:
          1. 先用完整 "歌名 歌手" 搜索
          2. 在每个音源的结果中匹配歌名+歌手
          3. 找到第一个匹配就返回，不再继续搜索其他音源

        Args:
            title: 歌曲名
            artist: 歌手名（可选）

        Returns:
            匹配的 SongInfo 或 None
        """
        if self.client is None:
            return None

        keyword = f"{title} {artist}".strip() if artist else title
        search_sources = self._get_search_sources()

        print(f"  ├─ 搜索 '{keyword}'...")

        for source in search_sources:
            if source not in self.client.music_clients:
                continue

            try:
                # 只搜索当前音源
                results = self.client.music_clients[source].search(
                    keyword=keyword,
                    num_threadings=3
                )
            except Exception as e:
                print(f"  │  └─ {source} 搜索出错: {e}")
                continue

            if not results:
                print(f"  │  └─ {source}: 无结果")
                continue

            # 在结果中匹配歌名+歌手
            best_match = self._find_best_match(results, title, artist)
            if best_match:
                print(f"  │  └─ ✓ {source}: 找到匹配 → {best_match.get('song_name', '')} - {best_match.get('singers', '')}")
                # 注入 source 信息
                best_match['source'] = source
                return best_match

            print(f"  │  └─ {source}: 无匹配结果")

        print(f"  └─ ✗ 所有音源均未找到匹配")
        return None

    def _find_best_match(self, results: List, title: str, artist: str) -> Optional[Dict]:
        """
        在搜索结果中找最佳匹配
        匹配规则: 歌名包含搜索关键词，歌手（如果提供）包含歌手名
        """
        title_lower = title.lower().strip()
        artist_lower = artist.lower().strip() if artist else ''

        for result in results:
            # musicdl 的结果可能是 SongInfo 对象或 dict
            if hasattr(result, 'song_name'):
                result_title = result.song_name or ''
                result_artist = str(result.singers or '')
            elif isinstance(result, dict):
                result_title = result.get('song_name', '') or result.get('title', '')
                result_artist = str(result.get('singers', '') or result.get('artist', ''))
            else:
                continue

            # 歌名匹配（必须包含搜索的歌名关键词）
            if title_lower not in result_title.lower():
                continue

            # 如果提供了歌手，检查歌手匹配
            if artist_lower and artist_lower not in result_artist.lower():
                continue

            # 匹配成功！返回结果
            if hasattr(result, 'song_name'):
                return {
                    'song_name': result.song_name,
                    'singers': str(result.singers or ''),
                    'album': result.album or '',
                    'duration': result.duration or 0,
                    'quality': result.ext or '',
                    'filesize': result.file_size or '',
                    'source': '',
                    'raw': result,
                }
            return result

        return None

    # ========== 去重 ==========

    def _make_dedup_key(self, title: str, artist: str) -> str:
        """生成本次运行的去重键"""
        return f"{title.lower().strip()}|{artist.lower().strip()}"

    def is_duplicate(self, title: str, artist: str) -> bool:
        """检查是否已经下载过（当次运行内去重）"""
        key = self._make_dedup_key(title, artist)
        return key in self.downloaded_set

    def mark_downloaded(self, title: str, artist: str):
        """标记为已下载"""
        key = self._make_dedup_key(title, artist)
        self.downloaded_set.add(key)

    # ========== 下载 ==========

    def download_song(self, song_info: Dict, output_dir: str) -> Optional[str]:
        """
        下载单首歌曲
        Args:
            song_info: 包含 'raw' SongInfo 对象和 'source' 的字典
            output_dir: 输出目录

        Returns:
            下载文件的路径，失败返回 None
        """
        raw = song_info.get('raw', song_info)
        source = song_info.get('source', '')

        if not raw:
            return None

        try:
            # musicdl 的 download 接受 SongInfo 对象或列表
            result = self.client.music_clients[source].download(
                song_infos=[raw],
                num_threadings=1
            )
            if result:
                # 返回下载文件路径
                if isinstance(result, list) and len(result) > 0:
                    downloaded = result[0]
                    if hasattr(downloaded, 'song_name'):
                        # 尝试找文件路径
                        song_name = downloaded.song_name.replace('/', '_').replace('\\', '_')
                        artist_name = str(getattr(downloaded, 'singers', '')).replace('/', '_').replace('\\', '_')
                        ext = getattr(downloaded, 'ext', 'mp3')
                        filename = f"{artist_name} - {song_name}.{ext}"
                        filepath = Path(output_dir) / filename
                        if filepath.exists():
                            return str(filepath)
                    # 尝试在输出目录找新文件
                    for f in Path(output_dir).iterdir():
                        if f.is_file() and f.suffix in ['.mp3', '.flac', '.ape', '.wav', '.aac', '.m4a', '.ogg']:
                            return str(f)
                return str(result) if isinstance(result, str) else None
        except Exception as e:
            print(f"    └─ 下载出错: {e}")

        return None

    def download_queue(self, songs: List[Dict], output_dir: str = './downloads') -> Dict:
        """
        并发队列下载
        1. 先对所有歌曲搜索最佳匹配
        2. 去重检查
        3. 并发下载队列
        """
        os.makedirs(output_dir, exist_ok=True)
        output_dir = str(Path(output_dir).resolve())

        print(f"\n{'='*60}")
        print(f"  智能下载引擎启动")
        print(f"  音源: {self.primary_source}")
        print(f"  音质: {self.quality}")
        print(f"  并发: {self.max_workers}")
        print(f"  歌曲: {len(songs)} 首")
        print(f"  目录: {output_dir}")
        print(f"{'='*60}\n")

        # 阶段 1: 搜索 + 去重
        download_queue = []
        print("▶ 阶段 1/3: 搜索匹配...")
        print(f"{'─'*50}")

        for idx, song in enumerate(songs, 1):
            title = song['title']
            artist = song.get('artist', '')
            print(f"[{idx}/{len(songs)}] {title} - {artist}")

            # 去重检查
            if self.is_duplicate(title, artist):
                print(f"  └─ ⏭️ 已下载过，跳过（去重）")
                self.results['skipped'].append({'title': title, 'artist': artist})
                continue

            # 搜索最佳匹配
            best = self.search_best_match(title, artist)
            if best is None:
                self.results['notfound'].append({'title': title, 'artist': artist})
                continue

            download_queue.append(best)

        # 阶段 2: 并发下载
        print(f"\n▶ 阶段 2/3: 并发下载 ({len(download_queue)} 首)...")
        print(f"{'─'*50}")

        if not download_queue:
            print("  没有需要下载的歌曲")
        else:
            def download_task(song_info):
                return self.download_song(song_info, output_dir)

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(download_task, song): song
                    for song in download_queue
                }

                for future in as_completed(futures):
                    song = futures[future]
                    title = song.get('song_name', '未知')
                    artist = song.get('singers', song.get('artist', '未知'))
                    try:
                        filepath = future.result()
                        if filepath:
                            self.results['success'].append({
                                'title': title,
                                'artist': artist,
                                'source': song.get('source', ''),
                                'quality': song.get('quality', ''),
                                'filepath': filepath,
                            })
                            # 标记去重
                            self.mark_downloaded(title, artist)
                            print(f"  ✓ {title} - {artist}")
                        else:
                            self.results['failed'].append({
                                'title': title,
                                'artist': artist,
                                'source': song.get('source', ''),
                            })
                            print(f"  ✗ {title} - {artist} 下载失败")
                    except Exception as e:
                        self.results['failed'].append({
                            'title': title,
                            'artist': artist,
                        })
                        print(f"  ✗ {title} - {artist} 异常: {e}")

        # 阶段 3: 打包
        print(f"\n▶ 阶段 3/3: 打包下载文件...")
        print(f"{'─'*50}")
        zip_path = self.package_downloads(output_dir)

        # 生成报告
        self.generate_report()

        return self.results

    # ========== 打包 ==========

    def package_downloads(self, output_dir: str) -> Optional[str]:
        """将下载的文件打包为 ZIP"""
        output_path = Path(output_dir)
        if not output_path.exists() or not any(output_path.iterdir()):
            print("  没有文件需要打包")
            return None

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"songs_download_{timestamp}.zip"
        zip_path = output_path.parent / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in output_path.rglob('*'):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(output_path.parent))
                    zf.write(file_path, arcname)

        file_size = zip_path.stat().st_size
        size_str = f"{file_size / 1024 / 1024:.1f} MB" if file_size > 1024 * 1024 else f"{file_size / 1024:.1f} KB"
        print(f"  ✓ 打包完成: {zip_filename} ({size_str})")

        return str(zip_path)

    # ========== 报告 ==========

    def generate_report(self):
        """生成下载报告（打印到控制台 + GitHub Step Summary）"""
        success = self.results['success']
        failed = self.results['failed']
        skipped = self.results['skipped']
        notfound = self.results['notfound']

        print(f"\n{'='*60}")
        print(f"  下载完成报告")
        print(f"{'='*60}")
        print(f"  ✓ 成功: {len(success)} 首")
        print(f"  ✗ 失败: {len(failed)} 首")
        print(f"  ⏭️ 跳过(去重): {len(skipped)} 首")
        print(f"  ❓ 未找到: {len(notfound)} 首")
        print(f"{'='*60}")

        # 生成 GitHub Actions Step Summary 格式
        summary = []
        summary.append("##  下载完成报告\n")
        summary.append("| 歌曲 | 歌手 | 音源 | 状态 |")
        summary.append("|------|------|------|------|")

        for s in success:
            summary.append(f"| {s['title']} | {s['artist']} | {s['source']} | ✅ |")
        for s in failed:
            summary.append(f"| {s['title']} | {s['artist']} | - | ❌ 下载失败 |")
        for s in notfound:
            summary.append(f"| {s['title']} | {s.get('artist', '')} | - | ❓ 未找到 |")
        for s in skipped:
            summary.append(f"| {s['title']} | {s.get('artist', '')} | - | ⏭️ 去重跳过 |")

        summary.append(f"\n✅ 成功: {len(success)} | ❌ 失败: {len(failed)} | ❓ 未找到: {len(notfound)} | ⏭️ 跳过: {len(skipped)}")

        # 写入文件，供 workflow 读取
        report_path = Path('download-report.md')
        report_path.write_text('\n'.join(summary), encoding='utf-8')
        print(f"\n报告已保存到 {report_path}")

        # 设置 GITHUB_STEP_SUMMARY（在 workflow 中生效）
        github_summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if github_summary:
            with open(github_summary, 'a', encoding='utf-8') as f:
                f.write('\n'.join(summary))


def main():
    parser = argparse.ArgumentParser(description='Smart Downloader - 智能音乐下载器')
    parser.add_argument('--file', '-f', type=str, default='', help='歌曲列表文件路径 (song-queue.txt)')
    parser.add_argument('--text', '-t', type=str, default='', help='歌曲列表文本 (多行)')
    parser.add_argument('--source', '-s', type=str, default='QQMusicClient',
                       help='首选音源 (默认: QQMusicClient)')
    parser.add_argument('--quality', '-q', type=str, default='flac',
                       choices=['flac', 'mp3', 'ape', 'wav', 'aac', 'auto'],
                       help='音质偏好 (默认: flac)')
    parser.add_argument('--workers', '-w', type=int, default=5, help='并发下载数 (默认: 5)')
    parser.add_argument('--output', '-o', type=str, default='./downloads', help='输出目录')
    parser.add_argument('--artist-filter', type=str, default='',
                       help='歌手筛选 (可选，只下载指定歌手的歌曲)')

    args = parser.parse_args()

    # 加载歌曲列表
    songs = []

    if args.file and Path(args.file).exists():
        downloader = SmartDownloader(source=args.source, quality=args.quality, max_workers=args.workers)
        songs = downloader.load_songs_from_file(args.file)
    elif args.text:
        downloader = SmartDownloader(source=args.source, quality=args.quality, max_workers=args.workers)
        songs = downloader.load_songs_from_text(args.text)
    else:
        # 尝试默认文件
        default_file = Path('song-queue.txt')
        if default_file.exists():
            downloader = SmartDownloader(source=args.source, quality=args.quality, max_workers=args.workers)
            songs = downloader.load_songs_from_file(str(default_file))
        else:
            parser.print_help()
            print("\n错误: 请提供歌曲列表 (--file 或 --text)")
            sys.exit(1)

    # 歌手筛选
    if args.artist_filter and songs:
        artist_lower = args.artist_filter.lower().strip()
        before = len(songs)
        songs = [s for s in songs if artist_lower in s.get('artist', '').lower()]
        print(f"歌手筛选 '{args.artist_filter}': {before} → {len(songs)} 首")
        if not songs:
            print("没有匹配该歌手的歌曲")
            sys.exit(0)

    if not songs:
        print("没有找到任何歌曲")
        sys.exit(0)

    # 执行下载
    downloader.download_queue(songs, args.output)


if __name__ == '__main__':
    main()
```

**Step 2: 验证文件创建成功**

Run:
```bash
python -c "import ast; ast.parse(open('../batch-music-downloader/src/smart_downloader.py').read()); print('语法检查通过')"
```

Expected: `语法检查通过`

---

### Task 2: 创建 Workflow: `smart-download.yml`

**文件:**
- Create: `batch-music-downloader/.github/workflows/smart-download.yml`

```yaml
name:  智能歌曲下载

on:
  workflow_dispatch:
    inputs:
      input_mode:
        description: '输入来源'
        required: true
        type: choice
        default: 'file'
        options:
          - file
          - manual
      songs_text:
        description: '歌曲列表（manual 模式时填写，每行一首，格式: 歌名, 歌手）'
        required: false
        type: string
        default: ''
      artist_filter:
        description: '歌手筛选（可选，留空则不筛选）'
        required: false
        type: string
        default: ''
      source:
        description: '首选音源'
        required: true
        type: choice
        default: 'QQMusicClient'
        options:
          - QQMusicClient
          - NeteaseMusicClient
          - KuwoMusicClient
          - KugouMusicClient
          - MiguMusicClient
          - QianqianMusicClient
          - SoundCloudClient
          - YouTubeMusicClient
      quality:
        description: '音质'
        required: true
        type: choice
        default: 'flac'
        options:
          - flac
          - mp3
          - ape
          - wav
          - aac
          - auto
      max_workers:
        description: '并发下载数'
        required: false
        type: number
        default: 5

jobs:
  smart-download:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout code
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name:  显示输入参数
      run: |
        echo "输入模式: ${{ github.event.inputs.input_mode }}"
        echo "首选音源: ${{ github.event.inputs.source }}"
        echo "音质: ${{ github.event.inputs.quality }}"
        echo "并发数: ${{ github.event.inputs.max_workers }}"
        echo "歌手筛选: ${{ github.event.inputs.artist_filter }}"

    - name:  读取 song-queue.txt（file 模式）
      if: github.event.inputs.input_mode == 'file'
      run: |
        if [ ! -f song-queue.txt ]; then
          echo "错误: song-queue.txt 文件不存在！"
          echo "请先在仓库中创建 song-queue.txt 文件，或选择 manual 输入模式。"
          exit 1
        fi
        echo "song-queue.txt 内容:"
        cat song-queue.txt
        echo ""
        echo "FILE_PATH=song-queue.txt" >> $GITHUB_ENV

    - name:  写入歌曲列表（manual 模式）
      if: github.event.inputs.input_mode == 'manual'
      run: |
        echo "--- 手动输入的歌曲列表 ---"
        echo "${{ github.event.inputs.songs_text }}"
        echo "---"
        echo "---" > manual_songs.txt
        echo "${{ github.event.inputs.songs_text }}" >> manual_songs.txt
        echo "FILE_PATH=manual_songs.txt" >> $GITHUB_ENV

    - name:  运行智能下载引擎
      id: download
      run: |
        cd batch-music-downloader
        CMD="python src/smart_downloader.py"
        CMD="$CMD --file ../${FILE_PATH}"
        CMD="$CMD --source ${{ github.event.inputs.source }}"
        CMD="$CMD --quality ${{ github.event.inputs.quality }}"
        CMD="$CMD --workers ${{ github.event.inputs.max_workers }}"
        
        if [ -n "${{ github.event.inputs.artist_filter }}" ]; then
          CMD="$CMD --artist-filter '${{ github.event.inputs.artist_filter }}'"
        fi
        
        echo "执行: $CMD"
        eval $CMD

    - name:  列出下载文件
      run: |
        echo "--- 下载的文件 ---"
        if [ -d "batch-music-downloader/downloads" ]; then
          find batch-music-downloader/downloads -type f | head -30
          echo ""
          echo "文件总数:"
          find batch-music-downloader/downloads -type f | wc -l
        else
          echo "无下载文件"
        fi

    - name:  打包下载文件
      run: |
        if [ -d "batch-music-downloader/downloads" ]; then
          cd batch-music-downloader
          zip -r songs-download.zip downloads/
          echo "ZIP 打包完成"
          ls -lh songs-download.zip
        else
          echo "NO_FILES=true" >> $GITHUB_ENV
          echo "没有需要打包的文件"
        fi

    - name: 上传 Artifact
      uses: actions/upload-artifact@v4
      with:
        name: songs-download
        path: batch-music-downloader/songs-download.zip
        if-no-files-found: warn
```

---

### Task 3: 创建 Workflow: `playlist-download.yml`

**文件:**
- Create: `batch-music-downloader/.github/workflows/playlist-download.yml`

```yaml
name:  歌单下载

on:
  workflow_dispatch:
    inputs:
      playlist_url:
        description: '歌单 URL（支持网易云/QQ音乐等平台歌单链接）'
        required: true
        type: string
      source:
        description: '首选音源'
        required: true
        type: choice
        default: 'QQMusicClient'
        options:
          - QQMusicClient
          - NeteaseMusicClient
          - KuwoMusicClient
          - KugouMusicClient
          - MiguMusicClient
      quality:
        description: '音质'
        required: true
        type: choice
        default: 'flac'
        options:
          - flac
          - mp3
          - ape
          - wav
          - aac
      max_workers:
        description: '并发下载数'
        required: false
        type: number
        default: 5

jobs:
  playlist-download:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout code
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name:  显示歌单信息
      run: |
        echo "歌单 URL: ${{ github.event.inputs.playlist_url }}"
        echo "首选音源: ${{ github.event.inputs.source }}"
        echo "音质: ${{ github.event.inputs.quality }}"
        echo "并发数: ${{ github.event.inputs.max_workers }}"

    - name:  创建临时歌单下载脚本
      run: |
        cat > download_playlist.py << 'PYEOF'
        #!/usr/bin/env python3
        """歌单下载脚本 - 直接利用 batch_downloader 的 playlist 功能"""
        import sys
        import os
        from pathlib import Path

        sys.path.insert(0, 'batch-music-downloader')
        from src.batch_downloader import BatchDownloader

        playlist_url = "${{ github.event.inputs.playlist_url }}"
        source = "${{ github.event.inputs.source }}"
        quality = "${{ github.event.inputs.quality }}"
        workers = ${{ github.event.inputs.max_workers }}
        output_dir = "./down_playlist"

        print(f"解析歌单: {playlist_url}")
        downloader = BatchDownloader(sources=[source])
        
        songs = downloader.parse_playlist(playlist_url)
        print(f"歌单共 {len(songs)} 首歌曲")
        
        if not songs:
            print("未解析到任何歌曲")
            sys.exit(1)

        result = downloader.download_batch(songs, quality, workers, output_dir)
        
        print(f"\n下载完成: {result['downloaded_count']} 成功 / {result['failed_count']} 失败")
        
        # 生成报告
        summary = []
        summary.append("##  歌单下载报告\n")
        summary.append(f"歌单: {playlist_url}\n")
        summary.append("| 歌曲 | 歌手 | 状态 |")
        summary.append("|------|------|------|")
        for s in result['success']:
            summary.append(f"| {s['title']} | {s['artist']} | ✅ |")
        for s in result['failed']:
            summary.append(f"| {s.get('title', '未知')} | {s.get('artist', '')} | ❌ |")
        summary.append(f"\n✅ 成功: {result['downloaded_count']} | ❌ 失败: {result['failed_count']}")
        
        with open('playlist-report.md', 'w', encoding='utf-8') as f:
            f.write('\n'.join(summary))
        
        github_summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if github_summary:
            with open(github_summary, 'a', encoding='utf-8') as f:
                f.write('\n'.join(summary))
        PYEOF

    - name:  运行歌单下载
      run: python download_playlist.py

    - name:  列出下载文件
      run: |
        echo "--- 下载的文件 ---"
        if [ -d "down_playlist" ]; then
          find down_playlist -type f | head -30
          echo ""
          echo "文件总数:"
          find down_playlist -type f | wc -l
        else
          echo "无下载文件"
        fi

    - name:  打包下载文件
      run: |
        if [ -d "down_playlist" ] && [ "$(ls -A down_playlist 2>/dev/null)" ]; then
          zip -r playlist-download.zip down_playlist/
          echo "ZIP 打包完成"
          ls -lh playlist-download.zip
        else
          echo "NO_FILES=true" >> GITHUB_ENV
          echo "没有需要打包的文件"
        fi

    - name: 上传 Artifact
      uses: actions/upload-artifact@v4
      with:
        name: playlist-download
        path: playlist-download.zip
        if-no-files-found: warn
```

---

### Task 4: 创建 song-queue.txt 示例文件

**文件:**
- Create: `batch-music-downloader/song-queue.txt`

```txt
# 歌曲队列 - 每行一首，格式: 歌名, 歌手
# 支持 # 注释，支持逗号/空格/制表符分隔
七里香, 周杰伦
夜曲, 周杰伦
晴天, 周杰伦
告白气球, 周杰伦
稻香, 周杰伦

# 可以按歌手分组
童话, 光良
约定, 光良
少年, 梦然
```

---

### Task 5: 更新 requirements.txt

**文件:**
- Modify: `batch-music-downloader/requirements.txt`

```txt
musicdl>=2.0.0
requests>=2.28.0
```

（依赖不变，smart_downloader.py 复用已有依赖）

---

### Task 6: 更新 README.md

**文件:**
- Modify: `batch-music-downloader/README.md`

在原有内容基础上，增加新 workflow 的说明。

---

### Task 7: 本地测试

**步骤:**
1. 确认 Python 环境已安装 musicdl
2. 创建测试歌曲文件
3. 运行 `python src/smart_downloader.py --file song-queue.txt --source QQMusicClient --quality flac --workers 3`
4. 检查 download 目录是否有文件
5. 检查日志输出去重是否正常工作
