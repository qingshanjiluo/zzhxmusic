'''
Function:
    Implementation of MusicdlGUI
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import sys
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5 import *
from PyQt5 import QtCore
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from musicdl import musicdl
from PyQt5.QtWidgets import *
from musicdl.modules.utils.misc import IOUtils, sanitize_filepath


'''SearchWorker'''
class SearchWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, music_sources, keyword, search_size, search_type='song'):
        super().__init__()
        self.music_sources = music_sources
        self.keyword = keyword
        self.search_size = search_size
        self.search_type = search_type

    def run(self):
        try:
            init_cfg = {src: {'search_size_per_source': self.search_size} for src in self.music_sources}
            # build search rules for different search types
            search_rules = {}
            for src in self.music_sources:
                if self.search_type == 'album':
                    if src == 'QQMusicClient':
                        from musicdl.modules.utils.qqutils import SearchType
                        search_rules[src] = {'search_type': SearchType.ALBUM.value}
                    elif src == 'NeteaseMusicClient':
                        search_rules[src] = {'type': 10}  # 网易云专辑搜索 type=10
                    else:
                        search_rules[src] = {}
                else:
                    search_rules[src] = {}
            client = musicdl.MusicClient(
                music_sources=self.music_sources,
                init_music_clients_cfg=init_cfg,
                search_rules=search_rules,
            )
            results = client.search(keyword=self.keyword)
            self.finished.emit((client, results))
        except Exception as e:
            self.error.emit(str(e))


'''PlaylistWorker'''
class PlaylistWorker(QThread):
    finished = pyqtSignal(object)  # (client, list_of_song_infos)
    error = pyqtSignal(str)

    def __init__(self, music_sources, playlist_url, search_size):
        super().__init__()
        self.music_sources = music_sources
        self.playlist_url = playlist_url
        self.search_size = search_size

    def run(self):
        try:
            init_cfg = {src: {'search_size_per_source': self.search_size} for src in self.music_sources}
            client = musicdl.MusicClient(
                music_sources=self.music_sources,
                init_music_clients_cfg=init_cfg,
            )
            results = client.parseplaylist(playlist_url=self.playlist_url)
            self.finished.emit((client, results))
        except Exception as e:
            self.error.emit(str(e))


'''BatchDownloadWorker'''
class BatchDownloadWorker(QThread):
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)      # list of downloaded file paths
    error = pyqtSignal(str)

    def __init__(self, song_infos, download_dir, max_workers=3):
        super().__init__()
        self.song_infos = song_infos
        self.download_dir = download_dir
        self.max_workers = max_workers

    def run(self):
        try:
            IOUtils.touchdir(self.download_dir)
            downloaded_files = []
            total = len(self.song_infos)

            def download_one(song_info):
                try:
                    with requests.get(
                        song_info['download_url'],
                        stream=True, verify=False, timeout=(10, 30)
                    ) as resp:
                        if resp.status_code == 200:
                            safe_filename = sanitize_filepath(song_info['song_name'] + '.' + song_info['ext'])
                            file_path = os.path.join(self.download_dir, safe_filename)
                            with open(file_path, 'wb') as fp:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        fp.write(chunk)
                            return file_path
                        else:
                            return None
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(download_one, info): info for info in self.song_infos}
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    result = future.result()
                    if result:
                        downloaded_files.append(result)
                    self.progress.emit(completed, total)

            self.finished.emit(downloaded_files)
        except Exception as e:
            self.error.emit(str(e))


'''MusicdlGUI'''
class MusicdlGUI(QWidget):
    def __init__(self):
        super(MusicdlGUI, self).__init__()
        # initialize
        self.setWindowTitle('MusicdlGUI —— Charles的皮卡丘')
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'icon.ico')))
        self.setFixedSize(1050, 700)
        self.initialize()
        # search sources
        self.src_names = ['QQMusicClient', 'KuwoMusicClient', 'MiguMusicClient', 'QianqianMusicClient', 'KugouMusicClient', 'NeteaseMusicClient']
        self.label_src = QLabel('Search Engine:')
        self.check_boxes = []
        for src in self.src_names:
            cb = QCheckBox(src, self)
            cb.setCheckState(QtCore.Qt.Checked)
            self.check_boxes.append(cb)
        # search type
        self.label_search_type = QLabel('Search Type:')
        self.combo_search_type = QComboBox()
        self.combo_search_type.addItems(['Song', 'Album'])
        # search size
        self.label_size = QLabel('Per Source:')
        self.spinbox_size = QSpinBox()
        self.spinbox_size.setRange(1, 100)
        self.spinbox_size.setValue(5)
        self.spinbox_size.setSuffix(' items')
        # input boxes
        self.label_keyword = QLabel('Keywords:')
        self.lineedit_keyword = QLineEdit('尾戒')
        self.button_keyword = QPushButton('Search')
        # playlist url
        self.label_playlist = QLabel('Playlist URL:')
        self.lineedit_playlist = QLineEdit()
        self.lineedit_playlist.setPlaceholderText('Paste playlist URL (e.g. https://music.163.com/playlist?id=...)')
        self.button_playlist = QPushButton('Parse Playlist')
        # output dir
        self.label_dir = QLabel('Save To:')
        self.lineedit_dir = QLineEdit('musicdl_outputs')
        self.button_browse = QPushButton('Browse')
        # concurrent downloads
        self.label_concurrency = QLabel('Threads:')
        self.spinbox_concurrency = QSpinBox()
        self.spinbox_concurrency.setRange(1, 10)
        self.spinbox_concurrency.setValue(3)
        self.spinbox_concurrency.setSuffix(' threads')
        # filter section
        self.label_filter = QLabel('Filter:')
        self.lineedit_filter_singer = QLineEdit()
        self.lineedit_filter_singer.setPlaceholderText('Filter by Singer')
        self.lineedit_filter_album = QLineEdit()
        self.lineedit_filter_album.setPlaceholderText('Filter by Album')
        self.button_filter = QPushButton('Apply Filter')
        self.label_filter_count = QLabel('')
        # search results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels(['ID', 'Singers', 'Songname', 'Filesize', 'Duration', 'Album', 'Source'])
        self.results_table.horizontalHeader().setStyleSheet("QHeaderView::section{background:skyblue;color:black;}")
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # mouse click menu
        self.context_menu = QMenu(self)
        self.action_download_selected = self.context_menu.addAction('Download Selected')
        self.action_download_all = self.context_menu.addAction('Download All (Filtered)')
        # progress bar
        self.bar_download = QProgressBar(self)
        self.label_download = QLabel('Download progress:')
        # status label
        self.label_status = QLabel('')
        self.label_status.setAlignment(Qt.AlignCenter)
        # grid layout
        grid = QGridLayout()
        # row 0: search engines
        grid.addWidget(self.label_src, 0, 0, 1, 1)
        for idx, cb in enumerate(self.check_boxes): grid.addWidget(cb, 0, idx+1, 1, 1)
        # row 1: search type + size + keyword + search button
        grid.addWidget(self.label_search_type, 1, 0, 1, 1)
        grid.addWidget(self.combo_search_type, 1, 1, 1, 1)
        grid.addWidget(self.label_size, 1, 2, 1, 1)
        grid.addWidget(self.spinbox_size, 1, 3, 1, 1)
        grid.addWidget(self.label_keyword, 1, 4, 1, 1)
        grid.addWidget(self.lineedit_keyword, 1, 5, 1, 3)
        grid.addWidget(self.button_keyword, 1, 8, 1, 1)
        # row 2: playlist url
        grid.addWidget(self.label_playlist, 2, 0, 1, 1)
        grid.addWidget(self.lineedit_playlist, 2, 1, 1, 7)
        grid.addWidget(self.button_playlist, 2, 8, 1, 1)
        # row 3: save dir + threads
        grid.addWidget(self.label_dir, 3, 0, 1, 1)
        grid.addWidget(self.lineedit_dir, 3, 1, 1, 6)
        grid.addWidget(self.button_browse, 3, 7, 1, 1)
        grid.addWidget(self.label_concurrency, 3, 8, 1, 1)
        grid.addWidget(self.spinbox_concurrency, 3, 9, 1, 1)
        # row 4: filter
        grid.addWidget(self.label_filter, 4, 0, 1, 1)
        grid.addWidget(self.lineedit_filter_singer, 4, 1, 1, 3)
        grid.addWidget(self.lineedit_filter_album, 4, 4, 1, 3)
        grid.addWidget(self.button_filter, 4, 7, 1, 1)
        grid.addWidget(self.label_filter_count, 4, 8, 1, 2)
        # row 5: download progress
        grid.addWidget(self.label_download, 5, 0, 1, 1)
        grid.addWidget(self.bar_download, 5, 1, 1, 9)
        # row 6: results table
        grid.addWidget(self.results_table, 6, 0, 1, 10)
        # row 7: status
        grid.addWidget(self.label_status, 7, 0, 1, 10)
        self.grid = grid
        self.setLayout(grid)
        # connect
        self.button_keyword.clicked.connect(self.search)
        self.button_playlist.clicked.connect(self.parse_playlist)
        self.lineedit_playlist.returnPressed.connect(self.parse_playlist)
        self.button_browse.clicked.connect(self.browse_dir)
        self.button_filter.clicked.connect(self.apply_filter)
        self.lineedit_filter_singer.returnPressed.connect(self.apply_filter)
        self.lineedit_filter_album.returnPressed.connect(self.apply_filter)
        self.results_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.mouseclick)
        self.action_download_selected.triggered.connect(self.download_selected)
        self.action_download_all.triggered.connect(self.download_all)
    '''initialize'''
    def initialize(self):
        self.search_results = {}
        self.music_records = {}       # all records from search
        self.filtered_records = {}    # records after applying filter
        self.selected_music_idx = -10000
        self.music_client = None
        self.search_worker = None
        self.playlist_worker = None
        self.download_worker = None
        self.current_keyword = ''
    '''browse_dir'''
    def browse_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, 'Select Download Directory')
        if dir_path:
            self.lineedit_dir.setText(dir_path)
    '''mouseclick'''
    def mouseclick(self):
        self.context_menu.move(QCursor().pos())
        self.context_menu.show()
    '''get_download_dir'''
    def get_download_dir(self):
        base_dir = self.lineedit_dir.text().strip() or 'musicdl_outputs'
        return os.path.join(base_dir, self.current_keyword)
    '''apply_filter'''
    def apply_filter(self):
        singer_filter = self.lineedit_filter_singer.text().strip().lower()
        album_filter = self.lineedit_filter_album.text().strip().lower()
        if not singer_filter and not album_filter:
            self.filtered_records = dict(self.music_records)
        else:
            self.filtered_records = {}
            for idx, info in self.music_records.items():
                match = True
                if singer_filter:
                    if not re.search(re.escape(singer_filter), info.get('singers', '').lower()):
                        match = False
                if match and album_filter:
                    if not re.search(re.escape(album_filter), info.get('album', '').lower()):
                        match = False
                if match:
                    self.filtered_records[idx] = info
        self.refresh_table()
    '''refresh_table'''
    def refresh_table(self):
        self.results_table.setRowCount(0)
        count = len(self.filtered_records)
        self.results_table.setRowCount(count)
        row = 0
        for idx in sorted(self.filtered_records.keys(), key=int):
            info = self.filtered_records[idx]
            for column, item in enumerate([str(row), info['singers'], info['song_name'], info['file_size'], info['duration'], info['album'], info['source']]):
                self.results_table.setItem(row, column, QTableWidgetItem(item))
                self.results_table.item(row, column).setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            row += 1
        self.label_filter_count.setText(f'Filtered: {count}/{len(self.music_records)}')
    '''download_selected'''
    def download_selected(self):
        selected_rows = set()
        for item in self.results_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            QMessageBox().warning(self, 'Warning', 'Please select at least one song.')
            return
        # map displayed row back to original record key
        sorted_keys = sorted(self.filtered_records.keys(), key=int)
        song_infos = []
        for row in sorted(selected_rows):
            if row < len(sorted_keys):
                info = self.filtered_records.get(sorted_keys[row])
                if info:
                    song_infos.append(info)
        self.start_batch_download(song_infos)
    '''download_all'''
    def download_all(self):
        if not self.filtered_records:
            QMessageBox().warning(self, 'Warning', 'No results to download.')
            return
        song_infos = list(self.filtered_records.values())
        self.start_batch_download(song_infos)
    '''start_batch_download'''
    def start_batch_download(self, song_infos):
        if not song_infos:
            return
        download_dir = self.get_download_dir()
        max_workers = self.spinbox_concurrency.value()
        self.label_status.setText(f'Downloading {len(song_infos)} songs ({max_workers} threads)...')
        self.bar_download.setValue(0)
        self.download_worker = BatchDownloadWorker(song_infos, download_dir, max_workers)
        self.download_worker.progress.connect(self.on_batch_progress)
        self.download_worker.finished.connect(self.on_batch_finished)
        self.download_worker.error.connect(self.on_batch_error)
        self.download_worker.start()
    '''on_batch_progress'''
    def on_batch_progress(self, current, total):
        self.bar_download.setMaximum(total)
        self.bar_download.setValue(current)
        self.label_status.setText(f'Downloading... {current}/{total}')
    '''on_batch_finished'''
    def on_batch_finished(self, downloaded_files):
        self.bar_download.setValue(self.bar_download.maximum())
        self.label_status.setText('')
        QMessageBox().information(
            self, 'Download Complete',
            f'Successfully downloaded {len(downloaded_files)} songs.\n'
            f'Saved to: {self.get_download_dir()}'
        )
        self.bar_download.setValue(0)
    '''on_batch_error'''
    def on_batch_error(self, err_msg):
        self.label_status.setText('')
        QMessageBox().warning(self, 'Download Failed', f'Download failed: {err_msg}')
        self.bar_download.setValue(0)
    '''search'''
    def search(self):
        self.initialize()
        # selected music sources
        music_sources = []
        for cb in self.check_boxes:
            if cb.isChecked():
                music_sources.append(cb.text())
        if not music_sources:
            QMessageBox().warning(self, 'Warning', 'Please select at least one music source.')
            return
        # keyword
        keyword = self.lineedit_keyword.text().strip()
        if not keyword:
            QMessageBox().warning(self, 'Warning', 'Please enter a keyword.')
            return
        self.current_keyword = keyword
        search_size = self.spinbox_size.value()
        search_type = self.combo_search_type.currentText().lower()
        # disable button and show status
        self.button_keyword.setEnabled(False)
        self.button_keyword.setText('Searching...')
        self.label_status.setText('Searching, please wait...')
        self.results_table.setRowCount(0)
        # start search in background
        self.search_worker = SearchWorker(music_sources, keyword, search_size, search_type)
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.start()
    '''on_search_finished'''
    def on_search_finished(self, result):
        client, search_results = result
        self.music_client = client
        self.search_results = search_results
        # collect all records
        count, row = 0, 0
        for per_source_search_results in self.search_results.values():
            count += len(per_source_search_results)
        self.music_records = {}
        for _, (_, per_source_search_results) in enumerate(self.search_results.items()):
            for _, per_source_search_result in enumerate(per_source_search_results):
                self.music_records.update({str(row): per_source_search_result})
                row += 1
        # apply current filter
        self.filtered_records = dict(self.music_records)
        self.refresh_table()
        # restore UI
        self.button_keyword.setEnabled(True)
        self.button_keyword.setText('Search')
        self.label_status.setText(f'Found {count} results')
    '''on_search_error'''
    def on_search_error(self, err_msg):
        self.button_keyword.setEnabled(True)
        self.button_keyword.setText('Search')
        self.label_status.setText('Search failed')
        QMessageBox().warning(self, 'Search Failed', f'Search failed: {err_msg}')
    '''parse_playlist'''
    def parse_playlist(self):
        playlist_url = self.lineedit_playlist.text().strip()
        if not playlist_url:
            QMessageBox().warning(self, 'Warning', 'Please enter a playlist URL.')
            return
        # selected music sources
        music_sources = []
        for cb in self.check_boxes:
            if cb.isChecked():
                music_sources.append(cb.text())
        if not music_sources:
            QMessageBox().warning(self, 'Warning', 'Please select at least one music source.')
            return
        self.initialize()
        self.current_keyword = 'playlist'
        search_size = self.spinbox_size.value()
        # disable button and show status
        self.button_playlist.setEnabled(False)
        self.button_playlist.setText('Parsing...')
        self.label_status.setText('Parsing playlist, please wait...')
        self.results_table.setRowCount(0)
        # start parsing in background
        self.playlist_worker = PlaylistWorker(music_sources, playlist_url, search_size)
        self.playlist_worker.finished.connect(self.on_playlist_finished)
        self.playlist_worker.error.connect(self.on_playlist_error)
        self.playlist_worker.start()
    '''on_playlist_finished'''
    def on_playlist_finished(self, result):
        client, song_infos = result
        self.music_client = client
        self.music_records = {}
        for idx, info in enumerate(song_infos):
            self.music_records[str(idx)] = info
        self.filtered_records = dict(self.music_records)
        self.refresh_table()
        # restore UI
        self.button_playlist.setEnabled(True)
        self.button_playlist.setText('Parse Playlist')
        self.label_status.setText(f'Parsed {len(song_infos)} songs from playlist')
    '''on_playlist_error'''
    def on_playlist_error(self, err_msg):
        self.button_playlist.setEnabled(True)
        self.button_playlist.setText('Parse Playlist')
        self.label_status.setText('Parse playlist failed')
        QMessageBox().warning(self, 'Parse Failed', f'Parse playlist failed: {err_msg}')


'''tests'''
if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MusicdlGUI()
    gui.show()
    sys.exit(app.exec_())