"""端到端剧本复做：单瓶筛选翻页、上游更正、批量认领、提交结论、重确认与写回比对。

用 FastAPI TestClient 直接打接口，验证：
1. 按归一规格筛选 + 分页，第二页是 R1/R3，且每条带候选证据版本；
2. 上游把 R1 更正为两瓶组合装 R2，旧证据撤回并带失效原因；
3. 在第二页一次认领 R1+R3：R3 取得资格、R1 等待重确认；
4. 不处理 R1 更正提示，立刻从认领单提交 R3：R3 可办理并写回；
5. 对 R1 重确认：旧版本失效，资格不恢复，R1 不写回；
6. 重新筛选：已确认的 R3、证据失效的 R1 不进交付范围，R2 作为新候选出现；
7. 并发第二人认领同一匹配，不能取得有效资格、不能写回；
8. 规格匹配器只回填了 R3 这一条可对账匹配。
"""
from __future__ import annotations

import sys
from pathlib import Path

# -I 隔离模式下 PYTHONPATH 不生效，显式把后端根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from app.main import app
from app.scenario_seed import R1_MATCH_ID, R2_MATCH_ID, R3_MATCH_ID
from app.services.review_workbench import UNQUALIFIED, WAITING
from app.store import store

client = TestClient(app)
PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def reset() -> None:
    resp = client.post("/api/review-workbench/reset")
    assert resp.json()["ok"]


print("== 步骤0：复位剧本 ==")
reset()

print("== 步骤1：按单瓶归一规格筛选，翻到第二页定位 R1/R3 ==")
resp = client.get("/api/review-workbench/candidates", params={
    "normalized_spec": "单瓶", "page": 1, "size": 4,
})
page1 = resp.json()
check("第一页 4 条且都是单瓶", page1["total"] == 6 and len(page1["items"]) == 4, str(page1["total"]))
check("第一页每条带证据版本", all(it["证据版本"] for it in page1["items"]))

resp = client.get("/api/review-workbench/candidates", params={
    "normalized_spec": "单瓶", "page": 2, "size": 4,
})
page2 = resp.json()
codes = [it["候选代号"] for it in page2["items"]]
check("第二页正好是 R1 与 R3", codes == ["R1", "R3"], str(codes))
r1_view = next(it for it in page2["items"] if it["候选代号"] == "R1")
r3_view = next(it for it in page2["items"] if it["候选代号"] == "R3")
check("R1 携带证据版本 EV-R1-v1", r1_view["证据版本"] == "EV-R1-v1", r1_view["证据版本"])
check("R3 携带证据版本 EV-R3-v1", r3_view["证据版本"] == "EV-R3-v1", r3_view["证据版本"])
r1_review_id = r1_view["review_id"]
r3_review_id = r3_view["review_id"]

print("== 步骤2：上游把 R1 单瓶更正为两瓶组合装 ==")
resp = client.post("/api/review-workbench/evidence/correction", json={"match_id": R1_MATCH_ID})
correction = resp.json()
check("更正成功并撤回旧证据", correction["ok"] and correction["withdrawn_evidence"] == "EV-R1-v1")
check("返回旧版失效原因", "失效" in correction["withdraw_reason"] or "更正" in correction["withdraw_reason"])
check("追加替换候选 R2", correction["new_match_id"] == R2_MATCH_ID)

ev_resp = client.get("/api/review-workbench/evidence")
ev_items = ev_resp.json()["items"]
ev_map = {e["证据版本"]: e for e in ev_items}
check("旧证据 EV-R1-v1 状态为已撤回且有失效原因",
      ev_map["EV-R1-v1"]["status"] == "已撤回" and bool(ev_map["EV-R1-v1"]["失效原因"]))
check("新证据 EV-R2-v1 有效且归一规格为两瓶组合装",
      ev_map["EV-R2-v1"]["status"] == "有效" and ev_map["EV-R2-v1"]["归一规格"] == "两瓶组合装 500ml")

print("== 步骤3：复核员在第二页一次批量认领 R1 + R3 ==")
resp = client.post("/api/review-workbench/claims", json={
    "review_ids": [r1_review_id, r3_review_id],
    "reviewer": "复核员甲",
    "role": "规格审核员",
})
claim = resp.json()
check("认领单已生成", claim["ok"])
order = claim["claim_order"]
order_id = order["id"]
item_by_review = {int(it["review_id"]): it for it in order["items"]}
check("R3 取得有效资格、可提交结论",
      item_by_review[r3_review_id]["资格状态"] == "已取得资格"
      and item_by_review[r3_review_id]["可提交结论"] is True)
check("R1 等待重确认且带失效原因",
      item_by_review[r1_review_id]["资格状态"] == "等待重确认"
      and bool(item_by_review[r1_review_id]["失效原因"]))
check("认领单汇总 1 可办理 / 1 等待",
      order["qualified_count"] == 1 and order["waiting_count"] == 1)

