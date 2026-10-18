from zhihu_backup.http_client import cookies_to_header


def test_cookie_header_from_string():
    assert cookies_to_header("a=1; b=2") == "a=1; b=2"


def test_cookie_header_from_dict():
    assert cookies_to_header({"a": "1", "b": "2"}) == "a=1; b=2"


def test_cookie_header_from_selenium_list():
    cookies = [
        {"name": "z_c0", "value": "token", "domain": ".zhihu.com"},
        {"name": "other", "value": "x", "domain": ".example.com"},
    ]
    assert cookies_to_header(cookies) == "z_c0=token"


def test_cookie_header_empty():
    assert cookies_to_header(None) == ""
    assert cookies_to_header([]) == ""
