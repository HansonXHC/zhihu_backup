# 知乎备份工具（zhihu-backup）

[English](README.md) | 中文

把指定知乎用户的**回答、文章、想法**备份为本地 Markdown，同时保存头像、背景图、简介、职业/教育经历等资料，支持下载内容内嵌视频、zvideo，以及可选的 PDF 导出。

输出为 `Markdown + 本地图片 + meta.json`，每篇内容一个目录，断点续传、按内容 ID 去重，提供稳定的 CLI 与 `--json` 汇总，方便脚本或 GUI 调用。

> 本项目仅供个人备份**本人或已获授权**的内容，请遵守知乎服务条款。Cookie 属于敏感信息，工具不会将其写入日志。

---

## 目录

- [功能](#功能)
- [环境要求](#环境要求)
- [安装](#安装)
- [登录](#登录)
- [快速开始](#快速开始)
- [常用场景速查](#常用场景速查)
- [输出结构](#输出结构)
- [命令行参数](#命令行参数)
- [工作方式](#工作方式)
- [增量备份、续传与去重](#增量备份续传与去重)
- [视频](#视频)
- [PDF](#pdf)
- [测试](#测试)
- [常见问题](#常见问题)
- [致谢与许可](#致谢与许可)

---

## 功能

- 备份指定用户的全部回答、文章、想法。
- 备份单个或多个回答、文章、想法、zvideo 链接，也支持从文件批量读取。
- 保存用户昵称、真实尺寸头像、背景图、一句话简介、个人简介、所在行业、职业经历、教育经历、IP 属地与主页链接。
- 头像自动升级为 `xll` 真实尺寸，背景图升级为 `1440w`，不使用缩略图。
- 公司/学校图标保存到 `logos/`；行业仅在页面实际显示图标时保存，不保存通用话题占位图。
- 回答/文章 Markdown 写入发布时间、编辑时间，以及赞同、收藏、喜欢、评论数。
- 回答/文章/想法中的视频默认下载；`--videos` 额外枚举用户的 zvideo 列表；`--no-videos` 可全部关闭。
- 断点续传、失败重试、增量跳过（`--update`），自动按内容 ID 去重。
- Markdown 公式、代码块、链接、图片本地化。
- 可选 PDF（Selenium 打印），自动清理广告/评论区/操作栏；页面异常时回退为本地正文生成干净 PDF。
- 稳定 CLI、`--json` 汇总与明确退出码，便于后期 C/C++ GUI 以子进程方式调用。

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python | 3.9+（开发环境使用 3.14 验证） |
| Microsoft Edge | 登录、DOM 兜底、PDF 打印 |
| ffmpeg | **可选**，仅 HLS/DASH（m3u8/mpd）视频需要；直链 MP4 不需要 |

Selenium 优先通过 Selenium Manager 自动匹配驱动；失败时可用 `--driver` 手动指定 `msedgedriver.exe`。

## 安装

```bash
cd zhihu-backup
python -m pip install -r requirements.txt
```

也可以安装为命令：

```bash
python -m pip install -e .
zhihu-backup --help
```

开发依赖（pytest）：

```bash
python -m pip install -r requirements-dev.txt
```

## 登录

首次使用需要打开浏览器人工登录：

```bash
python -m zhihu_backup login
```

登录成功后 Cookie 保存在 `.zhihu_backup/cookies.json`，后续无需重复登录。Cookie 失效时删除该文件或重新执行 `login`。

无浏览器环境可直接传入 Cookie：

```bash
python -m zhihu_backup user <token> --cookie "z_c0=..." 
python -m zhihu_backup user <token> --cookie-file cookies.txt
```

## 快速开始

### 备份用户的全部内容

```bash
# 默认备份回答、文章、想法；内容里的视频也会下载
python -m zhihu_backup user https://www.zhihu.com/people/xxx
```

常用变体：

```bash
# 同时生成 PDF
python -m zhihu_backup user https://www.zhihu.com/people/xxx --pdf

# 额外枚举并下载该用户的 zvideo 列表
python -m zhihu_backup user https://www.zhihu.com/people/xxx --videos

# 不下载任何视频
python -m zhihu_backup user https://www.zhihu.com/people/xxx --no-videos

# 只补本地已有内容缺失的视频
python -m zhihu_backup user https://www.zhihu.com/people/xxx --videos_only

# 只处理 2024-01-01 之后的内容，最多 100 条
python -m zhihu_backup user https://www.zhihu.com/people/xxx --since 2024-01-01 --limit 100

# 只枚举数量，不下载
python -m zhihu_backup user https://www.zhihu.com/people/xxx --dry-run
```

> `--videos` **不是**“只下载 zvideo”。它包含默认的内容视频补全逻辑：先补齐回答/文章/想法里缺失的视频，再额外枚举用户的 zvideo 列表。首次升级后可能先补历史视频，之后运行会跳过已有视频。

### 备份单个或多个链接

```bash
# 回答
python -m zhihu_backup urls https://www.zhihu.com/question/1/answer/2

# 文章
python -m zhihu_backup urls https://zhuanlan.zhihu.com/p/123

# 想法（链接中的视频默认下载）
python -m zhihu_backup urls https://www.zhihu.com/pin/456

# zvideo（默认下载视频）
python -m zhihu_backup urls https://www.zhihu.com/zvideo/<id>

# 多个链接 / 从文件读取（每行一个）
python -m zhihu_backup urls <url1> <url2> --file urls.txt

# 生成 PDF
python -m zhihu_backup urls <url> --pdf

# 只补某个已备份链接缺失的视频
python -m zhihu_backup urls <url> --videos_only --video-quality hd
```

### 只备份用户资料

```bash
python -m zhihu_backup profile https://www.zhihu.com/people/xxx
```

如果传入的是回答/文章/想法链接，`profile` 会自动按 `urls` 模式保存该内容。

### 只生成 PDF

```bash
# 用户模式：从本地已保存的 content.md 生成，不访问网络、不需要 Cookie
python -m zhihu_backup user https://www.zhihu.com/people/xxx --pdf_only

# 链接模式：本地已有内容时直接使用；本地没有时只抓取生成 PDF 所需内容
python -m zhihu_backup urls <url> --pdf_only
```

已有 PDF 默认跳过，`--force` 可重新生成。

## 常用场景速查

| 场景 | 命令 |
|---|---|
| 首次登录 | `python -m zhihu_backup login` |
| 全量备份用户 | `python -m zhihu_backup user <profile_url>` |
| 全量备份 + zvideo | `python -m zhihu_backup user <profile_url> --videos` |
| 只补缺失视频 | `python -m zhihu_backup user <profile_url> --videos_only` |
| 只生成 PDF | `python -m zhihu_backup user <profile_url> --pdf_only` |
| 备份单条内容 | `python -m zhihu_backup urls <content_url>` |
| 只备份资料 | `python -m zhihu_backup profile <profile_url>` |
| 只统计数量 | `python -m zhihu_backup user <profile_url> --dry-run --json` |
| 内容更新后重下 | `python -m zhihu_backup user <profile_url> --update` |
| 强制重下 | `python -m zhihu_backup user <profile_url> --force --limit 5` |

## 输出结构

```text
backup/                              # 默认输出目录，可用 --output 修改
├── logs/
│   ├── run_YYYYMMDD_HHMMSS.log
│   ├── full_backup.log
│   └── full_backup_summary.json
├── users/<url_token>/
│   ├── profile.json                 # 结构化资料
│   ├── profile.md                   # 人类可读资料页
│   ├── profile.raw.json             # API 原始返回
│   ├── avatar.jpg                   # 真实尺寸头像（xll）
│   ├── cover.jpg                    # 背景图（1440w）
│   ├── logos/                       # 公司/学校图标
│   │   ├── employment_1.png
│   │   └── education_1.png
│   ├── manifest.json                # 断点续传状态
│   ├── answers/<YYYYMMDD>-<id>-<标题>/
│   │   ├── content.md
│   │   ├── meta.json
│   │   ├── images/001.jpg ...
│   │   ├── videos/xxx.mp4           # 内容含视频时
│   │   └── content.pdf              # --pdf 时
│   ├── articles/...
│   ├── pins/...
│   └── zvideos/...                  # --videos 时
└── singles/
    ├── answers/...
    ├── articles/...
    ├── pins/...
    ├── zvideos/...
    └── manifest.json
```

### content.md

头部包含标题、作者、原文链接、发布时间、编辑时间（有修改时），以及统计信息：

```text
赞同 19 · 收藏 14 · 喜欢 8 · 评论 2
```

回答还会附带问题正文（`--no-question-body` 可关闭）。正文末尾如有下载的视频，会生成：

```markdown
## 视频

[视频](videos/10404....mp4)
```

### profile.json

| 字段 | 含义 |
|---|---|
| `name` / `headline` | 昵称 / 一句话简介 |
| `description` | 个人简介 |
| `industry` | 所在行业 |
| `employments` | 职业经历（公司、职位、图标 URL/本地文件） |
| `educations` | 教育经历（学校、专业、图标 URL/本地文件） |
| `locations` / `ip_location` | 所在地 / IP 属地 |
| `avatar_url` / `avatar_file` | 真实尺寸头像链接 / 本地文件 |
| `cover_url` / `cover_file` | 背景图链接 / 本地文件 |
| `answer_count` 等 | 回答、文章、想法、关注者、关注数 |

### meta.json 与 manifest.json

`meta.json` 记录单条内容的类型、ID、URL、标题、作者、创建/编辑时间、统计数、来源（`api`/`selenium`）及视频等附加信息。

`manifest.json` 以 `<type>:<id>` 为键记录备份状态：

```json
{
  "type": "pin",
  "id": "1449482128384294913",
  "status": "ok",
  "dir": "pins/20211201-...",
  "updated": 1638363469,
  "saved_at": "2026-10-18T04:03:32",
  "files": ["content.md", "meta.json", "images/", "videos/"],
  "error": ""
}
```

## 命令行参数

### 子命令

| 子命令 | 作用 |
|---|---|
| `login` | 打开 Edge 人工登录并保存 Cookie |
| `profile <url>` | 只备份用户资料；传入内容链接时按 `urls` 处理 |
| `user <url>` | 备份用户资料与全部回答/文章/想法 |
| `urls <url...>` | 备份指定的一个或多个内容链接 |

### 公共参数

| 参数 | 说明 |
|---|---|
| `--output DIR` | 输出目录，默认 `./backup` |
| `--state-dir DIR` | Cookie/状态目录，默认 `./.zhihu_backup` |
| `--sleep N` | 请求间隔秒数，默认 1.5 |
| `--pdf` | 额外生成 PDF（默认关闭） |
| `--pdf_only` / `--pdf-only` | 只生成 PDF，不重新下载内容 |
| `--videos` | 额外枚举用户的 zvideo 列表（内容视频默认已下载） |
| `--no-videos` | 不下载任何视频 |
| `--videos_only` / `--videos-only` | 只补已有内容缺失的视频，不新建内容 |
| `--video-quality` | 视频清晰度：`best`（默认）/ `hd` / `sd` / `ld` |
| `--no-images` | 不下载图片，保留远程链接 |
| `--no-question-body` | 回答不额外抓取问题描述 |
| `--limit N` | 最多处理 N 条 |
| `--since DATE` | 只处理该日期之后的内容 |
| `--force` | 忽略 manifest 强制重下 |
| `--update` | 内容更新时间变新时重下 |
| `--dry-run` | 只枚举，不下载 |
| `--json` | 输出 JSON 汇总 |
| `--cookie` / `--cookie-file` | 直接提供 Cookie，适合无浏览器环境 |
| `--driver PATH` | 手动指定 msedgedriver 路径 |

### 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 全部成功 |
| `1` | 部分失败（单条失败不影响其他条目） |
| `2` | 认证或配置错误 |

## 工作方式

1. **登录**：Selenium 打开 Edge 完成登录，Cookie 以 JSON 保存，不写入日志。
2. **取数据**：requests 复用 Cookie，优先调用知乎 v4 API：
   - `/api/v4/members/{token}` 获取资料；
   - `/api/v4/members/{token}/answers|articles|pins` 枚举内容；
   - `/api/v4/answers|articles|pins/{id}` 获取单条详情；
   - `/api/v4/zvideos/{id}` 获取视频详情。
3. **自动兜底**：API 出现 403/429、非 JSON、登录墙或正文缺失时，回退 Selenium 打开页面，用 DOM 选择器解析。单篇文章 API 返回 403 是常见情况，属于正常回退，`--verbose` 可见日志。
4. **转换**：HTML 转 Markdown（公式、代码块、链接解包、图片下载本地化），图片请求携带 `Referer`/UA/Cookie。
5. **落盘**：每篇内容一个目录，写入 `content.md`、`meta.json`、图片/视频，并立即更新 manifest，中断后可续传。

默认单线程并设置请求间隔，请勿把 `--sleep` 调得过低。

## 增量备份、续传与去重

- 每条内容完成后立即写入 `manifest.json`；`status=ok` 且 `content.md` 存在时跳过。
- 每次处理前还会扫描本地目录：同一用户下已存在的内容直接跳过；`urls` 模式会检查整个输出目录（`users/` + `singles/`），已备份链接不重复下载。
- `--force` 忽略已有内容；`--update` 仅在内容编辑时间变新时重下；失败条目默认重试。
- 知乎列表接口可能重复返回同一条内容（例如置顶内容再次出现在时间线中），工具按内容 ID 去重，`--dry-run` 显示的是去重后的唯一数量。
- 本地已有条目若缺少视频，普通 `user` 重跑会自动补下视频，其余内容跳过。

## 视频

| 场景 | 行为 |
|---|---|
| `user <url>` | 下载回答/文章/想法里的视频；不枚举 zvideo |
| `user <url> --videos` | 内容视频补全 + 枚举用户 zvideo 列表 |
| `user <url> --no-videos` | 不下载任何视频 |
| `user <url> --videos_only` | 只补本地已有但缺视频的条目 |
| `urls <content>` | 默认下载链接内容里的视频 |
| `urls <zvideo>` | 默认下载该 zvideo |
| `urls <content> --videos_only` | 只补本地已存在链接缺失的视频，不新建 |

实现要点：

- 直链 MP4 流式下载，支持 Range 续传与 `ftyp` 文件头校验。
- HLS/DASH（m3u8/mpd）调用本机 ffmpeg 合并，可用 `FFMPEG_PATH` 指定路径。
- 知乎视频为签名 URL，会过期；正常备份在获取后立即下载，`--videos_only` 会重新请求详情获取新签名。
- 回答/文章内嵌视频通过 `a.video-box[data-lens-id]` 识别，打开原页面读取渲染后的 `<video src>` 下载；只有含视频的条目才会打开浏览器，普通内容不受影响。
- zvideo 列表项不含清晰度信息，工具会逐条请求详情；失败时回退页面 `js-initialData` 或 DOM。
- 视频下载失败不会导致整条内容失败，会记录 `video_error` 并给出警告。
- 极老的已删除视频源可能返回 404，无法恢复。

## PDF

- `--pdf`：正常备份时额外打印页面 PDF。
- `--pdf_only`：只从本地已保存内容生成，不重新下载。
- 打印前等待 SPA 正文渲染，清理广告、评论区、操作栏、推荐区与页脚；不会误删正文中正常出现的“广告”字样。
- 打印后校验 PDF 头与大小，并用 pypdf 检查前几页是否仍是知乎错误页；异常时自动改用已保存正文与本地图片生成干净 PDF。
- PDF 不嵌入视频，只保留封面和本地 `[视频](videos/...)` 链接。
- PDF 体积可能较大（长文可达几十 MB）。

## 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试覆盖 URL 识别、文件名清洗、manifest/续传、Markdown 转换、想法视频结构、清晰度选择、MP4 下载、zvideo 解析、PDF 内容版、CLI 参数与去重等，共 83 项。

## 常见问题

**提示需要登录 / Cookie 失效**

```bash
python -m zhihu_backup login
```

**API 返回 403**

知乎 API 可能需要额外签名，工具会自动回退 Selenium，速度会慢一些。单篇文章接口 403 属于正常回退，不是备份失败；加 `--verbose` 可查看回退日志。可适当增大 `--sleep`。

**Edge 驱动问题**

优先使用 Selenium Manager 自动下载驱动。若失败，下载与 Edge 版本匹配的 `msedgedriver.exe`：

```bash
python -m zhihu_backup user xxx --driver path/to/msedgedriver.exe
```

**PDF 生成失败**

页面过大时浏览器打印可能失败，Markdown 仍会保留。可减少图片数量或关闭 `--pdf`；工具会自动尝试本地正文版 PDF。如仍有问题，可附页面 URL 与截图反馈。

**只想快速备份文字**

```bash
python -m zhihu_backup user xxx --no-images
```

**`--videos` 为什么先处理了很多回答/文章？**

`--videos` 包含默认的内容视频补全逻辑。首次升级后会把历史回答/文章/想法里缺失的视频补齐，之后再次运行会跳过已有视频。

**备份体积很大怎么办？**

视频是主要体积来源。可用 `--no-videos` 关闭，或用 `--video-quality hd/sd/ld` 限制清晰度。不要随意 `--force` 全量重跑。

## 致谢与许可

本项目的部分实现参考或改编自以下开源项目：

| 项目 | 许可证 | 用途 |
|---|---|---|
| [zhihu_spider_selenium-master](https://github.com/ZouJiu1/zhihu_spider_selenium) | GPL-3.0 | 基础：Selenium 登录、Cookie、DOM 兜底、PDF 打印 |
| [zhihu-download-main](https://github.com/chenluda/zhihu-download) | 上游快照未附许可证文件 | HTML → Markdown 管线 |
| [ZhihuSpider-master](https://github.com/Foxgeek36/ZhihuSpider) | 上游快照未附许可证文件 | 知乎 v4 API 端点与内容枚举思路 |
| [cat-catch](https://github.com/xifangczy/cat-catch) | GPL-3.0 | 视频识别、清晰度排序、Range/断点续传设计参考 |

- `zhihu_spider_selenium-master` 与 `cat-catch` 以 GPL-3.0 发布。本项目包含基于前者的实现，因此整体同样以 **GPL-3.0** 发布，完整条款见 [LICENSE](LICENSE)。
- `zhihu-download-main` 与 `ZhihuSpider-master` 的上游快照中没有 LICENSE 文件，相关权利归原作者所有；本项目保留出处说明。
- 对 cat-catch，仅借鉴资源识别、请求头传递、清晰度排序与断点续传设计，未移植其浏览器扩展代码、hls.js/mpd-parser/mux.js 或任何 DRM 相关实现。

## 免责声明

本工具仅用于备份本人或已获授权的内容。请遵守知乎服务条款，控制请求频率，不要用于批量抓取他人内容或任何侵权用途。因使用本工具产生的一切后果由使用者自行承担。
