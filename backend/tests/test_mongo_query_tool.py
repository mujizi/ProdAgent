from pymongo.errors import (
    ConnectionFailure,
    ExecutionTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from app.config import settings
from app.tools import mongo_query_tool as tool
from app.tools.mongo_query_tool import (
    _requested_scene_range,
    _to_mongo_filter,
    _to_mongo_projection,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, _spec):
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.find_calls = []

    def find(self, filter_, projection, *, limit=0, max_time_ms):
        if self.error:
            raise self.error
        self.find_calls.append({
            "filter": filter_, "projection": projection,
            "limit": limit, "max_time_ms": max_time_ms,
        })
        rows = self.rows
        scene_filter = filter_.get("scene_sort")
        if isinstance(scene_filter, dict) and "$in" in scene_filter:
            allowed = set(scene_filter["$in"])
            rows = [row for row in rows if row.get("scene_sort") in allowed]
        elif isinstance(scene_filter, dict):
            if "$gte" in scene_filter:
                rows = [row for row in rows if row.get("scene_sort") >= scene_filter["$gte"]]
            if "$lte" in scene_filter:
                rows = [row for row in rows if row.get("scene_sort") <= scene_filter["$lte"]]
        if limit > 0:
            rows = rows[:limit]
        return FakeCursor(rows)

    def count_documents(self, _filter, *, maxTimeMS):
        if self.error:
            raise self.error
        return len(self.rows)


class FakeDb(dict):
    pass


def _outline_args(limit=50):
    return {
        "collection": "seca_gen_scene_outline",
        "operation": "find",
        "filter": {"scene_sort": {"$gte": 1, "$lte": 100}},
        "limit": limit,
        "purpose": "读取原文",
    }


def test_requested_scene_range_normalizes_exclusive_bounds():
    assert _requested_scene_range({"scene_sort": {"$gt": 10, "$lt": 20}}) == {
        "start": 11, "end": 19,
    }
    assert _requested_scene_range({"scene_sort": {"$gte": 10, "$lte": 20}}) == {
        "start": 10, "end": 20,
    }


def test_outline_content_text_filter_maps_to_contents_content():
    out = _to_mongo_filter(
        "seca_gen_scene_outline", {"content_text": {"$regex": "杨小福"}},
    )
    assert out == {"contents.content": {"$regex": "杨小福"}}


def test_outline_content_text_filter_maps_inside_and():
    out = _to_mongo_filter(
        "seca_gen_scene_outline",
        {"$and": [
            {"content_text": {"$regex": "杨小福"}},
            {"content_text": {"$regex": "王艳凤"}},
        ]},
    )
    assert out == {"$and": [
        {"contents.content": {"$regex": "杨小福"}},
        {"contents.content": {"$regex": "王艳凤"}},
    ]}


def test_non_outline_filter_keeps_content_text():
    out = _to_mongo_filter(
        "seca_element_type_detail", {"content_text": {"$regex": "杨小福"}},
    )
    assert out == {"content_text": {"$regex": "杨小福"}}


def test_outline_content_text_projection_maps_to_contents():
    out = _to_mongo_projection(
        "seca_gen_scene_outline",
        {"_id": 0, "scene_sort": 1, "content_text": 1},
    )
    assert out == {"_id": 0, "scene_sort": 1, "contents": 1}


def test_outline_pages_by_distinct_scene_sort_and_reports_next(monkeypatch):
    rows = [
        {"scene_sort": i, "contents": [{"content": f"第{i}场"}]}
        for i in range(1, 52)
    ]
    collection = FakeCollection(rows)
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))

    result = tool.execute_mongo_query("script_1", _outline_args())

    assert collection.find_calls[0]["limit"] == 0
    assert collection.find_calls[1]["filter"]["scene_sort"]["$in"] == list(range(1, 51))
    assert result.error_code is None
    assert result.coverage["has_more"] is True
    assert result.coverage["next_scene_sort"] == 51
    assert result.coverage["requested_range"] == {"start": 1, "end": 100}
    assert result.row_count == 50


