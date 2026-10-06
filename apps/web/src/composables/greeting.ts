import { ref } from 'vue'

// 顶栏问候与工作台 hero 标题共享的时辰问候;首次对话后顶栏才显示问候
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const now = new Date()

export const dateLine = `${now.getMonth() + 1}月${now.getDate()}日 星期${WEEKDAYS[now.getDay()]}`

export const greeting = (() => {
  const hour = now.getHours()
  if (hour < 5) return '夜深了,想吃点什么'
  if (hour < 9) return '早上好,早餐想吃点什么'
  if (hour < 11) return '上午好,今天想吃点什么'
  if (hour < 14) return '中午好,午餐想吃点什么'
  if (hour < 18) return '下午好,想吃点什么了吗'
  return '晚上好,今晚吃什么'
})()

export const conversationStarted = ref(false)
