<script setup lang="ts">
const rows = [
  { category: '蛋奶', ingredient: '鸡蛋', required: '30 kg', available: '18 kg', missing: '12 kg' },
  { category: '肉类', ingredient: '鸡胸肉', required: '30 kg', available: '16 kg', missing: '14 kg' },
  { category: '蔬菜', ingredient: '番茄', required: '24 kg', available: '12 kg', missing: '12 kg' },
]
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <small>DETERMINISTIC RESULT</small>
        <h2>采购缺口预览</h2>
      </div>
      <button class="ghost-button">导出 CSV</button>
    </div>
    <p class="muted">采购缺口 = 菜单所需量 − 可用库存；由后端工具计算，不由大模型生成。</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>品类</th><th>食材</th><th>所需</th><th>库存</th><th>缺口</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.ingredient">
            <td>{{ row.category }}</td><td><strong>{{ row.ingredient }}</strong></td>
            <td>{{ row.required }}</td><td>{{ row.available }}</td><td class="missing">{{ row.missing }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
