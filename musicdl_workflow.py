#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MusicDL GitHub Actions 工作流核心脚本
支持单曲搜索、歌单下载、歌手下载三种模式
"""

import os
import sys
import json
import time
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from musicdl import musicdl
except ImportError:
    print("错误: 未安装 musicdl，请运行 pip install -r requirements.txt")
    sys.exit(1)


class MusicDLWorkflow:
    """MusicDL 工作流核心类"""
    
    def __init__(self, output_dir: str = "musicdl_outputs"):
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = self.base_dir / output_dir
        self.output_dir.mkdir(exist_ok=True)
        self.session_dir = None
        self.client = None
        
    def init_client(self, target_src: str = "qqmusic"):
        """初始化 musicdl 客户端"""
        config = {
            "logfilepath": str(self.base_dir / "musicdl.log"),
            "savedir": str(self.output_dir),
            "search_size": 50,
            "proxies": {},
            "target_src": target_src,
        }
        self.client = musicdl.musicdl(config=config)
        return self.client
    
    def create_session_dir(self, prefix: str = "session") -> Path:
        """创建会话目录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{prefix}_{timestamp}"
        self.session_dir = self.output_dir / session_name
        self.session_dir.mkdir(exist_ok=True)
        return self.session_dir
    
    def search_songs(self, keyword: str, limit: int = 10) -> List[Dict]:
        """搜索单曲"""
        print(f"正在搜索: {keyword}")
        results = self.client.search(keyword, limit=limit)
        
        # 保存搜索结果
        if self.session_dir:
            result_file = self.session_dir / "search_results.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        
        print(f"找到 {len(results)} 首歌曲")
        return results
    
    def download_songs(self, song_list: List[Dict], quality: str = "flac") -> List[Dict]:
        """下载歌曲列表"""
        print(f"开始下载 {len(song_list)} 首歌曲...")
        downloaded = []
        
        for idx, song in enumerate(song_list, 1):
            try:
                title = song.get('title', 'unknown')
                artist = song.get('artist', 'unknown')
                print(f"[{idx}/{len(song_list)}] 下载: {artist} - {title}")
                
                # 下载歌曲
                result = self.client.download(song, quality=quality)
                
                # 记录下载结果
                download_record = {
                    'title': title,
                    'artist': artist,
                    'quality': quality,
                    'status': 'success' if result else 'failed',
                    'file': result.get('filepath') if result else None
                }
                downloaded.append(download_record)
                
            except Exception as e:
                print(f"下载失败: {e}")
                downloaded.append({
                    'title': song.get('title', 'unknown'),
                    'artist': song.get('artist', 'unknown'),
                    'status': 'error',
                    'error': str(e)
                })
        
        # 保存下载记录
        if self.session_dir:
            record_file = self.session_dir / "download_results.json"
            with open(record_file, 'w', encoding='utf-8') as f:
                json.dump(downloaded, f, ensure_ascii=False, indent=2)
        
        print(f"下载完成: 成功 {len([d for d in downloaded if d['status'] == 'success'])} 首")
        return downloaded
    
    def get_playlist_songs(self, playlist_url: str) -> List[Dict]:
        """获取歌单歌曲列表"""
        print(f"正在获取歌单: {playlist_url}")
        # 使用 search 方法获取歌单信息
        # 这里需要根据实际 API 实现
        results = self.client.search(playlist_url, limit=100)
        return results
    
    def get_artist_songs(self, artist_name: str, limit: int = 50) -> List[Dict]:
        """获取歌手歌曲列表"""
        print(f"正在获取歌手: {artist_name}")
        results = self.client.search(artist_name, limit=limit)
        # 过滤出该歌手的歌曲
        artist_songs = [s for s in results if artist_name.lower() in s.get('artist', '').lower()]
        print(f"找到 {len(artist_songs)} 首歌曲")
        return artist_songs
    
    def pack_results(self, zip_name: str = "music_results") -> str:
        """打包结果到 ZIP 文件"""
        if not self.session_dir or not self.session_dir.exists():
            print("错误: 会话目录不存在")
            return ""
        
        zip_path = self.base_dir / f"{zip_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in self.session_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(self.session_dir.parent)
                    zipf.write(file_path, arcname)
        
        print(f"打包完成: {zip_path}")
        return str(zip_path)
    
    def cleanup(self):
        """清理临时文件"""
        if self.session_dir and self.session_dir.exists():
            shutil.rmtree(self.session_dir)
            print(f"已清理: {self.session_dir}")


def run_workflow(mode: str, target: str, quality: str = "flac", limit: int = 10, output_prefix: str = "music_results"):
    """运行工作流"""
    print(f"=== MusicDL 工作流开始 ===")
    print(f"模式: {mode}")
    print(f"目标: {target}")
    print(f"质量: {quality}")
    print(f"限制: {limit}")
    print("=" * 40)
    
    # 创建工作流实例
    workflow = MusicDLWorkflow()
    workflow.init_client()
    workflow.create_session_dir(prefix=mode)
    
    try:
        if mode == "search":
            # 单曲搜索模式
            songs = workflow.search_songs(target, limit=limit)
            if songs:
                workflow.download_songs(songs, quality=quality)
        
        elif mode == "playlist":
            # 歌单下载模式
            songs = workflow.get_playlist_songs(target)
            if songs:
                workflow.download_songs(songs[:limit], quality=quality)
        
        elif mode == "artist":
            # 歌手下载模式
            songs = workflow.get_artist_songs(target, limit=limit)
            if songs:
                workflow.download_songs(songs, quality=quality)
        
        else:
            print(f"错误: 未知模式 '{mode}'")
            return 1
        
        # 打包结果
        zip_path = workflow.pack_results(zip_name=output_prefix)
        if zip_path:
            print(f"\n✅ 工作流完成! 结果已打包至: {zip_path}")
            print(f"   请在 GitHub Actions 的 'Artifacts' 中下载 ZIP 文件")
        
        return 0
        
    except Exception as e:
        print(f"❌ 工作流执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # 清理临时文件（可选）
        # workflow.cleanup()
        pass


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="MusicDL GitHub Actions 工作流")
    parser.add_argument("--mode", choices=["search", "playlist", "artist"], required=True,
                        help="工作流模式: search(单曲搜索), playlist(歌单下载), artist(歌手下载)")
    parser.add_argument("--target", required=True,
                        help="搜索目标: 关键词/歌单URL/歌手名")
    parser.add_argument("--quality", choices=["flac", "mp3", "ape", "wav"], default="flac",
                        help="音频质量 (默认: flac)")
    parser.add_argument("--limit", type=int, default=10,
                        help="下载数量限制 (默认: 10)")
    parser.add_argument("--output", default="music_results",
                        help="输出ZIP文件名前缀 (默认: music_results)")
    
    args = parser.parse_args()
    
    sys.exit(run_workflow(
        mode=args.mode,
        target=args.target,
        quality=args.quality,
        limit=args.limit,
        output_prefix=args.output
    ))


if __name__ == "__main__":
    main()
