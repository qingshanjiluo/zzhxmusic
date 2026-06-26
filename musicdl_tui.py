'''
MusicDL TUI - 命令行交互式音乐下载器
基于 Rich 构建的现代化终端界面
'''
import sys
import os
import re
import time
import threading
from pathlib import Path
from typing import Optional

# ─── 路径修复：确保能导入 musicdl ───
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ─── Rich 终端美化 ───
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.prompt import Prompt, IntPrompt
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TimeElapsedColumn, TimeRemainingColumn, MofNCompleteColumn,
    DownloadColumn, TransferSpeedColumn,
)
from rich.text import Text
from rich.columns import Columns
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.box import ROUNDED, HEAVY, MINIMAL, DOUBLE
from rich.style import Style
from rich.color import Color
from rich import box as rich_box

# ─── musicdl 核心 ───
from musicdl.musicdl import MusicClient, DEFAULT_MUSIC_SOURCES
from musicdl.modules.sources import MusicClientBuilder
from musicdl.modules.utils.data import SongInfo

console = Console()

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
OUTPUT_DIR = _PROJECT_ROOT / 'musicdl_outputs'
OUTPUT_DIR.mkdir(exist_ok=True)

# 音源分类（用于展示）
SOURCE_CATEGORIES = {
    '【大中华区】': [
        'QQMusicClient', 'NeteaseMusicClient', 'KugouMusicClient',
        'KuwoMusicClient', 'MiguMusicClient', 'QianqianMusicClient',
        'BilibiliMusicClient', 'FiveSingMusicClient', 'StreetVoiceMusicClient',
        'SodaMusicClient', 'BodianMusicClient', 'MOOVMusicClient',
    ],
    '【全球流媒体】': [
        'YouTubeMusicClient', 'SpotifyMusicClient', 'AppleMusicClient',
        'DeezerMusicClient', 'QobuzMusicClient', 'TIDALMusicClient',
        'SoundCloudMusicClient', 'JamendoMusicClient', 'JioSaavnMusicClient',
        'FMAMusicClient', 'OpenGameArtMusicClient', 'SunoMusicClient',
        'JooxMusicClient',
    ],
    '【音频/电台】': [
        'XimalayaMusicClient', 'LizhiMusicClient', 'QingtingMusicClient',
        'LRTSMusicClient', 'ITunesMusicClient',
    ],
    '【聚合搜索】': [
        'MP3JuiceMusicClient', 'TuneHubMusicClient', 'GDStudioMusicClient',
        'MyFreeMP3MusicClient', 'JBSouMusicClient', 'WJHEMusicClient',
    ],
    '【第三方站点】': [],  # 动态填充
}

# 获取所有已注册模块
_ALL_REGISTERED = list(MusicClientBuilder.REGISTERED_MODULES.keys())

# 将未分类的放入第三方站点
_categorized = set()
for cat_list in SOURCE_CATEGORIES.values():
    _categorized.update(cat_list)
SOURCE_CATEGORIES['【第三方站点】'] = [s for s in _ALL_REGISTERED if s not in _categorized]


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════
def format_duration(seconds_str: str) -> str:
    """格式化时长显示"""
    if not seconds_str:
        return '--:--'
    try:
        total = int(float(seconds_str))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m}:{s:02d}'
    except (ValueError, TypeError):
        return seconds_str


def format_size(size_str: str) -> str:
    """格式化文件大小"""
    if not size_str:
        return ''
    try:
        size = float(size_str)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'
    except (ValueError, TypeError):
        return size_str


def shorten(text: str, max_len: int = 20) -> str:
    """截断文本"""
    if not text:
        return ''
    text = str(text)
    return text[:max_len] + '...' if len(text) > max_len else text


def get_source_tag(source: str) -> str:
    """获取音源对应的标签"""
    tag_map = {
        'QQMusicClient': '[QQ]', 'NeteaseMusicClient': '[NE]', 'KugouMusicClient': '[KG]',
        'KuwoMusicClient': '[KW]', 'MiguMusicClient': '[MG]', 'QianqianMusicClient': '[QQ]',
        'BilibiliMusicClient': '[BL]', 'YouTubeMusicClient': '[YT]', 'SpotifyMusicClient': '[SP]',
        'AppleMusicClient': '[AP]', 'SoundCloudMusicClient': '[SC]', 'DeezerMusicClient': '[DZ]',
    }
    return tag_map.get(source, '[..]')


