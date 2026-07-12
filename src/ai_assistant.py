#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 智能音乐助手 V3 - 真正的 AI Agent 架构

核心改进:
  1. LLM 函数调用 (Function Calling) — DeepSeek/OpenAI API
  2. 迭代式 Agent 循环 — AI 自主决定搜索、发现、筛选步骤
  3. AI 驱动的歌曲筛选 — 根据用户需求智能选择数量和匹配度
  4. 完整的工具系统 — 每个工具都是真正的可执行函数

工作流程:
  [用户任务] → [LLM 分析 + 调用工具] → [执行工具] → [结果反馈给 LLM] → [LLM 再决策] → ... → [完成]

GitHub Actions 用法:
  手动触发工作流 → 填写任务目标和 API 密钥 → AI 自动完成

API 密钥说明:
  - DEEPSEEK_API_KEY / OPENAI_API_KEY: 用于 AI 函数调用（可选，纯规则模式 Fallback）
  - BROWSERACT_API_KEY: 用于 browser-act stealth 模式搜索（可选）
"""

import os
import sys
import json
import re
import copy
import argparse
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from pathlib import Path

# 导入同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smart_downloader import SmartDownloader, list_top_charts
from search_tools import SearchTools
from music_discovery import MusicDiscovery


# ========================================================================
#  第一部分: LLM 函数调用客户端
# ========================================================================

class LLMFunctionCallClient:
    """LLM 函数调用客户端 — 支持 DeepSeek / OpenAI"""

    # OpenAI 兼容的 API 端点
    API_ENDPOINTS = {
        'deepseek': 'https://api.deepseek.com/v1/chat/completions',
        'openai': 'https://api.openai.com/v1/chat/completions',
    }

    def __init__(self, api_key: str = '', model: str = 'deepseek-chat', provider: str = ''):
        """
        Args:
            api_key: API 密钥
            model: 模型名（deepseek-chat / gpt-4o-mini / gpt-4o 等）
            provider: 服务商（deepseek / openai），为空时自动从模型名推断
        """
        self.api_key = api_key or os.environ.get('DEEPSEEK_API_KEY', '') or os.environ.get('OPENAI_API_KEY', '')
        self.model = model

        # 自动推断服务商
        if not provider:
            if model.startswith('deepseek'):
                provider = 'deepseek'
            elif model.startswith('gpt') or model.startswith('o'):
                provider = 'openai'
            else:
                provider = 'deepseek'  # 默认

        self.provider = provider
        self.api_url = self.API_ENDPOINTS.get(provider, self.API_ENDPOINTS['deepseek'])

        # 构建 Authorization header
        prefix = 'Bearer '
        self.auth_header = prefix + self.api_key

    @property
    def available(self) -> bool:
        """是否可用"""
        return bool(self.api_key)

    def chat_completion(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                        temperature: float = 0.7, max_tokens: int = 4096) -> Dict:
        """
        调用 LLM Chat Completion API（支持函数调用）

        Args:
            messages: 对话历史
            tools: OpenAI 格式的函数定义列表
            temperature: 温度
            max_tokens: 最大生成 token

        Returns:
            { 'role': 'assistant', 'content': str, 'tool_calls': [...] }
        """
        headers = {
            'Authorization': self.auth_header,
            'Content-Type': 'application/json',
        }

        body = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }

        if tools:
            body['tools'] = tools
            # DeepSeek 使用 tools 而非 functions
            body['tool_choice'] = 'auto'

        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            self.api_url, data=data, headers=headers,
            method='POST'
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"LLM API HTTP {e.code}: {error_body}")
        except Exception as e:
            raise RuntimeError(f"LLM API 调用失败: {e}")

        # 解析响应
        choice = result['choices'][0]
        message = choice['message']

        output = {
            'role': 'assistant',
            'content': message.get('content', ''),
            'tool_calls': [],
        }

        # 处理函数调用
        if 'tool_calls' in message:
            for tc in message['tool_calls']:
                # 统一格式
                fn_info = tc['function']
                output['tool_calls'].append({
                    'id': tc['id'],
                    'type': 'function',
                    'function': {
                        'name': fn_info['name'],
                        'arguments': fn_info['arguments'],
                    }
                })
        elif 'function_call' in message:
            fc = message['function_call']
            output['tool_calls'].append({
                'id': 'fc-' + fc['name'],
                'type': 'function',
                'function': {
                    'name': fc['name'],
                    'arguments': fc['arguments'],
                }
            })

        return output

    @staticmethod
    def build_tool_def(tools_dict: Dict) -> List[Dict]:
        """
        将内部工具注册表转换为 OpenAI Function Calling 格式

        Args:
            tools_dict: {
                'tool_name': {
                    'description': str,
                    'params': {'param_name': 'param_description', ...},
                    'required_params': ['param_name', ...],  # 可选
                }
            }

        Returns:
            OpenAI tools 格式 [{ 'type': 'function', 'function': {...} }, ...]
        """
        result = []
        for name, info in tools_dict.items():
            properties = {}
            required = info.get('required_params', [])

            for pname, pdesc in info.get('params', {}).items():
                properties[pname] = {
                    'type': 'string',
                    'description': pdesc,
                }

            # 如果 params 是嵌套 dict（如 download_songs 的 songs 参数是数组）
            detailed_params = info.get('detailed_params', {})
            for pname, pinfo in detailed_params.items():
                properties[pname] = pinfo

            # 如果没指定 required，所有参数都需要
            if not required:
                required = list(properties.keys())

            function_def = {
                'name': name,
                'description': info.get('description', ''),
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                }
            }
            result.append({
                'type': 'function',
                'function': function_def,
            })
        return result


# ========================================================================
#  第二部分: Agent 工具系统
# ========================================================================

class AgentToolExecutor:
    """
    Agent 工具执行器
    将工具名称映射到真实的可执行函数，并执行调用
    """

    def __init__(self, discovery: MusicDiscovery, search: SearchTools,
                 downloader_factory: Callable):
        """
        Args:
            discovery: MusicDiscovery 实例
            search: SearchTools 实例
            downloader_factory: 返回 SmartDownloader 实例的工厂函数
        """
        self.discovery = discovery
        self.search = search
        self.make_downloader = downloader_factory

        # 工具注册表
        self._tools: Dict[str, Dict] = {}
        self._register_all_tools()

    def _register_all_tools(self):
        """注册所有工具"""
        self.register_tool(
            name='search_web',
            description='搜索网络信息，获取音乐资讯、热门歌曲、歌手信息、最新音乐动态等，返回搜索结果列表（标题+摘要+链接）',
            params={
                'query': {
                    'type': 'string',
                    'description': '搜索关键词，支持歌手、歌曲、风格、排行榜等信息',
                },
                'max_results': {
                    'type': 'number',
                    'description': '最大返回结果数（默认 5）',
                },
            },
            required_params=['query'],
        )
        self.register_tool(
            name='fetch_page',
            description='获取指定 URL 的网页文本内容，用于深入了解某首歌、某个歌手的详细信息',
            params={
                'url': {
                    'type': 'string',
                    'description': '网页完整 URL 地址',
                },
            },
            required_params=['url'],
        )
        self.register_tool(
            name='list_charts',
            description='列出所有可用的音乐排行榜（QQ音乐、网易云音乐等）',
            params={},
            required_params=[],
        )
        self.register_tool(
            name='get_chart',
            description='获取指定排行榜的歌曲列表',
            params={
                'chart_key': {
                    'type': 'string',
                    'description': '排行榜键名，如 qq_hot / netease_hot / netease_soar / 热歌榜 / 飙升榜',
                },
                'limit': {
                    'type': 'number',
                    'description': '获取前 N 首（默认 20）',
                },
            },
            required_params=['chart_key'],
        )
        self.register_tool(
            name='discover_by_artist',
            description='发现指定歌手的歌曲，从内置库和排行榜中匹配',
            params={
                'artist': {
                    'type': 'string',
                    'description': '歌手名称，如 周杰伦、洛天依、Taylor Swift',
                },
                'max_songs': {
                    'type': 'number',
                    'description': '最大歌曲数（默认 20）',
                },
            },
            required_params=['artist'],
        )
        self.register_tool(
            name='discover_by_style',
            description='按音乐风格发现歌曲，如 中国风、民谣、电子、VOCALOID、古风、摇滚 等',
            params={
                'style': {
                    'type': 'string',
                    'description': '风格名称，如 中国风、古风、民谣、电子、VOCALOID、摇滚、R&B',
                },
                'max_songs': {
                    'type': 'number',
                    'description': '最大歌曲数（默认 20）',
                },
            },
            required_params=['style'],
        )
        self.register_tool(
            name='ai_filter_songs',
            description='使用 AI 智能筛选歌曲列表，根据用户需求保留最匹配的歌曲，可调整数量。适合在收集大量歌曲后进行精选',
            params={
                'task_goal': {
                    'type': 'string',
                    'description': '用户原始任务目标，用于理解筛选标准',
                },
                'songs_json': {
                    'type': 'string',
                    'description': '待筛选的歌曲列表 JSON 字符串，格式 [{"title":"歌名","artist":"歌手"},...]',
                },
                'max_songs': {
                    'type': 'number',
                    'description': '保留的最大歌曲数（默认 0=全部）',
                },
                'filter_rules': {
                    'type': 'string',
                    'description': '筛选规则说明（可选），如 "只保留周杰伦的歌曲"、"去掉重复的"',
                },
            },
            required_params=['task_goal', 'songs_json'],
        )
        self.register_tool(
            name='save_songs',
            description='将当前收集的歌曲列表保存到队列文件，并打印歌曲清单供确认',
            params={
                'songs_json': {
                    'type': 'string',
                    'description': '要保存的歌曲列表 JSON 字符串，格式 [{"title":"歌名","artist":"歌手"},...]',
                },
                'filepath': {
                    'type': 'string',
                    'description': '保存路径（默认 song-queue.txt）',
                },
            },
            required_params=['songs_json'],
        )
        self.register_tool(
            name='download_songs',
            description='执行最终下载：将歌曲列表提交给下载引擎，支持并发下载、多种音质',
            params={
                'songs_json': {
                    'type': 'string',
                    'description': '要下载的歌曲列表 JSON 字符串，格式 [{"title":"歌名","artist":"歌手"},...]',
                },
                'source': {
                    'type': 'string',
                    'description': '首选音源（默认 QQMusicClient），可选: QQMusicClient, NeteaseMusicClient, KuwoMusicClient, KugouMusicClient, MiguMusicClient',
                },
                'quality': {
                    'type': 'string',
                    'description': '音质（默认 flac），可选: flac, mp3, ape, wav, aac, auto',
                },
                'workers': {
                    'type': 'number',
                    'description': '并发下载数（默认 5）',
                },
            },
            required_params=['songs_json'],
        )

    def register_tool(self, name: str, description: str,
                      params: Dict, required_params: List[str]):
        """注册一个工具"""
        self._tools[name] = {
            'description': description,
            'params': params,
            'required_params': required_params,
        }

    def get_all_tools(self) -> Dict:
        """获取所有工具注册信息"""
        return dict(self._tools)

    def get_openai_tools(self) -> List[Dict]:
        """获取 OpenAI 格式的工具定义"""
        return LLMFunctionCallClient.build_tool_def(self._tools)

    def execute(self, tool_name: str, arguments: Dict) -> str:
        """
        执行指定的工具

        Args:
            tool_name: 工具名称
            arguments: 参数字典

        Returns:
            工具执行结果的文本描述
        """
        handler = self._get_handler(tool_name)
        if not handler:
            return f"错误: 未知工具 '{tool_name}'"

        try:
            result = handler(**arguments)
            return result
        except Exception as e:
            import traceback
            return f"工具 '{tool_name}' 执行失败: {e}\n{traceback.format_exc()}"

    def _get_handler(self, name: str) -> Optional[Callable]:
        """获取工具的处理函数"""
        handlers = {
            'search_web': self._handle_search_web,
            'fetch_page': self._handle_fetch_page,
            'list_charts': self._handle_list_charts,
            'get_chart': self._handle_get_chart,
            'discover_by_artist': self._handle_discover_artist,
            'discover_by_style': self._handle_discover_style,
            'ai_filter_songs': self._handle_ai_filter,
            'save_songs': self._handle_save_songs,
            'download_songs': self._handle_download,
        }
        return handlers.get(name)

    # ---- 工具处理函数 ----

    def _handle_search_web(self, query: str, max_results: int = 5) -> str:
        """搜索网络"""
        print(f"\n  🔍 [工具] search_web(query='{query}', max={max_results})")
        results = self.search.search_web(query, max_results=max_results)
        if not results:
            return "搜索未返回任何结果"

        lines = [f"搜索 '{query}' 返回 {len(results)} 条结果:"]
        for i, r in enumerate(results, 1):
            lines.append(f"  {i}. {r.get('title', '?')}")
            lines.append(f"     URL: {r.get('url', '?')}")
            snippet = r.get('snippet', '')
            if snippet:
                lines.append(f"     摘要: {snippet[:200]}")
        return '\n'.join(lines)

    def _handle_fetch_page(self, url: str) -> str:
        """获取网页内容"""
        print(f"\n  📄 [工具] fetch_page(url='{url[:60]}...')")
        content = self.search.fetch_page(url, max_chars=3000)
        if not content or content.startswith('[browser-act'):
            return f"无法获取页面内容: {content}"
        # 截取前 2000 字符
        return f"页面内容 (前2000字符):\n{content[:2000]}"

    def _handle_list_charts(self) -> str:
        """列出排行榜"""
        print(f"\n  📊 [工具] list_charts()")
        from smart_downloader import TOP_CHARTS
        lines = ["可用的音乐排行榜:"]
        for key, info in TOP_CHARTS.items():
            lines.append(f"  - {key:20s} {info.get('name', '')}")
        return '\n'.join(lines)

    def _handle_get_chart(self, chart_key: str, limit: int = 20) -> str:
        """获取排行榜"""
        print(f"\n  📊 [工具] get_chart(chart_key='{chart_key}', limit={limit})")
        songs = self.discovery.discover_from_chart(chart_key, limit=limit)
        if not songs:
            return f"排行榜 '{chart_key}' 未获取到歌曲"

        lines = [f"排行榜 '{chart_key}' ({len(songs)} 首):"]
        for i, s in enumerate(songs, 1):
            artist = s.get('artist', '')
            lines.append(f"  {i:3d}. {s['title']} - {artist}")
        return '\n'.join(lines)

    def _handle_discover_artist(self, artist: str, max_songs: int = 20) -> str:
        """按歌手发现"""
        print(f"\n  🎤 [工具] discover_by_artist(artist='{artist}', max={max_songs})")
        songs = self.discovery.discover_by_artist(artist, max_songs=max_songs)
        if not songs:
            return f"未找到歌手 '{artist}' 的歌曲"

        lines = [f"歌手 '{artist}' ({len(songs)} 首):"]
        for i, s in enumerate(songs, 1):
            lines.append(f"  {i:3d}. {s['title']} - {s.get('artist', artist)}")
        return '\n'.join(lines)

    def _handle_discover_style(self, style: str, max_songs: int = 20) -> str:
        """按风格发现"""
        print(f"\n  🎵 [工具] discover_by_style(style='{style}', max={max_songs})")
        songs = self.discovery.discover_by_style(style, max_songs=max_songs)
        if not songs:
            return f"未找到风格 '{style}' 的歌曲"

        lines = [f"风格 '{style}' ({len(songs)} 首):"]
        for i, s in enumerate(songs, 1):
            lines.append(f"  {i:3d}. {s['title']} - {s.get('artist', '?')}")
        return '\n'.join(lines)

    def _handle_ai_filter(self, task_goal: str, songs_json: str,
                          max_songs: int = 0, filter_rules: str = '') -> str:
        """
        AI 筛选歌曲 — 使用 LLM 智能筛选
        这是一个特殊的工具，它调用 LLM 来理解用户需求并进行语义筛选
        """
        print(f"\n  🧠 [工具] ai_filter_songs(max_songs={max_songs or '全部'})")
        try:
            songs = json.loads(songs_json)
        except json.JSONDecodeError as e:
            return f"JSON 解析失败: {e}"

        if not songs:
            return "歌曲列表为空，无需筛选"

        # 如果有 LLM 客户端，用 LLM 筛选
        llm = self._get_llm_for_filter()
        if llm and llm.available:
            return self._llm_filter_songs(llm, task_goal, songs, max_songs, filter_rules)
        else:
            return self._rule_filter_songs(task_goal, songs, max_songs, filter_rules)

    def _get_llm_for_filter(self):
        """获取一个仅用于筛选的 LLM 客户端实例"""
        return _get_global_llm()

    def _llm_filter_songs(self, llm, task_goal: str, songs: List[Dict],
                          max_songs: int, filter_rules: str) -> str:
        """使用 LLM 进行语义筛选"""
        songs_text = json.dumps(songs, ensure_ascii=False, indent=2)
        max_text = f"，最多保留 {max_songs} 首" if max_songs > 0 else "，保留全部符合的"

        rules_text = f"\n筛选规则: {filter_rules}" if filter_rules else ""

        system_msg = """你是音乐筛选专家。你的任务是根据用户需求，从歌曲列表中筛选出最匹配的歌曲。

