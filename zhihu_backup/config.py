"""Shared constants and small helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

DEFAULT_OUTPUT = "backup"
DEFAULT_STATE_DIR = ".zhihu_backup"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

API_ROOT = "https://www.zhihu.com"
WEB_ROOT = "https://www.zhihu.com"
ZHIHU_COOKIE_DOMAIN = ".zhihu.com"

PAGE_LIMIT = 20
DEFAULT_SLEEP = 1.5
DEFAULT_BROWSER_SLEEP = 3.0
LOGIN_TIMEOUT = 600
SCROLL_TIMES = 18

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def safe_component(value: object, max_length: int = 80, fallback: str = "untitled") -> str:
    """Turn arbitrary text into a safe Windows path component.

    Chinese characters are preserved; only characters that Windows forbids and
    control characters are removed.
    """
    if value is None:
        return fallback
    text = _INVALID_FILENAME_CHARS.sub("", str(value))
    text = _WHITESPACE.sub(" ", text).strip(" .")
    if len(text) > max_length:
        text = text[:max_length].strip(" .")
    return text or fallback


def timestamp_to_date(timestamp: Optional[int]) -> str:
    if not timestamp:
        return "unknown-date"
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y%m%d")
    except (OverflowError, OSError, ValueError):
        return "unknown-date"


def timestamp_to_iso(timestamp: Optional[int]) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.fromtimestamp(int(timestamp)).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def content_dir_name(created: Optional[int], item_id: str, title: str) -> str:
    """Build the per-content directory name: YYYYMMDD-<id>-<safe title>."""
    return f"{timestamp_to_date(created)}-{safe_component(item_id, 40)}-{safe_component(title, 80)}"
