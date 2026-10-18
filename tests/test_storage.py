from pathlib import Path

from zhihu_backup.models import ContentItem
from zhihu_backup.storage import Manifest, Storage, atomic_write_json, read_json


def _item() -> ContentItem:
    return ContentItem(
        type="answer",
        id="123456",
        url="https://www.zhihu.com/question/1/answer/123456",
        title='标题/带:非法*字符?"<>|.',
        created=1690000000,
        updated=1690000100,
    )


def test_item_dir_name_is_safe(tmp_path):
    storage = Storage(tmp_path)
    item = _item()
    path = storage.item_dir(tmp_path, "answers", item)
    name = path.name
    assert "-123456-" in name
    assert not any(char in name for char in '<>:"/\\|?*')
    assert name.endswith(".") is False


def test_manifest_resume(tmp_path):
    base = tmp_path / "users" / "abc"
    base.mkdir(parents=True)
    item = _item()
    item_dir = base / "answers" / f"20230722-{item.id}-title"
    item_dir.mkdir(parents=True)
    (item_dir / "content.md").write_text("# title", encoding="utf-8")

    manifest = Manifest(base)
    manifest.mark_ok(item, f"answers/{item_dir.name}", ["content.md", "meta.json"])

    reloaded = Manifest(base)
    assert reloaded.should_skip(item) is True
    assert reloaded.should_skip(item, force=True) is False

    newer = _item()
    newer.updated = item.updated + 100
    assert reloaded.should_skip(newer, update=True) is False
    assert reloaded.should_skip(item, update=True) is True


def test_manifest_retries_failed(tmp_path):
    base = tmp_path
    item = _item()
    manifest = Manifest(base)
    manifest.mark_failed(item, "network error")
    assert manifest.should_skip(item) is False

    entry = manifest.get(item.type, item.id)
    assert entry is not None
    assert entry.status == "failed"
    assert "network" in entry.error


def test_atomic_json_roundtrip(tmp_path):
    path = Path(tmp_path) / "nested" / "data.json"
    atomic_write_json(path, {"中文": "值", "n": 1})
    assert read_json(path) == {"中文": "值", "n": 1}


def test_index_existing(tmp_path):
    kind_dir = tmp_path / "answers"
    (kind_dir / "20230722-111-title").mkdir(parents=True)
    (kind_dir / "20230723-222-other").mkdir()
    index = Storage.index_existing(tmp_path, "answers")
    assert index["111"].name == "20230722-111-title"
    assert index["222"].name == "20230723-222-other"


def test_build_content_index_across_users_and_singles(tmp_path):
    storage = Storage(tmp_path)
    user_item = tmp_path / "users" / "u1" / "answers" / "20230101-111-title"
    user_item.mkdir(parents=True)
    (user_item / "content.md").write_text("# answer", encoding="utf-8")

    single_item = tmp_path / "singles" / "pins" / "20230101-222-pin"
    single_item.mkdir(parents=True)
    (single_item / "content.md").write_text("# pin", encoding="utf-8")

    index = storage.build_content_index()
    assert index[("answers", "111")] == user_item
    assert index[("pins", "222")] == single_item
