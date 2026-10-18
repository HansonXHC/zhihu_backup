import argparse

from zhihu_backup.errors import EnumerationError
from zhihu_backup.models import ContentItem, Target, UserProfile
from zhihu_backup.runner import Runner


def make_args(tmp_path):
    return argparse.Namespace(
        output=str(tmp_path / "out"),
        state_dir=str(tmp_path / "state"),
        sleep=0,
        driver=None,
        cookie=None,
        cookie_file=None,
        force=False,
        update=False,
        no_images=True,
        no_videos=True,
        no_question_body=False,
        pdf=False,
        limit=0,
        since_ts=0,
        json=False,
        verbose=False,
    )


def _raw(index):
    return {
        "id": str(index),
        "content": f"<p>正文 {index}</p>",
        "created_time": 1690000000 + index,
        "voteup_count": index,
        "question": {"id": "1", "title": "问题"},
        "author": {"name": "作者", "url": "/people/abc"},
    }


class FakeApi:
    def __init__(self, fail_after=None):
        self.fail_after = fail_after
        self.seen = set()

    def question_detail(self, question_id):
        return {"detail": "<p>问题描述</p>"}

    def iter_user_items(self, token, kind, max_items=None, since_ts=0):
        for index in range(1, 4):
            if self.fail_after is not None and index > self.fail_after:
                raise EnumerationError("fake failure", self.seen)
            self.seen.add(str(index))
            yield _raw(index)


def test_count_user_items_dedupes_ids(tmp_path):
    class DuplicateApi:
        def iter_user_items(self, token, kind, max_items=None, since_ts=0):
            yield {"id": "1"}
            yield {"id": "1"}
            yield {"id": "2"}

    runner = Runner(make_args(tmp_path))
    runner.api = DuplicateApi()
    profile = UserProfile(url_token="abc")
    assert runner._count_user_items("abc", "answers", profile) == 2


def test_user_flow_uses_api_only(tmp_path, monkeypatch):
    runner = Runner(make_args(tmp_path))
    runner.api = FakeApi()
    runner.http = object()

    profile = UserProfile(url_token="abc", name="作者", url="https://www.zhihu.com/people/abc")
    user_dir = tmp_path / "out" / "users" / "abc"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "fetch_profile", lambda token: profile)
    monkeypatch.setattr(runner, "save_profile", lambda profile: user_dir)
    monkeypatch.setattr(
        runner,
        "_enumerate_user_browser",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应回退浏览器")),
    )

    result = runner.backup_user("abc", ["answers"])

    assert result["ok"] == 3
    assert result["failed"] == 0
    assert len(list((user_dir / "answers").iterdir())) == 3
    contents = list((user_dir / "answers").glob("*/content.md"))
    assert contents
    assert all("问题描述" in path.read_text(encoding="utf-8") for path in contents)


def test_user_flow_falls_back_after_partial_api_failure(tmp_path, monkeypatch):
    runner = Runner(make_args(tmp_path))
    runner.api = FakeApi(fail_after=1)
    runner.http = object()

    profile = UserProfile(url_token="abc", name="作者", url="https://www.zhihu.com/people/abc")
    user_dir = tmp_path / "out" / "users" / "abc"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "fetch_profile", lambda token: profile)
    monkeypatch.setattr(runner, "save_profile", lambda profile: user_dir)
    monkeypatch.setattr(
        runner,
        "_enumerate_user_browser",
        lambda *args, **kwargs: [
            Target("answer", "1", "https://www.zhihu.com/question/1/answer/1"),
            Target("answer", "2", "https://www.zhihu.com/question/1/answer/2"),
        ],
    )
    monkeypatch.setattr(
        runner,
        "_fetch_item_by_target",
        lambda target: ContentItem(
            type="answer",
            id=target.id,
            url=target.url,
            title=f"补全 {target.id}",
            content_html="<p>补全正文</p>",
        ),
    )

    result = runner.backup_user("abc", ["answers"])

    assert result["ok"] == 2
    assert result["failed"] == 0
    assert len(list((user_dir / "answers").iterdir())) == 2
