"""复核工作台接口契约：认领闭环专用请求体，与通用资源 ActionPayload 区分。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimPayload(BaseModel):
    review_ids: list[int] = Field(default_factory=list)
    reviewer: str
    role: str


class ReconfirmPayload(BaseModel):
    reviewer: str | None = None


class ConclusionPayload(BaseModel):
    approved: bool
    conclusion: str = ""
    reviewer: str = ""


class CorrectionPayload(BaseModel):
    match_id: int | None = None
