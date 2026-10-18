"""Article extraction from the v4 API or a rendered zhuanlan page."""

from __future__ import annotations

from typing import Any, Dict

from ..markdown import soup_of
from ..models import ContentItem
from . import (
    first_element,
    inner_html,
    meta_content,
    parse_action_counts,
    parse_content_times,
    text_of,
    web_url,
)


def from_api(raw: Dict[str, Any], author: str = "", author_url: str = "") -> ContentItem:
    article_id = str(raw.get("id") or "")
    author_obj = raw.get("author") or {}
    reaction = raw.get("reaction") or {}
    stats = reaction.get("statistics") or {}

    voteup = raw.get("voteup_count")
    if voteup is None:
        voteup = stats.get("up_vote_count")
    favorite = raw.get("favlists_count")
    if favorite is None:
        favorite = stats.get("favorites")
    like = raw.get("thanks_count")
    if like is None:
        like = stats.get("like_count")
    comment = raw.get("comment_count")
    if comment is None:
        comment = stats.get("comment_count")

    return ContentItem(
        type="article",
        id=article_id,
        url=web_url(raw.get("url") or "")
        or f"https://zhuanlan.zhihu.com/p/{article_id}",
        title=raw.get("title") or f"文章 {article_id}",
        author=author_obj.get("name") or author,
        author_url=web_url(author_obj.get("url") or "") or author_url,
        created=int(raw.get("created") or 0),
        updated=int(raw.get("updated") or 0),
        voteup_count=int(voteup or 0),
        comment_count=int(comment or 0),
        favorite_count=int(favorite or 0),
        like_count=int(like or 0),
        content_html=raw.get("content") or raw.get("content_html") or "",
        source="api",
    )


def from_dom(html: str, url: str) -> ContentItem:
    soup = soup_of(html)

    content_element = first_element(
        soup, ["div.Post-RichTextContainer", "div.Post-RichText", "div.RichText"]
    )
    title = text_of(soup, ["h1.Post-Title"])
    if not title:
        title = meta_content(soup, 'meta[property="og:title"]')

    author = meta_content(soup, 'div.AuthorInfo meta[itemprop="name"]')
    if not author:
        author = text_of(soup, [".AuthorInfo-name", ".AuthorInfo-name .UserLink-link"])

    created, updated = parse_content_times(soup)
    counts = parse_action_counts(soup)

    return ContentItem(
        type="article",
        id="",
        url=url,
        title=title,
        author=author,
        created=created,
        updated=updated,
        voteup_count=counts["voteup"],
        comment_count=counts["comment"],
        favorite_count=counts["favorite"],
        like_count=counts["like"],
        content_html=inner_html(content_element),
        source="selenium",
    )
