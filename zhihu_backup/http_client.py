"""HTTP session with cookie handling, retries and rate limiting."""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests

from .config import USER_AGENT
from .errors import ApiError, AuthError, VideoDownloadError

_LOGIN_WALL_MARKERS = (
    "有问题，就会有答案打开知乎App",
    "你似乎来到了没有知识存在的荒原",
    "安全验证",
)


def cookies_to_header(cookies: Any) -> str:
    """Build a Cookie header from a string, dict or Selenium cookie list."""
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return cookies.strip()
    if isinstance(cookies, dict):
        return "; ".join(f"{name}={value}" for name, value in cookies.items())
    parts = []
    for cookie in cookies:
        if not isinstance(cookie, dict) or "name" not in cookie:
            continue
        domain = str(cookie.get("domain") or "")
        if domain and "zhihu.com" not in domain:
            continue
        parts.append(f"{cookie['name']}={cookie.get('value', '')}")
    return "; ".join(parts)


class RateLimiter:
    def __init__(self, base_sleep: float = 1.5, jitter: float = 0.5):
        self.base_sleep = max(0.0, float(base_sleep))
        self.jitter = max(0.0, float(jitter))
        self._last: Optional[float] = None

    def wait(self) -> None:
        if self._last is not None and self.base_sleep > 0:
            delay = self.base_sleep + random.uniform(0, self.jitter)
            elapsed = time.monotonic() - self._last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last = time.monotonic()


class HttpClient:
    """A requests session preconfigured for Zhihu."""

    def __init__(
        self,
        cookies: Any = None,
        sleep: float = 1.5,
        jitter: float = 0.5,
        user_agent: str = USER_AGENT,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(sleep, jitter)
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.zhihu.com/",
            }
        )
        cookie_header = cookies_to_header(cookies)
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header

    @property
    def has_cookies(self) -> bool:
        return bool(self.session.headers.get("Cookie"))

    def set_cookies(self, cookies: Any) -> None:
        cookie_header = cookies_to_header(cookies)
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        apply_rate_limit: bool = True,
    ) -> requests.Response:
        if apply_rate_limit:
            self.limiter.wait()

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise ApiError(f"请求失败：{url}（{exc}）") from exc

            if response.status_code in (401, 403):
                raise AuthError(
                    f"知乎拒绝了请求（HTTP {response.status_code}）。"
                    "请确认 Cookie 有效；若失效请重新运行 login。"
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ApiError(f"知乎返回 HTTP {response.status_code}：{url}")
                if attempt + 1 < self.max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise last_error
            if response.status_code >= 400:
                raise ApiError(f"请求失败（HTTP {response.status_code}）：{url}")

            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                preview = response.text[:4000]
                if any(marker in preview for marker in _LOGIN_WALL_MARKERS):
                    raise AuthError(
                        "页面要求登录或安全验证，Cookie 可能已失效。请重新运行 login。"
                    )
            return response

        raise ApiError(f"请求失败：{url}（{last_error}）")

    def get_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        merged_headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }
        if headers:
            merged_headers.update(headers)
        response = self._request("GET", url, params=params, headers=merged_headers)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError(f"知乎返回了非 JSON 内容：{url}") from exc
        if not isinstance(data, dict):
            raise ApiError(f"知乎返回了意外的 JSON 结构：{url}")
        if data.get("error"):
            error = data.get("error")
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ApiError(f"知乎 API 错误：{message or error}")
        return data

    def get_bytes(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None,
    ) -> requests.Response:
        merged_headers = {"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
        if referer:
            merged_headers["Referer"] = referer
        if headers:
            merged_headers.update(headers)
        return self._request(
            "GET",
            url,
            headers=merged_headers,
            apply_rate_limit=False,
        )

    def stream_to_file(
        self,
        url: str,
        path: Path,
        *,
        referer: Optional[str] = None,
        expected_size: Optional[int] = None,
        chunk_size: int = 1024 * 1024,
    ) -> Path:
        """Stream a video to disk with Range resume and content validation."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.name + ".part")
        start = temp_path.stat().st_size if temp_path.exists() else 0

        headers = {
            "Accept": "video/*,application/octet-stream,*/*;q=0.8",
            "Referer": referer or "https://www.zhihu.com/",
        }
        if start:
            headers["Range"] = f"bytes={start}-"

        self.limiter.wait()
        try:
            response = self.session.get(
                url, headers=headers, stream=True, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise VideoDownloadError(f"视频请求失败：{url}（{exc}）") from exc

        try:
            if response.status_code in (401, 403):
                raise VideoDownloadError(
                    f"视频请求被拒绝（HTTP {response.status_code}），链接可能已过期：{url}"
                )
            if response.status_code == 416 and start:
                # Stale .part file; retry from scratch.
                temp_path.unlink(missing_ok=True)
                return self.stream_to_file(
                    url,
                    path,
                    referer=referer,
                    expected_size=expected_size,
                    chunk_size=chunk_size,
                )
            if response.status_code not in (200, 206):
                raise VideoDownloadError(
                    f"视频请求失败（HTTP {response.status_code}）：{url}"
                )

            content_type = (
                (response.headers.get("Content-Type") or "").split(";")[0].lower()
            )
            if content_type and not (
                content_type.startswith("video/")
                or content_type
                in (
                    "application/octet-stream",
                    "binary/octet-stream",
                    "application/mp4",
                )
            ):
                raise VideoDownloadError(
                    f"视频地址返回了非视频内容（{content_type}）：{url}"
                )

            mode = "ab" if response.status_code == 206 and start else "wb"
            written = start if mode == "ab" else 0
            with open(temp_path, mode) as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        handle.write(chunk)
                        written += len(chunk)

            if written <= 0:
                raise VideoDownloadError(f"视频内容为空：{url}")
            if expected_size and written < int(expected_size * 0.99):
                # Keep the partial file for a later resume; surface the problem.
                raise VideoDownloadError(
                    f"视频下载不完整：{written}/{expected_size} 字节：{url}"
                )

            os.replace(temp_path, path)
            return path
        finally:
            response.close()
