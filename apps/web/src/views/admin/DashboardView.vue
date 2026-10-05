<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchDailyFeedback, type DailyFeedbackDay } from '../../api/feedback'

defineOptions({ name: 'DashboardView' })

const days = ref<DailyFeedbackDay[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    days.value = await fetchDailyFeedback()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载每日反馈失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function stars(rating: number): string {
  return '★'.repeat(rating) + '☆'.repeat(5 - rating)
}

function timeOf(iso: string): string {
  return iso.slice(11, 16)
}
</script>

<template>
  <section class="page-grid">
    <article class="metric-card hero-metric">
      <small>明日预计用餐</small>
      <strong>120 人</strong>
      <span>午餐 · 11:30–13:00</span>
    </article>
    <article class="metric-card warning-card">
      <small>临期库存</small>
      <strong>1 项</strong>
      <span>番茄 12kg · 2 天后到期</span>
    </article>
    <article class="metric-card">
      <small>预算上限</small>
      <strong>¥900</strong>
      <span>待 Agent 规划</span>
    </article>
    <article class="panel span-3">
      <div class="panel-heading">
        <div>
          <small>Agent-ready context</small>
          <h2>规划上下文已经就绪</h2>
        </div>
        <RouterLink class="primary-link" to="/admin/agent">开始 Agent 决策</RouterLink>
      </div>
      <p class="muted">
        餐次、库存、临期、预算、过敏原和历史反馈会作为业务工具数据提供给 Agent，
        所有数量与成本由确定性服务计算。
      </p>
    </article>

    <article class="panel span-3 daily-panel">
      <div class="panel-heading">
        <div>
          <small>DAILY MENU &amp; FEEDBACK</small>
          <h2>每日菜单与反馈</h2>
        </div>
        <button class="ghost-button" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
      <p class="muted daily-hint">
        每天的反馈与当天已发布菜单放在一起展示；反馈不超过 10 条时逐条显示，超过 10 条自动概括。
      </p>
      <p v-if="error" class="error-message">{{ error }}</p>
      <p v-else-if="!loading && !days.length" class="muted">还没有餐次数据，先运行种子脚本。</p>

      <article v-for="day in days" :key="day.meal_service_id" class="day-card">
        <div class="day-head">
          <strong>{{ day.date }} · {{ day.meal_service_name }}</strong>
          <span class="day-count">{{ day.feedback_count }} 条反馈</span>
        </div>
        <div class="day-dishes">
          <span class="day-label">当日菜单</span>
          <template v-if="day.dishes.length">
            <span v-for="dish in day.dishes" :key="dish" class="dish-chip">{{ dish }}</span>
          </template>
          <span v-else class="muted">当天还没有已发布菜单</span>
        </div>

        <div v-if="day.entries && day.entries.length" class="feedback-entries">
          <div v-for="(entry, index) in day.entries" :key="index" class="feedback-entry">
            <span class="entry-stars" :class="{ low: entry.rating <= 2 }">{{ stars(entry.rating) }}</span>
            <span v-if="entry.tags.length" class="entry-tags">
              <em v-for="tag in entry.tags" :key="tag">{{ tag }}</em>
            </span>
            <span v-if="entry.comment" class="entry-comment">{{ entry.comment }}</span>
            <small class="entry-time">{{ timeOf(entry.submitted_at) }}</small>
          </div>
        </div>
        <div v-else-if="day.summary" class="feedback-summary">
          <p>
            共 {{ day.summary.sample_count }} 条反馈，平均
            <strong>{{ day.summary.avg_rating ?? '—' }}</strong> 分，已自动概括：
          </p>
          <p v-if="day.summary.top_tags.length">
            主要标签：
            <em v-for="tag in day.summary.top_tags" :key="tag" class="entry-tags">{{ tag }}</em>
          </p>
          <ul v-if="day.summary.comment_digest.length">
            <li v-for="digest in day.summary.comment_digest" :key="digest">“{{ digest }}”</li>
          </ul>
        </div>
        <p v-else-if="day.entries" class="muted day-empty">当天暂无反馈</p>
      </article>
    </article>
  </section>
</template>

<style scoped>
.daily-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.daily-hint {
  font-size: 0.8rem;
  margin: 0;
}
.day-card {
  border: 1px solid rgba(15, 76, 69, 0.15);
  border-radius: 10px;
  padding: 0.75rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.day-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}
.day-count {
  font-size: 0.8rem;
  color: rgba(15, 76, 69, 0.7);
}
.day-dishes {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
}
.day-label {
  font-size: 0.75rem;
  color: rgba(15, 76, 69, 0.6);
  margin-right: 0.2rem;
}
.dish-chip {
  background: rgba(15, 76, 69, 0.08);
  color: #0f4c45;
  border-radius: 999px;
  padding: 0.12rem 0.6rem;
  font-size: 0.8rem;
}
.feedback-entries {
  display: flex;
  flex-direction: column;
}
.feedback-entry {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.6rem;
  padding: 0.35rem 0;
  border-top: 1px dashed rgba(15, 76, 69, 0.15);
  font-size: 0.85rem;
}
.entry-stars {
  color: #d99a1b;
  letter-spacing: 0.08em;
}
.entry-stars.low {
  color: #c0392b;
}
.entry-tags em,
.feedback-summary em {
  font-style: normal;
  background: rgba(15, 76, 69, 0.08);
  border-radius: 6px;
  padding: 0.05rem 0.4rem;
  font-size: 0.78rem;
  margin-right: 0.25rem;
}
.entry-comment {
  color: rgba(23, 42, 58, 0.85);
}
.entry-time {
  margin-left: auto;
  color: rgba(15, 76, 69, 0.55);
}
.feedback-summary {
  font-size: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.feedback-summary ul {
  margin: 0;
  padding-left: 1.1rem;
}
.day-empty {
  font-size: 0.82rem;
  margin: 0;
}
</style>
