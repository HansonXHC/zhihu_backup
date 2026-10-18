"""HTML to Markdown conversion, adapted from zhihu-download-main."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify

from .config import timestamp_to_iso
from .images import ImageDownloader
from .models import ContentItem

try:  # lxml is preferred but html.parser always works
    import lxml  # noqa: F401

    SOUP_PARSER = "lxml"
except Exception:  # pragma: no cover - depends on environment
    SOUP_PARSER = "html.parser"

_MULTI_NEWLINE = re.compile(r"\n{3,}")
_LINK_HOSTS = ("link.zhihu.com", "www.zhihu.com/link")


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", SOUP_PARSER)


def unwrap_zhihu_link(href: str) -> str:
    """Extract the real target from Zhihu's link.zhihu.com redirect."""
    if not href:
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    if "target" in params and (
        "link.zhihu.com" in (parsed.netloc or "") or parsed.path.startswith("/link")
    ):
        return unquote(params["target"][0])
    return href


def _image_source(img) -> Optional[str]:
    for attribute in ("data-original", "data-actualsrc", "data-src", "src"):
        value = img.get(attribute)
        if value:
            return value
    return None


class HtmlToMarkdown:
    """Converts one rich-text HTML fragment into Markdown."""

    def __init__(self, downloader: Optional[ImageDownloader] = None, referer: Optional[str] = None):
        self.downloader = downloader
        self.referer = referer or "https://www.zhihu.com/"

    def convert(self, html: str) -> str:
        if not html or not html.strip():
            return ""

        soup = soup_of(html)
        for tag in soup(["style", "script", "noscript"]):
            tag.decompose()

        # Remove only lazy placeholders; a lazy <img> may still carry the real
        # URL in data-original, which is what the downloader should use.
        for img in list(soup.find_all("img")):
            classes = " ".join(img.get("class") or [])
            if "lazy" in classes:
                real_source = (
                    img.get("data-original")
                    or img.get("data-actualsrc")
                    or img.get("data-src")
                )
                if not real_source:
                    img.decompose()

        inline_math: List[str] = []
        block_math: List[str] = []
        for span in list(soup.select("span.ztext-math")):
            tex = span.get("data-tex")
            if not tex:
                continue
            if "\\tag" in tex or "\\begin{" in tex:
                token = f"@@ZHMATHB{len(block_math)}@@"
                block_math.append(tex)
                span.replace_with(f"\n\n{token}\n\n")
            else:
                token = f"@@ZHMATHI{len(inline_math)}@@"
                inline_math.append(tex)
                span.replace_with(token)

        for img in list(soup.find_all("img")):
            source = _image_source(img)
            if not source:
                img.decompose()
                continue
            if self.downloader:
                relative = self.downloader.download(source, referer=self.referer)
                img["src"] = relative or source
            else:
                img["src"] = source
            for attribute in ("data-original", "data-actualsrc", "data-src"):
                img.attrs.pop(attribute, None)
            if not img.get("alt"):
                img["alt"] = ""

        for link in list(soup.find_all("a")):
            href = link.get("href")
            if not href:
                continue
            link["href"] = unwrap_zhihu_link(href)
            if not link.get_text(strip=True):
                link.string = link.get("data-text") or link["href"]

        try:
            markdown = markdownify(str(soup), heading_style="ATX", bullets="-")
        except Exception:
            # A malformed fragment should not abort the whole backup.
            markdown = soup.get_text("\n", strip=True)

        for index, formula in enumerate(inline_math):
            replacement = formula if "$" in formula else f"${formula}$"
            markdown = markdown.replace(f"@@ZHMATHI{index}@@", replacement)
        for index, formula in enumerate(block_math):
            replacement = formula if "$" in formula else f"$${formula}$$"
            markdown = markdown.replace(f"@@ZHMATHB{index}@@", replacement)

        markdown = _MULTI_NEWLINE.sub("\n\n", markdown)
        return markdown.strip()

    def render_pin(self, item: ContentItem) -> str:
        """Render a pin's structured content array into Markdown."""
        parts = item.extra.get("parts") or []
        if not parts:
            return self.convert(item.content_html)

        chunks: List[str] = []
        for part in parts:
            part_type = part.get("type")
            if part_type == "text":
                text = self.convert(part.get("content") or "")
                if text:
                    chunks.append(text)
            elif part_type == "image":
                url = part.get("url") or part.get("src")
                if not url:
                    continue
                relative = self.downloader.download(url, referer=item.url) if self.downloader else None
                chunks.append(f"![]({relative or url})")
            elif part_type == "video":
                video_url = (
                    part.get("local_file")
                    or part.get("play_url")
                    or part.get("url")
                    or ""
                )
                cover = part.get("cover") or part.get("poster")
                if cover:
                    relative = self.downloader.download(cover, referer=item.url) if self.downloader else None
                    chunks.append(f"![]({relative or cover})")
                if video_url:
                    if part.get("local_file"):
                        chunks.append(f"[视频]({video_url})")
                    else:
                        chunks.append(f"[视频]({unwrap_zhihu_link(video_url)})")
            elif part_type == "link":
                url = unwrap_zhihu_link(part.get("url") or "")
                title = part.get("title") or url
                if url:
                    chunks.append(f"[{title}]({url})")
        return "\n\n".join(chunk for chunk in chunks if chunk).strip()

    def render_document(self, item: ContentItem, body_markdown: Optional[str] = None) -> str:
        body = body_markdown if body_markdown is not None else self.convert(item.content_html)

        if item.type == "zvideo":
            video = item.extra.get("video") or {}
            chunks = []
            cover = video.get("cover") if isinstance(video, dict) else ""
            if cover:
                relative = (
                    self.downloader.download(cover, referer=item.url)
                    if self.downloader
                    else None
                )
                chunks.append(f"![]({relative or cover})")
            target = (
                video.get("local_file")
                or video.get("url")
                or item.url
            ) if isinstance(video, dict) else item.url
            chunks.append(f"[视频]({target})")
            body = "\n\n".join([body, *chunks]).strip()

        if item.type == "answer":
            question_html = item.extra.get("question_html") or ""
            question_markdown = self.convert(question_html) if question_html else ""
            if question_markdown:
                body = f"## 问题\n\n{question_markdown}\n\n## 回答\n\n{body}".strip()

        if item.type in ("answer", "article"):
            embedded = item.extra.get("embedded_videos") or []
            if embedded:
                chunks = ["## 视频"]
                for video in embedded:
                    local_file = video.get("local_file")
                    if local_file:
                        chunks.append(f"[视频]({local_file})")
                if len(chunks) > 1:
                    body = "\n\n".join([body, *chunks]).strip()

        lines = [f"# {item.title or '无标题'}", ""]
        if item.author:
            if item.author_url:
                lines.extend([f"**作者**：[{item.author}]({item.author_url})", ""])
            else:
                lines.extend([f"**作者**：{item.author}", ""])
        lines.extend([f"**原文**：{item.url}", ""])
        if item.created:
            lines.extend([f"**发布时间**：{timestamp_to_iso(item.created)}", ""])
        if item.type in ("answer", "article") and item.updated and item.updated != item.created:
            lines.extend([f"**编辑时间**：{timestamp_to_iso(item.updated)}", ""])
        if any(
            [item.voteup_count, item.favorite_count, item.like_count, item.comment_count]
        ):
            stats = [
                f"赞同 {item.voteup_count}",
                f"收藏 {item.favorite_count}",
                f"喜欢 {item.like_count}",
                f"评论 {item.comment_count}",
            ]
            lines.extend([" · ".join(stats), ""])
        if body:
            lines.append(body.strip())
        else:
            lines.append("(内容为空)")
        return "\n".join(lines).rstrip() + "\n"
