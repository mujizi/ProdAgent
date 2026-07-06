"""深挖：element_type_code 枚举、多版本情况、contents 拼接、is_deleted、可用 script_id。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient  # noqa: E402

from app.config import settings  # noqa: E402

client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=8000)
db = client[settings.mongo_db]

outline = db["seca_gen_scene_outline"]
element = db["seca_element_type_detail"]
analysis = db["seca_scene_analysis"]

print("===== 1) element_type_code 枚举（采样 3000 条统计）=====")
codes = Counter()
names_by_code = {}
for d in element.find({}, {"element_type_code": 1, "element_name": 1}).limit(3000):
    c = d.get("element_type_code")
    codes[c] += 1
    names_by_code.setdefault(c, [])
    if len(names_by_code[c]) < 4:
        names_by_code[c].append(d.get("element_name"))
for c, n in codes.most_common():
    print(f"  {c}: {n}  样例={names_by_code.get(c)}")

print("\n===== 2) is_deleted 取值分布（各表采样 2000）=====")
for name, coll in [("outline", outline), ("element", element), ("analysis", analysis)]:
    vals = Counter(d.get("is_deleted") for d in coll.find({}, {"is_deleted": 1}).limit(2000))
    print(f"  {name}: {dict(vals)}")

print("\n===== 3) 找一个三表都有数据的 script_id =====")
# 用 element 表里某个 script_id 去三表查
candidate = None
for sid in element.distinct("script_id")[:40]:
    if not sid:
        continue
    o = outline.count_documents({"script_id": sid, "is_deleted": 0}, limit=1)
    a = analysis.count_documents({"script_id": sid, "is_deleted": 0}, limit=1)
    e = element.count_documents({"script_id": sid, "is_deleted": 0}, limit=1)
    if o and a and e:
        candidate = sid
        print(f"  ✓ 三表齐全 script_id={sid}")
        break
    else:
        print(f"  - {sid}: outline={o} analysis={a} element={e}")

if candidate:
    sid = candidate
    print(f"\n===== 4) script_id={sid} 多版本检查 =====")
    for name, coll in [("outline", outline), ("element", element), ("analysis", analysis)]:
        vers = coll.distinct("version_id", {"script_id": sid})
        cnt = coll.count_documents({"script_id": sid, "is_deleted": 0})
        print(f"  {name}: doc_count={cnt} version_ids={vers}")

    print(f"\n===== 5) script_id={sid} outline 的 contents 拼接形态 =====")
    docs = list(outline.find(
        {"script_id": sid, "is_deleted": 0},
        {"scene_sort": 1, "scene_title": 1, "contents": 1},
    ).sort("scene_sort", 1).limit(3))
    for d in docs:
        contents = d.get("contents") or []
        print(f"  --- scene_sort={d.get('scene_sort')} title={d.get('scene_title')} "
              f"contents_len={len(contents)} ---")
        for i, item in enumerate(contents):
            if isinstance(item, dict):
                ct = (item.get("content") or "")
                print(f"     [{i}] type={item.get('type')} content_len={len(ct)} "
                      f"head={ct[:80]!r}")
        # 拼接示例
        joined = "\n".join(
            (it.get("content") or "") for it in contents if isinstance(it, dict)
        )
        print(f"     >>> 拼接后总长={len(joined)}")

    print(f"\n===== 6) script_id={sid} element 各类型计数 =====")
    ec = Counter(d.get("element_type_code")
                 for d in element.find({"script_id": sid, "is_deleted": 0},
                                       {"element_type_code": 1}))
    print("  ", dict(ec))
