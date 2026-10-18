from zhihu_backup.extractors import web_url
from zhihu_backup.urls import parse_target, parse_user, resolve_user


def test_parse_answer():
    target = parse_target(
        "https://www.zhihu.com/question/123/answer/456?utm_source=test#fragment"
    )
    assert target is not None
    assert target.type == "answer"
    assert target.id == "456"
    assert target.question_id == "123"


def test_parse_article():
    target = parse_target("https://zhuanlan.zhihu.com/p/789")
    assert target is not None
    assert target.type == "article"
    assert target.id == "789"
    assert target.url == "https://zhuanlan.zhihu.com/p/789"


def test_parse_pin_and_video():
    pin = parse_target("https://www.zhihu.com/pin/111")
    video = parse_target("https://www.zhihu.com/zvideo/222")
    assert pin and pin.type == "pin" and pin.id == "111"
    assert video and video.type == "zvideo" and video.id == "222"


def test_parse_user_url_and_token():
    assert parse_user("https://www.zhihu.com/people/xie-qian-qian-20-2") == "xie-qian-qian-20-2"
    assert parse_user("https://www.zhihu.com/people/xie-qian-qian-20-2/answers") == "xie-qian-qian-20-2"
    assert parse_user("xie-qian-qian-20-2") == "xie-qian-qian-20-2"
    assert resolve_user("https://www.zhihu.com/people/abc") == "abc"


def test_invalid_values():
    assert parse_target("https://www.zhihu.com/people/abc") is None
    assert parse_target("https://example.com/post/1") is None
    assert parse_user("https://example.com/abc") is None


def test_web_url_normalises_api_resources():
    assert (
        web_url("https://www.zhihu.com/api/v4/people/abc")
        == "https://www.zhihu.com/people/abc"
    )
    assert (
        web_url("https://www.zhihu.com/api/v4/topics/123")
        == "https://www.zhihu.com/topic/123"
    )
    assert web_url("") == ""
