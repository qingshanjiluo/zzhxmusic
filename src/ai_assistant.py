#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 智能音乐助手 - 核心编排器

接收自然语言任务目标，综合调用搜索、发现、下载工具
完成从"我想听..."到"歌曲下载完成"的全流程自动化

工作流程:
  1. 解析用户任务目标和 API 密钥
  2. 分析用户偏好 → 调用搜索/音乐发现引擎收集歌曲
  3. 去重整理 → 生成下载队列
  4. 调用 smart_downloader 执行下载
  5. 打包结果 → 生成 AI 报告

GitHub Actions 用法:
  手动触发工作流 → 填写任务目标和 API 密钥 → AI 自动完成

API 密钥说明:
  - OPENAI_API_KEY / DEEPSEEK_API_KEY: 用于 AI 理解任务（可选，也支持纯规则模式）
  - BROWSERACT_API_KEY: 用于 browser-act stealth 模式搜索（可选，免费注册 https://www.browseract.com）
  - SERPAPI_KEY: 用于 SerpAPI 付费搜索（可选，完全不需要，browser-act 免费即可用）
"""

import os
import sys
import json
import re
import argparse
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path

# 导入同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smart_downloader import SmartDownloader, list_top_charts
from search_tools import SearchTools
from music_discovery import MusicDiscovery


# ========== 工具注册 ==========

AVAILABLE_TOOLS = {
    'search_web': {
        'name': '网络搜索',
        'description': '搜索网络信息，获取音乐资讯、热门歌曲、歌手信息等',
        'params': {'query': '搜索关键词'},
    },
    'search_music_news': {
        'name': '音乐资讯搜索',
        'description': '搜索音乐相关的新闻、排行榜信息',
        'params': {'query': '搜索关键词'},
    },
    'fetch_page_content': {
        'name': '获取网页内容',
        'description': '获取指定 URL 的网页文本内容',
        'params': {'url': '网页地址'},
    },
    'list_charts': {
        'name': '列出排行榜',
        'description': '列出所有可用的音乐排行榜',
        'params': {},
    },
    'get_chart': {
        'name': '获取排行榜',
        'description': '获取指定排行榜的歌曲列表',
        'params': {'chart_key': '排行榜键名', 'limit': '限制数量'},
    },
    'discover_by_taste': {
        'name': '按口味发现',
        'description': '根据自然语言描述的音乐偏好，智能发现匹配的歌曲',
        'params': {'taste': '口味描述', 'max_songs': '最大歌曲数'},
    },
    'discover_by_artist': {
        'name': '按歌手发现',
        'description': '发现指定歌手的歌曲',
        'params': {'artist': '歌手名', 'max_songs': '最大歌曲数'},
    },
    'discover_by_style': {
        'name': '按风格发现',
        'description': '按音乐风格发现歌曲',
        'params': {'style': '风格名称', 'max_songs': '最大歌曲数'},
    },
    'download_songs': {
        'name': '下载歌曲',
        'description': '下载指定歌曲列表，支持并发、多种音质和打包',
        'params': {
            'songs': '歌曲列表',
            'source': '首选音源',
            'quality': '音质',
            'workers': '并发数',
        },
    },
    'save_queue': {
        'name': '保存队列',
        'description': '将发现的歌曲列表保存到文件',
        'params': {'songs': '歌曲列表', 'filepath': '保存路径'},
    },
}


class AIAssistant:
    """
    AI 智能音乐助手 - 核心编排器

    接收用户的任务目标，自动编排搜索、发现、下载流程
    支持纯规则模式（无 LLM API）和 AI 增强模式（有 LLM API）
    """

    def __init__(self,
                 openai_api_key: str = '',
                 deepseek_api_key: str = '',
                 serpapi_key: str = '',
                 browseract_api_key: str = '',
                 model: str = 'deepseek-chat'):
        """
        初始化 AI 助手

        Args:
            openai_api_key: OpenAI API 密钥（可选）
            deepseek_api_key: DeepSeek API 密钥（可选，优先使用）
            serpapi_key: SerpAPI 密钥（可选，已不再推荐，保留向后兼容）
            browseract_api_key: BrowserAct API key（可选，免费注册 https://www.browseract.com）
                                 用于 stealth 模式搜索。不设置时自动使用 chrome 模式（无需 key）
            model: 使用的 AI 模型名
        """
        self.openai_api_key = openai_api_key or os.environ.get('OPENAI_API_KEY', '')
        self.deepseek_api_key = deepseek_api_key or os.environ.get('DEEPSEEK_API_KEY', '')
        self.serpapi_key = serpapi_key or os.environ.get('SERPAPI_KEY', '')
        self.browseract_api_key = browseract_api_key or os.environ.get('BROWSERACT_API_KEY', '')
        self.model = model

        # 子模块
        self.search = SearchTools(
            serpapi_key=self.serpapi_key,
            browseract_api_key=self.browseract_api_key
        )
        self.discovery = MusicDiscovery(search_tools=self.search)

        # 是否启用 AI 增强
        self.ai_enabled = bool(self.openai_api_key) or bool(self.deepseek_api_key)
        if self.ai_enabled:
            print(f"[AI助手] AI 增强模式已启用 (model={self.model})")
        else:
            print("[AI助手] 纯规则模式（未设置 API 密钥，使用内置规则分析）")

        # 执行轨迹
        self.execution_trace = []

    def execute_task(self, task_goal: str, options: Optional[Dict] = None) -> Dict:
        """
        执行用户的任务目标 - 主入口

        Args:
            task_goal: 自然语言任务目标
                如: "帮我找周杰伦的中国风歌曲并下载"
                     "我想听一些民谣和洛天依的歌"
                     "下载QQ热歌榜前30首，mp3格式"
            options: 可选参数
                {
                    'source': 'QQMusicClient',  # 首选音源
                    'quality': 'flac',           # 音质
                    'workers': 10,               # 并发下载数
                    'max_songs': 30,             # 最大歌曲数
                    'output_dir': './downloads', # 输出目录
                    'no_download': False,        # 仅发现不下载
                    'save_queue': True,          # 保存歌曲队列
                }

        Returns:
            {
                'status': 'success' | 'partial' | 'error',
                'message': str,
                'task_goal': str,
                'discovered_songs': [...],
                'download_results': {...},
                'execution_trace': [...],
                'saved_queue': str,
                'report': str,
            }
        """
        options = options or {}
        source = options.get('source', 'QQMusicClient')
        quality = options.get('quality', 'flac')
        workers = options.get('workers', 10)
        max_songs = options.get('max_songs', 30)
        output_dir = options.get('output_dir', './downloads')
        no_download = options.get('no_download', False)
        save_queue = options.get('save_queue', True)

        result = {
            'status': 'pending',
            'task_goal': task_goal,
            'message': '',
            'discovered_songs': [],
            'download_results': {},
            'execution_trace': [],
            'saved_queue': '',
            'report': '',
        }

        self.execution_trace = []
        self._add_trace('task_received', f"收到任务: {task_goal}")
        print(f"\n{'='*60}")
        print(f"  [AI] 智能音乐助手")
        print(f"  {'='*50}")
        print(f"  任务目标: {task_goal}")
        print(f"  音源: {source} | 音质: {quality} | 并发: {workers}")
        print(f"  AI增强: {'[OK] 已启用' if self.ai_enabled else '[!] 未启用(纯规则模式)'}")
        print(f"{'='*60}")

        try:
            # ========== 阶段 1: 任务理解 ==========
            self._add_trace('analyzing', '正在理解任务目标...')
            print(f"\n[阶段 1/4] 任务理解与意图分析")
            print("-" * 50)

            intent = self._analyze_intent(task_goal)
            print(f"  任务类型: {intent['type']}")
            if intent['artists']:
                print(f"  识别的歌手: {', '.join(intent['artists'])}")
            if intent['styles']:
                print(f"  识别的风格: {', '.join(intent['styles'])}")
            if intent['charts']:
                print(f"  识别的排行榜: {', '.join(intent['charts'])}")
            if intent['keywords']:
                print(f"  其他关键词: {', '.join(intent['keywords'])}")

            result['execution_trace'].append({
                'phase': 'analyze',
                'intent': intent,
            })

            # ========== 阶段 2: 歌曲发现 ==========
            self._add_trace('discovering', '正在搜索和发现歌曲...')
            print(f"\n[阶段 2/4] 歌曲发现")
            print("-" * 50)

            discovered = self._discover_songs(intent, max_songs)
            print(f"\n  发现歌曲总数: {len(discovered)} 首")

            if discovered:
                print(f"  前 10 首预览:")
                for i, s in enumerate(discovered[:10], 1):
                    artist = s.get('artist', '')
                    print(f"    {i:3d}. {s['title']:20s} - {artist}")
                if len(discovered) > 10:
                    print(f"    ... 还有 {len(discovered) - 10} 首")
            else:
                print("   [!] 未发现任何歌曲，尝试从热门排行榜获取")
                if not no_download:
                    chart_songs = self._get_default_chart_songs(limit=20)
                    discovered = chart_songs
                    print(f"  从排行榜获取到 {len(discovered)} 首")

            result['discovered_songs'] = discovered
            result['execution_trace'].append({
                'phase': 'discover',
                'song_count': len(discovered),
            })

            # 保存队列文件
            if save_queue and discovered:
                queue_path = self.discovery.save_to_queue_file(discovered, 'song-queue.txt')
                result['saved_queue'] = queue_path
                self._add_trace('save_queue', f"队列已保存到 {queue_path}")

            # ========== 阶段 3: 任务规划 ==========
            self._add_trace('planning', '正在制定下载计划...')
            print(f"\n[阶段 3/4] 执行规划")
            print("-" * 50)

            plan = self._make_plan(intent, discovered, {
                'source': source,
                'quality': quality,
                'workers': workers,
                'output_dir': output_dir,
            })

            print(f"  执行计划:")
            for step in plan.get('steps', []):
                print(f"    {step}")

            result['execution_trace'].append({
                'phase': 'plan',
                'plan': plan,
            })

            # ========== 阶段 4: 执行下载 ==========
            if not no_download and discovered:
                self._add_trace('downloading', '开始下载...')
                print(f"\n[阶段 4/4] 执行下载")
                print("-" * 50)

                download_results = self._execute_download(
                    discovered, 
                    source=source,
                    quality=quality,
                    workers=workers,
                    output_dir=output_dir,
                )
                result['download_results'] = download_results

                # 生成报告
                report = self._generate_report(task_goal, discovered, download_results)
                result['report'] = report
                print(f"\n{report}")

                success_count = len(download_results.get('success', []))
                failed_count = len(download_results.get('failed', []))
                notfound_count = len(download_results.get('notfound', []))
                skipped_count = len(download_results.get('skipped', []))

                if failed_count == 0 and notfound_count == 0:
                    result['status'] = 'success'
                    result['message'] = f'[OK] 全部完成！成功下载 {success_count} 首歌曲'
                elif success_count > 0:
                    result['status'] = 'partial'
                    result['message'] = (
                        f'[!] 部分完成：成功 {success_count} 首, '
                        f'失败 {failed_count} 首, 未找到 {notfound_count} 首'
                    )
                else:
                    result['status'] = 'error'
                    result['message'] = '[X] 下载全部失败'
            else:
                result['status'] = 'success'
                result['message'] = f'[OK] 发现完成！共 {len(discovered)} 首歌曲（未执行下载）'

            self._add_trace('completed', result['message'])

        except Exception as e:
            result['status'] = 'error'
            result['message'] = f'[X] 执行出错: {e}'
            self._add_trace('error', str(e))
            import traceback
            traceback.print_exc()

        return result

    def _analyze_intent(self, task_goal: str) -> Dict:
        """
        分析用户任务意图
        支持:
          - 直接指定歌手: "周杰伦的歌", "找陈奕迅的歌曲"
          - 按风格: "中国风的歌曲", "民谣推荐"
          - 排行榜: "QQ热歌榜", "飙升榜"
          - 混合: "周杰伦的中国风和洛天依的电音"
          - 模糊: "推荐一些好听的歌"
        """
        text = task_goal.lower()

        intent = {
            'type': 'mixed',
            'artists': [],
            'styles': [],
            'charts': [],
            'keywords': [],
            'raw_text': task_goal,
        }

        # 1. 检测排行榜关键词
        chart_indicators = {
            '热歌榜': 'qq_hot', '新歌榜': 'qq_new', '流行榜': 'qq_pop',
            '内地榜': 'qq_mainland', '欧美榜': 'qq_europe', '韩国榜': 'qq_korea',
            '飙升榜': 'netease_soar', '原创榜': 'netease_orig',
            'qq_hot': 'qq_hot', 'netease_hot': 'netease_hot',
            'netease_soar': 'netease_soar',
        }
        for keyword, chart_key in chart_indicators.items():
            if keyword in text:
                intent['charts'].append(chart_key)
                intent['keywords'].append(keyword)

        # 2. 检测歌手名（从内置库）
        from music_discovery import BUILTIN_ARTISTS
        for artist_name in BUILTIN_ARTISTS:
            if artist_name.lower() in text:
                intent['artists'].append(artist_name)

        # 3. 检测风格
        from music_discovery import MUSIC_STYLES
        for style_name, aliases in MUSIC_STYLES.items():
            for alias in aliases:
                if alias.lower() in text:
                    if style_name not in intent['styles']:
                        intent['styles'].append(style_name)
                    if style_name not in intent['keywords']:
                        intent['keywords'].append(style_name)
                    break

        # 4. 检测特殊指令
        if any(kw in text for kw in ['下载', '下', 'down', 'dl']):
            intent['keywords'].append('download')
        if any(kw in text for kw in ['仅发现', '只找', '搜索', '查找', 'find', 'search']):
            intent['keywords'].append('search_only')
        if any(kw in text for kw in ['mp3', 'flac', 'ape', 'wav', 'aac', '无损']):
            for q in ['mp3', 'flac', 'ape', 'wav', 'aac']:
                if q in text:
                    intent['keywords'].append(f'quality:{q}')

        # 5. 确定任务类型
        if intent['charts']:
            intent['type'] = 'chart'
        elif intent['artists'] and intent['styles']:
            intent['type'] = 'artist_style'
        elif intent['artists']:
            intent['type'] = 'artist'
        elif intent['styles']:
            intent['type'] = 'style'
        else:
            intent['type'] = 'general'

        return intent

    def _discover_songs(self, intent: Dict, max_songs: int) -> List[Dict[str, str]]:
        """
        根据意图发现歌曲
        """
        all_songs = []

        # 直接从排行榜
        if intent['charts']:
            for chart_key in intent['charts'][:2]:
                limit = max_songs // len(intent['charts'])
                songs = self.discovery.discover_from_chart(chart_key, limit=limit)
                all_songs.extend(songs)

        # 按口味混合发现
        if intent['artists'] or intent['styles']:
            # 构建口味描述
            taste_parts = []
            if intent['artists']:
                taste_parts.extend(intent['artists'])
            if intent['styles']:
                taste_parts.append(f"{'、'.join(intent['styles'])}风格")
            taste = "我喜欢" + "和".join(taste_parts) if taste_parts else "推荐好听的歌"

            songs = self.discovery.discover_by_taste(
                taste,
                max_songs=max_songs,
                include_charts=not bool(intent['charts']),
            )
            all_songs.extend(songs)

        # 纯排行榜模式
        if not intent['artists'] and not intent['styles'] and not intent['charts']:
            # 通用模式：从热门榜发现
            songs = self.discovery.discover_by_taste(
                "推荐热门好听的歌曲",
                max_songs=max_songs,
            )
            all_songs.extend(songs)

        # 去重
        seen = set()
        unique = []
        for s in all_songs:
            key = f"{s['title']}|{s.get('artist', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(s)

        return unique[:max_songs]

    def _get_default_chart_songs(self, limit: int = 20) -> List[Dict[str, str]]:
        """获取默认热歌榜歌曲"""
        try:
            return self.discovery.discover_from_chart('qq_hot', limit=limit)
        except Exception:
            try:
                return self.discovery.discover_from_chart('netease_hot', limit=limit)
            except Exception:
                return []

    def _make_plan(self, intent: Dict, songs: List[Dict], config: Dict) -> Dict:
        """制定执行计划"""
        steps = []

        if songs:
            steps.append(f"[List] 发现 {len(songs)} 首歌曲")
            # 按来源/歌手分组概览
            artists = set(s.get('artist', '') for s in songs if s.get('artist'))
            if artists:
                steps.append(f"[歌手] 涉及歌手: {', '.join(list(artists)[:8])}" +
                            (f" 等 {len(artists)} 位" if len(artists) > 8 else ""))

        steps.append(f"[音源] {config.get('source', 'QQMusicClient')}")
        steps.append(f"[音质] {config.get('quality', 'flac')}")
        steps.append(f"[并发] {config.get('workers', 10)}")

        if songs:
            steps.append(f"[下载] 目录: {config.get('output_dir', './downloads')}")
            steps.append(f"[打包] 自动打包为 ZIP")

        return {'steps': steps}

    def _execute_download(self, songs: List[Dict], 
                          source: str = 'QQMusicClient',
                          quality: str = 'flac',
                          workers: int = 10,
                          output_dir: str = './downloads') -> Dict:
        """执行下载"""
        if not songs:
            return {}

        downloader = SmartDownloader(
            source=source,
            quality=quality,
            max_workers=workers,
        )

        results = downloader.download_queue(songs, output_dir=output_dir)
        return results

    def _generate_report(self, task_goal: str, songs: List[Dict],
                         download_results: Dict) -> str:
        """生成 AI 任务报告"""
        success = download_results.get('success', [])
        failed = download_results.get('failed', [])
        notfound = download_results.get('notfound', [])
        skipped = download_results.get('skipped', [])

        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"  [AI] 智能音乐助手 - 任务报告")
        lines.append(f"{'='*60}")
        lines.append(f"")
        lines.append(f"  任务目标: {task_goal}")
        lines.append(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  AI 增强: {'[OK] 是' if self.ai_enabled else '[X] 否(纯规则模式)'}")
        lines.append(f"")
        lines.append(f"  [统计] 概览:")
        lines.append(f"    - 发现歌曲: {len(songs)} 首")
        lines.append(f"    - [OK] 成功下载: {len(success)} 首")
        lines.append(f"    - [X] 下载失败: {len(failed)} 首")
        lines.append(f"    - [?] 未找到: {len(notfound)} 首")
        lines.append(f"    - [-] 去重跳过: {len(skipped)} 首")
        lines.append(f"")

        if success:
            lines.append(f"  [OK] 成功列表 (前10首):")
            for i, s in enumerate(success[:10], 1):
                title = s.get('title', '?')
                artist = s.get('artist', '?')
                src = s.get('source', '')
                lines.append(f"    {i:3d}. {title} - {artist} [{src}]")
            if len(success) > 10:
                lines.append(f"    ... 还有 {len(success) - 10} 首")

        if failed:
            lines.append(f"")
            lines.append(f"  [X] 失败列表:")
            for s in failed:
                title = s.get('title', '?')
                artist = s.get('artist', '?')
                lines.append(f"    - {title} - {artist}")

        if notfound:
            lines.append(f"")
            lines.append(f"  [?] 未找到的歌曲:")
            for s in notfound:
                title = s.get('title', '?')
                artist = s.get('artist', '?')
                lines.append(f"    - {title} - {artist}")

        lines.append(f"")
        lines.append(f"{'='*60}")

        report = '\n'.join(lines)

        # 写入报告文件
        report_path = 'ai-assistant-report.md'
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n报告已保存到: {report_path}")
        except Exception:
            pass

        return report

    def _add_trace(self, event: str, message: str):
        """添加执行轨迹"""
        self.execution_trace.append({
            'event': event,
            'message': message,
            'time': datetime.now().isoformat(),
        })

    def list_tools(self) -> Dict:
        """列出所有可用工具"""
        return AVAILABLE_TOOLS


# ========== CLI 入口 ==========

def main():
    parser = argparse.ArgumentParser(
        description='AI 智能音乐助手 - 自然语言驱动的音乐发现下载工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 基本用法 - 描述你的需求
  python src/ai_assistant.py --task "帮我找周杰伦的中国风歌曲并下载"

  # 指定音源和音质
  python src/ai_assistant.py --task "下载QQ热歌榜前20首" --quality mp3 --workers 5

  # 仅发现不下载
  python src/ai_assistant.py --task "找好听的民谣歌曲" --no-download

  # 使用 AI 增强
  python src/ai_assistant.py --task "推荐一些类似周杰伦风格的歌手" \\
      --deepseek-key sk-xxx --model deepseek-chat

  # 仅搜索不下载
  python src/ai_assistant.py --task "最近有什么好听的英文歌" --no-download
        '''
    )

    parser.add_argument('--task', '-t', type=str, default='',
                        help='描述你的任务目标，如 "帮我找周杰伦的中国风歌曲并下载"')
    parser.add_argument('--task-file', '-f', type=str, default='',
                        help='从文件读取任务描述')

    # API 密钥
    parser.add_argument('--openai-key', type=str, default='',
                        help='OpenAI API 密钥')
    parser.add_argument('--deepseek-key', type=str, default='',
                        help='DeepSeek API 密钥')
    parser.add_argument('--serpapi-key', type=str, default='',
                        help='SerpAPI 密钥（已不推荐，保留向后兼容）')
    parser.add_argument('--browseract-key', type=str, default='',
                        help='BrowserAct API key（免费注册 https://www.browseract.com，'
                             '用于 stealth 浏览器搜索；不设置则自动使用 chrome 模式无需 key）')
    parser.add_argument('--model', type=str, default='deepseek-chat',
                        help='AI 模型名')

    # 下载选项
    parser.add_argument('--source', '-s', type=str, default='QQMusicClient',
                        help='首选音源')
    parser.add_argument('--quality', '-q', type=str, default='flac',
                        help='音质偏好')
    parser.add_argument('--workers', '-w', type=int, default=10,
                        help='并发下载数')
    parser.add_argument('--max-songs', type=int, default=30,
                        help='最大歌曲数')
    parser.add_argument('--output', '-o', type=str, default='./downloads',
                        help='输出目录')
    parser.add_argument('--no-download', action='store_true',
                        help='仅发现歌曲，不执行下载')

    # 工具
    parser.add_argument('--list-tools', action='store_true',
                        help='列出所有可用工具')

    args = parser.parse_args()

    if args.list_tools:
        assistant = AIAssistant()
        tools = assistant.list_tools()
        print("\n[AI] 智能音乐助手 - 可用工具\n")
        for key, info in tools.items():
            print(f"  {key}")
            print(f"    名称: {info['name']}")
            print(f"    描述: {info['description']}")
            if info['params']:
                print(f"    参数: {json.dumps(info['params'], ensure_ascii=False)}")
            print()
        sys.exit(0)

    # 获取任务描述
    task_goal = args.task
    if args.task_file:
        try:
            with open(args.task_file, 'r', encoding='utf-8') as f:
                task_goal = f.read().strip()
        except Exception as e:
            print(f"读取任务文件失败: {e}")
            sys.exit(1)

    if not task_goal:
        parser.print_help()
        print("\n错误: 请使用 --task 或 --task-file 提供任务目标")
        sys.exit(1)

    # 初始化 AI 助手
    assistant = AIAssistant(
        openai_api_key=args.openai_key,
        deepseek_api_key=args.deepseek_key,
        serpapi_key=args.serpapi_key,
        browseract_api_key=args.browseract_key,
        model=args.model,
    )

    # 执行任务
    options = {
        'source': args.source,
        'quality': args.quality,
        'workers': args.workers,
        'max_songs': args.max_songs,
        'output_dir': args.output,
        'no_download': args.no_download,
        'save_queue': True,
    }

    result = assistant.execute_task(task_goal, options)

    # 输出结果摘要
    print(f"\n{'='*60}")
    print(f"  任务状态: {result['status']}")
    print(f"  消息: {result['message']}")
    print(f"{'='*60}")

    # 非零退出码
    if result['status'] == 'error':
        sys.exit(1)
    elif result['status'] == 'partial':
        sys.exit(2)


if __name__ == '__main__':
    main()
