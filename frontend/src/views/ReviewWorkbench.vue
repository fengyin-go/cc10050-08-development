<template>
  <section class="page review-workbench" data-testid="review-workbench">
    <header class="page-head">
      <div>
        <h2>人工复核认领工作台</h2>
        <p class="page-desc">
          按证据版本与候选归一规格筛选待复核匹配，批量认领生成认领单；只有取得有效资格的条目才能提交结论并由规格匹配器回填。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="simulate-correction" type="button" @click="onCorrect">
          模拟上游更正 R1（单瓶→两瓶组合装）
        </button>
        <button class="btn ghost" data-testid="reset-scenario" type="button" @click="onReset">
          复位剧本
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">候选总数（当前筛选）</span>
        <strong class="stat-value">{{ candidatePage.total }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">本页已选</span>
        <strong class="stat-value">{{ selectedIds.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">认领单数</span>
        <strong class="stat-value">{{ claimOrders.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已撤回证据版本</span>
        <strong class="stat-value">{{ withdrawnCount }}</strong>
      </article>
    </div>

    <p v-if="notice" class="notice-text" :data-testid="'notice'" :class="noticeKind">{{ notice }}</p>

    <!-- 筛选条件 -->
    <form class="filter-bar" @submit.prevent="reloadCandidates(1)">
      <label class="filter-item">
        <span>候选归一规格</span>
        <input
          v-model="filters.normalized_spec"
          data-testid="filter-spec"
          placeholder="如：单瓶 / 两瓶组合装"
        />
      </label>
      <label class="filter-item">
        <span>证据版本</span>
        <input
          v-model="filters.evidence_version"
          data-testid="filter-evidence"
          placeholder="如：EV-R1-v1"
        />
      </label>
      <button class="btn primary" data-testid="query-candidates" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 认领人信息 -->
    <div class="claim-bar">
      <label class="filter-item">
        <span>复核员</span>
        <input v-model="reviewer" data-testid="claim-reviewer" placeholder="复核员姓名" />
      </label>
      <label class="filter-item">
        <span>复核角色</span>
        <select v-model="role" data-testid="claim-role">
          <option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
        </select>
      </label>
      <button
        class="btn primary"
        data-testid="batch-claim"
        type="button"
        :disabled="!selectedIds.length"
        @click="onClaim"
      >
        批量认领选中 {{ selectedIds.length }} 条
      </button>
    </div>

    <!-- 候选结果表 -->
    <table class="data-table candidate-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>候选代号</th>
          <th>记录编号</th>
          <th>匹配记录</th>
          <th>商品档案</th>
          <th>候选归一规格</th>
          <th>置信度</th>
          <th>候选证据版本</th>
          <th>证据状态</th>
          <th>认领情况</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in candidatePage.items"
          :key="row.review_id"
          :data-testid="`candidate-row-${row.候选代号}`"
          :data-status="row.证据状态"
        >
          <td>
            <input
              v-model="selectedIds"
              type="checkbox"
              :value="row.review_id"
              :data-testid="`check-${row.候选代号}`"
            />
          </td>
          <td>{{ row.候选代号 }}</td>
          <td>{{ row.记录编号 }}</td>
          <td>{{ row.匹配记录 }}</td>
          <td>{{ row.商品档案 }}</td>
          <td>{{ row.归一规格 }}</td>
          <td>{{ row.匹配置信度 }}</td>
          <td>
            <div>{{ row.证据版本 }}</div>
            <div class="muted-text">{{ row.证据原文 }}</div>
          </td>
          <td>
            <span :class="['status-tag', row.证据状态 === '有效' ? 'ok' : 'bad']">
              {{ row.证据状态 }}
            </span>
            <div v-if="row.证据失效原因" class="reason-text">{{ row.证据失效原因 }}</div>
          </td>
          <td>
            <span v-if="row.认领资格" :class="['status-tag', qualificationClass(row.认领资格)]">
              {{ row.认领资格 }}
            </span>
            <span v-else class="muted-text">未认领</span>
            <div v-if="row.认领单" class="muted-text">单据：{{ row.认领单 }}</div>
          </td>
        </tr>
        <tr v-if="!candidatePage.items.length">
          <td colspan="10" class="empty-state">
            当前筛选没有可交付的待复核候选（不匹配规格或已确认/证据失效的条目不进入交付范围）
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 分页 -->
    <div class="pager">
      <button
        class="btn"
        data-testid="prev-page"
        type="button"
        :disabled="candidatePage.page <= 1"
        @click="reloadCandidates(candidatePage.page - 1)"
      >
        上一页
      </button>
      <span data-testid="page-indicator">
        第 {{ candidatePage.page }} 页 / 共 {{ totalPages }} 页（每页 {{ candidatePage.size }} 条）
      </span>
      <button
        class="btn"
        data-testid="next-page"
        type="button"
        :disabled="candidatePage.page >= totalPages"
        @click="reloadCandidates(candidatePage.page + 1)"
      >
        下一页
      </button>
    </div>

    <!-- 认领单 -->
    <section class="claim-panel">
      <h3>我的认领单（翻页后仍可在此辨认实际领到的证据版本）</h3>
      <div v-if="!claimOrders.length" class="muted-text">暂无认领单</div>
      <article
        v-for="order in claimOrders"
        :key="order.id"
        class="order-card"
        :data-testid="`claim-order-${order.认领单号}`"
      >
        <header class="order-head">
          <strong>{{ order.认领单号 }}</strong>
          <span class="muted-text">
            {{ order.复核员 }}（{{ order.复核角色 }}）｜{{ order.认领时间 }}
          </span>
          <span :class="['status-tag', order.status === '已办结' ? 'ok' : 'pending']">
            {{ order.status }}
          </span>
          <span class="muted-text">
            可办理 {{ order.qualified_count }} ｜ 等待重确认 {{ order.waiting_count }} ｜
            未取得资格 {{ order.unqualified_count }}
          </span>
        </header>
        <table class="data-table">
          <thead>
            <tr>
              <th>候选</th>
              <th>匹配记录</th>
              <th>领到的证据版本</th>
              <th>归一规格</th>
              <th>资格状态</th>
              <th>等待/失效说明</th>
              <th>结论办理</th>
              <th>写回状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in order.items"
              :key="item.item_id"
              :data-testid="`order-item-${item.review_id}`"
            >
              <td>{{ item.记录编号 }}</td>
              <td>{{ item.匹配记录 }}</td>
              <td>{{ item.证据版本 }}</td>
              <td>{{ item.归一规格 }}</td>
              <td>
                <span :class="['status-tag', qualificationClass(item.资格状态)]">
                  {{ item.资格状态 }}
                </span>
              </td>
              <td class="reason-text">{{ item.等待说明 || item.失效原因 || '—' }}</td>
              <td class="row-actions">
                <button
                  v-if="item.资格状态 === '等待重确认'"
                  class="link"
                  type="button"
                  :data-testid="`reconfirm-${item.review_id}`"
                  @click="onReconfirm(order.id, item.review_id)"
                >
                  重新确认
                </button>
                <button
                  v-if="item.可提交结论"
                  class="link"
                  type="button"
                  :data-testid="`approve-${item.review_id}`"
                  @click="onConclusion(order, item, true)"
                >
                  提交通过
                </button>
                <button
                  v-if="item.可提交结论"
                  class="link danger"
                  type="button"
                  :data-testid="`reject-${item.review_id}`"
                  @click="onConclusion(order, item, false)"
                >
                  提交驳回
                </button>
                <span v-if="!item.可提交结论 && item.资格状态 !== '等待重确认'" class="muted-text">
                  不可办理
                </span>
              </td>
              <td>
                <span v-if="item.写回状态" class="status-tag ok">{{ item.写回状态 }}</span>
                <span v-else class="muted-text">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </article>
    </section>

    <!-- 证据版本台账 -->
    <section class="claim-panel">
      <h3>候选证据版本台账（旧版撤回与失效原因）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>证据版本</th>
            <th>匹配记录</th>
            <th>归一规格</th>
            <th>证据原文</th>
            <th>状态</th>
            <th>失效原因 / 替换去向</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ev in evidenceRows" :key="ev.id" :data-testid="`evidence-${ev.证据版本}`">
            <td>{{ ev.证据版本 }}</td>
            <td>{{ ev.匹配记录 }}</td>
            <td>{{ ev.归一规格 }}</td>
            <td>{{ ev.证据原文 }}</td>
            <td>
              <span :class="['status-tag', ev.status === '有效' ? 'ok' : 'bad']">
                {{ ev.status }}
              </span>
            </td>
            <td class="reason-text">
              <template v-if="ev.失效原因">{{ ev.失效原因 }}</template>
              <template v-if="ev.替换为">（替换为 {{ ev.替换为 }}）</template>
              <template v-if="!ev.失效原因 && !ev.替换为">—</template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>候选数据来自复核队列实际生成的匹配清单与候选证据版本，结论仅回填可对账匹配</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  applyCorrection,
  createClaim,
  fetchCandidates,
  fetchClaimOrders,
  fetchEvidence,
  reconfirmItem,
  resetScenario,
  submitConclusion,
  type CandidatePage,
  type ClaimItem,
  type ClaimOrder,
  type EvidenceRow,
} from '@/api/review-workbench'

const PAGE_SIZE = 4
const roles = ['规格审核员', '商品运营', '数据治理专员']

const filters = ref({ normalized_spec: '单瓶', evidence_version: '' })
const candidatePage = ref<CandidatePage>({
  ok: true,
  message: '',
  items: [],
  total: 0,
  page: 1,
  size: PAGE_SIZE,
})
const selectedIds = ref<number[]>([])
const reviewer = ref('复核员甲')
const role = ref('规格审核员')
const claimOrders = ref<ClaimOrder[]>([])
const evidenceRows = ref<EvidenceRow[]>([])
const notice = ref('')
const noticeKind = ref('info')

const totalPages = computed(() =>
  Math.max(1, Math.ceil(candidatePage.value.total / candidatePage.value.size)),
)
const withdrawnCount = computed(
  () => evidenceRows.value.filter((item) => item.status !== '有效').length,
)

function qualificationClass(status: string): string {
  if (status === '已取得资格') return 'ok'
  if (status === '等待重确认') return 'pending'
  return 'bad'
}

function setNotice(message: string, kind: 'info' | 'ok' | 'bad' = 'info') {
  notice.value = message
  noticeKind.value = kind
}

async function reloadCandidates(page = candidatePage.value.page) {
  notice.value = ''
  try {
    candidatePage.value = await fetchCandidates({
      evidence_version: filters.value.evidence_version || undefined,
      normalized_spec: filters.value.normalized_spec || undefined,
      page,
      size: PAGE_SIZE,
    })
    // 重新获取后清理已不在交付范围内的选择
    const visibleIds = new Set(candidatePage.value.items.map((item) => item.review_id))
    selectedIds.value = selectedIds.value.filter((id) => visibleIds.has(id))
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '候选结果读取失败', 'bad')
  }
}

async function reloadOrders() {
  const payload = await fetchClaimOrders()
  claimOrders.value = payload.items
}

async function reloadEvidence() {
  const payload = await fetchEvidence()
  evidenceRows.value = payload.items
}

function resetFilters() {
  filters.value = { normalized_spec: '', evidence_version: '' }
  void reloadCandidates(1)
}

async function onClaim() {
  if (!reviewer.value.trim()) {
    setNotice('请先填写复核员', 'bad')
    return
  }
  const result = await createClaim({
    review_ids: [...selectedIds.value],
    reviewer: reviewer.value.trim(),
    role: role.value,
  })
  setNotice(result.message, result.ok ? 'ok' : 'bad')
  selectedIds.value = []
  await Promise.all([reloadCandidates(), reloadOrders(), reloadEvidence()])
}

async function onCorrect() {
  const result = await applyCorrection()
  setNotice(String(result.message ?? '上游更正已完成'), result.ok ? 'info' : 'bad')
  await Promise.all([reloadCandidates(), reloadEvidence(), reloadOrders()])
}

async function onReset() {
  const result = await resetScenario()
  setNotice(result.message, 'ok')
  selectedIds.value = []
  await Promise.all([reloadCandidates(1), reloadOrders(), reloadEvidence()])
}

async function onReconfirm(orderId: number, reviewId: number) {
  const result = await reconfirmItem(orderId, reviewId)
  setNotice(result.message, result.ok ? 'ok' : 'bad')
  await Promise.all([reloadOrders(), reloadCandidates(), reloadEvidence()])
}

async function onConclusion(order: ClaimOrder, item: ClaimItem, approved: boolean) {
  const result = await submitConclusion(order.id, item.review_id, {
    approved,
    conclusion: approved
      ? `${item.记录编号} 规格核对无误，通过`
      : `${item.记录编号} 规格核对不符，驳回`,
    reviewer: order.复核员,
  })
  if (result.ok) {
    setNotice(
      `${result.message}；实际写回匹配 ${result.backfilled_match_id}（证据版本 ${result.evidence_version}）`,
      'ok',
    )
  } else {
    setNotice(result.message, 'bad')
  }
  await Promise.all([reloadOrders(), reloadCandidates(), reloadEvidence()])
}

onMounted(async () => {
  await Promise.all([reloadCandidates(1), reloadOrders(), reloadEvidence()])
})
</script>
