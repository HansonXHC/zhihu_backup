"""Selenium browser used for login, DOM fallback and PDF printing."""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any, List, Optional

from .config import SCROLL_TIMES, USER_AGENT
from .errors import AuthError

logger = logging.getLogger(__name__)


class Browser:
    """A lazily created Edge driver with light anti-automation measures."""

    def __init__(
        self,
        headless: bool = False,
        driver_path: Optional[str] = None,
        page_load_timeout: int = 30,
        script_timeout: int = 20,
    ):
        self.headless = headless
        self.driver_path = driver_path
        self.page_load_timeout = page_load_timeout
        self.script_timeout = script_timeout
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = self._create_driver()
        return self._driver

    def _create_driver(self):
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions

        options = EdgeOptions()
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("disable-blink-features=AutomationControlled")
        options.add_argument("--lang=zh-CN,zh,zh-TW,en-US,en")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.page_load_strategy = "normal"
        if self.headless:
            options.add_argument("--headless=new")

        if self.driver_path:
            from selenium.webdriver.edge.service import Service

            service = Service(executable_path=self.driver_path)
            driver = webdriver.Edge(options=options, service=service)
        else:
            # Selenium Manager resolves/downloads the matching driver.
            driver = webdriver.Edge(options=options)

        driver.set_page_load_timeout(self.page_load_timeout)
        driver.set_script_timeout(self.script_timeout)
        try:
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": USER_AGENT}
            )
        except Exception as exc:
            logger.debug("反自动化初始化部分失败：%s", exc)
        return driver

    def get(self, url: str, wait_css: Optional[str] = None, wait_timeout: float = 15.0) -> None:
        from selenium.common.exceptions import TimeoutException

        try:
            self.driver.get(url)
        except TimeoutException:
            # Zhihu pages often keep long-polling requests open; the content is
            # usually already rendered, so continue instead of failing the item.
            logger.warning("页面加载超时，继续解析：%s", url)
        if wait_css:
            self.wait_for_css(wait_css, timeout=wait_timeout)

    def wait_for_css(self, css: str, timeout: float = 15.0) -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            return True
        except Exception:
            return False

    def wait_for_login(self, timeout: float = 600.0) -> bool:
        """Poll until a z_c0 cookie appears, meaning the user has logged in."""
        deadline = time.monotonic() + timeout
        announced = False
        while time.monotonic() < deadline:
            try:
                names = {cookie.get("name") for cookie in self.driver.get_cookies()}
            except Exception:
                names = set()
            if "z_c0" in names:
                return True
            if not announced:
                logger.info(
                    "请在弹出的浏览器中完成登录；登录成功后会自动继续（最长等待 %d 秒）。",
                    int(timeout),
                )
                announced = True
            time.sleep(2)
        return False

    def scroll(self, times: int = SCROLL_TIMES, pause: float = 0.4) -> None:
        try:
            height = self.driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);"
            )
        except Exception:
            return
        step = max(400, int(height / max(1, times)))
        for index in range(1, times + 1):
            try:
                self.driver.execute_script(
                    "window.scrollTo(0, arguments[0]);", step * index
                )
            except Exception:
                break
            time.sleep(pause)

    def expand_buttons(self) -> None:
        """Click common "expand" buttons inside rich content."""
        script = """
        const roots = document.querySelectorAll(
          '.RichContent-inner, .Post-RichTextContainer, .QuestionRichText, .RichText'
        );
        const wanted = ['展开', '阅读全文', '显示全部', '展开阅读全文'];
        for (const root of roots) {
          const buttons = root.querySelectorAll('button, .Button');
          for (const button of buttons) {
            const text = (button.innerText || '').trim();
            if (wanted.some(w => text.includes(w))) {
              try { button.click(); } catch (e) {}
            }
          }
        }
        """
        try:
            self.driver.execute_script(script)
            time.sleep(0.5)
        except Exception:
            pass

    @property
    def html(self) -> str:
        return self.driver.page_source

    @property
    def current_url(self) -> str:
        return self.driver.current_url

    def check_login(self) -> None:
        if "signin" in (self.current_url or ""):
            raise AuthError("登录已失效，页面跳转到了登录页。请重新运行 login。")

    def body_text(self) -> str:
        try:
            return self.driver.execute_script(
                "return document.body ? document.body.innerText : ''"
            ) or ""
        except Exception:
            return ""

    def is_error_page(self) -> bool:
        text = self.body_text()
        return any(
            marker in text
            for marker in (
                "出了一点问题",
                "我们正在解决",
                "去往首页",
                "你似乎来到了没有知识存在的荒原",
                "页面不存在",
            )
        )

    def get_cookies(self) -> List[dict]:
        try:
            return self.driver.get_cookies()
        except Exception:
            return []

    def save_cookies_to(self, driver, cookies: Any) -> None:
        from .auth import apply_cookies_to_driver

        try:
            driver.get("https://www.zhihu.com/")
        except Exception as exc:
            raise AuthError(f"无法打开知乎：{exc}") from exc
        apply_cookies_to_driver(driver, cookies)

    def remove_ad_elements(self) -> None:
        """Hide ads, comment sections and other noise before PDF printing."""
        script = """
        const selectors = [
          '[class*="advert"]', '[class*="Advert"]', '[class*="ADVERT"]',
          '[id*="advert"]', '[id*="Advert"]', '[id*="ADVERT"]',
          '[class*="KfeCollection"]', '[class*="Kfe-"]', '[id*="Kfe"]',
          '[class*="ad-slot"]', '[id*="ad-slot"]',
          '[class*="ad_slot"]', '[id*="ad_slot"]',
          '[data-za-detail-view-path-module="Ad"]', '[data-za-module="Ad"]',
          '[data-ad]', '[data-ad-slot]', '[data-advert]',
          '.Comments-container', '.CommentList', '.CommentEditor',
          '.CommentsV2', '.CommentEditorV2', '.Post-Actions', '.Post-Sub',
          '.Recommendations-Main', '.Footer', '.CornerButtons', '.Sticky',
          'iframe[src*="pos.baidu"]', 'iframe[src*="cpro"]',
          'iframe[src*="tanx"]', 'iframe[src*="alimama"]',
          'iframe[src*="googleads"]', 'iframe[src*="doubleclick"]'
        ];
        let hidden = 0;
        const hide = el => {
          if (!el || !el.style) return;
          el.style.setProperty('display', 'none', 'important');
          hidden += 1;
        };
        for (const selector of selectors) {
          document.querySelectorAll(selector).forEach(hide);
        }

        const adPattern = /(的广告|广告|赞助|广告推广)/;
        for (const el of document.querySelectorAll('body *')) {
          const text = (el.innerText || '').trim();
          if (!text || text.length > 400 || !adPattern.test(text)) continue;
          // Never hide the article title or body, even if they mention 广告.
          if (el.closest('.Post-Title, .Post-RichTextContainer, .Post-RichText, .RichContent-inner')) continue;
          let node = el;
          for (let i = 0; i < 5 && node.parentElement; i++) {
            node = node.parentElement;
            if (node === document.body) break;
            if (node.querySelector && node.querySelector('.Post-RichTextContainer, .Post-RichText, .Post-Title')) {
              break;
            }
            const nodeText = (node.innerText || '').trim();
            if (nodeText.length > 0 && nodeText.length < 600) hide(node);
          }
        }
        return hidden;
        """
        try:
            hidden = self.driver.execute_script(script)
            logger.debug("PDF 前隐藏广告/评论区元素：%s", hidden)
        except Exception as exc:
            logger.debug("广告清理失败：%s", exc)

    def print_pdf(
        self,
        path: Path,
        remove_selectors: Optional[List[str]] = None,
        remove_ads: bool = True,
    ) -> bool:
        """Print the current page to PDF; returns False instead of raising."""
        from selenium.webdriver.common.print_page_options import PrintOptions

        if remove_selectors:
            script = """
            const selectors = arguments[0];
            for (const selector of selectors) {
              document.querySelectorAll(selector).forEach(el => el.remove());
            }
            """
            try:
                self.driver.execute_script(script, remove_selectors)
            except Exception:
                pass

        if remove_ads:
            self.remove_ad_elements()

        options = PrintOptions()
        options.background = True
        options.shrink_to_fit = True
        options.scale = 1.0
        try:
            encoded = self.driver.print_page(options)
            data = base64.b64decode(encoded)
            if not data.startswith(b"%PDF-") or len(data) < 1024:
                logger.warning("PDF 数据异常，已丢弃：%s", path)
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
            return True
        except Exception as exc:
            logger.warning("PDF 生成失败（%s）：%s", path, exc)
            return False

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
