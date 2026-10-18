"""Zvideo extraction from the v4 API or a rendered zvideo page."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ..markdown import soup_of
from ..models import ContentItem
from ..videos import normalize_cover, normalize_variants, select_variant
from . import first_element, meta_content, parse_date_text, parse_zop, text_of, web_url

_ZVIDEO_URL_RE = re.compile(r"/zvideo/(\d+)")
_ZVIDEO_WEB = "https://www.zhihu.com/zvideo/{}"


def _as_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def from_api(raw: Dict[str, Any], video_id: str = "") -> ContentItem:
    video_id = str(raw.get("id") or video_id)
    video = raw.get("video") or {}
    if not isinstance(video, dict):
        video = {}
    title = raw.get("title") or video.get("title") or f"视频 {video_id}"
    author_obj = raw.get("author") or {}
    author = _as_name(author_obj) or str(raw.get("author_name") or "")
    author_url = ""
    if isinstance(author_obj, dict):
        author_url = web_url(str(author_obj.get("url") or ""))
    cover = (
        normalize_cover({"video": video, "cover": raw.get("cover_url") or raw.get("image_url")})
        or str(raw.get("cover_url") or raw.get("image_url") or "")
    )
    playlist = video.get("playlist") or raw.get("playlist") or {}
    part = {
        "type": "video",
        "id": video_id,
        "playlist": playlist,
        "cover": cover,
        "duration": raw.get("duration") or video.get("duration") or 0,
    }
    variants = normalize_variants(part)
    best = select_variant(variants, "best")
    description = raw.get("description") or raw.get("excerpt") or ""
    if isinstance(description, dict):
        description = description.get("text") or ""
    content_html = f"<p>{description}</p>" if description else ""

    return ContentItem(
        type="zvideo",
        id=video_id,
        url=_ZVIDEO_WEB.format(video_id),
        title=title,
        author=author,
        author_url=author_url,
        created=int(
            raw.get("published_at")
            or raw.get("created")
            or raw.get("created_time")
            or 0
        ),
        updated=int(
            raw.get("updated_at")
            or raw.get("updated")
            or raw.get("updated_time")
            or 0
        ),
        voteup_count=int(raw.get("voteup_count") or 0),
        comment_count=int(raw.get("comment_count") or 0),
        favorite_count=int(raw.get("favlists_count") or 0),
        like_count=int(raw.get("liked_count") or 0),
        content_html=content_html,
        source="api",
        extra={
            "video": {
                "playlist": playlist,
                "variants": variants,
                "url": best["url"] if best else "",
                "cover": cover,
                "duration": part["duration"],
                "width": (best or {}).get("width", 0),
                "height": (best or {}).get("height", 0),
                "bitrate": (best or {}).get("bitrate", 0),
                "size": (best or {}).get("size", 0),
            },
            "description": description,
        },
    )


def _find_zvideo_entity(data: Dict[str, Any], video_id: str) -> Optional[Dict[str, Any]]:
    state = data.get("initialState") or data.get("initial_state") or {}
    entities = state.get("entities") or {}
    zvideos = entities.get("zvideos") or {}
    if isinstance(zvideos, dict):
        if video_id and video_id in zvideos:
            return zvideos[video_id]
        for value in zvideos.values():
            if isinstance(value, dict):
                return value
    if isinstance(zvideos, list):
        for value in zvideos:
            if isinstance(value, dict) and str(value.get("id")) == video_id:
                return value
        if zvideos and isinstance(zvideos[0], dict):
            return zvideos[0]
    return None


def from_dom(html: str, url: str) -> ContentItem:
    soup = soup_of(html)
    match = _ZVIDEO_URL_RE.search(url)
    video_id = match.group(1) if match else ""

    initial = soup.find("script", id="js-initialData")
    if initial is not None and initial.string:
        try:
            data = json.loads(initial.string)
            entity = _find_zvideo_entity(data, video_id)
            if entity:
                item = from_api(entity, video_id)
                item.source = "selenium"
                return item
        except (TypeError, ValueError):
            pass

    title = text_of(soup, ["h1.ZVideo-title", "h1"])
    if not title:
        title = meta_content(soup, 'meta[property="og:title"]') or f"视频 {video_id}"
    author = text_of(soup, [".ZVideo-author", ".AuthorInfo-name"])
    cover = meta_content(soup, 'meta[property="og:image"]')
    cover_element = first_element(soup, ["img.ZVideo-cover", ".ZVideo-cover img"])
    if cover_element is not None:
        cover = (
            cover_element.get("src")
            or cover_element.get("data-original")
            or cover
        )
    description = text_of(soup, [".ZVideo-description"])
    video_element = first_element(soup, ["div.ZVideo-video[data-zop]", ".ZVideo-video"])
    zop = parse_zop(video_element) if video_element is not None else {}
    created = int(zop.get("created") or zop.get("createdTime") or 0)
    if not created:
        created = parse_date_text(text_of(soup, [".ContentItem-time"]))

    return ContentItem(
        type="zvideo",
        id=video_id,
        url=_ZVIDEO_WEB.format(video_id) if video_id else url,
        title=str(zop.get("title") or title),
        author=str(zop.get("authorName") or author),
        created=created,
        content_html=f"<p>{description}</p>" if description else "",
        source="selenium",
        extra={
            "video": {
                "cover": cover,
                "url": "",
                "variants": [],
            },
            "description": description,
        },
    )
