import sys
from pathlib import Path
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QProgressBar,
    QLabel, QStatusBar, QMenuBar, QMenu, QToolBar,
    QSplitter, QTreeWidget, QTreeWidgetItem, QMessageBox,
    QFileDialog, QCheckBox, QSpinBox, QGroupBox,
    QRadioButton, QButtonGroup, QGridLayout, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QAction, QIcon, QKeySequence

from ..core.config import ConfigManager
from ..core.search import SearchService
from ..core.download import DownloadService, DownloadTask
from ..core.history import HistoryService


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.search_service = SearchService(config)
        self.download_service = DownloadService(config)
        self.history_service = HistoryService()
        
        self.current_results = []
        self.download_tasks = []
        
        self.setup_ui()
        self.setup_menu()
        self.setup_toolbar()
        self.setup_statusbar()
        self.setup_signals()
        self.load_settings()
    
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle("zzhxmusic - 全功能音乐下载工具箱")
        self.setMinimumSize(1200, 800)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 搜索区域
        search_widget = self.create_search_widget()
        layout.addWidget(search_widget)
        
        # 标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.create_results_tab(), "搜索结果")
        self.tab_widget.addTab(self.create_download_tab(), "下载管理")
        self.tab_widget.addTab(self.create_history_tab(), "历史记录")
        layout.addWidget(self.tab_widget, 1)
        
        # 应用样式
        self.apply_style()
    
    def create_search_widget(self) -> QWidget:
        """创建搜索区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 5)
        
        # 搜索模式
        self.search_type = QComboBox()
        self.search_type.addItems(["单曲", "专辑", "歌单", "歌手"])
        self.search_type.setFixedWidth(80)
        layout.addWidget(QLabel("模式:"))
        layout.addWidget(self.search_type)
        
        # 音源选择
        self.source_combo = QComboBox()
        sources = self.config.get_sources()
        self.source_combo.addItems(["全部"] + sources)
        self.source_combo.setFixedWidth(120)
        layout.addWidget(QLabel("音源:"))
        layout.addWidget(self.source_combo)
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入搜索关键词...")
        self.search_input.returnPressed.connect(self.on_search)
        layout.addWidget(self.search_input, 1)
        
        # 搜索按钮
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.on_search)
        layout.addWidget(self.search_btn)
        
        return widget
    
    def create_results_tab(self) -> QWidget:
        """创建搜索结果标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 工具栏
        toolbar = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.on_select_all)
        toolbar.addWidget(self.select_all_btn)
        
        self.download_selected_btn = QPushButton("下载选中")
        self.download_selected_btn.clicked.connect(self.on_download_selected)
        toolbar.addWidget(self.download_selected_btn)
        
        toolbar.addStretch()
        
        self.result_count_label = QLabel("共 0 首歌曲")
        toolbar.addWidget(self.result_count_label)
        layout.addLayout(toolbar)
        
        # 结果表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(["选择", "歌名", "歌手", "专辑", "音源", "时长"])
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.result_table)
        
        return widget
    
    def create_download_tab(self) -> QWidget:
        """创建下载管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 下载列表
        self.download_table = QTableWidget()
        self.download_table.setColumnCount(6)
        self.download_table.setHorizontalHeaderLabels(["歌曲", "歌手", "质量", "状态", "进度", "操作"])
        self.download_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.download_table)
        
        return widget
    
    def create_history_tab(self) -> QWidget:
        """创建历史记录标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 历史列表
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["歌曲", "歌手", "音源", "时间", "操作"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history_table)
        
        return widget
    
    def setup_menu(self):
        """设置菜单"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 设置菜单
        settings_menu = menubar.addMenu("设置(&S)")
        
        settings_action = QAction("首选项(&P)", self)
        settings_action.triggered.connect(self.on_settings)
        settings_menu.addAction(settings_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)
    
    def setup_toolbar(self):
        """设置工具栏"""
        self.toolbar = self.addToolBar("主工具栏")
        self.toolbar.setMovable(False)
        
        # 刷新按钮
        refresh_action = QAction("刷新", self)
        refresh_action.triggered.connect(self.on_refresh)
        self.toolbar.addAction(refresh_action)
        
        self.toolbar.addSeparator()
        
        # 打开下载目录
        open_dir_action = QAction("打开下载目录", self)
        open_dir_action.triggered.connect(self.on_open_download_dir)
        self.toolbar.addAction(open_dir_action)
    
    def setup_statusbar(self):
        """设置状态栏"""
        self.statusBar().showMessage("就绪")
        
        # 添加进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)
    
    def setup_signals(self):
        """设置信号连接"""
        pass
    
    def apply_style(self):
        """应用样式"""
        style = """
            QMainWindow {
                background-color: #2b2b2b;
            }
            QTableWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                gridline-color: #3c3c3c;
                alternate-background-color: #252525;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                color: #d4d4d4;
                padding: 4px;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QLineEdit, QComboBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px;
            }
            QTabWidget::pane {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
            }
            QTabBar::tab {
                background-color: #2b2b2b;
                color: #d4d4d4;
                padding: 8px 16px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                border-bottom: 2px solid #0e639c;
            }
        """
        self.setStyleSheet(style)
    
    def load_settings(self):
        """加载设置"""
        pass
    
    def on_search(self):
        """执行搜索"""
        keyword = self.search_input.text().strip()
        if not keyword:
            return
        
        search_type = self.search_type.currentText()
        self.statusBar().showMessage(f"正在搜索: {keyword}...")
        
        # 执行搜索
        if search_type == "单曲":
            results = self.search_service.search_songs(keyword, limit=30)
        elif search_type == "专辑":
            results = self.search_service.search_album(keyword, limit=20)
        elif search_type == "歌单":
            # 歌单需要URL，这里简化处理
            results = self.search_service.search_playlist(keyword)
        else:  # 歌手
            results = self.search_service.search_artist(keyword, limit=30)
        
        self.current_results = results
        self.display_results(results)
        self.statusBar().showMessage(f"找到 {len(results)} 首歌曲")
        
        # 记录搜索历史
        self.history_service.add_search(keyword, search_type, '', len(results))
    
    def display_results(self, results: List[Dict]):
        """显示搜索结果"""
        self.result_table.setRowCount(len(results))
        self.result_count_label.setText(f"共 {len(results)} 首歌曲")
        
        for row, item in enumerate(results):
            # 选择框
            checkbox = QTableWidgetItem()
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            self.result_table.setItem(row, 0, checkbox)
            
            # 歌名
            self.result_table.setItem(row, 1, QTableWidgetItem(item.get('title', '')))
            
            # 歌手
            self.result_table.setItem(row, 2, QTableWidgetItem(item.get('artist', '')))
            
            # 专辑
            self.result_table.setItem(row, 3, QTableWidgetItem(item.get('album', '')))
            
            # 音源
            self.result_table.setItem(row, 4, QTableWidgetItem(item.get('source', '')))
            
            # 时长
            duration = item.get('duration', 0)
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                self.result_table.setItem(row, 5, QTableWidgetItem(f"{minutes}:{seconds:02d}"))
            else:
                self.result_table.setItem(row, 5, QTableWidgetItem("--"))
    
    def on_select_all(self):
        """全选/取消全选"""
        rows = self.result_table.rowCount()
        if rows == 0:
            return
        
        # 检查当前全选状态
        first = self.result_table.item(0, 0)
        if first is None:
            return
        
        new_state = Qt.CheckState.Unchecked if first.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        for row in range(rows):
            item = self.result_table.item(row, 0)
            if item:
                item.setCheckState(new_state)
    
    def on_download_selected(self):
        """下载选中歌曲"""
        selected = []
        for row in range(self.result_table.rowCount()):
            check_item = self.result_table.item(row, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                selected.append(self.current_results[row])
        
        if not selected:
            QMessageBox.information(self, "提示", "请先选择要下载的歌曲")
            return
        
        # 添加下载任务
        quality = self.config.get_quality()
        tasks = self.download_service.add_tasks(selected, quality)
        
        # 开始下载
        self.download_service.start_batch(
            tasks,
            on_progress=self.on_download_progress,
            on_complete=self.on_download_complete
        )
        
        QMessageBox.information(self, "提示", f"已添加 {len(selected)} 首歌曲到下载队列")
    
    def on_download_progress(self, task: DownloadTask):
        """下载进度回调"""
        self.update_download_list()
    
    def on_download_complete(self, task: DownloadTask):
        """下载完成回调"""
        self.update_download_list()
        
        # 记录下载历史
        self.history_service.add_download(
            task.song_info,
            task.quality,
            task.status,
            task.filepath or '',
            task.error or ''
        )
    
    def update_download_list(self):
        """更新下载列表"""
        tasks = self.download_service.get_tasks()
        self.download_table.setRowCount(len(tasks))
        
        status_map = {
            'pending': '等待中',
            'downloading': '下载中',
            'completed': '已完成',
            'failed': '失败',
            'paused': '已暂停'
        }
        
        for row, task in enumerate(tasks):
            self.download_table.setItem(row, 0, QTableWidgetItem(task.song_info.get('title', '')))
            self.download_table.setItem(row, 1, QTableWidgetItem(task.song_info.get('artist', '')))
            self.download_table.setItem(row, 2, QTableWidgetItem(task.quality))
            self.download_table.setItem(row, 3, QTableWidgetItem(status_map.get(task.status, task.status)))
            
            # 进度
            progress_item = QTableWidgetItem(f"{task.progress}%")
            self.download_table.setItem(row, 4, progress_item)
            
            # 操作按钮
            self.download_table.setItem(row, 5, QTableWidgetItem("-"))
    
    def on_settings(self):
        """打开设置对话框"""
        QMessageBox.information(self, "设置", "设置功能开发中...")
    
    def on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self,
            "关于 zzhxmusic",
            "zzhxmusic - 全功能音乐下载工具箱\n\n"
            "基于 PyQt6 和 musicdl 构建\n"
            "版本 1.0.0\n\n"
            "支持 QQ音乐、网易云音乐、酷狗、酷我 等音源"
        )
    
    def on_refresh(self):
        """刷新"""
        self.update_download_list()
        self.statusBar().showMessage("已刷新")
    
    def on_open_download_dir(self):
        """打开下载目录"""
        download_dir = self.config.get_download_dir()
        import os
        os.startfile(str(download_dir))
    
    def closeEvent(self, event):
        """关闭事件"""
        # 确认退出
        reply = QMessageBox.question(
            self,
            "确认退出",
            "确定要退出 zzhxmusic 吗？\n正在下载的任务将被中断。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()
