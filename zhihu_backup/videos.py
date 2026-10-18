"""Video variant selection and downloading."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .config import safe_component
from .errors import VideoDownloadError
from .http_client import HttpClient

logger = logging.getLogger(__name__)

_HLS_DASH_FORMATS = {"hls", "dash", "m3u8", "mpd"}
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".flv", ".mov", ".m4v", ".ts"}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _infer_format(url: str, value: Dict[str, Any]) -> str:
    fmt = str(value.get("format") or "").lower()
    if fmt:
        return fmt
    path = urlparse(url).path.lower()
    suffix = Path(path).suffix.lstrip(".")
    if suffix in ("m3u8", "mpd"):
        return suffix
    return suffix or "mp4"


def _quality_label(key: str, height: int) -> str:
    if height >= 1080:
        return "fhd"
    if height >= 720:
        return "hd"
    if height >= 400:
        return "sd"
    if height > 0:
        return "ld"
    key = (key or "").lower()
    return key if key in ("ld", "sd", "hd", "fhd", "uhd") else "ld"


def normalize_variants(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize the many Zhihu playlist shapes into a flat variant list."""
    if not isinstance(part, dict):
        return []

    existing = part.get("video_variants")
    if isinstance(existing, list) and existing:
        normalized = []
        for item in existing:
            if isinstance(item, dict) and item.get("url"):
                normalized.append(dict(item))
        if normalized:
            return normalized

    playlists: List[Any] = []
    top = part.get("playlist")
    if isinstance(top, (dict, list)):
        playlists.append(top)
    video = part.get("video")
    if isinstance(video, dict):
        nested = video.get("playlist")
        if isinstance(nested, (dict, list)):
            playlists.append(nested)

    variants: List[Dict[str, Any]] = []
    for playlist in playlists:
        if isinstance(playlist, dict):
            entries = playlist.items()
        else:
            entries = ((str(index), value) for index, value in enumerate(playlist))
        for key, value in entries:
            if not isinstance(value, dict):
                continue
            url = value.get("play_url") or value.get("playUrl") or value.get("url")
            if not url:
                continue
            height = _int(value.get("height"))
            quality = str(key).lower()
            variants.append(
                {
                    "quality": quality,
                    "quality_label": _quality_label(quality, height),
                    "url": str(url),
                    "format": _infer_format(str(url), value),
                    "width": _int(value.get("width")),
                    "height": height,
                    "bitrate": _int(value.get("bitrate")),
                    "size": _int(value.get("size")),
                    "duration": value.get("duration") or 0,
                }
            )

    if not variants:
        direct = part.get("play_url") or part.get("url")
        if not direct and isinstance(video, dict):
            direct = video.get("play_url") or video.get("playUrl") or video.get("url")
        if direct:
            height = _int(part.get("height"))
            variants.append(
                {
                    "quality": "direct",
                    "quality_label": _quality_label("direct", height),
                    "url": str(direct),
                    "format": _infer_format(str(direct), part),
                    "width": _int(part.get("width")),
                    "height": height,
                    "bitrate": _int(part.get("bitrate")),
                    "size": _int(part.get("size")),
                    "duration": part.get("duration") or 0,
                }
            )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for variant in variants:
        if variant["url"] in seen:
            continue
        seen.add(variant["url"])
        deduped.append(variant)
    return deduped


def select_variant(
    variants: List[Dict[str, Any]], quality: str = "best"
) -> Optional[Dict[str, Any]]:
    if not variants:
        return None
    quality = (quality or "best").lower()
    if quality != "best":
        matches = [
            item
            for item in variants
            if quality in (item.get("quality"), item.get("quality_label"))
        ]
        if matches:
            return max(
                matches,
                key=lambda item: (
                    item.get("height", 0),
                    item.get("width", 0),
                    item.get("bitrate", 0),
                ),
            )
    return max(
        variants,
        key=lambda item: (
            item.get("height", 0),
            item.get("width", 0),
            item.get("bitrate", 0),
            item.get("size", 0),
        ),
    )


def normalize_cover(part: Dict[str, Any]) -> str:
    if not isinstance(part, dict):
        return ""
    cover_info = part.get("cover_info")
    if isinstance(cover_info, dict):
        for key in ("thumbnail", "url", "poster"):
            value = cover_info.get(key)
            if value:
                return str(value)
    video = part.get("video")
    if isinstance(video, dict):
        for key in ("thumbnail", "cover", "poster", "image"):
            value = video.get(key)
            if value:
                return str(value)
    for key in ("cover", "poster", "thumbnail"):
        value = part.get(key)
        if value:
            return str(value)
    return ""


def _is_hls_or_dash(url: str, fmt: str) -> bool:
    if (fmt or "").lower() in _HLS_DASH_FORMATS:
        return True
    path = urlparse(url).path.lower()
    return path.endswith(".m3u8") or path.endswith(".mpd")