print("== 步骤4：先不处理 R1 更正提示，立刻从认领单提交 R3 ==")
resp = client.post(f"/api/review-workbench/claims/{order_id}/items/{r3_review_id}/conclusion", json={
    "approved": True,
    "conclusion": "R3 单瓶规格核对无误，通过",
    "reviewer": "复核员甲",
})
r3_result = resp.json()
check("R3 结论提交成功", r3_result["ok"], r3_result.get("message", ""))
check("R3 回填到可对账匹配记录", r3_result.get("backfilled_match_id") == R3_MATCH_ID)
check("R3 回填锁定证据版本 EV-R3-v1", r3_result.get("evidence_version") == "EV-R3-v1")

# 立刻尝试提交 R1（仍在等待重确认），应被拦截
resp = client.post(f"/api/review-workbench/claims/{order_id}/items/{r1_review_id}/conclusion", json={
    "approved": True,
    "conclusion": "R1 旧版本结论",
    "reviewer": "复核员甲",
})
r1_blocked = resp.json()
check("R1 在等待重确认时提交被拦截", not r1_blocked["ok"] and r1_blocked.get("blocked"))
check("拦截信息交代在等什么（重确认/撤回）",
      "重确认" in r1_blocked["message"] or "撤回" in r1_blocked["message"])

print("== 步骤5：对 R1 重新确认 ==")
resp = client.post(f"/api/review-workbench/claims/{order_id}/items/{r1_review_id}/reconfirm", json={})
reconfirm = resp.json()
check("R1 重确认未通过（旧版已撤回）", not reconfirm["ok"] and reconfirm.get("withdrawn"))
check("重确认返回失效原因", bool(reconfirm.get("withdraw_reason")))
order_now = client.get(f"/api/review-workbench/claims/{order_id}").json()["claim_order"]
r1_item = next(it for it in order_now["items"] if int(it["review_id"]) == r1_review_id)
check("R1 重确认后转为未取得资格", r1_item["资格状态"] == "未取得资格")

# 再尝试提交 R1，仍应被拦截
resp = client.post(f"/api/review-workbench/claims/{order_id}/items/{r1_review_id}/conclusion", json={
    "approved": True, "conclusion": "R1 再次尝试", "reviewer": "复核员甲",
})
check("R1 未取得资格仍不能写回", not resp.json()["ok"])

print("== 步骤6：重新获取筛选结果，核对交付范围 ==")
resp = client.get("/api/review-workbench/candidates", params={
    "normalized_spec": "单瓶", "page": 1, "size": 10,
})
re_list = resp.json()
re_codes = [it["候选代号"] for it in re_list["items"]]
check("已确认的 R3 不再进入候选交付范围", "R3" not in re_codes, str(re_codes))
check("证据失效的 R1 不再进入候选交付范围", "R1" not in re_codes, str(re_codes))
check("剩余 4 条单瓶候选（R4-R7）", re_list["total"] == 4, str(re_list["total"]))

resp = client.get("/api/review-workbench/candidates", params={
    "normalized_spec": "两瓶组合装", "page": 1, "size": 10,
})
combo = resp.json()
check("按两瓶组合装能筛出替换后的 R2",
      combo["total"] == 1 and combo["items"][0]["候选代号"] == "R2")

# 规格不匹配的条件不应塞入条目
resp = client.get("/api/review-workbench/candidates", params={
    "normalized_spec": "不存在的规格XYZ", "page": 1, "size": 10,
})
check("不匹配规格的筛选返回空交付范围", resp.json()["total"] == 0)

print("== 步骤7：并发第二人认领同一匹配，不能取得有效资格 ==")
# R3 已确认，R1 已被甲的认领单占用但资格为未取得资格；用一条仍待复核的 R4 测试竞争
r4 = client.get("/api/review-workbench/candidates", params={"page": 1, "size": 10}).json()["items"]
r4_review_id = next(it["review_id"] for it in r4 if it["候选代号"] == "R4")
first = client.post("/api/review-workbench/claims", json={
    "review_ids": [r4_review_id], "reviewer": "复核员乙", "role": "规格审核员",
}).json()
check("乙先认领 R4 取得资格", first["claim_order"]["items"][0]["资格状态"] == "已取得资格")
second = client.post("/api/review-workbench/claims", json={
    "review_ids": [r4_review_id], "reviewer": "复核员丙", "role": "商品运营",
}).json()
check("丙再认领 R4 未取得资格", second["claim_order"]["items"][0]["资格状态"] == "未取得资格")
# 丙尝试提交结论
second_order_id = second["claim_order"]["id"]
resp = client.post(
    f"/api/review-workbench/claims/{second_order_id}/items/{r4_review_id}/conclusion",
    json={"approved": True, "conclusion": "丙抢办", "reviewer": "复核员丙"},
)
check("丙的请求不能写回规格匹配器", not resp.json()["ok"])

# 无效应角色
bad_role = client.post("/api/review-workbench/claims", json={
    "review_ids": [r4_review_id], "reviewer": "实习生", "role": "访客",
}).json()
check("无复核资格角色不能取得资格", bad_role["claim_order"]["items"][0]["资格状态"] == "未取得资格")

