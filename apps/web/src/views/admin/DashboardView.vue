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
  </section>
</template>
