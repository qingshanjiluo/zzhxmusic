# zzhxmusic-desktop - Windows 全功能音乐下载工具箱

基于 PyQt6 和 musicdl 构建的 Windows 桌面音乐下载工具，支持多音源搜索、批量下载、历史记录等功能。

## ✨ 功能特点

- **多音源支持**: QQ音乐、网易云音乐、酷狗、酷我
- **四种搜索模式**: 单曲、专辑、歌单、歌手
- **批量下载**: 多线程并发下载，实时进度显示
- **历史记录**: SQLite 本地存储，记录搜索和下载历史
- **现代化界面**: 深色主题，标签页布局

##  安装依赖

```bash
pip install -r requirements.txt
```

## ▶️ 运行应用

```bash
python -m src.main
```

##  打包为 EXE

### 方式一：使用 Python 脚本

```bash
python build_exe.py
```

### 方式二：使用批处理脚本 (Windows)

双击运行 `build.bat`

### 方式三：使用 PowerShell 脚本

```powershell
.\build.ps1
```

打包完成后，EXE 文件位于 `dist/zzhxmusic.exe`

##  配置文件

配置文件位于 `%USERPROFILE%/.zzhxmusic/config.json`

```json
{
    "download_dir": "C:/Users/xxx/Music/zzhxmusic",
    "quality": "flac",
    "max_concurrent": 3,
    "music_sources": ["QQMusicClient", "NeteaseMusicClient", "KuwoMusicClient"]
}
```

##  使用说明

1. 在搜索框输入关键词
2. 选择搜索模式（单曲/专辑/歌单/歌手）
3. 点击"搜索"按钮
4. 在结果列表中勾选需要下载的歌曲
5. 点击"下载选中"开始下载
6. 在"下载管理"标签页查看进度
7. 在"历史记录"标签页查看过往记录

## ️ 技术栈

- Python 3.10+
- PyQt6 - GUI 框架
- musicdl - 音乐下载核心库
- SQLite - 本地数据库
- PyInstaller - 打包工具

##  许可证

MIT License