# ═══════════════════════════════════════════════════════════════
# 主应用类
# ═══════════════════════════════════════════════════════════════
class MusicDLTUI:
    def __init__(self):
        self.client: Optional[MusicClient] = None
        self.sources: list[str] = list(DEFAULT_MUSIC_SOURCES)
        self.search_results: dict[str, list[SongInfo]] = {}
        self.selected_songs: list[SongInfo] = []
        self.download_history: list[dict] = []
        self.running = True

    # ─── 欢迎界面 ───
    def show_welcome(self):
        console.clear()
        content = (
            '[bold gradient(7c5cfc,00d4aa)]== MusicDL TUI ==[/]\n'
            '[dim white]v2.12.7 - 40+ 音源聚合搜索下载[/]\n\n'
            '[italic white]轻量级音乐下载器[/]\n'
            f'[dim blue]下载目录: {OUTPUT_DIR}[/]'
        )
        welcome = Panel(
            content,
            box=DOUBLE,
            border_style='bright_blue',
            padding=(1, 4),
            title='[bold cyan]欢迎使用[/]',
            subtitle='[dim]输入 q 退出 - h 帮助[/]',
        )
        console.print(welcome)
        console.print()

    # ─── 主菜单 ───
    def show_main_menu(self):
        """显示主菜单并处理用户选择"""
        while self.running:
            console.print()
            menu = Panel(
                '\n'.join([
                    '[bold]1[/] [搜索] 搜索音乐',
                    '[bold]2[/] [歌单] 解析歌单',
                    '[bold]3[/] [音源] 选择音源',
                    '[bold]4[/] [下载] 下载管理',
                    '[bold]5[/] [历史] 下载历史',
                    '',
                    '[dim]q 退出  |  h 帮助[/]',
                ]),
                title='[bold cyan]主菜单[/]',
                box=ROUNDED,
                border_style='bright_blue',
                padding=(1, 2),
            )
            console.print(menu)

            choice = Prompt.ask('[bold cyan]>> 请选择[/]', default='1')
            if choice == '1':
                self.search_music()
            elif choice == '2':
                self.parse_playlist()
            elif choice == '3':
                self.select_sources()
            elif choice == '4':
                self.download_manager()
            elif choice == '5':
                self.show_download_history()
            elif choice.lower() == 'q':
                self.running = False
                console.print('[bold yellow]再见![/]')
            elif choice.lower() == 'h':
                self.show_help()
            else:
                console.print('[bold red][错误] 无效选项，请重新选择[/]')

    # ─── 帮助 ───
    def show_help(self):
        console.clear()
        help_text = """
## MusicDL TUI 帮助

### 基本操作
- **方向键 Up/Down** - 在列表中移动
- **空格键** - 选中/取消选中
- **Enter** - 确认操作
- **数字键** - 选择菜单项

### 功能说明
1. **搜索音乐** - 输入关键词搜索，支持多音源并行搜索
2. **解析歌单** - 输入歌单链接自动解析
3. **选择音源** - 切换搜索来源（40+ 音源可选）
4. **下载管理** - 查看下载进度和管理任务
5. **下载历史** - 查看已下载的文件

### 快捷键
- `q` - 退出
- `h` - 显示帮助
- `r` - 返回主菜单
- `a` - 全选
- `d` - 取消全选

### 提示
- 搜索时建议选择 3-5 个音源以获得最佳速度
- 下载文件保存在 `musicdl_outputs/` 目录
- 部分音源需要网络代理才能访问
        """
        console.print(Markdown(help_text))
        Prompt.ask('[dim]按 Enter 返回[/]')

    # ─── 音源选择 ───
    def select_sources(self):
        """交互式音源选择"""
        console.clear()
        console.print(Panel('[bold][音源] 选择音源[/]', box=ROUNDED, border_style='bright_blue'))

        # 显示当前选择
        current = ', '.join(s.replace('MusicClient', '') for s in self.sources)
        console.print(f'[bold]当前已选:[/] [green]{current}[/]')
        console.print()

        # 按分类显示
        all_source_names = []
        source_to_cat = {}
        for cat, srcs in SOURCE_CATEGORIES.items():
            if not srcs:
                continue
            console.print(f'\n[bold cyan]{cat}[/]')
            row_parts = []
            for src in srcs:
                if src not in _ALL_REGISTERED:
                    continue
                name = src.replace('MusicClient', '')
                all_source_names.append(src)
                source_to_cat[src] = cat
                selected = '[√]' if src in self.sources else '[ ]'
                row_parts.append(f'{selected} {name}')
            # 每行显示 4 个
            for i in range(0, len(row_parts), 4):
                console.print('  ' + '  |  '.join(row_parts[i:i+4]))

        console.print()
        console.print('[dim]输入音源名称切换开关（如 QQMusicClient），输入 a 全选，d 取消全选，空回车返回[/]')
        console.print('[dim]提示: 输入部分名称也可匹配，如 "QQ" 匹配 QQMusicClient[/]')

        while True:
            inp = Prompt.ask('[bold cyan]>>[/]').strip()
            if not inp:
                break
            if inp.lower() == 'a':
                self.sources = list(_ALL_REGISTERED)
                console.print(f'[green][√] 已全选 {len(self.sources)} 个音源[/]')
                continue
            if inp.lower() == 'd':
                self.sources = list(DEFAULT_MUSIC_SOURCES)
                console.print(f'[green][√] 已重置为默认音源 ({len(self.sources)} 个)[/]')
                continue

            # 匹配音源
            matched = [s for s in _ALL_REGISTERED if inp.lower() in s.lower()]
            if not matched:
                console.print(f'[red][×] 未找到匹配 "{inp}" 的音源[/]')
                continue

            for src in matched:
                if src in self.sources:
                    if len(self.sources) <= 1:
                        console.print('[yellow][!] 至少保留一个音源[/]')
                        continue
                    self.sources.remove(src)
                    console.print(f'[yellow][×] 已移除 {src.replace("MusicClient", "")}[/]')
                else:
                    self.sources.append(src)
                    console.print(f'[green][√] 已添加 {src.replace("MusicClient", "")}[/]')

        console.print(f'\n[bold]最终选择:[/] [green]{", ".join(s.replace("MusicClient", "") for s in self.sources)}[/]')
        console.print(f'[dim]共 {len(self.sources)} 个音源[/]')
        time.sleep(1)

    # ─── 搜索音乐 ───
    def search_music(self):
        """搜索音乐"""
        console.clear()
        console.print(Panel('[bold][搜索] 搜索音乐[/]', box=ROUNDED, border_style='bright_blue'))
        console.print(f'[dim]当前音源: {", ".join(s.replace("MusicClient", "") for s in self.sources)}[/]')
        console.print()

        keyword = Prompt.ask('[bold cyan]>> 输入关键词[/]')
        if not keyword.strip():
            return

        # 过滤掉需要 quark_parser_config 但未配置的音源
        _quark_required = ['FLMP3MusicClient', 'KKWSMusicClient', 'FiveSongMusicClient']
        filtered_sources = [s for s in self.sources if s not in _quark_required]
        skipped = [s for s in self.sources if s in _quark_required]
        if skipped:
            console.print(f'[dim yellow]跳过 {len(skipped)} 个需要夸克网盘配置的音源: {", ".join(s.replace("MusicClient","") for s in skipped)}[/]')

        if not filtered_sources:
            console.print('[bold red][×] 没有可用的音源，请先选择音源[/]')
            time.sleep(2)
            return

        try:
            # 创建客户端（disable_print=False 让 musicdl 内部进度条可见）
            self.client = MusicClient(
                music_sources=filtered_sources,
                init_music_clients_cfg={
                    src: {
                        'work_dir': str(OUTPUT_DIR),
                        'disable_print': False,
                    }
                    for src in filtered_sources
                },
            )

            # musicdl.search() 内部自带 Progress 进度条，直接调用即可
            console.print(f'[bold][搜索] 正在搜索 "{keyword}" ...[/]')
            self.search_results = self.client.search(keyword)

        except Exception as e:
            console.print(f'[bold red][×] 搜索失败: {e}[/]')
            time.sleep(2)
            return

        # 统计结果
        total = sum(len(v) for v in self.search_results.values())
        if total == 0:
            console.print(f'[bold yellow][!] 未找到 "{keyword}" 的相关歌曲[/]')
            time.sleep(2)
            return

        console.print(f'\n[bold green][√] 搜索完成! 共找到 {total} 首歌曲[/]')
        time.sleep(0.5)

        # 显示结果并选择
        self.show_search_results(keyword)

    # ─── 显示搜索结果 ───
    def show_search_results(self, keyword: str):
        """展示搜索结果并让用户选择"""
        # 展平结果
        all_songs: list[SongInfo] = []
        for source_name, song_list in self.search_results.items():
            for si in song_list:
                si._tui_source_display = source_name  # 存一下原始来源
                all_songs.append(si)

        if not all_songs:
            return

        # 分页显示
        page_size = 15
        total_pages = (len(all_songs) + page_size - 1) // page_size
        current_page = 0
        selected_indices: set[int] = set()

        while True:
            console.clear()
            start = current_page * page_size
            end = min(start + page_size, len(all_songs))
            page_songs = all_songs[start:end]

            # 标题
            title = Panel(
                f'[bold][搜索] "{keyword}"[/]  [dim]共 {len(all_songs)} 首  |  已选 {len(selected_indices)} 首[/]',
                box=ROUNDED,
                border_style='bright_blue',
            )
            console.print(title)

            # 表格
            table = Table(
                box=MINIMAL,
                header_style='bold cyan',
                border_style='dim',
                show_edge=False,
                padding=(0, 1),
            )
            table.add_column('选', width=3, justify='center')
            table.add_column('#', width=4, justify='right', style='dim')
            table.add_column('歌手', width=16, no_wrap=True)
            table.add_column('歌曲名', width=30, no_wrap=True)
            table.add_column('大小', width=8, justify='right')
            table.add_column('时长', width=6, justify='center')
            table.add_column('音源', width=10, no_wrap=True)

            for i, song in enumerate(page_songs):
                idx = start + i
                checked = '√' if idx in selected_indices else ' '
                singer = shorten(str(song.singers or '未知'), 14)
                songname = shorten(str(song.song_name or '未知'), 28)
                filesize = format_size(song.file_size)
                duration = format_duration(song.duration)
                src = str(song.source or song._tui_source_display or '').replace('MusicClient', '')
                tag = get_source_tag(str(song.source or ''))

                style = 'bold green' if idx in selected_indices else ''
                table.add_row(
                    f'[{checked}]', str(idx + 1),
                    singer, songname,
                    filesize, duration,
                    f'{tag} {src}',
                    style=style,
                )

            console.print(table)

            # 分页信息
            console.print(
                f'[dim]第 {current_page + 1}/{total_pages} 页  '
                f'({start + 1}-{end} / {len(all_songs)})  '
                f'| 输入序号选择, a全选, d取消, p/n翻页, Enter下载, q返回[/]'
            )

            # 用户输入
            inp = Prompt.ask('[bold cyan]>>[/]').strip().lower()

            if inp == 'q':
                break
            elif inp == 'a':
                selected_indices = set(range(len(all_songs)))
            elif inp == 'd':
                selected_indices.clear()
            elif inp == 'p':
                if current_page > 0:
                    current_page -= 1
            elif inp == 'n':
                if current_page < total_pages - 1:
                    current_page += 1
            elif inp == '':
                # Enter - 确认下载
                if selected_indices:
                    break
                else:
                    console.print('[yellow][!] 请先选择歌曲[/]')
                    time.sleep(1)
            else:
                # 尝试解析序号
                try:
                    nums = re.findall(r'\d+', inp)
                    for n in nums:
                        idx = int(n) - 1
                        if 0 <= idx < len(all_songs):
                            if idx in selected_indices:
                                selected_indices.remove(idx)
                            else:
                                selected_indices.add(idx)
                except ValueError:
                    pass

        if not selected_indices:
            return

        # 确认下载
        self.selected_songs = [all_songs[i] for i in sorted(selected_indices)]
        console.print(f'\n[bold green][√] 已选择 {len(self.selected_songs)} 首歌曲[/]')

        confirm = Prompt.ask('[bold cyan]>> 开始下载?[/]', choices=['y', 'n', 'Y', 'N'], default='y')
        if confirm.lower() == 'y':
            self.start_download(self.selected_songs)

    # ─── 解析歌单 ───
    def parse_playlist(self):
        """解析歌单链接"""
        console.clear()
        console.print(Panel('[bold][歌单] 解析歌单[/]', box=ROUNDED, border_style='bright_blue'))
        console.print('[dim]支持: 网易云音乐、QQ音乐、酷狗音乐等歌单链接[/]')
        console.print()

        url = Prompt.ask('[bold cyan]>> 输入歌单链接[/]')
        if not url.strip():
            return

        if not url.startswith('http'):
            console.print('[bold red][×] 无效的链接格式[/]')
            time.sleep(2)
            return

        # 过滤掉需要 quark_parser_config 但未配置的音源
        _quark_required = ['FLMP3MusicClient', 'KKWSMusicClient', 'FiveSongMusicClient']
        filtered_sources = [s for s in self.sources if s not in _quark_required]
        skipped = [s for s in self.sources if s in _quark_required]
        if skipped:
            console.print(f'[dim yellow]跳过 {len(skipped)} 个需要夸克网盘配置的音源: {", ".join(s.replace("MusicClient","") for s in skipped)}[/]')

        if not filtered_sources:
            console.print('[bold red][×] 没有可用的音源[/]')
            time.sleep(2)
            return

        console.print(f'\n[bold][歌单] 正在解析歌单...[/]')

        try:
            self.client = MusicClient(
                music_sources=filtered_sources,
                init_music_clients_cfg={
                    src: {
                        'work_dir': str(OUTPUT_DIR),
                        'disable_print': True,
                    }
                    for src in filtered_sources
                },
            )

            with console.status('[bold cyan]解析中...[/]', spinner='dots'):
                song_infos = self.client.parseplaylist(url)

            if not song_infos:
                console.print('[bold yellow][!] 未解析到歌曲，请检查链接是否有效[/]')
                time.sleep(2)
                return

            console.print(f'\n[bold green][√] 解析成功! 共 {len(song_infos)} 首歌曲[/]')

            # 显示歌曲列表
            table = Table(box=MINIMAL, header_style='bold cyan', border_style='dim')
            table.add_column('#', width=4, justify='right')
            table.add_column('歌手', width=16)
            table.add_column('歌曲名', width=30)
            table.add_column('时长', width=6, justify='center')
            table.add_column('音源', width=10)

            for i, si in enumerate(song_infos[:20]):
                table.add_row(
                    str(i + 1),
                    shorten(str(si.singers or '未知'), 14),
                    shorten(str(si.song_name or '未知'), 28),
                    format_duration(si.duration),
                    str(si.source or '').replace('MusicClient', ''),
                )

            console.print(table)
            if len(song_infos) > 20:
                console.print(f'[dim]... 还有 {len(song_infos) - 20} 首[/]')

            confirm = Prompt.ask('[bold cyan]>> 下载全部歌曲?[/]', choices=['y', 'n'], default='y')
            if confirm.lower() == 'y':
                self.start_download(song_infos)

        except Exception as e:
            console.print(f'[bold red][×] 解析失败: {e}[/]')
            time.sleep(2)

    # ─── 开始下载 ───
    def start_download(self, songs: list[SongInfo]):
        """执行下载任务"""
        if not songs:
            return

        console.clear()
        console.print(Panel(f'[bold][下载] 下载 {len(songs)} 首歌曲[/]', box=ROUNDED, border_style='bright_blue'))

        # 按音源分类
        classified: dict[str, list[SongInfo]] = {}
        for si in songs:
            classified.setdefault(si.source, []).append(si)

        # 显示下载队列
        console.print('\n[bold][列表] 下载队列:[/]')
        for src, src_songs in classified.items():
            tag = get_source_tag(src)
            console.print(f'  {tag} [bold]{src.replace("MusicClient", "")}[/]: {len(src_songs)} 首')

        console.print()

        # 执行下载（带进度条）
        total = len(songs)
        completed = 0
        failed = 0

        progress = Progress(
            TextColumn('[progress.description]{task.description}'),
            BarColumn(bar_width=None),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        with progress:
            # 总进度
            overall_task = progress.add_task(
                f'[cyan][下载] 下载进度 ({completed}/{total})[/]',
                total=total,
            )

            for src, src_songs in classified.items():
                if src not in self.client.music_clients:
                    console.print(f'  [red][×] 跳过未知音源: {src}[/]')
                    failed += len(src_songs)
                    completed += len(src_songs)
                    progress.update(overall_task, completed=completed)
                    continue

                mc = self.client.music_clients[src]
                src_task = progress.add_task(
                    f'  {get_source_tag(src)} [dim]{src.replace("MusicClient", "")}[/]',
                    total=len(src_songs),
                )

                for si in src_songs:
                    try:
                        # 使用 musicdl 的下载方法
                        mc.download(
                            song_infos=[si],
                            num_threadings=1,
                            request_overrides={},
                        )
                        completed += 1
                        progress.update(src_task, advance=1)
                        progress.update(
                            overall_task,
                            completed=completed,
                            description=f'[cyan][下载] 下载进度 ({completed}/{total})[/]',
                        )
                    except Exception as e:
                        failed += 1
                        completed += 1
                        progress.update(src_task, advance=1)
                        progress.update(overall_task, completed=completed)
                        console.print(f'  [red][×] 下载失败: {si.song_name} - {e}[/]')

        # 下载完成
        console.print()
        if failed == 0:
            console.print(f'[bold green][√] 全部下载完成! 成功 {completed}/{total} 首[/]')
        else:
            console.print(f'[bold yellow][!] 下载完成: 成功 {completed - failed}/{total}, 失败 {failed}[/]')

        # 记录历史
        self.download_history.append({
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total': total,
            'completed': completed - failed,
            'failed': failed,
            'songs': songs,
        })

        Prompt.ask('[dim]按 Enter 返回[/]')

    # ─── 下载管理 ───
    def download_manager(self):
        """下载管理（查看当前状态）"""
        console.clear()
        console.print(Panel('[bold][下载] 下载管理[/]', box=ROUNDED, border_style='bright_blue'))
        console.print()
        console.print('[dim]下载功能已集成在搜索流程中[/]')
        console.print()
        console.print(f'[bold]下载目录:[/] [cyan]{OUTPUT_DIR}[/]')
        console.print()

        # 列出已下载的文件
        if OUTPUT_DIR.exists():
            files = []
            for root, dirs, fnames in os.walk(OUTPUT_DIR):
                for f in fnames:
                    if f.endswith(('.mp3', '.flac', '.m4a', '.wav', '.ape', '.ogg')):
                        fp = Path(root) / f
                        files.append(fp)

            if files:
                console.print(f'[bold]已下载 {len(files)} 个音频文件:[/]')
                # 按时间排序，显示最新的 10 个
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                for fp in files[:10]:
                    size = fp.stat().st_size
                    mtime = time.strftime('%m-%d %H:%M', time.localtime(fp.stat().st_mtime))
                    console.print(f'  [dim]{mtime}[/] {shorten(fp.name, 40)} [dim]({format_size(str(size))})[/]')
                if len(files) > 10:
                    console.print(f'  [dim]... 还有 {len(files) - 10} 个文件[/]')
            else:
                console.print('[yellow][!] 暂无下载文件[/]')

        console.print()
        Prompt.ask('[dim]按 Enter 返回[/]')

    # ─── 下载历史 ───
    def show_download_history(self):
        """显示下载历史"""
        console.clear()
        console.print(Panel('[bold][历史] 下载历史[/]', box=ROUNDED, border_style='bright_blue'))
        console.print()

        if not self.download_history:
            console.print('[yellow][!] 暂无下载记录[/]')
        else:
            table = Table(box=MINIMAL, header_style='bold cyan')
            table.add_column('时间', width=20)
            table.add_column('总数', width=6, justify='center')
            table.add_column('成功', width=6, justify='center')
            table.add_column('失败', width=6, justify='center')

            for record in reversed(self.download_history):
                table.add_row(
                    record['time'],
                    str(record['total']),
                    f'[green]{record["completed"]}[/]',
                    f'[red]{record["failed"]}[/]' if record['failed'] else '0',
                )

            console.print(table)

        console.print()
        Prompt.ask('[dim]按 Enter 返回[/]')

    # ─── 启动 ───
    def run(self):
        """启动 TUI"""
        self.show_welcome()
        self.show_main_menu()


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════
def main():
    try:
        app = MusicDLTUI()
        app.run()
    except KeyboardInterrupt:
        console.print('\n[bold yellow]再见![/]')
    except Exception as e:
        console.print(f'\n[bold red][×] 发生错误: {e}[/]')
        import traceback
        console.print(traceback.format_exc())


if __name__ == '__main__':
    main()
