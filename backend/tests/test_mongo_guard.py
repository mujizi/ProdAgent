"""Guard 单元测试（plan §15 pytest）。"""
import pytest

from app.tools.mongo_guard import GuardError, validate_and_normalize


def base_args(**over):
    args = {
        "collection": "seca_scene_analysis",
        "operation": "find",
        "filter": {"scene_sort": 8},
        "projection": {"_id": 0, "scene_sort": 1, "scene_brief": 1},
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
        "script_001", base_args(filter={"summary": {"$regex": long_regex}})
    )
    assert len(out["filter"]["summary"]["$regex"]) == 50


def test_regex_too_long_alternation_keeps_complete_keywords():
    long_regex = "服装|衣服|外套|制服|囚服|衬衫|西装|领带|鞋子|帽子|警服|长袍"
    out = validate_and_normalize(
        "script_001", base_args(filter={"content_text": {"$regex": long_regex}})
    )
    regex = out["filter"]["content_text"]["$regex"]
    assert len(regex) <= 50
    assert regex.startswith("服装|衣服")
    assert not regex.endswith("|")


def test_regex_ok_within_limit():
    out = validate_and_normalize(
        "script_001", base_args(filter={"scene_brief": {"$regex": "戒指"}})
    )
    assert out["filter"]["script_id"] == "script_001"


def test_script_id_injected_and_overrides():
    out = validate_and_normalize(
        "script_001", base_args(filter={"script_id": "evil", "scene_sort": 8})
    )
    assert out["filter"]["script_id"] == "script_001"
    assert out["filter"]["scene_sort"] == 8


def test_limit_default_when_missing():
    out = validate_and_normalize("script_001", base_args())
    assert out["limit"] == 20


def test_limit_capped_at_50():
    out = validate_and_normalize("script_001", base_args(limit=999))
    assert out["limit"] == 50


def test_content_query_limit_capped_at_10():
    # 查 content_text 字段 → limit 上限压到 10
    out = validate_and_normalize(
        "script_001",
        base_args(
            collection="seca_gen_scene_outline",
            projection={"_id": 0, "content_text": 1},
            limit=50,
        ),
    )
    assert out["limit"] == 10


def test_default_projection_excludes_id_and_is_collection_specific():
    # 未指定 projection → 用每表默认精简 projection
    out = validate_and_normalize("script_001", base_args(projection=None))
    assert out["projection"]["_id"] == 0
    assert "scene_brief" in out["projection"]


def test_outline_default_projection_caps_content_limit():
    # outline 默认 projection 含 contents → 视为查 content → cap 10
    out = validate_and_normalize(
        "script_001",
        base_args(collection="seca_gen_scene_outline", projection=None, limit=50),
    )
    assert out["limit"] == 10


def test_missing_purpose_reject():
    args = base_args()
    del args["purpose"]
    with pytest.raises(GuardError):
        validate_and_normalize("script_001", args)


def test_missing_script_id_reject():
    with pytest.raises(GuardError):
        validate_and_normalize("", base_args())