def test_outline_exact_limit_is_complete(monkeypatch):
    rows = [{"scene_sort": i, "contents": [{"content": "短"}]} for i in range(1, 51)]
    collection = FakeCollection(rows)
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))

    result = tool.execute_mongo_query("script_1", _outline_args())

    assert result.coverage["has_more"] is False
    assert result.coverage["next_scene_sort"] is None
    assert result.coverage["coverage_complete"] is True


def test_formatter_omission_controls_next_scene(monkeypatch):
    rows = [
        {"scene_sort": i, "contents": [{"content": "长原文" * 1000}]}
        for i in range(1, 11)
    ]
    collection = FakeCollection(rows)
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))
    monkeypatch.setattr(settings, "max_tool_chars", 5000)
    monkeypatch.setattr(settings, "max_tool_estimated_tokens", 2500)

    result = tool.execute_mongo_query("script_1", _outline_args(limit=10))

    assert result.coverage["has_more"] is True
    assert result.coverage["next_scene_sort"] == 2
    assert result.coverage["returned_scene_sorts"] == [1]


def test_single_scene_with_more_documents_than_limit_is_returned_whole(monkeypatch):
    rows = [
        {"scene_sort": 1, "contents": [{"content": f"片段{i}"}]}
        for i in range(60)
    ] + [{"scene_sort": 2, "contents": [{"content": "下一场"}]}]
    collection = FakeCollection(rows)
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))

    result = tool.execute_mongo_query("script_1", _outline_args(limit=1))

    assert result.coverage["returned_scene_sorts"] == [1]
    assert len(result.payload) == 60
    assert result.coverage["next_scene_sort"] == 2
    assert result.coverage["has_more"] is True


def test_limit_counts_complete_scenes_not_documents(monkeypatch):
    rows = [
        {"scene_sort": 1, "contents": [{"content": "一"}]},
        {"scene_sort": 2, "contents": [{"content": "二上"}]},
        {"scene_sort": 2, "contents": [{"content": "二下"}]},
    ]
    collection = FakeCollection(rows)
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))

    result = tool.execute_mongo_query("script_1", _outline_args(limit=2))

    assert result.coverage["returned_scene_sorts"] == [1, 2]
    assert [row["scene_sort"] for row in result.payload] == [1, 2, 2]
    assert result.coverage["next_scene_sort"] is None


def test_connection_errors_are_db_unavailable(monkeypatch):
    for exc in (ConnectionFailure("secret-host"), ServerSelectionTimeoutError("secret-host")):
        collection = FakeCollection(error=exc)
        monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))
        result = tool.execute_mongo_query("script_1", _outline_args(limit=1))
        assert result.error_code == "db_unavailable"
        assert "secret-host" not in result.full_result


def test_execution_timeout_is_classified(monkeypatch):
    collection = FakeCollection(error=ExecutionTimeout("private query"))
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))
    result = tool.execute_mongo_query("script_1", _outline_args(limit=1))
    assert result.error_code == "db_timeout"
    assert "private query" not in result.full_result


def test_query_failure_is_not_database_unavailable(monkeypatch):
    collection = FakeCollection(error=OperationFailure("private query"))
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))
    result = tool.execute_mongo_query("script_1", _outline_args(limit=1))
    assert result.error_code == "query_failed"
    assert "private query" not in result.full_result


def test_program_error_is_internal_error(monkeypatch):
    collection = FakeCollection(error=ValueError("private bug"))
    monkeypatch.setattr(tool, "get_db", lambda: FakeDb({tool.OUTLINE_COLLECTION: collection}))
    result = tool.execute_mongo_query("script_1", _outline_args(limit=1))
    assert result.error_code == "internal_error"
    assert "private bug" not in result.full_result
