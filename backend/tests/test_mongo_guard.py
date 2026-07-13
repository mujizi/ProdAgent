"""Guard 单元测试（plan §15 pytest）。"""
import pytest

from app.tools.mongo_guard import GuardError, validate_and_normalize


def base_args(**over):
    args = {
        "collection": "seca_gen_scene_outline",
        "operation": "find",
        "filter": {"scene_sort": 8},
        "projection": {"_id": 0, "scene_sort": 1, "scene_summary": 1},
        "purpose": "测试",
    }
    args.update(over)
    return args


def test_collection_whitelist_reject():
    with pytest.raises(GuardError):
        validate_and_normalize("script_001", base_args(collection="users"))


def test_is_deleted_injected():
    out = validate_and_normalize("script_001", base_args())
    assert out["filter"]["is_deleted"] == 0


def test_is_deleted_injected_overrides():
    out = validate_and_normalize(
        "script_001", base_args(filter={"is_deleted": 1, "scene_sort": 8})
    )
    assert out["filter"]["is_deleted"] == 0


def test_operation_whitelist_reject():
    for op in ("insert", "update", "delete", "drop", "aggregate"):
        with pytest.raises(GuardError):
            validate_and_normalize("script_001", base_args(operation=op))


def test_forbidden_operator_where():
    with pytest.raises(GuardError):
        validate_and_normalize(
            "script_001", base_args(filter={"$where": "this.x==1"})
        )


def test_forbidden_operator_nested():
    with pytest.raises(GuardError):
        validate_and_normalize(
            "script_001",
            base_args(filter={"a": {"b": {"$function": {}}}}),
        )


def test_regex_too_long():
    long_regex = "a" * 60
    out = validate_and_normalize(
        "script_001",
        base_args(
            collection="seca_element_type_detail",
            filter={"remark": {"$regex": long_regex}},
        ),
    )
    assert len(out["filter"]["remark"]["$regex"]) == 50


def test_regex_too_long_alternation_keeps_complete_keywords():
    long_regex = "服装|衣服|外套|制服|囚服|衬衫|西装|领带|鞋子|帽子|警服|长袍"
    out = validate_and_normalize(
        "script_001", base_args(filter={"content_text": {"$regex": long_regex}})
    )
    assert "content_text" not in out["filter"]
    assert out["filter"] == {"script_id": "script_001", "is_deleted": 0}


def test_regex_ok_within_limit():
    out = validate_and_normalize(
        "script_001", base_args(filter={"scene_summary": {"$regex": "戒指"}})
    )
    assert out["filter"]["script_id"] == "script_001"
    assert "scene_summary" not in out["filter"]


def test_script_id_injected_and_overrides():
    out = validate_and_normalize(
        "script_001", base_args(filter={"script_id": "evil", "scene_sort": 8})
    )
    assert out["filter"]["script_id"] == "script_001"
    assert out["filter"]["scene_sort"] == 8


def test_limit_default_when_missing():
    out = validate_and_normalize("script_001", base_args())
    assert out["limit"] == 50


def test_limit_capped_at_50():
    out = validate_and_normalize("script_001", base_args(limit=999))
    assert out["limit"] == 50


def test_content_query_limit_allows_small_full_script_read():
    # 查 content_text 字段，小剧本全剧通读允许一次覆盖 37 场。
    out = validate_and_normalize(
        "script_001",
        base_args(
            collection="seca_gen_scene_outline",
            projection={"_id": 0, "content_text": 1},
            limit=37,
        ),
    )
    assert out["limit"] == 37


def test_content_query_limit_still_capped_at_max():
    out = validate_and_normalize(
        "script_001",
        base_args(
            collection="seca_gen_scene_outline",
            projection={"_id": 0, "content_text": 1},
            limit=999,
        ),
    )
    assert out["limit"] == 50


