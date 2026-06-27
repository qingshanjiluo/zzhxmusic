# Batch Music Downloader - GitHub Actions 自动化音乐下载工具

这是一个基于 GitHub Actions 的自动化音乐搜索和下载工具，支持单曲搜索、歌单下载和歌手下载三种模式，无需本地环境即可使用。

## ✨ 功能特点

- **三种下载模式**: 单曲搜索、歌单下载、歌手下载
- **GitHub Actions 自动化**: 直接在 GitHub 网页触发，无需安装
- **多音源支持**: QQ音乐、网易云音乐、酷狗、酷我
- **多音质选择**: FLAC、MP3、APE、WAV、AAC
- **自动打包**: 下载完成后自动打包为 ZIP 并供用户下载

##  使用方法

### 1. 单曲搜索下载

在 GitHub 仓库中，进入 **Actions** → **单曲搜索下载** → **Run workflow**

参数说明：
- **歌曲列表**: 每行一首，格式为 `歌名 歌手`
- **音质**: 选择下载音质 (flac/mp3/ape/wav/aac)
- **每首歌曲最多搜索结果数**: 默认 3

示例：
```
七里香 周杰伦
夜曲 周杰伦
告白气球 周杰伦
```

### 2. 歌单下载

进入 **Actions** → **歌单下载** → **Run workflow**

参数说明：
- **歌单 URL**: 支持网易云、QQ音乐等平台的歌单链接
- **音质**: 选择下载音质

示例：
```
https://music.163.com/playlist?id=123456
```

### 3. 歌手下载

进入 **Actions** → **歌手下载** → **Run workflow**

参数说明：
- **歌手名称**: 输入歌手名称
- **音质**: 选择下载音质
- **最多下载歌曲数**: 限制下载数量

示例：
```
周杰伦
```

##  下载文件

工作流运行完成后，在 **Artifacts** 区域下载 ZIP 文件即可。

## ️ 本地运行

如需在本地运行，请安装依赖：

```bash
pip install -r requirements.txt
```

命令行示例：

```bash
# 单曲搜索
python src/batch_downloader.py --query "周杰伦 七里香" --quality flac

# 从文件批量下载
python src/batch_downloader.py --file songs.txt --workers 5

# 歌单下载
python src/batch_downloader.py --playlist "https://music.163.com/playlist?id=123456"

# 歌手下载
python src/batch_downloader.py --artist "周杰伦" --limit 30
```

## ⚙️ 配置

配置文件 `config.json` 支持自定义：

```json
{
    "sources": ["QQMusicClient", "NeteaseMusicClient", "KuwoMusicClient"],
    "output_dir": "./downloads",
    "quality": "flac",
    "max_workers": 3
}
```

##  许可证

MIT License
