<script setup lang="ts">
import { computed, ref } from 'vue'

import { createAgentRun, reviseAgentRun } from '../../api/agent'
import type { AgentRun, MenuOption } from '../../types/agent'

defineOptions({ name: 'AgentPlannerView' })

const prompt = ref('明天午餐 120 人，预算 900 元，清淡，优先消耗临期番茄，不能含花生')
const run = ref<AgentRun | null>(null)
const loading = ref(false)
const error = ref('')
const selectedStrategy = ref('')

// 方案排序与筛选：可实现（无采购缺口）的方案始终排在前面
type SortMode = 'score' | 'price' | 'expiring'
const sortMode = ref<SortMode>('score')
const onlyRealizable = ref(false)
const onlyWithinBudget = ref(false)

const budgetCents = computed(() => run.value?.constraints.budget_limit_cents ?? null)

function isRealizable(option: MenuOption): boolean {
  return option.procurement_list.length === 0
}

function isWithinBudget(option: MenuOption): boolean {
  return budgetCents.value == null || option.estimated_cost_cents <= budgetCents.value
}

const displayOptions = computed<MenuOption[]>(() => {
  const source = run.value?.options ?? []
  const filtered = source.filter(
    (option) =>
      (!onlyRealizable.value || isRealizable(option)) &&
      (!onlyWithinBudget.value || isWithinBudget(option)),
  )
  const scoreOf = (option: MenuOption) => option.score_breakdown?.total ?? 0
  const expiringOf = (option: MenuOption) => option.score_breakdown?.expiring ?? 0
  const compare = (a: MenuOption, b: MenuOption): number => {
    if (sortMode.value === 'price') return a.estimated_cost_cents - b.estimated_cost_cents
    if (sortMode.value === 'expiring') return expiringOf(b) - expiringOf(a)
    return scoreOf(b) - scoreOf(a)
  }
  return [...filtered].sort((a, b) => {
    const realizableGap = (isRealizable(a) ? 0 : 1) - (isRealizable(b) ? 0 : 1)
    return realizableGap !== 0 ? realizableGap : compare(a, b)
  })
})

function missingNames(option: MenuOption): string[] {
  return option.procurement_list.map((row) => String(row.ingredient ?? ''))
}

const constraints = computed(() => {
  if (!run.value) return []
  const value = run.value.constraints
  return [
    `${value.expected_diners ?? '待确认'} 人`,
    value.budget_limit_cents ? `预算 ¥${value.budget_limit_cents / 100}` : '预算待确认',
    ...value.dietary_style,
    ...value.excluded_ingredients.map((item) => `禁用 ${item}`),
    ...(value.prioritize_expiring ? ['优先临期'] : []),
  ]
})

async function startPlanning() {
  loading.value = true
  error.value = ''
  selectedStrategy.value = ''
  try {
    run.value = await createAgentRun(prompt.value)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Agent 运行失败'
  } finally {
    loading.value = false
  }
}

async function replan(expectedDiners: number) {
  if (!run.value) return
  loading.value = true
  error.value = ''
  try {
    run.value = await reviseAgentRun(run.value.id, expectedDiners)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重规划失败'
  } finally {
    loading.value = false
  }
}

function money(cents: number) {
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(cents / 100)
}

function choose(option: MenuOption) {
  selectedStrategy.value = option.strategy
}

interface ProcurementRow {
  ingredient: string
  required: string
  available: string
  missing_quantity: string
  unit: string
}

function procurementRows(option: MenuOption): ProcurementRow[] {
  return option.procurement_list.map((row) => ({
    ingredient: String(row.ingredient ?? ''),
    required: String(row.required ?? ''),
    available: String(row.available ?? ''),
    missing_quantity: String(row.missing_quantity ?? ''),
    unit: String(row.unit ?? ''),
  }))
}

