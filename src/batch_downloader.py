#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量音乐下载工具 - 完整版
基于 musicdl 实现批量搜索和下载，支持音源选择、筛选功能
"""

import sys
import os
import argparse
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到路径
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

try:
    from musicdl import musicdl
except ImportError:
    print("错误: 未安装 musicdl")
    print("请运行: pip install musicdl")
    sys.exit(1)

# 导入配置
try:
    from src.config import Config
except ImportError:
    from .config import Config


class BatchDownloader:
    """批量音乐下载器"""
    
    # 可用音源列表
    AVAILABLE_SOURCES = [
        'QQMusicClient',
        'NeteaseMusicClient', 
        'KuwoMusicClient',
        'KugouMusicClient',
        'SpotifyClient',
        'SoundCloudClient',
        'TidalClient',
        'DeezerClient',
        'AppleMusicClient',
        'YouTubeMusicClient'
    ]
    
    def __init__(self, config: Optional[Config] = None, sources: Optional[List[str]] = None):
        self.config = config or Config()
        self.sources = sources or self.config.get('sources', ['QQMusicClient', 'NeteaseMusicClient'])
        self.client = None
        self._init_client()
        self.downloaded = []
        self.failed = []
    
    def _init_client(self):
        """初始化 musicdl 客户端"""
        init_cfg = {src: {'search_size_per_source': self.config.get('search_size', 10)} for src in self.sources}
        
        try:
            self.client = musicdl.MusicClient(
                music_sources=self.sources,
                init_music_clients_cfg=init_cfg
            )
        except Exception as e:
            print(f"初始化客户端失败: {e}")
            self.client = None
    
    def search(self, keyword: str, limit: int = 10, source_filter: Optional[str] = None) -> List[Dict]:
        """搜索歌曲，支持音源筛选"""
        if self.client is None:
            return []
        
        try:
            results = self.client.search(keyword=keyword)
            formatted = []
            if isinstance(results, list):
                for idx, item in enumerate(results):
                    if idx >= limit * len(self.sources):
                        break
                    if isinstance(item, dict):
                        if source_filter and source_filter != 'all':
                            item_source = item.get('source', '')
                            if source_filter not in item_source:
                                continue
                        formatted.append({
                            'title': item.get('title', ''),
                            'artist': item.get('artist', ''),
                            'album': item.get('album', ''),
                            'source': item.get('source', ''),
                            'duration': item.get('duration', 0),
                            'quality': item.get('quality', 'flac'),
                            'raw': item
                        })
            return formatted
        except Exception as e:
            print(f"搜索失败 '{keyword}': {e}")
            return []
    
    def search_with_filters(self, keyword: str, limit: int = 10, 
                           source_filter: Optional[str] = None,
                           min_duration: Optional[int] = None,
                           max_duration: Optional[int] = None,
                           keyword_filter: Optional[str] = None) -> List[Dict]:
        """带筛选条件的搜索"""
        results = self.search(keyword, limit * 2, source_filter)
        
        filtered = []
        for item in results:
            duration = item.get('duration', 0)
            if min_duration and duration < min_duration:
                continue
            if max_duration and duration > max_duration:
                continue
            
            if keyword_filter:
                title = item.get('title', '').lower()
                artist = item.get('artist', '').lower()
                if keyword_filter.lower() not in title and keyword_filter.lower() not in artist:
                    continue
            
            filtered.append(item)
            if len(filtered) >= limit:
                break
        
        return filtered
    
    def download(self, song_info: Dict, quality: str = 'flac', output_dir: Optional[str] = None) -> Optional[str]:
        """下载单首歌曲"""
        if self.client is None:
            return None
        
        if output_dir is None:
            output_dir = self.config.get('output_dir', './downloads')
        
        try:
            raw = song_info.get('raw', song_info)
            
            # 直接调用，不传额外参数，让 musicdl 使用默认行为
            # musicdl 的 download 方法会从 song_info 中获取必要信息
            result = self.client.download(raw)
            
            if result:
                filepath = result.get('filepath', '') if isinstance(result, dict) else str(result)
                print(f"✅ 下载成功: {song_info.get('title', '')} - {song_info.get('artist', '')}")
                return filepath
            else:
                print(f"❌ 下载失败: {song_info.get('title', '')} - {song_info.get('artist', '')}")
                return None
        except Exception as e:
            print(f"❌ 下载出错: {song_info.get('title', '')} - {e}")
            return None
    
    def download_batch(self, songs: List[Dict], quality: str = 'flac', 
                       max_workers: int = 3, output_dir: Optional[str] = None,
                       only_selected: bool = False, selected_indices: Optional[List[int]] = None) -> Dict:
        """批量下载"""
        if output_dir is None:
            output_dir = self.config.get('output_dir', './downloads')
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        if only_selected and selected_indices:
            songs_to_download = [songs[i] for i in selected_indices if i < len(songs)]
            print(f"只下载选中的 {len(songs_to_download)} 首歌曲")
        else:
            songs_to_download = songs
        
        if not songs_to_download:
            print("没有要下载的歌曲")
            return {'success': [], 'failed': [], 'total': 0, 'downloaded_count': 0, 'failed_count': 0}
        
        self.downloaded = []
        self.failed = []
        
        print(f"\n开始批量下载 {len(songs_to_download)} 首歌曲...")
        print(f"音质: {quality}, 并发数: {max_workers}")
        print("-" * 50)
        
        def download_task(song):
            return self.download(song, quality, output_dir)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_task, song): song for song in songs_to_download}
            
            for future in as_completed(futures):
                song = futures[future]
                try:
                    result = future.result()
                    if result:
                        self.downloaded.append({
                            'title': song.get('title', ''),
                            'artist': song.get('artist', ''),
                            'filepath': result
                        })
                    else:
                        self.failed.append(song)
                except Exception as e:
                    print(f"❌ 任务异常: {song.get('title', '')} - {e}")
                    self.failed.append(song)
        
        print("-" * 50)
        print(f"\n✅ 完成: {len(self.downloaded)} 首成功, {len(self.failed)} 首失败")
        
        return {
            'success': self.downloaded,
            'failed': self.failed,
            'total': len(songs_to_download),
            'downloaded_count': len(self.downloaded),
            'failed_count': len(self.failed)
        }
    
    def parse_playlist(self, playlist_url: str, source_filter: Optional[str] = None) -> List[Dict]:
        """解析歌单"""
        if self.client is None:
            return []
        
        try:
            results = self.client.parseplaylist(playlist_url=playlist_url)
            songs = []
            for item in results:
                if source_filter and source_filter != 'all':
                    item_source = item.get('source', '')
                    if source_filter not in item_source:
                        continue
                songs.append({
                    'title': item.get('title', ''),
                    'artist': item.get('artist', ''),
                    'album': item.get('album', ''),
                    'source': item.get('source', ''),
                    'duration': item.get('duration', 0),
                    'raw': item
                })
            return songs
        except Exception as e:
            print(f"解析歌单失败: {e}")
            return []
    
    def get_artist_songs(self, artist_name: str, limit: int = 30, source_filter: Optional[str] = None) -> List[Dict]:
        """获取歌手歌曲"""
        results = self.search(artist_name, limit * 2, source_filter)
        songs = []
        for item in results:
            if artist_name.lower() in item.get('artist', '').lower():
                songs.append(item)
                if len(songs) >= limit:
                    break
        return songs


def load_songs_from_file(filepath: str) -> List[Dict]:
    """从文件加载歌曲列表"""
    songs = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ',' in line:
                parts = line.split(',', 1)
            else:
                parts = line.split(' ', 1)
            if len(parts) >= 1:
                title = parts[0].strip()
                artist = parts[1].strip() if len(parts) > 1 else ''
                songs.append({'title': title, 'artist': artist})
    return songs


def main():
    parser = argparse.ArgumentParser(description='批量音乐下载工具')
    parser.add_argument('--query', '-q', type=str, help='搜索关键词')
    parser.add_argument('--file', '-f', type=str, help='歌曲列表文件路径')
    parser.add_argument('--playlist', '-p', type=str, help='歌单 URL')
    parser.add_argument('--artist', '-a', type=str, help='歌手名称')
    parser.add_argument('--quality', type=str, default='flac', 
                       choices=['flac', 'mp3', 'ape', 'wav', 'aac'],
                       help='音质 (默认: flac)')
    parser.add_argument('--workers', type=int, default=3, help='并发下载数 (默认: 3)')
    parser.add_argument('--output', '-o', type=str, default='./downloads', help='输出目录')
    parser.add_argument('--limit', type=int, default=10, help='搜索结果数量限制')
    parser.add_argument('--config', type=str, help='配置文件路径')
    parser.add_argument('--list-sources', action='store_true', help='列出可用音源')
    parser.add_argument('--source', type=str, default='all', help='指定音源')
    parser.add_argument('--min-duration', type=int, help='最小时长 (秒)')
    parser.add_argument('--max-duration', type=int, help='最大时长 (秒)')
    parser.add_argument('--keyword-filter', type=str, help='标题/歌手关键词筛选')
    parser.add_argument('--only-selected', action='store_true', help='只下载选中的歌曲')
    parser.add_argument('--selected-indices', type=str, help='选中歌曲索引 (如: 0,2,5)')
    parser.add_argument('--playlist-source', type=str, default='all', help='歌单下载时指定音源')
    
    args = parser.parse_args()
    
    config = Config()
    if args.config:
        config.load_from_file(args.config)
    
    if args.list_sources:
        print("可用音源:")
        for src in BatchDownloader.AVAILABLE_SOURCES:
            print(f"  - {src}")
        return
    
    selected_indices = None
    if args.selected_indices:
        selected_indices = [int(x.strip()) for x in args.selected_indices.split(',')]
    
    source_list = None
    if args.source != 'all':
        source_list = [args.source]
    
    downloader = BatchDownloader(config, source_list)
    songs = []
    
    if args.query:
        print(f"搜索: {args.query}")
        if args.min_duration or args.max_duration or args.keyword_filter:
            songs = downloader.search_with_filters(
                args.query, args.limit,
                source_filter=args.source if args.source != 'all' else None,
                min_duration=args.min_duration,
                max_duration=args.max_duration,
                keyword_filter=args.keyword_filter
            )
        else:
            songs = downloader.search(args.query, args.limit, 
                                     source_filter=args.source if args.source != 'all' else None)
        if not songs:
            print("未找到任何歌曲")
            return
        print(f"找到 {len(songs)} 首歌曲")
        
    elif args.file:
        print(f"从文件读取: {args.file}")
        song_list = load_songs_from_file(args.file)
        print(f"共 {len(song_list)} 首歌曲")
        for s in song_list:
            keyword = f"{s['title']} {s['artist']}".strip()
            results = downloader.search(keyword, 1, 
                                       source_filter=args.source if args.source != 'all' else None)
            if results:
                songs.append(results[0])
                print(f"✅ 找到: {results[0]['title']} - {results[0]['artist']}")
            else:
                print(f"❌ 未找到: {keyword}")
    
    elif args.playlist:
        print(f"歌单: {args.playlist}")
        if downloader.client is None:
            print("客户端未初始化")
            return
        songs = downloader.parse_playlist(
            args.playlist,
            source_filter=args.playlist_source if args.playlist_source != 'all' else None
        )
        print(f"歌单包含 {len(songs)} 首歌曲")
        
        if args.keyword_filter or args.min_duration or args.max_duration:
            filtered = []
            for item in songs:
                if args.min_duration and item.get('duration', 0) < args.min_duration:
                    continue
                if args.max_duration and item.get('duration', 0) > args.max_duration:
                    continue
                if args.keyword_filter:
                    title = item.get('title', '').lower()
                    artist = item.get('artist', '').lower()
                    if args.keyword_filter.lower() not in title and args.keyword_filter.lower() not in artist:
                        continue
                filtered.append(item)
            songs = filtered
            print(f"筛选后剩余 {len(songs)} 首歌曲")
    
    elif args.artist:
        print(f"搜索歌手: {args.artist}")
        songs = downloader.get_artist_songs(
            args.artist, args.limit,
            source_filter=args.source if args.source != 'all' else None
        )
        print(f"找到 {len(songs)} 首 {args.artist} 的歌曲")
    
    else:
        print("请指定以下操作之一:")
        print("  --query '关键词'       搜索单曲")
        print("  --file songs.txt       从文件批量下载")
        print("  --playlist URL         歌单下载")
        print("  --artist '歌手名'      歌手下载")
        print("  --list-sources         列出可用音源")
        return
    
    if not songs:
        print("没有找到任何歌曲")
        return
    
    result = downloader.download_batch(
        songs, args.quality, args.workers, args.output,
        only_selected=args.only_selected,
        selected_indices=selected_indices
    )
    
    with open('download_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: download_result.json")


if __name__ == '__main__':
    main()
