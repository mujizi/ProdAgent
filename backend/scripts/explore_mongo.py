"""一次性探查脚本：连真库，列 DB / collection，采样目标表的真实字段结构。

运行：python scripts/explore_mongo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient  # noqa: E402

from app.config import settings  # noqa: E402

TARGETS = ["seca_gen_scene_outline", "seca_element_type_detail"]


def describe_value(v, depth=0):
    t = type(v).__name__
    if isinstance(v, list):
        inner = describe_value(v[0], depth + 1) if v else "empty"
        return f"list[len={len(v)}] of ({inner})"
    if isinstance(v, dict):
        keys = list(v.keys())
        return f"dict(keys={keys})"
    s = str(v)
    if len(s) > 120:
        s = s[:120] + "..."
    return f"{t}: {s}"


def main():
    print("URI host:", settings.mongo_uri.split("@")[-1][:60])
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    print("✓ ping OK\n")

    dbs = client.list_database_names()
    print("databases:", dbs, "\n")

    # 优先使用 .env 配置的 MONGO_DB；否则找第一个目标表齐全的 DB
    target_db = settings.mongo_db or None
    if not target_db:
        for dbname in dbs:
            if dbname in ("admin", "local", "config"):
                continue
            colls = client[dbname].list_collection_names()
            if all(c in colls for c in TARGETS):
                target_db = dbname
                break

    if not target_db:
        print("\n⚠️ 未找到目标表齐全的 DB")
        return

    print(f"\n>>> 使用 DB: {target_db}\n")
    db = client[target_db]

    for name in TARGETS:
        print(f"========== {name} ==========")
        coll = db[name]
        total = coll.estimated_document_count()
        print("estimated_count:", total)
        # 看有哪些 script_id（取前几个 distinct，限量避免太大）
        try:
            sample_ids = coll.distinct("script_id")[:5]
            print("script_id 样例(前5):", sample_ids)
        except Exception as e:
            print("distinct script_id 失败:", e)

        doc = coll.find_one()
        if not doc:
            print("(空表)\n")
            continue
        print("字段结构:")
        for k, v in doc.items():
            print(f"  - {k}: {describe_value(v)}")

        # 对 contents 字段特别展开（原文表）
        if "contents" in doc:
            print("\n  >>> contents 详细形态:")
            c = doc["contents"]
            print("     type:", type(c).__name__)
            if isinstance(c, list) and c:
                print("     第一个元素:", describe_value(c[0]))
                if isinstance(c[0], dict):
                    for kk, vv in c[0].items():
                        print(f"        {kk}: {describe_value(vv)}")
        print()

    print(f"\n>>> 把这个 DB 名填进 .env 的 MONGO_DB: {target_db}")


if __name__ == "__main__":
    main()
