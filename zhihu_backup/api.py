"""Thin wrapper around the Zhihu v4 web API."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional
from urllib.parse import quote

from .config import API_ROOT, PAGE_LIMIT
from .errors import ApiError, EnumerationError
from .http_client import HttpClient


def _created_of(kind: str, raw: Dict[str, Any]) -> int:
    if kind == "answer":
        value = raw.get("created_time", raw.get("created"))
    elif kind == "zvideos":
        value = raw.get("published_at", raw.get("created", raw.get("created_time")))
    else:
        value = raw.get("created", raw.get("created_time"))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _item_id(raw: Dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("token") or "")


class ZhihuApi:
    def __init__(self, http: HttpClient):
        self.http = http

    # ---------------------------------------------------------------- profile
    def me(self) -> Dict[str, Any]:
        return self.http.get_json(f"{API_ROOT}/api/v4/me")

    def user_profile(self, url_token: str) -> Dict[str, Any]:
        token = quote(url_token, safe="")
        include = (
            "locations,employments,gender,educations,business,mcn_company,"
            "follower_count,following_count,answer_count,articles_count,"
            "pins_count,zvideo_count,description,cover_url,cover_url_template"
        )
        return self.http.get_json(
            f"{API_ROOT}/api/v4/members/{token}",
            params={"include": include},
            headers={"Referer": f"{API_ROOT}/people/{url_token}"},
        )

    # ------------------------------------------------------------------ lists
    def _list_page(self, kind: str, url_token: str, offset: int) -> Dict[str, Any]:
        token = quote(url_token, safe="")
        if kind == "answers":
            url = f"{API_ROOT}/api/v4/members/{token}/answers"
            params = {
                "include": (
                    "data[*].content,voteup_count,comment_count,thanks_count,"
                    "favlists_count,reaction,created_time,updated_time,question"
                ),
                "limit": PAGE_LIMIT,
                "offset": offset,
                "sort_by": "created",
            }
            referer = f"{API_ROOT}/people/{url_token}/answers"
        elif kind == "articles":
            url = f"{API_ROOT}/api/v4/members/{token}/articles"
            params = {
                "include": (
                    "data[*].content,voteup_count,comment_count,thanks_count,"
                    "favlists_count,reaction,created,updated"
                ),
                "limit": PAGE_LIMIT,
                "offset": offset,
                "sort_by": "created",
            }
            referer = f"{API_ROOT}/people/{url_token}/posts"
        elif kind == "pins":
            url = f"{API_ROOT}/api/v4/members/{token}/pins"
            params = {"limit": PAGE_LIMIT, "offset": offset}
            referer = f"{API_ROOT}/people/{url_token}/pins"
        elif kind == "zvideos":
            url = f"{API_ROOT}/api/v4/members/{token}/zvideos"
            params = {"limit": PAGE_LIMIT, "offset": offset}
            referer = f"{API_ROOT}/people/{url_token}/zvideo"
        else:
            raise ValueError(f"unsupported kind: {kind}")

        return self.http.get_json(url, params=params, headers={"Referer": referer})

    def iter_user_items(
        self,
        url_token: str,
        kind: str,
        *,
        max_items: Optional[int] = None,
        since_ts: int = 0,
    ) -> Iterator[Dict[str, Any]]:
        """Yield raw answer/article/pin objects for a user, newest first."""
        offset = 0
        yielded = 0
        seen_ids: set[str] = set()

        while True:
            try:
                page = self._list_page(kind, url_token, offset)
            except Exception as exc:
                raise EnumerationError(
                    f"枚举 {url_token} 的 {kind} 失败（offset={offset}）：{exc}",
                    seen_ids,
                ) from exc

            data = page.get("data") or []
            paging = page.get("paging") or {}

            if not isinstance(data, list):
                raise EnumerationError(
                    f"枚举 {url_token} 的 {kind} 时返回了意外的 data 结构",
                    seen_ids,
                )

            if not data:
                if paging.get("is_end"):
                    return
                raise EnumerationError(
                    f"枚举 {url_token} 的 {kind} 时返回空列表但未到末尾（offset={offset}）",
                    seen_ids,
                )

            for raw in data:
                item_id = _item_id(raw)
                if item_id:
                    seen_ids.add(item_id)
                created = _created_of(kind, raw)
                if since_ts and created and created < since_ts:
                    return
                yield raw
                yielded += 1
                if max_items and yielded >= max_items:
                    return

            total = paging.get("totals")
            if paging.get("is_end"):
                return
            if isinstance(total, int) and offset + len(data) >= total:
                return
            offset += len(data)
            if offset > 1_000_000:
                return

    # ----------------------------------------------------------------- detail
    def answer_detail(self, answer_id: str) -> Dict[str, Any]:
        return self.http.get_json(
            f"{API_ROOT}/api/v4/answers/{answer_id}",
            params={
                "include": (
                    "content,voteup_count,comment_count,thanks_count,"
                    "favlists_count,reaction,created_time,updated_time,question"
                )
            },
            headers={"Referer": f"{API_ROOT}/"},
        )

    def article_detail(self, article_id: str) -> Dict[str, Any]:
        return self.http.get_json(
            f"{API_ROOT}/api/v4/articles/{article_id}",
            params={
                "include": (
                    "content,voteup_count,comment_count,thanks_count,"
                    "favlists_count,reaction,created,updated"
                )
            },
            headers={"Referer": f"https://zhuanlan.zhihu.com/p/{article_id}"},
        )

    def pin_detail(self, pin_id: str) -> Dict[str, Any]:
        return self.http.get_json(
            f"{API_ROOT}/api/v4/pins/{pin_id}",
            headers={"Referer": f"{API_ROOT}/pin/{pin_id}"},
        )

    def zvideo_detail(self, video_id: str) -> Dict[str, Any]:
        return self.http.get_json(
            f"{API_ROOT}/api/v4/zvideos/{video_id}",
            headers={"Referer": f"{API_ROOT}/zvideo/{video_id}"},
        )

    def question_detail(self, question_id: str) -> Dict[str, Any]:
        return self.http.get_json(
            f"{API_ROOT}/api/v4/questions/{question_id}",
            params={"include": "detail"},
            headers={"Referer": f"{API_ROOT}/question/{question_id}"},
        )
