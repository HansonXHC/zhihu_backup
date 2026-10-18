"""Orchestration for user backups and single-URL backups."""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote

from . import auth
from .api import ZhihuApi
from .browser import Browser
from .config import content_dir_name, now_iso, timestamp_to_date
from .errors import AuthError, EnumerationError, ParseError, ZhihuBackupError
from .extractors import answer as answer_ext
from .extractors import article as article_ext
from .extractors import pin as pin_ext
from .extractors import profile as profile_ext
from .extractors import zvideo as zvideo_ext
from .http_client import HttpClient
from .images import ImageDownloader
from .markdown import HtmlToMarkdown, soup_of
from .models import ContentItem, Target, UserProfile
from .pdf import print_item_pdf, print_markdown_pdf
from .videos import VideoDownloader
from .storage import Manifest, Storage, atomic_write_json, read_json
from .urls import parse_target

logger = logging.getLogger(__name__)

KIND_DIR = {
    "answer": "answers",
    "article": "articles",
    "pin": "pins",
    "zvideo": "zvideos",
}

PLURAL_TO_KIND = {
    "answers": "answer",
    "articles": "article",
    "pins": "pin",
    "zvideos": "zvideo",
}

LIST_SELECTOR = {
    "answers": ".AnswerItem",
    "articles": ".ArticleItem",
    "pins": ".PinItem",
}

DETAIL_WAIT_SELECTOR = {
    "answer": ".AnswerItem, .RichContent-inner",
    "article": ".Post-Title, .Post-RichTextContainer",
    "pin": ".RichContent-inner, .PinItem",
    "zvideo": "h1, .ZVideo-video",
}


@dataclass
class RunStats:
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "failed": self.failed,
            "total": self.total,
            "errors": self.errors,
        }


