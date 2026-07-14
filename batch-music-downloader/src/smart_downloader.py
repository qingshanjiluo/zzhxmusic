#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Downloader V2 - 智能音乐下载器
基于 musicdl 实现自动化搜索、去重、排队下载

特性:
  - 串行逐源搜索，搜到符合条件的第一个结果即停（速度优先）
  - 音质自动回退：flac→ape→wav→mp3→auto
  - 跨音源重试：QQMusic→Netease→Kuwo→Kugou→...
  - 歌名/歌手变体搜索：自动拆解"歌名(feat.XXX)"，去括号、去特殊符号
  - 内置歌单解析：支持网易云/QQ音乐等歌单 URL
  - 歌词+封面自动保存
  - 文件命名模板：{title}、{artist}、{index}、{source}、{quality}
  - 并发队列下载（rich 进度条）
  - 歌单范围筛选：--first N、--last N、--range start,end
  - 中英文歌名筛选：--chinese-only、--no-chinese
  - 源级熔断：连续下载失败自动跳过故障音源
  - 搜索过滤：支持歌名/歌手关键字过滤
  - GitHub Actions 自动打包上传

依赖: pip install musicdl rich

用法:
  python smart_downloader.py --file song-queue.txt
  python smart_downloader.py --text "七里香, 周杰伦\n夜曲, 周杰伦"
  python smart_downloader.py --file song-queue.txt --artist-filter "周杰伦"
  python smart_downloader.py --playlist-url "https://music.163.com/playlist?id=xxx"
  python smart_downloader.py --file songs.txt --quality mp3 --first 5 --filename-template "{index}. {title} - {artist}"
