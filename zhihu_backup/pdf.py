"""Optional PDF generation via the Selenium print API."""

from __future__ import annotations

import logging
import time
from html import escape
from pathlib import Path
from typing import Dict, Optional

import markdown as markdown_lib

from .config import timestamp_to_iso
from .markdown import soup_of
from .models import ContentItem

logger = logging.getLogger(__name__)

REMOVE_SELECTORS = [
    ".Post-Sub",
    ".ColumnPageHeader-Wrapper",
    ".RichContent-actions",
    ".ContentItem-actions",
    ".MoreAnswers",
    ".ViewAll",
    ".AppHeader",
    ".Reward",
    ".Question-sideColumn",
    ".Recommendations-Main",
    ".CornerButtons",
    ".Sticky",
    ".PinItem-actions",
    ".Comments-container",
    ".CommentList",
    ".CommentEditor",
    ".Post-Actions",
    ".Footer",
]

WAIT_SELECTOR = {
    "answer": ".RichContent-inner, .AnswerItem",
    "article": ".Post-RichTextContainer, .Post-Title",
    "pin": ".RichContent-inner, .PinItem",
}


def _wait_until_ready(browser, timeout: float = 20.0) -> bool:
    """Wait until the SPA has rendered real content, not its error/loading shell."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = browser.body_text()
        if text and len(text) > 120 and not browser.is_error_page():
            return True
        time.sleep(0.5)
    return False


def _rewrite_images(html: str, image_map: Dict[str, str]) -> str:
    if not html:
        return ""
    soup = soup_of(html)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for img in soup.find_all("img"):
        source = (
            img.get("data-original")
            or img.get("data-actualsrc")
            or img.get("data-src")
            or img.get("src")
            or ""
        )
        if source in image_map:
            img["src"] = image_map[source]
        elif source:
            img["src"] = source
        for attribute in ("data-original", "data-actualsrc", "data-src"):
            img.attrs.pop(attribute, None)
    body = soup.body
    return body.decode_contents() if body is not None else str(soup)


def _stats_line(item: ContentItem) -> str:
    if not any(
        [item.voteup_count, item.favorite_count, item.like_count, item.comment_count]
    ):
        return ""
    return (
        f"赞同 {item.voteup_count} · 收藏 {item.favorite_count} · "
        f"喜欢 {item.like_count} · 评论 {item.comment_count}"
    )


def build_content_html(
    item: ContentItem, item_dir: Path, image_map: Optional[Dict[str, str]] = None
) -> str:
    image_map = image_map or {}
    body = _rewrite_images(item.content_html, image_map)
    question = ""
    if item.type == "answer":
        question_html = _rewrite_images(item.extra.get("question_html") or "", image_map)
        if question_html:
            question = f"<h2>问题</h2>{question_html}<h2>回答</h2>"

    meta = []
    if item.author:
        meta.append(f"<div>作者：{escape(item.author)}</div>")
    meta.append(
        f'<div>原文：<a href="{escape(item.url)}">{escape(item.url)}</a></div>'
    )
    if item.created:
        meta.append(f"<div>发布时间：{timestamp_to_iso(item.created)}</div>")
    if item.type in ("answer", "article") and item.updated and item.updated != item.created:
        meta.append(f"<div>编辑时间：{timestamp_to_iso(item.updated)}</div>")
    stats = _stats_line(item)
    if stats:
        meta.append(f"<div>{escape(stats)}</div>")

    base_href = Path(item_dir).resolve().as_uri().rstrip("/") + "/"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<base href="{escape(base_href)}">
<title>{escape(item.title or item.id)}</title>
<style>
  @page {{ margin: 18mm; }}
  body {{
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 15px; line-height: 1.8; color: #1a1a1a;
    max-width: 820px; margin: 0 auto; padding: 8px 0;
  }}
  h1 {{ font-size: 26px; line-height: 1.4; margin: 0 0 14px; }}
  h2 {{ font-size: 20px; margin: 24px 0 10px; }}
  h3 {{ font-size: 17px; margin: 20px 0 8px; }}
  .meta {{ color: #555; font-size: 13px; margin: 12px 0 20px; }}
  .meta div {{ margin: 3px 0; }}
  img {{ max-width: 100%; height: auto; page-break-inside: avoid; }}
  a {{ color: #175199; text-decoration: none; word-break: break-all; }}
  blockquote {{ border-left: 3px solid #ddd; margin-left: 0; padding-left: 14px; color: #555; }}
  pre {{ white-space: pre-wrap; background: #f6f6f6; padding: 10px; overflow-wrap: anywhere; }}
  code {{ background: #f2f2f2; padding: 1px 4px; }}
  table {{ border-collapse: collapse; max-width: 100%; }}
  td, th {{ border: 1px solid #ddd; padding: 4px 8px; }}
</style>
</head>
<body>
<h1>{escape(item.title or item.id)}</h1>
<div class="meta">{''.join(meta)}</div>
<hr>
{question}
{body}
</body>
</html>
"""


