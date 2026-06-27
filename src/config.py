#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """配置管理类"""
    
    DEFAULT_CONFIG = {
        'sources': ['QQMusicClient', 'NeteaseMusicClient', 'KuwoMusicClient'],
        'output_dir': './downloads',
        'search_size': 10,
        'quality': 'flac',
        'max_workers': 3
    }
    
    def __init__(self, config: Optional[Dict] = None, config_path: Optional[str] = None):
        """初始化配置"""
        self.config = self.DEFAULT_CONFIG.copy()
        
        # 从文件加载
        if config_path:
            self.load_from_file(config_path)
        
        # 从字典更新
        if config:
            self.config.update(config)
    
    def load_from_file(self, config_path: str):
        """从文件加载配置"""
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.config.update(loaded)
            except Exception as e:
                print(f"加载配置文件失败: {e}")
    
    def save_to_file(self, config_path: str):
        """保存配置到文件"""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self.config[key] = value
    
    def get_sources(self) -> list:
        """获取音源列表"""
        return self.get('sources', [])
    
    def get_output_dir(self) -> str:
        """获取输出目录"""
        return self.get('output_dir', './downloads')
    
    def get_quality(self) -> str:
        """获取默认音质"""
        return self.get('quality', 'flac')
    
    def get_max_workers(self) -> int:
        """获取最大并发数"""
        return self.get('max_workers', 3)
    
    def get_search_size(self) -> int:
        """获取搜索数量"""
        return self.get('search_size', 10)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return self.config.copy()
