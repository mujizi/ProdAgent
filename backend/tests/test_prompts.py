from app.agent.prompts import build_system_prompt


def test_system_prompt_instructs_batching_for_large_scripts():
    prompt = build_system_prompt(
        "- 原文表检测到可靠场次数：250 场（测试桩）。"
    )

    assert "总场次数 >50" in prompt
    assert "每 50 场一批" in prompt
    assert "1-50、51-100、101-150、151-200、201-250" in prompt
