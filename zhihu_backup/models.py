"""Data models shared by fetchers, extractors and storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import now_iso


@dataclass
class Target:
    """A parsed Zhihu URL."""

    type: str  # answer / article / pin / zvideo / user
    id: str
    url: str
    question_id: Optional[str] = None
    url_token: Optional[str] = None


@dataclass
class UserProfile:
    url_token: str
    name: str = ""
    headline: str = ""
    avatar_url: str = ""
    url: str = ""
    answer_count: int = 0
    articles_count: int = 0
    pins_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    description: str = ""
    industry: str = ""
    industry_logo_url: str = ""
    industry_logo: str = ""
    employments: List[Dict[str, Any]] = field(default_factory=list)
    educations: List[Dict[str, Any]] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    ip_location: str = ""
    cover_url: str = ""
    cover_file: str = ""
    avatar_file: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url_token": self.url_token,
            "name": self.name,
            "headline": self.headline,
            "avatar_url": self.avatar_url,
            "avatar_file": self.avatar_file,
            "url": self.url,
            "answer_count": self.answer_count,
            "articles_count": self.articles_count,
            "pins_count": self.pins_count,
            "follower_count": self.follower_count,
            "following_count": self.following_count,
            "description": self.description,
            "industry": self.industry,
            "industry_logo_url": self.industry_logo_url,
            "industry_logo": self.industry_logo,
            "employments": self.employments,
            "educations": self.educations,
            "locations": self.locations,
            "ip_location": self.ip_location,
            "cover_url": self.cover_url,
            "cover_file": self.cover_file,
            "fetched_at": self.fetched_at,
        }


@dataclass
class ContentItem:
    """A single answer, article or pin, normalised from API or DOM."""

    type: str
    id: str
    url: str
    title: str = ""
    author: str = ""
    author_url: str = ""
    created: int = 0
    updated: int = 0
    voteup_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    like_count: int = 0
    content_html: str = ""
    source: str = "api"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "author_url": self.author_url,
            "created": self.created,
            "updated": self.updated,
            "voteup_count": self.voteup_count,
            "comment_count": self.comment_count,
            "favorite_count": self.favorite_count,
            "like_count": self.like_count,
            "source": self.source,
            "extra": self.extra,
        }


@dataclass
class ManifestEntry:
    type: str
    id: str
    status: str  # ok / failed
    dir: str = ""
    updated: int = 0
    saved_at: str = ""
    files: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "status": self.status,
            "dir": self.dir,
            "updated": self.updated,
            "saved_at": self.saved_at,
            "files": list(self.files),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManifestEntry":
        return cls(
            type=data.get("type", ""),
            id=str(data.get("id", "")),
            status=data.get("status", ""),
            dir=data.get("dir", ""),
            updated=int(data.get("updated") or 0),
            saved_at=data.get("saved_at", ""),
            files=list(data.get("files") or []),
            error=data.get("error", ""),
        )
