import { defineStore } from 'pinia'

// 跨页面把文本填入智能配餐输入框:
// 宝典等页面 stage() 后跳转 /admin/agent,工作台在 onActivated 里 consume() 消费。
export const useAgentHandoffStore = defineStore('agentHandoff', {
  state: () => ({
    pendingText: '',
  }),
  getters: {
    hasPending: (state) => state.pendingText.trim().length > 0,
  },
  actions: {
    stage(text: string) {
      this.pendingText = text
    },
    consume(): string {
      const text = this.pendingText
      this.pendingText = ''
      return text
    },
  },
})
