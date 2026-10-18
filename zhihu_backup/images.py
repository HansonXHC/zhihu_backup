"""Image downloading with content-type aware file names."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import unquote, urlparse

from .http_client import HttpClient

logger = logging.getLogger(__name__)

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
}

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


def _extension_from_url(url: str) -> Optional[str]:
    path = unquote(urlparse(url).path).lower()
    for ext in _ALLOWED_EXT:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return None


class ImageDownloader:
    """Downloads images into one item's ``images/`` directory."""

    def __init__(self, http: HttpClient, item_dir: Path, enabled: bool = True):
        self.http = http
        self.item_dir = Path(item_dir)
        self.enabled = enabled
        self.counter = 0
        self.seen: Dict[str, str] = {}
        self.failures = 0

    def _write(self, data: bytes, extension: str) -> str:
        images_dir = self.item_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        self.counter += 1
        name = f"{self.counter:03d}{extension}"
        path = images_dir / name
        with open(path, "wb") as handle:
            handle.write(data)
        return f"images/{name}"

    def _decode_data_uri(self, url: str) -> Optional[tuple]:
        header, _, payload = url.partition(",")
        if not header or not payload:
            return None
        extension = ".jpg"
        for mime, ext in _CONTENT_TYPE_EXT.items():
            if mime in header:
                extension = ext
                break
        try:
            if "base64" in header:
                data = base64.b64decode(payload)
            else:
                from urllib.parse import unquote_to_bytes

                data = unquote_to_bytes(payload)
        except Exception as exc:
            logger.debug("无法解码 data URI 图片：%s", exc)
            return None
        return data, extension

    def download(self, url: str, referer: Optional[str] = None) -> Optional[str]:
        if not self.enabled or not url:
            return None
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith(("http://", "https://", "data:")):
            if url.startswith(("v1-", "v2-")):
                url = "https://picx.zhimg.com/" + url
            elif referer:
                from urllib.parse import urljoin

                url = urljoin(referer, url)
        if url.startswith("data:"):
            decoded = self._decode_data_uri(url)
            if not decoded:
                return None
            data, extension = decoded
            return self._write(data, extension)

        if url in self.seen:
            return self.seen[url]

        try:
            response = self.http.get_bytes(url, referer=referer)
        except Exception as exc:
            self.failures += 1
            logger.warning("图片下载失败：%s（%s）", url, exc)
            return None

        if response.status_code != 200:
            self.failures += 1
            logger.warning("图片下载失败（HTTP %s）：%s", response.status_code, url)
            return None

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
            self.failures += 1
            logger.warning("图片地址返回了非图片内容（%s）：%s", content_type, url)
            return None
        extension = _CONTENT_TYPE_EXT.get(content_type) or _extension_from_url(url)
        if not extension:
            guessed = mimetypes.guess_extension(content_type) if content_type else None
            extension = guessed if guessed in _ALLOWED_EXT else ".jpg"
        if extension == ".jpeg":
            extension = ".jpg"

        if not response.content:
            self.failures += 1
            return None

        relative = self._write(response.content, extension)
        self.seen[url] = relative
        return relative
