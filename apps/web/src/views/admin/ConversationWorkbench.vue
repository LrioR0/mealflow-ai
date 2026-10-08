<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { generateProcurement } from '../../composables/procurement'
import { useAgentHandoffStore } from '../../stores/agentHandoff'

import { ArrowDown, Check, Delete, User } from '@element-plus/icons-vue'

import {
  conversationStarted,
  greeting as timeGreeting,
} from '../../composables/greeting'

import {
  createHouseholdEvent,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessions,
  fetchHousehold,
  fetchRecipeDetail,
  streamChat,
  type ChatSessionSummary,
  type Household,
  type RecipeDetail,
} from '../../api/chat'
import type { AgentRun } from '../../types/agent'

defineOptions({ name: 'ConversationWorkbench' })

interface StatusStep {
  step: string
  /** 后端按本次工具调用动态生成的步骤名,优先于本地标签表显示 */
  label?: string
  state: 'running' | 'done'
  detail: string
}

interface CandidateItem {
  recipe_id: string
  name: string
  ingredients_summary: string
  conflict_level: 'forbidden' | 'warn' | null
  conflict_summary: string | null
  expiring: boolean
  expiring_used: string[]
  used_fridge: string[]
  missing: string[]
}

// 库未命中时实时搜索到的网络菜谱(下厨房),仅食材清单与步骤梗概
interface WebRecipeItem {
  title: string
  url: string
  ingredients: string
  rating: string | null
  cooked_count: string | null
  steps_brief: string[]
}

interface ChatBubble {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking: string
  thinkingDone: boolean
  steps: StatusStep[]
  plan: AgentRun | null
  selectedStrategy: string
  questions: string[]
  streaming: boolean
  error: string
  stopped?: boolean
  searchQuery?: string
  candidates?: CandidateItem[]
  candidatesQuery?: string
  webQuery?: string
  webRecipes?: WebRecipeItem[]
  thinkingOpen?: boolean
}

const STEP_LABELS: Record<string, string> = {
  session: '会话就绪',
  parse_request: '理解需求',
  get_meal_service_context: '确认餐次',
  list_inventory: '读取冰箱',
  get_member_constraints: '检查用餐限制',
  search_recipe_candidates: '召回菜谱',
  filter_hard_constraints: '过滤硬约束',
  score_menu_options: '方案评分',
  scale_recipe_quantities: '按人数换算',
  estimate_nutrition_and_cost: '估算热量成本',
  build_procurement_list: '生成采购缺口',
}

const EVENT_TYPES = ['例假', '感冒', '肠胃不适', '康复期', '最近在健身', '减脂', '其他']

function seq(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

const messages = ref<ChatBubble[]>([])
// 首次对话后顶栏才出现问候语(初始页让位给居中大标题)
watch(
  () => messages.value.length,
  (len) => {
    conversationStarted.value = len > 0
  },
)
const input = ref('')
const sending = ref(false)
const currentAbort = ref<AbortController | null>(null)
const sessionId = ref<string | null>(null)
const listEl = ref<HTMLElement | null>(null)
const recipeCache = ref<Record<string, RecipeDetail>>({})
const expandedDish = ref<string | null>(null)
const household = ref<Household | null>(null)
const selectedDinerIds = ref<string[]>([])
const dinerPickerOpen = ref(false)
const dinerSelectorEl = ref<HTMLElement | null>(null)
const knownMemberIds = new Set<string>()
const CHAT_SCROLL_KEY = 'mealflow_agent_chat_scroll_top_v1'
const CHAT_SESSION_KEY = 'mealflow_agent_chat_session_id_v1'
const savedChatScrollTop = ref(0)

// ===== 会话管理:历史下拉 + 新建对话 + 刷新恢复 =====
const sessionMenuOpen = ref(false)
const sessionMenuEl = ref<HTMLElement | null>(null)
const sessions = ref<ChatSessionSummary[]>([])
const sessionsLoading = ref(false)
const restoring = ref(false)

const activeSessionTitle = computed(
  () => sessions.value.find((item) => item.session_id === sessionId.value)?.title ?? '当前对话',
)

function relativeTime(iso: string): string {
  const delta = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(delta)) return ''
  const minutes = Math.floor(delta / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await fetchChatSessions()
  } catch {
    // 列表加载失败不打断对话,下拉里显示空态
  } finally {
    sessionsLoading.value = false
  }
}

function toggleSessionMenu() {
  sessionMenuOpen.value = !sessionMenuOpen.value
  if (sessionMenuOpen.value) void loadSessions()
}

// 新建对话:界面清空,旧会话保留在库里,可从下拉重新进入
function startNewSession() {
  if (sending.value || restoring.value) return
  currentAbort.value?.abort()
  sessionId.value = null
  sessionStorage.removeItem(CHAT_SESSION_KEY)
  messages.value = []
  expandedDish.value = null
  followLatest.value = true
  sessionMenuOpen.value = false
}

