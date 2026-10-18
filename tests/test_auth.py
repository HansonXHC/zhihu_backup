from zhihu_backup import auth
from zhihu_backup.api import ZhihuApi


def test_validate_cookies_uses_api_me(monkeypatch):
    monkeypatch.setattr(
        ZhihuApi, "me", lambda self: {"name": "tester", "url_token": "abc"}
    )
    me = auth.validate_cookies(
        [{"name": "z_c0", "value": "x", "domain": ".zhihu.com"}], sleep=0
    )
    assert me["name"] == "tester"
