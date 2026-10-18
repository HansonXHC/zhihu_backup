"""User profile extraction from the v4 API or a rendered profile page."""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

from ..markdown import soup_of
from ..models import UserProfile
from . import absolute_url, first_element, meta_content, text_of, web_url

_AVATAR_SIZE = "xll"
_LOGO_SIZE = "l"
_COVER_SIZE = "1440w"
_ALL_LABELS = ("所在行业", "职业经历", "教育经历", "个人简介")

_SIZE_TOKEN = r"(?:[a-z]{1,4}|\d+x\d+|\d+w)"
_SIZE_SUFFIX_RE = re.compile(
    rf"_{_SIZE_TOKEN}(\.(?:jpg|jpeg|png|webp))$", re.IGNORECASE
)
_CDN_RESIZE_RE = re.compile(r"(zhimg\.com)/(?:50|80|100|200)/", re.IGNORECASE)
_IMAGE_HOST = "picx.zhimg.com"


def clean_image_url(url: str, size: str = "") -> str:
    """Strip query strings, normalise the CDN host and set an image size."""
    if not url:
        return ""
    url = absolute_url(url.strip())
    url = url.split("?", 1)[0]
    parsed = urlparse(url)
    if parsed.netloc.endswith("zhimg.com"):
        url = urlunparse(parsed._replace(netloc=_IMAGE_HOST))
    url = _CDN_RESIZE_RE.sub(r"\1/", url)
    if "{size}" in url:
        url = url.replace("{size}", size or _LOGO_SIZE)
    if size:
        url = _SIZE_SUFFIX_RE.sub(rf"_{size}\1", url)
    return url


def upgrade_avatar_url(url: str) -> str:
    """Turn a thumbnail URL or avatar template into the full-size avatar URL."""
    return clean_image_url(url, _AVATAR_SIZE)


def upgrade_cover_url(url: str) -> str:
    """Upgrade a profile cover to the 1440w version used by the profile page."""
    if not url:
        return ""
    url = clean_image_url(url)
    if not url:
        return ""
    if _SIZE_SUFFIX_RE.search(url):
        return _SIZE_SUFFIX_RE.sub(rf"_{_COVER_SIZE}\1", url)
    return re.sub(
        r"(\.(?:jpg|jpeg|png|webp))$", rf"_{_COVER_SIZE}\1", url, flags=re.IGNORECASE
    )


def _first_image_url(obj: Any, size: str = _LOGO_SIZE) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in ("avatar_url_template", "avatar_url", "logo_url", "logo", "image_url", "avatar"):
        value = obj.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("avatar_url") or ""
        if isinstance(value, str) and value:
            return clean_image_url(value, size)
    return ""


