import pytest

from zhihu_backup.api import ZhihuApi
from zhihu_backup.errors import EnumerationError


class FakeApi(ZhihuApi):
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def _list_page(self, kind, url_token, offset):
        self.calls.append(offset)
        return self.pages[offset]


def _page(ids, totals, is_end, created=1000):
    return {
        "data": [
            {"id": str(item_id), "created": created - index, "content": "<p>x</p>"}
            for index, item_id in enumerate(ids)
        ],
        "paging": {"totals": totals, "is_end": is_end},
    }


def test_iter_user_items_paginates_and_stops():
    api = FakeApi(
        {
            0: _page([1, 2], totals=4, is_end=False),
            2: _page([3, 4], totals=4, is_end=True),
        }
    )
    items = list(api.iter_user_items("abc", "articles"))
    assert [item["id"] for item in items] == ["1", "2", "3", "4"]
    assert api.calls == [0, 2]


def test_iter_user_items_respects_max_items():
    api = FakeApi({0: _page([1, 2, 3], totals=10, is_end=False)})
    items = list(api.iter_user_items("abc", "articles", max_items=2))
    assert [item["id"] for item in items] == ["1", "2"]
    assert api.calls == [0]


def test_iter_user_items_respects_since():
    api = FakeApi({0: _page([1, 2, 3], totals=3, is_end=False, created=1000)})
    items = list(api.iter_user_items("abc", "articles", since_ts=999))
    assert [item["id"] for item in items] == ["1", "2"]
    assert api.calls == [0]


def test_iter_user_items_empty_page_is_an_error():
    api = FakeApi(
        {
            0: {
                "data": [],
                "paging": {"totals": 10, "is_end": False},
            }
        }
    )
    with pytest.raises(EnumerationError):
        list(api.iter_user_items("abc", "articles"))


def test_iter_user_items_wraps_request_errors():
    class BrokenApi(ZhihuApi):
        def _list_page(self, kind, url_token, offset):
            raise RuntimeError("boom")

    api = BrokenApi(http=None)
    with pytest.raises(EnumerationError):
        list(api.iter_user_items("abc", "articles"))