筛选原则:
1. 仔细理解用户的需求（任务目标）
2. 逐首歌判断是否符合需求（歌手匹配、风格匹配、语义相关）
3. 按匹配度从高到低排序
4. 只输出 JSON 数组，不要其他文字
5. 返回完整歌曲信息，不要改变原始数据的格式"""

        prompt = f"""## 用户任务目标
{task_goal}

## 待筛选歌曲列表
{songs_text}

## 要求
请根据用户的任务目标，筛选出最匹配的歌曲。
{max_text}{rules_text}

请直接输出筛选后的 JSON 数组，格式: [{{"title": "歌名", "artist": "歌手"}}, ...]
只输出 JSON，不要加任何其他文字。"""

        try:
            result = llm.chat_completion(
                messages=[
                    {'role': 'system', 'content': system_msg},
                    {'role': 'user', 'content': prompt},
                ],
                tools=None,
                temperature=0.3,
                max_tokens=4096,
            )

            content = result.get('content', '')
            # 尝试提取 JSON
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                filtered = json.loads(json_match.group())
            else:
                filtered = json.loads(content)

            if max_songs > 0 and len(filtered) > max_songs:
                filtered = filtered[:max_songs]

            lines = [f"🧠 AI 筛选完成: {len(songs)} 首 → {len(filtered)} 首"]
            for i, s in enumerate(filtered, 1):
                lines.append(f"  {i:3d}. {s['title']} - {s.get('artist', '?')}")
            lines.append(f"\n筛选后的 JSON:\n{json.dumps(filtered, ensure_ascii=False)}")
            return '\n'.join(lines)

        except Exception as e:
            # Fallback 到规则筛选
            return f"LLM 筛选失败 ({e})，使用规则筛选:\n{self._rule_filter_songs(task_goal, songs, max_songs, filter_rules)}"

    def _rule_filter_songs(self, task_goal: str, songs: List[Dict],
                           max_songs: int, filter_rules: str) -> str:
        """规则兜底的歌曲筛选"""
        text = task_goal.lower()
        scored = []

        for s in songs:
            score = 0
            title = s.get('title', '').lower()
            artist = s.get('artist', '').lower()

            # 歌手匹配
            if artist and artist in text:
                score += 3
            # 歌名关键词匹配
            for word in re.split(r'[\s,，、]+', text):
                if word and len(word) > 1 and word in title:
                    score += 2

            scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        # 过滤掉完全不匹配的（除非有特定规则）
        if filter_rules:
            filtered = [s for _, s in scored]
        else:
            filtered = [s for score, s in scored if score > 0]
            if not filtered:
                filtered = [s for _, s in scored[:20]]  # 无匹配时保留前20

        if max_songs > 0 and len(filtered) > max_songs:
            filtered = filtered[:max_songs]

        lines = [f"📋 规则筛选完成: {len(songs)} 首 → {len(filtered)} 首"]
        for i, s in enumerate(filtered, 1):
            lines.append(f"  {i:3d}. {s['title']} - {s.get('artist', '?')}")
        lines.append(f"\n筛选后的 JSON:\n{json.dumps(filtered, ensure_ascii=False)}")
        return '\n'.join(lines)

    def _handle_save_songs(self, songs_json: str, filepath: str = 'song-queue.txt') -> str:
        """保存歌曲列表到文件"""
        print(f"\n  💾 [工具] save_songs(count=?, file='{filepath}')")
        try:
            songs = json.loads(songs_json)
        except json.JSONDecodeError as e:
            return f"JSON 解析失败: {e}"

        if not songs:
            return "歌曲列表为空，跳过保存"

        # 去重
        seen = set()
        unique = []
        for s in songs:
            key = f"{s['title']}|{s.get('artist', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(s)

        # 写入文件
        lines = [
            f"# AI 智能发现歌曲列表 - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"# 共 {len(unique)} 首歌曲",
            "",
        ]
        for s in unique:
            artist = s.get('artist', '')
            if artist:
                lines.append(f"{s['title']}, {artist}")
            else:
                lines.append(s['title'])

        Path(filepath).write_text('\n'.join(lines) + '\n', encoding='utf-8')

        result_lines = [f"✅ 已保存 {len(unique)} 首歌曲到 {filepath}"]
        for i, s in enumerate(unique, 1):
            result_lines.append(f"  {i:3d}. {s['title']} - {s.get('artist', '?')}")
        return '\n'.join(result_lines)

    def _handle_download(self, songs_json: str, source: str = 'QQMusicClient',
                         quality: str = 'flac', workers: int = 5) -> str:
        """执行下载"""
        print(f"\n  ⬇️ [工具] download_songs(count=?, source={source}, quality={quality})")
        try:
            songs = json.loads(songs_json)
        except json.JSONDecodeError as e:
            return f"JSON 解析失败: {e}"

        if not songs:
            return "歌曲列表为空，跳过下载"

        output_dir = f"./downloads/{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        downloader = self.make_downloader(source=source, quality=quality, workers=workers)

        try:
            results = downloader.download_queue(songs, output_dir=output_dir)
        except Exception as e:
            return f"下载执行失败: {e}"

        success = results.get('success', [])
        failed = results.get('failed', [])
        notfound = results.get('notfound', [])
        skipped = results.get('skipped', [])

        lines = [f"下载完成 — 目录: {output_dir}"]
        lines.append(f"  ✅ 成功: {len(success)} 首")
        if failed:
            lines.append(f"  ❌ 失败: {len(failed)} 首")
        if notfound:
            lines.append(f"  ❓ 未找到: {len(notfound)} 首")
        if skipped:
            lines.append(f"  ⏭️ 跳过: {len(skipped)} 首")

        if success:
            lines.append("\n成功下载的歌曲:")
            for i, s in enumerate(success[:10], 1):
                lines.append(f"  {i:3d}. {s.get('title', '?')} - {s.get('artist', '?')}")
            if len(success) > 10:
                lines.append(f"  ... 还有 {len(success) - 10} 首")

        return '\n'.join(lines)


# ========================================================================
#  第三部分: AI Agent 主循环
# ========================================================================

# 全局 LLM 实例（供筛选工具内部调用）
_GLOBAL_LLM: Optional[LLMFunctionCallClient] = None

def _get_global_llm() -> Optional[LLMFunctionCallClient]:
    return _GLOBAL_LLM


# Agent 系统提示词
SYSTEM_PROMPT = """你是 AI 智能音乐助手，一个专业的音乐发现和下载 Agent。

