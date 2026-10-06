<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'

import {
  addInventoryItem,
  deleteInventoryItem,
  fetchIngredients,
  fetchInventory,
  updateInventoryItem,
  type IngredientOption,
  type InventoryItem,
} from '../../api/inventory'

defineOptions({ name: 'InventoryView' })

const items = ref<InventoryItem[]>([])
const ingredients = ref<IngredientOption[]>([])
const loading = ref(true)
const submitting = ref(false)
const searchText = ref('')
const activeCategory = ref('全部')
const showAddDialog = ref(false)
const editingItemId = ref<string | null>(null)

interface IngredientSuggestion {
  value: string
  key: string
  category: string
  default_unit: string
}

const form = ref({
  ingredient_name: '',
  ingredient_key: '',
  category: '',
  quantity: 1,
  unit: '',
  expires_on: '',
})

const TODAY = new Date()

const selectedIngredient = computed(() =>
  ingredients.value.find(
    (item) =>
      item.key === form.value.ingredient_key ||
      item.name === form.value.ingredient_name.trim(),
  ),
)

const ingredientCategories = computed(() =>
  Array.from(new Set(ingredients.value.map((item) => item.category))),
)

const categories = computed(() => ['全部', ...ingredientCategories.value])

function suggestIngredients(
  queryString: string,
  callback: (suggestions: IngredientSuggestion[]) => void,
) {
  const query = queryString.trim().toLowerCase()
  const suggestions = ingredients.value
    .filter((item) => !form.value.category || item.category === form.value.category)
    .filter((item) => !query || `${item.name}${item.key}`.toLowerCase().includes(query))
    .slice(0, 8)
    .map((item) => ({
      value: item.name,
      key: item.key,
      category: item.category,
      default_unit: item.default_unit,
    }))
  callback(suggestions)
}

function selectIngredient(item: IngredientSuggestion) {
  form.value.ingredient_name = item.value
  form.value.ingredient_key = item.key
  form.value.category = item.category
  if (!editingItemId.value || !form.value.unit) form.value.unit = item.default_unit
}

function resetForm() {
  form.value = {
    ingredient_name: '',
    ingredient_key: '',
    category: '',
    quantity: 1,
    unit: '',
    expires_on: '',
  }
  editingItemId.value = null
}

function openAddDialog() {
  resetForm()
  showAddDialog.value = true
}

function openEditDialog(item: InventoryItem) {
  editingItemId.value = item.id
  form.value = {
    ingredient_name: item.ingredient_name,
    ingredient_key: item.ingredient_key,
    category: item.category,
    quantity: Number(item.quantity) || 1,
    unit: item.unit,
    expires_on: item.expires_on ?? '',
  }
  showAddDialog.value = true
}

function daysLeft(item: InventoryItem): number | null {
  if (!item.expires_on) return null
  const expiry = new Date(`${item.expires_on}T00:00:00`)
  const start = new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate())
  return Math.round((expiry.getTime() - start.getTime()) / 86_400_000)
}

function expiryText(item: InventoryItem): string {
  const days = daysLeft(item)
  if (days === null) return '—'
  if (days < 0) return `已过期 ${-days} 天`
  if (days === 0) return '今天到期'
  if (days === 1) return '明天到期'
  return `${days} 天后到期`
}

function rowClass({ row }: { row: InventoryItem }): string {
  const days = daysLeft(row)
  if (days === null) return ''
  if (days < 0) return 'row-expired'
  if (days <= 2) return 'row-expiring'
  return ''
}

function isExpired(item: InventoryItem): boolean {
  const days = daysLeft(item)
  return days !== null && days < 0
}

function statusText(item: InventoryItem): string {
  if (isExpired(item)) return '已过期'
  return item.is_expiring ? '临期' : '正常'
}

function statusType(item: InventoryItem): 'danger' | 'warning' | 'success' {
  if (isExpired(item)) return 'danger'
  return item.is_expiring ? 'warning' : 'success'
}

// 默认按到期日升序(最快要过期的在最前),无到期日的沉底
function expirySort(a: InventoryItem, b: InventoryItem): number {
  const left = daysLeft(a)
  const right = daysLeft(b)
  if (left === null && right === null) return a.ingredient_name.localeCompare(b.ingredient_name)
  if (left === null) return 1
  if (right === null) return -1
  return left - right
}

function numberSort(a: string, b: string): number {
  return Number(a) - Number(b)
}

const filteredItems = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return items.value
    .filter((item) => activeCategory.value === '全部' || item.category === activeCategory.value)
    .filter((item) =>
      !keyword
        ? true
        : `${item.ingredient_name}${item.category}`.toLowerCase().includes(keyword),
    )
})

