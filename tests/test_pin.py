from zhihu_backup.extractors import pin as pin_ext
from zhihu_backup.markdown import HtmlToMarkdown

RAW_PIN = {
    "id": "1108690352105553920",
    "created": 1557112378,
    "updated": 1557112400,
    "reaction_count": 153,
    "comment_count": 10,
    "author": {"name": "叶倩倩", "url": "/people/xie-qian-qian-20-2"},
    "content": [
        {
            "type": "text",
            "content": "搬家折腾了<strong>一周</strong><br>新家的第一个家具👇",
        },
        {"type": "image", "url": "https://pic3.zhimg.com/a_qhd.jpg"},
        {"type": "link", "url": "https://example.com/post", "title": "示例链接"},
        {
            "type": "video",
            "video": {
                "playlist": {"LD": {"playUrl": "https://video.example.com/v.mp4"}},
                "thumbnail": "https://pic3.zhimg.com/cover.jpg",
            },
        },
    ],
}


class FakeDownloader:
    def __init__(self):
        self.counter = 0

    def download(self, url, referer=None):
        self.counter += 1
        return f"images/{self.counter:03d}.jpg"


def test_pin_from_api():
    item = pin_ext.from_api(RAW_PIN)
    assert item.id == "1108690352105553920"
    assert item.type == "pin"
    assert item.author == "叶倩倩"
    assert item.voteup_count == 153
    assert item.comment_count == 10
    assert "搬家" in item.title
    assert len(item.extra["parts"]) == 4
    assert "<img" in item.content_html


def test_pin_render():
    item = pin_ext.from_api(RAW_PIN)
    markdown = HtmlToMarkdown(FakeDownloader()).render_pin(item)
    assert "搬家折腾了" in markdown
    assert "**一周**" in markdown
    assert "images/001.jpg" in markdown
    assert "[示例链接](https://example.com/post)" in markdown
    assert "[视频](https://video.example.com/v.mp4)" in markdown
    assert "images/002.jpg" in markdown


def test_pin_from_dom():
    html = """
    <html><body>
      <div class="PinItem">
        <div class="RichContent-inner">
          <div class="RichText">今天<strong>很开心</strong></div>
          <figure><img data-original="https://pic3.zhimg.com/b.jpg"></figure>
        </div>
        <div class="ContentItem-time">发布于 2023-01-21 13:01</div>
      </div>
    </body></html>
    """
    item = pin_ext.from_dom(html, "https://www.zhihu.com/pin/123")
    assert item.id == "123"
    assert "今天" in item.title
    assert "<strong>很开心</strong>" in item.content_html
    assert item.created > 0


def test_pin_video_real_schema():
    raw = {
        "id": "1449482128384294913",
        "created": 1638363469,
        "author": {"name": "示例用户", "url": "/people/abc"},
        "content": [
            {"type": "text", "content": "视频配乐"},
            {
                "type": "video",
                "id": "1449481349007052801",
                "duration": 38,
                "playlist": {
                    "ld": {
                        "play_url": "https://example.com/SD.mp4",
                        "height": 476,
                        "width": 848,
                        "bitrate": 327,
                        "size": 1557061,
                        "format": "mp4",
                    },
                    "hd": {
                        "play_url": "https://example.com/HD.mp4",
                        "height": 720,
                        "width": 1280,
                        "bitrate": 477,
                        "size": 2269629,
                        "format": "mp4",
                    },
                },
                "cover_info": {
                    "thumbnail": "https://pic1.zhimg.com/v2-cover.jpg?source=1"
                },
                "play_url": "",
                "cover": "",
            },
        ],
    }
    item = pin_ext.from_api(raw)
    video = next(part for part in item.extra["parts"] if part["type"] == "video")
    assert video["play_url"].endswith("HD.mp4")
    assert video["cover"].startswith("https://pic1.zhimg.com/")
    assert video["video_id"] == "1449481349007052801"
    assert [variant["quality_label"] for variant in video["video_variants"]] == [
        "sd",
        "hd",
    ]
    html = pin_ext.parts_to_html(item.extra["parts"])
    assert "HD.mp4" in html
    assert "v2-cover.jpg" in html
