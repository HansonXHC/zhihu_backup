from zhihu_backup.models import ContentItem
from zhihu_backup.pdf import build_content_html, build_markdown_html


def test_build_content_html_pin_with_local_image(tmp_path):
    item = ContentItem(
        type="pin",
        id="1",
        url="https://www.zhihu.com/pin/1",
        title="测试想法",
        author="作者",
        created=1549660774,
        updated=1549660774,
        voteup_count=7,
        favorite_count=1,
        like_count=7,
        comment_count=0,
        content_html='<div>正文<img src="https://pic1.zhimg.com/a.jpg"></div>',
    )
    html = build_content_html(
        item, tmp_path, {"https://pic1.zhimg.com/a.jpg": "images/001.jpg"}
    )
    assert "<h1>测试想法</h1>" in html
    assert "正文" in html
    assert 'src="images/001.jpg"' in html
    assert "赞同 7 · 收藏 1 · 喜欢 7 · 评论 0" in html
    assert "file://" in html


def test_build_content_html_answer_includes_question_and_edit_time(tmp_path):
    item = ContentItem(
        type="answer",
        id="2",
        url="https://www.zhihu.com/question/1/answer/2",
        title="问题标题",
        author="作者",
        created=1549660774,
        updated=1550888927,
        voteup_count=19,
        favorite_count=14,
        like_count=8,
        comment_count=2,
        content_html="<div>回答正文</div>",
        extra={"question_html": "<div>问题描述</div>"},
    )
    html = build_content_html(item, tmp_path)
    assert "<h2>问题</h2>" in html
    assert "问题描述" in html
    assert "<h2>回答</h2>" in html
    assert "回答正文" in html
    assert "编辑时间" in html
    assert "赞同 19 · 收藏 14 · 喜欢 8 · 评论 2" in html


def test_build_markdown_html_for_local_pdf(tmp_path):
    html = build_markdown_html(
        "# 标题\n\n**作者**：作者\n\n正文\n\n![](images/001.jpg)",
        tmp_path,
    )
    assert "<h1>标题</h1>" in html
    assert "<strong>作者</strong>" in html
    assert "正文" in html
    assert 'src="images/001.jpg"' in html
    assert "file://" in html
