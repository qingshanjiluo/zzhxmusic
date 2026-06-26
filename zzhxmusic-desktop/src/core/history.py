import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class HistoryService:
    """历史记录服务类"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path.home() / '.zzhxmusic' / 'history.db')
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 创建搜索历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                search_type TEXT NOT NULL,
                source TEXT,
                result_count INTEGER,
                timestamp TEXT NOT NULL
            )
        ''')
        
        # 创建下载历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                source TEXT,
                quality TEXT,
                filepath TEXT,
                status TEXT,
                error TEXT,
                timestamp TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_search(self, keyword: str, search_type: str, source: str = '', result_count: int = 0):
        """添加搜索记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO search_history (keyword, search_type, source, result_count, timestamp) VALUES (?, ?, ?, ?, ?)',
            (keyword, search_type, source, result_count, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    
    def add_download(self, song_info: Dict, quality: str, status: str, filepath: str = '', error: str = ''):
        """添加下载记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO download_history (title, artist, album, source, quality, filepath, status, error, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                song_info.get('title', ''),
                song_info.get('artist', ''),
                song_info.get('album', ''),
                song_info.get('source', ''),
                quality,
                filepath,
                status,
                error,
                datetime.now().isoformat()
            )
        )
        conn.commit()
        conn.close()
    
    def get_search_history(self, limit: int = 100) -> List[Dict]:
        """获取搜索历史"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM search_history ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_download_history(self, limit: int = 200) -> List[Dict]:
        """获取下载历史"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM download_history ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_download_by_keyword(self, keyword: str, limit: int = 50) -> List[Dict]:
        """按关键词搜索下载历史"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM download_history WHERE title LIKE ? OR artist LIKE ? ORDER BY timestamp DESC LIMIT ?',
            (f'%{keyword}%', f'%{keyword}%', limit)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def clear_search_history(self):
        """清空搜索历史"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute('DELETE FROM search_history')
        conn.commit()
        conn.close()
    
    def clear_download_history(self):
        """清空下载历史"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute('DELETE FROM download_history')
        conn.commit()
        conn.close()
    
    def delete_download_record(self, record_id: int):
        """删除单条下载记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute('DELETE FROM download_history WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
