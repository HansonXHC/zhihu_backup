import argparse

from zhihu_backup.models import ContentItem
from zhihu_backup.runner import Runner
from zhihu_backup.storage import Manifest


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
        no_question_body=True,
        pdf=False,
        limit=0,
        since_ts=0,
        json=False,
        verbose=False,
    )


def _item() -> ContentItem:
    return ContentItem(
        type="answer",
        id="123",
        url="https://www.zhihu.com/question/1/answer/123",
        title="测试回答",
        author="作者",
        created=1690000000,
        content_html="<div><p>正文内容</p></div>",
    )


def test_process_item_writes_markdown_and_manifest(tmp_path):
    runner = Runner(make_args(tmp_path))
    base = tmp_path / "out" / "users" / "abc"
    base.mkdir(parents=True)
    manifest = Manifest(base)
    item = _item()

    runner._process_item(item, base, manifest, {})

    target_dir = base / "answers" / "20230722-123-测试回答"
    content = (target_dir / "content.md").read_text(encoding="utf-8")
    assert content.startswith("# 测试回答")
    assert "正文内容" in content
    assert (target_dir / "meta.json").exists()
    assert runner.stats.ok == 1
    assert manifest.should_skip(item) is True

    runner._process_item(item, base, manifest, {})
    assert runner.stats.skipped == 1


def test_backup_urls_uses_singles_layout(tmp_path, monkeypatch):
    runner = Runner(make_args(tmp_path))
    item = _item()
    monkeypatch.setattr(runner, "_fetch_item_by_target", lambda target: item)

    result = runner.backup_urls(["https://www.zhihu.com/question/1/answer/123"])

    assert result["ok"] == 1
    assert result["failed"] == 0
    assert (tmp_path / "out" / "singles" / "answers").is_dir()
    assert (tmp_path / "out" / "singles" / "manifest.json").exists()


def test_backup_urls_ignores_duplicates(tmp_path, monkeypatch):
    runner = Runner(make_args(tmp_path))
    item = _item()
    calls = []
    monkeypatch.setattr(
        runner,
        "_fetch_item_by_target",
        lambda target: calls.append(target.id) or item,
    )

    runner.backup_urls(
        [
            "https://www.zhihu.com/question/1/answer/123",
            "https://www.zhihu.com/question/1/answer/123?utm=1",
        ]
    )
    assert calls == ["123"]


def test_pdf_only_user_generates_and_skips(tmp_path, monkeypatch):
    runner = Runner(make_args(tmp_path))
    runner.pdf_only = True
    item_dir = tmp_path / "out" / "users" / "abc" / "answers" / "20230101-1-title"
    item_dir.mkdir(parents=True)
    (item_dir / "content.md").write_text("# title\n\nbody", encoding="utf-8")

    calls = []

    def fake_generate(folder, pdf_path):
        calls.append((folder, pdf_path))
        pdf_path.write_bytes(b"%PDF-1.4 test")
        return True

    monkeypatch.setattr(runner, "_generate_markdown_pdf", fake_generate)

    first = runner._backup_user_pdfs("abc", ["answers"])
    assert first["ok"] == 1
    assert len(calls) == 1
    assert (item_dir / "content.pdf").exists()

    second = Runner(make_args(tmp_path))
    second.pdf_only = True
    monkeypatch.setattr(second, "_generate_markdown_pdf", fake_generate)
    result = second._backup_user_pdfs("abc", ["answers"])
    assert result["skipped"] == 1
    assert len(calls) == 1


def test_embedded_video_ids_from_content_html(tmp_path):
    runner = Runner(make_args(tmp_path))
    item = ContentItem(
        type="answer",
        id="1",
        url="https://www.zhihu.com/question/1/answer/1",
        content_html=(
            '<div>'
            '<a class="video-box" data-lens-id="123" href="#"></a>'
            '<a class="video-box" '
            'href="https://link.zhihu.com/?target=https%3A//www.zhihu.com/video/456"></a>'
            '</div>'
        ),
    )
    assert runner._embedded_video_ids(item) == ["123", "456"]


def test_embedded_video_ids_from_content_md(tmp_path):
    runner = Runner(make_args(tmp_path))
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    (item_dir / "content.md").write_text(
        "[视频](https://www.zhihu.com/video/789)", encoding="utf-8"
    )
    item = ContentItem(type="answer", id="1", url="https://example.com")
    assert runner._embedded_video_ids(item, item_dir) == ["789"]