// 删除历史会话:确认后删除;若删的是当前打开的会话,界面同步清空
async function removeSession(item: ChatSessionSummary) {
  if (sending.value || restoring.value) return
  try {
    await ElMessageBox.confirm(`删除「${item.title}」？删除后不可恢复。`, '删除对话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteChatSession(item.session_id)
    sessions.value = sessions.value.filter((entry) => entry.session_id !== item.session_id)
    if (sessionId.value === item.session_id) {
      currentAbort.value?.abort()
      sessionId.value = null
      sessionStorage.removeItem(CHAT_SESSION_KEY)
      messages.value = []
      expandedDish.value = null
    }
    ElMessage.success('对话已删除')
  } catch {
    ElMessage.error('删除失败，请重试')
  }
}

// 恢复历史会话:回放消息(思考过程默认收起,可展开回看)
async function restoreSession(id: string) {
  if (sending.value || restoring.value || id === sessionId.value) {
    sessionMenuOpen.value = false
    return
  }
  restoring.value = true
  sessionMenuOpen.value = false
  try {
    const view = await fetchChatSession(id)
    currentAbort.value?.abort()
    sessionId.value = view.session_id
    sessionStorage.setItem(CHAT_SESSION_KEY, view.session_id)
    expandedDish.value = null
    followLatest.value = true
    messages.value = view.messages.map((message) =>
      reactive({
        id: message.id,
        role: message.role === 'user' ? ('user' as const) : ('assistant' as const),
        content: message.content,
        thinking: message.thinking_text ?? '',
        thinkingDone: true,
        thinkingOpen: false,
        steps: [],
        plan: null,
        selectedStrategy: '',
        questions: [],
        streaming: false,
        error: '',
      }),
    )
    void nextTick(() => {
      const list = listEl.value
      if (list) list.scrollTop = list.scrollHeight
    })
  } catch {
    ElMessage.error('会话恢复失败，请重试')
  } finally {
    restoring.value = false
  }
}

const selectedDiners = computed(() =>
  (household.value?.members ?? []).filter((member) => selectedDinerIds.value.includes(member.user_id)),
)

const dinerSummary = computed(() =>
  selectedDiners.value.length
    ? selectedDiners.value.map((member) => member.display_name).join('、')
    : '还未选择用餐人',
)

async function loadHousehold() {
  try {
    household.value = await fetchHousehold()
    const currentIds = household.value.members.map((member) => member.user_id)
    selectedDinerIds.value = selectedDinerIds.value.filter((id) => currentIds.includes(id))
    for (const member of household.value.members) {
      if (!knownMemberIds.has(member.user_id) && member.residency === 'resident') {
        selectedDinerIds.value.push(member.user_id)
      }
      knownMemberIds.add(member.user_id)
    }
  } catch {
    // 家庭档案加载失败不阻断对话
  }
}

function rememberChatScroll() {
  const list = listEl.value
  if (!list) return
  savedChatScrollTop.value = list.scrollTop
  sessionStorage.setItem(CHAT_SCROLL_KEY, String(list.scrollTop))
}

function restoreChatScroll() {
  void nextTick(() => {
    const list = listEl.value
    if (!list || !messages.value.length) return
    const stored = Number(sessionStorage.getItem(CHAT_SCROLL_KEY) ?? savedChatScrollTop.value)
    if (!Number.isFinite(stored)) return
    list.scrollTop = stored
    onListScroll()
  })
}

const agentHandoff = useAgentHandoffStore()

onActivated(() => {
  // 懒人宝典等页面跳转过来时,把待填文本放入输入框(只填充,不自动发送)
  const pendingText = agentHandoff.consume()
  if (pendingText) {
    input.value = pendingText
    ElMessage({ message: '已把需求填入输入框,确认后发送即可', type: 'success', grouping: true })
  }
  void loadHousehold()
  // 刷新后组件重建:从 sessionStorage 恢复当前会话(KeepAlive 内切换页面则 ref 还在,跳过)
  if (!sessionId.value && !messages.value.length) {
    const saved = sessionStorage.getItem(CHAT_SESSION_KEY)
    if (saved) void restoreSession(saved)
  }
  restoreChatScroll()
})
onDeactivated(rememberChatScroll)

let scrollFrame: number | null = null
const followLatest = ref(true)
onBeforeUnmount(() => {
  rememberChatScroll()
  if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (dinerPickerOpen.value && target && !dinerSelectorEl.value?.contains(target)) {
    dinerPickerOpen.value = false
  }
  if (sessionMenuOpen.value && target && !sessionMenuEl.value?.contains(target)) {
    sessionMenuOpen.value = false
  }
}

document.addEventListener('pointerdown', onDocumentPointerDown)

function onListScroll() {
  const list = listEl.value
  if (list) followLatest.value = list.scrollHeight - list.scrollTop - list.clientHeight < 96
}

function scrollBottom() {
  if (scrollFrame !== null || !followLatest.value) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = null
    void nextTick(() => {
      const list = listEl.value
      if (list && followLatest.value) list.scrollTop = list.scrollHeight
    })
  })
}

function stepLabel(stepItem: StatusStep): string {
  return stepItem.label || STEP_LABELS[stepItem.step] || stepItem.step
}

function strategySummary(strategy: string): string {
  const summaries: Record<string, string> = {
    expiring_first: '优先消耗临期食材',
    original_first: '尊重菜谱原版做法与标准配比',
    balanced_first: '综合评估临期、口味、时间与预算',
    dislike_first: '优先避开长期忌口，过敏原始终为红线',
  }
  return summaries[strategy] ?? '按当前家庭条件综合安排'
}