"""

import sys
import os
import re
import json
import shutil
import copy
import zipfile
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
from datetime import datetime
import threading

# musicdl 导入（可选，--list-top-charts 不需要它）
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
        pass

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("提示: 安装 rich 可获得更好的进度条体验 (pip install rich)")


# ========== 排行榜常量（模块级，不依赖 musicdl） ==========

TOP_CHARTS = {
    # QQ 音乐巅峰榜
    'qq_hot':     {'name': 'QQ热歌榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 4, 'format': 'json'}},
    'qq_new':     {'name': 'QQ新歌榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 27, 'format': 'json'}},
    'qq_pop':     {'name': 'QQ流行榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 26, 'format': 'json'}},
    'qq_mainland':{'name': 'QQ内地榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 5, 'format': 'json'}},
    'qq_europe':  {'name': 'QQ欧美榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 3, 'format': 'json'}},
    'qq_korea':   {'name': 'QQ韩国榜',     'source': 'QQ', 'api': 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg',    'params': {'topid': 16, 'format': 'json'}},
    # 网易云音乐排行榜
    'netease_hot':   {'name': '网易云热歌榜', 'source': 'Netease', 'api': 'https://music.163.com/api/playlist/detail',       'params': {'id': 3778678}},
    'netease_new':   {'name': '网易云新歌榜', 'source': 'Netease', 'api': 'https://music.163.com/api/playlist/detail',       'params': {'id': 3779629}},
    'netease_soar':  {'name': '网易云飙升榜', 'source': 'Netease', 'api': 'https://music.163.com/api/playlist/detail',       'params': {'id': 19723756}},
    'netease_orig':  {'name': '网易云原创榜', 'source': 'Netease', 'api': 'https://music.163.com/api/playlist/detail',       'params': {'id': 2884035}},
}

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


SOURCE_NAMES = {
    'QQ': 'QQ音乐', 'Netease': '网易云音乐',
}


def list_top_charts(source: str = ''):
    """列出所有可用的排行榜（模块级函数，不依赖 musicdl）

    Args:
        source: 音源名称，如 'QQ' / 'Netease' / 'Kuwo' / 'Kugou' / 'Migu'
                空字符串列出所有音源的榜单
    """
    print(f"\n{'='*60}")
    title = '可用排行榜列表'
    if source:
        title = f'{source}音乐 - {title}'
    print(f"  {title}")
    print(f"{'='*60}")


    if source:
        # 只列出指定音源的榜单
        items = []
        for key, info in TOP_CHARTS.items():
            if info['source'] == source:
                items.append((key, info['name']))
        display_name = SOURCE_NAMES.get(source, source)
        print(f"\n  {display_name}:")
        for key, name in items:
            print(f"    {key:20s}  {name}")
    else:
        # 按音源分组展示全部
        group_order = ['QQ', 'Netease']
        for src in group_order:
            items = [(k, v['name']) for k, v in TOP_CHARTS.items() if v['source'] == src]
            if items:
                display_name = SOURCE_NAMES.get(src, src)
                print(f"\n  {display_name}:")
                for key, name in items:
                    print(f"    {key:20s}  {name}")
    print()


class SmartDownloader:
    """智能音乐下载器 V2"""

    # 默认音源搜索优先级（串行搜索，搜到即停）
    SOURCE_PRIORITY = [
        'QQMusicClient',
        'NeteaseMusicClient',
        'KuwoMusicClient',
        'KugouMusicClient',
        'MiguMusicClient',
        'QianqianMusicClient',
        'SoundCloudClient',
    ]

    # 音质回退链：首选音质 -> 回退音质列表
    QUALITY_FALLBACK = {
        'flac': ['flac', 'ape', 'wav', 'mp3', 'auto'],
        'ape': ['ape', 'flac', 'wav', 'mp3', 'auto'],
        'wav': ['wav', 'flac', 'ape', 'mp3', 'auto'],
        'mp3': ['mp3', 'auto'],
        'aac': ['aac', 'mp3', 'auto'],
        'auto': ['auto'],
    }

    def __init__(self, source: str = 'QQMusicClient', quality: str = 'flac',
                 max_workers: int = 10, retry_count: int = 2,
                 filename_template: str = '',
                 no_lyrics: bool = True, no_cover: bool = True,
                 unlimited_format: bool = False):
        """
        初始化下载器
        Args:
            source: 首选音源（搜不到时自动切换下一个）
            quality: 音质偏好
            max_workers: 最大并发下载数（根据歌单规模调整，建议 10-20）
            retry_count: 下载失败重试次数
            filename_template: 文件命名模板（空=使用默认）
            no_lyrics: 不下载歌词（默认 True，不下载）
            no_cover: 不下载封面（默认 True，不下载）
            unlimited_format: 不限格式，接受任何文件扩展名
        """
        self.primary_source = source
        self.quality = quality
        self.max_workers = max_workers
        self.retry_count = max(1, retry_count)
        self.filename_template = filename_template
        self.no_lyrics = no_lyrics
        self.no_cover = no_cover
        self.unlimited_format = unlimited_format
        self.client = None
        self.SOURCE_CIRCUIT_BREAKER_THRESHOLD = 3  # 源级熔断：连续失败 N 次后跳过该源
        self.source_failures: Dict[str, int] = {}  # 每个源的连续失败次数
        self.downloaded_set: Set[str] = set()  # 去重集合: "歌名|歌手"
        self.results = {
            'success': [],   # 成功下载的歌曲
            'failed': [],    # 下载失败的歌曲
            'skipped': [],   # 去重跳过的歌曲
            'notfound': [],  # 搜索不到的歌曲
        }
        self.quality_fallback_list = self.QUALITY_FALLBACK.get(quality, ['mp3', 'auto'])
        self._file_index = 0  # 文件序号计数器
        # 不限格式时，允许所有常见音频后缀 + 任何后缀
        self._valid_exts = None  # None = 不限格式
        # 【修复】线程安全锁
        self._lock = threading.Lock()
        self._print_lock = threading.Lock()
        # 【修复】restrict_source: 限制搜索/下载只使用指定音源（如 'NeteaseMusicClient'）
        self.restrict_source: Optional[str] = None
        self._init_client()

    def _safe_print(self, *args, **kwargs):
        """线程安全的 print，防止并发日志交错"""
        with self._print_lock:
            print(*args, **kwargs)


    def _init_client(self):
        """初始化 musicdl 客户端"""
        if not MUSICDL_AVAILABLE or MusicClient is None:
            print("警告: musicdl 未安装，仅排行榜功能可用")
            return
        try:
            self.client = MusicClient()
        except Exception as e:
            print(f"警告: musicdl 初始化失败: {e}")
            print("部分音源可能不可用，将自动跳过")

    def _client_ready(self) -> bool:
        """检查 client 是否可用，不抛异常"""
        return self.client is not None and hasattr(self.client, 'music_clients') and self.client.music_clients is not None

    def _get_search_sources(self) -> List[str]:
        """获取搜索/下载的音源列表
        【修复】支持 restrict_source：若设置，只返回该源
        """
        if self.restrict_source:
            return [self.restrict_source]
        sources = [self.primary_source]
        for src in self.SOURCE_PRIORITY:
            if src != self.primary_source:
                sources.append(src)
        return sources

    def _filter_available_sources(self, sources: List[str]) -> List[str]:
        """过滤掉 client 中不可用的音源"""
        if not self._client_ready():
            return []
        available = []
        for s in sources:
            if s in self.client.music_clients:
                available.append(s)
        return available

    # ========== 输入解析 ==========

    def load_songs_from_file(self, filepath: str) -> List[Dict[str, str]]:
        songs = []
        fp = Path(filepath)
        if not fp.exists():
            print(f"错误: 文件不存在 - {fp}")
            return songs

        content = None
        for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312']:
            try:
                content = fp.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            content = fp.read_text(encoding='utf-8', errors='ignore')

        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ',' in line:
                parts = line.split(',', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                songs.append({'title': line.strip(), 'artist': ''})
                continue
            title = parts[0].strip()
            artist = parts[1].strip() if len(parts) > 1 else ''
            if title:
                songs.append({'title': title, 'artist': artist})

        return songs

    def load_songs_from_text(self, text: str) -> List[Dict[str, str]]:
        songs = []
        for line_num, line in enumerate(text.strip().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if ',' in line:
                parts = line.split(',', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                songs.append({'title': line.strip(), 'artist': ''})
                continue
            title = parts[0].strip()
            artist = parts[1].strip() if len(parts) > 1 else ''
            if title:
                songs.append({'title': title, 'artist': artist})
        return songs

    # ========== 排行榜获取 ==========

    def list_top_charts(self, source: str = ''):
        """列出所有可用的排行榜（委托模块级函数）

        Args:
            source: 音源名称过滤，如 'QQ' / 'Netease'，空字符串列出全部
        """
        list_top_charts(source=source)

    def get_top_chart(self, chart_key: str, limit: int = 0) -> List[Dict[str, str]]:
        """
        获取排行榜歌曲列表
        Args:
            chart_key: 排行榜键名（如 qq_hot, netease_new）或别名（如 热歌榜, hot）
            limit: 限制返回数量（0=全部）
        Returns:
            歌曲列表 [{'title': str, 'artist': str}, ...]
        """
        # 别名解析
        resolved = TOP_CHARTS_ALIASES.get(chart_key, chart_key)
        chart_cfg = TOP_CHARTS.get(resolved)
        if not chart_cfg:
            print(f"错误: 未知排行榜 '{chart_key}'。使用 --list-top-charts 查看可用的排行榜。")
            return []

        songs = []
        print(f"正在获取 {chart_cfg['name']}...")

        try:
            import requests

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://y.qq.com/' if chart_cfg['source'] == 'QQ' else 'https://music.163.com/',
            }

            resp = requests.get(chart_cfg['api'], params=chart_cfg['params'], headers=headers, timeout=15)
            data = resp.json()

            if chart_cfg['source'] == 'QQ':
                # QQ 音乐榜：songlist[].data.songname / .singer[].name
                songlist = data.get('songlist', [])
                for item in songlist:
                    sd = item.get('data', item)
                    title = sd.get('songname', '') or sd.get('name', '')
                    singers_raw = sd.get('singer', []) or sd.get('singers', [])
                    artist = '/'.join([s.get('name', '') for s in singers_raw]) if singers_raw else ''
                    if not title:
                        title = sd.get('title', '') or sd.get('name', '')
                    if title:
                        songs.append({'title': title, 'artist': artist})
            else:
                # 网易云榜：result.tracks[].name / .artists[].name
                tracks = data.get('result', {}).get('tracks', [])
                for track in tracks:
                    title = track.get('name', '')
                    artists = '/'.join([a['name'] for a in track.get('artists', [])])
                    if title:
                        songs.append({'title': title, 'artist': artists})

            # 去重
            seen = set()
            unique = []
            for s in songs:
                dedup_key = f"{s['title']}|{s['artist']}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    unique.append(s)
            songs = unique

            print(f"  获取到 {len(songs)} 首歌曲")

            # 限制数量
            if limit > 0 and len(songs) > limit:
                songs = songs[:limit]
                print(f"  限制取前 {limit} 首")

            return songs

        except requests.exceptions.Timeout:
            print(f"  ❌ 请求超时: {chart_cfg['name']}")
        except requests.exceptions.ConnectionError:
            print(f"  ❌ 连接失败: {chart_cfg['name']}")
        except Exception as e:
            print(f"  ❌ 获取失败: {e}")

        return songs

    def parse_playlist(self, playlist_url: str) -> List[Dict[str, str]]:
        """解析歌单 URL，返回歌曲列表"""
        songs = []
        print(f"正在解析歌单: {playlist_url}")

        try:
            import requests
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(playlist_url)
            query = parse_qs(parsed.query)

            # 网易云歌单
            if '163' in parsed.netloc or '163' in playlist_url:
                playlist_id = query.get('id', [None])[0]
                if not playlist_id:
                    # 从 path 提取
                    import re as _re
                    m = _re.search(r'/playlist[?/](\d+)', playlist_url)
                    if m:
                        playlist_id = m.group(1)
                if playlist_id:
                    api_url = f"https://music.163.com/api/playlist/detail?id={playlist_id}"
                    resp = requests.get(api_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://music.163.com/',
                    })
                    data = resp.json()
                    for track in data.get('result', {}).get('tracks', []):
                        artists = '/'.join([a['name'] for a in track.get('artists', [])])
                        songs.append({'title': track['name'], 'artist': artists})
                    print(f"  解析到 {len(songs)} 首歌曲")
                    return songs

            # QQ 音乐歌单
            elif 'qq' in parsed.netloc:
                playlist_id = query.get('id', [None])[0]
                if not playlist_id:
                    import re as _re
                    m = _re.search(r'/(\d+)\.html', playlist_url)
                    if m:
                        playlist_id = m.group(1)
                if playlist_id:
                    api_url = f"https://c.y.qq.com/v8/fcg-bin/fcg_playlist_get_cp.fcg?id={playlist_id}&format=json"
                    resp = requests.get(api_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://y.qq.com/',
                    })
                    data = resp.json()
                    for item in data.get('data', {}).get('cdlist', [{}])[0].get('songlist', []):
                        title = item.get('name', '')
                        artists = '/'.join([s['name'] for s in item.get('singer', [])])
                        if title:
                            songs.append({'title': title, 'artist': artists})
                    print(f"  解析到 {len(songs)} 首歌曲")
                    return songs

        except Exception as e:
            print(f"  歌单解析失败: {e}")

        if not songs:
            print("  警告: 未能解析到任何歌曲")

        return songs

    def _generate_search_keywords(self, title: str, artist: str) -> List[str]:
        """
        根据歌名和歌手生成多个搜索关键词变体，提高匹配率
        例如: "起风了 (Cover: 高桥优)" → ["起风了", "起风了 高桥优"]
        """
        keywords = []

        # 原始完整关键词
        if artist:
            keywords.append(f"{title} {artist}")
        keywords.append(title)

        # 去括号版本（移除 (Cover: xxx), (feat. xxx) 等）
        clean_title = re.sub(r'[（(][^)）]*[)）]', '', title).strip()
        clean_title = re.sub(r'\s+', ' ', clean_title).strip()
        if clean_title and clean_title != title:
            if artist:
                keywords.append(f"{clean_title} {artist}")
            keywords.append(clean_title)

        # 移除特殊符号
        clean_title2 = re.sub(r'[^\w\u4e00-\u9fff\s]', ' ', title).strip()
        clean_title2 = re.sub(r'\s+', ' ', clean_title2).strip()
        if clean_title2 and clean_title2 not in keywords and clean_title2 != clean_title:
            if artist:
                keywords.append(f"{clean_title2} {artist}")
            keywords.append(clean_title2)

        # 提取纯中文/英文部分
        chinese_part = ''.join(re.findall(r'[\u4e00-\u9fff]+', title))
        if chinese_part and chinese_part != clean_title2:
            if artist:
                keywords.append(f"{chinese_part} {artist}")
            keywords.append(chinese_part)

        # 去重
        seen = set()
        unique = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique.append(kw)

        return unique

    def search_best_match(self, title: str, artist: str = '') -> Optional[Dict]:
        """
        搜索最佳匹配，支持关键词变体
        所有音源并行搜索，取最快返回的匹配结果
        """
        keywords = self._generate_search_keywords(title, artist)
        total_kw = len(keywords)

        for kw_idx, keyword in enumerate(keywords, 1):
            print(f"  +-[{kw_idx}/{total_kw}] 搜索 '{keyword}'...")
            result = self._search_single_keyword(keyword, title, artist)
            if result:
                return result

        return None

    def _search_single_keyword(self, keyword: str, title: str, artist: str) -> Optional[Dict]:
        """使用单个关键词在多个音源中**并行**搜索，最快返回的匹配结果优先
        【修复】使用 _safe_print 避免日志交错；若 restrict_source 则只搜指定源
        """
        if not self._client_ready():
            self._safe_print(f"  |  client 未就绪，无法搜索 '{keyword}'")
            return None

        search_sources = self._filter_available_sources(self._get_search_sources())
        if not search_sources:
            self._safe_print(f"  |  没有可用音源，无法搜索 '{keyword}'")
            return None

        self._safe_print(f"  |  并行搜索 {len(search_sources)} 个音源...")

        results_queue: List[Optional[Dict]] = []

        def _search_on_source(source: str) -> Optional[Dict]:
            """单个音源搜索（用于线程池）"""
            try:
                sr = self.client.music_clients[source].search(
                    keyword=keyword,
                    num_threadings=2
                )
                if not sr:
                    return None
                best = self._find_best_match(sr, title, artist)
                if best:
                    best['source'] = source
                    return best
                return None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=len(search_sources)) as pool:
            fut_map = {pool.submit(_search_on_source, s): s for s in search_sources}
            for fut in as_completed(fut_map):
                res = fut.result()
                if res is not None:
                    # 找到匹配，取消其他未完成的任务
                    for o in fut_map:
                        if not o.done():
                            o.cancel()
                    src = res['source']
                    self._safe_print(f"  |  +- [OK] {src}: 找到匹配 -> {res.get('song_name', '')} - {res.get('singers', '')}")
                    return res

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
        return self._make_dedup_key(title, artist) in self.downloaded_set

    def mark_downloaded(self, title: str, artist: str):
        """标记歌曲为已下载"""
        self.downloaded_set.add(self._make_dedup_key(title, artist))

    # ========== 文件命名模板 ==========

    def _build_filename(self, template: str, song_info: Dict, index: int, ext: str) -> str:
        """
        根据模板生成文件名
        可用变量: {title}, {artist}, {index}, {source}, {quality}, {album}
        """
        title = song_info.get('song_name', song_info.get('title', '未知'))
        artist = str(song_info.get('singers', song_info.get('artist', '未知')))
        source = song_info.get('source', 'unknown')
        quality = song_info.get('quality', '')
        album = str(song_info.get('album', ''))

        # 清理文件名非法字符
        def clean(s):
            return re.sub(r'[<>:"/\\|?*]', '_', str(s)).strip()

        name = template
        name = name.replace('{title}', clean(title))
        name = name.replace('{artist}', clean(artist))
        name = name.replace('{index}', str(index).zfill(3))
        name = name.replace('{source}', source)
        name = name.replace('{quality}', quality)
        name = name.replace('{album}', clean(album))

        # 如果结果为空
        if not name.strip():
            name = f"{clean(title)} - {clean(artist)}"

        return f"{name}{ext}"

    # ========== 歌词/封面保存 ==========

    def save_lyrics(self, song_info: Dict, save_path: str):
        """保存歌词 .lrc 文件"""
        if self.no_lyrics:
            return
        raw = song_info.get('raw', song_info)
        try:
            if hasattr(raw, 'lyric') and raw.lyric and raw.lyric != 'NULL':
                lrc_path = Path(save_path).with_suffix('.lrc')
                lrc_path.write_text(raw.lyric, encoding='utf-8')
        except Exception:
            pass

    def save_cover(self, song_info: Dict, save_path: str):
        """保存封面图"""
        if self.no_cover:
            return
        raw = song_info.get('raw', song_info)
        try:
            if hasattr(raw, 'cover_url') and raw.cover_url:
                import requests
                resp = requests.get(raw.cover_url, timeout=10)
                if resp.status_code == 200:
                    cover_path = Path(save_path).with_suffix('.jpg')
                    cover_path.write_bytes(resp.content)
        except Exception:
            pass

    # ========== 核心下载逻辑（熔断增强版 V2） ==========

    def download_song_with_retry(self, song_info: Dict, output_dir: str) -> Optional[str]:
        """
        带重试 + 音质回退 + 跨音源 + 源级熔断的下载方法
        【修复 V3】
          1. 线程安全：source_failures 通过 _lock 保护
          2. 每源每首歌只计 1 次失败（无论尝试多少音质）
          3. 熔断计数设上限 min(old + 1, threshold + 1)
          4. 全部 print 使用 _safe_print 防止日志交错
          5. 支持 restrict_source：只尝试指定音源
        """
        raw = song_info.get('raw', song_info)
        primary_source = song_info.get('source', self.primary_source)
        quality_chain = self.quality_fallback_list
        source_chain = [primary_source]
        for s in self._get_search_sources():
            if s not in source_chain:
                source_chain.append(s)

        song_title = song_info.get('song_name', getattr(raw, 'song_name', '?'))
        self._safe_print(f"    [DEBUG] download_song_with_retry: title='{song_title}' source_chain={source_chain} quality_chain={quality_chain}")

        if not self._client_ready():
            self._safe_print(f"    [DEBUG]   client 未就绪，无法下载")
            return None

        available_sources = self._filter_available_sources(source_chain)
        if not available_sources:
            self._safe_print(f"    [DEBUG]   没有可用音源，无法下载")
            return None

        for source in available_sources:

            # ===== 源级熔断检查（线程安全）=====
            with self._lock:
                src_fails = self.source_failures.get(source, 0)
            if src_fails >= self.SOURCE_CIRCUIT_BREAKER_THRESHOLD:
                self._safe_print(f"    [DEBUG]   ⛔ 源 {source} 已熔断（连续失败 {src_fails} 次），跳过")
                continue

            # 【修复】每源每首歌只计 1 次失败，记录本源的失败标记
            source_failed_for_this_song = False

            for quality in quality_chain:
                actual_si = copy.deepcopy(raw)
                if hasattr(actual_si, 'work_dir'):
                    actual_si.work_dir = output_dir

                self._safe_print(f"    [DEBUG]   尝试: source={source} quality={quality}")

                try:
                    result = self.client.music_clients[source].download(
                        song_infos=[actual_si], num_threadings=1
                    )

                    # ===== 空列表识别 =====
                    if not result or not isinstance(result, list) or len(result) == 0:
                        if not source_failed_for_this_song:
                            with self._lock:
                                old = self.source_failures.get(source, 0)
                                self.source_failures[source] = min(old + 1, self.SOURCE_CIRCUIT_BREAKER_THRESHOLD + 1)
                            source_failed_for_this_song = True
                        with self._lock:
                            fc = self.source_failures.get(source, 0)
                        self._safe_print(f"    [DEBUG]   download() 返回空列表（musicdl 内部失败），源熔断计数={fc}/{self.SOURCE_CIRCUIT_BREAKER_THRESHOLD}")
                        continue

                    dl = result[0]
                    save_path = None

                    # 尝试从 download 结果获取路径
                    if hasattr(dl, 'save_path'):
                        sp = dl.save_path
                        if sp and os.path.exists(sp):
                            save_path = str(sp)

                    # 回退：扫描输出目录
                    if not save_path:
                        if Path(output_dir).exists():
                            for f in Path(output_dir).iterdir():
                                if f.is_file():
                                    if self.unlimited_format:
                                        save_path = str(f)
                                        break
                                    elif f.suffix in ['.mp3', '.flac', '.ape', '.wav', '.aac', '.m4a', '.ogg']:
                                        save_path = str(f)
                                        break

                    if save_path:
                        # 成功：重置该源的熔断计数（线程安全）
                        with self._lock:
                            self.source_failures[source] = 0
                        # 应用文件命名模板
                        if self.filename_template:
                            old_path = Path(save_path)
                            ext = old_path.suffix
                            self._file_index += 1
                            new_name = self._build_filename(
                                self.filename_template, song_info,
                                self._file_index, ext
                            )
                            new_path = old_path.parent / new_name
                            if not new_path.exists() and old_path.exists():
                                shutil.move(str(old_path), str(new_path))
                                save_path = str(new_path)
                        # 保存歌词和封面
                        self.save_lyrics(song_info, save_path)
                        self.save_cover(song_info, save_path)
                        return save_path
                    else:
                        if not source_failed_for_this_song:
                            with self._lock:
                                old = self.source_failures.get(source, 0)
                                self.source_failures[source] = min(old + 1, self.SOURCE_CIRCUIT_BREAKER_THRESHOLD + 1)
                            source_failed_for_this_song = True
                        with self._lock:
                            fc = self.source_failures.get(source, 0)
                        self._safe_print(f"    [DEBUG]   结果非空但无文件落地，源熔断计数={fc}/{self.SOURCE_CIRCUIT_BREAKER_THRESHOLD}")

                except Exception as e:
                    if not source_failed_for_this_song:
                        with self._lock:
                            old = self.source_failures.get(source, 0)
                            self.source_failures[source] = min(old + 1, self.SOURCE_CIRCUIT_BREAKER_THRESHOLD + 1)
                        source_failed_for_this_song = True
                    with self._lock:
                        fc = self.source_failures.get(source, 0)
                    self._safe_print(f"    [DEBUG]   download异常: {type(e).__name__}: {e} → 源熔断计数={fc}/{self.SOURCE_CIRCUIT_BREAKER_THRESHOLD}")
                    continue

        self._safe_print(f"    [DEBUG]   所有source+quality组合均失败，返回None")
        return None

    # ========== 并发下载队列 ==========

    def download_queue(self, songs: List[Dict], output_dir: str = './downloads') -> Dict:
        """
        并发队列下载
        1. 先对所有歌曲搜索最佳匹配
        2. 去重检查
        3. 并发下载队列（带重试 + 源级熔断）
        【修复】使用 _safe_print 防止日志交错；支持 restrict_source 显示；捕获 CancelledError
        """
        os.makedirs(output_dir, exist_ok=True)
        output_dir = str(Path(output_dir).resolve())

        self._safe_print(f"\n{'='*60}")
        self._safe_print(f"  智能下载引擎 V2 启动")
        self._safe_print(f"  音源: {self.primary_source}")
        if self.restrict_source:
            self._safe_print(f"  限制: 仅使用 {self.restrict_source}")
        self._safe_print(f"  音质: {self.quality}")
        self._safe_print(f"  并发: {self.max_workers}")
        self._safe_print(f"  重试: {self.retry_count}次")
        self._safe_print(f"  模板: {self.filename_template or '(默认)'}")
        self._safe_print(f"  歌曲: {len(songs)} 首")
        self._safe_print(f"  目录: {output_dir}")
        self._safe_print(f"{'='*60}\n")

        # 阶段 1: 搜索 + 去重
        download_queue = []
        self._safe_print("==> 阶段 1/3: 搜索匹配...")
        self._safe_print("-" * 50)

        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
            ) as progress:
                task = progress.add_task("搜索歌曲...", total=len(songs))
                for idx, song in enumerate(songs, 1):
                    title = song['title']
                    artist = song.get('artist', '')
                    progress.update(
                        task,
                        description=f"搜索 [{idx}/{len(songs)}] {title}"[:60]
                    )

                    # 去重检查
                    if self.is_duplicate(title, artist):
                        self.results['skipped'].append({'title': title, 'artist': artist})
                        progress.advance(task)
                        continue

                    # 搜索最佳匹配
                    best = self.search_best_match(title, artist)
                    if best is None:
                        self.results['notfound'].append({'title': title, 'artist': artist})
                    else:
                        download_queue.append(best)

                    progress.advance(task)
        else:
            for idx, song in enumerate(songs, 1):
                title = song['title']
                artist = song.get('artist', '')
                self._safe_print(f"[{idx}/{len(songs)}] {title} - {artist}")

                # 去重检查
                if self.is_duplicate(title, artist):
                    self._safe_print(f"  -> 已下载过，跳过（去重）")
                    self.results['skipped'].append({'title': title, 'artist': artist})
                    continue

                # 搜索最佳匹配
                best = self.search_best_match(title, artist)
                if best is None:
                    self.results['notfound'].append({'title': title, 'artist': artist})
                    continue

                download_queue.append(best)

        # 阶段 2: 并发下载
        self._safe_print(f"\n==> 阶段 2/3: 并发下载 ({len(download_queue)} 首)...")
        self._safe_print("-" * 50)

        if not download_queue:
            self._safe_print("  没有需要下载的歌曲")
        else:
            def download_task(song_info):
                return self.download_song_with_retry(song_info, output_dir)

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
                            self._safe_print(f"  ✓ {title} - {artist}")
                        else:
                            self.results['failed'].append({
                                'title': title,
                                'artist': artist,
                                'source': song.get('source', ''),
                            })
                            self._safe_print(f"  ✗ {title} - {artist} 下载失败（已重试所有音质和音源）")
                    except CancelledError:
                        self.results['failed'].append({
                            'title': title,
                            'artist': artist,
                            'source': song.get('source', ''),
                        })
                        self._safe_print(f"  ✗ {title} - {artist} 任务被取消（所有音源已熔断）")
                    except Exception as e:
                        self.results['failed'].append({
                            'title': title,
                            'artist': artist,
                        })
                        self._safe_print(f"  ✗ {title} - {artist} 异常: {e}")

        # 阶段 3: 打包
        self._safe_print(f"\n==> 阶段 3/3: 打包下载文件...")
        self._safe_print("-" * 50)
        zip_path = self.package_downloads(output_dir)

        # 生成报告
        self.generate_report()

        return self.results

    # ========== 打包 ==========

    def package_downloads(self, output_dir: str) -> Optional[str]:
        """将下载的文件打包为 ZIP"""
        files = list(Path(output_dir).iterdir())
        if self.unlimited_format:
            audio_files = [f for f in files if f.is_file()]
        else:
            audio_files = [f for f in files if f.is_file() and f.suffix in ['.mp3', '.flac', '.ape', '.wav', '.aac', '.m4a', '.ogg']]
        if not audio_files:
            self._safe_print("  没有音频文件可打包")
            return None

        zip_name = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = Path(output_dir) / zip_name
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in audio_files:
                zf.write(f, f.name)

        self._safe_print(f"  ✓ 已打包: {zip_name} ({len(audio_files)} 个文件)")
        return str(zip_path)

    # ========== 报告 ==========

    def generate_report(self):
        """生成下载结果报告"""
        self._safe_print(f"\n{'='*60}")
        self._safe_print(f"  下载报告")
        self._safe_print(f"{'='*60}")
        self._safe_print(f"  [OK] 成功: {len(self.results['success'])}")
        self._safe_print(f"  [FAIL] 失败: {len(self.results['failed'])}")
        self._safe_print(f"  [SKIP] 跳过(去重): {len(self.results['skipped'])}")
        self._safe_print(f"  [NF] 未找到: {len(self.results['notfound'])}")
        self._safe_print(f"{'='*60}")

        if self.results['failed']:
            self._safe_print(f"\n  失败列表:")
            for item in self.results['failed']:
                self._safe_print(f"    [X] {item.get('title', '?')} - {item.get('artist', '?')}")

        if self.results['notfound']:
            self._safe_print(f"\n  未找到的歌曲:")
            for item in self.results['notfound']:
                self._safe_print(f"    ? {item.get('title', '?')} - {item.get('artist', '?')}")


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(
        description='Smart Downloader V2 - 智能音乐下载器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  %(prog)s --file song-queue.txt
  %(prog)s --text "七里香, 周杰伦"
  %(prog)s --file queue.txt --source KuwoMusicClient --quality mp3
  %(prog)s --playlist-url "https://music.163.com/playlist?id=xxx"
  %(prog)s --file songs.txt --first 10
  %(prog)s --file songs.txt --last 5
  %(prog)s --file songs.txt --range 3,8
  %(prog)s --file songs.txt --chinese-only
  %(prog)s --file songs.txt --filename-template "{index}. {title} - {artist}"
  %(prog)s --file songs.txt --unlimited-format
        '''
    )
    parser.add_argument('--file', '-f', type=str, help='歌曲列表文件路径')
    parser.add_argument('--text', '-t', type=str, help='直接传入歌曲列表文本，用 \\n 或换行分隔')
    parser.add_argument('--playlist-url', type=str, help='歌单 URL（支持网易云/QQ音乐等）')
    parser.add_argument('--source', '-s', type=str, default='QQMusicClient',
                        help='首选音源，默认 QQMusicClient')
    parser.add_argument('--quality', '-q', type=str, default='flac',
                        help='音质偏好，默认 flac')
    parser.add_argument('--workers', '-w', type=int, default=10,
                        help='并发下载数，默认 10')
    parser.add_argument('--retry', '-r', type=int, default=2,
                        help='下载失败重试次数')
    parser.add_argument('--output', '-o', type=str, default='./downloads',
                        help='下载目录，默认 ./downloads')
    parser.add_argument('--no-pack', action='store_true',
                        help='不打包为 ZIP')
    parser.add_argument('--artist-filter', type=str, default='',
                        help='只下载指定歌手的歌曲（歌名、歌手包含关键字）')
    parser.add_argument('--title-filter', type=str, default='',
                        help='只下载歌名包含指定关键字的歌曲')

    # V2 新增参数
    parser.add_argument('--filename-template', type=str, default='',
                        help='文件命名模板，支持 {title}/{artist}/{index}/{source}/{quality}/{album}')
    parser.add_argument('--lyrics', action='store_false', dest='no_lyrics',
                        help='下载歌词（默认不下载）')
    parser.add_argument('--cover', action='store_false', dest='no_cover',
                        help='下载封面（默认不下载）')
    parser.add_argument('--first', type=int, default=0,
                        help='只下载前 N 首（优先级高于 --range）')
    parser.add_argument('--last', type=int, default=0,
                        help='只下载后 N 首（优先级高于 --range）')
    parser.add_argument('--range', type=str, default='',
                        help='下载指定范围，如 3,8（优先级低于 --first/--last）')
    parser.add_argument('--chinese-only', action='store_true',
                        help='只下载歌名含中文的歌曲')
    parser.add_argument('--no-chinese', action='store_true',
                        help='只下载歌名不含中文的歌曲')
    parser.add_argument('--unlimited-format', action='store_true',
                        help='不限格式，接受任何文件扩展名（默认只接受 mp3/flac/ape/wav 等）')

    # 排行榜参数
    parser.add_argument('--top-charts', type=str, default='',
                        help='下载指定排行榜（如 qq_hot, netease_new, 热歌榜），使用 --list-top-charts 查看可用榜单')
    parser.add_argument('--list-top-charts', action='store_true',
                        help='列出所有可用的排行榜')
    parser.add_argument('--source-charts', type=str, default='',
                        help='按音源列出榜单，如 QQ / Netease；留空则列出全部')
    parser.add_argument('--chart-limit', type=int, default=0,
                        help='排行榜模式下限制获取的歌曲数量（0=全部）')

    args = parser.parse_args()

    # 先处理纯展示模式（不涉及下载，不需要 musicdl）
    if args.list_top_charts:
        list_top_charts()
        sys.exit(0)
    if args.source_charts:
        list_top_charts(source=args.source_charts.strip())
        sys.exit(0)

    # 收集歌曲
    songs = []
    if args.file:
        downloader = SmartDownloader(source=args.source, quality=args.quality,
                                     max_workers=args.workers, retry_count=args.retry,
                                     filename_template=args.filename_template,
                                     no_lyrics=args.no_lyrics, no_cover=args.no_cover,
                                     unlimited_format=args.unlimited_format)
        songs = downloader.load_songs_from_file(args.file)
    elif args.text:
        downloader = SmartDownloader(source=args.source, quality=args.quality,
                                     max_workers=args.workers, retry_count=args.retry,
                                     filename_template=args.filename_template,
                                     no_lyrics=args.no_lyrics, no_cover=args.no_cover,
                                     unlimited_format=args.unlimited_format)
        songs = downloader.load_songs_from_text(args.text.replace('\\n', '\n'))
    elif args.playlist_url:
        downloader = SmartDownloader(source=args.source, quality=args.quality,
                                     max_workers=args.workers, retry_count=args.retry,
                                     filename_template=args.filename_template,
                                     no_lyrics=args.no_lyrics, no_cover=args.no_cover,
                                     unlimited_format=args.unlimited_format)
        songs = downloader.parse_playlist(args.playlist_url)
        if not songs:
            print("错误: 无法从歌单 URL 解析到任何歌曲")
            sys.exit(1)
    elif args.top_charts:
        downloader = SmartDownloader(source=args.source, quality=args.quality,
                                     max_workers=args.workers, retry_count=args.retry,
                                     filename_template=args.filename_template,
                                     no_lyrics=args.no_lyrics, no_cover=args.no_cover,
                                     unlimited_format=args.unlimited_format)
        songs = downloader.get_top_chart(args.top_charts, limit=args.chart_limit)
        if not songs:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    if not songs:
        print("错误: 没有可下载的歌曲")
        sys.exit(1)

    print(f"共加载 {len(songs)} 首歌曲")

    # 应用筛选 -----------------------------------------------

    # 歌手筛选
    if args.artist_filter:
        keyword = args.artist_filter.lower()
        filtered = []
        for s in songs:
            title = s.get('title', '').lower()
            artist = s.get('artist', '').lower()
            if keyword in title or keyword in artist:
                filtered.append(s)
        songs = filtered
        print(f"歌手筛选 '{args.artist_filter}': 剩余 {len(songs)} 首")

    # 歌名筛选
    if args.title_filter:
        keyword = args.title_filter.lower()
        filtered = [s for s in songs if keyword in s.get('title', '').lower()]
        songs = filtered
        print(f"歌名筛选 '{args.title_filter}': 剩余 {len(songs)} 首")

    # first/last/range
    if args.first > 0:
        songs = songs[:args.first]
        print(f"--first {args.first}: 剩余 {len(songs)} 首")
    elif args.last > 0:
        songs = songs[-args.last:]
        print(f"--last {args.last}: 剩余 {len(songs)} 首")
    elif args.range:
        parts = args.range.split(',')
        if len(parts) == 2:
            start, end = int(parts[0]), int(parts[1])
            songs = songs[max(0, start - 1):end]
            print(f"--range {args.range}: 剩余 {len(songs)} 首")

    # 中英文筛选
    if args.chinese_only:
        filtered = [s for s in songs if re.search(r'[\u4e00-\u9fff]', s.get('title', ''))]
        songs = filtered
        print(f"--chinese-only: 剩余 {len(songs)} 首")
    elif args.no_chinese:
        filtered = [s for s in songs if not re.search(r'[\u4e00-\u9fff]', s.get('title', ''))]
        songs = filtered
        print(f"--no-chinese: 剩余 {len(songs)} 首")

    if not songs:
        print("筛选后没有可下载的歌曲")
        sys.exit(0)

    # 执行下载
    try:
        results = downloader.download_queue(songs, output_dir=args.output)
    except KeyboardInterrupt:
        print("\n\n用户中断下载")
        sys.exit(1)
    except Exception as e:
        print(f"\n下载过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # 成功/失败统计
    success_count = len(results.get('success', []))
    failed_count = len(results.get('failed', []))
    notfound_count = len(results.get('notfound', []))
    skipped_count = len(results.get('skipped', []))

    print(f"\n下载完成: 成功 {success_count}, 失败 {failed_count}, 未找到 {notfound_count}, 跳过 {skipped_count}")

    # 非零退出码表示有失败
    if failed_count > 0:
        sys.exit(2)


if __name__ == '__main__':
    main()
