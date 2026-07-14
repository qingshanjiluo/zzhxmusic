#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成音源榜单 Markdown 报告
用法: python src/generate_charts_report.py [SOURCE_NAME]
"""

import sys
import os

SOURCE_NAMES = {'QQ': 'QQ音乐', 'Netease': '网易云音乐'}

TOP_CHARTS = {
    'qq_hot':     {'name': 'QQ热歌榜',     'source': 'QQ'},
    'qq_new':     {'name': 'QQ新歌榜',     'source': 'QQ'},
    'qq_pop':     {'name': 'QQ流行榜',     'source': 'QQ'},
    'qq_mainland':{'name': 'QQ内地榜',     'source': 'QQ'},
    'qq_europe':  {'name': 'QQ欧美榜',     'source': 'QQ'},
    'qq_korea':   {'name': 'QQ韩国榜',     'source': 'QQ'},
    'netease_hot':   {'name': '网易云热歌榜', 'source': 'Netease'},
    'netease_new':   {'name': '网易云新歌榜', 'source': 'Netease'},
    'netease_soar':  {'name': '网易云飙升榜', 'source': 'Netease'},
    'netease_orig':  {'name': '网易云原创榜', 'source': 'Netease'},
}

TOP_CHARTS_ALIASES = {
    '热歌榜': 'qq_hot',      'hot': 'qq_hot',
    '新歌榜': 'qq_new',      'new': 'qq_new',
    '流行榜': 'qq_pop',      'pop': 'qq_pop',
    '内地榜': 'qq_mainland', '欧美榜': 'qq_europe',
    '韩国榜': 'qq_korea',
    '飙升榜': 'netease_soar', 'soar': 'netease_soar',
    '原创榜': 'netease_orig', 'orig': 'netease_orig',
    '网易云热歌榜': 'netease_hot', '网易云新歌榜': 'netease_new',
}


def generate_report(source_filter: str = '') -> str:
    """生成榜单 Markdown 报告"""
    lines = []
    if source_filter:
        lines.append(f"# 音源榜单列表 - {SOURCE_NAMES.get(source_filter, source_filter)}音乐")
    else:
        lines.append("# 音源榜单列表 - 全部")

    lines.append("")
    lines.append(f"**音源**: {SOURCE_NAMES.get(source_filter, source_filter) or '全部'}")
    lines.append("")
    lines.append("## 可用排行榜")
    lines.append("")
    lines.append("| 键名 | 榜单名称 | 音源 |")
    lines.append("|------|----------|------|")

    for key, info in TOP_CHARTS.items():
        if source_filter and info['source'] != source_filter:
            continue
        display_name = SOURCE_NAMES.get(info['source'], info['source'])
        lines.append(f"| `{key}` | {info['name']} | {display_name} |")

    lines.append("")
    lines.append("## 别名参考")
    lines.append("")
    lines.append("| 别名 | 对应键名 |")
    lines.append("|------|----------|")

    for alias, key in TOP_CHARTS_ALIASES.items():
        if source_filter:
            info = TOP_CHARTS.get(key)
            if info and info['source'] != source_filter:
                continue
        lines.append(f"| `{alias}` | `{key}` |")

    lines.append("")
    lines.append("## 使用示例")
    lines.append("")
    lines.append("```bash")
    lines.append("# 下载热歌榜（QQ音乐）")
    lines.append("python src/smart_downloader.py --top-charts qq_hot --chart-limit 20")
    lines.append("")
    lines.append("# 下载飙升榜（网易云音乐）")
    lines.append("python src/smart_downloader.py --top-charts netease_soar --chart-limit 30")
    lines.append("")
    lines.append("# 下载全部（不限制数量）")
    lines.append("python src/smart_downloader.py --top-charts 热歌榜")
    lines.append("")
    lines.append("# 列表展示")
    lines.append("python src/smart_downloader.py --list-top-charts")
    lines.append("python src/smart_downloader.py --source-charts QQ")
    lines.append("```")
    lines.append("")

    return '\n'.join(lines)


if __name__ == '__main__':
    source_filter = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    report = generate_report(source_filter)
    report_path = 'charts-report.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"报告已生成: {report_path}")
    print(report)
