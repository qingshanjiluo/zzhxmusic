import os
import sys
import threading
from pathlib import Path
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 添加项目根目录到路径
_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

try:
    from musicdl import musicdl
except ImportError:
    print("警告: musicdl 未安装，请运行 pip install musicdl")
    musicdl = None

from .config import ConfigManager


class DownloadTask:
    """下载任务类"""
    
    def __init__(self, song_info: Dict, quality: str = 'flac'):
        self.song_info = song_info
        self.quality = quality
        self.status = 'pending'  # pending, downloading, completed, failed, paused
        self.progress = 0
        self.filepath = None
        self.error = None
        self.start_time = None
        self.end_time = None
        self._raw_result = None
    
    def to_dict(self) -> Dict:
        return {
            'title': self.song_info.get('title', ''),
            'artist': self.song_info.get('artist', ''),
            'album': self.song_info.get('album', ''),
            'source': self.song_info.get('source', ''),
            'quality': self.quality,
            'status': self.status,
            'progress': self.progress,
            'filepath': self.filepath,
            'error': self.error,
            'start_time': self.start_time,
            'end_time': self.end_time
        }


class DownloadService:
    """下载服务类"""
    
    def __init__(self, config: Optional[ConfigManager] = None):
        self.config = config or ConfigManager()
        self.client = None
        self.tasks: List[DownloadTask] = []
        self._lock = threading.Lock()
        self._executor = None
        self._max_workers = self.config.get('max_concurrent', 3)
        self._init_client()
    
    def _init_client(self):
        """初始化 musicdl 客户端"""
        if musicdl is None:
            return
        
        sources = self.config.get_sources()
        try:
            self.client = musicdl.MusicClient(
                music_sources=sources,
                init_music_clients_cfg={src: {} for src in sources}
            )
        except Exception as e:
            print(f"初始化客户端失败: {e}")
            self.client = None
    
    def add_tasks(self, song_infos: List[Dict], quality: Optional[str] = None) -> List[DownloadTask]:
        """添加下载任务"""
        if quality is None:
            quality = self.config.get_quality()
        
        tasks = []
        with self._lock:
            for info in song_infos:
                task = DownloadTask(info, quality)
                self.tasks.append(task)
                tasks.append(task)
        return tasks
    
    def start_download(self, task: DownloadTask, callback: Optional[Callable] = None):
        """开始下载单个任务"""
        if self.client is None:
            task.status = 'failed'
            task.error = '客户端未初始化'
            if callback:
                callback(task)
            return
        
        task.status = 'downloading'
        task.start_time = datetime.now().isoformat()
        
        try:
            # 获取原始歌曲信息
            raw = task.song_info.get('raw', task.song_info)
            
            # 执行下载
            result = self.client.download(raw, quality=task.quality)
            
            if result:
                task.status = 'completed'
                task.filepath = result.get('filepath', '')
                task.progress = 100
            else:
                task.status = 'failed'
                task.error = '下载返回空结果'
        except Exception as e:
            task.status = 'failed'
            task.error = str(e)
        
        task.end_time = datetime.now().isoformat()
        
        if callback:
            callback(task)
    
    def start_batch(self, tasks: List[DownloadTask], 
                    on_progress: Optional[Callable] = None,
                    on_complete: Optional[Callable] = None):
        """批量下载"""
        def download_wrapper(task):
            self.start_download(task, on_progress)
            return task
        
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(download_wrapper, task): task for task in tasks}
            
            for future in as_completed(futures):
                task = futures[future]
                if on_complete:
                    on_complete(task)
    
    def get_tasks(self) -> List[DownloadTask]:
        """获取所有任务"""
        with self._lock:
            return self.tasks.copy()
    
    def get_active_tasks(self) -> List[DownloadTask]:
        """获取活跃任务"""
        with self._lock:
            return [t for t in self.tasks if t.status in ['pending', 'downloading']]
    
    def clear_completed(self):
        """清除已完成的任务"""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status not in ['completed', 'failed']]
    
    def retry_failed(self) -> List[DownloadTask]:
        """重试失败的任务"""
        with self._lock:
            failed = [t for t in self.tasks if t.status == 'failed']
            for task in failed:
                task.status = 'pending'
                task.error = None
                task.progress = 0
            return failed
