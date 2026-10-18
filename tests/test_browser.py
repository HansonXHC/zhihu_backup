from zhihu_backup.browser import Browser


class FakeDriver:
    def __init__(self, text):
        self.text = text
        self.scripts = []

    def execute_script(self, script):
        self.scripts.append(script)
        return self.text


def test_is_error_page_detects_zhihu_error_shell():
    browser = Browser()
    browser._driver = FakeDriver("出了一点问题 我们正在解决 去往首页")
    assert browser.is_error_page() is True


def test_is_error_page_allows_normal_content():
    browser = Browser()
    browser._driver = FakeDriver("这是一篇正常文章")
    assert browser.is_error_page() is False
