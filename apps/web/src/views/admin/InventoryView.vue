<script setup lang="ts">
const inventory = [
  { name: '番茄', quantity: '12 kg', expires: '2 天后', status: '临期' },
  { name: '鸡蛋', quantity: '360 枚', expires: '12 天后', status: '正常' },
  { name: '土豆', quantity: '28 kg', expires: '18 天后', status: '正常' },
  { name: '鸡胸肉', quantity: '16 kg', expires: '4 天后', status: '关注' },
]
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <small>AGENT DATA SOURCE</small>
        <h2>库存与临期状态</h2>
      </div>
      <button class="primary-button">新增库存</button>
    </div>
    <p class="muted">这些数据由 Agent 通过只读工具获取；模型不能直接修改库存。</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>食材</th><th>可用量</th><th>到期</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="item in inventory" :key="item.name">
            <td><strong>{{ item.name }}</strong></td>
            <td>{{ item.quantity }}</td>
            <td>{{ item.expires }}</td>
            <td><span :class="['status-pill', item.status === '临期' ? 'danger' : '']">{{ item.status }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
