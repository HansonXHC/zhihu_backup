from zhihu_backup.extractors import zvideo as zvideo_ext

RAW = {
    "id": "1266745005789921280",
    "title": "测试视频",
    "description": "视频简介",
    "published_at": 1595433600,
    "updated_at": 1595565640,
    "voteup_count": 100,
    "comment_count": 5,
    "favlists_count": 10,
    "liked_count": 20,
    "author": {
        "name": "知乎",
        "url": "https://www.zhihu.com/api/v4/people/fdd4a956cc8fabe260d708aecb33330a",
    },
    "image_url": "https://pic1.zhimg.com/cover_r.jpg?source=1",
    "video": {
        "playlist": {
            "hd": {
                "play_url": "https://example.com/HD.mp4",
                "height": 720,
                "width": 1280,
                "bitrate": 500,
                "size": 200,
                "duration": 30,
                "format": "mp4",
            },
            "fhd": {
                "play_url": "https://example.com/FHD.mp4",
                "height": 1080,
                "width": 1920,
                "bitrate": 1000,
                "size": 400,
                "duration": 30,
                "format": "mp4",
            },
        }
    },
}


def test_zvideo_from_api():
    item = zvideo_ext.from_api(RAW, "1266745005789921280")
    assert item.type == "zvideo"
    assert item.title == "测试视频"
    assert item.author == "知乎"
    assert item.author_url == "https://www.zhihu.com/people/fdd4a956cc8fabe260d708aecb33330a"
    assert item.created == 1595433600
    assert item.updated == 1595565640
    assert item.voteup_count == 100
    assert item.comment_count == 5
    assert item.favorite_count == 10
    assert item.like_count == 20
    video = item.extra["video"]
    assert video["url"].endswith("FHD.mp4")
    assert video["cover"]
    assert [variant["quality_label"] for variant in video["variants"]] == ["hd", "fhd"]


def test_zvideo_from_initial_data():
    html = """
    <html><body>
      <script id="js-initialData" type="text/json">
      {"initialState":{"entities":{"zvideos":{"1266745005789921280":{
        "id":"1266745005789921280","title":"初始数据视频","published_at":1595433600,
        "video":{"playlist":{"hd":{"play_url":"https://example.com/HD.mp4","height":720,"width":1280}}}
      }}}}}
      </script>
    </body></html>
    """
    item = zvideo_ext.from_dom(
        html, "https://www.zhihu.com/zvideo/1266745005789921280"
    )
    assert item.id == "1266745005789921280"
    assert item.title == "初始数据视频"
    assert item.extra["video"]["url"].endswith("HD.mp4")
