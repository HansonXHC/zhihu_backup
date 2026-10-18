"""Login, cookie persistence and cookie validation."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DEFAULT_STATE_DIR, LOGIN_TIMEOUT, now_iso
from .errors import AuthError
from .http_client import HttpClient, cookies_to_header

logger = logging.getLogger(__name__)


def state_dir_path(state_dir: Optional[str]) -> Path:
    return Path(state_dir or DEFAULT_STATE_DIR).expanduser().resolve()


def cookies_path(state_dir: Path) -> Path:
    return state_dir / "cookies.json"


def state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_cookies_file(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AuthError(f"无法读取 Cookie 文件：{path}（{exc}）") from exc
    if isinstance(data, dict) and "cookies" in data:
        return data["cookies"]
    return data


def load_cookies(state_dir: Path) -> Any:
    path = cookies_path(state_dir)
    if not path.exists():
        return None
    return load_cookies_file(path)


def import_cookie_source(cookie: Optional[str] = None, cookie_file: Optional[str] = None) -> Any:
    if cookie:
        return cookie
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if not path.exists():
            raise AuthError(f"Cookie 文件不存在：{path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthError(f"无法读取 Cookie 文件：{path}（{exc}）") from exc
        stripped = text.strip()
        if stripped.startswith(("[", "{")):
            try:
                return json.loads(stripped)
            except ValueError:
                pass
        return stripped
    return None


def save_cookies(state_dir: Path, cookies: List[Dict[str, Any]], me: Optional[Dict[str, Any]] = None) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"saved_at": now_iso(), "cookies": cookies}
    path = cookies_path(state_dir)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    if me:
        state = {
            "url_token": me.get("url_token") or me.get("url") or "",
            "name": me.get("name") or "",
            "saved_at": now_iso(),
        }
        with open(state_path(state_dir), "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)


def load_state(state_dir: Path) -> Dict[str, Any]:
    path = state_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get_cookies(args) -> Any:
    """Resolve cookies from CLI flags or the saved state directory."""
    imported = import_cookie_source(
        getattr(args, "cookie", None),
        getattr(args, "cookie_file", None),
    )
    if imported:
        return imported

    cookies = load_cookies(state_dir_path(getattr(args, "state_dir", None)))
    if not cookies:
        raise AuthError(
            "没有找到登录 Cookie。请先运行：python -m zhihu_backup login"
        )
    return cookies


def validate_cookies(cookies: Any, sleep: float = 0.0) -> Dict[str, Any]:
    """Check the saved cookies against /api/v4/me.

    A 403 can also mean the API now demands a signature, so when a z_c0 cookie
    exists we warn and continue instead of declaring the session invalid.
    """
    header = cookies_to_header(cookies)
    if not header:
        raise AuthError("Cookie 为空，请重新运行 login。")

    client = HttpClient(cookies=cookies, sleep=sleep)
    try:
        from .api import ZhihuApi

        me = ZhihuApi(client).me()
    except AuthError as exc:
        if "z_c0=" in header:
            logger.warning("无法通过 API 验证登录态（%s），将继续尝试。", exc)
            return {}
        raise
    except Exception as exc:  # network / signature issues are not fatal here
        logger.warning("登录态校验失败：%s；将继续尝试。", exc)
        return {}

    if not me.get("url_token") and not me.get("url"):
        logger.warning("登录态校验返回了意外结果，将继续尝试。")
    return me


def login(state_dir: Path, driver_path: Optional[str] = None, timeout: int = LOGIN_TIMEOUT) -> Dict[str, Any]:
    """Open a browser, wait for the user to log in, then persist cookies."""
    from .browser import Browser

    state_dir.mkdir(parents=True, exist_ok=True)
    browser = Browser(driver_path=driver_path)
    try:
        logger.info("正在打开知乎登录页，请在浏览器中完成登录……")
        browser.get("https://www.zhihu.com/signin")
        if not browser.wait_for_login(timeout=timeout):
            raise AuthError(
                "等待登录超时。请重新运行 login，并在浏览器中完成登录后再离开。"
            )

        # Give the page a moment to finish writing the session cookies.
        time.sleep(2)
        cookies = browser.get_cookies()
        if not cookies:
            raise AuthError("登录成功但未读取到 Cookie，请重试。")

        me = validate_cookies(cookies)
        save_cookies(state_dir, cookies, me)
        logger.info("登录成功，Cookie 已保存到 %s", cookies_path(state_dir))
        if me.get("name"):
            logger.info("当前账号：%s", me.get("name"))
        return me
    finally:
        browser.close()


def apply_cookies_to_driver(driver, cookies: Any) -> None:
    """Add cookies to a Selenium driver after navigating to zhihu.com."""
    if not cookies:
        return
    if isinstance(cookies, str):
        parsed = []
        for chunk in cookies.split(";"):
            if "=" not in chunk:
                continue
            name, value = chunk.split("=", 1)
            if name.strip():
                parsed.append({"name": name.strip(), "value": value.strip()})
        cookies = parsed
    if isinstance(cookies, dict):
        cookies = [{"name": name, "value": value} for name, value in cookies.items()]

    allowed = {"name", "value", "domain", "path", "secure", "expiry", "httpOnly"}
    for cookie in cookies:
        if not isinstance(cookie, dict) or "name" not in cookie:
            continue
        payload = {key: cookie[key] for key in allowed if key in cookie}
        try:
            driver.add_cookie(payload)
        except Exception as exc:  # individual cookies may be rejected
            logger.debug("跳过无法注入的 Cookie %s：%s", payload.get("name"), exc)
