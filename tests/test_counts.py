from datetime import datetime

from bs4 import BeautifulSoup

from zhihu_backup.extractors import parse_action_counts, parse_content_times
from zhihu_backup.extractors import answer as answer_ext
from zhihu_backup.extractors import article as article_ext
from zhihu_backup.markdown import HtmlToMarkdown
from zhihu_backup.models import ContentItem

TIME_HTML = """
<div class="ContentItem-time">
  <a data-tooltip="发布于2019-02-09 05:19">编辑于2019-02-23 10:28</a>
</div>
"""

ACTIONS_HTML = """
<div class="ContentItem-actions RichContent-actions">
  <button class="Button VoteButton is-active">已赞同 19</button>
  <button class="Button VoteButton VoteButton--down"></button>
  <button class="Button ContentItem-action">2 条评论</button>
  <button aria-label="收藏" class="Button ContentItem-action">14 </button>
  <button aria-label="喜欢" class="Button ContentItem-action">8</button>
</div>
"""


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def test_parse_content_times_from_edited_tooltip():
    created, updated = parse_content_times(_soup(TIME_HTML))
    assert datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M") == "2019-02-09 05:19"
    assert datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M") == "2019-02-23 10:28"


def test_parse_action_counts():
    counts = parse_action_counts(_soup(ACTIONS_HTML))
    assert counts == {"voteup": 19, "favorite": 14, "like": 8, "comment": 2}


def test_answer_from_api_full_counts():
    raw = {
        "id": "1",
        "question": {"id": "2", "title": "问题"},
        "content": "<p>正文</p>",
        "voteup_count": 19,
        "comment_count": 2,
        "thanks_count": 8,
        "favlists_count": 14,
        "created_time": 1549660774,
        "updated_time": 1550888927,
        "author": {
            "name": "示例用户",
            "url": "https://www.zhihu.com/api/v4/people/91949509989e39acc6e55e4216ac260b",
        },
    }
    item = answer_ext.from_api(raw)
    assert item.voteup_count == 19
    assert item.favorite_count == 14
    assert item.like_count == 8
    assert item.comment_count == 2
    assert item.updated > item.created
    assert item.author_url == "https://www.zhihu.com/people/91949509989e39acc6e55e4216ac260b"
    assert item.extra["needs_stats"] is False


def test_answer_from_list_needs_detail_stats():
    raw = {
        "id": "1",
        "question": {"id": "2", "title": "问题"},
        "content": "<p>正文</p>",
        "comment_count": 15,
        "reaction": {"statistics": {"favorites": 93, "like_count": 78}},
        "created_time": 1549660774,
        "updated_time": 1550888927,
    }
    item = answer_ext.from_api(raw)
    assert item.favorite_count == 93
    assert item.like_count == 78
    assert item.comment_count == 15
    assert item.extra["needs_stats"] is True


def test_article_from_api_counts():
    raw = {
        "id": "3",
        "title": "文章",
        "content": "<p>正文</p>",
        "voteup_count": 12,
        "comment_count": 0,
        "reaction": {"statistics": {"favorites": 2, "like_count": 2}},
        "created": 1610352043,
        "updated": 1610539851,
    }
    item = article_ext.from_api(raw)
    assert item.voteup_count == 12
    assert item.favorite_count == 2
    assert item.like_count == 2
    assert item.comment_count == 0
    assert item.updated > item.created


def test_render_document_shows_edit_time_and_all_counts():
    item = ContentItem(
        type="answer",
        id="1",
        url="https://www.zhihu.com/question/1/answer/1",
        title="标题",
        created=1549660774,
        updated=1550888927,
        voteup_count=19,
        favorite_count=14,
        like_count=8,
        comment_count=2,
        content_html="<p>正文</p>",
    )
    markdown = HtmlToMarkdown(None).render_document(item)
    assert "**发布时间**" in markdown
    assert "**编辑时间**" in markdown
    assert "赞同 19 · 收藏 14 · 喜欢 8 · 评论 2" in markdown
    assert markdown.index("**发布时间**") < markdown.index("**编辑时间**") < markdown.index("赞同 19")
