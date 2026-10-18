from zhihu_backup.images import ImageDownloader


class FakeResponse:
    def __init__(self, content=b"data", content_type="image/png", status_code=200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_bytes(self, url, referer=None):
        self.calls.append((url, referer))
        return self.response


def test_download_uses_content_type_extension(tmp_path):
    http = FakeHttp(FakeResponse(b"png-bytes", "image/png"))
    downloader = ImageDownloader(http, tmp_path)

    relative = downloader.download("https://pic1.zhimg.com/a.jpg", referer="https://www.zhihu.com/")

    assert relative == "images/001.png"
    assert (tmp_path / relative).read_bytes() == b"png-bytes"
    assert http.calls == [
        ("https://pic1.zhimg.com/a.jpg", "https://www.zhihu.com/")
    ]


def test_download_deduplicates(tmp_path):
    http = FakeHttp(FakeResponse())
    downloader = ImageDownloader(http, tmp_path)
    first = downloader.download("https://pic1.zhimg.com/a.jpg")
    second = downloader.download("https://pic1.zhimg.com/a.jpg")
    assert first == second
    assert downloader.counter == 1


def test_download_rejects_non_image(tmp_path):
    http = FakeHttp(FakeResponse(b"<html>blocked</html>", "text/html"))
    downloader = ImageDownloader(http, tmp_path)
    assert downloader.download("https://pic1.zhimg.com/a.jpg") is None
    assert downloader.failures == 1


def test_download_normalizes_protocol_relative_url(tmp_path):
    http = FakeHttp(FakeResponse())
    downloader = ImageDownloader(http, tmp_path)
    downloader.download("//pic1.zhimg.com/a.jpg")
    assert http.calls[0][0] == "https://pic1.zhimg.com/a.jpg"


def test_download_normalizes_relative_zhihu_image_url(tmp_path):
    http = FakeHttp(FakeResponse())
    downloader = ImageDownloader(http, tmp_path)
    downloader.download("v2-dddddddddddddddddddddddddddddddd.jpg")
    assert (
        http.calls[0][0]
        == "https://picx.zhimg.com/v2-dddddddddddddddddddddddddddddddd.jpg"
    )


def test_disabled_downloader_keeps_remote_urls(tmp_path):
    http = FakeHttp(FakeResponse())
    downloader = ImageDownloader(http, tmp_path, enabled=False)
    assert downloader.download("https://pic1.zhimg.com/a.jpg") is None
    assert http.calls == []