def test_default_projection_excludes_id_and_is_collection_specific():
    # 未指定 projection → 用每表默认精简 projection
    out = validate_and_normalize("script_001", base_args(projection=None))
    assert out["projection"]["_id"] == 0
    assert "contents" in out["projection"]
    assert out["sort"] == {"scene_sort": 1, "_id": 1}


def test_outline_default_projection_caps_content_limit():
    # outline 默认 projection 含 contents → 视为查 content → cap 到正文查询上限
    out = validate_and_normalize(
        "script_001",
        base_args(collection="seca_gen_scene_outline", projection=None, limit=999),
    )
    assert out["limit"] == 50


def test_outline_text_filter_is_stripped_but_scene_sort_is_preserved():
    out = validate_and_normalize(
        "script_001",
        base_args(
            filter={
                "$and": [
                    {"content_text": {"$regex": "王艳凤"}},
                    {"contents.content": {"$regex": "钱老哥"}},
                    {"scene_sort": {"$gte": 20, "$lte": 25}},
                ]
            },
            projection={"_id": 0, "scene_sort": 1, "scene_title": 1},
            limit=None,
        ),
    )
    assert out["filter"] == {
        "scene_sort": {"$gte": 20, "$lte": 25},
        "script_id": "script_001",
        "is_deleted": 0,
    }
    assert out["projection"]["contents"] == 1
    assert out["limit"] == 50
    assert out["sort"] == {"scene_sort": 1, "_id": 1}


def test_outline_name_filter_without_scene_sort_reads_original_range():
    out = validate_and_normalize(
        "script_001",
        base_args(
            filter={
                "content_text": {
                    "$all": [
                        {"$regex": "王艳凤"},
                        {"$regex": "麻将馆老板娘"},
                        {"$regex": "钱老哥"},
                    ]
                }
            },
            projection={"_id": 0, "scene_sort": 1, "scene_title": 1},
            limit=50,
        ),
    )
    assert out["filter"] == {"script_id": "script_001", "is_deleted": 0}
    assert out["projection"]["contents"] == 1
    assert out["limit"] == 50
    assert out["sort"] == {"scene_sort": 1, "_id": 1}


def test_outline_count_rejected():
    args = base_args()
    args["operation"] = "count"
    with pytest.raises(GuardError, match="原文不支持 count"):
        validate_and_normalize("script_001", args)


def test_element_count_allowed():
    args = base_args()
    args.update({
        "collection": "seca_element_type_detail",
        "operation": "count",
        "filter": {"element_type_code": "main_cast"},
    })
    out = validate_and_normalize("script_001", args)
    assert out["operation"] == "count"
    assert out["filter"]["element_type_code"] == "main_cast"


def test_outline_scene_sort_or_rejected_instead_of_silently_dropping_branch():
    with pytest.raises(GuardError, match=r"不支持 \$or"):
        validate_and_normalize(
            "script_001",
            base_args(filter={"$or": [{"scene_sort": 1}, {"scene_sort": 2}]}),
        )


def test_outline_multiple_and_scene_ranges_rejected():
    with pytest.raises(GuardError, match="只能提供一个 scene_sort"):
        validate_and_normalize(
            "script_001",
            base_args(filter={"$and": [
                {"scene_sort": {"$gte": 1}},
                {"scene_sort": {"$lte": 5}},
            ]}),
        )


def test_outline_sort_is_forced_to_stable_scene_order():
    out = validate_and_normalize(
        "script_001",
        base_args(sort={"scene_title": -1}),
    )
    assert out["sort"] == {"scene_sort": 1, "_id": 1}


@pytest.mark.parametrize("bad_limit", [True, "10", 1.5, {}, []])
def test_invalid_limit_rejected(bad_limit):
    with pytest.raises(GuardError, match="limit 必须是整数"):
        validate_and_normalize("script_001", base_args(limit=bad_limit))


def test_missing_purpose_reject():
    args = base_args()
    del args["purpose"]
    with pytest.raises(GuardError):
        validate_and_normalize("script_001", args)


def test_missing_script_id_reject():
    with pytest.raises(GuardError):
        validate_and_normalize("", base_args())
