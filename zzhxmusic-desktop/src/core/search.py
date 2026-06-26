import sys
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到路径
_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

try:
    from musicdl import musicdl
except ImportError:
    print("警告: musicdl 未安装，请运行 pip install musicdl")
    musicdl = None

from .config import ConfigManager


class SearchService:
    """搜索服务类"""
    
    def __init__(self, config: Optional[ConfigManager] = None):
        self.config = config or ConfigManager()
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化 musicdl 客户端"""
        if musicdl is None:
            return
        
        sources = self.config.get_sources()
        init_cfg = {src: {'search_size_per_source': 20} for src in sources}
        
        try:
            self.client = musicdl.MusicClient(
                music_sources=sources,
                init_music_clients_cfg=init_cfg
            )
        except Exception as e:
            print(f"初始化客户端失败: {e}")
            self.client = None
    
    def search_songs(self, keyword: str, limit: int = 20) -> List[Dict]:
        """搜索单曲"""
        if self.client is None:
            return []
        
        try:
            results = self.client.search(keyword=keyword)
            # 格式化结果
            formatted = []
            for item in results[:limit]:
                formatted.append({
                    'title': item.get('title', ''),
                    'artist': item.get('artist', ''),
                    'album': item.get('album', ''),
                    'source': item.get('source', ''),
                    'duration': item.get('duration', 0),
                    'url': item.get('url', ''),
                    'song_id': item.get('song_id', ''),
                    'quality': item.get('quality', 'flac'),
                    'raw': item
                })
            return formatted
        except Exception as e:
            print(f"搜索失败: {e}")
            return []
    
    def search_album(self, keyword: str, limit: int = 20) -> List[Dict]:
        """搜索专辑"""
        if self.client is None:
            return []
        
        try:
            # 使用特殊搜索规则搜索专辑
            results = self.client.search(keyword=keyword)
            # 这里简化处理，实际需要根据 album 字段过滤
            formatted = []
            for item in results[:limit]:
                if item.get('album'):
                    formatted.append({
                        'title': item.get('album', ''),
                        'artist': item.get('artist', ''),
                        'source': item.get('source', ''),
                        'song_count': item.get('song_count', 0),
                        'raw': item
                    })
            return formatted
        except Exception as e:
            print(f"搜索专辑失败: {e}")
            return []
    
    def search_playlist(self, playlist_url: str) -> List[Dict]:
        """获取歌单歌曲列表"""
        if self.client is None:
            return []
        
        try:
            results = self.client.parseplaylist(playlist_url=playlist_url)
            formatted = []
            for item in results:
                formatted.append({
                    'title': item.get('title', ''),
                    'artist': item.get('artist', ''),
                    'source': item.get('source', ''),
                    'raw': item
                })
            return formatted
        except Exception as e:
            print(f"获取歌单失败: {e}")
            return []
    
    def search_artist(self, artist_name: str, limit: int = 30) -> List[Dict]:
        """搜索歌手歌曲"""
        if self.client is None:
            return []
        
        try:
            results = self.client.search(keyword=artist_name)
            # 过滤出该歌手的歌曲
            formatted = []
            for item in results:
                if artist_name.lower() in item.get('artist', '').lower():
                    formatted.append({
                        'title': item.get('title', ''),
                        'artist': item.get('artist', ''),
                        'album': item.get('album', ''),
                        'source': item.get('source', ''),
                        'duration': item.get('duration', 0),
                        'raw': item
                    })
                    if len(formatted) >= limit:
                        break
            return formatted
        except Exception as e:
            print(f"搜索歌手失败: {e}")
            return []
    
    def get_sources(self) -> List[str]:
        """获取可用音源列表"""
        return self.config.get_sources()