def _ffmpeg_path() -> Optional[str]:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")


class VideoDownloader:
    """Downloads video parts into ``<item_dir>/videos``."""

    def __init__(
        self,
        http: HttpClient,
        item_dir: Path,
        enabled: bool = True,
        quality: str = "best",
        referer: str = "",
        overwrite: bool = False,
    ):
        self.http = http
        self.item_dir = Path(item_dir)
        self.enabled = enabled
        self.quality = quality
        self.referer = referer or "https://www.zhihu.com/"
        self.overwrite = overwrite
        self.downloaded: List[Dict[str, Any]] = []
        self.failures = 0

    def download_part(
        self, part: Dict[str, Any], index: int = 1
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        variants = normalize_variants(part)
        chosen = select_variant(variants, self.quality)
        if not chosen:
            return None

        url = str(chosen["url"])
        fmt = str(chosen.get("format") or "mp4").lower()
        if _is_hls_or_dash(url, fmt):
            extension = ".mp4"
        else:
            suffix = Path(urlparse(url).path).suffix.lower()
            extension = suffix if suffix in _VIDEO_EXTENSIONS else ".mp4"
        video_id = safe_component(
            part.get("id") or part.get("video_id") or f"{index:03d}", 80
        )
        dest = self.item_dir / "videos" / f"{video_id}{extension}"
        relative = f"videos/{dest.name}"

        if dest.exists() and dest.stat().st_size > 0 and not self.overwrite:
            meta = {
                "local_file": relative,
                "url": url,
                "quality": chosen.get("quality_label") or chosen.get("quality", "best"),
                "format": fmt,
                "size": dest.stat().st_size,
                "width": chosen.get("width", 0),
                "height": chosen.get("height", 0),
                "bitrate": chosen.get("bitrate", 0),
                "duration": chosen.get("duration", 0),
            }
            part["local_file"] = relative
            part["video_meta"] = meta
            self.downloaded.append(meta)
            return meta

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if _is_hls_or_dash(url, fmt):
                self._download_with_ffmpeg(url, dest)
            else:
                self.http.stream_to_file(
                    url,
                    dest,
                    referer=self.referer,
                    expected_size=chosen.get("size") or None,
                )
                self._validate_mp4(dest)
        except Exception as exc:
            self.failures += 1
            part["video_error"] = str(exc)
            logger.warning("视频下载失败：%s（%s）", url, exc)
            return None

        meta = {
            "local_file": relative,
            "url": url,
            "quality": chosen.get("quality_label") or chosen.get("quality", "best"),
            "format": fmt,
            "size": dest.stat().st_size,
            "width": chosen.get("width", 0),
            "height": chosen.get("height", 0),
            "bitrate": chosen.get("bitrate", 0),
            "duration": chosen.get("duration", 0),
        }
        part["local_file"] = relative
        part["video_meta"] = meta
        self.downloaded.append(meta)
        logger.info(
            "已下载视频：%s（%s，%s 字节）",
            relative,
            meta["quality"],
            meta["size"],
        )
        return meta

    def download_video(self, video: Dict[str, Any], index: int = 1) -> Optional[Dict[str, Any]]:
        """Download a zvideo-style dict with a playlist/variants field."""
        return self.download_part(video, index)

    @staticmethod
    def _validate_mp4(path: Path) -> None:
        if path.suffix.lower() not in (".mp4", ".m4v"):
            return
        try:
            with open(path, "rb") as handle:
                header = handle.read(12)
        except OSError as exc:
            raise VideoDownloadError(f"无法读取视频文件：{exc}") from exc
        if len(header) < 12 or header[4:8] != b"ftyp":
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise VideoDownloadError("下载内容不是有效的 MP4 文件")

    def _download_with_ffmpeg(self, url: str, dest: Path) -> None:
        ffmpeg = _ffmpeg_path()
        if not ffmpeg:
            raise VideoDownloadError(
                "视频是 HLS/DASH 格式，但未找到 ffmpeg；请安装 ffmpeg 或设置 FFMPEG_PATH"
            )
        temp = dest.with_name(dest.stem + ".part" + dest.suffix)
        if temp.exists():
            temp.unlink(missing_ok=True)
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-headers",
            f"Referer: {self.referer}\r\n",
            "-i",
            url,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temp),
        ]
        logger.debug("ffmpeg 视频下载：%s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoDownloadError("ffmpeg 下载超时") from exc
        if result.returncode != 0 or not temp.exists() or temp.stat().st_size <= 0:
            error = (result.stderr or "").strip()[-500:]
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise VideoDownloadError(f"ffmpeg 下载失败：{error or '未知错误'}")
        os.replace(temp, dest)
