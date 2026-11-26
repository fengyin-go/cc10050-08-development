"""规格匹配器领域服务：把站点SKU匹配到商品档案的归一规格，负责匹配置信度判定与人工复核分流。

数据链路位置：规格对齐层，消费规格归一器推送的候选规格与商品档案中心的主数据，
低置信度结果转人工复核队列，高置信度结果回填商品档案。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SkuMatchService(BaseModuleService):
    MODULE = "sku_match"
    ENTITY = "匹配记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["匹配批次", "商品档案", "候选规格", "匹配置信度", "匹配状态"]
    REQUIRED_FIELDS = ["匹配批次", "商品档案", "候选规格"]
    STATUS_ORDER = ["待匹配", "已匹配", "人工复核", "匹配失败"]
    ACTION_RULES = {"执行匹配": "已匹配", "转人工复核": "人工复核"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：规格匹配与置信度分流 ----

    def run_match(self, entry_id: int, confidence: float) -> dict[str, Any]:
        """执行规格匹配，按置信度分流到已匹配或人工复核。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        goods_name = entry.get("商品档案", "")
        goods = next(
            (g for g in store.rows("goods_registry") if g.get("商品标识") == goods_name), None
        )
        if goods is None:
            entry["status"] = "匹配失败"
            entry["abnormal"] = True
            return {"ok": False, "message": f"商品档案 {goods_name} 不存在"}
        if confidence >= 0.95:
            entry["status"] = "已匹配"
            entry["pending"] = False
        else:
            entry["status"] = "人工复核"
            entry["pending"] = True
        entry["匹配置信度"] = f"{confidence:.2f}"
        return {
            "ok": True,
            "message": "匹配执行完成",
            "result_status": entry.get("status"),
            "confidence": entry.get("匹配置信度"),
        }

    def escalate_review(self, entry_id: int) -> dict[str, Any]:
        """把低置信度匹配记录升级到人工复核队列。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "人工复核":
            return {"ok": False, "message": "记录不存在或不处于人工复核状态"}
        rows = store.rows("match_review")
        rid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": rid,
            "记录编号": f"SM-{entry_id}-{rid}",
            "匹配记录": str(entry.get("id", "")),
            "复核结论": f"置信度 {entry.get('匹配置信度', '')}",
            "复核角色": "规格审核员",
            "复核时间": datetime.now(timezone.utc).isoformat(),
            "status": "待复核",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": "已升级人工复核", "review_id": rid}

    def backfill_reviewed_match(
        self,
        entry_id: int,
        *,
        approved: bool,
        evidence_version: str,
        claim_order_no: str,
    ) -> dict[str, Any]:
        """回填人工复核结论：只写回这条可对账的匹配结果。

        对账条件：匹配记录存在、仍处人工复核、且当前证据版本与认领单条目锁定的
        证据版本一致。证据版本被上游替换/撤回的旧匹配不允许写回，必须走重新认领。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"匹配记录 {entry_id} 不存在，无可对账目标"}
        if entry.get("status") != "人工复核":
            return {"ok": False, "message": f"匹配记录 {entry_id} 不处于人工复核，拒绝回填"}
        if str(entry.get("证据版本", "")) != str(evidence_version):
            return {
                "ok": False,
                "message": (
                    f"证据版本不一致：认领单锁定 {evidence_version}，"
                    f"匹配记录当前为 {entry.get('证据版本', '')}，拒绝回填"
                ),
            }
        evidence = next(
            (e for e in store.rows("candidate_evidence")
             if e.get("证据版本") == evidence_version),
            None,
        )
        if evidence is None or evidence.get("status") != "有效":
            return {
                "ok": False,
                "message": f"证据版本 {evidence_version} 已撤回，规格匹配器拒绝回填",
            }
        if approved:
            entry["status"] = "已匹配"
            entry["pending"] = False
            entry["匹配状态"] = "人工复核通过并回填"
        else:
            entry["status"] = "匹配失败"
            entry["abnormal"] = True
            entry["匹配状态"] = "人工复核驳回"
            rows = store.rows("failure_quarantine")
            fid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            rows.append({
                "id": fid,
                "样本指纹": f"match-{entry_id}",
                "失败阶段": "匹配",
                "失败原因": f"人工复核驳回（认领单 {claim_order_no}）",
                "隔离时间": datetime.now(timezone.utc).isoformat(),
                "重试次数": "0",
                "status": "待处理",
                "pending": True,
                "abnormal": False,
            })
        entry["回填认领单"] = claim_order_no
        entry["回填时间"] = datetime.now(timezone.utc).isoformat()
        return {
            "ok": True,
            "message": f"匹配记录 {entry_id} 已按认领单 {claim_order_no} 回填",
            "match_id": entry_id,
            "evidence_version": evidence_version,
            "result_status": entry["status"],
        }

    def apply_review_result(self, entry_id: int, approved: bool) -> dict[str, Any]:
        """应用复核结论：通过则回填档案，驳回则进失败隔离。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "记录不存在"}
        if approved:
            entry["status"] = "已匹配"
            entry["pending"] = False
            return {"ok": True, "message": "复核通过，匹配已确认"}
        entry["status"] = "匹配失败"
        entry["abnormal"] = True
        rows = store.rows("failure_quarantine")
        fid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": fid,
            "样本指纹": f"match-{entry_id}",
            "失败阶段": "匹配",
            "失败原因": "人工复核驳回",
            "隔离时间": datetime.now(timezone.utc).isoformat(),
            "重试次数": "0",
            "status": "待处理",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": "复核驳回，样本已隔离", "quarantine_id": fid}

    def consume_normalized(self, entry_id: int) -> dict[str, Any]:
        """消费规格归一器推送的候选规格完成对齐。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "记录不存在"}
        spec = entry.get("候选规格", "")
        matched_rule = next(
            (r for r in store.rows("spec_normalizer")
             if r.get("status") == "已启用" and r.get("归一规格") == spec), None
        )
        if matched_rule is None:
            entry["status"] = "匹配失败"
            entry["abnormal"] = True
            return {"ok": False, "message": f"候选规格 {spec} 没有启用中的归一规则"}
        entry["匹配状态"] = "归一对齐"
        return {
            "ok": True,
            "message": "候选规格已对齐归一规则",
            "rule": matched_rule.get("规则名称", ""),
        }

    def link_goods_baseline(self, entry_id: int) -> dict[str, Any]:
        """检查匹配成功后商品是否具备基线价格。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已匹配":
            return {"ok": False, "message": "记录不存在或未匹配"}
        goods_name = entry.get("商品档案", "")
        has_baseline = any(
            b.get("商品标识") == goods_name and b.get("status") == "已生效"
            for b in store.rows("price_baseline")
        )
        return {
            "ok": True,
            "message": "基线关联检查完成",
            "goods": goods_name,
            "has_baseline": has_baseline,
        }

    def batch_summary(self, batch: str) -> dict[str, Any]:
        """汇总匹配批次内各状态数量并上报指标。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("匹配批次") == batch]
        if not rows:
            return {"ok": False, "message": f"批次 {batch} 不存在"}
        matched = sum(1 for r in rows if r.get("status") == "已匹配")
        review = sum(1 for r in rows if r.get("status") == "人工复核")
        return {
            "ok": True,
            "message": "批次汇总完成",
            "total": len(rows),
            "matched": matched,
            "need_review": review,
            "failed": len(rows) - matched - review,
        }
