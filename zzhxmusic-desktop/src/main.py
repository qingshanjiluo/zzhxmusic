#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zzhxmusic-desktop 主入口
Windows 全功能音乐下载工具箱
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
except ImportError:
    print("错误: 未安装 PyQt6，请运行 pip install PyQt6")
    sys.exit(1)

from src.ui.main_window import MainWindow
from src.core.config import ConfigManager


def main():
    """主函数"""
    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    app.setApplicationName("zzhxmusic")
    app.setOrganizationName("zzhxmusic")
    
    # 加载配置
    config = ConfigManager()
    
    # 创建主窗口
    window = MainWindow(config)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
