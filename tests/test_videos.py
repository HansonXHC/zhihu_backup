from pathlib import Path
from types import SimpleNamespace

from zhihu_backup.videos import VideoDownloader, normalize_variants, select_variant

PLAYLIST = {
    "ld": {
        "play_url": "https://example.com/SD.mp4",
        "height": 476,
        "width": 848,
        "bitrate": 327,
        "size": 100,
        "duration": 38,
    },
    "hd": {
        "play_url": "https://example.com/HD.mp4",
        "height": 720,
        "width": 1280,
        "bitrate": 477,
        "size": 200,
        "duration": 38,
    },
}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def stream_to_file(self, url, path, referer=None, expected_size=None):
        self.calls.append((url, expected_size))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"x" * 64)
        return path


def test_normalize_and_select_quality():
    variants = normalize_variants({"playlist": PLAYLIST})
    assert len(variants) == 2
    assert select_variant(variants, "best")["url"].endswith("HD.mp4")
    assert select_variant(variants, "sd")["url"].endswith("SD.mp4")


def test_numeric_quality_keys_are_labelled_by_height():
    variants = normalize_variants(
        {
            "playlist": {
                "0": {"play_url": "https://example.com/a.mp4", "height": 476},
                "1": {"play_url": "https://example.com/b.mp4", "height": 720},
            }
        }
    )
    assert [item["quality_label"] for item in variants] == ["sd", "hd"]
    assert select_variant(variants, "sd")["url"].endswith("a.mp4")


def test_download_best_quality(tmp_path):
    http = FakeHttp()
    part = {"type": "video", "id": "42", "playlist": PLAYLIST}
    downloader = VideoDownloader(http, tmp_path, enabled=True, quality="best")
    meta = downloader.download_part(part)
    assert meta is not None
    assert meta["local_file"] == "videos/42.mp4"
    assert meta["quality"] == "hd"
    assert http.calls[0][0] == "https://example.com/HD.mp4"
    assert (tmp_path / "videos" / "42.mp4").exists()
    assert part["local_file"] == "videos/42.mp4"


def test_download_sd_quality(tmp_path):
    http = FakeHttp()
    part = {"type": "video", "id": "42", "playlist": PLAYLIST}
    downloader = VideoDownloader(http, tmp_path, enabled=True, quality="sd")
    meta = downloader.download_part(part)
    assert meta is not None
    assert meta["quality"] == "sd"
    assert http.calls[0][0] == "https://example.com/SD.mp4"


def test_existing_video_is_not_redownloaded(tmp_path):
    target = tmp_path / "videos" / "42.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"x" * 64)
    http = FakeHttp()
    downloader = VideoDownloader(http, tmp_path, enabled=True)
    meta = downloader.download_part({"type": "video", "id": "42", "playlist": PLAYLIST})
    assert meta is not None
    assert http.calls == []


def test_disabled_downloader(tmp_path):
    downloader = VideoDownloader(FakeHttp(), tmp_path, enabled=False)
    assert downloader.download_part({"type": "video", "id": "1", "playlist": PLAYLIST}) is None


def test_hls_uses_ffmpeg(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        output = Path(cmd[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"x" * 64)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("zhihu_backup.videos.shutil.which", lambda name: "/ffmpeg")
    monkeypatch.setattr("zhihu_backup.videos.subprocess.run", fake_run)

    part = {
        "type": "video",
        "id": "hls1",
        "playlist": {
            "hd": {
                "play_url": "https://example.com/master.m3u8",
                "format": "m3u8",
                "height": 720,
            }
        },
    }
    downloader = VideoDownloader(FakeHttp(), tmp_path, enabled=True)
    meta = downloader.download_part(part)
    assert meta is not None
    assert meta["local_file"] == "videos/hls1.mp4"
    assert (tmp_path / "videos" / "hls1.mp4").exists()