## 你的能力
你可以使用多种工具来搜索、发现、筛选和下载音乐。你的工作方式是：
1. 理解用户的任务目标
2. 自主决定需要调用哪些工具，按什么顺序调用
3. 每次调用工具后，分析结果并决定下一步
4. 直到任务完成，输出最终总结

## 通用工作流程建议（灵活执行，不必全部执行）
1. 首先尝试理解用户具体想要什么音乐
2. 使用 search_web 搜索最新的音乐信息、排行榜数据
3. 使用 list_charts / get_chart 获取热门榜单
4. 使用 discover_by_artist / discover_by_style 发现歌曲
5. 使用 ai_filter_songs 进行智能筛选
6. 使用 save_songs 保存确认
7. 使用 download_songs 下载

## 重要规则
- 每次只调用一个工具，等待结果后再决定下一步
- 收集足够多的候选歌曲（通常 20-50 首），然后用 ai_filter_songs 精选
- ai_filter_songs 可以多次调用，不同标准筛选
- 任务完成后，在 content 中输出最终总结
- 如果工具调用失败，尝试其他工具或方法
- 不要在 content 中输出长列表，用工具来管理数据
- 最终上传前必须用 save_songs 保存队列

## 歌曲列表传递格式
在工具间传递歌曲列表时，使用 JSON 字符串格式：
[{"title": "七里香", "artist": "周杰伦"}, {"title": "晴天", "artist": "周杰伦"}]

