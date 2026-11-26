"""人工复核工作台路由：候选结果、证据更正、认领单、重确认、结论回填、剧本复位。

注册顺序上本路由先于通用资源路由（/api/{module}），固定路径不会被动态模块抢占。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.review_schemas import ClaimPayload, ConclusionPayload, CorrectionPayload, ReconfirmPayload
from app.services.review_workbench import review_workbench
from app.store import store

router = APIRouter(prefix="/api/review-workbench", tags=["人工复核工作台"])


@router.get("/candidates")
def list_candidates(
    evidence_version: str | None = Query(default=None),
    normalized_spec: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=4, ge=1, le=200),
) -> dict[str, Any]:
    """带候选证据版本的匹配清单，支持按证据版本与候选归一规格筛选、分页。"""
    return review_workbench.list_candidates(
        evidence_version=evidence_version,
        normalized_spec=normalized_spec,
        page=page,
        size=size,
    )


@router.post("/evidence/correction")
def apply_correction(payload: CorrectionPayload) -> dict[str, Any]:
    """模拟上游证据更正：撤回旧版本（带失效原因）并追加替换候选。"""
    from app.scenario_seed import R1_MATCH_ID

    return review_workbench.apply_upstream_correction(payload.match_id or R1_MATCH_ID)


@router.post("/claims")
def create_claim(payload: ClaimPayload) -> dict[str, Any]:
    """批量认领匹配清单，生成认领单并逐条判定有效资格。"""
    return review_workbench.create_claim(
        review_ids=payload.review_ids,
        reviewer=payload.reviewer,
        role=payload.role,
    )


@router.get("/claims")
def list_claims(reviewer: str | None = Query(default=None)) -> dict[str, Any]:
    return review_workbench.list_claim_orders(reviewer)


@router.get("/claims/{order_id}")
def get_claim(order_id: int) -> dict[str, Any]:
    order = review_workbench.get_claim_order(order_id)
    if order is None:
        return {"ok": False, "message": f"认领单 {order_id} 不存在"}
    return {"ok": True, "message": "认领单已输出", "claim_order": order}


@router.post("/claims/{order_id}/items/{review_id}/reconfirm")
def reconfirm(order_id: int, review_id: int, payload: ReconfirmPayload) -> dict[str, Any]:
    return review_workbench.reconfirm_item(order_id, review_id)


@router.post("/claims/{order_id}/items/{review_id}/conclusion")
def submit_conclusion(
    order_id: int, review_id: int, payload: ConclusionPayload
) -> dict[str, Any]:
    return review_workbench.submit_conclusion(
        order_id,
        review_id,
        approved=payload.approved,
        conclusion=payload.conclusion,
        reviewer=payload.reviewer,
    )


@router.post("/reset")
def reset_scenario() -> dict[str, Any]:
    return review_workbench.reset_scenario()


@router.get("/evidence")
def list_evidence() -> dict[str, Any]:
    """输出候选证据版本全量，含撤回状态与失效原因，供页面交代版本去向。"""
    return {
        "ok": True,
        "message": "候选证据版本已输出",
        "items": store.rows("candidate_evidence"),
        "total": len(store.rows("candidate_evidence")),
    }
