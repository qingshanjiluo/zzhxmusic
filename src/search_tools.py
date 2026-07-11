#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索工具模块 - 提供网络搜索、音乐资讯获取能力
支持 DuckDuckGo（免API密钥）、可选的 SerpAPI / Google Custom Search

用法:
    from search_tools import SearchTools
    tools = SearchTools()
    results = tools.search_web("2026年热门中文歌曲")
    results = tools.search_music_news("周杰伦 新专辑")
"""

import os
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import html.parser
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import ssl


class HTMLTextExtractor(html.parser.HTMLParser):
    """简单的 HTML 文本提取器"""
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip_tags = {'script', 'style', 'noscript'}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth = getattr(self, '_skip_depth', 0) + 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip_depth = getattr(self, '_skip_depth', 1) - 1
            if self._skip_depth < 0:
                self._skip_depth = 0

    def handle_data(self, data):
        if getattr(self, '_skip_depth', 0) == 0:
            stripped = data.strip()
            if stripped:
                self.text.append(stripped)

    def get_text(self) -> str:
        return ' '.join(self.text)


class SearchTools:
    """搜索工具集 - 网络搜索、音乐资讯获取"""

    # DuckDuckGo HTML 搜索 URL
    DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
    # DuckDuckGo 即时答案 API
    DUCKDUCKGO_INSTANT = "https://api.duckduckgo.com/"

    def __init__(self, 
                 serpapi_key: str = '',
                 google_api_key: str = '',
                 google_cse_id: str = '',
                 bing_api_key: str = '',
                 user_agent: str = ''):
        """
        初始化搜索工具

        Args:
            serpapi_key: SerpAPI 密钥（可选）
            google_api_key: Google Custom Search API 密钥（可选）
            google_cse_id: Google Custom Search Engine ID（可选）
            bing_api_key: Bing Search API 密钥（可选）
            user_agent: 自定义 User-Agent
        """
        self.serpapi_key = serpapi_key or os.environ.get('SERPAPI_KEY', '')
        self.google_api_key = google_api_key or os.environ.get('GOOGLE_API_KEY', '')
        self.google_cse_id = google_cse_id or os.environ.get('GOOGLE_CSE_ID', '')
        self.bing_api_key = bing_api_key or os.environ.get('BING_API_KEY', '')
        self.user_agent = user_agent or (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        )
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    def search_web(self, query: str, max_results: int = 8, 
                   source: str = 'auto') -> List[Dict[str, str]]:
        """
        网络搜索主入口 - 根据可用 API 自动选择后端

        Args:
            query: 搜索关键词
            max_results: 最大返回结果数
            source: 搜索源 (auto/duckduckgo/serpapi/google/bing)

        Returns:
            [{'title': str, 'url': str, 'snippet': str}, ...]
        """
        if source == 'auto':
            if self.serpapi_key:
                source = 'serpapi'
            elif self.google_api_key and self.google_cse_id:
                source = 'google'
            elif self.bing_api_key:
                source = 'bing'
            else:
                source = 'duckduckgo'

        sources = {
            'duckduckgo': self._search_duckduckgo,
            'serpapi': self._search_serpapi,
            'google': self._search_google,
            'bing': self._search_bing,
        }

        searcher = sources.get(source, self._search_duckduckgo)
        try:
            results = searcher(query, max_results)
            if results:
                print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via {source})")
                return results
        except Exception as e:
            print(f"  [搜索] {source} 失败: {e}")

        # fallback: 尝试 DuckDuckGo
        if source != 'duckduckgo':
            try:
                results = self._search_duckduckgo(query, max_results)
                if results:
                    print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via duckduckgo fallback)")
                    return results
            except Exception as e:
                print(f"  [搜索] duckduckgo fallback 也失败: {e}")

        return []

    def _search_duckduckgo(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """使用 DuckDuckGo HTML 搜索（无需 API 密钥）"""
        data = urllib.parse.urlencode({'q': query}).encode('utf-8')
        req = urllib.request.Request(
            self.DUCKDUCKGO_URL,
            data=data,
            headers={
                'User-Agent': self.user_agent,
                'Content-Type': 'application/x-www-form-urlencoded',
            }
        )
        with urllib.request.urlopen(req, context=self._ssl_context, timeout=15) as resp:
            html_content = resp.read().decode('utf-8', errors='replace')

        results = []
        # 解析 DuckDuckGo HTML 结果
        # 查找结果块: <a rel="nofollow" class="result__a" href="...">
        # 标题在 <a> 内，摘要在 <a class="result__snippet">

        # 用正则提取结果
        result_pattern = re.compile(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        for match in result_pattern.finditer(html_content)[:max_results]:
            url = self._decode_html_entities(match.group(1).strip())
            title = self._strip_tags(match.group(2)).strip()
            snippet = self._strip_tags(match.group(3)).strip()
            if title and url:
                results.append({
                    'title': title,
                    'url': url,
                    'snippet': snippet,
                })

        return results

    def _search_serpapi(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """使用 SerpAPI 搜索（需要 API 密钥）"""
        if not self.serpapi_key:
            raise ValueError("SERPAPI_KEY 未设置")

        params = urllib.parse.urlencode({
            'q': query,
            'api_key': self.serpapi_key,
            'num': min(max_results, 20),
            'engine': 'google',
        })
        url = f"https://serpapi.com/search?{params}"

        req = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        with urllib.request.urlopen(req, context=self._ssl_context, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        results = []
        for item in data.get('organic_results', [])[:max_results]:
            results.append({
                'title': item.get('title', ''),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', ''),
            })
        return results

    def _search_google(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """使用 Google Custom Search API"""
        if not self.google_api_key or not self.google_cse_id:
            raise ValueError("GOOGLE_API_KEY 或 GOOGLE_CSE_ID 未设置")

        params = urllib.parse.urlencode({
            'q': query,
            'key': self.google_api_key,
            'cx': self.google_cse_id,
            'num': min(max_results, 10),
        })
        url = f"https://www.googleapis.com/customsearch/v1?{params}"

        req = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        with urllib.request.urlopen(req, context=self._ssl_context, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        results = []
        for item in data.get('items', [])[:max_results]:
            results.append({
                'title': item.get('title', ''),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', ''),
            })
        return results

    def _search_bing(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """使用 Bing Search API"""
        if not self.bing_api_key:
            raise ValueError("BING_API_KEY 未设置")

        params = urllib.parse.urlencode({
            'q': query,
            'count': min(max_results, 50),
            'mkt': 'zh-CN',
        })
        url = f"https://api.bing.microsoft.com/v7.0/search?{params}"

        req = urllib.request.Request(url, headers={
            'User-Agent': self.user_agent,
            'Ocp-Apim-Subscription-Key': self.bing_api_key,
        })
        with urllib.request.urlopen(req, context=self._ssl_context, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        results = []
        for item in data.get('webPages', {}).get('value', [])[:max_results]:
            results.append({
                'title': item.get('name', ''),
                'url': item.get('url', ''),
                'snippet': item.get('snippet', ''),
            })
        return results

    def search_music_news(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        搜索音乐相关资讯/新闻

        Args:
            query: 搜索关键词（如 "周杰伦 2026 新专辑", "热门中文歌曲推荐"）
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        return self.search_web(query, max_results=max_results)

    def fetch_page_content(self, url: str, max_chars: int = 3000) -> str:
        """
        获取网页内容摘要

        Args:
            url: 网页 URL
            max_chars: 最大字符数

        Returns:
            网页文本内容
        """
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': self.user_agent}
            )
            with urllib.request.urlopen(req, context=self._ssl_context, timeout=15) as resp:
                html_content = resp.read().decode('utf-8', errors='replace')

            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            text = extractor.get_text()

            # 截断
            if len(text) > max_chars:
                text = text[:max_chars] + '...'

            return text
        except Exception as e:
            return f"[获取内容失败: {e}]"

    def search_top_charts_info(self, chart_key: str = '') -> List[Dict[str, str]]:
        """
        搜索排行榜音乐资讯

        Args:
            chart_key: 排行榜键名，空字符串则搜索热门榜单

        Returns:
            搜索结果
        """
        query = f"{chart_key} 热门歌曲排行榜" if chart_key else "2026年热门歌曲排行榜"
        return self.search_web(query, max_results=5)

    def search_artist_info(self, artist_name: str) -> List[Dict[str, str]]:
        """
        搜索歌手信息

        Args:
            artist_name: 歌手名

        Returns:
            搜索结果
        """
        return self.search_web(f"{artist_name} 歌手 热门歌曲", max_results=5)

    def search_song_recommendations(self, style: str = '') -> List[Dict[str, str]]:
        """
        搜索歌曲推荐

        Args:
            style: 音乐风格/流派

        Returns:
            搜索结果
        """
        query = f"{style} 歌曲推荐" if style else "热门歌曲推荐 2026"
        return self.search_web(query, max_results=8)

    @staticmethod
    def _strip_tags(html_text: str) -> str:
        """移除 HTML 标签"""
        return re.sub(r'<[^>]+>', '', html_text).strip()

    @staticmethod
    def _decode_html_entities(text: str) -> str:
        """解码 HTML 实体"""
        return html.unescape(text)


# ========== 独立测试 ==========
if __name__ == '__main__':
    print("=== SearchTools 测试 ===")
    tools = SearchTools()
    
    # 测试搜索
    results = tools.search_web("热门中文歌曲 2026")
    print(f"\n搜索结果 ({len(results)} 条):")
    for r in results[:3]:
        print(f"  - {r['title']}")
        print(f"    {r['url']}")
        print(f"    {r['snippet'][:100]}...")
        print()

    # 测试音乐资讯搜索
    news = tools.search_music_news("周杰伦 新歌")
    print(f"\n音乐资讯 ({len(news)} 条):")
    for r in news[:3]:
        print(f"  - {r['title']}")
