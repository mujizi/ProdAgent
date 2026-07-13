from app.tools import character_resolver as resolver


def test_candidate_score_keeps_possible_full_name_for_model_judgment():
    score, reason = resolver._candidate_score(
        "暗迪",
        "安迪·杜弗兰",
    )
    assert score > 0
    assert reason == "候选名相近"


def test_exact_match_against_name_forms():
    assert resolver._candidate_exact_match(
        "安迪",
        [{"name": "安迪·杜弗兰", "score": 1.0}],
    ) == "安迪·杜弗兰"


def test_heuristic_prefix_is_not_an_exact_match():
    candidates = [{"name": "欧阳娜娜", "score": 0.94}]
    assert resolver._candidate_exact_match("欧阳", candidates) is None
    score, _reason = resolver._candidate_score("欧阳", "欧阳娜娜")
    assert score > 0


def test_translated_name_component_can_be_exact_form():
    candidates = [{"name": "安迪·杜弗兰", "score": 1.0}]
    assert resolver._candidate_exact_match("安迪", candidates) == "安迪·杜弗兰"


def test_zero_score_candidates_are_not_plausible_for_clarification():
    assert not resolver._has_plausible_candidate([
        {"name": "杨小福", "score": 0.0},
        {"name": "李春生", "score": 0.0},
    ])


def test_positive_score_candidate_is_plausible_for_clarification():
    assert resolver._has_plausible_candidate([
        {"name": "瑞德", "score": 0.5},
    ])


def test_exact_candidate_uses_candidate_authority(monkeypatch):
    monkeypatch.setattr(resolver, "_element_candidates", lambda *_: [
        {"name": "安迪·杜弗兰", "score": 1.0, "reason": "候选名完全一致", "remark": ""},
    ])
    monkeypatch.setattr(
        resolver, "_original_exact_hits",
        lambda *_: (_ for _ in ()).throw(AssertionError("精确候选不应再查原文")),
    )

    result = resolver.resolve_character_name(
        "script_1", {"raw_name": "安迪", "purpose": "核实人物"}
    )

    assert result.payload["status"] == "candidate_exact"
    assert result.payload["canonical_name"] == "安迪·杜弗兰"
    assert result.payload["authority"] == "人物候选信息"


def test_original_exact_precedes_fuzzy_clarification(monkeypatch):
    monkeypatch.setattr(resolver, "_element_candidates", lambda *_: [
        {"name": "安迪", "score": 0.5, "reason": "候选名相近", "remark": ""},
    ])
    hit = resolver._OriginalHit(8, "第八场", "暗迪", "原文出现")
    monkeypatch.setattr(
        resolver, "_original_exact_hits", lambda *_: ("暗迪", [hit], "original_exact")
    )

    result = resolver.resolve_character_name(
        "script_1", {"raw_name": "暗迪", "purpose": "核实人物"}
    )

    assert result.payload["status"] == "original_exact"
    assert result.payload["clarification_required"] is False
    assert result.payload["authority"] == "剧本原文"


def test_fuzzy_candidate_clarifies_only_after_original_miss(monkeypatch):
    monkeypatch.setattr(resolver, "_element_candidates", lambda *_: [
        {"name": "安迪", "score": 0.5, "reason": "候选名相近", "remark": ""},
    ])
    monkeypatch.setattr(
        resolver, "_original_exact_hits", lambda *_: (None, [], "not_found")
    )

    result = resolver.resolve_character_name(
        "script_1", {"raw_name": "暗迪", "purpose": "核实人物"}
    )

    assert result.payload["status"] == "needs_clarification"
    assert result.payload["clarification_required"] is True
    assert result.payload["authority"] == "未确认"


def test_no_candidate_and_original_miss_is_unconfirmed(monkeypatch):
    monkeypatch.setattr(resolver, "_element_candidates", lambda *_: [])
    monkeypatch.setattr(
        resolver, "_original_exact_hits", lambda *_: (None, [], "not_found")
    )

    result = resolver.resolve_character_name(
        "script_1", {"raw_name": "不存在的写法", "purpose": "核实人物"}
    )

    assert result.payload["matched"] is False
    assert result.payload["clarification_required"] is False
    assert "未确认" in result.payload["message"]
