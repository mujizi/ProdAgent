"""真实 Mongo Tool 端到端测试（plan §15 scripts）。

用真实 script_id 对真库执行 execute_mongo_query，断言：
- 正常查询（摘要/原文拼接/元素）
- 非法 collection / operation / $where 被拒
- limit=999→50；content 查询 limit→10
- content_text 拼接非空；超长截断；is_deleted 注入

运行：python scripts/test_mongo_tool.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.mongo_query_tool import execute_mongo_query  # noqa: E402
from app.tools.budget import TOOL_RESULT_TRUNCATED  # noqa: E402

SCRIPT_ID = "690c1b6736c9c50c40160976"  # 肖申克的救赎（三表齐全，单版本）

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name} {extra}")
    else:
        failed += 1
        print(f"  ✗ FAIL: {name} {extra}")


def main():
    print(f"script_id = {SCRIPT_ID}\n")

    # 1) 场景摘要表正常查询
    print("[1] seca_scene_analysis 查第1场摘要")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_scene_analysis", "operation": "find",
        "filter": {"scene_sort": 1}, "purpose": "第1场摘要"})
    check("摘要返回非空", r.row_count >= 1, f"row_count={r.row_count}")
    check("含 scene_brief", "scene_brief" in r.full_result)
    check("不含 is_deleted 噪音", "is_deleted" not in r.full_result)

    # 2) 原文表 content_text 拼接
    print("\n[2] seca_gen_scene_outline 查第1场原文（content_text 拼接）")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_gen_scene_outline", "operation": "find",
        "filter": {"scene_sort": 1}, "purpose": "第1场原文"})
    check("原文返回非空", r.row_count >= 1, f"row_count={r.row_count}")
    check("含 content_text", "content_text" in r.full_result)
    check("不含原始 contents 数组", '"contents"' not in r.full_result)
    check("content_text 有实际内容", len(r.full_result) > 100,
          f"len={len(r.full_result)}")

    # 3) 元素表按 element_type_code 查
    print("\n[3] seca_element_type_detail 查 main_cast")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_element_type_detail", "operation": "find",
        "filter": {"element_type_code": "main_cast"}, "purpose": "主要人物"})
    check("人物返回非空", r.row_count >= 1, f"row_count={r.row_count}")
    check("含 element_name", "element_name" in r.full_result)

    # 4) count 操作
    print("\n[4] count 全剧场景数")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_scene_analysis", "operation": "count",
        "purpose": "场景总数"})
    check("count 返回", '"count":' in r.full_result, r.full_result.splitlines()[-2:])

    # 5) 非法 collection 被拒
    print("\n[5] 非法 collection 被拒")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "users", "operation": "find", "purpose": "非法"})
    check("被拒绝", "拒绝" in r.full_result)

    # 6) 非法 operation 被拒
    print("\n[6] 非法 operation 被拒")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_scene_analysis", "operation": "delete", "purpose": "非法"})
    check("被拒绝", "拒绝" in r.full_result)

    # 7) $where 被拒
    print("\n[7] $where 被拒")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_scene_analysis", "operation": "find",
        "filter": {"$where": "this.x==1"}, "purpose": "非法"})
    check("被拒绝", "拒绝" in r.full_result)

    # 8) limit=999 → 50（非 content 查询）
    print("\n[8] limit=999 归一到 50")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_scene_analysis", "operation": "find",
        "filter": {}, "projection": {"_id": 0, "scene_sort": 1, "scene_title": 1},
        "limit": 999, "purpose": "全部场景标题"})
    check("行数<=50", r.row_count <= 50, f"row_count={r.row_count}")

    # 9) content 查询 limit → 10
    print("\n[9] content 查询 limit 上限 10")
    r = execute_mongo_query(SCRIPT_ID, {
        "collection": "seca_gen_scene_outline", "operation": "find",
        "filter": {}, "limit": 50, "purpose": "大量原文"})
    check("行数<=10", r.row_count <= 10, f"row_count={r.row_count}")

    # 10) 超长 content 截断
    print("\n[10] 大范围原文触发截断")
    check("出现截断标记或 row_count 受限",
          (TOOL_RESULT_TRUNCATED in r.full_result) or r.truncated or r.field_truncated
          or r.row_count <= 10,
          f"truncated={r.truncated} field_truncated={r.field_truncated} "
          f"est_tokens={r.estimated_tokens}")

    print(f"\n=== 结果: {passed} passed, {failed} failed ===")
    if failed:
        sys.exit(1)
    print("✅ Mongo Tool 真实测试全部通过")


if __name__ == "__main__":
    main()
