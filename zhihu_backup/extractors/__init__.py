"""Shared helpers for DOM-based extraction."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable, Optional

from bs4 import BeautifulSoup

from ..markdown import soup_of

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2}))?")
_WAN_RE = re.compile(r"([\d.]+)\s*万")


def first_element(soup: BeautifulSoup, selectors: Iterable[str]):
    for selector in selectors:
        element = soup.select_one(selector)
        if element is not None:
            return element
    return None


def text_of(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    element = first_element(soup, selectors)
    return element.get_text(" ", strip=True) if element is not None else ""


def meta_content(soup: BeautifulSoup, selector: str) -> str:
    element = soup.select_one(selector)
    if element is None:
        return ""
    return (element.get("content") or "").strip()


def inner_html(element) -> str:
    if element is None:
        return ""
    return element.decode_contents()


def parse_date_text(text: Optional[str]) -> int:
    match = _DATE_RE.search(text or "")
    if not match:
        return 0
    year, month, day = (int(part) for part in match.group(1, 2, 3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    try:
        return int(datetime(year, month, day, hour, minute).timestamp())
    except ValueError:
        return 0


def parse_count(text: Optional[str]) -> int:
    text = (text or "").strip()
    match = _WAN_RE.search(text)
    if match:
        try:
            return int(float(match.group(1)) * 10_000)
        except ValueError:
            return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_zop(element) -> dict:
    if element is None:
        return {}
    raw = element.get("data-zop")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def absolute_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return "https://www.zhihu.com" + value
    return value


def web_url(value: str) -> str:
    """Convert API resource URLs into user-facing web URLs."""
    url = absolute_url(value)
    if not url:
        return ""
    for old, new in (
        ("/api/v4/people/", "/people/"),
        ("/api/v4/topics/", "/topic/"),
        ("/api/v4/orgs/", "/org/"),
    ):
        url = url.replace(old, new)
    return url


def parse_comment_count(scope) -> int:
    if scope is None:
        return 0
    text = scope.get_text(" ", strip=True)
    match = re.search(r"(\d[\d,.]*)\s*条评论", text)
    if not match:
        return 0
    return parse_count(match.group(1))


def parse_action_counts(scope) -> dict:
    """Read 赞同/收藏/喜欢/评论 counts from a Zhihu action bar."""
    result = {"voteup": 0, "favorite": 0, "like": 0, "comment": 0}
    if scope is None:
        return result
    actions = (
        scope.select_one(".ContentItem-actions")
        or scope.select_one(".RichContent-actions")
        or scope
    )
    vote = actions.select_one(".VoteButton--up") or actions.select_one("button.VoteButton")
    if vote is not None:
        result["voteup"] = parse_count(
            vote.get_text(" ", strip=True) or vote.get("aria-label") or ""
        )

    for button in actions.select("button"):
        label = button.get("aria-label") or ""
        text = button.get_text(" ", strip=True)
        if "收藏" in label or "收藏" in text:
            result["favorite"] = parse_count(text or label)
        elif "喜欢" in label or "喜欢" in text:
            result["like"] = parse_count(text or label)
        elif "条评论" in text:
            result["comment"] = parse_count(text)

    if not result["comment"]:
        match = re.search(r"(\d[\d,.]*)\s*条评论", actions.get_text(" ", strip=True))
        if match:
            result["comment"] = parse_count(match.group(1))
    return result


def parse_content_times(scope) -> tuple:
    """Return (published, edited) timestamps from a ContentItem-time element."""
    if scope is None:
        return 0, 0
    element = scope.select_one(".ContentItem-time")
    if element is None:
        return (
            parse_date_text(meta_content(scope, 'meta[itemprop="datePublished"]')),
            parse_date_text(meta_content(scope, 'meta[itemprop="dateModified"]')),
        )
    text = element.get_text(" ", strip=True)
    link = element.select_one("a")
    tooltip = ""
    if link is not None:
        tooltip = link.get("data-tooltip") or link.get("aria-label") or ""

    created = 0
    updated = 0
    if "编辑于" in text:
        updated = parse_date_text(text)
        created = parse_date_text(tooltip)
    else:
        created = parse_date_text(tooltip) or parse_date_text(text)
    if not created:
        created = parse_date_text(meta_content(scope, 'meta[itemprop="datePublished"]'))
    if not updated:
        updated = parse_date_text(meta_content(scope, 'meta[itemprop="dateModified"]'))
    return created, updated
