"""Pin (想法) extraction from the v4 API or a rendered pin page."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List

from ..config import timestamp_to_date
from ..markdown import soup_of, unwrap_zhihu_link
from ..models import ContentItem
from ..videos import normalize_cover, normalize_variants, select_variant
from . import (
    first_element,
    inner_html,
    parse_action_counts,
    parse_content_times,
    text_of,
    web_url,
)

_PIN_URL_RE = re.compile(r"/pin/(\d+)")


def _plain_text(html: str) -> str:
    return soup_of(html).get_text(" ", strip=True) if html else ""


def _video_url(part: Dict[str, Any]) -> str:
    best = select_variant(normalize_variants(part), "best")
    return str(best["url"]) if best else ""


def _cover_url(part: Dict[str, Any]) -> str:
    return normalize_cover(part)


def parts_to_html(parts: List[Dict[str, Any]]) -> str:
    chunks: List[str] = []
    for part in parts or []:
        part_type = part.get("type")
        if part_type == "text":
            content = part.get("content") or ""
            if content:
                chunks.append(f"<div>{content}</div>")
        elif part_type == "image":
            url = part.get("url") or part.get("src") or ""
            if url:
                chunks.append(
                    f'<figure><img src="{escape(url, quote=True)}" alt=""></figure>'
                )
        elif part_type == "video":
            play_url = _video_url(part)
            cover = _cover_url(part)
            if cover:
                chunks.append(
                    f'<figure><img src="{escape(cover, quote=True)}" alt=""></figure>'
                )
            if play_url:
                chunks.append(
                    f'<p><a href="{escape(play_url, quote=True)}" data-text="视频">视频</a></p>'
                )
        elif part_type == "link":
            url = unwrap_zhihu_link(part.get("url") or "")
            title = part.get("title") or part.get("title_text") or url
            if url:
                safe_url = escape(url, quote=True)
                safe_title = escape(title, quote=True)
                chunks.append(
                    f'<p><a href="{safe_url}" data-text="{safe_title}">{safe_title}</a></p>'
                )
    return "".join(chunks)


def from_api(raw: Dict[str, Any]) -> ContentItem:
    pin_id = str(raw.get("id") or "")
    author_obj = raw.get("author") or {}
    parts = raw.get("content") or []
    if not isinstance(parts, list):
        parts = []

    normalized_parts = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "video":
            part = dict(part)
            variants = normalize_variants(part)
            best = select_variant(variants, "best")
            part["video_variants"] = variants
            if best:
                part["play_url"] = part.get("play_url") or best["url"]
            cover = normalize_cover(part)
            if cover:
                part["cover"] = part.get("cover") or cover
            part["video_id"] = str(part.get("id") or part.get("video_id") or "")
        normalized_parts.append(part)

    text_bits = [
        _plain_text(part.get("content") or "")
        for part in normalized_parts
        if part.get("type") == "text"
    ]
    title = " ".join(bit for bit in text_bits if bit).strip()[:60]
    if not title:
        title = f"想法 {timestamp_to_date(int(raw.get('created') or 0))}"

    reaction = raw.get("reaction") or {}
    stats = reaction.get("statistics") or {}
    voteup = raw.get("reaction_count") or stats.get("up_vote_count")
    favorite = raw.get("favlists_count") or stats.get("favorites")
    like = raw.get("like_count") or raw.get("thanks_count") or stats.get("like_count")
    comment = raw.get("comment_count") or stats.get("comment_count")

    return ContentItem(
        type="pin",
        id=pin_id,
        url=f"https://www.zhihu.com/pin/{pin_id}",
        title=title,
        author=author_obj.get("name") or "",
        author_url=web_url(author_obj.get("url") or ""),
        created=int(raw.get("created") or 0),
        updated=int(raw.get("updated") or 0),
        voteup_count=int(voteup or 0),
        comment_count=int(comment or 0),
        favorite_count=int(favorite or 0),
        like_count=int(like or 0),
        content_html=parts_to_html(normalized_parts),
        source="api",
        extra={"parts": normalized_parts},
    )


def from_dom(html: str, url: str) -> ContentItem:
    soup = soup_of(html)
    match = _PIN_URL_RE.search(url)
    pin_id = match.group(1) if match else ""

    content_element = first_element(
        soup, ["div.RichContent-inner", "div.RichText", "div.PinItem .RichText"]
    )
    content_html = inner_html(content_element)
    title = _plain_text(content_html)[:60] or f"想法 {pin_id}"

    created, updated = parse_content_times(soup)
    counts = parse_action_counts(soup)
    author = text_of(soup, [".AuthorInfo-name", ".AuthorInfo-name .UserLink-link"])

    return ContentItem(
        type="pin",
        id=pin_id,
        url=url,
        title=title,
        author=author,
        created=created,
        updated=updated,
        voteup_count=counts["voteup"],
        comment_count=counts["comment"],
        favorite_count=counts["favorite"],
        like_count=counts["like"],
        content_html=content_html,
        source="selenium",
    )
