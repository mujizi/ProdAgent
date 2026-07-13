"""LLM 工具定义（plan §8）。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_character_name",
            "description": (
                "解析用户输入中尚未被可靠确认或可能写错的人物名。"
                "用户输入疑似错别字、同音字或别名时必须先调用。"
                "该工具先核对人物候选信息；没有精确候选时检查原文是否正向出现，"
                "原文未确认后才返回相近候选供用户澄清。"
                "当 clarification_required=true 时，不要继续查询剧情，应先问用户是否指某个候选人物。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "raw_name": {
                        "type": "string",
                        "description": "用户原始输入的人物名，例如“杨小富”。",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "本次解析目的，例如“核实用户提到的人物名”。",
                    },
                },
                "required": ["raw_name", "purpose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_mongo_query",
            "description": (
                "查询剧本 MongoDB 数据库，只允许只读查询。"
                "用于检索剧本原文、人物、服装、化妆、道具和场景信息。"
                "系统会自动注入 script_id 与 is_deleted=0，无需自己传。"
                "查询剧本原文 seca_gen_scene_outline 时，不要用人物名、称谓、关键词过滤正文；"
                "除非用户指定场次，否则 filter 留空并读取原文后再判断。"
                "注意：seca_element_type_detail 是预抽取候选表，结果可能不准；"
                "涉及数量、名单、是否存在、分类归属、具体出现情况等结论时，"
                "先查抽取表获取候选，第二步必须查 seca_gen_scene_outline 并通读剧本原文所有场次后回答；"
                "如果全剧超过50场，必须按 scene_sort 每50场一批分批查询直到覆盖全部场次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": [
                            "seca_gen_scene_outline",
                            "seca_element_type_detail",
                        ],
                        "description": (
                            "要查询的 collection："
                            "seca_gen_scene_outline=剧本原文(字段 scene_sort/scene_title/"
                            "scene_summary/content_text，content_text 是拼接后的完整原文)；"
                            "seca_element_type_detail=预抽取元素(字段 element_type_code/"
                            "element_name/remark)，按 element_type_code 区分类型；"
                            "该表只作候选线索，统计/名单/准确性/分类归属/出现情况问题第二步必须查 "
                            "seca_gen_scene_outline 并通读剧本原文所有场次后回答；"
                            "超过50场时按 scene_sort 每50场一批查询："
                            "main_cast=主要人物, supporting_cast=次要人物, "
                            "background_actor=群演, props_action=动作道具, "
                            "props_static=静态道具, location=地点/场景, costume=服装, "
                            "makeup=化妆, special_effects=特效"
                        ),
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["find", "count"],
                        "description": (
                            "查询类型。剧本原文 seca_gen_scene_outline 只允许 find；"
                            "count 仅用于元素候选表，原文文档数不等于场次数。"
                        ),
                    },
                    "filter": {
                        "type": "object",
                        "description": (
                        "Mongo 查询条件，不需要传 script_id / is_deleted，系统会自动注入。"
                        "按场次查用 scene_sort（整数，从 1 开始）；"
                        "查元素类型用 element_type_code。查询剧本原文时不要传人物名、"
                        "称谓或关键词过滤 content_text / scene_summary / scene_title；"
                        "没有明确场次时传空对象。"
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
