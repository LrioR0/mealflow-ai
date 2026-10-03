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
        </div>
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
        <span>不是唯一答案，而是可解释选择</span>
      </div>
      <div class="option-grid">
        <article
          v-for="option in run.options"
          :key="option.strategy"
          class="option-card"
          :class="{ selected: selectedStrategy === option.strategy }"
        >
          <div class="option-topline">
            <h3>{{ option.title }}</h3>
            <strong>{{ money(option.estimated_cost_cents) }}</strong>
          </div>
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
                    <tr v-for="row in procurementRows(option)" :key="row.ingredient">
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
  color: #0f4c45;
}
.procurement-block .table-wrap table {
  width: 100%;
  font-size: 0.85rem;
}
</style>
