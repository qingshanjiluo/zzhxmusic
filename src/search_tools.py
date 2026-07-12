#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索工具模块 - 提供网络搜索、音乐资讯获取能力
支持三种后端:
  1. DuckDuckGo HTML 搜索（免配置零成本，默认）
  2. browser-act 无头浏览器搜索（推荐，免费注册即可用，可搜索 Google/Bing）
  3. 可选付费 API：SerpAPI / Google Custom Search / Bing Search

用法:
    from search_tools import SearchTools
    tools = SearchTools()
    results = tools.search_web("2026年热门中文歌曲")
    results = tools.search_music_news("周杰伦 新专辑")
"""

import os
import json
import re
import subprocess
import shutil
import urllib.parse
import urllib.request
import urllib.error
import html.parser
import tempfile
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


class BrowserActSearch:
    """
    browser-act 无头浏览器搜索后端
    使用 Chrome 浏览器打开搜索引擎抓取结果，无需任何 API key
    也支持 stealth-extract（需免费注册获取 API key，突破反爬更强）
    """
    
    # browser-act CLI 路径
    BROWSER_ACT_CMD = 'browser-act'
    
    # 缓存检测结果：browser-act 是否已安装
    _available = None
    
    @classmethod
    def is_available(cls) -> bool:
        """检测 browser-act 命令是否已安装"""
        if cls._available is None:
            import shutil
            cls._available = shutil.which(cls.BROWSER_ACT_CMD) is not None
        return cls._available
    
    # 搜索 URL 模板
    SEARCH_URLS = {
        'google': 'https://www.google.com/search?q={query}&hl=zh-CN&num={num}',
        'bing': 'https://www.bing.com/search?q={query}&count={num}',
        'baidu': 'https://www.baidu.com/s?wd={query}&rn={num}',
    }

    def __init__(self, engine: str = 'google', use_stealth: bool = False,
                 api_key: str = '', timeout: int = 30):
        """
        初始化 browser-act 搜索
        
        Args:
            engine: 搜索引擎 (google/bing/baidu)
            use_stealth: 是否使用 stealth-extract（需 BrowserAct API key）
            api_key: BrowserAct API key（stealth 模式需要）
            timeout: 超时秒数
        """
        self.engine = engine
        self.use_stealth = use_stealth
        self.api_key = api_key or os.environ.get('BROWSERACT_API_KEY', '')
        self.timeout = timeout
        self._has_stealth = bool(self.api_key) if use_stealth else False
    
    def search(self, query: str, max_results: int = 8) -> List[Dict[str, str]]:
        """
        使用 browser-act 执行搜索
        
        策略:
          1. 如果 use_stealth=True 且有 API key，使用 stealth-extract（可突破反爬）
          2. 否则使用 chrome 模式打开搜索引擎并提取结果
        
        Returns:
            [{'title': str, 'url': str, 'snippet': str}, ...]
        """
        if self.use_stealth and self._has_stealth:
            return self._search_stealth(query, max_results)
        else:
            return self._search_chrome(query, max_results)
    
    def _search_chrome(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """
        使用 Chrome 模式搜索（无需 API key）
        打开搜索引擎页面，提取搜索结果
        """
        search_url = self.SEARCH_URLS.get(
            self.engine,
            self.SEARCH_URLS['google']
        ).format(
            query=urllib.parse.quote(query),
            num=min(max_results + 5, 20)  # 多取一些用于过滤
        )
        
        session_name = f"search_{int(datetime.now().timestamp())}"
        
        try:
            # 1. 打开页面
            open_result = self._run_cmd([
                '--session', session_name,
                'browser', 'open', 'chrome', search_url
            ])
            if not open_result:
                return []
            
            # 2. 获取 state 查看页面内容
            state_result = self._run_cmd([
                '--session', session_name, 'state'
            ])
            
            # 3. 尝试获取页面源码（用 state 输出提取）
            results = self._parse_state_results(state_result or '', max_results)
            
            # 4. 如果有截图功能可以截取页面，但我们只需要文本
            
            # 清理 session
            self._run_cmd(['session', 'close', session_name], check=False)
            
            return results
            
        except Exception as e:
            # 清理 session
            try:
                self._run_cmd(['session', 'close', session_name], check=False)
            except:
                pass
            print(f"  [browser-act] Chrome 搜索失败: {e}")
            return []
    
    def _search_stealth(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """
        使用 stealth-extract 模式搜索（需要免费注册获取 API key）
        自动突破反爬，直接获取页面渲染后的内容
        """
        search_url = self.SEARCH_URLS.get(
            self.engine,
            self.SEARCH_URLS['google']
        ).format(
            query=urllib.parse.quote(query),
            num=min(max_results + 5, 20)
        )
        
        try:
            # 使用临时文件保存输出
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.md', 
                                            delete=False, encoding='utf-8') as f:
                output_path = f.name
            
            try:
                result = self._run_cmd([
                    'stealth-extract', search_url,
                    '--output', output_path,
                    '--content-type', 'markdown'
                ])
                
                # 读取结果
                if os.path.exists(output_path):
                    with open(output_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 解析 markdown 格式的搜索结果
                    results = self._parse_stealth_results(content, max_results)
                    if results:
                        return results
                
                # 如果没有解析出结构化结果，返回原始内容
                if content and content.strip():
                    return [{
                        'title': f'{self.engine.upper()} 搜索结果',
                        'url': search_url,
                        'snippet': content[:500] + ('...' if len(content) > 500 else '')
                    }]
                    
            finally:
                # 清理临时文件
                try:
                    os.unlink(output_path)
                except:
                    pass
            
            return []
            
        except Exception as e:
            print(f"  [browser-act] stealth-extract 搜索失败: {e}")
            return []
    
    def _parse_state_results(self, state_text: str, max_results: int) -> List[Dict[str, str]]:
        """
        从 browser-act state 输出中解析搜索结果
        state 输出格式类似:
        url=https://www.google.com/...
        title=xxx
        
        *[1]<div />
          ...
        """
        results = []
        
        # 提取所有可见文本（state 输出包含页面结构和文本）
        # Google/Bing 搜索结果通常在 <a> 标签中
        lines = state_text.split('\n')
        
        current_title = ''
        current_url = ''
        current_snippet = ''
        
        for line in lines:
            # 提取 URL（state 输出中的 href 属性）
            url_match = re.search(r'href="([^"]+)"', line)
            if url_match:
                url = url_match.group(1)
                if url.startswith('http') and not current_url:
                    current_url = url
            
            # 提取链接文本（搜索结果标题通常在链接中）
            text_match = re.search(r'\]<[^>]*>\s*(.+?)\s*$', line)
            if text_match:
                text = text_match.group(1).strip()
                if text and len(text) > 10 and current_url:
                    results.append({
                        'title': text,
                        'url': current_url,
                        'snippet': ''
                    })
                    current_url = ''
                    if len(results) >= max_results:
                        break
        
        return results
    
    def _parse_stealth_results(self, content: str, max_results: int) -> List[Dict[str, str]]:
        """
        从 stealth-extract 输出的 markdown 中解析搜索结果
        Google 搜索结果 markdown 通常包含链接和描述
        """
        results = []
        
        # 匹配 markdown 链接: [title](url)
        link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        
        # 按段落分割
        paragraphs = content.split('\n\n')
        
        for para in paragraphs:
            links = link_pattern.findall(para)
            for title, url in links:
                # 过滤掉 Google UI 链接
                if url.startswith('http') and not any(
                    skip in url for skip in [
                        'google.com/search', 'google.com/setpref',
                        'accounts.google.com', 'support.google.com',
                        'policies.google.com'
                    ]
                ):
                    # 提取摘要（链接后的文本）
                    snippet = ''
                    lines = para.split('\n')
                    for i, line in enumerate(lines):
                        if url in line or title in line:
                            if i + 1 < len(lines):
                                snippet = lines[i + 1].strip()
                            break
                    
                    if title not in [r['title'] for r in results]:
                        results.append({
                            'title': title,
                            'url': url,
                            'snippet': snippet[:200] if snippet else ''
                        })
                        if len(results) >= max_results:
                            return results
        
        return results
    
    def _run_cmd(self, args: List[str], check: bool = True) -> Optional[str]:
        """执行 browser-act 命令"""
        if not self.is_available():
            return None
        
        cmd = [self.BROWSER_ACT_CMD] + args
        
        env = os.environ.copy()
        if self.api_key:
            env['BROWSERACT_API_KEY'] = self.api_key
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env
            )
            if check and result.returncode != 0:
                return None
            return result.stdout or result.stderr
        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None
    
    def fetch_page(self, url: str, max_chars: int = 3000) -> str:
        """
        使用 browser-act 获取页面内容
        
        优先使用 stealth-extract（如果有 API key），否则用 chrome 模式
        """
        if self._has_stealth:
            return self._fetch_stealth(url, max_chars)
        else:
            return self._fetch_chrome(url, max_chars)
    
    def _fetch_stealth(self, url: str, max_chars: int) -> str:
        """使用 stealth-extract 获取页面"""
        try:
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.md',
                                            delete=False, encoding='utf-8') as f:
                output_path = f.name
            
            try:
                self._run_cmd([
                    'stealth-extract', url,
                    '--output', output_path,
                    '--content-type', 'markdown'
                ])
                
                if os.path.exists(output_path):
                    with open(output_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if len(content) > max_chars:
                        content = content[:max_chars] + '...'
                    return content
            finally:
                try:
                    os.unlink(output_path)
                except:
                    pass
            
            return ''
        except Exception as e:
            return f"[browser-act 获取页面失败: {e}]"
    
    def _fetch_chrome(self, url: str, max_chars: int) -> str:
        """使用 Chrome 模式获取页面"""
        session_name = f"fetch_{int(datetime.now().timestamp())}"
        
        try:
            open_result = self._run_cmd([
                '--session', session_name,
                'browser', 'open', 'chrome', url
            ])
            if not open_result:
                return ''
            
            state_result = self._run_cmd([
                '--session', session_name, 'state'
            ])
            
            # 清理
            self._run_cmd(['session', 'close', session_name], check=False)
            
            text = state_result or ''
            if len(text) > max_chars:
                text = text[:max_chars] + '...'
            return text
            
        except Exception as e:
            try:
                self._run_cmd(['session', 'close', session_name], check=False)
            except:
                pass
            return f"[browser-act 获取页面失败: {e}]"


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
                 browseract_api_key: str = '',
                 browseract_engine: str = 'google',
                 user_agent: str = ''):
        """
        初始化搜索工具

        搜索后端优先级（按推荐顺序）:
          1. browser-act（推荐，无头浏览器，免费注册即可使用）
          2. DuckDuckGo（零配置，免费，默认）
          3. SerpAPI（可选付费）
          4. Google/Bing API（可选付费）

        Args:
            serpapi_key: SerpAPI 密钥（可选付费）
            google_api_key: Google Custom Search API 密钥（可选付费）
            google_cse_id: Google Custom Search Engine ID（可选付费）
            bing_api_key: Bing Search API 密钥（可选付费）
            browseract_api_key: BrowserAct API key（免费注册获取，用于 stealth 模式）
            browseract_engine: browser-act 使用的搜索引擎 (google/bing/baidu)
            user_agent: 自定义 User-Agent
        """
        self.serpapi_key = serpapi_key or os.environ.get('SERPAPI_KEY', '')
        self.google_api_key = google_api_key or os.environ.get('GOOGLE_API_KEY', '')
        self.google_cse_id = google_cse_id or os.environ.get('GOOGLE_CSE_ID', '')
        self.bing_api_key = bing_api_key or os.environ.get('BING_API_KEY', '')
        
        browseract_key = browseract_api_key or os.environ.get('BROWSERACT_API_KEY', '')
        
        self.user_agent = user_agent or (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        )
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE
        
        # 初始化 browser-act 搜索后端
        self._browser_act = BrowserActSearch(
            engine=browseract_engine,
            use_stealth=bool(browseract_key),
            api_key=browseract_key
        )

    def search_web(self, query: str, max_results: int = 8, 
                   source: str = 'auto') -> List[Dict[str, str]]:
        """
        网络搜索主入口 - 智能选择最优后端

        后端选择策略:
          1. browser-act chrome 模式（无需任何 key，搜索 Google）
          2. DuckDuckGo（零配置免费用）
          3. 如果手动指定了 source，使用指定后端

        Args:
            query: 搜索关键词
            max_results: 最大返回结果数
            source: 搜索源
                     auto       - 自动选择最优后端
                     duckduckgo - DuckDuckGo 零配置搜索
                     browseract - browser-act 无头浏览器搜索
                     serpapi    - SerpAPI（需 API key）
                     google     - Google API（需 API key + CSE ID）
                     bing       - Bing API（需 API key）

        Returns:
            [{'title': str, 'url': str, 'snippet': str}, ...]
        """
        # 手动指定后端
        if source != 'auto':
            return self._search_with_source(source, query, max_results)
        
        # 自动选择策略:
        # 优先使用 browser-act（可以搜索 Google，结果质量高）
        try:
            browseract_results = self._browser_act.search(query, max_results)
            if browseract_results:
                print(f"  [搜索] '{query}' -> {len(browseract_results)} 条结果 (via browser-act/{self._browser_act.engine})")
                return browseract_results
        except Exception as e:
            print(f"  [搜索] browser-act 失败: {e}")
        
        # fallback: DuckDuckGo
        try:
            ddg_results = self._search_duckduckgo(query, max_results)
            if ddg_results:
                print(f"  [搜索] '{query}' -> {len(ddg_results)} 条结果 (via duckduckgo)")
                return ddg_results
        except Exception as e:
            print(f"  [搜索] duckduckgo 失败: {e}")
        
        # 最后尝试付费 API
        return self._try_paid_apis(query, max_results)
    
    def _search_with_source(self, source: str, query: str, 
                            max_results: int) -> List[Dict[str, str]]:
        """使用指定后端搜索"""
        handlers = {
            'duckduckgo': self._search_duckduckgo,
            'browseract': lambda q, m: self._browser_act.search(q, m),
            'serpapi': self._search_serpapi,
            'google': self._search_google,
            'bing': self._search_bing,
        }
        
        handler = handlers.get(source, self._search_duckduckgo)
        try:
            results = handler(query, max_results)
            if results:
                print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via {source})")
                return results
        except Exception as e:
            print(f"  [搜索] {source} 失败: {e}")
        
        # fallback 链
        fallbacks = ['browseract', 'duckduckgo']
        for fb in fallbacks:
            if fb == source:
                continue
            fb_handler = handlers.get(fb)
            if fb_handler:
                try:
                    results = fb_handler(query, max_results)
                    if results:
                        print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via {fb} fallback)")
                        return results
                except Exception as e:
                    print(f"  [搜索] {fb} fallback 也失败: {e}")
        
        return []
    
    def _try_paid_apis(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """尝试付费 API 搜索后端"""
        # SerpAPI
        if self.serpapi_key:
            try:
                results = self._search_serpapi(query, max_results)
                if results:
                    print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via serpapi)")
                    return results
            except Exception as e:
                print(f"  [搜索] serpapi 失败: {e}")
        
        # Google API
        if self.google_api_key and self.google_cse_id:
            try:
                results = self._search_google(query, max_results)
                if results:
                    print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via google api)")
                    return results
            except Exception as e:
                print(f"  [搜索] google api 失败: {e}")
        
        # Bing API
        if self.bing_api_key:
            try:
                results = self._search_bing(query, max_results)
                if results:
                    print(f"  [搜索] '{query}' -> {len(results)} 条结果 (via bing api)")
                    return results
            except Exception as e:
                print(f"  [搜索] bing api 失败: {e}")
        
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
        result_pattern = re.compile(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        for match in list(result_pattern.finditer(html_content))[:max_results]:
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
        """
        return self.search_web(query, max_results=max_results)

    def fetch_page_content(self, url: str, max_chars: int = 3000) -> str:
        """
        获取网页内容摘要
        
        优先使用 browser-act（能处理 JS 渲染页面），
        fallback 到 urllib 简单抓取
        """
        # 先尝试 browser-act（能处理 JS 渲染、反爬页面）
        try:
            content = self._browser_act.fetch_page(url, max_chars)
            if content and not content.startswith('[browser-act'):
                return content
        except Exception:
            pass
        
        # fallback: 简单 urllib 抓取
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

            if len(text) > max_chars:
                text = text[:max_chars] + '...'

            return text
        except Exception as e:
            return f"[获取内容失败: {e}]"

    def search_top_charts_info(self, chart_key: str = '') -> List[Dict[str, str]]:
        """搜索排行榜音乐资讯"""
        query = f"{chart_key} 热门歌曲排行榜" if chart_key else "2026年热门歌曲排行榜"
        return self.search_web(query, max_results=5)

    def search_artist_info(self, artist_name: str) -> List[Dict[str, str]]:
        """搜索歌手信息"""
        return self.search_web(f"{artist_name} 歌手 热门歌曲", max_results=5)

    def search_song_recommendations(self, style: str = '') -> List[Dict[str, str]]:
        """搜索歌曲推荐"""
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
    import sys
    import shutil
    
    print("=== SearchTools 测试 ===")
    ba_available = shutil.which('browser-act') is not None
    print(f"browser-act 已安装: {ba_available}")
    print()
    
    if '--fetch' in sys.argv:
        # 测试页面抓取
        idx = sys.argv.index('--fetch')
        url = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else 'https://www.example.com'
        tools = SearchTools()
        content = tools.fetch_page_content(url)
        print(f"\n页面内容 ({url}):")
        print(content[:500])
        
    elif '--browseract' in sys.argv:
        tools = SearchTools()
        query = "热门中文歌曲 2026"
        results = tools.search_web(query, source='browseract')
        print(f"\nbrowser-act 搜索结果 ({len(results)} 条):")
        for r in results[:5]:
            print(f"  - {r['title']}")
            print(f"    {r['url']}")
            print()
    
    else:
        # 默认测试 DuckDuckGo
        tools = SearchTools()
        
        results = tools.search_web("热门中文歌曲 2026")
        print(f"\n搜索结果 ({len(results)} 条):")
        for r in results[:3]:
            print(f"  - {r['title']}")
            print(f"    {r['url']}")
            print(f"    {r['snippet'][:100]}...")
            print()

        news = tools.search_music_news("周杰伦 新歌")
        print(f"\n音乐资讯 ({len(news)} 条):")
        for r in news[:3]:
            print(f"  - {r['title']}")
