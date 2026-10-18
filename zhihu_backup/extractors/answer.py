"""Answer extraction from the v4 API or a rendered question page."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..markdown import soup_of
from ..models import ContentItem
from . import (
    first_element,
    inner_html,
    meta_content,
    parse_action_counts,
    parse_content_times,
    parse_zop,
    text_of,
    web_url,
)

_ANSWER_URL_RE = re.compile(r"/question/(\d+)/answer/(\d+)")


def from_api(raw: Dict[str, Any], author: str = "", author_url: str = "") -> ContentItem:
    question = raw.get("question") or {}
    question_id = str(question.get("id") or "")
    answer_id = str(raw.get("id") or "")
    title = question.get("title") or raw.get("title") or f"回答 {answer_id}"
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
        type="answer",
        id=answer_id,
        url=f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}",
        title=title,
        author=author_obj.get("name") or author,
        author_url=web_url(author_obj.get("url") or "") or author_url,
        created=int(raw.get("created_time") or raw.get("created") or 0),
        updated=int(raw.get("updated_time") or raw.get("updated") or 0),
        voteup_count=int(voteup or 0),
        comment_count=int(comment or 0),
        favorite_count=int(favorite or 0),
        like_count=int(like or 0),
        content_html=raw.get("content") or raw.get("content_html") or "",
        source="api",
        extra={
            "question_id": question_id,
            "question_title": title,
            # List endpoints omit voteup_count; fetch the detail for full stats.
            "needs_stats": raw.get("voteup_count") is None,
        },
    )


def from_dom(html: str, url: str) -> ContentItem:
    soup = soup_of(html)
    match = _ANSWER_URL_RE.search(url)
    question_id = match.group(1) if match else ""
    answer_id = match.group(2) if match else ""

    scope = None
    for candidate in soup.select("div.AnswerItem"):
        zop = parse_zop(candidate)
        if str(zop.get("itemId") or "") == answer_id:
            scope = candidate
            break
    if scope is None:
        answer_items = soup.select("div.AnswerItem")
        scope = answer_items[0] if answer_items else soup

    content_element = first_element(scope, ["div.RichContent-inner", "div.RichText"])
    if content_element is None:
        content_element = first_element(soup, ["div.RichContent-inner", "div.RichText"])

    question_element = first_element(
        soup, ["div.QuestionRichText", "div.QuestionRichText--collapsed"]
    )

    title = text_of(soup, ["h1.QuestionHeader-title"])
    if not title:
        title = meta_content(soup, 'meta[property="og:title"]') or f"回答 {answer_id}"

    author = meta_content(scope, 'div.AuthorInfo meta[itemprop="name"]')
    if not author:
        author = text_of(scope, [".AuthorInfo-name", ".AuthorInfo-name .UserLink-link"])

    created, updated = parse_content_times(scope)
    counts = parse_action_counts(scope)

    return ContentItem(
        type="answer",
        id=answer_id,
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
        extra={
            "question_id": question_id,
            "question_title": title,
            "question_html": inner_html(question_element),
        },
    )
