from zhihu_backup.markdown import HtmlToMarkdown
from zhihu_backup.models import ContentItem


class FakeDownloader:
    def __init__(self):
        self.counter = 0
        self.seen = {}

    def download(self, url, referer=None):
        if url in self.seen:
            return self.seen[url]
        self.counter += 1
        relative = f"images/{self.counter:03d}.jpg"
        self.seen[url] = relative
        return relative


def test_headings_links_math_images():
    html = """
    <div>
      <h2>小标题</h2>
      <p>正文 <span class="ztext-math" data-tex="x^2"></span></p>
      <p><a href="https://link.zhihu.com/?target=https%3A%2F%2Fexample.com">链接</a></p>
      <figure><img src="https://pic.example.com/a.jpg"></figure>
      <img class="lazy" src="placeholder.jpg">
    </div>
    """
    downloader = FakeDownloader()
    markdown = HtmlToMarkdown(downloader).convert(html)

    assert "## 小标题" in markdown
    assert "$x^2$" in markdown
    assert "[链接](https://example.com)" in markdown
    assert "images/001.jpg" in markdown
    assert "placeholder" not in markdown


def test_classless_image_is_kept():
    html = '<div><img src="https://pic.example.com/b.png"></div>'
    markdown = HtmlToMarkdown(FakeDownloader()).convert(html)
    assert "images/001.jpg" in markdown


def test_lazy_image_with_real_source_is_kept():
    html = (
        '<div><img class="lazy" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" '
        'data-original="https://pic.example.com/d.jpg"></div>'
    )
    downloader = FakeDownloader()
    markdown = HtmlToMarkdown(downloader).convert(html)
    assert "images/001.jpg" in markdown
    assert downloader.seen == {"https://pic.example.com/d.jpg": "images/001.jpg"}


def test_block_math_with_tag():
    html = '<div><span class="ztext-math" data-tex="a\\tag{1}"></span></div>'
    markdown = HtmlToMarkdown(None).convert(html)
    assert "$$a\\tag{1}$$" in markdown


def test_images_disabled_keeps_remote_url():
    html = '<div><img src="https://pic.example.com/c.jpg"></div>'
    markdown = HtmlToMarkdown(None).convert(html)
    assert "https://pic.example.com/c.jpg" in markdown


def test_render_document_header():
    item = ContentItem(
        type="answer",
        id="1",
        url="https://www.zhihu.com/question/1/answer/1",
        title="标题",
        author="作者",
        created=1690000000,
        voteup_count=12,
        comment_count=3,
        content_html="<p>正文</p>",
    )
    markdown = HtmlToMarkdown(None).render_document(item)
    assert markdown.startswith("# 标题")
    assert "**作者**：作者" in markdown
    assert "**原文**：https://www.zhihu.com/question/1/answer/1" in markdown
    assert "赞同 12" in markdown
    assert "评论 3" in markdown


def test_render_answer_with_question_body():
    item = ContentItem(
        type="answer",
        id="1",
        url="https://www.zhihu.com/question/1/answer/1",
        title="问题标题",
        content_html="<p>回答正文</p>",
        extra={"question_html": "<p>问题描述</p>"},
    )
    markdown = HtmlToMarkdown(None).render_document(item)
    assert "## 问题" in markdown
    assert "问题描述" in markdown
    assert "## 回答" in markdown
    assert "回答正文" in markdown
