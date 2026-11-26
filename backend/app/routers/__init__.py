"""业务路由汇总：专用工作台路由先注册，通用模块资源路由兜底。"""
from __future__ import annotations

from app.routers import resource, review_workbench

# review_workbench 的固定路径必须排在通用 /api/{module} 动态路由之前
ROUTERS = [review_workbench, resource]
