import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """配置管理类"""
    
    DEFAULT_CONFIG = {
        'download_dir': str(Path.home() / 'Music' / 'zzhxmusic'),
        'quality': 'flac',
        'max_concurrent': 3,
        'music_sources': ['QQMusicClient', 'NeteaseMusicClient', 'KuwoMusicClient'],
        'proxy': '',
        'auto_start': False,
        'minimize_to_tray': True,
        'history_limit': 500,
        'theme': 'dark'
    }
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = str(Path.home() / '.zzhxmusic' / 'config.json')
        self.config_path = Path(config_path)
        self.config = {}
        self._ensure_config_dir()
        self.load()
    
    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
    
    def load(self):
        """加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 合并默认配置
                    self.config = {**self.DEFAULT_CONFIG, **loaded}
            except Exception:
                self.config = self.DEFAULT_CONFIG.copy()
        else:
            self.config = self.DEFAULT_CONFIG.copy()
            self.save()
    
    def save(self):
        """保存配置"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self.config[key] = value
        self.save()
    
    def get_download_dir(self) -> Path:
        """获取下载目录"""
        path = Path(self.get('download_dir'))
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_quality(self) -> str:
        """获取默认音质"""
        return self.get('quality', 'flac')
    
    def get_sources(self) -> list:
        """获取音源列表"""
        return self.get('music_sources', ['QQMusicClient', 'NeteaseMusicClient'])