## 关于歌曲数量
根据用户需求灵活决定:
- "找一些" → 10-15 首
- "查周杰伦的歌曲" → 15-20 首
- "下载排行榜前30" → 按用户要求
- 用户没有明确说数量时，默认 20-30 首比较合适"""


class AIAgent:
    """
    AI Agent - 迭代式工具调用主循环

    工作流程:
    1. 初始化 → 发送系统提示 + 用户任务 → LLM 决定调用哪个工具
    2. 执行工具 → 结果返回给 LLM → LLM 再决策
    3. 循环直到 LLM 认为任务完成（不再调用工具）
    4. 输出最终总结
    """

    MAX_ITERATIONS = 25  # 最大工具调用轮次

    def __init__(self, task_goal: str, llm: LLMFunctionCallClient,
                 executor: AgentToolExecutor, options: Dict):
        """
        Args:
            task_goal: 用户任务目标
            llm: LLM 客户端
            executor: 工具执行器
            options: 配置选项
        """
        self.task_goal = task_goal
        self.llm = llm
        self.executor = executor
        self.options = options

        # 对话历史
        self.messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': self._build_user_prompt()},
        ]

        # 执行记录
        self.trace = []

    def _build_user_prompt(self) -> str:
        """构建用户提示词"""
        source = self.options.get('source', 'QQMusicClient')
        quality = self.options.get('quality', 'flac')
        workers = self.options.get('workers', 10)
        no_download = self.options.get('no_download', False)

        parts = [f"## 任务目标\n{self.task_goal}\n"]
        parts.append(f"## 配置")
        parts.append(f"- 首选音源: {source}")
        parts.append(f"- 音质: {quality}")
        parts.append(f"- 并发下载数: {workers}")

        if no_download:
            parts.append(f"- ⚠️ 仅发现模式：不要调用 download_songs，发现并保存歌曲即可")

        parts.append(f"\n请根据任务目标自主决定如何操作。每次只调用一个工具。")

        return '\n'.join(parts)

    def run(self) -> Dict:
        """
        运行 Agent 主循环

        Returns:
            {
                'status': 'success' | 'error',
                'message': str,
                'task_goal': str,
                'discovered_songs': List,
                'final_songs': List,
                'trace': List,
                'report': str,
            }
        """
        print(f"\n{'='*60}")
        print(f"  🤖 AI 智能音乐助手 V3 — Agent 模式")
        print(f"  {'='*50}")
        print(f"  任务: {self.task_goal}")
        print(f"  模型: {self.llm.model}")
        print(f"  最大迭代: {self.MAX_ITERATIONS} 步")
        print(f"{'='*60}\n")

        start_time = datetime.now()
        iteration = 0
        tool_calls_made = 0
        final_content = ""

        # 工具定义
        tools_def = self.executor.get_openai_tools()
        # 将 tools 定义注入系统提示
        # (已经在 SYSTEM_PROMPT 中描述了工具，这里补充)

        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            print(f"\n--- 迭代 {iteration}/{self.MAX_ITERATIONS} ---")

            try:
                response = self.llm.chat_completion(
                    messages=self.messages,
                    tools=tools_def,
                    temperature=0.7,
                    max_tokens=4096,
                )
            except Exception as e:
                error_msg = f"LLM 调用失败: {e}"
                print(f"  ❌ {error_msg}")
                self.trace.append({'step': iteration, 'action': 'llm_error', 'result': error_msg})
                # 降级：执行默认流程
                return self._fallback_flow()

            content = response.get('content', '')
            tool_calls = response.get('tool_calls', [])

            if content:
                print(f"  💬 {content[:300]}")

            if not tool_calls:
                # AI 决定任务完成
                final_content = content
                print(f"\n  ✅ AI 认为任务已完成")
                break

            # 执行每个工具调用
            for tc in tool_calls:
                tool_calls_made += 1
                fn_info = tc['function']
                name = fn_info['name']
                raw_args = fn_info['arguments']

                # 解析参数
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {'raw': raw_args}

                print(f"\n  🛠️  [{tool_calls_made}] {name}({json.dumps(args, ensure_ascii=False)[:100]})")

                # 执行工具
                result_text = self.executor.execute(name, args)

                print(f"  📋 结果: {result_text[:200]}...")

                # 记录 trace
                self.trace.append({
                    'step': iteration,
                    'tool': name,
                    'arguments': args,
                    'result_preview': result_text[:200],
                })

                # 将工具调用和结果加入对话
                self.messages.append({
                    'role': 'assistant',
                    'content': content if content else None,
                    'tool_calls': [{
                        'id': tc['id'],
                        'type': 'function',
                        'function': {
                            'name': name,
                            'arguments': raw_args,
                        }
                    }]
                })

                self.messages.append({
                    'role': 'tool',
                    'tool_call_id': tc['id'],
                    'content': result_text,
                })

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n{'='*60}")
        print(f"  Agent 执行完成")
        print(f"  迭代: {iteration} 轮 | 工具调用: {tool_calls_made} 次 | 耗时: {elapsed:.1f}s")
        print(f"{'='*60}")

        # 生成报告
        report = self._generate_report(final_content, tool_calls_made, iteration)

        result = {
            'status': 'success',
            'task_goal': self.task_goal,
            'message': final_content or '任务完成',
            'trace': self.trace,
            'report': report,
            'iterations': iteration,
            'tool_calls': tool_calls_made,
        }

        return result

    def _fallback_flow(self) -> Dict:
        """
        降级流程 — 当 LLM 不可用时，使用规则引擎执行默认流程
        """
        print(f"\n  ⚠️  LLM 不可用，使用规则降级模式")
        return FallbackFlow(self.task_goal, self.executor, self.options).run()

    def _generate_report(self, final_content: str, tool_calls: int, iterations: int) -> str:
        """生成任务报告"""
        lines = [
            f"\n{'='*60}",
            f"  🤖 AI 智能音乐助手 — 任务报告",
            f"{'='*60}",
            f"",
            f"  任务目标: {self.task_goal}",
            f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  AI 模型: {self.llm.model}",
            f"",
            f"  [统计]",
            f"    - 迭代轮次: {iterations}",
            f"    - 工具调用: {tool_calls} 次",
            f"    - 执行步骤:",
        ]

        for t in self.trace:
            tool = t.get('tool', '?')
            args = t.get('arguments', {})
            result = t.get('result_preview', '')[:80]
            lines.append(f"      · {tool}(...) → {result}")

        if final_content:
            lines.append(f"")
            lines.append(f"  [AI 总结]")
            lines.append(f"    {final_content[:500]}")

        lines.append(f"")
        lines.append(f"{'='*60}")

        report = '\n'.join(lines)

        try:
            Path('ai-assistant-report.md').write_text(report, encoding='utf-8')
        except Exception:
            pass

        return report


class FallbackFlow:
    """
    降级流程 — 当 LLM 不可用时使用规则引擎执行
    """

    def __init__(self, task_goal: str, executor: AgentToolExecutor, options: Dict):
        self.task_goal = task_goal
        self.executor = executor
        self.options = options

    def run(self) -> Dict:
        """执行降级流程"""
        print(f"\n[Fallback] 使用规则引擎自动发现")

        discover = self.executor.discovery
        search = self.executor.search
        no_download = self.options.get('no_download', False)

        # 1. 分析意图
        taste = self.task_goal.replace('下载', '').replace('帮我', '').replace('找', '').replace('的', '').strip()
        prefs = discover.analyzer.analyze(taste)

        print(f"  分析: 歌手={prefs['artists']}, 风格={prefs['styles']}")

        # 2. 发现歌曲
        all_songs = []
        if prefs['artists'] or prefs['styles']:
            songs = discover.discover_by_taste(taste, max_songs=30)
            all_songs.extend(songs)
        else:
            songs = discover.discover_from_chart('qq_hot', limit=20)
            all_songs.extend(songs)

        # 3. 去重
        seen = set()
        unique = []
        for s in all_songs:
            key = f"{s['title']}|{s.get('artist', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(s)

        final_songs = unique[:30]
        print(f"  发现 {len(final_songs)} 首歌曲")

        # 4. 保存
        songs_json = json.dumps(final_songs, ensure_ascii=False)
        save_result = self.executor.execute('save_songs', {
            'songs_json': songs_json,
            'filepath': 'song-queue.txt',
        })
        print(f"  {save_result}")

        # 5. 下载
        if not no_download and final_songs:
            dl_result = self.executor.execute('download_songs', {
                'songs_json': songs_json,
                'source': self.options.get('source', 'QQMusicClient'),
                'quality': self.options.get('quality', 'flac'),
                'workers': self.options.get('workers', 5),
            })
            print(f"  {dl_result}")

        report = f"Fallback 模式完成，发现 {len(final_songs)} 首歌曲"
        return {
            'status': 'success',
            'task_goal': self.task_goal,
            'message': report,
            'trace': [{'step': 1, 'action': 'fallback', 'result': report}],
            'report': report,
            'iterations': 1,
            'tool_calls': 0,
        }


# ========================================================================
#  第四部分: CLI 入口
# ========================================================================

def main():
    parser = argparse.ArgumentParser(
        description='AI 智能音乐助手 V3 - AI Agent 驱动的音乐发现下载工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # Agent 模式（需要 API 密钥）
  python src/ai_assistant.py --task "帮我找周杰伦的中国风歌曲和洛天依的歌曲并下载" \\
      --deepseek-key sk-xxx

  # 纯规则模式（无需 API 密钥，自动降级）
  python src/ai_assistant.py --task "帮我找周杰伦的中国风歌曲和洛天依的歌曲并下载"

  # 仅发现不下载
  python src/ai_assistant.py --task "找好听的民谣歌曲" --no-download

  # 自定义音源音质
  python src/ai_assistant.py --task "下载QQ热歌榜前20首" --quality mp3 --workers 5
        '''
    )

    parser.add_argument('--task', '-t', type=str, default='',
                        help='描述你的任务目标，如 "帮我找周杰伦的中国风歌曲并下载"')
    parser.add_argument('--task-file', '-f', type=str, default='',
                        help='从文件读取任务描述')

    # API 密钥
    parser.add_argument('--deepseek-key', type=str, default='',
                        help='DeepSeek API 密钥（推荐，便宜且中文好）')
    parser.add_argument('--openai-key', type=str, default='',
                        help='OpenAI API 密钥')
    parser.add_argument('--browseract-key', type=str, default='',
                        help='BrowserAct API key（可选）')
    parser.add_argument('--model', type=str, default='deepseek-chat',
                        help='AI 模型名（默认 deepseek-chat，可选 gpt-4o-mini 等）')

    # 下载选项
    parser.add_argument('--source', '-s', type=str, default='QQMusicClient',
                        help='首选音源')
    parser.add_argument('--quality', '-q', type=str, default='flac',
                        help='音质偏好')
    parser.add_argument('--workers', '-w', type=int, default=10,
                        help='并发下载数')
    parser.add_argument('--output', '-o', type=str, default='./downloads',
                        help='输出目录')
    parser.add_argument('--no-download', action='store_true',
                        help='仅发现歌曲，不执行下载')
    parser.add_argument('--max-iterations', type=int, default=25,
                        help='Agent 最大迭代轮次')

    args = parser.parse_args()

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

    # 初始化 LLM
    api_key = args.deepseek_key or os.environ.get('DEEPSEEK_API_KEY', '') \
              or args.openai_key or os.environ.get('OPENAI_API_KEY', '')
    provider = 'deepseek' if (args.deepseek_key or 'DEEPSEEK_API_KEY' in os.environ) else 'openai'

    llm = LLMFunctionCallClient(
        api_key=api_key,
        model=args.model,
        provider=provider,
    )

    if llm.available:
        print(f"[AI Agent] LLM 已就绪 (model={args.model}, provider={provider})")
    else:
        print("[AI Agent] 未设置 API 密钥，将使用规则降级模式")
        print(f"[AI Agent] 设置方法: --deepseek-key sk-xxx 或环境变量 DEEPSEEK_API_KEY")

    # 设置全局 LLM（供筛选工具内部调用）
    global _GLOBAL_LLM
    _GLOBAL_LLM = llm

    # 初始化子模块
    search = SearchTools(
        browseract_api_key=args.browseract_key or os.environ.get('BROWSERACT_API_KEY', ''),
    )
    discovery = MusicDiscovery(search_tools=search)

    def make_downloader(source=args.source, quality=args.quality, workers=args.workers):
        return SmartDownloader(
            source=source,
            quality=quality,
            max_workers=workers,
        )

    # 初始化工具执行器
    executor = AgentToolExecutor(
        discovery=discovery,
        search=search,
        downloader_factory=make_downloader,
    )

    # 创建 Agent 并运行
    options = {
        'source': args.source,
        'quality': args.quality,
        'workers': args.workers,
        'output_dir': args.output,
        'no_download': args.no_download,
    }

    if llm.available:
        AIAgent.MAX_ITERATIONS = args.max_iterations
        agent = AIAgent(
            task_goal=task_goal,
            llm=llm,
            executor=executor,
            options=options,
        )
        result = agent.run()
    else:
        # 降级模式
        fallback = FallbackFlow(task_goal, executor, options)
        result = fallback.run()

    # 输出结果
    print(f"\n{'='*60}")
    print(f"  状态: {'✅ 成功' if result['status'] == 'success' else '❌ 失败'}")
    print(f"  消息: {result['message'][:200]}")
    print(f"{'='*60}")

    if result['status'] == 'error':
        sys.exit(1)


if __name__ == '__main__':
    main()
