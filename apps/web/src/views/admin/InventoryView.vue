<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  addInventoryItem,
  deleteInventoryItem,
  fetchIngredients,
  fetchInventory,
  type IngredientOption,
  type InventoryItem,
} from '../../api/inventory'

const items = ref<InventoryItem[]>([])
const ingredients = ref<IngredientOption[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')

const form = ref({ ingredient_key: '', quantity: 1, expires_on: '' })
const submitting = ref(false)

const groupedIngredients = computed(() => {
  const groups = new Map<string, IngredientOption[]>()
  for (const ingredient of ingredients.value) {
    const list = groups.get(ingredient.category) ?? []
    list.push(ingredient)
    groups.set(ingredient.category, list)
  }
  return [...groups.entries()]
})

const selectedIngredient = computed(() =>
  ingredients.value.find((item) => item.key === form.value.ingredient_key),
)

function expiryText(item: InventoryItem): string {
  if (!item.expires_on) return '—'
  const today = new Date()
  const expiry = new Date(`${item.expires_on}T00:00:00`)
  const days = Math.round((expiry.getTime() - today.getTime()) / 86_400_000)
  if (days < 0) return `已过期 ${-days} 天`
  if (days === 0) return '今天到期'
  return `${item.expires_on}（${days} 天后）`
}

async function refresh() {
  error.value = ''
  try {
    items.value = await fetchInventory()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载库存失败'
  }
}

async function submit() {
  if (!form.value.ingredient_key) {
    error.value = '请选择食材'
    return
  }
  submitting.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await addInventoryItem({
      ingredient_key: form.value.ingredient_key,
      quantity: form.value.quantity,
      expires_on: form.value.expires_on || null,
    })
    notice.value = `已保存：${created.ingredient_name} ${created.quantity} ${created.unit}`
    form.value = { ingredient_key: '', quantity: 1, expires_on: '' }
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '新增库存失败'
  } finally {
    submitting.value = false
  }
}

async function remove(item: InventoryItem) {
  error.value = ''
  notice.value = ''
  try {
    await deleteInventoryItem(item.id)
    notice.value = `已删除：${item.ingredient_name}`
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '删除失败'
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, options] = await Promise.all([fetchInventory(), fetchIngredients()])
    items.value = list
    ingredients.value = options
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载库存失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <small>AGENT DATA SOURCE</small>
        <h2>库存与临期状态</h2>
      </div>
    </div>
    <p class="muted">与 Agent 决策同源的实时库存；新增/修改即影响下一次规划与采购缺口。</p>
    <p v-if="error" class="error-message">{{ error }}</p>
    <p v-if="notice" class="muted">{{ notice }}</p>

    <form class="inventory-form" @submit.prevent="submit">
      <select v-model="form.ingredient_key" aria-label="选择食材" :disabled="loading">
        <option value="" disabled>选择食材</option>
        <optgroup v-for="[category, options] in groupedIngredients" :key="category" :label="category">
          <option v-for="option in options" :key="option.key" :value="option.key">
            {{ option.name }}（{{ option.default_unit }}）
          </option>
        </optgroup>
      </select>
      <input
        v-model.number="form.quantity"
        type="number"
        min="0"
        step="0.1"
        aria-label="数量"
        :placeholder="selectedIngredient ? `数量（${selectedIngredient.default_unit}）` : '数量'"
      />
      <span class="muted">{{ selectedIngredient?.default_unit ?? '' }}</span>
      <input v-model="form.expires_on" type="date" aria-label="到期日期" />
      <button class="primary-button" type="submit" :disabled="submitting || loading">
        {{ submitting ? '保存中…' : '新增库存' }}
      </button>
    </form>

    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>食材</th><th>类别</th><th>可用量</th><th>到期</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" class="muted">加载中…</td></tr>
          <tr v-else-if="items.length === 0"><td colspan="6" class="muted">暂无库存</td></tr>
          <tr v-for="item in items" :key="item.id">
            <td><strong>{{ item.ingredient_name }}</strong></td>
            <td>{{ item.category }}</td>
            <td>{{ item.quantity }} {{ item.unit }}</td>
            <td>{{ expiryText(item) }}</td>
            <td>
              <span :class="['status-pill', item.is_expiring ? 'danger' : '']">
                {{ item.is_expiring ? '临期' : '正常' }}
              </span>
            </td>
            <td><button class="ghost-button" @click="remove(item)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.inventory-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0.75rem 0 1rem;
}
.inventory-form select,
.inventory-form input {
  padding: 0.45rem 0.6rem;
  border: 1px solid rgba(15, 76, 69, 0.25);
  border-radius: 8px;
  background: #fff;
}
</style>
