"""Step 3（plan §15）：Mongo 连接 + 目标表各取一条 + 打印字段结构。

运行：python scripts/test_mongo_connection.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db.mongo_client import get_db, ping  # noqa: E402

COLLECTIONS = [
    "seca_gen_scene_outline",
    "seca_element_type_detail",
]


def main():
    assert settings.mongo_uri, "MONGO_URI 未配置"
    assert settings.mongo_db, "MONGO_DB 未配置"
    print(f"DB: {settings.mongo_db}")
    ping()
    print("✓ ping OK")

    db = get_db()
    existing = db.list_collection_names()
    print("现有 collections:", existing)

    for name in COLLECTIONS:
        print(f"\n=== {name} ===")
        coll = db[name]
        count = coll.estimated_document_count()
        print("estimated_count:", count)
        doc = coll.find_one()
        if not doc:
            print("  (空表)")
            continue
        print("  字段:")
        for k, v in doc.items():
            preview = str(v)
            if len(preview) > 80:
                preview = preview[:80] + "..."
            print(f"    {k}: ({type(v).__name__}) {preview}")

    print("\n✅ Mongo 连接与目标表字段结构打印完成。")


if __name__ == "__main__":
    main()