const stats = computed(() => {
  return {
    total: items.value.length,
    categories: new Set(items.value.map((item) => item.category)).size,
    expiring: items.value.filter((item) => {
      const days = daysLeft(item)
      return days !== null && days >= 0 && days <= 2
    }).length,
    expired: items.value.filter((item) => {
      const days = daysLeft(item)
      return days !== null && days < 0
    }).length,
  }
})

async function refresh() {
  items.value = await fetchInventory()
}

async function submit() {
  const matched = selectedIngredient.value
  if (!matched) {
    ElMessage.warning('请输入并选择一个已有食材')
    return
  }
  submitting.value = true
  try {
    if (editingItemId.value) {
      const updated = await updateInventoryItem(editingItemId.value, {
        quantity: form.value.quantity,
        unit: form.value.unit.trim() || matched.default_unit,
        expires_on: form.value.expires_on || null,
      })
      ElMessage.success(`已更新:${updated.ingredient_name} ${updated.quantity} ${updated.unit}`)
    } else {
      const created = await addInventoryItem({
        ingredient_key: matched.key,
        quantity: form.value.quantity,
        unit: form.value.unit.trim() || matched.default_unit,
        expires_on: form.value.expires_on || null,
      })
      ElMessage.success(`已保存:${created.ingredient_name} ${created.quantity} ${created.unit}`)
    }
    resetForm()
    showAddDialog.value = false
    await refresh()
  } finally {
    submitting.value = false
  }
}