function exportCsv(option: MenuOption) {
  const header = ['食材', '需求量', '当前库存', '缺口', '单位']
  const rows = procurementRows(option).map((row) => [
    row.ingredient,
    row.required,
    row.available,
    row.missing_quantity,
    row.unit,
  ])
  const table = [header, ...rows]
  const csv =
    '\uFEFF' +
    table.map((cells) => cells.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `采购清单_${option.title}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="agent-page">
    <article class="agent-command panel">
      <div class="eyebrow">OPERATIONS AGENT</div>
      <h2>告诉 Agent 这次食堂运营目标</h2>
      <p class="muted">模型负责理解与编排，库存、成本、热量和采购缺口由确定性工具计算。</p>
      <textarea v-model="prompt" rows="3" aria-label="Agent 任务"></textarea>
      <div class="command-actions">
        <button class="primary-button" :disabled="loading || prompt.length < 2" @click="startPlanning">
          {{ loading ? 'Agent 执行中…' : '生成三套决策方案' }}
        </button>
        <button class="ghost-button" :disabled="!run || loading" @click="replan(150)">
          What-if：人数改为 150
        </button>
      </div>
      <p v-if="error" class="error-message">{{ error }}</p>
    </article>

    <template v-if="run">
      <div class="run-summary">
        <div>
          <small>运行状态</small>
          <strong>{{ run.status }}</strong>
        </div>
        <div>
          <small>Agent Run</small>
          <span>{{ run.id.slice(0, 8) }}</span>
        </div>
        <div>
          <small>审批状态</small>
          <span>{{ run.approval_status }}</span>
        </div>
      </div>

      <article class="panel">
        <div class="panel-heading compact">
          <div>
            <small>01 · UNDERSTAND</small>
            <h2>结构化约束</h2>
          </div>
        </div>
        <div class="chip-row">
          <span v-for="item in constraints" :key="item" class="constraint-chip">{{ item }}</span>
          <span
            v-for="item in run.workspace_restrictions"
            :key="item"
            class="constraint-chip restriction-chip"
            title="来自食堂档案的用餐限制，硬过滤，与本次输入无关"
          >
            食堂档案 · {{ item }}
          </span>
        </div>
        <p class="muted restriction-note">
          「过敏原 / 忌口」是食堂档案里预置的用餐限制（数据字典规定 allergy 与 dislike 均为硬过滤），
          不是本次输入的内容，所以即使你没提花生和香菜，相关菜品也会被排除。
        </p>
      </article>

      <article class="panel">
        <div class="panel-heading compact">
          <div>
            <small>02 · ACT</small>
            <h2>真实工具轨迹</h2>
          </div>
          <span class="trace-count">{{ run.tool_trace.length }} 个节点</span>
        </div>
        <ol class="trace-list">
          <li v-for="(trace, index) in run.tool_trace" :key="`${trace.tool_name}-${index}`">
            <span class="trace-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <div>
              <strong>{{ trace.tool_name }}</strong>
              <p>{{ trace.output_summary }}</p>
            </div>
            <span class="trace-time">{{ trace.duration_ms }}ms</span>
          </li>
        </ol>
      </article>

      <div class="section-title">
        <div>
          <small>03 · DECIDE</small>
          <h2>三种决策取舍</h2>
        </div>
        <span>可直接制作的方案排在前面，缺食材的往后放</span>
      </div>
      <div class="option-toolbar">
        <div class="toolbar-row">
          <span class="toolbar-label">排序</span>
          <button :class="{ active: sortMode === 'score' }" @click="sortMode = 'score'">最优组合</button>
          <button :class="{ active: sortMode === 'price' }" @click="sortMode = 'price'">价格从低到高</button>
          <button :class="{ active: sortMode === 'expiring' }" @click="sortMode = 'expiring'">临期食材优先</button>
        </div>
        <div class="toolbar-row">
          <span class="toolbar-label">筛选</span>
          <label class="filter-toggle">
            <input v-model="onlyRealizable" type="checkbox" /> 仅看库存可做
          </label>
          <label class="filter-toggle" :class="{ disabled: budgetCents == null }">
            <input
              v-model="onlyWithinBudget"
              type="checkbox"
              :disabled="budgetCents == null"
            />
            仅看低于预算{{ budgetCents == null ? '（本次未解析到预算）' : '' }}
          </label>
        </div>
      </div>
      <p v-if="!displayOptions.length" class="empty-filter-hint">
        没有符合筛选条件的方案，试着取消“仅看”勾选。
      </p>
      <div class="option-grid">
        <article
          v-for="option in displayOptions"
          :key="option.strategy"
          class="option-card"
          :class="{ selected: selectedStrategy === option.strategy, 'has-gap': !isRealizable(option) }"
        >
          <div class="option-topline">
            <h3>{{ option.title }}</h3>
            <strong :class="{ 'over-budget': !isWithinBudget(option) }">{{ money(option.estimated_cost_cents) }}</strong>
          </div>
          <div class="option-badges">
            <span :class="isRealizable(option) ? 'badge badge-ok' : 'badge badge-gap'">
              {{ isRealizable(option) ? '✓ 库存可全量制作' : `⚠ 缺 ${option.procurement_list.length} 项食材` }}
            </span>
            <span v-if="budgetCents != null" :class="isWithinBudget(option) ? 'badge badge-ok' : 'badge badge-over'">
              {{ isWithinBudget(option) ? '预算内' : '超预算' }}
            </span>
          </div>
          <p v-if="!isRealizable(option)" class="missing-list">
            缺少食材：<span v-for="name in missingNames(option)" :key="name" class="missing-item">{{ name }}</span>
          </p>
          <p class="kcal">约 {{ option.estimated_kcal_per_serving }} kcal / 人</p>
          <ul class="dish-list">
            <li v-for="dish in option.items" :key="dish.name">
              <span>{{ dish.name }}</span><small>{{ dish.servings }} 份</small>
            </li>
          </ul>
          <div v-if="procurementRows(option).length" class="procurement-block">
            <details>
              <summary>采购明细（{{ procurementRows(option).length }} 项缺口）</summary>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th>食材</th><th>需求量</th><th>当前库存</th><th>缺口</th><th>单位</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in procurementRows(option)" :key="row.ingredient" class="missing-row">
                      <td>{{ row.ingredient }}</td>
                      <td>{{ row.required }}</td>
                      <td>{{ row.available }}</td>
                      <td><strong>{{ row.missing_quantity }}</strong></td>
                      <td>{{ row.unit }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
            <button class="ghost-button" @click="exportCsv(option)">导出采购清单 CSV</button>
          </div>
          <div class="reason-list">
            <span v-for="reason in option.reasons" :key="reason">{{ reason }}</span>
          </div>
          <p v-for="warning in option.warnings" :key="warning" class="warning-text">{{ warning }}</p>
          <button class="select-button" @click="choose(option)">
            {{ selectedStrategy === option.strategy ? '已选择，等待确认' : '选择此方案' }}
          </button>
        </article>
      </div>

      <article v-if="selectedStrategy" class="approval-bar">
        <div>
          <small>04 · HUMAN IN THE LOOP</small>
          <strong>Agent 已暂停，等待管理员确认发布</strong>
        </div>
        <button class="primary-button">确认并发布菜单</button>
      </article>
    </template>

    <article v-else class="empty-agent-state">
      <strong>Agent 尚未开始</strong>
      <p>运行后将在这里展示约束、工具轨迹、三方案与人工确认节点。</p>
    </article>
  </section>
</template>

<style scoped>
.option-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin-bottom: 0.85rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid rgba(15, 76, 69, 0.15);
  border-radius: 10px;
  background: rgba(15, 76, 69, 0.03);
}
.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.5rem;
}
.toolbar-label {
  flex: 0 0 auto;
  width: 2.4em;
  font-size: 0.78rem;
  color: rgba(15, 76, 69, 0.65);
}
.toolbar-row button {
  border: 1px solid rgba(15, 76, 69, 0.3);
  background: #fff;
  color: #0f4c45;
  border-radius: 999px;
  padding: 0.18rem 0.7rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.toolbar-row button.active {
  background: #0f4c45;
  color: #fff;
  border-color: #0f4c45;
}
.filter-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.82rem;
  color: #0f4c45;
  cursor: pointer;
}
.filter-toggle.disabled {
  color: rgba(15, 76, 69, 0.45);
  cursor: not-allowed;
}
.restriction-chip {
  background: #fff7e6;
  border: 1px dashed rgba(191, 122, 22, 0.55);
  color: #8a5a00;
}
.restriction-note {
  font-size: 0.78rem;
  margin-top: 0.5rem;
}
.empty-filter-hint {
  color: rgba(15, 76, 69, 0.7);
  font-size: 0.9rem;
  margin: 0.5rem 0;
}
.option-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.4rem 0 0.2rem;
}
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 0.18rem 0.65rem;
  font-size: 0.78rem;
  font-weight: 600;
}
.badge-ok {
  background: rgba(31, 122, 90, 0.12);
  color: #1f7a5a;
}
.badge-gap {
  background: #fdecea;
  color: #c0392b;
  border: 1px solid rgba(192, 57, 43, 0.45);
}
.badge-over {
  background: #fdecea;
  color: #c0392b;
}
.over-budget {
  color: #c0392b;
}
.missing-list {
  margin: 0.25rem 0 0;
  font-size: 0.85rem;
  color: #c0392b;
  font-weight: 600;
}
.missing-item {
  display: inline-block;
  background: #fdecea;
  border: 1px solid rgba(192, 57, 43, 0.45);
  color: #c0392b;
  border-radius: 6px;
  padding: 0.05rem 0.45rem;
  margin: 0.15rem 0.3rem 0.15rem 0;
  font-weight: 600;
}
.option-card.has-gap {
  border: 1px solid rgba(192, 57, 43, 0.35);
}
.missing-row td {
  color: #c0392b;
  background: rgba(253, 236, 234, 0.55);
}
.procurement-block {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px dashed rgba(15, 76, 69, 0.2);
}
.procurement-block summary {
  cursor: pointer;
  font-weight: 600;
  color: #c0392b;
}
.procurement-block .table-wrap table {
  width: 100%;
  font-size: 0.85rem;
}
</style>