print("== 步骤7b：等待重确认的匹配不能被第二张认领单接管 ==")
# 复位后制造 R1 等待重确认，再由另一复核员尝试认领 R1
reset()
client.post("/api/review-workbench/evidence/correction", json={"match_id": R1_MATCH_ID})
first_r1 = client.post("/api/review-workbench/claims", json={
    "review_ids": [R1_MATCH_ID], "reviewer": "复核员甲", "role": "规格审核员",
}).json()
check("甲认领已撤回的 R1 进入等待重确认",
      first_r1["claim_order"]["items"][0]["资格状态"] == WAITING)
grab_r1 = client.post("/api/review-workbench/claims", json={
    "review_ids": [R1_MATCH_ID], "reviewer": "复核员乙", "role": "商品运营",
}).json()
check("乙不能接管处于等待重确认的 R1",
      grab_r1["claim_order"]["items"][0]["资格状态"] == UNQUALIFIED)
# 复位回主剧本状态，避免影响后续步骤8
reset()
client.post("/api/review-workbench/evidence/correction", json={"match_id": R1_MATCH_ID})
main_order = client.post("/api/review-workbench/claims", json={
    "review_ids": [R1_MATCH_ID, R3_MATCH_ID], "reviewer": "复核员甲", "role": "规格审核员",
}).json()["claim_order"]
client.post(
    f"/api/review-workbench/claims/{main_order['id']}/items/{R3_MATCH_ID}/conclusion",
    json={"approved": True, "conclusion": "R3通过", "reviewer": "复核员甲"},
)
order_now = main_order

print("== 步骤7c：通用资源路由的通过/驳回同样受认领资格闸门约束 ==")
reset()
# 未认领直接打通用动作接口，应被拦截
r5_review = client.get("/api/review-workbench/candidates", params={"page": 1, "size": 10}).json()["items"]
r5_id = next(it["review_id"] for it in r5_review if it["候选代号"] == "R5")
blocked_generic = client.post(f"/api/match_review/{r5_id}/actions", json={"action": "通过记录"}).json()
check("未认领时通用通过动作被拦截", not blocked_generic["ok"])
# 走认领取得资格后，通用动作可以办理且同样对账回填
g_order = client.post("/api/review-workbench/claims", json={
    "review_ids": [r5_id], "reviewer": "复核员乙", "role": "数据治理专员",
}).json()["claim_order"]
ok_generic = client.post(f"/api/match_review/{r5_id}/actions", json={"action": "通过记录"}).json()
check("取得资格后通用通过动作成功", ok_generic["ok"], ok_generic.get("message", ""))
r5_match = store.find("sku_match", 102)
check("通用动作回填也锁定认领单与证据版本",
      r5_match["status"] == "已匹配" and r5_match["回填认领单"] == g_order["认领单号"])

print("== 步骤8：比对规格匹配器实际写回了哪条 ==")
from app.store import store
# 重建主剧本状态做最终写回比对
reset()
client.post("/api/review-workbench/evidence/correction", json={"match_id": R1_MATCH_ID})
final_order = client.post("/api/review-workbench/claims", json={
    "review_ids": [R1_MATCH_ID, R3_MATCH_ID], "reviewer": "复核员甲", "role": "规格审核员",
}).json()["claim_order"]
client.post(
    f"/api/review-workbench/claims/{final_order['id']}/items/{R3_MATCH_ID}/conclusion",
    json={"approved": True, "conclusion": "R3通过", "reviewer": "复核员甲"},
)
order_now = final_order
sku_rows = store.rows("sku_match")
backfilled = [m for m in sku_rows if m.get("回填认领单")]
backfilled_ids = sorted(m["id"] for m in backfilled)
check("只有 R3 一条匹配被实际写回", backfilled_ids == [R3_MATCH_ID], str(backfilled_ids))
r3_match = next(m for m in sku_rows if m["id"] == R3_MATCH_ID)
check("R3 匹配状态为已匹配并记录认领单/证据版本",
      r3_match["status"] == "已匹配"
      and r3_match["回填认领单"] == order_now["认领单号"]
      and r3_match["证据版本"] == "EV-R3-v1")
r1_match = next(m for m in sku_rows if m["id"] == R1_MATCH_ID)
check("R1 旧匹配未被写回，仍是人工复核且证据撤回标记",
      r1_match["status"] == "人工复核" and r1_match["abnormal"] is True
      and not r1_match.get("回填认领单"))
r2_match = next(m for m in sku_rows if m["id"] == R2_MATCH_ID)
check("R2 组合装作为新候选保持人工复核，未被任何结论写回",
      r2_match["status"] == "人工复核" and not r2_match.get("回填认领单"))

# 复核队列侧：只有 R3 一条已通过
review_rows = store.rows("match_review")
approved = [r for r in review_rows if r["status"] == "已通过"]
check("复核队列只有 R3 一条有效结论", len(approved) == 1 and str(approved[0]["匹配记录"]) == str(R3_MATCH_ID))

print(f"\n结果：通过 {PASS} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)
