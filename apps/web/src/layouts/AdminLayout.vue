<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const navItems = [
  { path: '/admin/dashboard', label: '运营概览' },
  { path: '/admin/agent', label: 'Agent 决策' },
  { path: '/admin/inventory', label: '库存管理' },
  { path: '/admin/procurement', label: '采购清单' },
]
</script>

<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">食</span>
        <div>
          <strong>食序 MealFlow</strong>
          <small>机关食堂运营决策 Agent</small>
        </div>
      </div>
      <nav>
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: route.path === item.path }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="sidebar-note">
        <span class="status-dot"></span>
        演示工作区 · 机关一食堂
      </div>
    </aside>
    <main class="admin-main">
      <header class="topbar">
        <div>
          <small>政府机关食堂 · V1 演示环境</small>
          <h1>明日午餐运营</h1>
        </div>
        <div class="operator">管理员 Lrio</div>
      </header>
      <RouterView v-slot="{ Component }">
        <!-- Agent 决策页在切换页面时保留运行结果；Kiosk 与其他页面不受影响 -->
        <KeepAlive include="AgentPlannerView">
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
