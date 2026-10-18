from zhihu_backup import cli
from zhihu_backup.cli import build_parser
from zhihu_backup.runner import Runner


def _summary(output):
    return {
        "ok": 1,
        "skipped": 0,
        "failed": 0,
        "total": 1,
        "errors": [],
        "output": str(output),
    }


def test_profile_command_routes_content_url_to_urls(tmp_path, monkeypatch):
    calls = {}

    def fake_backup_urls(self, values):
        calls["urls"] = list(values)
        return {**_summary(tmp_path), "singles": len(values)}

    def fake_backup_profile(self, token):
        calls["profile"] = token
        return {**_summary(tmp_path), "profile": {"name": "x", "url_token": token}}

    monkeypatch.setattr(Runner, "backup_urls", fake_backup_urls)
    monkeypatch.setattr(Runner, "backup_profile", fake_backup_profile)
    monkeypatch.setattr(Runner, "close", lambda self: None)

    code = cli.main(
        [
            "profile",
            "https://www.zhihu.com/pin/123",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert calls["urls"] == ["https://www.zhihu.com/pin/123"]
    assert "profile" not in calls


def test_profile_command_routes_user_url_to_profile(tmp_path, monkeypatch):
    calls = {}

    def fake_backup_profile(self, token):
        calls["profile"] = token
        return {**_summary(tmp_path), "profile": {"name": "x", "url_token": token}}

    monkeypatch.setattr(Runner, "backup_profile", fake_backup_profile)
    monkeypatch.setattr(Runner, "close", lambda self: None)

    code = cli.main(
        [
            "profile",
            "https://www.zhihu.com/people/abc",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert calls["profile"] == "abc"


def test_user_pdf_flag_keeps_default_all_kinds(tmp_path, monkeypatch):
    calls = {}

    def fake_backup_user(self, token, kinds, dry_run=False):
        calls["token"] = token
        calls["kinds"] = list(kinds)
        calls["pdf"] = self.args.pdf
        return _summary(tmp_path)

    monkeypatch.setattr(Runner, "backup_user", fake_backup_user)
    monkeypatch.setattr(Runner, "close", lambda self: None)

    code = cli.main(
        ["user", "https://www.zhihu.com/people/abc", "--pdf", "--output", str(tmp_path)]
    )
    assert code == 0
    assert calls["kinds"] == ["answers", "articles", "pins"]
    assert calls["pdf"] is True


def test_urls_pdf_defaults_to_false_and_can_be_enabled():
    parser = build_parser()
    default = parser.parse_args(
        ["urls", "https://www.zhihu.com/question/1/answer/2"]
    )
    enabled = parser.parse_args(
        ["urls", "https://www.zhihu.com/question/1/answer/2", "--pdf"]
    )
    assert default.pdf is False
    assert enabled.pdf is True


def test_pdf_only_accepts_hyphen_and_underscore_aliases():
    parser = build_parser()
    assert parser.parse_args(["user", "x"]).pdf_only is False
    assert parser.parse_args(["user", "x", "--pdf_only"]).pdf_only is True
    assert (
        parser.parse_args(
            ["urls", "https://www.zhihu.com/question/1/answer/2", "--pdf-only"]
        ).pdf_only
        is True
    )


def test_video_flags():
    parser = build_parser()
    default = parser.parse_args(["user", "x"])
    assert default.videos is False
    assert default.no_videos is False
    assert default.videos_only is False
    assert default.video_quality == "best"

    enabled = parser.parse_args(["user", "x", "--videos", "--video-quality", "hd"])
    assert enabled.videos is True
    assert enabled.video_quality == "hd"

    disabled = parser.parse_args(["user", "x", "--no-videos"])
    assert disabled.no_videos is True

    only = parser.parse_args(
        ["urls", "https://www.zhihu.com/pin/1", "--videos_only"]
    )
    assert only.videos_only is True


def test_user_videos_includes_zvideos(tmp_path, monkeypatch):
    calls = {}

    def fake_backup_user(self, token, kinds, dry_run=False):
        calls["kinds"] = list(kinds)
        return _summary(tmp_path)

    monkeypatch.setattr(Runner, "backup_user", fake_backup_user)
    monkeypatch.setattr(Runner, "close", lambda self: None)

    code = cli.main(
        ["user", "https://www.zhihu.com/people/abc", "--videos", "--output", str(tmp_path)]
    )
    assert code == 0
    assert calls["kinds"] == ["answers", "articles", "pins", "zvideos"]