def _pdf_contains_error(path: Path) -> bool:
    try:
        from pypdf import PdfReader
    except Exception:
        return False
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
    except Exception:
        return False
    return any(
        marker in text
        for marker in (
            "出了一点问题",
            "我们正在解决",
            "去往首页",
            "你似乎来到了没有知识存在的荒原",
        )
    )


def print_content_pdf(
    browser,
    item: ContentItem,
    path: Path,
    item_dir: Path,
    image_map: Optional[Dict[str, str]] = None,
) -> bool:
    """Render the saved content as a clean local page and print that instead."""
    path = Path(path)
    item_dir = Path(item_dir)
    html_path = item_dir / "content.pdf.html"
    try:
        html_path.write_text(
            build_content_html(item, item_dir, image_map), encoding="utf-8"
        )
        browser.get(html_path.as_uri(), wait_timeout=15)
        time.sleep(1.0)
        ok = browser.print_pdf(path, remove_selectors=[], remove_ads=False)
        if not ok:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return ok
    except Exception as exc:
        logger.warning("内容版 PDF 生成失败：%s", exc)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    finally:
        try:
            html_path.unlink(missing_ok=True)
        except OSError:
            pass


def build_markdown_html(markdown_text: str, item_dir: Path) -> str:
    """Convert a saved content.md into a clean local HTML document."""
    body = markdown_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    base_href = Path(item_dir).resolve().as_uri().rstrip("/") + "/"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<base href="{escape(base_href)}">
<title>知乎备份</title>
<style>
  @page {{ margin: 18mm; }}
  body {{
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 15px; line-height: 1.8; color: #1a1a1a;
    max-width: 820px; margin: 0 auto; padding: 8px 0;
  }}
  h1 {{ font-size: 26px; line-height: 1.4; margin: 0 0 14px; }}
  h2 {{ font-size: 20px; margin: 24px 0 10px; }}
  h3 {{ font-size: 17px; margin: 20px 0 8px; }}
  img {{ max-width: 100%; height: auto; page-break-inside: avoid; }}
  a {{ color: #175199; text-decoration: none; word-break: break-all; }}
  blockquote {{ border-left: 3px solid #ddd; margin-left: 0; padding-left: 14px; color: #555; }}
  pre {{ white-space: pre-wrap; background: #f6f6f6; padding: 10px; overflow-wrap: anywhere; }}
  code {{ background: #f2f2f2; padding: 1px 4px; }}
  table {{ border-collapse: collapse; max-width: 100%; }}
  td, th {{ border: 1px solid #ddd; padding: 4px 8px; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def print_markdown_pdf(
    browser, markdown_path: Path, path: Path, item_dir: Path
) -> bool:
    """Print a saved content.md directly, without opening Zhihu."""
    path = Path(path)
    item_dir = Path(item_dir)
    html_path = item_dir / "content.pdf.html"
    try:
        markdown_text = Path(markdown_path).read_text(encoding="utf-8")
        html_path.write_text(
            build_markdown_html(markdown_text, item_dir), encoding="utf-8"
        )
        browser.get(html_path.as_uri(), wait_timeout=15)
        time.sleep(0.8)
        ok = browser.print_pdf(path, remove_selectors=[], remove_ads=False)
        if not ok:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return ok
    except Exception as exc:
        logger.warning("Markdown PDF 生成失败：%s", exc)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    finally:
        try:
            html_path.unlink(missing_ok=True)
        except OSError:
            pass


def print_item_pdf(
    browser,
    item: ContentItem,
    path: Path,
    item_dir: Optional[Path] = None,
    image_map: Optional[Dict[str, str]] = None,
) -> bool:
    """Open the item (if needed) and print the current rendered page to PDF."""
    path = Path(path)
    item_dir = Path(item_dir) if item_dir else path.parent
    try:
        current = (browser.current_url or "").rstrip("/")
        target = (item.url or "").rstrip("/")
        if current != target:
            browser.get(
                item.url,
                wait_css=WAIT_SELECTOR.get(item.type),
                wait_timeout=20,
            )
            if not _wait_until_ready(browser):
                logger.info("页面未就绪，已改用已保存内容生成 PDF：%s", item.url)
                return print_content_pdf(browser, item, path, item_dir, image_map)
            time.sleep(1.0)
            browser.scroll(times=10, pause=0.3)
            browser.expand_buttons()
        if browser.is_error_page():
            logger.info("页面无法直接打印，已改用已保存内容生成 PDF：%s", item.url)
            return print_content_pdf(browser, item, path, item_dir, image_map)
        ok = browser.print_pdf(path, REMOVE_SELECTORS)
        if ok and _pdf_contains_error(path):
            logger.info("页面打印结果异常，已改用已保存内容重新生成 PDF：%s", item.url)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return print_content_pdf(browser, item, path, item_dir, image_map)
        if not ok:
            logger.info("页面 PDF 生成失败，改用已保存内容生成：%s", item.url)
            return print_content_pdf(browser, item, path, item_dir, image_map)
        return ok
    except Exception as exc:
        logger.warning("PDF 生成失败 [%s:%s]：%s，改用已保存内容", item.type, item.id, exc)
        return print_content_pdf(browser, item, path, item_dir, image_map)
