#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音乐发现引擎 - 智能分析用户偏好，发现符合爱好的音乐

核心功能:
  1. 理解用户自然语言描述的听歌偏好
  2. 从排行榜、歌单、搜索结果中挖掘音乐
  3. 基于歌手/风格/年代相似性推荐
  4. 构建高质量下载列表

用法:
    from music_discovery import MusicDiscovery
    discover = MusicDiscovery()
    
    # 发现符合偏好的歌曲
    songs = discover.discover_by_taste(
        taste_description="我喜欢周杰伦的中国风歌曲，还有洛天依的电音",
        max_songs=30
    )
"""

import os
import sys
import json
import re
import random
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
from pathlib import Path

# 导入同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smart_downloader import SmartDownloader, TOP_CHARTS, TOP_CHARTS_ALIASES, list_top_charts
from search_tools import SearchTools


# ========== 音乐风格/流派知识库 ==========

# 中文常见音乐风格标签
MUSIC_STYLES = {
    '流行': ['pop', '流行', 'pop music'],
    '摇滚': ['rock', '摇滚', 'rock music'],
    '民谣': ['folk', '民谣', '民谣音乐'],
    '电子': ['electronic', '电音', '电子音乐', 'edm'],
    '嘻哈': ['hiphop', '嘻哈', 'hip hop', 'rap'],
    'R&B': ['rnb', 'randb', '节奏布鲁斯'],
    '古风': ['古风', '中国风', '国风', '古风音乐'],
    '爵士': ['jazz', '爵士', '爵士乐'],
    '古典': ['classical', '古典', '古典音乐'],
    '轻音乐': ['轻音乐', '纯音乐', 'instrumental'],
    '民乐': ['民乐', '民族音乐', '中国传统音乐'],
    'ACG': ['acg', '动漫', '二次元', 'anime'],
    'VOCALOID': ['vocaloid', 'v家', '虚拟歌姬', '洛天依', '初音未来'],
    '说唱': ['rap', '说唱', '饶舌'],
    '金属': ['metal', '金属', '重金属'],
    '雷鬼': ['reggae', '雷鬼'],
    '蓝调': ['blues', '蓝调', '布鲁斯'],
    '乡村': ['country', '乡村', '乡村音乐'],
}

# 年代标签
ERA_TAGS = {
    '80后': '80s', '90后': '90s', '00后': '00s',
    '10后': '10s', '20后': '20s',
    '经典': 'classic', '最新': 'latest',
}

# 常见歌手/乐队（内置推荐库）
BUILTIN_ARTISTS = {
    '周杰伦': {'style': ['流行', 'R&B', '中国风'], 'era': '00s', 'hot_songs': [
        '七里香', '晴天', '夜曲', '稻香', '青花瓷', '告白气球',
        '简单爱', '枫', '搁浅', '彩虹', '蒲公英的约定', '说好的幸福呢',
        '一路向北', '不能说的秘密', '兰亭序', '烟花易冷', '红尘客栈',
    ]},
    '林俊杰': {'style': ['流行', 'R&B'], 'era': '00s', 'hot_songs': [
        '江南', '修炼爱情', '可惜没如果', '她说', '一千年以后',
        '不为谁而作的歌', '小酒窝', '美人鱼', '曹操', '醉赤壁',
    ]},
    '陈奕迅': {'style': ['流行', '情歌'], 'era': '00s', 'hot_songs': [
        '十年', '浮夸', 'K歌之王', '富士山下', '爱情转移',
        '淘汰', '圣诞结', '好久不见', '你的背包', '红玫瑰',
    ]},
    '邓紫棋': {'style': ['流行', 'R&B'], 'era': '10s', 'hot_songs': [
        '光年之外', '泡沫', '倒数', '句号', '来自天堂的魔鬼',
        '喜欢你', '差不多姑娘', '透明', '平凡天使', '天空没有极限',
    ]},
    '李荣浩': {'style': ['流行', '独立'], 'era': '10s', 'hot_songs': [
        '年少有为', '麻雀', '李白', '模特', '戒烟',
        '不将就', '喜剧之王', '爸爸妈妈', '乌梅子酱', '纵横四海',
    ]},
    '许嵩': {'style': ['流行', '中国风', '独立'], 'era': '00s', 'hot_songs': [
        '断桥残雪', '有何不可', '庐州月', '半城烟沙', '灰色头像',
        '清明雨上', '千百度', '素颜', '惊鸿一面', '雅俗共赏',
    ]},
    '洛天依': {'style': ['VOCALOID', '电子', '古风'], 'era': '10s', 'hot_songs': [
        '普通DISCO', '达拉崩吧', '权御天下', '万古生香', '霜雪千年',
        '东京不太热', '九九八十一', '勾指起誓', '一半一半', '千年食谱颂',
    ]},
    '初音未来': {'style': ['VOCALOID', '电子', 'ACG'], 'era': '00s', 'hot_songs': [
        '千本桜', '世界第一的公主殿下', 'メルト', '初音ミクの消失',
        'ロミオとシンデレラ', '恋愛サーキュレーション',
    ]},
    '赵雷': {'style': ['民谣', '独立'], 'era': '10s', 'hot_songs': [
        '成都', '南方姑娘', '理想', '少年锦时', '画',
        '吉姆餐厅', '鼓楼', '三十岁的女人', '阿刁', '我们的时光',
    ]},
    '朴树': {'style': ['民谣', '摇滚'], 'era': '00s', 'hot_songs': [
        '平凡之路', '那些花儿', '白桦林', '生如夏花', '送别',
        '清白之年', 'Forever Young', '在木星', '猎户星座', '达尼亚',
    ]},
    '毛不易': {'style': ['流行', '民谣'], 'era': '10s', 'hot_songs': [
        '消愁', '像我这样的人', '如果有一天我变得很有钱', '感觉自己是巨星',
        '借', '盛夏', '牧马城市', '不染', '无问', '东北民谣',
    ]},
    'Taylor Swift': {'style': ['流行', '乡村'], 'era': '00s', 'hot_songs': [
        'Love Story', 'Shake It Off', 'Blank Space', 'Bad Blood',
        'Look What You Made Me Do', 'Cardigan', 'Anti-Hero',
    ]},
    'Ed Sheeran': {'style': ['流行', '民谣'], 'era': '10s', 'hot_songs': [
        'Shape of You', 'Perfect', 'Photograph', 'Thinking Out Loud',
        'Castle on the Hill', 'Galway Girl', 'Bad Habits', 'Shivers',
    ]},
}

# 中国风歌曲库
CHINESE_STYLE_SONGS = [
    {'title': '青花瓷', 'artist': '周杰伦'},
    {'title': '兰亭序', 'artist': '周杰伦'},
    {'title': '烟花易冷', 'artist': '周杰伦'},
    {'title': '红尘客栈', 'artist': '周杰伦'},
    {'title': '菊花台', 'artist': '周杰伦'},
    {'title': '东风破', 'artist': '周杰伦'},
    {'title': '发如雪', 'artist': '周杰伦'},
    {'title': '千里之外', 'artist': '周杰伦'},
    {'title': '断桥残雪', 'artist': '许嵩'},
    {'title': '庐州月', 'artist': '许嵩'},
    {'title': '半城烟沙', 'artist': '许嵩'},
    {'title': '清明雨上', 'artist': '许嵩'},
    {'title': '千百度', 'artist': '许嵩'},
    {'title': '惊鸿一面', 'artist': '许嵩'},
    {'title': '倾尽天下', 'artist': '河图'},
    {'title': '第三十八年夏至', 'artist': '河图'},
    {'title': '盛唐夜唱', 'artist': 'EDIQ'},
    {'title': '权御天下', 'artist': '洛天依'},
    {'title': '万古生香', 'artist': '洛天依'},
    {'title': '华夏', 'artist': 'Winky诗'},
    {'title': '山鬼', 'artist': 'Winky诗'},
    {'title': '一身诗意千寻瀑', 'artist': '不才'},
    {'title': '牵丝戏', 'artist': '银临'},
    {'title': '锦鲤抄', 'artist': '银临'},
    {'title': '腐草为萤', 'artist': '银临'},
    {'title': '泸沽寻梦', 'artist': '银临'},
    {'title': '典狱司', 'artist': '音频怪物'},
    {'title': '琴师', 'artist': '音频怪物'},
    {'title': '长安忆', 'artist': '音频怪物'},
    {'title': '白石溪', 'artist': '洛天依'},
    {'title': '霜雪千年', 'artist': '洛天依'},
    {'title': '普通DISCO', 'artist': '洛天依'},
    {'title': '达拉崩吧', 'artist': '洛天依'},
    {'title': '九九八十一', 'artist': '洛天依'},
]


class TasteAnalyzer:
    """口味分析器 - 从自然语言中解析用户的音乐偏好"""

    def __init__(self):
        self.style_map = MUSIC_STYLES
        self.era_map = ERA_TAGS

    def analyze(self, description: str) -> Dict:
        """
        分析用户描述，提取音乐偏好

        Args:
            description: 自然语言描述，如 "我喜欢周杰伦的中国风歌曲，还有洛天依的电音"

        Returns:
            {
                'artists': ['周杰伦', '洛天依'],
                'styles': ['中国风', '电子'],
                'eras': [],
                'keywords': ['中国风', '电音', '周杰伦', '洛天依'],
                'raw_description': description,
            }
        """
        result = {
            'artists': [],
            'styles': [],
            'eras': [],
            'keywords': [],
            'raw_description': description,
        }

        text = description.lower()

        # 1. 识别歌手
        for artist_name in BUILTIN_ARTISTS:
            if artist_name.lower() in text:
                result['artists'].append(artist_name)
                result['keywords'].append(artist_name)

        # 2. 识别风格
        for style_name, aliases in self.style_map.items():
            for alias in aliases:
                if alias.lower() in text:
                    if style_name not in result['styles']:
                        result['styles'].append(style_name)
                    result['keywords'].append(style_name)
                    break

        # 3. 识别年代
        for tag_name, tag_value in self.era_map.items():
            if tag_name.lower() in text:
                result['eras'].append(tag_value)
                result['keywords'].append(tag_name)

        return result

    def expand_preferences(self, prefs: Dict) -> List[str]:
        """
        基于分析结果扩展搜索关键词

        Args:
            prefs: analyze() 的输出

        Returns:
            搜索关键词列表，用于发现更多音乐
        """
        keywords = set()

        # 基于歌手扩展
        for artist in prefs['artists']:
            keywords.add(f"{artist} 热门歌曲")
            keywords.add(f"{artist} 代表作")
            if artist in BUILTIN_ARTISTS:
                info = BUILTIN_ARTISTS[artist]
                for style in info.get('style', []):
                    keywords.add(f"{artist} {style} 风格")

        # 基于风格扩展
        for style in prefs['styles']:
            keywords.add(f"{style} 歌曲推荐")
            keywords.add(f"{style} 热门歌单")
            keywords.add(f"{style} 经典歌曲")

        # 组合扩展
        for artist in prefs['artists']:
            for style in prefs['styles']:
                keywords.add(f"{artist} {style}")

        return list(keywords)


class MusicDiscovery:
    """
    音乐发现引擎 - 智能挖掘用户喜欢的音乐
    组合多种发现策略来寻找符合用户口味的歌曲
    """

    def __init__(self, search_tools: Optional[SearchTools] = None):
        """
        初始化

        Args:
            search_tools: SearchTools 实例（可选，会自动创建）
        """
        self.search = search_tools or SearchTools()
        self.analyzer = TasteAnalyzer()
        self.downloader = SmartDownloader()
        # 记录已发现的歌曲（去重）
        self._discovered: Set[str] = set()

    def discover_by_taste(self, taste_description: str, max_songs: int = 30,
                          include_charts: bool = True,
                          include_search: bool = True,
                          include_similar: bool = True) -> List[Dict[str, str]]:
        """
        根据自然语言描述的偏好发现音乐

        Args:
            taste_description: 口味描述，如 "我喜欢周杰伦的中国风，也听洛天依"
            max_songs: 最大歌曲数
            include_charts: 是否从排行榜发现
            include_search: 是否从网络搜索发现
            include_similar: 是否基于相似歌手发现

        Returns:
            [{'title': str, 'artist': str}, ...]
        """
        print(f"\n{'='*60}")
        print(f"  [发现] 音乐发现引擎启动")
        print(f"  用户偏好: {taste_description}")
        print(f"{'='*60}")

        # 分析口味
        prefs = self.analyzer.analyze(taste_description)
        print(f"\n[分析结果]")
        print(f"  歌手: {prefs['artists'] or '(未识别)'}")
        print(f"  风格: {prefs['styles'] or '(未识别)'}")
        print(f"  关键词: {prefs['keywords']}")

        all_songs: List[Dict[str, str]] = []

        # 策略 1: 从内置歌曲库匹配
        print(f"\n[策略 1/4] 内置歌曲库匹配...")
        builtin_songs = self._discover_from_builtin(prefs)
        all_songs.extend(builtin_songs)
        print(f"  -> 找到 {len(builtin_songs)} 首")

        # 策略 2: 从排行榜发现
        if include_charts:
            print(f"\n[策略 2/4] 排行榜发现...")
            chart_songs = self._discover_from_charts(prefs, max_songs // 3)
            all_songs.extend(chart_songs)
            print(f"  -> 找到 {len(chart_songs)} 首")

        # 策略 3: 网络搜索发现
        if include_search:
            print(f"\n[策略 3/4] 网络搜索发现...")
            search_songs = self._discover_from_search(prefs, max_songs // 3)
            all_songs.extend(search_songs)
            print(f"  -> 找到 {len(search_songs)} 首")

        # 策略 4: 基于相似歌手发现
        if include_similar:
            print(f"\n[策略 4/4] 相似歌手/风格发现...")
            similar_songs = self._discover_similar(prefs, max_songs // 3)
            all_songs.extend(similar_songs)
            print(f"  -> 找到 {len(similar_songs)} 首")

        # 合并去重
        final_songs = self._dedup_and_merge(all_songs)

        # 限制数量
        if max_songs > 0 and len(final_songs) > max_songs:
            final_songs = final_songs[:max_songs]

        print(f"\n{'='*60}")
        print(f"  [OK] 音乐发现完成！最终推荐 {len(final_songs)} 首歌曲")
        print(f"{'='*60}")

        return final_songs

    def _discover_from_builtin(self, prefs: Dict) -> List[Dict[str, str]]:
        """从内置歌曲库匹配用户偏好"""
        songs = []
        seen = set()

        # 如果识别出具体歌手，直接取热门歌曲
        for artist in prefs['artists']:
            if artist in BUILTIN_ARTISTS:
                for song_title in BUILTIN_ARTISTS[artist]['hot_songs']:
                    key = f"{song_title}|{artist}"
                    if key not in seen:
                        songs.append({'title': song_title, 'artist': artist})
                        seen.add(key)

        # 如果是中国风偏好，添加中国风歌曲库
        if any(style in ['中国风', '古风', '国风'] for style in prefs['styles']):
            for s in CHINESE_STYLE_SONGS:
                key = f"{s['title']}|{s['artist']}"
                if key not in seen:
                    songs.append(s)
                    seen.add(key)

        return songs

    def _discover_from_charts(self, prefs: Dict, max_count: int) -> List[Dict[str, str]]:
        """从热门排行榜发现音乐"""
        songs = []
        seen = set()

        # 根据偏好选择合适的排行榜
        chart_keys = []

        # 总是包含一些通用热门榜
        if prefs['styles']:
            # 偏好有风格倾向
            if any(s in ['中国风', '古风'] for s in prefs['styles']):
                chart_keys.extend(['qq_mainland', 'netease_orig'])
            elif any(s in ['电子', 'VOCALOID', 'ACG'] for s in prefs['styles']):
                chart_keys.extend(['qq_hot', 'netease_new'])
            else:
                chart_keys.extend(['qq_hot', 'netease_hot', 'netease_new'])
        else:
            chart_keys.extend(['qq_hot', 'netease_hot', 'netease_soar'])

        # 遍历排行榜获取歌曲
        for chart_key in chart_keys[:3]:  # 最多取 3 个榜
            try:
                chart_songs = self.downloader.get_top_chart(chart_key, limit=15)
                for s in chart_songs:
                    key = f"{s['title']}|{s['artist']}"
                    if key not in seen:
                        songs.append(s)
                        seen.add(key)
            except Exception as e:
                print(f"  [排行榜 {chart_key}] 获取失败: {e}")

        return songs[:max_count]

    def _discover_from_search(self, prefs: Dict, max_count: int) -> List[Dict[str, str]]:
        """通过网络搜索发现音乐"""
        songs = []
        seen = set()

        # 生成搜索关键词
        keywords = self.analyzer.expand_preferences(prefs)

        # 取前 3 个关键词搜索
        for keyword in keywords[:3]:
            try:
                results = self.search.search_web(keyword, max_results=5)
                for r in results:
                    # 尝试从搜索结果提取歌曲信息
                    extracted = self._extract_songs_from_text(
                        f"{r['title']} {r['snippet']}"
                    )
                    for s in extracted:
                        key = f"{s['title']}|{s['artist']}"
                        if key not in seen:
                            songs.append(s)
                            seen.add(key)
            except Exception as e:
                print(f"  [搜索 {keyword}] 失败: {e}")

        return songs[:max_count]

    def _discover_similar(self, prefs: Dict, max_count: int) -> List[Dict[str, str]]:
        """基于相似歌手/风格发现"""
        songs = []
        seen = set()

        # 风格 → 歌手映射
        style_to_artists = {}
        for artist, info in BUILTIN_ARTISTS.items():
            for style in info.get('style', []):
                if style not in style_to_artists:
                    style_to_artists[style] = []
                style_to_artists[style].append(artist)

        # 收集相似歌手
        similar_artists = set()
        for style in prefs['styles']:
            if style in style_to_artists:
                for artist in style_to_artists[style]:
                    if artist not in prefs['artists']:
                        similar_artists.add(artist)

        # 取相似歌手的热门歌曲
        for artist in list(similar_artists)[:5]:
            if artist in BUILTIN_ARTISTS:
                for song_title in BUILTIN_ARTISTS[artist]['hot_songs'][:5]:
                    key = f"{song_title}|{artist}"
                    if key not in seen:
                        songs.append({'title': song_title, 'artist': artist})
                        seen.add(key)

        return songs[:max_count]

    def discover_by_artist(self, artist_name: str, max_songs: int = 20) -> List[Dict[str, str]]:
        """
        发现特定歌手的歌曲

        Args:
            artist_name: 歌手名
            max_songs: 最大歌曲数
        """
        songs = []

        # 内置库
        if artist_name in BUILTIN_ARTISTS:
            for title in BUILTIN_ARTISTS[artist_name]['hot_songs']:
                songs.append({'title': title, 'artist': artist_name})

        # 搜索网络获取更多
        try:
            results = self.search.search_web(f"{artist_name} 全部歌曲 代表作品", max_results=3)
            for r in results:
                extracted = self._extract_songs_from_text(f"{r['title']} {r['snippet']}", artist_name)
                for s in extracted:
                    if s not in songs:
                        songs.append(s)
        except Exception:
            pass

        return songs[:max_songs]

    def discover_by_style(self, style: str, max_songs: int = 20) -> List[Dict[str, str]]:
        """
        按音乐风格发现歌曲

        Args:
            style: 风格名称（中国风、民谣、电子...）
            max_songs: 最大歌曲数
        """
        songs = []
        seen = set()

        # 从内置歌手匹配风格
        for artist, info in BUILTIN_ARTISTS.items():
            if any(style in s for s in info.get('style', [])):
                for title in info['hot_songs'][:5]:
                    key = f"{title}|{artist}"
                    if key not in seen:
                        songs.append({'title': title, 'artist': artist})
                        seen.add(key)

        # 从排行榜找
        try:
            chart_songs = self.downloader.get_top_chart('qq_hot', limit=10)
            for s in chart_songs:
                key = f"{s['title']}|{s['artist']}"
                if key not in seen:
                    songs.append(s)
                    seen.add(key)
        except Exception:
            pass

        return songs[:max_songs]

    def discover_from_chart(self, chart_key: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        从指定排行榜发现歌曲

        Args:
            chart_key: 排行榜键名
            limit: 限制数量
        """
        try:
            return self.downloader.get_top_chart(chart_key, limit=limit)
        except Exception as e:
            print(f"  获取排行榜失败: {e}")
            return []

    def save_to_queue_file(self, songs: List[Dict[str, str]], 
                           filepath: str = 'song-queue.txt') -> str:
        """
        将发现的歌曲保存到队列文件

        Args:
            songs: 歌曲列表
            filepath: 保存路径

        Returns:
            保存的文件路径
        """
        # 去重
        seen = set()
        unique_songs = []
        for s in songs:
            key = f"{s['title']}|{s.get('artist', '')}"
            if key not in seen:
                seen.add(key)
                unique_songs.append(s)

        # 生成内容
        lines = [
            f"# 智能发现歌曲列表 - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"# 共 {len(unique_songs)} 首歌曲",
            "",
        ]
        for s in unique_songs:
            artist = s.get('artist', '')
            if artist:
                lines.append(f"{s['title']}, {artist}")
            else:
                lines.append(s['title'])

        # 写入文件
        content = '\n'.join(lines) + '\n'
        fp = Path(filepath)
        fp.write_text(content, encoding='utf-8')

        print(f"\n歌曲列表已保存到: {filepath}")
        print(f"共 {len(unique_songs)} 首歌曲")

        return str(fp)

    def _extract_songs_from_text(self, text: str, default_artist: str = '') -> List[Dict[str, str]]:
        """
        从文本中提取歌曲信息
        尝试匹配 "歌名 - 歌手"、"歌名/歌手" 等常见格式
        """
        songs = []

        # 模式 1: "歌名 - 歌手"
        pattern1 = re.findall(r'[《]([^》]+)[》]\s*[-–—]\s*([^\s,，、]+)', text)
        for title, artist in pattern1:
            if title and len(title) < 30:
                songs.append({'title': title.strip(), 'artist': artist.strip()})

        # 模式 2: "歌名 / 歌手"
        pattern2 = re.findall(r'[《]([^》]+)[》]\s*[/]\s*([^\s,，、]+)', text)
        for title, artist in pattern2:
            if title and len(title) < 30:
                songs.append({'title': title.strip(), 'artist': artist.strip()})

        # 如果没有识别到，但知道歌手
        if not songs and default_artist:
            # 简单提取书名号内的内容
            titles_in_brackets = re.findall(r'[《]([^》]+)[》]', text)
            for title in titles_in_brackets:
                if title and len(title) < 30:
                    songs.append({'title': title.strip(), 'artist': default_artist})

        return songs

    def _dedup_and_merge(self, songs: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """合并去重"""
        seen = set()
        result = []
        for s in songs:
            key = f"{s['title']}|{s.get('artist', '')}"
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result

    def list_available_charts(self):
        """列出所有可用的排行榜"""
        list_top_charts()

    def list_builtin_artists(self) -> List[str]:
        """列出内置的歌手库"""
        return list(BUILTIN_ARTISTS.keys())

    def list_chinese_style_songs(self) -> List[Dict[str, str]]:
        """列出内置中国风歌曲库"""
        return CHINESE_STYLE_SONGS


# ========== CLI 独立运行 ==========
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='音乐发现引擎')
    parser.add_argument('--taste', '-t', type=str, default='',
                        help='描述你的听歌偏好，如 "我喜欢周杰伦的中国风"')
    parser.add_argument('--artist', '-a', type=str, default='',
                        help='发现指定歌手的歌曲')
    parser.add_argument('--style', '-s', type=str, default='',
                        help='按风格发现歌曲，如 民谣、中国风、电子')
    parser.add_argument('--chart', '-c', type=str, default='',
                        help='从排行榜发现，如 qq_hot')
    parser.add_argument('--max-songs', type=int, default=20,
                        help='最大歌曲数')
    parser.add_argument('--save', action='store_true',
                        help='保存到 song-queue.txt')
    parser.add_argument('--list-artists', action='store_true',
                        help='列出内置歌手库')
    parser.add_argument('--list-charts', action='store_true',
                        help='列出可用排行榜')

    args = parser.parse_args()
    discover = MusicDiscovery()

    if args.list_artists:
        print("\n内置歌手库:")
        for name in discover.list_builtin_artists():
            info = BUILTIN_ARTISTS[name]
            print(f"  {name:12s} 风格: {', '.join(info['style']):20s} 代表作: {info['hot_songs'][0]}")
        sys.exit(0)

    if args.list_charts:
        discover.list_available_charts()
        sys.exit(0)

    songs = []

    if args.taste:
        songs = discover.discover_by_taste(args.taste, max_songs=args.max_songs)
    elif args.artist:
        songs = discover.discover_by_artist(args.artist, max_songs=args.max_songs)
    elif args.style:
        songs = discover.discover_by_style(args.style, max_songs=args.max_songs)
    elif args.chart:
        songs = discover.discover_from_chart(args.chart, limit=args.max_songs)
    else:
        parser.print_help()
        sys.exit(1)

    if songs:
        print(f"\n发现的歌曲 ({len(songs)} 首):")
        for i, s in enumerate(songs, 1):
            artist = s.get('artist', '')
            print(f"  {i:3d}. {s['title']:20s} - {artist}")

        if args.save:
            discover.save_to_queue_file(songs)
    else:
        print("\n未发现歌曲，请尝试其他搜索条件")