class Runner:
    def __init__(self, args):
        self.args = args
        self.storage = Storage(Path(args.output))
        self.stats = RunStats()
        self.since_ts = int(getattr(args, "since_ts", 0) or 0)
        self.limit = int(getattr(args, "limit", 0) or 0)
        self._cookies = None
        self.http: Optional[HttpClient] = None
        self.api: Optional[ZhihuApi] = None
        self._browser: Optional[Browser] = None
        self._pdf_browser: Optional[Browser] = None
        self._question_cache: Dict[str, str] = {}
        self._logo_cache: Dict[str, tuple] = {}
        self.pdf_only = bool(getattr(args, "pdf_only", False))
        self.download_videos = not bool(getattr(args, "no_videos", False))
        self.include_zvideos = bool(getattr(args, "videos", False)) and self.download_videos
        self.videos_only = bool(getattr(args, "videos_only", False))
        self.video_quality = str(getattr(args, "video_quality", "best") or "best")
        self.force = bool(getattr(args, "force", False))
        self._content_index_cache: Optional[Dict[tuple, Path]] = None

    # ------------------------------------------------------------- lifecycle
    def ensure_api(self) -> ZhihuApi:
        if self.api is None:
            self._cookies = auth.get_cookies(self.args)
            self.http = HttpClient(cookies=self._cookies, sleep=self.args.sleep)
            self.api = ZhihuApi(self.http)
        return self.api

    def ensure_browser(self) -> Browser:
        if self._browser is None:
            if self._cookies is None:
                self._cookies = auth.get_cookies(self.args)
            self._browser = Browser(driver_path=getattr(self.args, "driver", None))
            self._browser.get("https://www.zhihu.com/")
            auth.apply_cookies_to_driver(self._browser.driver, self._cookies)
        return self._browser

    def ensure_pdf_browser(self) -> Browser:
        """A browser for printing local HTML; no Zhihu cookies or page loads."""
        if self._pdf_browser is None:
            self._pdf_browser = Browser(driver_path=getattr(self.args, "driver", None))
        return self._pdf_browser

    def _content_index(self) -> Dict[tuple, Path]:
        if self._content_index_cache is None:
            self._content_index_cache = self.storage.build_content_index()
        return self._content_index_cache

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pdf_browser is not None:
            self._pdf_browser.close()
            self._pdf_browser = None

    def summary(self) -> Dict[str, Any]:
        data = self.stats.to_dict()
        data["output"] = str(self.storage.output)
        return data

    # --------------------------------------------------------------- profile
    def fetch_profile(self, url_token: str) -> UserProfile:
        api = self.ensure_api()
        try:
            raw = api.user_profile(url_token)
            profile = profile_ext.from_api(raw, url_token)
            if profile.name:
                return profile
            logger.debug("API 返回的用户资料缺少昵称，改用浏览器解析。")
        except AuthError:
            logger.debug("用户资料接口返回 403，改用浏览器解析。")
        except Exception as exc:
            logger.debug("API 获取用户资料失败，改用浏览器解析：%s", exc)

        browser = self.ensure_browser()
        browser.get(
            f"https://www.zhihu.com/people/{url_token}",
            wait_css=".ProfileHeader, .ProfileHeader-name, .ProfileHeader-headline",
            wait_timeout=20,
        )
        browser.check_login()
        browser.scroll(times=3, pause=0.3)
        profile = profile_ext.from_dom(browser.html, url_token)
        if not profile.name and not profile.headline:
            raise AuthError(
                "无法读取用户资料。请确认 Cookie 有效，且该用户主页可访问。"
            )
        return profile

    def save_profile(self, profile: UserProfile) -> Path:
        user_dir = self.storage.user_dir(profile.url_token)
        user_dir.mkdir(parents=True, exist_ok=True)

        profile.avatar_file = self._save_avatar(user_dir, profile) or ""
        profile.cover_file = self._save_cover(user_dir, profile) or ""
        if not profile.industry_logo_url:
            profile.industry_logo = ""
            for stale in (user_dir / "logos").glob("industry.*"):
                try:
                    stale.unlink()
                except OSError:
                    pass
        if profile.industry_logo_url:
            profile.industry_logo = (
                self._save_remote_image(
                    profile.industry_logo_url, user_dir, "industry", profile.url
                )
                or ""
            )
        for index, entry in enumerate(profile.employments, start=1):
            logo_url = entry.get("logo_url")
            if logo_url:
                entry["logo_file"] = (
                    self._save_remote_image(
                        logo_url, user_dir, f"employment_{index}", profile.url
                    )
                    or ""
                )
        for index, entry in enumerate(profile.educations, start=1):
            logo_url = entry.get("logo_url")
            if logo_url:
                entry["logo_file"] = (
                    self._save_remote_image(
                        logo_url, user_dir, f"education_{index}", profile.url
                    )
                    or ""
                )

        atomic_write_json(user_dir / "profile.json", profile.to_dict())
        atomic_write_json(user_dir / "profile.raw.json", profile.raw or profile.to_dict())
        (user_dir / "profile.md").write_text(
            profile_ext.render_markdown(profile), encoding="utf-8"
        )

        if profile.avatar_file:
            logger.info("已保存头像：%s", user_dir / profile.avatar_file)
        logger.info(
            "用户资料：%s（%s）｜行业：%s｜职业经历：%d｜教育经历：%d｜简介：%s",
            profile.name,
            profile.url_token,
            profile.industry or "(空)",
            len(profile.employments),
            len(profile.educations),
            profile.description or "(空)",
        )
        return user_dir

    def _save_avatar(self, user_dir: Path, profile: UserProfile) -> Optional[str]:
        if not profile.avatar_url:
            return None
        return self._save_root_image(profile.avatar_url, user_dir, "avatar", profile.url)

    def _save_cover(self, user_dir: Path, profile: UserProfile) -> Optional[str]:
        if not profile.cover_url:
            return None
        return self._save_root_image(profile.cover_url, user_dir, "cover", profile.url)

    def _save_root_image(
        self, url: str, user_dir: Path, stem: str, referer: str
    ) -> Optional[str]:
        if not url or self.http is None:
            return None
        try:
            response = self.http.get_bytes(url, referer=referer)
            if response.status_code != 200 or not response.content:
                return None
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            extension = {
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/svg+xml": ".svg",
            }.get(content_type)
            if not extension:
                clean = url.split("?", 1)[0].lower()
                for value in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                    if clean.endswith(value):
                        extension = ".jpg" if value == ".jpeg" else value
                        break
            extension = extension or ".jpg"
            path = user_dir / f"{stem}{extension}"
            with open(path, "wb") as handle:
                handle.write(response.content)
            return path.name
        except Exception as exc:
            logger.warning("图片下载失败：%s（%s）", url, exc)
            return None

    def _save_remote_image(
        self, url: str, user_dir: Path, stem: str, referer: str
    ) -> Optional[str]:
        """Download a company/school/industry logo to <user>/logos/."""
        if not url or self.http is None:
            return None
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url

        if url in self._logo_cache:
            data, extension = self._logo_cache[url]
        else:
            try:
                response = self.http.get_bytes(url, referer=referer)
                if response.status_code != 200 or not response.content:
                    return None
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
                if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
                    logger.warning("图标地址返回了非图片内容（%s）：%s", content_type, url)
                    return None
                extension = {
                    "image/jpeg": ".jpg",
                    "image/jpg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                    "image/svg+xml": ".svg",
                }.get(content_type)
                if not extension:
                    clean = url.split("?", 1)[0].lower()
                    for value in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                        if clean.endswith(value):
                            extension = ".jpg" if value == ".jpeg" else value
                            break
                extension = extension or ".jpg"
                data = response.content
                self._logo_cache[url] = (data, extension)
            except Exception as exc:
                logger.warning("图标下载失败：%s（%s）", url, exc)
                return None

        logos_dir = user_dir / "logos"
        logos_dir.mkdir(parents=True, exist_ok=True)
        path = logos_dir / f"{stem}{extension}"
        with open(path, "wb") as handle:
            handle.write(data)
        return f"logos/{path.name}"

    def backup_profile(self, url_token: str) -> Dict[str, Any]:
        profile = self.fetch_profile(url_token)
        self.save_profile(profile)
        self.stats.total = 1
        self.stats.ok = 1
        result = self.summary()
        result["profile"] = profile.to_dict()
        return result

    # ------------------------------------------------------------ user backup
    def backup_user(self, url_token: str, kinds: Iterable[str], dry_run: bool = False) -> Dict[str, Any]:
        if self.pdf_only:
            return self._backup_user_pdfs(url_token, kinds)
        profile = self.fetch_profile(url_token)
        logger.info("开始备份用户：%s（%s）", profile.name, url_token)

        if dry_run:
            counts = {}
            for kind in kinds:
                counts[kind] = self._count_user_items(url_token, kind, profile)
            result = self.summary()
            result.update({"dry_run": True, "user": profile.to_dict(), "counts": counts})
            return result

        user_dir = self.save_profile(profile)
        manifest = Manifest(user_dir)
        for kind in kinds:
            self._backup_user_kind(url_token, kind, profile, user_dir, manifest)

        result = self.summary()
        result["user"] = profile.to_dict()
        return result

    def _generate_markdown_pdf(self, item_dir: Path, pdf_path: Path) -> bool:
        try:
            ok = print_markdown_pdf(
                self.ensure_pdf_browser(),
                Path(item_dir) / "content.md",
                Path(pdf_path),
                Path(item_dir),
            )
            if ok:
                logger.info("已生成 PDF：%s", pdf_path)
            return ok
        except Exception as exc:
            logger.warning("PDF 生成失败：%s（%s）", pdf_path, exc)
            return False

    def _backup_user_pdfs(self, url_token: str, kinds: Iterable[str]) -> Dict[str, Any]:
        user_dir = self.storage.user_dir(url_token)
        if not user_dir.is_dir():
            raise ZhihuBackupError(
                f"本地没有用户 {url_token} 的备份内容，请先运行 user 备份。"
            )
        force = bool(getattr(self.args, "force", False))
        processed = 0

        for kind in kinds:
            dir_name = KIND_DIR.get(PLURAL_TO_KIND.get(kind, ""), kind)
            kind_dir = user_dir / dir_name
            if not kind_dir.is_dir():
                continue
            for item_dir in sorted(path for path in kind_dir.iterdir() if path.is_dir()):
                if not (item_dir / "content.md").exists():
                    continue
                if self.limit and processed >= self.limit:
                    break
                pdf_path = item_dir / "content.pdf"
                if pdf_path.exists() and not force:
                    self.stats.skipped += 1
                    processed += 1
                    continue
                self.stats.total += 1
                if self._generate_markdown_pdf(item_dir, pdf_path):
                    self.stats.ok += 1
                else:
                    self.stats.failed += 1
                    self.stats.errors.append(
                        {"url": str(item_dir), "error": "PDF 生成失败"}
                    )
                processed += 1
            if self.limit and processed >= self.limit:
                break

        result = self.summary()
        result["pdf_only"] = True
        result["user"] = {"url_token": url_token}
        return result

    def _backup_url_pdfs(self, values: Iterable[str]) -> Dict[str, Any]:
        targets: List[Target] = []
        seen: set[tuple] = set()
        for value in values:
            target = parse_target(value)
            if target is None:
                self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append({"url": value, "error": "无法识别的知乎链接"})
                logger.error("无法识别的知乎链接：%s", value)
                continue
            key = (target.type, target.id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(target)

        index = self._content_index()
        force = bool(getattr(self.args, "force", False))
        processed = 0

        for target in targets:
            if self.limit and processed >= self.limit:
                break
            dir_name = KIND_DIR.get(target.type, target.type + "s")
            existing_dir = index.get((dir_name, target.id))

            if existing_dir is not None and (existing_dir / "content.md").exists():
                pdf_path = existing_dir / "content.pdf"
                if pdf_path.exists() and not force:
                    self.stats.skipped += 1
                    processed += 1
                    continue
                self.stats.total += 1
                if self._generate_markdown_pdf(existing_dir, pdf_path):
                    self.stats.ok += 1
                else:
                    self.stats.failed += 1
                    self.stats.errors.append(
                        {"url": target.url, "error": "PDF 生成失败"}
                    )
                processed += 1
                continue

            try:
                item = self._fetch_item_by_target(target)
            except AuthError:
                raise
            except Exception as exc:
                logger.error("获取内容失败 %s：%s", target.url, exc)
                self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append({"url": target.url, "error": str(exc)})
                processed += 1
                continue

            item_dir = (
                self.storage.singles_dir()
                / dir_name
                / content_dir_name(item.created, item.id, item.title)
            )
            item_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = item_dir / "content.pdf"
            if pdf_path.exists() and not force:
                self.stats.skipped += 1
                processed += 1
                continue
            self.stats.total += 1
            if print_item_pdf(
                self.ensure_browser(),
                item,
                pdf_path,
                item_dir=item_dir,
                image_map={},
            ):
                self.stats.ok += 1
            else:
                self.stats.failed += 1
                self.stats.errors.append(
                    {"url": target.url, "error": "PDF 生成失败"}
                )
            processed += 1

        result = self.summary()
        result["pdf_only"] = True
        result["singles"] = len(targets)
        return result

    @staticmethod
    def _meta_has_video(meta: Dict[str, Any]) -> bool:
        extra = meta.get("extra") or {}
        parts = extra.get("parts") or []
        if any(
            isinstance(part, dict) and part.get("type") == "video" for part in parts
        ):
            return True
        video = extra.get("video")
        return isinstance(video, dict) and bool(
            video.get("playlist") or video.get("variants") or video.get("url")
        )

    @staticmethod
    def _has_video_files(item_dir: Path) -> bool:
        directory = Path(item_dir) / "videos"
        if not directory.is_dir():
            return False
        return any(path.is_file() and path.stat().st_size > 0 for path in directory.iterdir())

    def _item_needs_video(
        self, item: ContentItem, item_dir: Optional[Path]
    ) -> bool:
        if item_dir is None or not self.download_videos:
            return False
        if not Path(item_dir).is_dir() or self._has_video_files(item_dir):
            return False
        if item.type == "pin":
            return any(
                isinstance(part, dict) and part.get("type") == "video"
                for part in (item.extra.get("parts") or [])
            )
        if item.type == "zvideo":
            video = item.extra.get("video") or {}
            return isinstance(video, dict) and bool(
                video.get("variants") or video.get("playlist") or video.get("url")
            )
        if item.type in ("answer", "article"):
            return bool(self._embedded_video_ids(item, Path(item_dir)))
        return False

    @staticmethod
    def _item_from_meta(meta: Dict[str, Any]) -> ContentItem:
        extra = meta.get("extra") or {}
        content_html = ""
        if meta.get("type") == "zvideo":
            description = extra.get("description") or ""
            if description:
                content_html = f"<p>{description}</p>"
        return ContentItem(
            type=meta.get("type") or "",
            id=str(meta.get("id") or ""),
            url=meta.get("url") or "",
            title=meta.get("title") or "",
            author=meta.get("author") or "",
            author_url=meta.get("author_url") or "",
            created=int(meta.get("created") or 0),
            updated=int(meta.get("updated") or 0),
            voteup_count=int(meta.get("voteup_count") or 0),
            comment_count=int(meta.get("comment_count") or 0),
            favorite_count=int(meta.get("favorite_count") or 0),
            like_count=int(meta.get("like_count") or 0),
            content_html=content_html,
            source=meta.get("source") or "api",
            extra=extra,
        )

    def _item_for_video_backfill(
        self, meta: Dict[str, Any], item_dir: Path
    ) -> ContentItem:
        item = self._item_from_meta(meta)
        try:
            if item.type == "pin":
                fresh = pin_ext.from_api(self.ensure_api().pin_detail(item.id))
            elif item.type == "zvideo":
                fresh = zvideo_ext.from_api(
                    self.ensure_api().zvideo_detail(item.id), item.id
                )
            else:
                return item
            if self._meta_has_video(fresh.to_meta()):
                return fresh
            logger.warning("重新获取视频链接后未找到视频，使用旧链接：%s", item.url)
            return item
        except Exception as exc:
            logger.warning("重新获取视频链接失败，使用旧链接：%s（%s）", item.url, exc)
            return item

    def _download_videos_for_item(
        self,
        item: ContentItem,
        downloader: VideoDownloader,
        item_dir: Optional[Path] = None,
    ) -> int:
        count = 0
        if item.type in ("answer", "article"):
            if item_dir is None:
                return 0
            ids = self._embedded_video_ids(item, Path(item_dir))
            if ids:
                embedded = self._download_embedded_videos(
                    item, Path(item_dir), ids
                )
                if embedded:
                    item.extra["embedded_videos"] = embedded
                count = len(embedded)
            return count
        if item.type == "pin":
            for index, part in enumerate(item.extra.get("parts") or [], start=1):
                if isinstance(part, dict) and part.get("type") == "video":
                    if downloader.download_part(part, index):
                        count += 1
        elif item.type == "zvideo":
            video = item.extra.get("video") or {}
            if isinstance(video, dict) and video:
                meta = downloader.download_video(video, 1)
                if meta:
                    video["local_file"] = meta["local_file"]
                    video["video_meta"] = meta
                    item.extra["video"] = video
                    count += 1
        return count

    @staticmethod
    def _files_for_item_dir(item_dir: Path) -> List[str]:
        files = ["content.md", "meta.json"]
        images = item_dir / "images"
        if images.is_dir() and any(path.is_file() for path in images.iterdir()):
            files.append("images/")
        videos = item_dir / "videos"
        if videos.is_dir() and any(path.is_file() for path in videos.iterdir()):
            files.append("videos/")
        if (item_dir / "content.pdf").exists():
            files.append("content.pdf")
        return files

    def _write_item_with_videos(self, item: ContentItem, item_dir: Path) -> List[str]:
        downloader = ImageDownloader(self.http, item_dir, enabled=True)
        converter = HtmlToMarkdown(downloader, referer=item.url)
        if item.type == "pin":
            body = converter.render_pin(item)
        else:
            body = converter.convert(item.content_html)
        markdown = converter.render_document(item, body)
        (item_dir / "content.md").write_text(markdown, encoding="utf-8")
        atomic_write_json(item_dir / "meta.json", item.to_meta())
        return self._files_for_item_dir(item_dir)

    def _base_for_item_dir(self, item_dir: Path) -> Path:
        relative = Path(item_dir).resolve().relative_to(self.storage.output.resolve())
        parts = relative.parts
        if parts and parts[0] == "users" and len(parts) >= 2:
            return self.storage.output / "users" / parts[1]
        return self.storage.singles_dir()

    def _backfill_url_videos(self, values: Iterable[str]) -> Dict[str, Any]:
        targets: List[Target] = []
        seen: set[tuple] = set()
        for value in values:
            target = parse_target(value)
            if target is None:
                self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append({"url": value, "error": "无法识别的知乎链接"})
                continue
            key = (target.type, target.id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(target)

        index = self._content_index()
        processed = 0
        for target in targets:
            if self.limit and processed >= self.limit:
                break
            dir_name = KIND_DIR.get(target.type, target.type + "s")
            existing_dir = index.get((dir_name, target.id))

            try:
                counted = False
                if existing_dir is not None and (existing_dir / "content.md").exists():
                    meta = read_json(existing_dir / "meta.json", {})
                    if not isinstance(meta, dict):
                        meta = {}
                    if self._has_video_files(existing_dir) and not self.force:
                        self.stats.skipped += 1
                        processed += 1
                        continue
                    self.stats.total += 1
                    counted = True
                    item = (
                        self._item_for_video_backfill(meta, existing_dir)
                        if self._meta_has_video(meta)
                        else self._fetch_item_by_target(target)
                    )
                    item_dir = existing_dir
                else:
                    logger.info(
                        "本地没有该内容，跳过（--videos_only 只补已有内容）：%s",
                        target.url,
                    )
                    self.stats.skipped += 1
                    processed += 1
                    continue

                if not (
                    any(
                        isinstance(part, dict) and part.get("type") == "video"
                        for part in (item.extra.get("parts") or [])
                    )
                    or item.extra.get("video")
                ):
                    raise ZhihuBackupError("该内容中没有可下载的视频")

                base_dir = self._base_for_item_dir(item_dir)
                manifest = Manifest(base_dir)
                downloader = VideoDownloader(
                    self.http,
                    item_dir,
                    enabled=True,
                    quality=self.video_quality,
                    referer=item.url,
                    overwrite=self.force,
                )
                if self._download_videos_for_item(item, downloader, item_dir) == 0:
                    raise ZhihuBackupError("未下载到视频（链接可能已过期）")
                files = self._write_item_with_videos(item, item_dir)
                manifest.mark_ok(
                    item,
                    self.storage.relative_to(base_dir, item_dir),
                    files,
                )
                if self._content_index_cache is not None:
                    self._content_index_cache[(dir_name, item.id)] = item_dir
                self.stats.ok += 1
                logger.info("已补全视频：%s", item.url)
            except AuthError:
                raise
            except Exception as exc:
                if not counted:
                    self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append(
                    {"url": target.url, "error": str(exc)}
                )
                logger.warning("补全视频失败：%s（%s）", target.url, exc)
            processed += 1

        result = self.summary()
        result["videos_only"] = True
        result["singles"] = len(targets)
        return result

    def _count_user_items(self, url_token: str, kind: str, profile: UserProfile) -> int:
        api = self.ensure_api()
        seen: set[str] = set()
        count = 0
        try:
            for raw in api.iter_user_items(
                url_token, kind, max_items=self.limit or None, since_ts=self.since_ts
            ):
                item_id = str(raw.get("id") or "")
                if item_id in seen:
                    continue
                seen.add(item_id)
                count += 1
            return count
        except EnumerationError as exc:
            logger.info("API 枚举 %s 失败，改用浏览器计数：%s", kind, exc)
            seen |= exc.seen_ids
            if kind == "zvideos":
                logger.warning("zvideo 列表 API 失败，无法用浏览器回退。")
                return count

        targets = self._enumerate_user_browser(
            url_token, kind, max_items=(self.limit - count) if self.limit else None
        )
        return count + len([target for target in targets if target.id not in seen])

    def _make_progress(self, desc: str):
        if bool(getattr(self.args, "json", False)) or not sys.stderr.isatty():
            return None
        try:
            from tqdm import tqdm
        except Exception:
            return None
        return tqdm(desc=desc, unit="条", leave=False)

    def _backup_user_kind(
        self,
        url_token: str,
        kind: str,
        profile: UserProfile,
        base_dir: Path,
        manifest: Manifest,
    ) -> None:
        progress = self._make_progress(kind)
        try:
            self._backup_user_kind_inner(
                url_token, kind, profile, base_dir, manifest, progress
            )
        finally:
            if progress is not None:
                progress.close()

    def _backup_user_kind_inner(
        self,
        url_token: str,
        kind: str,
        profile: UserProfile,
        base_dir: Path,
        manifest: Manifest,
        progress,
    ) -> None:
        api = self.ensure_api()
        dir_name = KIND_DIR[PLURAL_TO_KIND[kind]]
        existing = Storage.index_existing(base_dir, dir_name)
        seen: set[str] = set()
        processed = 0
        fallback_needed = False

        try:
            for raw in api.iter_user_items(
                url_token, kind, max_items=self.limit or None, since_ts=self.since_ts
            ):
                item = self._item_from_raw(kind, raw, profile)
                if item.id in seen:
                    logger.info(
                        "重复条目，已跳过：%s（%s）", item.title or item.id, item.id
                    )
                    self.stats.skipped += 1
                    continue
                seen.add(item.id)
                self._process_item(item, base_dir, manifest, existing, profile)
                processed += 1
                if progress is not None:
                    progress.update(1)
                if self.limit and processed >= self.limit:
                    return
        except EnumerationError as exc:
            fallback_needed = True
            logger.info(
                "API 枚举 %s 中断（已处理 %d 条），改用浏览器补全：%s",
                kind,
                processed,
                exc,
            )
            seen |= exc.seen_ids

        if not fallback_needed:
            return

        if kind == "zvideos":
            logger.warning("zvideo 列表 API 失败，无法用浏览器回退。")
            return

        remaining = (self.limit - processed) if self.limit else None
        if remaining is not None and remaining <= 0:
            return

        targets = self._enumerate_user_browser(url_token, kind, max_items=remaining)
        for target in targets:
            if target.id in seen:
                continue
            if self.limit and processed >= self.limit:
                return
            try:
                item = self._fetch_item_by_target(target)
            except AuthError:
                raise
            except Exception as exc:
                logger.error("获取内容失败 %s：%s", target.url, exc)
                self.stats.failed += 1
                self.stats.total += 1
                self.stats.errors.append(
                    {"url": target.url, "error": str(exc)}
                )
                continue
            self._process_item(item, base_dir, manifest, existing, profile)
            processed += 1
            if progress is not None:
                progress.update(1)

    def _item_from_raw(self, kind: str, raw: Dict[str, Any], profile: UserProfile) -> ContentItem:
        if kind == "answers":
            item = answer_ext.from_api(raw, profile.name, profile.url)
        elif kind == "articles":
            item = article_ext.from_api(raw, profile.name, profile.url)
        elif kind == "pins":
            item = pin_ext.from_api(raw)
        elif kind == "zvideos":
            item = zvideo_ext.from_api(raw)
            if not item.extra.get("video", {}).get("variants"):
                try:
                    detail = self.ensure_api().zvideo_detail(item.id)
                    item = zvideo_ext.from_api(detail, item.id)
                except Exception as exc:
                    logger.debug("zvideo 详情获取失败 %s：%s", item.id, exc)
        else:
            raise ValueError(f"不支持的内容类型：{kind}")

        if not item.author:
            item.author = profile.name
        if not item.author_url:
            item.author_url = profile.url
        return item

    # ----------------------------------------------------------- single URLs
    def backup_urls(self, values: Iterable[str]) -> Dict[str, Any]:
        if self.videos_only:
            return self._backfill_url_videos(values)
        if self.pdf_only:
            return self._backup_url_pdfs(values)
        targets: List[Target] = []
        seen: set[tuple] = set()
        for value in values:
            target = parse_target(value)
            if target is None:
                self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append({"url": value, "error": "无法识别的知乎链接"})
                logger.error("无法识别的知乎链接：%s", value)
                continue
            key = (target.type, target.id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(target)

        if not targets:
            return self.summary()

        base_dir = self.storage.singles_dir()
        manifest = Manifest(base_dir)
        existing_by_kind: Dict[str, Dict[str, Path]] = {}

        for index, target in enumerate(targets, start=1):
            if self.limit and index > self.limit:
                break
            dir_name = KIND_DIR.get(target.type, target.type + "s")
            existing_path = self._content_index().get((dir_name, target.id))
            if (
                existing_path is not None
                and not bool(getattr(self.args, "force", False))
                and not bool(getattr(self.args, "update", False))
            ):
                logger.info("本地已存在，跳过：%s", target.url)
                self.stats.skipped += 1
                continue
            try:
                item = self._fetch_item_by_target(target)
            except AuthError:
                raise
            except Exception as exc:
                logger.error("获取内容失败 %s：%s", target.url, exc)
                self.stats.total += 1
                self.stats.failed += 1
                self.stats.errors.append({"url": target.url, "error": str(exc)})
                continue
            dir_name = KIND_DIR.get(item.type, item.type + "s")
            if dir_name not in existing_by_kind:
                existing_by_kind[dir_name] = Storage.index_existing(base_dir, dir_name)
            self._process_item(item, base_dir, manifest, existing_by_kind[dir_name])

        result = self.summary()
        result["singles"] = len(targets)
        return result

    def _fetch_item_by_target(self, target: Target) -> ContentItem:
        api = self.ensure_api()
        try:
            if target.type == "answer":
                raw = api.answer_detail(target.id)
                item = answer_ext.from_api(raw)
            elif target.type == "article":
                raw = api.article_detail(target.id)
                item = article_ext.from_api(raw)
            elif target.type == "pin":
                raw = api.pin_detail(target.id)
                item = pin_ext.from_api(raw)
            else:
                item = self._zvideo_item(target)
            if item.content_html or target.type == "zvideo":
                if not item.id:
                    item.id = target.id
                if not item.url:
                    item.url = target.url
                return item
            logger.debug("API 返回的内容为空，改用浏览器解析：%s", target.url)
        except AuthError:
            # The endpoint (usually the single-article API) may reject requests
            # even with valid cookies; the browser fallback handles the rest.
            logger.debug("内容接口返回 403，改用浏览器解析：%s", target.url)
        except Exception as exc:
            logger.debug("API 获取失败，改用浏览器解析：%s（%s）", target.url, exc)

        placeholder = ContentItem(
            type=target.type,
            id=target.id,
            url=target.url,
            title="",
            extra={"question_id": target.question_id or ""},
        )
        return self._fetch_item_dom(placeholder)

    def _zvideo_item(self, target: Target) -> ContentItem:
        try:
            raw = self.ensure_api().zvideo_detail(target.id)
            item = zvideo_ext.from_api(raw, target.id)
            if item.extra.get("video", {}).get("variants"):
                return item
            logger.debug("zvideo API 未返回清晰度列表，改用浏览器解析。")
        except Exception as exc:
            logger.debug("zvideo API 获取失败，改用浏览器：%s", exc)

        browser = self.ensure_browser()
        browser.get(target.url, wait_css="h1, .ZVideo-video", wait_timeout=20)
        browser.check_login()
        item = zvideo_ext.from_dom(browser.html, target.url)
        if not item.title:
            item.title = f"视频 {target.id}"
        return item

    def _embedded_video_ids(
        self, item: ContentItem, item_dir: Optional[Path] = None
    ) -> List[str]:
        ids: List[str] = []
        if item.content_html:
            soup = soup_of(item.content_html)
            for anchor in soup.select("a.video-box, .video-box"):
                lens_id = anchor.get("data-lens-id") or ""
                if lens_id:
                    ids.append(str(lens_id))
                    continue
                href = unquote(anchor.get("href") or "")
                match = re.search(r"/video/(\d+)", href)
                if match:
                    ids.append(match.group(1))
        if not ids and item_dir is not None:
            content_md = Path(item_dir) / "content.md"
            if content_md.exists():
                ids = re.findall(
                    r"zhihu\.com/video/(\d+)",
                    content_md.read_text(encoding="utf-8"),
                )
        return list(dict.fromkeys(ids))

    def _download_embedded_videos(
        self,
        item: ContentItem,
        item_dir: Path,
        video_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        ids = video_ids if video_ids is not None else self._embedded_video_ids(item, item_dir)
        if not ids:
            return []
        if self.http is None:
            self.ensure_api()

        from selenium.webdriver.common.by import By

        browser = self.ensure_browser()
        browser.get(
            item.url,
            wait_css=".RichContent-inner, .Post-RichTextContainer, .Post-RichText",
            wait_timeout=20,
        )
        browser.check_login()
        browser.scroll(times=10, pause=0.3)
        browser.expand_buttons()

        scope = None
        if item.type == "answer":
            for element in browser.driver.find_elements(By.CSS_SELECTOR, "div.AnswerItem"):
                try:
                    import json

                    zop = json.loads(element.get_attribute("data-zop") or "{}")
                except (TypeError, ValueError):
                    zop = {}
                if str(zop.get("itemId") or "") == item.id:
                    scope = element
                    break
            if scope is None:
                candidates = browser.driver.find_elements(By.CSS_SELECTOR, ".RichContent-inner")
                scope = candidates[0] if candidates else None
        elif item.type == "article":
            candidates = browser.driver.find_elements(
                By.CSS_SELECTOR, ".Post-RichTextContainer, .Post-RichText"
            )
            scope = candidates[0] if candidates else None
        if scope is None:
            scope = browser.driver.find_element(By.TAG_NAME, "body")

        videos = []
        for element in scope.find_elements(By.TAG_NAME, "video"):
            source = element.get_attribute("src") or browser.driver.execute_script(
                "return arguments[0].currentSrc || arguments[0].src || ''", element
            )
            poster = element.get_attribute("poster") or ""
            if source:
                videos.append((source, poster))
        if not videos:
            for element in scope.find_elements(By.TAG_NAME, "source"):
                source = element.get_attribute("src")
                if source:
                    videos.append((source, ""))

        if not videos:
            logger.warning("页面中未找到内嵌视频元素：%s", item.url)
            return []

        downloader = VideoDownloader(
            self.http,
            item_dir,
            enabled=True,
            quality=self.video_quality,
            referer=item.url,
            overwrite=self.force,
        )
        results: List[Dict[str, Any]] = []
        for index, (source, poster) in enumerate(videos, start=1):
            video_id = ids[index - 1] if index - 1 < len(ids) else f"embedded_{index}"
            part = {
                "type": "video",
                "id": video_id,
                "playlist": {
                    "hd": {"play_url": source, "format": "mp4"},
                },
                "cover": poster,
            }
            meta = downloader.download_part(part, index)
            if meta:
                results.append(
                    {
                        "id": video_id,
                        "local_file": meta["local_file"],
                        "url": source,
                        "poster": poster,
                        "video_meta": meta,
                    }
                )
        return results

    # --------------------------------------------------------------- helpers
    def _process_item(
        self,
        item: ContentItem,
        base_dir: Path,
        manifest: Manifest,
        existing: Dict[str, Path],
        profile: Optional[UserProfile] = None,
    ) -> None:
        if self.since_ts and item.created and item.created < self.since_ts:
            self.stats.skipped += 1
            return

        if not item.id:
            # DOM extraction may not know the id; derive it from the URL.
            parsed = parse_target(item.url)
            if parsed:
                item.id = parsed.id
        if not item.id:
            self.stats.total += 1
            self.stats.failed += 1
            self.stats.errors.append({"url": item.url, "error": "无法确定内容 ID"})
            logger.error("无法确定内容 ID：%s", item.url)
            return

        entry_for_skip = manifest.get(item.type, item.id)
        if entry_for_skip and entry_for_skip.dir:
            candidate_dir = Path(base_dir) / entry_for_skip.dir
        elif item.id in existing:
            candidate_dir = existing[item.id]
        else:
            candidate_dir = None

        if self.videos_only and candidate_dir is None:
            self.stats.skipped += 1
            return

        skip = manifest.should_skip(
            item,
            force=bool(getattr(self.args, "force", False)),
            update=bool(getattr(self.args, "update", False)),
            existing_dirs=existing,
        )
        if skip and self._item_needs_video(item, candidate_dir):
            skip = False
            logger.info("检测到缺失视频，重新处理：%s", item.url)
        if skip:
            self.stats.skipped += 1
            logger.debug("跳过已备份内容：%s:%s", item.type, item.id)
            return

        self.stats.total += 1
        try:
            if self.http is None and (
                not bool(getattr(self.args, "no_images", False))
                or self.download_videos
            ):
                self.ensure_api()
            if item.type == "answer" and item.extra.pop("needs_stats", False):
                self._fill_answer_stats(item)
            if not item.content_html:
                item = self._fetch_item_dom(item)
            if not item.content_html and not item.title:
                raise ParseError("页面中没有找到正文")

            if profile is not None:
                if not item.author:
                    item.author = profile.name
                if not item.author_url:
                    item.author_url = profile.url

            if (
                item.type == "answer"
                and not item.extra.get("question_html")
                and not bool(getattr(self.args, "no_question_body", False))
            ):
                question_id = str(item.extra.get("question_id") or "")
                if question_id:
                    item.extra["question_html"] = self._fetch_question_html(question_id)

            dir_name = KIND_DIR.get(item.type, item.type + "s")
            entry = manifest.get(item.type, item.id)
            if entry and entry.dir and (Path(base_dir) / entry.dir).exists():
                item_dir = Path(base_dir) / entry.dir
            elif item.id in existing:
                item_dir = existing[item.id]
            else:
                item_dir = self.storage.item_dir(Path(base_dir), dir_name, item)
            item_dir.mkdir(parents=True, exist_ok=True)

            embedded_videos: List[Dict[str, Any]] = []
            if self.download_videos and item.type in ("answer", "article"):
                embedded_videos = self._download_embedded_videos(item, item_dir)
                if embedded_videos:
                    item.extra["embedded_videos"] = embedded_videos

            video_downloader: Optional[VideoDownloader] = None
            if self.download_videos:
                video_downloader = VideoDownloader(
                    self.http,
                    item_dir,
                    enabled=True,
                    quality=self.video_quality,
                    referer=item.url,
                )
                if item.type == "pin":
                    for index, part in enumerate(
                        item.extra.get("parts") or [], start=1
                    ):
                        if part.get("type") == "video":
                            video_downloader.download_part(part, index)
                elif item.type == "zvideo":
                    video = item.extra.get("video") or {}
                    if isinstance(video, dict) and video:
                        meta = video_downloader.download_video(video, 1)
                        if meta:
                            video["local_file"] = meta["local_file"]
                            video["video_meta"] = meta
                            item.extra["video"] = video

            downloader = ImageDownloader(
                self.http,
                item_dir,
                enabled=not bool(getattr(self.args, "no_images", False)),
            )
            converter = HtmlToMarkdown(downloader, referer=item.url)
            if item.type == "pin":
                body = converter.render_pin(item)
            else:
                body = converter.convert(item.content_html)
            markdown = converter.render_document(item, body)

            content_md = item_dir / "content.md"
            content_md.write_text(markdown, encoding="utf-8")
            atomic_write_json(item_dir / "meta.json", item.to_meta())

            files = ["content.md", "meta.json"]
            if downloader.counter:
                files.append("images/")
            if embedded_videos or (
                video_downloader is not None and video_downloader.downloaded
            ):
                files.append("videos/")
            if getattr(self.args, "pdf", False):
                pdf_path = item_dir / "content.pdf"
                if print_item_pdf(
                    self.ensure_browser(),
                    item,
                    pdf_path,
                    item_dir=item_dir,
                    image_map=downloader.seen,
                ):
                    files.append("content.pdf")

            relative = self.storage.relative_to(Path(base_dir), item_dir)
            manifest.mark_ok(item, relative, files)
            existing[item.id] = item_dir
            if self._content_index_cache is not None:
                self._content_index_cache[(dir_name, item.id)] = item_dir
            self.stats.ok += 1
            logger.info(
                "已保存 [%s] %s（图片 %d，视频 %d）",
                item.type,
                item.title or item.id,
                downloader.counter,
                len(embedded_videos)
                + (len(video_downloader.downloaded) if video_downloader else 0),
            )
        except AuthError:
            raise
        except Exception as exc:
            self.stats.failed += 1
            self.stats.errors.append(
                {"url": item.url, "type": item.type, "id": item.id, "error": str(exc)}
            )
            logger.error("保存失败 [%s:%s]：%s", item.type, item.id, exc)
            try:
                manifest.mark_failed(item, str(exc))
            except Exception:
                pass

    def _fill_answer_stats(self, item: ContentItem) -> None:
        """List endpoints omit voteup_count; fetch the detail for full stats."""
        try:
            detail = answer_ext.from_api(self.ensure_api().answer_detail(item.id))
            item.voteup_count = detail.voteup_count
            item.favorite_count = detail.favorite_count
            item.like_count = detail.like_count
            item.comment_count = detail.comment_count
            if detail.created:
                item.created = detail.created
            if detail.updated:
                item.updated = detail.updated
        except Exception as exc:
            logger.debug("补全回答统计失败 %s：%s", item.id, exc)

    def _fetch_question_html(self, question_id: str) -> str:
        if question_id in self._question_cache:
            return self._question_cache[question_id]
        html = ""
        try:
            raw = self.ensure_api().question_detail(question_id)
            detail = raw.get("detail") or raw.get("content") or ""
            if isinstance(detail, str):
                html = detail
        except Exception as exc:
            logger.debug("获取问题描述失败 %s：%s", question_id, exc)
        self._question_cache[question_id] = html
        return html

    def _fetch_item_dom(self, item: ContentItem) -> ContentItem:
        browser = self.ensure_browser()
        wait_selector = DETAIL_WAIT_SELECTOR.get(item.type)
        browser.get(item.url, wait_css=wait_selector, wait_timeout=20)
        browser.check_login()
        time.sleep(0.5)
        browser.scroll(times=18, pause=0.35)
        browser.expand_buttons()
        html = browser.html

        if item.type == "answer":
            parsed = answer_ext.from_dom(html, item.url)
        elif item.type == "article":
            parsed = article_ext.from_dom(html, item.url)
        elif item.type == "pin":
            parsed = pin_ext.from_dom(html, item.url)
        elif item.type == "zvideo":
            parsed = zvideo_ext.from_dom(html, item.url)
        else:
            raise ParseError(f"不支持 DOM 解析：{item.type}")

        parsed.id = item.id or parsed.id
        parsed.url = item.url or parsed.url
        if not parsed.created:
            parsed.created = item.created
        if not parsed.updated:
            parsed.updated = item.updated
        if not parsed.author:
            parsed.author = item.author
        if not parsed.author_url:
            parsed.author_url = item.author_url
        if item.extra.get("question_id") and not parsed.extra.get("question_id"):
            parsed.extra["question_id"] = item.extra["question_id"]
        return parsed

    def _enumerate_user_browser(
        self,
        url_token: str,
        kind: str,
        max_items: Optional[int] = None,
    ) -> List[Target]:
        from selenium.webdriver.common.by import By

        browser = self.ensure_browser()
        path = {"answers": "answers", "articles": "posts", "pins": "pins"}[kind]
        base_url = f"https://www.zhihu.com/people/{url_token}/{path}"
        item_selector = LIST_SELECTOR[kind]

        browser.get(
            base_url,
            wait_css=f".Pagination, {item_selector}",
            wait_timeout=20,
        )
        browser.check_login()
        max_pages = 1
        buttons = browser.driver.find_elements(By.CSS_SELECTOR, ".PaginationButton")
        numbers = []
        for button in buttons:
            text = (button.text or "").strip()
            if text.isdigit():
                numbers.append(int(text))
        if numbers:
            max_pages = max(numbers)

        targets: List[Target] = []
        seen: set[tuple] = set()

        for page in range(1, max_pages + 1):
            if page > 1:
                browser.get(
                    f"{base_url}?page={page}",
                    wait_css=f".Pagination, {item_selector}",
                    wait_timeout=20,
                )
                browser.check_login()
            browser.scroll(times=4, pause=0.3)
            elements = browser.driver.find_elements(By.CSS_SELECTOR, item_selector)
            for element in elements:
                url = self._element_content_url(element, kind)
                if not url:
                    continue
                target = parse_target(url)
                if target is None:
                    continue
                key = (target.type, target.id)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(target)
                if max_items and len(targets) >= max_items:
                    return targets
            time.sleep(max(1.0, float(getattr(self.args, "sleep", 1.5))))

        return targets

    @staticmethod
    def _element_content_url(element, kind: str) -> str:
        from selenium.webdriver.common.by import By

        # Prefer the structured payload: item cards may contain links to other
        # content in their footer or recommendations.
        raw = element.get_attribute("data-zop")
        if raw:
            import json

            try:
                zop = json.loads(raw)
            except ValueError:
                zop = {}
            if kind == "answers":
                answer_id = zop.get("itemId")
                question_id = zop.get("questionId")
                if answer_id and question_id:
                    return (
                        f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
                    )
            if kind == "pins" and zop.get("itemId"):
                return f"https://www.zhihu.com/pin/{zop['itemId']}"

        selectors = {
            "answers": ['a[href*="/answer/"]'],
            "articles": ['a[href*="zhuanlan.zhihu.com/p/"]', 'a[href*="/p/"]'],
            "pins": ['a[href*="/pin/"]'],
        }[kind]
        for selector in selectors:
            links = element.find_elements(By.CSS_SELECTOR, selector)
            for link in links:
                href = link.get_attribute("href")
                if href:
                    return href
        return ""


__all__ = ["Runner", "RunStats", "KIND_DIR", "PLURAL_TO_KIND"]
