# zzhxmusic - 音乐下载工具

基于 MusicDL 构建的 GitHub Actions 自动化音乐下载工具，支持单曲搜索、歌单下载、歌手下载三种模式，结果自动打包为 ZIP 供下载。

## ✨ 功能特点

- **三种下载模式**：单曲搜索、歌单下载、歌手下载
- **高质量音频**：支持 FLAC、MP3、APE、WAV 格式
- **自动化工作流**：通过 GitHub Actions 一键触发
- **结果打包**：自动将下载的歌曲和元数据打包为 ZIP 文件
- **灵活配置**：支持自定义下载数量、音频质量等参数

##  快速开始

### 1. 部署到 GitHub

将本项目推送到您的 GitHub 仓库：

```bash
git add .
git commit -m "添加 zzhxmusic 音乐下载工具"
git push origin main
```

### 2. 触发工作流

1. 进入仓库的 **Actions** 选项卡
2. 选择对应的工作流：
   - **单曲搜索下载** - 搜索并下载指定歌曲
   - **歌单下载** - 下载指定歌单的所有歌曲
   - **歌手下载** - 下载指定歌手的歌曲
3. 点击 **Run workflow** 并填写参数
4. 等待执行完成

### 3. 下载结果

工作流执行完成后，在 **Artifacts** 区域下载 ZIP 文件，解压即可获得下载的音频文件和元数据记录。

##  工作流说明

### 单曲搜索下载 (`musicdl-search.yml`)

搜索关键词并下载匹配的歌曲。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| keyword | 搜索关键词（歌曲名或歌手名） | 周杰伦 |
| quality | 音频质量 | flac |
| limit | 下载数量限制 (1-100) | 10 |
| output_name | 输出 ZIP 文件名前缀 | search_results |

### 歌单下载 (`musicdl-playlist.yml`)

下载指定歌单中的所有歌曲。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| playlist_url | 歌单链接（QQ音乐/网易云音乐等） | - |
| quality | 音频质量 | flac |
| limit | 下载数量限制 (1-100) | 20 |
| output_name | 输出 ZIP 文件名前缀 | playlist_results |

### 歌手下载 (`musicdl-artist.yml`)

下载指定歌手的歌曲。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| artist_name | 歌手名称 | 周杰伦 |
| quality | 音频质量 | flac |
| limit | 下载数量限制 (1-100) | 30 |
| output_name | 输出 ZIP 文件名前缀 | artist_results |

##  输出结构

下载完成后，ZIP 文件包含以下内容：

```
musicdl_outputs/
├── [mode]_[timestamp]/
│   ├── search_results.json    # 搜索结果元数据
│   ├── download_results.json  # 下载结果记录
│   └── [歌曲文件]              # 下载的音频文件
└── [mode]_[timestamp].zip     # 打包文件
```

## ️ 技术栈

- **Python 3.10+** - 核心脚本语言
- **MusicDL** - 音乐下载库
- **GitHub Actions** - 自动化工作流
- **ZIP** - 文件打包

##  依赖安装

工作流会自动安装依赖，无需手动操作：

```bash
pip install -r requirements.txt
pip install -r requirements-optional.txt  # 可选
```

##  贡献

欢迎提交 Issue 和 Pull Request。

##  许可证

本项目基于 MusicDL 构建，遵循其许可证。

##  相关链接

- [MusicDL 项目](https://github.com/MusicDL/MusicDL)
- [GitHub Actions 文档](https://docs.github.com/actions)

---

**zzhxmusic** - 让音乐下载更简单 