// 安全约定：此处用 v-html 渲染 AI 回复，前提是 renderMarkdown 必须
// 先做 HTML 实体转义（& < >），再只注入 <strong>/<br/> 这类受控标签。
// 禁止把未转义文本、第三方抓取内容（如下厨房标题）或引入的 markdown
// 库的原始 HTML 直接喂给 v-html；改动渲染逻辑前先想清楚这条底线。
function renderMarkdown(text: string): string {
  const escaped = polishClarification(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>')
}

function money(cents: number | null | undefined): string {
  if (cents == null) return '—'
  return `¥${(cents / 100).toFixed(2)}`
}

function budgetLine(plan: AgentRun): string {
  const budget = plan.constraints.budget_limit_cents
  if (!budget) return ''
  const diff = budget - (plan.options[0]?.estimated_cost_cents ?? 0)
  return diff >= 0 ? `预算还剩 ${money(diff)}` : `超出预算 ${money(-diff)}`
}

function planBudgetText(plan: AgentRun | null): string {
  if (!plan) return ''
  return budgetLine(plan)
}

function dishWarning(plan: AgentRun, dish: string): string {
  for (const option of plan.options) {
    for (const warning of option.warnings ?? []) {
      if (warning.includes(`:${dish}——`)) return warning
    }
  }
  return ''
}

function warningLevel(warning: string): 'forbidden' | 'warn' {
  return warning.startsWith('⛔') ? 'forbidden' : 'warn'
}

function polishClarification(text: string): string {
  const prefix = '好,先确认两件事:这餐几个人吃?有预算上限的话我一并算进成本和采购缺口里。全家当前的饮食限制我记着呢:'
  let polished = text.replace(
    prefix,
    '好，我们来安排这顿饭。请在输入框下方确认用餐人员；有预算上限，也可以直接告诉我，我会一并计算食材用量、预计费用和需要采购的食材。\n\n已读取的家庭饮食提醒：\n',
  )
  for (const member of household.value?.members ?? []) {
    for (const restriction of member.restrictions) {
      polished = polished.replaceAll(restriction.ingredient_key, restriction.ingredient_name)
    }
  }
  if (text.includes(prefix)) polished = polished.replaceAll('；', '\n').replaceAll('(', '（').replaceAll(')', '）')
  return polished
}

function allStepsDone(bubble: ChatBubble): boolean {
  return bubble.steps.length > 0 && bubble.steps.every((step) => step.state === 'done')
}

async function toggleRecipe(dish: string, plan: AgentRun | null) {
  if (expandedDish.value === dish) {
    expandedDish.value = null
    return
  }
  expandedDish.value = dish
  if (recipeCache.value[dish]) return
  const recipeId = plan?.options
    .flatMap((option) => option.items)
    .find((item) => item.name === dish)?.recipe_id
  if (!recipeId) return
  const detail = await fetchRecipeDetail(
    String(recipeId),
    plan?.constraints.expected_diners ?? undefined,
  )
  recipeCache.value = { ...recipeCache.value, [dish]: detail }
}

// 候选菜列表点击:复用详情展开,按当前勾选的用餐人数换算用量
async function openCandidate(item: CandidateItem) {
  if (expandedDish.value === item.name) {
    expandedDish.value = null
    return
  }
  expandedDish.value = item.name
  if (recipeCache.value[item.name]) return
  const detail = await fetchRecipeDetail(
    String(item.recipe_id),
    selectedDiners.value.length || undefined,
  )
  recipeCache.value = { ...recipeCache.value, [item.name]: detail }
}

// 库存使用标注:临期食材带(临期)后缀
function fridgeUsageText(item: CandidateItem): string {
  if (!item.used_fridge?.length) return ''
  return item.used_fridge
    .map((name) => (item.expiring_used?.includes(name) ? `${name}(临期)` : name))
    .join('、')
}

async function confirmPlan(bubble: ChatBubble) {
  if (sending.value) return
  const option = bubble.plan?.options.find((item) => item.strategy === bubble.selectedStrategy)
  if (!option || !bubble.plan) return
  if (option?.procurement_list?.length) {
    try {
      const added = await generateProcurement(option.procurement_list, `${bubble.plan.id}:${option.strategy}`)
      ElMessage.success(added ? `已将 ${added} 项食材加入采购清单` : '这套方案的采购项已在清单中')
    } catch {
      ElMessage.error('采购清单保存失败，请检查浏览器存储空间')
      return
    }
  } else {
    ElMessage.success('现有食材已足够，无需新增采购项')
  }
  ask(`确认${option.title}，就做这套`)
}

function ask(text: string) {
  if (sending.value) return
  void send(text)
}

async function send(preset?: string) {
  const displayMessage = (preset ?? input.value).trim()
  if (!displayMessage || sending.value) return
  if (household.value && !selectedDiners.value.length) {
    ElMessage.info('请先选择至少一位用餐人员')
    dinerPickerOpen.value = true
    return
  }
  const dinerContext = selectedDiners.value.length
    ? `本次用餐${selectedDiners.value.length}人，人员：${selectedDiners.value.map((member) => member.display_name).join('、')}`
    : '本次暂未选择用餐人员'
  const requestMessage = `${displayMessage}\n\n[${dinerContext}]`.slice(0, 2000)
  dinerPickerOpen.value = false
  followLatest.value = true
  sending.value = true
  input.value = ''
  messages.value.push({
    id: seq(),
    role: 'user',
    content: displayMessage,
    thinking: '',
    thinkingDone: false,
    steps: [],
    plan: null,
    selectedStrategy: '',
    questions: [],
    streaming: false,
    error: '',
  })
  // 必须用 reactive 引用:普通对象在 push 后与响应式代理脱节,流式更新不会触发渲染
  const assistant = reactive<ChatBubble>({
    id: seq(),
    role: 'assistant',
    content: '',
    thinking: '',
    thinkingDone: false,
    steps: [],
    plan: null,
    selectedStrategy: '',
    questions: [],
    streaming: true,
    error: '',
  })
  messages.value.push(assistant)
  scrollBottom()
  let thinkingIdleTimer: ReturnType<typeof setTimeout> | undefined

  // 中断控制器:发送后可主动停止流式生成(后端 SSE 随断开自动取消)
  const controller = new AbortController()
  currentAbort.value = controller

  try {
    for await (const event of streamChat({
      session_id: sessionId.value,
      diners_user_ids: selectedDinerIds.value,
      message: requestMessage,
    }, controller.signal)) {
      if (event.event === 'thinking') {
        assistant.thinking += String(event.data.delta ?? '')
        assistant.thinkingDone = false
        assistant.thinkingOpen = true // 流式期间自动展开,实时看思维链
        clearTimeout(thinkingIdleTimer)
        thinkingIdleTimer = setTimeout(() => {
          assistant.thinkingDone = true
        }, 700)
      } else if (event.event === 'status') {
        const step = String(event.data.step ?? '')
        const label = String(event.data.label ?? '')
        const state = event.data.state === 'running' ? 'running' : 'done'
        const detail = String(event.data.detail ?? '')
        if (state === 'running') {
          assistant.steps.push({ step, label, state, detail: '' })
        } else {
          const reverseIdx = [...assistant.steps]
            .reverse()
            .findIndex((item) => item.step === step && item.state === 'running')
          if (reverseIdx >= 0) {
            const real = assistant.steps.length - 1 - reverseIdx
            assistant.steps[real] = { step, label: label || assistant.steps[real].label, state: 'done', detail }
          } else {
            assistant.steps.push({ step, label, state: 'done', detail })
          }
        }
      } else if (event.event === 'text') {
        assistant.content += String(event.data.delta ?? '')
        assistant.thinkingDone = true
      } else if (event.event === 'plan') {
        assistant.thinkingDone = true
        assistant.plan = event.data as unknown as AgentRun
        assistant.selectedStrategy = assistant.plan.options[0]?.strategy ?? ''
      } else if (event.event === 'candidates') {
        // 食材模糊查询:候选菜列表(规则召回,不含 run),点击展开做法详情
        assistant.thinkingDone = true
        assistant.candidatesQuery = String(event.data.query ?? '')
        assistant.candidates = (event.data.items as CandidateItem[]) ?? []
      } else if (event.event === 'web_recipes') {
        // 本地库未命中时的实时搜索结果(下厨房,仅食材清单与步骤梗概)
        assistant.thinkingDone = true
        assistant.webQuery = String(event.data.query ?? '')
        assistant.webRecipes = (event.data.items as WebRecipeItem[]) ?? []
      } else if (event.event === 'questions') {
        assistant.questions = (event.data.items as string[]) ?? []
      } else if (event.event === 'error') {
        assistant.error = String(event.data.message ?? 'Agent 运行失败')
      } else if (event.event === 'done') {
        assistant.streaming = false
        assistant.thinkingDone = true
        // 菜单列表的思考过程保持展开(决策透明);其余分支收起,答案为主
        assistant.thinkingOpen = Boolean(assistant.candidates?.length)
        sessionId.value = (event.data.session_id as string) ?? sessionId.value
        if (sessionId.value) sessionStorage.setItem(CHAT_SESSION_KEY, sessionId.value)
        assistant.searchQuery = typeof event.data.search_query === 'string' ? event.data.search_query : undefined
      }
      scrollBottom()
    }
  } catch (reason) {
    // 主动停止:静默收尾并标注,不当错误弹给用户
    if (reason instanceof DOMException && reason.name === 'AbortError') {
      assistant.stopped = true
    } else {
      assistant.error = reason instanceof Error ? reason.message : '连接中断'
    }
  } finally {
    currentAbort.value = null
    clearTimeout(thinkingIdleTimer)
    assistant.streaming = false
    // 收尾兜底:中断/出错时把仍"进行中"的步骤标记完成,避免 mini-spinner 永转
    assistant.steps.forEach((item) => {
      if (item.state === 'running') item.state = 'done'
    })
    sending.value = false
    scrollBottom()
  }
}

// 停止生成:中断当前流,已输出的内容保留
function stopGeneration() {
  currentAbort.value?.abort()
}

</script>

<template>
  <section class="workbench">
    <div class="chat-panel">
      <!-- 会话栏:新建对话 + 历史会话下拉 -->
      <div class="session-bar">
        <button class="new-session-btn" type="button" :disabled="sending || restoring" @click="startNewSession">
          ＋ 新建对话
        </button>
        <div ref="sessionMenuEl" class="session-menu" :class="{ open: sessionMenuOpen }">
          <button class="session-menu-trigger" type="button" @click.stop="toggleSessionMenu">
            <span class="session-menu-title">{{ activeSessionTitle }}</span>
            <span class="session-menu-chevron">{{ sessionMenuOpen ? '⌃' : '⌄' }}</span>
          </button>
          <div v-if="sessionMenuOpen" class="session-menu-panel" @pointerdown.stop>
            <div class="session-menu-head">
              <strong>历史对话</strong>
              <small>点击恢复,最近优先</small>
            </div>
            <div v-if="sessionsLoading" class="session-menu-empty">加载中…</div>
            <div v-else-if="!sessions.length" class="session-menu-empty">暂无历史会话</div>
            <div
              v-for="item in sessions"
              v-else
              :key="item.session_id"
              class="session-menu-row"
            >
              <button
                class="session-menu-item"
                :class="{ active: item.session_id === sessionId }"
                type="button"
                @click="restoreSession(item.session_id)"
              >
                <span class="session-item-title">{{ item.title }}</span>
                <small class="session-item-time">{{ relativeTime(item.updated_at) }}</small>
              </button>
              <button
                class="session-delete-btn"
                type="button"
                title="删除对话"
                :disabled="sending || restoring"
                @click.stop="removeSession(item)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 消息流:对话即工作台 -->
      <div ref="listEl" class="chat-list" @scroll="onListScroll">
        <div v-if="!messages.length" class="chat-hero">
          <span class="hero-kicker">MEALFLOW AI KITCHEN</span>
          <h2>{{ timeGreeting }}</h2>
          <p>把今天想吃什么交给我。人数、预算、冰箱库存和饮食限制，我会一起考虑，给你一套能直接开火的方案。</p>
          <div class="hero-chips">
            <el-button size="small" round @click="ask('明天中午想吃辣子鸡,我们俩,预算 60 块')">
              <span class="chip-icon">✦</span>明天中午想吃辣子鸡 · 2 人 · 60 元
            </el-button>
            <el-button size="small" round @click="ask('晚上吃点清淡的')">今晚吃点清淡的</el-button>
            <el-button size="small" round @click="ask('看看冰箱里有什么适合今天吃的')">看看冰箱里有什么</el-button>
          </div>
        </div>

        <template v-for="bubble in messages" :key="bubble.id">
          <!-- 用户消息:右对齐气泡 -->
          <div v-if="bubble.role === 'user'" class="msg-row user">
            <div class="user-bubble">{{ bubble.content }}</div>
          </div>

          <!-- Agent 消息:思考直播 → 步骤 → 回答 → 方案卡 → 反问 -->
          <div v-else class="msg-row assistant">
            <div class="assistant-block">
              <div
                v-if="bubble.streaming && !bubble.thinking && !bubble.steps.length"
                class="thinking-line"
              >
                <span class="spinner"></span>
              </div>

              <!-- 思考过程:LLM 为真实思维链,规则分支为真实执行步骤;流式自动展开,完成收起(菜单列表保持展开) -->
              <div v-if="bubble.thinking" class="thinking-box">
                <button class="thinking-toggle" type="button" @click="bubble.thinkingOpen = !bubble.thinkingOpen">
                  <span>{{ bubble.streaming && !bubble.thinkingDone ? '✦ 正在思考' : '✦ 思考过程' }}</span>
                  <el-icon class="thinking-chev" :class="{ open: bubble.thinkingOpen }"><ArrowDown /></el-icon>
                </button>
                <pre v-show="bubble.thinkingOpen" class="thinking-text">{{ bubble.thinking }}</pre>
              </div>

              <!-- 思索步骤只在流式期间展示,回答完成后全部路由隐藏 -->
              <ol v-if="bubble.streaming && bubble.steps.length" class="tool-steps">
                <li
                  v-for="(stepItem, index) in bubble.steps"
                  :key="index"
                  :class="{ running: stepItem.state === 'running' }"
                >
                  <template v-if="stepItem.state === 'running'">
                    <span class="mini-spinner"></span>
                    <span class="running-label">{{ stepLabel(stepItem) }}…</span>
                  </template>
                  <template v-else>
                    <span class="step-check"><el-icon><Check /></el-icon></span>
                    <span class="step-name">{{ stepLabel(stepItem) }}</span>
                    <small v-if="stepItem.detail" class="step-detail">{{ stepItem.detail }}</small>
                  </template>
                </li>
              </ol>

              <div
                v-if="bubble.streaming && !bubble.content && !bubble.error && (bubble.thinkingDone || allStepsDone(bubble))"
                class="response-placeholder"
              >
                <span class="response-placeholder-dot"></span>
                <span>{{ allStepsDone(bubble) ? '食材与约束检查已完成，正在整理建议…' : '正在整理用餐建议，回复即将呈现…' }}</span>
              </div>


              <div v-if="bubble.content" class="assistant-text" v-html="renderMarkdown(bubble.content)"></div>
              <p v-if="bubble.stopped" class="stopped-note">⏹ 已停止生成，以上为已输出的内容</p>
              <p v-if="bubble.error" class="error-message">{{ bubble.error }}</p>

              <!-- 食材模糊查询:候选菜列表(仅标注忌口/过敏,不过滤),点击展开做法 -->
              <div v-if="bubble.candidates?.length" class="candidate-card">
                <div class="candidate-card-head">
                  <strong>与「{{ (bubble.candidatesQuery ?? '').slice(0, 30) }}」相关的菜谱</strong>
                  <small>共 {{ bubble.candidates.length }} 道 · 点击查看做法</small>
                </div>
                <div class="candidate-items">
                  <div v-for="item in bubble.candidates" :key="item.recipe_id" class="candidate-row">
                    <button
                      class="candidate-item"
                      :class="{ expanded: expandedDish === item.name }"
                      @click="openCandidate(item)"
                    >
                      <span class="candidate-line-top">
                        <span class="candidate-name">{{ item.name }}</span>
                        <span class="candidate-tags">
                          <span v-if="item.expiring" class="candidate-tag expiring">临期优先</span>
                          <span v-if="item.conflict_level === 'forbidden'" class="candidate-tag forbidden">
                            ⚠ {{ item.conflict_summary }}
                          </span>
                          <span v-else-if="item.conflict_level === 'warn'" class="candidate-tag warn">
                            {{ item.conflict_summary }}
                          </span>
                        </span>
                      </span>
                      <span class="candidate-line-sub">
                        <small class="candidate-ings">{{ item.ingredients_summary }}</small>
                        <small v-if="item.used_fridge?.length" class="candidate-fridge">
                          用冰箱：{{ fridgeUsageText(item) }}
                        </small>
                        <small v-if="item.missing?.length" class="candidate-missing">
                          缺：{{ item.missing.join('、') }}
                        </small>
                      </span>
                    </button>
                    <div
                      v-if="expandedDish === item.name && recipeCache[item.name]"
                      class="recipe-detail"
                    >
                      <div class="recipe-meta">
                        {{ recipeCache[item.name].duration_minutes }} 分钟 ·
                        {{ recipeCache[item.name].kcal_per_serving ?? '—' }} kcal/份 ·
                        {{ recipeCache[item.name].source_name }}
                      </div>
                      <ol>
                        <li
                          v-for="(step, stepIndex) in recipeCache[item.name].steps"
                          :key="stepIndex"
                        >
                          {{ step }}
                        </li>
                      </ol>
                      <table>
                        <thead>
                          <tr><th>食材</th><th>用量</th><th>冰箱</th><th>参考价</th></tr>
                        </thead>
                        <tbody>
                          <tr v-for="row in recipeCache[item.name].ingredients" :key="row.key">
                            <td>{{ row.name }}</td>
                            <td>{{ row.quantity }}{{ row.unit }}</td>
                            <td>{{ row.available ?? 0 }}{{ row.unit }}</td>
                            <td>{{ row.reference_price ? `¥${row.reference_price}/${row.unit}` : '—' }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 本地库未命中:实时搜索到的网络菜谱(下厨房,仅食材清单与步骤梗概) -->
              <div v-if="bubble.webRecipes?.length" class="candidate-card web-recipe-card">
                <div class="candidate-card-head">
                  <strong>实时搜索「{{ bubble.webQuery }}」的网络菜谱</strong>
                  <small>来源：下厨房 · 点击标题查看完整做法</small>
                </div>
                <div class="web-recipe-list">
                  <div v-for="item in bubble.webRecipes" :key="item.url" class="web-recipe-item">
                    <a
                      class="web-recipe-name"
                      :href="item.url"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {{ item.title }}
                      <small v-if="item.rating" class="web-recipe-stats">
                        ★{{ item.rating }} · {{ item.cooked_count }} 人做过
                      </small>
                    </a>
                    <p class="web-recipe-ing">食材：{{ item.ingredients }}</p>
                    <details v-if="item.steps_brief.length" class="web-recipe-steps">
                      <summary>做法梗概（{{ item.steps_brief.length }} 步）</summary>
                      <ol>
                        <li v-for="(step, stepIndex) in item.steps_brief" :key="stepIndex">
                          {{ step }}
                        </li>
                      </ol>
                    </details>
                  </div>
                </div>
                <div class="web-recipe-foot">
                  <a
                    :href="`https://www.xiachufang.com/search/?keyword=${encodeURIComponent(bubble.webQuery ?? '')}`"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    在下厨房查看更多「{{ bubble.webQuery }}」↗
                  </a>
                  <small>网络菜谱为通用做法，未适配忌口与库存，请自行调整。</small>
                </div>
              </div>

              <div v-if="bubble.searchQuery && !bubble.streaming" class="external-recipe">
                <a :href="`https://www.xiachufang.com/search/?keyword=${encodeURIComponent(bubble.searchQuery)}`" target="_blank" rel="noopener noreferrer">
                  去下厨房搜索「{{ bubble.searchQuery }}」↗
                </a>
                <small>外部菜谱为通用做法，未适配你的忌口与体质，请自行调整。</small>
              </div>

              <!-- 方案卡:出现在对话流内,决策依据一并融入 -->
              <article v-if="bubble.plan" class="plan-card">
                <div class="plan-head">
                  <el-radio-group v-model="bubble.selectedStrategy" size="small">
                    <el-radio-button
                      v-for="(option, optionIndex) in bubble.plan.options"
                      :key="option.strategy"
                      :value="option.strategy"
                    >
                      {{ optionIndex === 0 ? '★ ' : '' }}{{ option.title }}
                    </el-radio-button>
                  </el-radio-group>
                  <strong class="plan-cost">
                    {{
                      money(
                        bubble.plan.options.find((o) => o.strategy === bubble.selectedStrategy)
                          ?.estimated_cost_cents,
                      )
                    }}
                  </strong>
                </div>

                <template v-for="option in bubble.plan.options" :key="option.strategy">
                  <div v-if="option.strategy === bubble.selectedStrategy" class="plan-body">
                    <p class="strategy-summary">当前：{{ option.title }} · {{ strategySummary(option.strategy) }}</p>
                    <div class="plan-metrics">
                      <span>约 {{ option.estimated_kcal_per_serving ?? '—' }} kcal / 人</span>
                      <span class="divider">·</span>
                      <span>{{ bubble.plan.constraints.expected_diners ?? '—' }} 人</span>
                      <span class="divider">·</span>
                      <span>{{ bubble.plan.constraints.budget_limit_cents ? `预算差额 ${money(bubble.plan.constraints.budget_limit_cents - option.estimated_cost_cents)}` : '未设预算' }}</span>
                    </div>

                    <ul class="dish-list">
                      <li v-for="item in option.items" :key="item.name">
                        <button
                          class="dish-name"
                          @click="toggleRecipe(String(item.name), bubble.plan)"
                        >
                          {{ item.name }}
                        </button>
                        <small>{{ item.servings }} 份 · {{ item.kcal_per_serving ?? '—' }} kcal/份</small>
                        <div
                          v-if="dishWarning(bubble.plan, String(item.name))"
                          class="dish-warning"
                          :class="warningLevel(dishWarning(bubble.plan, String(item.name)))"
                        >
                          {{ dishWarning(bubble.plan, String(item.name)) }}
                        </div>
                        <div
                          v-if="expandedDish === item.name && recipeCache[item.name]"
                          class="recipe-detail"
                        >
                          <div class="recipe-meta">
                            {{ recipeCache[item.name].duration_minutes }} 分钟 ·
                            {{ recipeCache[item.name].source_name }}
                          </div>
                          <ol>
                            <li
                              v-for="(step, stepIndex) in recipeCache[item.name].steps"
                              :key="stepIndex"
                            >
                              {{ step }}
                            </li>
                          </ol>
                          <table>
                            <thead>
                              <tr><th>食材</th><th>用量</th><th>冰箱</th><th>参考价</th></tr>
                            </thead>
                            <tbody>
                              <tr v-for="row in recipeCache[item.name].ingredients" :key="row.key">
                                <td>{{ row.name }}</td>
                                <td>{{ row.quantity }}{{ row.unit }}</td>
                                <td>{{ row.available ?? 0 }}{{ row.unit }}</td>
                                <td>{{ row.reference_price ? `¥${row.reference_price}/${row.unit}` : '—' }}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </li>
                    </ul>

                    <el-collapse v-if="option.procurement_list?.length" class="proc-collapse">
                      <el-collapse-item :title="`采购缺口(${option.procurement_list.length} 项)`">
                        <ul class="proc-list">
                          <li v-for="row in option.procurement_list" :key="row.ingredient">
                            {{ row.ingredient }} 缺 {{ row.missing_quantity }}{{ row.unit }}
                          </li>
                        </ul>
                      </el-collapse-item>
                    </el-collapse>
                    <p v-else class="no-proc">冰箱现有食材就够,不用采购 👍</p>

                    <div v-if="option.pantry_notes?.length" class="pantry-notes">
                      <span>⌁</span>
                      <div>
                        <strong>常备料提醒</strong>
                        <p v-for="note in option.pantry_notes" :key="note">{{ note }}</p>
                      </div>
                    </div>

                    <div class="reason-list">
                      <span v-for="reason in option.reasons" :key="reason">{{ reason }}</span>
                    </div>
                  </div>
                </template>

                <div class="plan-foot">
                  <small>价格参考:市区大型超市公开参考价</small>
                  <RouterLink class="procurement-link" to="/admin/procurement">查看采购清单 ↗</RouterLink>
                  <el-button type="primary" :disabled="sending" @click="confirmPlan(bubble)">
                    确认这套,生成采购清单
                  </el-button>
                </div>
              </article>

              <div v-if="bubble.questions.length && !bubble.streaming" class="chip-row">
                <el-button
                  v-for="question in bubble.questions"
                  :key="question"
                  size="small"
                  round
                  @click="ask(question)"
                >
                  {{ question }}
                </el-button>
              </div>
            </div>

          </div>
        </template>
      </div>

      <!-- 底部输入区:ChatGPT 式 -->
      <div class="chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="2000"
          placeholder="今天想吃什么，告诉我就好…&#10;例如：明天中午想吃辣子鸡，清淡一些，预算 60 元&#10;我会结合用餐人员、家庭偏好与冰箱食材，为你安排一餐"
          :disabled="sending"
          @keydown.enter.exact.prevent="send()"
        />
        <div class="input-actions">
          <div ref="dinerSelectorEl" class="diner-selector" :class="{ open: dinerPickerOpen }">
            <button class="diner-selector-trigger" type="button" @click.stop="dinerPickerOpen = !dinerPickerOpen">
              <span class="diner-selector-leading"><el-icon><User /></el-icon></span>
              <span class="diner-selector-copy">
                <strong>本次用餐人员</strong>
                <small>{{ dinerSummary }} · 默认勾选常驻成员</small>
              </span>
              <span class="diner-selector-count">{{ selectedDiners.length }} 人</span>
              <span class="diner-selector-chevron">{{ dinerPickerOpen ? '⌃' : '⌄' }}</span>
            </button>
            <div v-if="dinerPickerOpen" class="diner-picker" @pointerdown.stop>
              <div class="diner-picker-head">
                <strong>这顿饭谁来吃？</strong>
                <small>所选人员与人数将随需求发送；当前规划仍读取全家约束</small>
              </div>
              <el-checkbox-group v-model="selectedDinerIds" class="diner-options">
                <el-checkbox
                  v-for="member in household?.members ?? []"
                  :key="member.user_id"
                  :value="member.user_id"
                  border
                  :disabled="sending"
                >
                  <span>{{ member.display_name }}</span>
                  <small>{{ member.residency === 'resident' ? '常驻' : '访客' }}</small>
                </el-checkbox>
              </el-checkbox-group>
              <p v-if="!household" class="diner-load-hint">家庭档案暂未加载，请重试。</p>
              <el-button v-if="!household" size="small" text @click="loadHousehold">重新加载</el-button>
              <div class="diner-picker-foot">
                <span>已选择 {{ selectedDiners.length }} 人</span>
                <el-button size="small" type="primary" @click="dinerPickerOpen = false">完成选择</el-button>
              </div>
            </div>
          </div>
          <el-button
            v-if="!sending"
            type="primary"
            round
            :disabled="input.trim().length < 2 || (household !== null && !selectedDiners.length)"
            @click="send()"
          >
            发送 ⏎
          </el-button>
          <el-button v-else class="stop-btn" round @click="stopGeneration">⏹ 停止生成</el-button>
        </div>
      </div>
    </div>

  </section>
</template>

<style scoped>
.workbench {
  height: calc(100vh - 132px);
  display: flex;
  justify-content: center;
}
.chat-panel {
  width: 100%;
  max-width: 880px;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  min-height: 0;
}
/* ===== 会话栏:新建 + 历史下拉(diner-selector 同语言) ===== */
.session-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.new-session-btn {
  flex-shrink: 0;
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  color: var(--green);
  font-size: 12.5px;
  font-weight: 650;
  transition: 0.15s ease;
}
.new-session-btn:hover:not(:disabled) {
  border-color: var(--green-2);
  transform: translateY(-1px);
}
.new-session-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.session-menu { position: relative; flex: 1; min-width: 0; }
.session-menu-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 13px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.session-menu-trigger:hover { border-color: var(--green-2); }
.session-menu.open .session-menu-trigger { border-color: var(--green-2); }
.session-menu-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}
.session-menu-chevron { color: var(--muted); font-size: 12px; flex-shrink: 0; }
.session-menu-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 60;
  max-height: 320px;
  overflow-y: auto;
  padding: 6px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 14px 38px rgba(33, 60, 54, 0.13);
}
.session-menu-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 8px 8px;
  border-bottom: 1px solid #eef2ef;
  margin-bottom: 4px;
}
.session-menu-head strong { font-size: 12.5px; color: var(--ink); }
.session-menu-head small { color: var(--muted); font-size: 11px; }
.session-menu-empty {
  padding: 18px 8px;
  text-align: center;
  color: var(--muted);
  font-size: 12.5px;
}
.session-menu-row {
  display: flex;
  align-items: center;
  gap: 2px;
}
.session-menu-row .session-menu-item { flex: 1; min-width: 0; }
.session-menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: none;
  text-align: left;
  cursor: pointer;
  transition: background 0.14s ease;
}
.session-menu-item:hover { background: #f1f7f3; }
.session-menu-item.active { background: #e7f2ee; }
.session-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ink);
}
.session-menu-item.active .session-item-title { color: var(--green); font-weight: 650; }
.session-item-time { flex-shrink: 0; color: var(--muted); font-size: 11px; }
/* 悬浮渐显的删除小按钮(与消息复制按钮同一动画语言) */
.session-delete-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-right: 4px;
  border: 0;
  border-radius: 7px;
  background: none;
  color: var(--muted);
  cursor: pointer;
  opacity: 0;
  transform: translateX(3px);
  transition: opacity 0.22s ease, transform 0.22s ease, color 0.15s ease, background 0.15s ease;
}
.session-menu-row:hover .session-delete-btn {
  opacity: 1;
  transform: translateX(0);
}
.session-delete-btn:hover:not(:disabled) { background: #fdeceb; color: #a43c36; }
.session-delete-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.household-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.5rem 0.85rem;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid var(--border);
  border-radius: 14px;
}
.strip-left { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.member-card {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
}
.member-card strong { font-size: 13px; }
.strip-right { display: flex; gap: 0.4rem; }
.chat-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 0.4rem 14px 0.4rem 0.2rem;
  scrollbar-gutter: stable;
}
.chat-list::-webkit-scrollbar { width: 8px; }
.chat-list::-webkit-scrollbar-track { background: transparent; }
.chat-list::-webkit-scrollbar-thumb {
  background: #d5ddd8;
  border-radius: 8px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.chat-list::-webkit-scrollbar-thumb:hover { background-color: #b9c6c0; }
.chat-hero {
  margin: auto;
  text-align: center;
  max-width: 660px;
  padding: 2.6rem 1rem;
}
.hero-kicker {
  display: inline-block;
  margin-bottom: 12px;
  color: var(--green-2);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .18em;
}
.chat-hero h2 {
  font-family: Georgia, 'Songti SC', serif;
  font-size: 32px;
  margin-bottom: 0.5rem;
  color: var(--ink);
}
.chat-hero p { max-width: 560px; color: var(--muted); margin: 0 auto 1.25rem; line-height: 1.8; }
.hero-chips { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; }
.hero-chips .el-button { border-color: #d6e4de; background: rgba(255,255,255,.82); color: var(--green); }
.hero-chips .el-button:hover { border-color: var(--green-2); background: #f3f8f5; }
.chip-icon { margin-right: 4px; color: var(--gold); }
.msg-row { display: flex; }
.stopped-note { margin: 6px 0 0; color: var(--muted); font-size: 12px; }
.msg-row.user { justify-content: flex-end; }
.user-bubble {
  max-width: 78%;
  padding: 0.7rem 1rem;
  border-radius: 16px 16px 4px 16px;
  background: #0f4c45;
  color: #fff;
  line-height: 1.6;
  font-size: 14.5px;
}
.assistant-block {
  width: 100%;
  padding: 0.1rem 0.2rem;
}
.thinking-line {
  margin-bottom: 0.5rem;
  font-size: 12.5px;
  color: #7a8a86;
}
.thinking-line.done { color: #9aa8a4; }
.thinking-box {
  margin-bottom: 0.5rem;
  font-size: 12.5px;
  color: #7a8a86;
}
.thinking-chev {
  margin-left: 4px;
  vertical-align: -2px;
  transition: transform 0.18s ease;
}
.thinking-chev.open { transform: rotate(180deg); }
.thinking-toggle {
  border: 0;
  background: none;
  padding: 0;
  color: inherit;
  font-size: 12.5px;
  cursor: pointer;
  font-weight: 600;
}
.thinking-toggle:hover { color: #1f7a6d; }
.thinking-text {
  white-space: pre-wrap;
  opacity: 0.75;
  max-height: 110px;
  overflow-y: auto;
  border-left: 2px solid #d8e4e0;
  padding-left: 0.55rem;
  margin-top: 0.35rem;
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 0.55; } 50% { opacity: 0.95; } }
.spinner {
  display: inline-block;
  width: 13px;
  height: 13px;
  border: 2px solid #cfdad6;
  border-top-color: #0f4c45;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 0.65rem;
  vertical-align: -2px;
}
.thinking-live {
  font-weight: 600;
  background: linear-gradient(90deg, #9aa8a4 20%, #1f7a6d 50%, #9aa8a4 80%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: shimmer 1.8s linear infinite;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@keyframes spin { to { transform: rotate(360deg); } }
.tool-steps {
  list-style: none;
  margin: 0 0 0.65rem;
  padding: 0;
  font-size: 12.5px;
  color: #0f4c45;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.tool-steps li {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  line-height: 1.55;
}
.tool-steps li.running {
  color: #1f7a6d;
  background: #eef5f2;
  border-radius: 8px;
  padding: 4px 10px;
  align-items: center;
}
.running-label {
  background: linear-gradient(90deg, #1f7a6d 20%, #6fbfae 50%, #1f7a6d 80%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: shimmer 1.6s linear infinite;
  font-weight: 600;
}
.mini-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid #cfdad6;
  border-top-color: #1f7a6d;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  margin-right: 6px;
  vertical-align: -1px;
}
.step-check {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #e3f1ec;
  color: #1f7a6d;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}
.step-check :deep(.el-icon) { font-size: 10px; }
.step-name { font-weight: 600; }
.step-detail { color: #8ba39d; }
.assistant-text { line-height: 1.75; font-size: 14.5px; }
.assistant-text :deep(strong) { color: var(--green); font-weight: 750; }
.external-recipe { display: grid; gap: 4px; margin-top: 10px; padding: 10px 12px; border: 1px solid #dce9e3; border-radius: 10px; background: #f7fbf8; }
.external-recipe a { color: var(--green); font-size: 13px; font-weight: 700; text-decoration: none; }
.external-recipe a:hover { text-decoration: underline; }
.external-recipe small { color: var(--muted); font-size: 11px; }
.chip-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.6rem; }
.plan-card {
  margin-top: 0.8rem;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 0.9rem 1rem;
  background: linear-gradient(145deg, #fff 0%, #fbfdfb 100%);
  box-shadow: 0 8px 24px rgba(33, 60, 54, .05);
}
.response-placeholder {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0.15rem 0 0.75rem;
  padding: 9px 13px;
  border: 1px solid #dce9e3;
  border-radius: 11px;
  background: linear-gradient(90deg, #f6faf8, #fff);
  color: #6f817b;
  font-size: 12.5px;
  animation: response-in .24s ease-out;
}
.response-placeholder-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--green-2);
  box-shadow: 0 0 0 5px rgba(23,114,103,.1);
  animation: response-pulse 1.25s ease-in-out infinite;
}
@keyframes response-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@keyframes response-pulse { 0%, 100% { opacity: .42; } 50% { opacity: 1; } }
.plan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}
.plan-cost { font-size: 19px; font-family: Georgia, serif; }
.plan-body { border-top: 1px dashed var(--border); padding-top: 0.6rem; }
.strategy-summary { margin: 0 0 0.55rem; padding: 6px 9px; border-radius: 8px; background: #f3f8f5; color: var(--green); font-size: 12px; }
.plan-metrics { font-size: 13px; color: var(--muted); margin-bottom: 0.55rem; }
.plan-metrics .divider { margin: 0 0.4rem; }
.dish-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.dish-name {
  border: 0;
  background: none;
  padding: 0;
  font-weight: 650;
  color: var(--ink);
  cursor: pointer;
  text-decoration: underline dotted;
  font-size: 14.5px;
}
.dish-list small { color: var(--muted); margin-left: 0.4rem; }
.dish-warning {
  font-size: 12px;
  padding: 4px 9px;
  border-radius: 8px;
  margin-top: 0.3rem;
}
.dish-warning.warn { background: #fdf3e0; color: #8a5a12; }
.dish-warning.forbidden { background: #fdeceb; color: #a43c36; }
.recipe-detail {
  margin-top: 0.45rem;
  padding: 0.6rem 0.7rem;
  background: #f6faf8;
  border-radius: 10px;
  font-size: 13px;
}
.recipe-meta { color: var(--muted); margin-bottom: 0.3rem; }
.recipe-detail ol { margin: 0 0 0.4rem 1.1rem; }
.recipe-detail table { width: 100%; font-size: 12px; }
.proc-collapse { margin: 0.55rem 0 0; }
.proc-collapse :deep(.el-collapse-item__header) { font-weight: 600; color: #0f4c45; }
.proc-list { margin: 0; padding-left: 1.1rem; font-size: 13px; color: var(--ink); }
.no-proc { font-size: 13px; color: var(--muted); margin-top: 0.5rem; }
.pantry-notes {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  margin-top: 0.6rem;
  padding: 8px 10px;
  border: 1px solid #e8dfc7;
  border-radius: 9px;
  background: #fffaf0;
  color: #866b31;
  font-size: 12px;
}
.pantry-notes > span { color: #c58d2d; font-size: 17px; line-height: 1; }
.pantry-notes strong { display: block; margin-bottom: 2px; }
.pantry-notes p { margin: 0; line-height: 1.55; }
.reason-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 12px;
  color: var(--muted);
  margin-top: 0.55rem;
}
.plan-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.75rem;
  padding-top: 0.6rem;
  border-top: 1px dashed var(--border);
}
.plan-foot small { color: #9aa8a4; }
/* ===== 食材模糊查询:候选菜列表卡(与方案卡同视觉语言,仅标注不过滤) ===== */
.candidate-card {
  margin-top: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: linear-gradient(145deg, #fff, #fbfdfb);
  box-shadow: 0 8px 24px rgba(33, 60, 54, 0.05);
  overflow: hidden;
}
/* 实时搜索的网络菜谱卡(下厨房):样式基调与候选卡一致 */
.web-recipe-list { display: grid; }
.web-recipe-item { padding: 0.65rem 0.95rem; display: grid; gap: 5px; }
.web-recipe-item + .web-recipe-item { border-top: 1px solid #f0f4f1; }
.web-recipe-name {
  color: #21403a; font-size: 13.5px; font-weight: 700;
  text-decoration: none; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
}
.web-recipe-name:hover { color: var(--green); text-decoration: underline; }
.web-recipe-stats { color: #a2701d; font-size: 11px; font-weight: 600; }
.web-recipe-ing { margin: 0; font-size: 12.5px; color: #3d524c; }
.web-recipe-steps { font-size: 12.5px; color: #3d524c; }
.web-recipe-steps summary { cursor: pointer; color: var(--muted); font-size: 12px; }
.web-recipe-steps ol { margin: 6px 0 0; padding-left: 22px; display: grid; gap: 4px; }
.web-recipe-foot {
  display: grid; gap: 3px; padding: 0.6rem 0.95rem;
  border-top: 1px solid #eef4f0; background: #f7fbf8;
}
.web-recipe-foot a { color: var(--green); font-size: 12.5px; font-weight: 700; text-decoration: none; }
.web-recipe-foot a:hover { text-decoration: underline; }
.web-recipe-foot small { color: var(--muted); font-size: 11px; }
.candidate-card-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.6rem;
  padding: 0.6rem 0.95rem 0.5rem;
  border-bottom: 1px solid #eef4f0;
}
.candidate-card-head strong { font-size: 13.5px; color: var(--green); }
.candidate-card-head small { color: var(--muted); font-size: 11.5px; }
.candidate-items { display: grid; }
.candidate-row + .candidate-row { border-top: 1px solid #f0f4f1; }
.candidate-item {
  width: 100%;
  display: block;
  padding: 0.55rem 0.95rem;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}
.candidate-item:hover { background: #f4faf7; }
.candidate-item.expanded { background: #eef7f2; }
.candidate-line-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.55rem;
}
.candidate-name {
  flex-shrink: 0;
  font-weight: 650;
  font-size: 14px;
  color: var(--ink);
  white-space: nowrap;
}
.candidate-item:hover .candidate-name { color: var(--green-2); }
.candidate-line-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem 0.7rem;
  margin-top: 3px;
}
.candidate-ings {
  color: var(--muted);
  font-size: 12px;
}
.candidate-fridge { color: #0f6b4f; font-size: 12px; }
.candidate-missing { color: #a15b21; font-size: 12px; }
.candidate-tags { display: flex; gap: 5px; flex-shrink: 0; }
.candidate-tag {
  padding: 2.5px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.candidate-tag.forbidden { background: #fdeceb; color: #a43c36; }
.candidate-tag.warn { background: #fdf3e0; color: #8a5a12; }
.candidate-tag.expiring { background: #e7f2ee; color: #0f6b4f; }
.candidate-row .recipe-detail { margin: 0 0.95rem 0.6rem; }
.chat-input {
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: #fff;
  padding: 0.6rem 0.7rem 0.5rem;
  box-shadow: 0 6px 24px rgba(33, 60, 54, 0.07);
}
.diner-selector {
  position: relative;
  width: 330px;
  flex: 0 0 330px;
  margin-top: 0;
}

.diner-selector-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 0;
  background: transparent;
  padding: 4px 4px 3px;
  color: var(--ink);
  text-align: left;
}
.diner-selector-trigger:hover { color: var(--green); }
.diner-selector-leading {
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: #e9f3ef;
  color: var(--green);
}
.diner-selector-copy { flex: 1; display: grid; gap: 1px; }
.diner-selector-copy strong { font-size: 12px; }
.diner-selector-copy small { color: var(--muted); font-size: 11px; }
.diner-selector-count,
.diner-selector-chevron {
  height: 27px;
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
.diner-selector-count { color: var(--green); font-size: 12px; font-weight: 700; white-space: nowrap; }
.diner-selector-chevron {
  width: 18px;
  flex: 0 0 18px;
  justify-content: center;
  color: #8da09a;
  font-size: 15px;
  font-weight: 700;
}
.diner-picker {
  position: absolute;
  z-index: 10;
  right: 0;
  bottom: calc(100% + 9px);
  width: min(390px, 100%);
  padding: 14px;
  border: 1px solid #d8e5df;
  border-radius: 14px;
  background: rgba(255,255,255,.98);
  box-shadow: 0 16px 38px rgba(28,65,57,.16);
}
.diner-picker-head { display: grid; gap: 3px; margin-bottom: 11px; }
.diner-picker-head strong { font-size: 13px; }
.diner-picker-head small { color: var(--muted); font-size: 11px; }
.diner-options { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.diner-options { max-height: 180px; overflow-y: auto; }
.diner-load-hint { font-size: 12px; color: var(--muted); }
.diner-options :deep(.el-checkbox) { width: 100%; margin: 0; padding: 8px 10px; border-radius: 9px; }
.diner-options :deep(.el-checkbox__label) { display: flex; align-items: center; justify-content: space-between; flex: 1; gap: 8px; font-size: 12px; }
.diner-options :deep(.el-checkbox__label small) { color: var(--muted); font-size: 10px; }
.diner-picker-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; color: var(--muted); font-size: 11px; }
.procurement-link { margin-left: auto; font-size: 12px; color: var(--green); text-decoration: none; white-space: nowrap; }
.procurement-link:hover { text-decoration: underline; }
@media (prefers-reduced-motion: reduce) {
  .response-placeholder, .response-placeholder-dot, .thinking-live { animation: none; }
}
.chat-input :deep(.el-textarea__inner) {
  font-size: 14.5px;
  line-height: 1.6;
  border-radius: 10px;
  box-shadow: none;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 0.4rem;
}
.error-message { margin-top: 0.4rem; }
</style>
