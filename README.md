# Smart Downloader - 智能音乐下载器

基于 GitHub Actions 的全自动音乐下载工具，解决下载时间长、重复下载、不能排队三大痛点。

## 特性

- **串行逐源搜索**: 按音源优先级逐个搜索，搜到即停（速度优先）
- **内存去重**: 基于歌名+歌手去重，当次运行内不重复下载
- **并发队列下载**: 自动排队，多线程并发下载
- **两种输入模式**: `file` 模式（读 song-queue.txt）和 命令行参数模式
- **歌手筛选**: 可选只下载指定歌手的歌曲
- **自动打包**: 下载完成自动打包为 ZIP

## GitHub Actions 使用

1. Fork 此仓库
2. 进入 **Actions** -> **智能歌曲下载** -> **Run workflow**
3. 选择输入模式（file/manual），填写歌曲列表
4. 运行完成后在 Artifacts 下载 ZIP

### 参数说明

| 参数 | 说明 |
|------|------|
| 输入来源 | file（读 song-queue.txt）或 manual（手动输入） |
| 歌曲列表 | manual 模式时填写，用 `;` 分隔歌曲，用 `,` 分隔歌手，如: `七里香,周杰伦;稻香,周杰伦;童话,光良` |
| 歌手筛选 | 可选，只下载指定歌手的歌曲 |
| 首选音源 | QQMusicClient / NeteaseMusicClient / ... |
| 音质 | flac / mp3 / ape / wav / aac |
| 并发下载数 | 默认 5 |

## 本地运行

```bash
# 安装依赖
pip install musicdl

# 从 song-queue.txt 文件下载
python src/smart_downloader.py --file song-queue.txt

# 手动输入歌曲列表（;分隔歌曲，,分隔歌手）
python src/smart_downloader.py --text "七里香,周杰伦;稻香,周杰伦;童话,光良"

# 歌手筛选（只下载周杰伦的歌曲）
python src/smart_downloader.py --file song-queue.txt --artist-filter "周杰伦"

# 指定音源和音质
python src/smart_downloader.py --file song-queue.txt --source QQMusicClient --quality flac --workers 5
```

## 项目结构

```
smart-downloader/
├── .github/workflows/
│   ├── smart-download.yml      # 歌曲列表下载 workflow
│   └── playlist-download.yml   # 歌单下载 workflow
├── src/
│   └── smart_downloader.py     # 核心引擎
├── song-queue.txt              # 歌曲列表示例
├── requirements.txt            # 依赖
└── README.md
```

## 技术栈

- Python 3.11+
- [musicdl](https://github.com/CharlesPikachu/musicdl) (音乐源库)
- GitHub Actions (CI/CD)
