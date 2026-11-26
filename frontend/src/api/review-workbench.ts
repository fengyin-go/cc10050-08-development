import { request } from './client'

// 人工复核工作台：候选结果、证据版本、认领单、重确认、结论回填
export type CandidateRow = {
  review_id: number
  记录编号: string
  匹配记录: string
  候选代号: string
  商品档案: string
  归一规格: string
  匹配置信度: string
  证据版本: string
  证据原文: string
  证据状态: string
  证据失效原因: string
  认领资格: string
  认领单: string
  复核状态: string
}

export type CandidatePage = {
  ok: boolean
  message: string
  items: CandidateRow[]
  total: number
  page: number
  size: number
}

export type ClaimItem = {
  item_id: string
  review_id: number
  记录编号: string
  匹配记录: string
  证据版本: string
  归一规格: string
  复核员: string
  复核角色: string
  资格状态: string
  失效原因: string
  可提交结论: boolean
  等待说明: string
  结论: string
  写回状态: string
}

export type ClaimOrder = {
  id: number
  认领单号: string
  status: string
  pending: boolean
  abnormal: boolean
  复核员: string
  复核角色: string
  认领时间: string
  items: ClaimItem[]
  qualified_count: number
  waiting_count: number
  unqualified_count: number
}

export type EvidenceRow = {
  id: string
  status: string
  证据版本: string
  匹配记录: string
  证据原文: string
  归一规格: string
  失效原因: string
  替换为: string
}

async function asJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

export async function fetchCandidates(params: {
  evidence_version?: string
  normalized_spec?: string
  page: number
  size: number
}): Promise<CandidatePage> {
  const query = new URLSearchParams()
  if (params.evidence_version) query.set('evidence_version', params.evidence_version)
  if (params.normalized_spec) query.set('normalized_spec', params.normalized_spec)
  query.set('page', String(params.page))
  query.set('size', String(params.size))
  const response = await request(`/api/review-workbench/candidates?${query.toString()}`)
  if (!response.ok) throw new Error('候选结果读取失败')
  return asJson<CandidatePage>(response)
}

export async function fetchEvidence(): Promise<{ items: EvidenceRow[]; total: number }> {
  const response = await request('/api/review-workbench/evidence')
  if (!response.ok) throw new Error('证据版本读取失败')
  return asJson(response)
}

export async function applyCorrection(matchId?: number): Promise<Record<string, unknown>> {
  const response = await request('/api/review-workbench/evidence/correction', {
    method: 'POST',
    body: JSON.stringify(matchId ? { match_id: matchId } : {}),
  })
  return asJson(response)
}

export async function createClaim(payload: {
  review_ids: number[]
  reviewer: string
  role: string
}): Promise<{ ok: boolean; message: string; claim_order: ClaimOrder }> {
  const response = await request('/api/review-workbench/claims', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return asJson(response)
}

export async function fetchClaimOrders(): Promise<{ items: ClaimOrder[]; total: number }> {
  const response = await request('/api/review-workbench/claims')
  if (!response.ok) throw new Error('认领单读取失败')
  return asJson(response)
}

export async function reconfirmItem(
  orderId: number,
  reviewId: number,
): Promise<{ ok: boolean; message: string; withdraw_reason?: string }> {
  const response = await request(
    `/api/review-workbench/claims/${orderId}/items/${reviewId}/reconfirm`,
    { method: 'POST', body: JSON.stringify({}) },
  )
  return asJson(response)
}

export async function submitConclusion(
  orderId: number,
  reviewId: number,
  payload: { approved: boolean; conclusion: string; reviewer: string },
): Promise<{
  ok: boolean
  message: string
  blocked?: boolean
  backfilled_match_id?: number
  evidence_version?: string
}> {
  const response = await request(
    `/api/review-workbench/claims/${orderId}/items/${reviewId}/conclusion`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
  return asJson(response)
}

export async function resetScenario(): Promise<{ ok: boolean; message: string }> {
  const response = await request('/api/review-workbench/reset', { method: 'POST' })
  return asJson(response)
}
