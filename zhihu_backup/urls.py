"""Zhihu URL parsing and normalisation."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from .errors import ZhihuBackupError
from .models import Target

_ANSWER_RE = re.compile(r"/question/(\d+)/answer/(\d+)")
_ARTICLE_RE = re.compile(r"/p/(\d+)")
_PIN_RE = re.compile(r"/pin/(\d+)")
_ZVIDEO_RE = re.compile(r"/zvideo/(\d+)")
_PEOPLE_RE = re.compile(r"/people/([^/?#]+)")
_ORG_RE = re.compile(r"/org/([^/?#]+)")
_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _ensure_scheme(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if "/" in value or "." in value:
        return "https://" + value
    return value


def parse_target(value: str) -> Optional[Target]:
    """Parse a Zhihu content URL into a Target, or return None."""
    url = _ensure_scheme(value)
    parsed = urlparse(url)
    path = parsed.path

    match = _ANSWER_RE.search(path)
    if match:
        question_id, answer_id = match.groups()
        canonical = f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
        return Target("answer", answer_id, canonical, question_id=question_id)

    if parsed.netloc.endswith("zhuanlan.zhihu.com"):
        match = _ARTICLE_RE.search(path)
        if match:
            article_id = match.group(1)
            return Target("article", article_id, f"https://zhuanlan.zhihu.com/p/{article_id}")

    match = _PIN_RE.search(path)
    if match:
        pin_id = match.group(1)
        return Target("pin", pin_id, f"https://www.zhihu.com/pin/{pin_id}")

    match = _ZVIDEO_RE.search(path)
    if match:
        video_id = match.group(1)
        return Target("zvideo", video_id, f"https://www.zhihu.com/zvideo/{video_id}")

    return None


def parse_user(value: str) -> Optional[str]:
    """Return the url_token from a people URL or a bare token."""
    value = value.strip()
    if not value:
        return None

    url = _ensure_scheme(value)
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        match = _PEOPLE_RE.search(parsed.path) or _ORG_RE.search(parsed.path)
        if match:
            return match.group(1)
        return None

    if _BARE_TOKEN_RE.match(value):
        return value
    return None


def resolve_user(value: str) -> str:
    token = parse_user(value)
    if not token:
        raise ZhihuBackupError(
            f"无法识别用户：{value!r}。请传入用户主页 URL 或 url_token，"
            "例如 https://www.zhihu.com/people/xxx"
        )
    return token


def is_content_url(value: str) -> bool:
    return parse_target(value) is not None


def canonical_url(target: Target) -> str:
    if target.type == "answer":
        return f"https://www.zhihu.com/question/{target.question_id}/answer/{target.id}"
    if target.type == "article":
        return f"https://zhuanlan.zhihu.com/p/{target.id}"
    if target.type == "pin":
        return f"https://www.zhihu.com/pin/{target.id}"
    if target.type == "zvideo":
        return f"https://www.zhihu.com/zvideo/{target.id}"
    return target.url
