<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiRequest } from '../../api/client'

interface MenuResponse {
  meal_service: { name: string; expected_diners: number; status: string }
  menu: Array<{ name: string; kcal_per_serving: number; allergens: string[] }>
}

const menu = ref<MenuResponse | null>(null)
const rating = ref(0)
const tags = ref<string[]>([])
const comment = ref('')
const submitted = ref(false)
const loading = ref(false)
const error = ref('')
const tagOptions = ['太咸', '太辣', '份量少', '温度低', '很喜欢']

onMounted(async () => {
  try {
    menu.value = await apiRequest<MenuResponse>('/kiosk/current-menu')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '菜单加载失败'
  }
})

function toggleTag(tag: string) {
  tags.value = tags.value.includes(tag) ? tags.value.filter((item) => item !== tag) : [...tags.value, tag]
}

function reset() {
  rating.value = 0
  tags.value = []
  comment.value = ''
  submitted.value = false
}

async function submit() {
  if (!rating.value) return
  loading.value = true
  error.value = ''
  try {
    await apiRequest('/kiosk/feedback', {
      method: 'POST',
      body: JSON.stringify({
        meal_service_id: 'demo-lunch',
        meal_plan_id: 'demo-plan',
        rating: rating.value,
        tags: tags.value,
        comment: comment.value || null,
      }),
    })
    submitted.value = true
    window.setTimeout(reset, 3000)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '提交失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="kiosk-shell">
    <header class="kiosk-header">
      <div class="brand">
        <span class="brand-mark">食</span>
        <div><strong>机关一食堂</strong><small>公共用餐反馈终端</small></div>
      </div>
      <span>今日午餐 · 匿名反馈</span>
    </header>

    <section v-if="submitted" class="thank-you">
      <div class="thank-icon">✓</div>
      <h1>感谢您的反馈</h1>
      <p>页面将在 3 秒后自动清空，供下一位使用。</p>
    </section>

    <section v-else class="kiosk-content">
      <div>
        <p class="eyebrow">TODAY'S MENU</p>
        <h1>今天的菜品</h1>
        <div v-if="menu" class="kiosk-menu-grid">
          <article v-for="dish in menu.menu" :key="dish.name">
            <strong>{{ dish.name }}</strong>
            <span>约 {{ dish.kcal_per_serving }} kcal / 人</span>
            <small>{{ dish.allergens.length ? `过敏原：${dish.allergens.join('、')}` : '无已知主要过敏原' }}</small>
          </article>
        </div>
      </div>

      <div class="feedback-card">
        <p class="eyebrow">YOUR FEEDBACK</p>
        <h2>这顿饭您满意吗？</h2>
        <div class="rating-row">
          <button v-for="value in 5" :key="value" :class="{ active: rating === value }" @click="rating = value">
            <span>{{ ['很差', '一般', '还行', '满意', '很好'][value - 1] }}</span>
            <strong>{{ value }}</strong>
          </button>
        </div>
        <div class="tag-row">
          <button v-for="tag in tagOptions" :key="tag" :class="{ active: tags.includes(tag) }" @click="toggleTag(tag)">
            {{ tag }}
          </button>
        </div>
        <textarea v-model="comment" maxlength="300" rows="2" placeholder="选填：还有什么想告诉我们？"></textarea>
        <button class="kiosk-submit" :disabled="!rating || loading" @click="submit">
          {{ loading ? '正在提交…' : '提交匿名反馈' }}
        </button>
        <p v-if="error" class="error-message">{{ error }}</p>
      </div>
    </section>
  </main>
</template>