async function remove(item: InventoryItem) {
  try {
    await ElMessageBox.confirm(`确定从冰箱移除「${item.ingredient_name}」吗？`, '删除食材', {
      type: 'warning',
      confirmButtonText: '移除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteInventoryItem(item.id)
  ElMessage.success(`已删除:${item.ingredient_name}`)
  await refresh()
}

async function load() {
  loading.value = true
  try {
    const [list, options] = await Promise.all([fetchInventory(), fetchIngredients()])
    items.value = list
    ingredients.value = options
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="inventory-page">
    <header class="page-hero">
      <div>
        <span class="eyebrow">FRIDGE INVENTORY</span>
        <h2>冰箱库存</h2>
        <p>与 Agent 决策同源的实时冰箱:临期食材优先消耗,新增或修改即刻影响下一次配餐。</p>
      </div>
      <div class="hero-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openAddDialog">
          新增库存
        </el-button>
      </div>
    </header>

    <div class="summary-strip">
      <div><span>在库食材</span><strong>{{ stats.total }}</strong><small>种</small></div>
      <div><span>临期(2 天内)</span><strong>{{ stats.expiring }}</strong><small>种</small></div>
      <div><span>已过期</span><strong>{{ stats.expired }}</strong><small>种</small></div>
      <div><span>食材类别</span><strong>{{ stats.categories }}</strong><small>类</small></div>
    </div>

    <el-dialog
      v-model="showAddDialog"
      :title="editingItemId ? '编辑冰箱库存' : '新增冰箱库存'"
      width="520px"
      destroy-on-close
      class="inventory-dialog"
    >
      <div class="dialog-intro">
        <span class="dialog-icon"><el-icon><Plus /></el-icon></span>
        <div>
          <strong>{{ editingItemId ? '调整这份库存信息' : '把新食材放进冰箱' }}</strong>
          <p>{{ editingItemId ? '修改数量、单位或到期日，下一次配餐会使用最新数据。' : '输入食材名称并选择建议项，Agent 会在下一次配餐中使用它。' }}</p>
        </div>
      </div>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="食材名称" required>
          <el-autocomplete
            v-model="form.ingredient_name"
            :fetch-suggestions="suggestIngredients"
            value-key="value"
            clearable
            :disabled="loading"
            :readonly="Boolean(editingItemId)"
            placeholder="输入食材名称，例如：番茄"
            style="width: 100%"
            @select="selectIngredient"
            @clear="form.ingredient_key = ''"
          >
            <template #default="{ item }">
              <div class="ingredient-suggestion">
                <span>{{ item.value }}</span>
                <small>{{ item.category }} · {{ item.default_unit }}</small>
              </div>
            </template>
          </el-autocomplete>
          <small class="field-hint">输入后请从联想结果中选择，确保食材能被 Agent 正确识别。</small>
        </el-form-item>
        <div class="form-grid two">
          <el-form-item label="食材类别" required>
            <el-select v-model="form.category" placeholder="选择类别" :disabled="Boolean(editingItemId)" style="width: 100%">
              <el-option
                v-for="category in ingredientCategories"
                :key="category"
                :label="category"
                :value="category"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="可用数量" required>
            <div class="quantity-control">
              <el-input-number v-model="form.quantity" :min="0.1" :step="0.1" :precision="1" />
            </div>
          </el-form-item>
        </div>
        <el-form-item label="单位" required>
          <el-input
            v-model="form.unit"
            maxlength="12"
            placeholder="例如：kg、个、盒、袋"
          >
            <template #suffix>
              <span class="unit-suffix-hint">默认 {{ selectedIngredient?.default_unit ?? '单位' }}</span>
            </template>
          </el-input>
          <small class="field-hint">可按实际购买方式填写，例如番茄可以记录为“个”。</small>
        </el-form-item>
        <el-form-item label="到期日期">
          <el-date-picker
            v-model="form.expires_on"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选填，临期食材会优先推荐"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
            <el-button type="primary" :loading="submitting || loading" @click="submit">{{ editingItemId ? '保存修改' : '保存入库' }}</el-button>
      </template>
    </el-dialog>

    <div class="filter-bar">
      <el-input v-model="searchText" :prefix-icon="Search" clearable placeholder="搜索食材或类别" />
      <div class="tag-filter">
        <button
          v-for="category in categories"
          :key="category"
          :class="{ active: activeCategory === category }"
          @click="activeCategory = category"
        >
          {{ category }}
        </button>
      </div>
    </div>

    <div class="inventory-table-wrap">
      <el-table
        :data="filteredItems"
        v-loading="loading"
        :row-class-name="rowClass"
        :default-sort="{ prop: 'expires_on', order: 'ascending' }"
        height="100%"
        style="width: 100%"
        empty-text="暂无库存，点击右上角新增"
      >
      <el-table-column prop="ingredient_name" label="食材" min-width="130" sortable>
        <template #default="{ row }">
          <strong>{{ row.ingredient_name }}</strong>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="类别" width="110" sortable />
      <el-table-column prop="quantity" label="可用量" width="130" sortable :sort-method="(a: InventoryItem, b: InventoryItem) => numberSort(a.quantity, b.quantity)">
        <template #default="{ row }">{{ row.quantity }} {{ row.unit }}</template>
      </el-table-column>
      <el-table-column label="到期日" width="150" sortable prop="expires_on" :sort-method="expirySort">
        <template #default="{ row }">
          <span v-if="row.expires_on" class="expiry-date">{{ row.expires_on }}</span>
          <span v-else class="expiry-none">未设到期</span>
        </template>
      </el-table-column>
      <el-table-column label="剩余" width="140" sortable :sort-method="expirySort">
        <template #default="{ row }">
          <span :class="['expiry-text', rowClass({ row })]">{{ expiryText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row)" effect="light" size="small">
            {{ statusText(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="openEditDialog(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<style scoped>
.inventory-page { max-width: 1180px; width: 100%; height: calc(100vh - 118px); min-height: 0; margin: 0 auto; padding-bottom: 0; display: flex; flex-direction: column; overflow: hidden; }
.inventory-table-wrap { flex: 1; min-height: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 14px; background: #fff; }
.hero-actions { display: flex; gap: 10px; align-items: center; }
.inventory-form {
  margin: 0 0 4px;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 18px;
  row-gap: 0.5rem;
  flex: 0 0 auto;
}
.dialog-intro { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin-bottom: 18px; background: #f3f8f5; border: 1px solid #dbeae3; border-radius: 12px; }
.dialog-icon { width: 34px; height: 34px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 10px; background: var(--green); color: #fff; }
.dialog-intro strong { color: var(--ink); font-size: 14px; }
.dialog-intro p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.field-hint { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.ingredient-suggestion { display: flex; justify-content: space-between; gap: 16px; align-items: center; width: 100%; }
.ingredient-suggestion small { color: var(--muted); font-size: 11px; }
.quantity-control { display: flex; align-items: center; gap: 8px; }
.unit-suffix-hint { color: var(--muted); font-size: 11px; white-space: nowrap; }
.unit-hint { color: var(--muted); font-size: 13px; }
.expand-enter-active, .expand-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.expand-enter-from, .expand-leave-to { opacity: 0; transform: translateY(-6px); }

.expiry-date { font-variant-numeric: tabular-nums; }
.expiry-none { color: #b3bdb9; font-size: 12.5px; }
.expiry-text { font-weight: 650; }
.expiry-text.row-expired { color: #c0392b; }
.expiry-text.row-expiring { color: #b8791b; }

/* 临期/过期行高亮:左侧色条 + 底色,一眼看出要先吃哪样 */
:deep(.el-table .row-expiring) { background: #fffaf0; }
:deep(.el-table .row-expiring td:first-child) { box-shadow: inset 3px 0 0 #e0a23c; }
:deep(.el-table .row-expired) { background: #fdf1f0; }
:deep(.el-table .row-expired td:first-child) { box-shadow: inset 3px 0 0 #c0392b; }
:deep(.el-table .row-expiring:hover > td), :deep(.el-table .row-expired:hover > td) {
  background: rgba(0, 0, 0, 0.02) !important;
}
:deep(.el-table th) { background: #f8f8f4; color: var(--muted); font-weight: 600; }
:deep(.inventory-table-wrap .el-table) { height: 100%; }
</style>
