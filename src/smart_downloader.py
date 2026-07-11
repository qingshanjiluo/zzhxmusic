#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Downloader - 智能音乐下载器
基于 musicdl 实现自动化搜索、去重、排队下载

特性:
  - 串行逐源搜索，搜到符合条件的第一个结果即停（速度优先）
  - 基于歌名+歌手的内存去重（当次运行内不重复下载）
  - 并发队列下载，自动排队
  - 支持 song-queue.txt 文件和命令行参数两种输入
  - 下载报告自动生成
  - GitHub Actions 自动打包上传

依赖: pip install musicdl

用法:
  python smart_downloader.py --file song-queue.txt
  python smart_downloader.py --text "七里香, 周杰伦\n夜曲, 周杰伦"
  python smart_downloader.py --file song-queue.txt --artist-filter "周杰伦"
"""

import sys
import os
import zipfile
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    from musicdl import musicdl
except ImportError:
    print("错误: 未安装 musicdl")
    print("请运行: pip install musicdl")
    sys.exit(1)


class SmartDownloader:
    """智能音乐下载器"""

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
        self.primary_source = source
        self.quality = quality
        self.max_workers = max_workers
        self.client = None
        self.downloaded_set: Set[str] = set()
        self.results = {
            'success': [],
            'failed': [],
            'skipped': [],
            'notfound': [],
        }
        self._init_client()

    def _init_client(self):
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
        sources = [self.primary_source]
        for src in self.SOURCE_PRIORITY:
            if src != self.primary_source:
                sources.append(src)
        return sources

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
        if self.client is None:
            return None
        keyword = f"{title} {artist}".strip() if artist else title
        search_sources = self._get_search_sources()
        print(f"  ├─ 搜索 '{keyword}'...")
        for source in search_sources:
            if source not in self.client.music_clients:
                continue
            try:
                results = self.client.music_clients[source].search(
                    keyword=keyword, num_threadings=3
                )
            except Exception as e:
                print(f"  │  └─ {source} 搜索出错: {e}")
                continue
            if not results:
                print(f"  │  └─ {source}: 无结果")
                continue
            best_match = self._find_best_match(results, title, artist)
            if best_match:
                print(f"  │  └─ OK {source}: 找到匹配 -> {best_match.get('song_name', '')} - {best_match.get('singers', '')}")
                best_match['source'] = source
                return best_match
            print(f"  │  └─ {source}: 无匹配结果")
        print(f"  └─ 所有音源均未找到匹配")
        return None

    def _find_best_match(self, results: List, title: str, artist: str) -> Optional[Dict]:
        title_lower = title.lower().strip()
        artist_lower = artist.lower().strip() if artist else ''
        for result in results:
            if hasattr(result, 'song_name'):
                result_title = result.song_name or ''
                result_artist = str(result.singers or '')
            elif isinstance(result, dict):
                result_title = result.get('song_name', '') or result.get('title', '')
                result_artist = str(result.get('singers', '') or result.get('artist', ''))
            else:
                continue
            if title_lower not in result_title.lower():
                continue
            if artist_lower and artist_lower not in result_artist.lower():
                continue
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
        return f"{title.lower().strip()}|{artist.lower().strip()}"

    def is_duplicate(self, title: str, artist: str) -> bool:
        return self._make_dedup_key(title, artist) in self.downloaded_set

    def mark_downloaded(self, title: str, artist: str):
        self.downloaded_set.add(self._make_dedup_key(title, artist))

    # ========== 下载 ==========

    def download_song(self, song_info: Dict, output_dir: str) -> Optional[str]:
        raw = song_info.get('raw', song_info)
        source = song_info.get('source', '')
        if not raw:
            return None
        try:
            result = self.client.music_clients[source].download(
                song_infos=[raw], num_threadings=1
            )
            if result:
                if isinstance(result, list) and len(result) > 0:
                    dl = result[0]
                    if hasattr(dl, 'song_name'):
                        sname = dl.song_name.replace('/', '_').replace('\\', '_')
                        aname = str(getattr(dl, 'singers', '')).replace('/', '_').replace('\\', '_')
                        ext = getattr(dl, 'ext', 'mp3')
                        fpath = Path(output_dir) / f"{aname} - {sname}.{ext}"
                        if fpath.exists():
                            return str(fpath)
                    for f in Path(output_dir).iterdir():
                        if f.is_file() and f.suffix in ['.mp3', '.flac', '.ape', '.wav', '.aac', '.m4a', '.ogg']:
                            return str(f)
                return str(result) if isinstance(result, str) else None
        except Exception as e:
            print(f"    └─ 下载出错: {e}")
        return None

    def download_queue(self, songs: List[Dict], output_dir: str = './downloads') -> Dict:
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
        print("阶段 1/3: 搜索匹配...")
        print(f"{'-'*50}")

        for idx, song in enumerate(songs, 1):
            title = song['title']
            artist = song.get('artist', '')
            print(f"[{idx}/{len(songs)}] {title} - {artist}")
            if self.is_duplicate(title, artist):
                print(f"  -> 已下载过，跳过(去重)")
                self.results['skipped'].append({'title': title, 'artist': artist})
                continue
            best = self.search_best_match(title, artist)
            if best is None:
                self.results['notfound'].append({'title': title, 'artist': artist})
                continue
            download_queue.append(best)

        # 阶段 2: 并发下载
        print(f"\n阶段 2/3: 并发下载 ({len(download_queue)} 首)...")
        print(f"{'-'*50}")

        if not download_queue:
            print("  没有需要下载的歌曲")
        else:
            def download_task(si):
                return self.download_song(si, output_dir)

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(download_task, s): s for s in download_queue}
                for future in as_completed(futures):
                    song = futures[future]
                    title = song.get('song_name', '未知')
                    artist = song.get('singers', song.get('artist', '未知'))
                    try:
                        fp = future.result()
                        if fp:
                            self.results['success'].append({
                                'title': title, 'artist': artist,
                                'source': song.get('source', ''),
                                'quality': song.get('quality', ''),
                                'filepath': fp,
                            })
                            self.mark_downloaded(title, artist)
                            print(f"  OK {title} - {artist}")
                        else:
                            self.results['failed'].append({
                                'title': title, 'artist': artist,
                                'source': song.get('source', ''),
                            })
                            print(f"  FAIL {title} - {artist}")
                    except Exception as e:
                        self.results['failed'].append({'title': title, 'artist': artist})
                        print(f"  FAIL {title} - {artist}: {e}")

        # 阶段 3: 打包
        print(f"\n阶段 3/3: 打包下载文件...")
        print(f"{'-'*50}")
        self.package_downloads(output_dir)
        self.generate_report()

        return self.results

    # ========== 打包 ==========

    def package_downloads(self, output_dir: str) -> Optional[str]:
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
                    zf.write(file_path, str(file_path.relative_to(output_path.parent)))
        size = zip_path.stat().st_size
        size_str = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.1f} KB"
        print(f"  打包完成: {zip_filename} ({size_str})")
        return str(zip_path)

    # ========== 报告 ==========

    def generate_report(self):
        success = self.results['success']
        failed = self.results['failed']
        skipped = self.results['skipped']
        notfound = self.results['notfound']

        print(f"\n{'='*60}")
        print(f"  下载完成报告")
        print(f"{'='*60}")
        print(f"  成功: {len(success)} 首")
        print(f"  失败: {len(failed)} 首")
        print(f"  跳过(去重): {len(skipped)} 首")
        print(f"  未找到: {len(notfound)} 首")
        print(f"{'='*60}")

        summary = []
        summary.append("## 下载完成报告\n")
        summary.append("| 歌曲 | 歌手 | 音源 | 状态 |")
        summary.append("|------|------|------|------|")
        for s in success:
            summary.append(f"| {s['title']} | {s['artist']} | {s['source']} | OK |")
        for s in failed:
            summary.append(f"| {s['title']} | {s['artist']} | - | FAIL |")
        for s in notfound:
            summary.append(f"| {s['title']} | {s.get('artist', '')} | - | NOTFOUND |")
        for s in skipped:
            summary.append(f"| {s['title']} | {s.get('artist', '')} | - | SKIP |")
        summary.append(f"\n成功: {len(success)} | 失败: {len(failed)} | 未找到: {len(notfound)} | 跳过: {len(skipped)}")

        report_path = Path('download-report.md')
        report_path.write_text('\n'.join(summary), encoding='utf-8')
        print(f"报告已保存到 {report_path}")

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

    # 提前初始化，避免重复
    downloader = SmartDownloader(source=args.source, quality=args.quality, max_workers=args.workers)

    songs = []
    if args.file and Path(args.file).exists():
        songs = downloader.load_songs_from_file(args.file)
    elif args.text:
        songs = downloader.load_songs_from_text(args.text)
    else:
        default_file = Path('song-queue.txt')
        if default_file.exists():
            songs = downloader.load_songs_from_file(str(default_file))
        else:
            parser.print_help()
            print("\n错误: 请提供歌曲列表 (--file 或 --text)")
            sys.exit(1)

    # 歌手筛选
    if args.artist_filter and songs:
        al = args.artist_filter.lower().strip()
        before = len(songs)
        songs = [s for s in songs if al in s.get('artist', '').lower()]
        print(f"歌手筛选 '{args.artist_filter}': {before} -> {len(songs)} 首")
        if not songs:
            print("没有匹配该歌手的歌曲")
            sys.exit(0)

    if not songs:
        print("没有找到任何歌曲")
        sys.exit(0)

    downloader.download_queue(songs, args.output)


if __name__ == '__main__':
    main()
