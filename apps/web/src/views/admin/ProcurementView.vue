<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchIngredients, type IngredientOption } from '../../api/inventory'
import { fetchLatestAgentRun } from '../../api/procurement'
import type { AgentRun, MenuOption } from '../../types/agent'

defineOptions({ name: 'ProcurementView' })

const run = ref<AgentRun | null>(null)
const ingredients = ref<IngredientOption[]>([])
const loading = ref(true)
const error = ref('')
const notStarted = ref(false)
const selectedStrategy = ref('')

const option = computed(
  () => run.value?.options.find((item) => item.strategy === selectedStrategy.value) ?? null,
)

const categoryByName = computed(() => {
  const map = new Map<string, string>()
  for (const item of ingredients.value) map.set(item.name, item.category)
  return map
})

interface ProcurementRow {
  ingredient: string
  category: string
  required: string
  available: string
  missing: string
  unit: string
}

const rows = computed<ProcurementRow[]>(() =>
  (option.value?.procurement_list ?? []).map((row) => ({
    ingredient: String(row.ingredient ?? ''),
    category: categoryByName.value.get(String(row.ingredient ?? '')) ?? '—',
    required: String(row.required ?? ''),
    available: String(row.available ?? ''),
    missing: String(row.missing_quantity ?? ''),
    unit: String(row.unit ?? ''),
  })),
)

function score(item: MenuOption): string {
  const total = item.score_breakdown?.total
  return typeof total === 'number' ? `${total.toFixed(3)} 分` : ''
}

function money(cents: number) {
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(cents / 100)
}

async function load() {
  loading.value = true
  error.value = ''
  notStarted.value = false
  try {
    const [latest, ingredientList] = await Promise.all([fetchLatestAgentRun(), fetchIngredients()])
    run.value = latest
    ingredients.value = ingredientList
    selectedStrategy.value = latest.options[0]?.strategy ?? ''
  } catch (reason) {
    run.value = null
    if (reason instanceof Error && reason.message.includes('No agent runs yet')) {
      notStarted.value = true
    } else {
      error.value = reason instanceof Error ? reason.message : '加载采购清单失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)

function exportCsv() {
  if (!option.value) return
  const header = ['品类', '食材', '需求量', '当前库存', '缺口', '单位']
  const table = [
    header,
    ...rows.value.map((row) => [
      row.category,
      row.ingredient,
      row.required,
      row.available,
      row.missing,
      row.unit,
    ]),
  ]
  const csv =
    '\uFEFF' +
    table.map((cells) => cells.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `采购清单_${option.value.title}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <small>DETERMINISTIC RESULT</small>
        <h2>采购清单</h2>
      </div>
      <button class="ghost-button" :disabled="loading" @click="load">
        {{ loading ? '加载中…' : '刷新最新运行' }}
      </button>
    </div>
    <p class="muted">
      采购缺口 = 菜单所需量 − 可用库存；由后端工具计算，不由大模型生成。数据来自最近一次
      Agent 运行，可先在 Agent 决策页生成或 What-if 重规划。
    </p>

    <p v-if="error" class="error-message">{{ error }}</p>

    <article v-if="notStarted" class="empty-procurement">
      <strong>还没有 Agent 运行记录</strong>
      <p>到 Agent 决策页生成三套方案后，这里会展示对应餐次的采购缺口与导出。</p>
      <router-link class="primary-button" to="/admin/agent">去 Agent 决策页</router-link>
    </article>

    <template v-if="run && !notStarted">
      <div class="run-summary">
        <div>
          <small>最新运行</small>
          <span>{{ run.id.slice(0, 8) }}</span>
        </div>
        <div>
          <small>运行状态</small>
          <strong>{{ run.status }}</strong>
        </div>
        <div>
          <small>预计人数</small>
          <span>{{ run.constraints.expected_diners ?? '待确认' }} 人</span>
        </div>
      </div>

      <p v-for="warning in run.warnings" :key="warning" class="warning-text">{{ warning }}</p>

      <div class="strategy-tabs">
        <button
          v-for="item in run.options"
          :key="item.strategy"
          class="strategy-tab"
          :class="{ active: selectedStrategy === item.strategy }"
          @click="selectedStrategy = item.strategy"
        >
          <strong>{{ item.title }}</strong>
          <small>{{ score(item) }} · 成本 {{ money(item.estimated_cost_cents) }}</small>
        </button>
      </div>

      <div v-if="rows.length" class="table-wrap">
        <table>
          <thead>
            <tr><th>品类</th><th>食材</th><th>所需</th><th>库存</th><th>缺口</th><th>单位</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.ingredient">
              <td>{{ row.category }}</td>
              <td><strong>{{ row.ingredient }}</strong></td>
              <td>{{ row.required }}</td>
              <td>{{ row.available }}</td>
              <td class="missing">{{ row.missing }}</td>
              <td>{{ row.unit }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">当前方案库存充足，没有采购缺口。</p>

      <button v-if="rows.length" class="ghost-button" @click="exportCsv">导出 CSV</button>
    </template>
  </section>
</template>

<style scoped>
.empty-procurement {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  margin-top: 1rem;
  padding: 1.25rem;
  border: 1px dashed var(--border);
  border-radius: 12px;
}
.run-summary {
  display: flex;
  gap: 2rem;
  margin-top: 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--border);
  border-radius: 12px;
}
.run-summary small {
  display: block;
  color: var(--muted);
}
.warning-text {
  color: #a43c36;
  font-size: 13px;
}
.strategy-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 1rem;
}
.strategy-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: white;
  cursor: pointer;
}
.strategy-tab.active {
  border-color: var(--green);
  background: #eef5f2;
}
.strategy-tab small {
  color: var(--muted);
}
.table-wrap table {
  width: 100%;
  margin-top: 1rem;
  font-size: 0.9rem;
}
.panel > .ghost-button {
  margin-top: 0.9rem;
}
</style>