def _normalize_ip(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("location") or value.get("ip_location") or ""
        if isinstance(value, dict):
            value = value.get("name") or ""
    text = str(value or "").strip()
    return re.sub(r"^IP\s*属地\s*[:：]?\s*", "", text).strip()


def _as_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def _normalize_employment(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"text": str(raw or ""), "logo_url": ""}
    company = raw.get("company")
    job = raw.get("job")
    company_name = _as_name(company)
    company_url = web_url(company.get("url") or "") if isinstance(company, dict) else ""
    job_name = _as_name(job)
    return {
        "company": company_name,
        "company_url": company_url,
        "job": job_name,
        "logo_url": _first_image_url(company),
        "created": int(raw.get("created") or 0),
        "updated": int(raw.get("updated") or 0),
    }


def _normalize_education(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"text": str(raw or ""), "logo_url": ""}
    school = raw.get("school")
    major = raw.get("major")
    school_name = _as_name(school)
    school_url = web_url(school.get("url") or "") if isinstance(school, dict) else ""
    return {
        "school": school_name,
        "school_url": school_url,
        "major": _as_name(major),
        "diploma": _as_name(raw.get("diploma")),
        "logo_url": _first_image_url(school),
        "created": int(raw.get("created") or 0),
    }


def _plain_text(value: Any) -> str:
    text = str(value or "")
    if "<" in text and ">" in text:
        return soup_of(text).get_text("\n", strip=True)
    return text.strip()


def from_api(raw: Dict[str, Any], url_token: str) -> UserProfile:
    template = raw.get("avatar_url_template") or ""
    avatar = upgrade_avatar_url(template or raw.get("avatar_url") or "")

    business = raw.get("business")
    if isinstance(business, dict):
        industry = str(business.get("name") or "")
    else:
        industry = str(business or "")
    # business.avatar_url is the generic topic avatar (a "#" placeholder), not
    # the icon shown on the profile page, so it is intentionally not used here.
    industry_logo_url = ""
    if not industry:
        category = raw.get("industry_category")
        industry = _as_name(category)

    locations: List[str] = []
    for location in raw.get("locations") or []:
        name = _as_name(location)
        if name:
            locations.append(name)

    return UserProfile(
        url_token=raw.get("url_token") or url_token,
        name=raw.get("name") or "",
        headline=_plain_text(raw.get("headline")),
        avatar_url=avatar,
        url=web_url(raw.get("url") or f"/people/{url_token}"),
        answer_count=int(raw.get("answer_count") or 0),
        articles_count=int(raw.get("articles_count") or 0),
        pins_count=int(raw.get("pins_count") or 0),
        follower_count=int(raw.get("follower_count") or 0),
        following_count=int(raw.get("following_count") or 0),
        description=_plain_text(raw.get("description")),
        industry=industry,
        industry_logo_url=industry_logo_url,
        employments=[
            _normalize_employment(item) for item in (raw.get("employments") or [])
        ],
        educations=[
            _normalize_education(item) for item in (raw.get("educations") or [])
        ],
        locations=locations,
        ip_location=_normalize_ip(raw.get("ip_info")),
        cover_url=upgrade_cover_url(
            raw.get("cover_url_template") or raw.get("cover_url") or ""
        ),
        raw=raw,
    )


def _row_for(label_node):
    label = str(label_node).strip()
    tag = label_node.parent
    current = tag
    for _ in range(5):
        if current is None:
            break
        text = current.get_text(" ", strip=True)
        images = current.find_all("img")
        if len(text) > len(label) + 1 or images:
            return current
        current = current.parent
    return tag


def _clean_label_text(text: str) -> str:
    for label in _ALL_LABELS:
        text = text.replace(label, "")
    return text.strip(" \n\u00a0·:：")


def _merge_lines(text: str) -> List[str]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    merged: List[str] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if line in ("·", "・", ":", "："):
            if merged and index + 1 < len(raw_lines):
                merged[-1] = merged[-1] + " " + line + " " + raw_lines[index + 1]
                index += 2
                continue
            index += 1
            continue
        if line.startswith(("·", "・")) and merged:
            merged[-1] = merged[-1] + " " + line
            index += 1
            continue
        merged.append(line)
        index += 1
    cleaned = [item.strip(" ·:：") for item in merged]
    return [item for item in cleaned if item]


def _label_row_data(soup, label: str):
    for node in soup.find_all(string=lambda s: s and s.strip() == label):
        row = _row_for(node)
        if row is None:
            continue
        text = _clean_label_text(row.get_text("\n", strip=True))
        images = []
        for img in row.find_all("img"):
            src = img.get("src") or img.get("data-original") or img.get("data-actualsrc") or ""
            if src:
                images.append(absolute_url(src))
        return _merge_lines(text), images
    return [], []


def _entries_from_dom(soup, label: str) -> List[Dict[str, Any]]:
    lines, images = _label_row_data(soup, label)
    entries = []
    for index, line in enumerate(lines):
        entries.append(
            {
                "text": line,
                "logo_url": images[index] if index < len(images) else "",
            }
        )
    return entries


def from_dom(html: str, url_token: str) -> UserProfile:
    soup = soup_of(html)
    name_element = first_element(soup, ["h1.ProfileHeader-name", ".ProfileHeader-name"])
    name = name_element.get_text(" ", strip=True) if name_element is not None else ""
    headline = text_of(
        soup,
        [
            "div.ProfileHeader-headline",
            ".ProfileHeader-headline",
        ],
    )
    if not headline and name_element is not None:
        sibling = name_element.find_next_sibling()
        if sibling is not None and sibling.get_text(strip=True):
            headline = sibling.get_text(" ", strip=True)
        elif name_element.parent is not None:
            parent_text = name_element.parent.get_text(" ", strip=True)
            headline = parent_text.replace(name, "", 1).strip()
    if not name:
        name = meta_content(soup, 'meta[property="og:title"]')
    if not headline:
        headline = meta_content(soup, 'meta[property="og:description"]')
    for marker in ("回答数", "关注者", "获得"):
        if marker in headline:
            headline = headline.split(marker, 1)[0].strip()

    avatar_element = soup.select_one("img.Avatar") or soup.select_one(".Avatar img")
    avatar = ""
    if avatar_element is not None:
        avatar = (
            avatar_element.get("src")
            or avatar_element.get("data-original")
            or avatar_element.get("data-actualsrc")
            or ""
        )
    if not avatar:
        avatar = meta_content(soup, 'meta[property="og:image"]')

    cover = ""
    cover_element = soup.select_one("img.ProfileHeader-cover") or soup.select_one(
        ".ProfileHeader-cover img"
    )
    if cover_element is not None:
        cover = (
            cover_element.get("src")
            or cover_element.get("data-original")
            or cover_element.get("data-actualsrc")
            or ""
        )
    if not cover:
        cover_container = soup.select_one(".ProfileHeader-cover")
        if cover_container is not None:
            style = cover_container.get("style") or ""
            match = re.search(r'url\(["\']?([^"\')]+)', style)
            if match:
                cover = match.group(1)

    industry_lines, industry_images = _label_row_data(soup, "所在行业")
    description_lines, _ = _label_row_data(soup, "个人简介")
    body_text = soup.get_text(" ", strip=True)
    ip_match = re.search(r"IP\s*属地\s*([^\s]+)", body_text)

    return UserProfile(
        url_token=url_token,
        name=name,
        headline=headline,
        avatar_url=upgrade_avatar_url(avatar),
        url=f"https://www.zhihu.com/people/{url_token}",
        description="\n".join(description_lines),
        industry=industry_lines[0] if industry_lines else "",
        industry_logo_url=industry_images[0] if industry_images else "",
        employments=_entries_from_dom(soup, "职业经历"),
        educations=_entries_from_dom(soup, "教育经历"),
        ip_location=ip_match.group(1) if ip_match else "",
        cover_url=upgrade_cover_url(cover),
    )


def _entry_text(entry: Dict[str, Any]) -> str:
    if entry.get("text"):
        return str(entry["text"])
    parts = [
        entry.get("company") or entry.get("school") or "",
        entry.get("job") or entry.get("major") or "",
    ]
    return " · ".join(part for part in parts if part)


def _logo_markdown(entry: Dict[str, Any]) -> str:
    source = entry.get("logo_file") or entry.get("logo_url")
    return f"![图标]({source}) " if source else ""


def render_markdown(profile: UserProfile) -> str:
    """Render a human-readable profile.md."""
    lines = [f"# {profile.name or profile.url_token}", ""]
    if profile.headline:
        lines.extend([profile.headline, ""])
    if profile.cover_file:
        lines.extend([f"![背景]({profile.cover_file})", ""])
    if profile.avatar_file:
        lines.extend([f"![头像]({profile.avatar_file})", ""])
    lines.extend([f"**主页**：{profile.url}", ""])
    if profile.ip_location:
        lines.extend([f"**IP 属地**：{profile.ip_location}", ""])

    if profile.industry:
        logo = ""
        if profile.industry_logo:
            logo = f"![图标]({profile.industry_logo}) "
        lines.extend([f"**所在行业**：{logo}{profile.industry}", ""])

    if profile.employments:
        lines.extend(["## 职业经历", ""])
        for entry in profile.employments:
            lines.append(f"- {_logo_markdown(entry)}{_entry_text(entry)}")
        lines.append("")

    if profile.educations:
        lines.extend(["## 教育经历", ""])
        for entry in profile.educations:
            lines.append(f"- {_logo_markdown(entry)}{_entry_text(entry)}")
        lines.append("")

    if profile.description:
        lines.extend(["## 个人简介", "", profile.description, ""])

    if profile.locations:
        lines.extend([f"**所在地**：{'、'.join(profile.locations)}", ""])

    return "\n".join(lines).rstrip() + "\n"
