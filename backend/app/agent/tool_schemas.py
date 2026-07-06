"""LLM 工具定义（plan §8）。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_mongo_query",
            "description": (
                "查询剧本 MongoDB 数据库，只允许只读查询。"
                "用于检索剧本原文、分场摘要、人物、服装、化妆、道具和场景信息。"
                "系统会自动注入 script_id 与 is_deleted=0，无需自己传。"
                "注意：seca_element_type_detail 是预抽取候选表，结果可能不准；"
                "涉及数量、名单、是否存在、分类归属、具体出现情况等结论时，"
                "先查抽取表获取候选，第二步必须查 seca_gen_scene_outline 并通读剧本原文所有场次后回答。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": [
                            "seca_gen_scene_outline",
                            "seca_scene_analysis",
                            "seca_element_type_detail",
                        ],
                        "description": (
                            "要查询的 collection："
                            "seca_gen_scene_outline=剧本原文(字段 scene_sort/scene_title/"
                            "scene_summary/content_text，content_text 是拼接后的完整原文)；"
                            "seca_scene_analysis=场景摘要(字段 scene_sort/scene_title/"
                            "scene_brief=场景摘要/scene_location/interior_exterior/time_of_day，"
                            "用于快速理解大概发生了什么)；"
                            "seca_element_type_detail=预抽取元素(字段 element_type_code/"
                            "element_name/remark)，按 element_type_code 区分类型；"
                            "该表只作候选线索，统计/名单/准确性/分类归属/出现情况问题第二步必须查 "
                            "seca_gen_scene_outline 并通读剧本原文所有场次后回答："
                            "main_cast=主要人物, supporting_cast=次要人物, "
                            "background_actor=群演, props_action=动作道具, "
                            "props_static=静态道具, location=地点/场景, costume=服装, "
                            "makeup=化妆, special_effects=特效"
                        ),
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["find", "count"],
                        "description": "查询类型",
                    },
                    "filter": {
                        "type": "object",
                        "description": (
                            "Mongo 查询条件，不需要传 script_id / is_deleted，系统会自动注入。"
                            "按场次查用 scene_sort（整数，从 1 开始）；"
                            "查元素类型用 element_type_code。"
                        ),
                    },
                    "projection": {"type": "object", "description": "返回字段"},
                    "sort": {"type": "object", "description": "排序条件"},
                    "limit": {
                        "type": "integer",
                        "description": "最大返回条数，最大 50",
                    },
                    "purpose": {"type": "string", "description": "本次查询目的"},
                },
                "required": ["collection", "operation", "purpose"],
            },
        },
    }
]
