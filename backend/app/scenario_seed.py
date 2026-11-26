"""认领闭环剧本数据：6 条待复核候选、其候选证据版本与复核队列匹配清单。

设计要点：
- 每条待复核匹配（sku_match）都由一个候选证据版本（candidate_evidence）产生，
  复核队列 match_review 的匹配清单记录通过 ``证据版本`` 与 sku_match 双向对账。
- 剧本默认页大小 4 时，第二页（第 5、6 条）正好是待复核的 R1（id=105）和 R3（id=106）；
  R1（单瓶）随后被上游更正为两瓶组合装，替换后的 R2 以 id=107 追加为第 7 条。
- 旧证据版本被撤回时记录 ``失效原因``，认领单条目据此进入「等待重确认」。
"""
from __future__ import annotations

from typing import Any

# 剧本内 sku_match / match_review 的固定编号，复位剧本与 E2E 复做脚本依赖这些稳定标识。
R1_MATCH_ID = 105
R3_MATCH_ID = 106
R2_MATCH_ID = 107
SCENARIO_SKU_IDS = [101, 102, 103, 104, 105, 106]
SCENARIO_REVIEW_IDS = [101, 102, 103, 104, 105, 106]
SCENARIO_PAGE_SIZE = 4

# 每条候选按展示顺序排列：(sku_match id, 商品档案, 归一规格, 证据版本, 证据文本, 置信度, 候选代号)
_SCENARIO_CANDIDATES: list[tuple[int, str, str, str, str, str, str]] = [
    (101, "G-1002 苏打水", "单瓶 450ml", "EV-R4-v1", "苏打水 450ml × 1 瓶", "0.78", "R4"),
    (102, "G-1003 茶饮", "单瓶 600ml", "EV-R5-v1", "茶饮 600ml × 1 瓶", "0.80", "R5"),
    (103, "G-1004 果汁", "单瓶 350ml", "EV-R6-v1", "果汁 350ml × 1 瓶", "0.75", "R6"),
    (104, "G-1005 咖啡", "单瓶 270ml", "EV-R7-v1", "咖啡 270ml × 1 瓶", "0.83", "R7"),
    (105, "G-1001 矿泉水", "单瓶 500ml", "EV-R1-v1", "矿泉水 500ml × 1 瓶", "0.82", "R1"),
    (106, "G-1006 矿泉水", "单瓶 500ml", "EV-R3-v1", "矿泉水 500ml × 1 瓶", "0.81", "R3"),
]

# 允许认领复核的有效角色
REVIEW_ROLES = ("规格审核员", "商品运营", "数据治理专员")

BATCH_NO = "BATCH-2026-11"


def build_scenario_tables() -> dict[str, list[dict[str, Any]]]:
    """生成剧本涉及的四张表初始快照。"""
    sku_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for sku_id, goods, spec, evidence_id, evidence_text, confidence, code in _SCENARIO_CANDIDATES:
        sku_rows.append({
            "id": sku_id,
            "status": "人工复核",
            "pending": True,
            "abnormal": False,
            "匹配批次": BATCH_NO,
            "商品档案": goods,
            "候选规格": spec,
            "归一规格": spec,
            "匹配置信度": confidence,
            "匹配状态": "待人工裁决",
            "证据版本": evidence_id,
            "候选代号": code,
            "回填认领单": "",
            "回填时间": "",
        })
        evidence_rows.append({
            "id": evidence_id,
            "status": "有效",
            "pending": True,
            "abnormal": False,
            "证据版本": evidence_id,
            "匹配记录": str(sku_id),
            "证据原文": evidence_text,
            "归一规格": spec,
            "版本序号": 1,
            "失效原因": "",
            "替换为": "",
            "产生时间": "2026-11-26T09:00:00+00:00",
        })
        review_rows.append({
            "id": sku_id,
            "status": "待复核",
            "pending": True,
            "abnormal": False,
            "记录编号": f"MR-{sku_id}",
            "匹配记录": str(sku_id),
            "复核结论": f"置信度 {confidence}，待人工裁决",
            "复核角色": "",
            "复核时间": "",
            "证据版本": evidence_id,
            "归一规格": spec,
            "认领单": "",
            "认领资格": "",
        })

    return {
        "sku_match": sku_rows,
        "candidate_evidence": evidence_rows,
        "match_review": review_rows,
        "claim_order": [],
    }
