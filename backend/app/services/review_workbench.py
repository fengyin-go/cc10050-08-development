"""人工复核工作台领域服务：候选结果筛选、证据版本管理、认领单与结论回填闭环。

数据链路位置：裁决层入口。候选结果页读取复核队列（match_review）为认领实际生成的
匹配清单记录与其候选证据版本（candidate_evidence），保证页面看到的每一条都可对账。

关键规则：
1. 筛选期间重新获取只返回仍处待复核、且证据版本有效并仍满足筛选条件的条目，
   已确认（已通过/已驳回）或不匹配归一规格的条目不进交付范围。
2. 批量认领对每条匹配独立判定资格：只有第一条有效认领能取得资格；证据版本被撤回
   的条目进入「等待重确认」；无角色资格或已被他人取得资格的条目不得写回。
3. 结论提交只接受认领单内、资格为「已取得资格」的条目，再由规格匹配器按匹配记录 id
   与证据版本回填这一条可对账的匹配结果。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.scenario_seed import (
    BATCH_NO,
    R1_MATCH_ID,
    R2_MATCH_ID,
    REVIEW_ROLES,
    SCENARIO_PAGE_SIZE,
)
from app.services.sku_match import SkuMatchService
from app.store import store

# 认领条目资格状态
QUALIFIED = "已取得资格"
WAITING = "等待重确认"
UNQUALIFIED = "未取得资格"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewWorkbenchService:
    """复核工作台：不注册进通用资源路由，由专用 review_workbench 路由调用。"""

    sku_service = SkuMatchService()

    # ---------- 候选结果页 ----------

    def list_candidates(
        self,
        *,
        evidence_version: str | None = None,
        normalized_spec: str | None = None,
        page: int = 1,
        size: int = SCENARIO_PAGE_SIZE,
    ) -> dict[str, Any]:
        """输出带候选证据版本的匹配清单（数据源是复核队列实际生成的记录）。

        一致性保证：重新获取时过滤掉非待复核、证据版本失效、规格不匹配的条目，
        已确认的条目不进入交付范围；分页在过滤后的集合上做。
        """
        review_rows = store.rows("match_review")
        evidence_by_id = {e["证据版本"]: e for e in store.rows("candidate_evidence")}
        sku_by_id = {str(m["id"]): m for m in store.rows("sku_match")}

        visible: list[dict[str, Any]] = []
        for review in review_rows:
            if review.get("status") != "待复核":
                # 已确认（已通过/已驳回）的条目绝不进入候选交付范围
                continue
            evidence_id = str(review.get("证据版本", ""))
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence.get("status") != "有效":
                # 证据版本已撤回：不进入可认领候选，页面需到认领单看失效原因
                continue
            spec = str(review.get("归一规格", ""))
            if normalized_spec and normalized_spec.casefold() not in spec.casefold():
                continue
            if evidence_version and evidence_version.casefold() not in evidence_id.casefold():
                continue
            match = sku_by_id.get(str(review.get("匹配记录", "")))
            visible.append(self._candidate_view(review, evidence, match))

        total = len(visible)
        start = (page - 1) * size
        page_items = visible[start:start + size]
        return {
            "ok": True,
            "message": "候选结果已按证据版本与归一规格筛选",
            "items": page_items,
            "total": total,
            "page": page,
            "size": size,
        }

    def _candidate_view(
        self,
        review: dict[str, Any],
        evidence: dict[str, Any],
        match: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "review_id": review.get("id"),
            "记录编号": review.get("记录编号", ""),
            "匹配记录": str(review.get("匹配记录", "")),
            "候选代号": (match or {}).get("候选代号", ""),
            "商品档案": (match or {}).get("商品档案", ""),
            "归一规格": review.get("归一规格", ""),
            "匹配置信度": (match or {}).get("匹配置信度", ""),
            "证据版本": review.get("证据版本", ""),
            "证据原文": evidence.get("证据原文", ""),
            "证据状态": evidence.get("status", ""),
            "证据失效原因": evidence.get("失效原因", ""),
            "认领资格": review.get("认领资格", ""),
            "认领单": review.get("认领单", ""),
            "复核状态": review.get("status", ""),
        }

    # ---------- 上游更正（剧本动作） ----------

    def apply_upstream_correction(self, match_id: int = R1_MATCH_ID) -> dict[str, Any]:
        """模拟上游把单瓶候选更正为两瓶组合装：撤回旧证据、追加替换证据与新匹配。

        旧证据版本记录失效原因；原匹配（R1）保留旧版本快照，复核队列记录不删除，
        已基于旧版本发起的认领据此进入等待重确认。替换后的 R2 作为第 7 条候选追加。
        """
        match = store.find("sku_match", match_id)
        if match is None:
            return {"ok": False, "message": f"匹配记录 {match_id} 不存在"}
        old_evidence_id = str(match.get("证据版本", ""))
        evidence = next(
            (e for e in store.rows("candidate_evidence") if e.get("证据版本") == old_evidence_id),
            None,
        )
        if evidence is None:
            return {"ok": False, "message": f"证据版本 {old_evidence_id} 不存在"}
        if evidence.get("status") == "已撤回":
            return {"ok": False, "message": f"证据版本 {old_evidence_id} 已撤回，不能重复更正"}

        new_spec = "两瓶组合装 500ml"
        new_evidence_id = "EV-R2-v1"
        reason = f"上游更正：单瓶证据 {old_evidence_id} 被替换为两瓶组合装 {new_evidence_id}"

        # 1) 撤回旧证据版本，写明失效原因
        evidence["status"] = "已撤回"
        evidence["pending"] = False
        evidence["abnormal"] = True
        evidence["失效原因"] = reason
        evidence["替换为"] = new_evidence_id

        # 2) R1 匹配记录保留旧版本快照，标注证据已失效，等待复核员重确认
        match["匹配状态"] = "证据版本已撤回，待重确认"
        match["abnormal"] = True

        # 3) 追加替换后的组合装证据 R2 与匹配 R2（第 7 条）
        evidence_rows = store.rows("candidate_evidence")
        if not any(e.get("证据版本") == new_evidence_id for e in evidence_rows):
            evidence_rows.append({
                "id": new_evidence_id,
                "status": "有效",
                "pending": True,
                "abnormal": False,
                "证据版本": new_evidence_id,
                "匹配记录": str(R2_MATCH_ID),
                "证据原文": "矿泉水 500ml × 2 瓶 组合装",
                "归一规格": new_spec,
                "版本序号": 1,
                "失效原因": "",
                "替换为": "",
                "产生时间": _now(),
            })
        sku_rows = store.rows("sku_match")
        if not any(m.get("id") == R2_MATCH_ID for m in sku_rows):
            sku_rows.append({
                "id": R2_MATCH_ID,
                "status": "人工复核",
                "pending": True,
                "abnormal": False,
                "匹配批次": BATCH_NO,
                "商品档案": "G-1001 矿泉水",
                "候选规格": new_spec,
                "归一规格": new_spec,
                "匹配置信度": "0.86",
                "匹配状态": "待人工裁决",
                "证据版本": new_evidence_id,
                "候选代号": "R2",
                "回填认领单": "",
                "回填时间": "",
            })
            review_rows = store.rows("match_review")
            review_rows.append({
                "id": R2_MATCH_ID,
                "status": "待复核",
                "pending": True,
                "abnormal": False,
                "记录编号": f"MR-{R2_MATCH_ID}",
                "匹配记录": str(R2_MATCH_ID),
                "复核结论": "置信度 0.86，待人工裁决（替换 R1 的组合装）",
                "复核角色": "",
                "复核时间": "",
                "证据版本": new_evidence_id,
                "归一规格": new_spec,
                "认领单": "",
                "认领资格": "",
            })

        return {
            "ok": True,
            "message": reason,
            "withdrawn_evidence": old_evidence_id,
            "withdraw_reason": reason,
            "new_evidence": new_evidence_id,
            "new_match_id": R2_MATCH_ID,
            "new_spec": new_spec,
        }

    # ---------- 批量认领 ----------

    def create_claim(
        self,
        *,
        review_ids: list[int],
        reviewer: str,
        role: str,
    ) -> dict[str, Any]:
        """按匹配清单批量认领，生成带条目的认领单。

        每条独立判定资格：
        - 角色不在有效复核角色内：未取得资格（无复核资格）；
        - 匹配已被他人取得资格或已确认：未取得资格；
        - 证据版本已撤回：等待重确认（给出失效原因，先不允许提交结论）；
        - 其余：已取得资格，可从认领单办理。
        """
        if not review_ids:
            return {"ok": False, "message": "请至少选择一条待复核匹配"}

        order_rows = store.rows("claim_order")
        order_id = max((int(o.get("id", 0)) for o in order_rows), default=0) + 1
        order_no = f"CO-{order_id:04d}"
        items: list[dict[str, Any]] = []
        qualified_count = 0
        waiting_count = 0
        unqualified_count = 0

        for review_id in review_ids:
            review = store.find("match_review", review_id)
            item = self._build_claim_item(review_id, review, reviewer, role, order_no)
            items.append(item)
            if item["资格状态"] == QUALIFIED:
                qualified_count += 1
            elif item["资格状态"] == WAITING:
                waiting_count += 1
            else:
                unqualified_count += 1

        order = {
            "id": order_id,
            "认领单号": order_no,
            "status": "办理中",
            "pending": True,
            "abnormal": waiting_count > 0 or unqualified_count > 0,
            "复核员": reviewer,
            "复核角色": role,
            "认领时间": _now(),
            "items": items,
            "qualified_count": qualified_count,
            "waiting_count": waiting_count,
            "unqualified_count": unqualified_count,
        }
        order_rows.append(order)

        # 对取得资格/等待重确认的条目回写复核队列认领标记（未取得资格不占用匹配）
        for item in items:
            review = store.find("match_review", int(item["review_id"]))
            if review is not None and item["资格状态"] in (QUALIFIED, WAITING):
                review["认领单"] = order_no
                review["复核角色"] = role
                review["认领资格"] = item["资格状态"]

        return {
            "ok": True,
            "message": self._claim_summary(order_no, qualified_count, waiting_count, unqualified_count),
            "claim_order": order,
        }

    def _build_claim_item(
        self,
        review_id: int,
        review: dict[str, Any] | None,
        reviewer: str,
        role: str,
        order_no: str,
    ) -> dict[str, Any]:
        base = {
            "item_id": f"{order_no}-{review_id}",
            "review_id": review_id,
            "记录编号": "",
            "匹配记录": "",
            "证据版本": "",
            "归一规格": "",
            "复核员": reviewer,
            "复核角色": role,
            "资格状态": UNQUALIFIED,
            "失效原因": "",
            "可提交结论": False,
            "等待说明": "",
            "结论": "",
            "写回状态": "",
        }
        if review is None:
            base["等待说明"] = "匹配清单记录不存在"
            return base

        base["记录编号"] = review.get("记录编号", "")
        base["匹配记录"] = str(review.get("匹配记录", ""))
        base["证据版本"] = review.get("证据版本", "")
        base["归一规格"] = review.get("归一规格", "")

        # 1) 角色资格校验：无有效资格的请求不能写回规格
        if role not in REVIEW_ROLES:
            base["等待说明"] = f"角色 {role} 无复核资格，请求未取得有效资格"
            return base

        # 2) 已确认条目不能再认领
        if review.get("status") != "待复核":
            base["等待说明"] = f"匹配 {base['匹配记录']} 已确认（{review.get('status')}），不在可认领范围"
            return base

        # 3) 同一待复核匹配只能由一个复核员取得有效资格；
        #    已被其他认领单占用（含等待重确认）的匹配不允许被新认领单接管，
        #    未取得资格不构成占用，其他复核员仍可正常认领。
        existing_order = str(review.get("认领单", "") or "")
        existing_qual = str(review.get("认领资格", "") or "")
        if (
            existing_order
            and existing_order != order_no
            and existing_qual in (QUALIFIED, WAITING)
        ):
            base["等待说明"] = (
                f"匹配 {base['匹配记录']} 已由认领单 {existing_order} 占用"
                f"（当前资格：{existing_qual}）"
            )
            return base

        # 4) 证据版本是否仍有效：撤回则进入等待重确认
        evidence = next(
            (e for e in store.rows("candidate_evidence")
             if e.get("证据版本") == base["证据版本"]),
            None,
        )
        if evidence is None or evidence.get("status") != "有效":
            reason = (evidence or {}).get("失效原因", "证据版本已撤回")
            base["资格状态"] = WAITING
            base["失效原因"] = reason
            base["可提交结论"] = False
            base["等待说明"] = f"证据版本 {base['证据版本']} 已撤回，等待复核员重新确认：{reason}"
            return base

        # 5) 正常取得资格
        base["资格状态"] = QUALIFIED
        base["可提交结论"] = True
        base["等待说明"] = "已取得有效资格，可提交复核结论"
        return base

    def _claim_summary(
        self, order_no: str, qualified: int, waiting: int, unqualified: int
    ) -> str:
        parts = [f"认领单 {order_no} 已生成"]
        parts.append(f"可办理 {qualified} 条")
        if waiting:
            parts.append(f"等待重确认 {waiting} 条（证据版本已撤回）")
        if unqualified:
            parts.append(f"未取得资格 {unqualified} 条")
        return "，".join(parts)

    # ---------- 认领单查询 ----------

    def list_claim_orders(self, reviewer: str | None = None) -> dict[str, Any]:
        rows = store.rows("claim_order")
        if reviewer:
            rows = [o for o in rows if o.get("复核员") == reviewer]
        return {
            "ok": True,
            "message": "认领单已输出",
            "items": rows,
            "total": len(rows),
        }

    def get_claim_order(self, order_id: int) -> dict[str, Any] | None:
        return store.find("claim_order", order_id)

    # ---------- 重确认 ----------

    def reconfirm_item(self, order_id: int, review_id: int) -> dict[str, Any]:
        """对等待重确认的条目重新确认证据版本。

        旧证据已撤回且没有同匹配的有效新版本可直接接续时，条目转为未取得资格，
        给出失效原因，不能写回；复核员需改认领替换后的组合装候选（R2）。
        """
        order = store.find("claim_order", order_id)
        if order is None:
            return {"ok": False, "message": f"认领单 {order_id} 不存在"}
        item = next((it for it in order["items"] if int(it["review_id"]) == review_id), None)
        if item is None:
            return {"ok": False, "message": f"认领单内没有匹配清单记录 {review_id}"}
        if item["资格状态"] == QUALIFIED:
            return {"ok": False, "message": "该条目已取得有效资格，无需重确认"}

        evidence = next(
            (e for e in store.rows("candidate_evidence")
             if e.get("证据版本") == item["证据版本"]),
            None,
        )
        # 旧证据确认已撤回：本次认领的旧版本失效，资格不予恢复
        if evidence is None or evidence.get("status") != "有效":
            reason = (evidence or {}).get("失效原因", "证据版本已撤回")
            item["资格状态"] = UNQUALIFIED
            item["可提交结论"] = False
            item["等待说明"] = f"重新确认未通过：{reason}；请改认领替换后的候选 {evidence.get('替换为', '')}".strip()
            item["失效原因"] = reason
            review = store.find("match_review", review_id)
            if review is not None:
                review["认领资格"] = UNQUALIFIED
            order["waiting_count"] = max(0, order.get("waiting_count", 1) - 1)
            order["unqualified_count"] = order.get("unqualified_count", 0) + 1
            return {
                "ok": False,
                "message": item["等待说明"],
                "withdrawn": True,
                "withdraw_reason": reason,
                "item": item,
            }

        # 证据仍有效：恢复资格
        item["资格状态"] = QUALIFIED
        item["可提交结论"] = True
        item["等待说明"] = "重新确认通过，已恢复有效资格"
        review = store.find("match_review", review_id)
        if review is not None:
            review["认领资格"] = QUALIFIED
        return {"ok": True, "message": "重新确认通过，条目恢复有效资格", "item": item}

    # ---------- 提交结论 ----------

    def submit_conclusion(
        self,
        order_id: int,
        review_id: int,
        *,
        approved: bool,
        conclusion: str,
        reviewer: str,
    ) -> dict[str, Any]:
        """从认领单提交复核结论，只接受取得有效资格的条目，并回填这条可对账匹配。"""
        order = store.find("claim_order", order_id)
        if order is None:
            return {"ok": False, "message": f"认领单 {order_id} 不存在"}
        item = next((it for it in order["items"] if int(it["review_id"]) == review_id), None)
        if item is None:
            return {"ok": False, "message": f"认领单 {order['认领单号']} 内没有该匹配条目"}

        # 资格闸门：等待重确认 / 未取得资格的请求不得写回
        if item["资格状态"] != QUALIFIED:
            return {
                "ok": False,
                "message": f"条目未取得有效资格（当前：{item['资格状态']}），不能提交结论；{item.get('等待说明', '')}",
                "blocked": True,
                "qualification": item["资格状态"],
            }
        if reviewer and reviewer != order.get("复核员"):
            return {"ok": False, "message": "只有发起认领的复核员可以提交结论"}

        review = store.find("match_review", review_id)
        if review is None:
            return {"ok": False, "message": "复核队列匹配清单记录不存在"}
        if review.get("status") != "待复核":
            return {"ok": False, "message": f"匹配已确认（{review.get('status')}），不能重复提交"}

        # 二次确认证据版本仍有效，避免撤回后写回
        evidence = next(
            (e for e in store.rows("candidate_evidence")
             if e.get("证据版本") == item["证据版本"]),
            None,
        )
        if evidence is None or evidence.get("status") != "有效":
            item["资格状态"] = WAITING
            item["可提交结论"] = False
            item["失效原因"] = (evidence or {}).get("失效原因", "证据版本已撤回")
            return {
                "ok": False,
                "message": f"证据版本 {item['证据版本']} 已撤回，结论被拦截，请先重确认",
                "blocked": True,
            }

        # 交给规格匹配器：只回填这条可对账的匹配结果（匹配记录 id + 证据版本）
        match_id = int(item["匹配记录"])
        result = self.sku_service.backfill_reviewed_match(
            match_id,
            approved=approved,
            evidence_version=item["证据版本"],
            claim_order_no=order["认领单号"],
        )
        if not result.get("ok"):
            return {"ok": False, "message": result.get("message", "规格匹配器回填失败"), "blocked": True}

        # 回写复核队列
        review["status"] = "已通过" if approved else "已驳回"
        review["pending"] = False
        review["复核角色"] = order.get("复核角色", "")
        review["复核时间"] = _now()
        review["复核结论"] = conclusion or review.get("复核结论", "")
        review["认领资格"] = QUALIFIED

        item["结论"] = conclusion
        item["可提交结论"] = False
        item["写回状态"] = "已写回规格匹配器"
        if all(not it.get("可提交结论") for it in order["items"]):
            order["status"] = "已办结"
            order["pending"] = False

        return {
            "ok": True,
            "message": f"结论已提交并由规格匹配器回填匹配记录 {match_id}",
            "backfilled_match_id": match_id,
            "evidence_version": item["证据版本"],
            "claim_order_no": order["认领单号"],
            "approved": approved,
            "item": item,
        }

    # ---------- 剧本复位 ----------

    def reset_scenario(self) -> dict[str, Any]:
        """把剧本相关表复位到初始快照，供端到端复做。"""
        from app.scenario_seed import build_scenario_tables

        snapshot = build_scenario_tables()
        store.reset_tables(snapshot)
        return {"ok": True, "message": "认领闭环剧本已复位", "tables": sorted(snapshot)}


review_workbench = ReviewWorkbenchService()
