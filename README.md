# Zhihu Backup (zhihu-backup)

English | [中文](README.zh.md)

Back up a Zhihu user's **answers, articles and pins** to local Markdown, together with their profile: avatar, cover image, headline, bio, industry, employment/education history and IP location. Embedded videos, zvideos and optional PDF export are supported.

Output is `Markdown + local images + meta.json`, one directory per item. Downloads are resumable, items are deduplicated by content ID, and a stable CLI with `--json` output makes it easy to call from scripts or a GUI.

> Use this tool only to back up content you own or are authorized to archive, and respect Zhihu's terms of service. Cookies are sensitive and are never written to logs.

---

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Login](#login)
- [Quick start](#quick-start)
- [Common recipes](#common-recipes)
- [Output layout](#output-layout)
- [CLI reference](#cli-reference)
- [How it works](#how-it-works)
- [Incremental backup, resume and deduplication](#incremental-backup-resume-and-deduplication)
- [Videos](#videos)
- [PDF](#pdf)
- [Testing](#testing)
- [FAQ](#faq)
- [Credits and license](#credits-and-license)

---

## Features

- Back up all answers, articles and pins of a given user.
- Back up individual or multiple answer, article, pin and zvideo links, or read links from a file.
- Save nickname, full-size avatar, cover image, headline, bio, industry, employment/education history, IP location and profile URL.
- Avatars are upgraded to the `xll` size and covers to `1440w`; thumbnails are never saved.
- Company/school logos are saved under `logos/`; an industry icon is saved only when the page actually displays one, never the generic topic placeholder.
- Answer/article Markdown includes publish time, edit time, and upvote/favorite/like/comment counts.
- Videos inside answers, articles and pins are downloaded by default. `--videos` additionally enumerates the user's zvideo list; `--no-videos` disables all video downloads.
- Resumable downloads, retries, incremental updates (`--update`) and automatic deduplication by content ID.
- Markdown formulas, code blocks, link unwrapping and local image downloads.
- Optional PDF export via Selenium printing, with ads/comments/action bars removed; when the page itself is broken, a clean PDF is rebuilt from the saved content.
- Stable CLI, `--json` summary and meaningful exit codes, suitable for later use from a C/C++ GUI as a subprocess.

## Requirements

| Dependency | Notes |
|---|---|
| Python | 3.9+ (validated on 3.14) |
| Microsoft Edge | Login, DOM fallback, PDF printing |
| ffmpeg | **Optional**; only needed for HLS/DASH (m3u8/mpd) videos. Direct MP4 downloads do not need it. |

Selenium Manager resolves the driver automatically. If that fails, pass `--driver` with the path to `msedgedriver.exe`.

## Installation

```bash
cd zhihu-backup
python -m pip install -r requirements.txt
```

Or install it as a command:

```bash
python -m pip install -e .
zhihu-backup --help
```

Development dependencies (pytest):

```bash
python -m pip install -r requirements-dev.txt
```

## Login

The first run opens a browser for manual login:

```bash
python -m zhihu_backup login
```

Cookies are saved to `.zhihu_backup/cookies.json` and reused afterwards. If they expire, delete the file or run `login` again.

For headless environments you can pass cookies directly:

```bash
python -m zhihu_backup user <token> --cookie "z_c0=..."
python -m zhihu_backup user <token> --cookie-file cookies.txt
```

## Quick start

### Back up all content of a user

```bash
# Answers, articles and pins are backed up; embedded videos are downloaded too
python -m zhihu_backup user https://www.zhihu.com/people/xxx
```

Common variants:

```bash
# Also generate PDFs
python -m zhihu_backup user https://www.zhihu.com/people/xxx --pdf

# Additionally enumerate and download the user's zvideo list
python -m zhihu_backup user https://www.zhihu.com/people/xxx --videos

# Do not download any video
python -m zhihu_backup user https://www.zhihu.com/people/xxx --no-videos

# Only fill in missing videos for items already backed up locally
python -m zhihu_backup user https://www.zhihu.com/people/xxx --videos_only

# Only content published after 2024-01-01, at most 100 items
python -m zhihu_backup user https://www.zhihu.com/people/xxx --since 2024-01-01 --limit 100

# Count items without downloading anything
python -m zhihu_backup user https://www.zhihu.com/people/xxx --dry-run
```

> `--videos` is **not** "zvideos only". It includes the default content-video pass: first it fills in missing videos for answers/articles/pins, then it enumerates the user's zvideos. After the first upgrade run, later runs skip videos that already exist.

### Back up one or more links

```bash
# Answer
python -m zhihu_backup urls https://www.zhihu.com/question/1/answer/2

# Article
python -m zhihu_backup urls https://zhuanlan.zhihu.com/p/123

# Pin (videos in the pin are downloaded by default)
python -m zhihu_backup urls https://www.zhihu.com/pin/456

# zvideo (video is downloaded by default)
python -m zhihu_backup urls https://www.zhihu.com/zvideo/<id>

# Multiple links / read from a file (one URL per line)
python -m zhihu_backup urls <url1> <url2> --file urls.txt

# Generate a PDF
python -m zhihu_backup urls <url> --pdf

# Only fill in missing videos for an already-backed-up link
python -m zhihu_backup urls <url> --videos_only --video-quality hd
```

### Back up the profile only

```bash
python -m zhihu_backup profile https://www.zhihu.com/people/xxx
```

If the supplied URL is an answer/article/pin link, `profile` automatically falls back to `urls` mode and saves that item.

### PDF only

```bash
# User mode: build PDFs from locally saved content.md; no network or cookie needed
python -m zhihu_backup user https://www.zhihu.com/people/xxx --pdf_only

# URL mode: use local content when available; otherwise fetch only what is needed for the PDF
python -m zhihu_backup urls <url> --pdf_only
```

Existing PDFs are skipped by default; use `--force` to regenerate them.

## Common recipes

| Task | Command |
|---|---|
| First login | `python -m zhihu_backup login` |
| Full user backup | `python -m zhihu_backup user <profile_url>` |
| Full backup + zvideos | `python -m zhihu_backup user <profile_url> --videos` |
| Fill missing videos only | `python -m zhihu_backup user <profile_url> --videos_only` |
| Generate PDFs only | `python -m zhihu_backup user <profile_url> --pdf_only` |
| Back up a single item | `python -m zhihu_backup urls <content_url>` |
| Profile only | `python -m zhihu_backup profile <profile_url>` |
| Count items only | `python -m zhihu_backup user <profile_url> --dry-run --json` |
| Re-download updated items | `python -m zhihu_backup user <profile_url> --update` |
| Force re-download | `python -m zhihu_backup user <profile_url> --force --limit 5` |

## Output layout

```text
backup/                              # default; change with --output
├── logs/
│   ├── run_YYYYMMDD_HHMMSS.log
│   ├── full_backup.log
│   └── full_backup_summary.json
├── users/<url_token>/
│   ├── profile.json                 # structured profile
│   ├── profile.md                   # human-readable profile
│   ├── profile.raw.json             # raw API response
│   ├── avatar.jpg                   # full-size avatar (xll)
│   ├── cover.jpg                    # cover image (1440w)
│   ├── logos/                       # company/school logos
│   │   ├── employment_1.png
│   │   └── education_1.png
│   ├── manifest.json                # resume state
│   ├── answers/<YYYYMMDD>-<id>-<title>/
│   │   ├── content.md
│   │   ├── meta.json
│   │   ├── images/001.jpg ...
│   │   ├── videos/xxx.mp4           # when the item contains video
│   │   └── content.pdf              # with --pdf
│   ├── articles/...
│   ├── pins/...
│   └── zvideos/...                  # with --videos
└── singles/
    ├── answers/...
    ├── articles/...
    ├── pins/...
    ├── zvideos/...
    └── manifest.json
```

### content.md

The header contains the title, author, source URL, publish time, edit time (when modified), and statistics:

```text
Upvotes 19 · Favorites 14 · Likes 8 · Comments 2
```

Answers also include the question body (disable with `--no-question-body`). When videos were downloaded, the end of the file contains:

```markdown
## Videos

[Video](videos/10404....mp4)
```

### profile.json

| Field | Meaning |
|---|---|
| `name` / `headline` | Nickname / one-line bio |
| `description` | Full bio |
| `industry` | Industry |
| `employments` | Employment history (company, title, logo URL/local file) |
| `educations` | Education history (school, major, logo URL/local file) |
| `locations` / `ip_location` | Location / IP location |
| `avatar_url` / `avatar_file` | Full-size avatar URL / local file |
| `cover_url` / `cover_file` | Cover image URL / local file |
| `answer_count` etc. | Answer, article, pin, follower and following counts |

### meta.json and manifest.json

`meta.json` records the type, ID, URL, title, author, publish/edit times, statistics, source (`api`/`selenium`) and extra data such as video information.

`manifest.json` is keyed by `<type>:<id>` and tracks backup state:

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

## CLI reference

### Subcommands

| Subcommand | Purpose |
|---|---|
| `login` | Open Edge for manual login and save cookies |
| `profile <url>` | Back up the profile only; content links are handled as `urls` |
| `user <url>` | Back up the profile and all answers/articles/pins |
| `urls <url...>` | Back up one or more specific content links |

### Common options

| Option | Description |
|---|---|
| `--output DIR` | Output directory, default `./backup` |
| `--state-dir DIR` | Cookie/state directory, default `./.zhihu_backup` |
| `--sleep N` | Delay between requests in seconds, default 1.5 |
| `--pdf` | Also generate PDFs (off by default) |
| `--pdf_only` / `--pdf-only` | Generate PDFs only; do not re-download content |
| `--videos` | Additionally enumerate the user's zvideo list (embedded videos are already downloaded) |
| `--no-videos` | Do not download any video |
| `--videos_only` / `--videos-only` | Only fill in missing videos for existing items; never create new items |
| `--video-quality` | Video quality: `best` (default) / `hd` / `sd` / `ld` |
| `--no-images` | Do not download images; keep remote URLs |
| `--no-question-body` | Do not fetch the question body for answers |
| `--limit N` | Process at most N items |
| `--since DATE` | Only process content published after this date |
| `--force` | Ignore the manifest and re-download |
| `--update` | Re-download when the edit time is newer |
| `--dry-run` | Enumerate only; download nothing |
| `--json` | Emit a JSON summary |
| `--cookie` / `--cookie-file` | Supply cookies directly (headless environments) |
| `--driver PATH` | Path to `msedgedriver` |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All succeeded |
| `1` | Partial failure (one item failing does not stop the rest) |
| `2` | Authentication or configuration error |

## How it works

1. **Login**: Selenium drives Edge for manual login and saves cookies as JSON. Cookies are never logged.
2. **Fetch**: requests reuses the cookies and prefers the Zhihu v4 API:
   - `/api/v4/members/{token}` for the profile;
   - `/api/v4/members/{token}/answers|articles|pins` for content enumeration;
   - `/api/v4/answers|articles|pins/{id}` for single items;
   - `/api/v4/zvideos/{id}` for video details.
3. **Fallback**: on 403/429, non-JSON responses, login walls or missing content fields, the tool falls back to Selenium and parses the DOM. A 403 on a single article is common and is a normal fallback; use `--verbose` to see it.
4. **Convert**: HTML to Markdown, including formulas, code blocks, link unwrapping and image localization. Image requests carry `Referer`/UA/cookies.
5. **Persist**: one directory per item with `content.md`, `meta.json`, images/videos, and an immediately updated manifest, so interrupted runs can resume.

Requests are single-threaded with a delay by default. Do not set `--sleep` too low.

## Incremental backup, resume and deduplication

- The manifest is updated after every item; items with `status=ok` and an existing `content.md` are skipped.
- Before processing, local directories are scanned too: content already present for the same user is skipped, and `urls` mode checks the whole output tree (`users/` + `singles/`) so a backed-up link is never downloaded twice.
- `--force` ignores existing content; `--update` re-downloads only when the edit time is newer; failed items are retried by default.
- The Zhihu list API can return the same item twice (for example, a pinned item appearing again in the timeline). The tool deduplicates by content ID; `--dry-run` reports unique counts.
- If an existing local item is missing videos, a normal `user` run reprocesses it to download the videos and skips everything else.

## Videos

| Scenario | Behavior |
|---|---|
| `user <url>` | Download videos inside answers/articles/pins; do not enumerate zvideos |
| `user <url> --videos` | Content-video pass + enumerate the user's zvideos |
| `user <url> --no-videos` | Download no videos at all |
| `user <url> --videos_only` | Only fill in missing videos for existing items |
| `urls <content>` | Download videos inside the linked content by default |
| `urls <zvideo>` | Download that zvideo by default |
| `urls <content> --videos_only` | Only fill in missing videos for an existing link; create nothing |

Implementation notes:

- Direct MP4 URLs are streamed to disk with Range resume and an `ftyp` header check.
- HLS/DASH (`m3u8`/`mpd`) is merged with the local ffmpeg; `FFMPEG_PATH` can override the binary.
- Zhihu video URLs are signed and expire. Normal backups download immediately after fetching; `--videos_only` requests fresh details to obtain a new signature.
- Embedded videos in answers/articles are detected via `a.video-box[data-lens-id]`; the original page is opened and the rendered `<video src>` is downloaded. Only items that actually contain video open a browser, so ordinary content is unaffected.
- zvideo list entries do not include quality information, so details are fetched per item; on failure the tool falls back to the page's `js-initialData` or DOM.
- A failed video does not fail the whole item; it is recorded as `video_error` with a warning.
- Very old, deleted video sources may return 404 and cannot be recovered.

## PDF

- `--pdf`: print a page PDF in addition to the normal backup.
- `--pdf_only`: build PDFs from locally saved content without re-downloading.
- Before printing, the page waits for the SPA content to render and removes ads, comments, action bars, recommendations and the footer. Normal occurrences of the word "ad" in the body are not removed.
- After printing, the PDF header and size are validated, and pypdf checks the first pages for a Zhihu error page. On failure, a clean PDF is rebuilt from the saved content and local images.
- Videos are not embedded in PDFs; only the cover and a local `[Video](videos/...)` link are kept.
- PDFs can be large (tens of MB for long articles).

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The suite covers URL parsing, filename sanitization, manifest/resume behavior, Markdown conversion, pin video structures, quality selection, MP4 downloads, zvideo parsing, content-based PDFs, CLI options and deduplication: 83 tests.

## FAQ

**Login required / cookies expired**

```bash
python -m zhihu_backup login
```

**API returns 403**

Zhihu's API may require additional signatures. The tool falls back to Selenium automatically, which is slower. A 403 on a single article is a normal fallback, not a backup failure; add `--verbose` to see the logs. Consider increasing `--sleep`.

**Edge driver problems**

Selenium Manager is preferred. If it fails, download the `msedgedriver.exe` matching your Edge version:

```bash
python -m zhihu_backup user xxx --driver path/to/msedgedriver.exe
```

**PDF generation fails**

Very large pages can fail to print; the Markdown is still kept. Reduce the number of images or disable `--pdf`; the tool will also try the local-content PDF. If the problem persists, provide the page URL and a screenshot.

**I only want text quickly**

```bash
python -m zhihu_backup user xxx --no-images
```

**Why does `--videos` process many answers/articles first?**

`--videos` includes the default content-video pass. The first run after upgrading fills in missing videos for historical answers/articles/pins; later runs skip existing videos.

**The backup is huge. What can I do?**

Video is the main contributor. Use `--no-videos`, or limit quality with `--video-quality hd/sd/ld`. Avoid a full `--force` re-run.

## Credits and license

Parts of this project were developed with reference to, or adapted from, the following open-source projects:

| Project | License | Use |
|---|---|---|
| `zhihu_spider_selenium-master` | GPL-3.0 | Base: Selenium login, cookies, DOM fallback, PDF printing |
| [zhihu-download-main](https://github.com/chenluda/zhihu-download) | No license file in the upstream snapshot | HTML → Markdown pipeline |
| `ZhihuSpider-master` | No license file in the upstream snapshot | Zhihu v4 API endpoints and enumeration approach |
| [cat-catch](https://github.com/xifangczy/cat-catch) | GPL-3.0 | Video detection, quality ordering and Range/resume design reference |

- `zhihu_spider_selenium-master` and `cat-catch` are released under GPL-3.0. Because this project contains code derived from the former, the project as a whole is released under **GPL-3.0**; see [LICENSE](LICENSE) for the full terms.
- The upstream snapshots of `zhihu-download-main` and `ZhihuSpider-master` contain no LICENSE file; all rights remain with their original authors. Attribution is retained here.
- For cat-catch, only resource detection, header handling, quality ordering and resume design were referenced. No browser-extension code, hls.js/mpd-parser/mux.js or DRM-related implementation was ported.

## Disclaimer

This tool is intended only for backing up content you own or are authorized to archive. Respect Zhihu's terms of service, keep request rates reasonable, and do not use it for bulk scraping of other people's content or any infringing purpose. You are responsible for how you use this tool.
