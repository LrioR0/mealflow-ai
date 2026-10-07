import { apiRequest } from './client'
import { sseStream, type SseEvent } from './sseClient'
import type { AgentRun } from '../types/agent'

// 独立新文件:src/api 下旧 *.js 编译产物会先于同名 .ts 被解析,新增函数不要写进 agent.ts

export interface HouseholdRestriction {
  id: string
  user_id: string | null
  type: string
  ingredient_key: string
  ingredient_name: string
}

export interface HouseholdMember {
  user_id: string
  display_name: string
  role: string
  gender: string | null
  residency: string
  taboo: string | null
  note: string | null
  restrictions: HouseholdRestriction[]
}

export interface HouseholdEvent {
  id: string
  user_id: string
  member_name: string
  event_type: string
  constraint_tags: string[]
  start_date: string
  end_date: string
  note: string | null
}

export interface Household {
  workspace_id: string
  members: HouseholdMember[]
  events: HouseholdEvent[]
}

export interface ChatStreamRequest {
  session_id: string | null
  workspace_id?: string
  site_id?: string
  meal_service_id?: string
  diners_user_ids?: string[]
  message: string
}

export interface ChatPlanEvent extends AgentRun {}

export interface ChatMessageView {
  id: string
  role: 'user' | 'assistant' | string
  content: string
  thinking_text: string | null
  run_id: string | null
}

export interface ChatSessionView {
  session_id: string
  title: string
  messages: ChatMessageView[]
}

export interface ChatSessionSummary {
  session_id: string
  title: string
  updated_at: string
}

export function fetchChatSessions(workspaceId = 'home-workspace'): Promise<ChatSessionSummary[]> {
  return apiRequest(`/agent/chat/sessions?workspace_id=${encodeURIComponent(workspaceId)}`)
}

export function fetchChatSession(sessionId: string): Promise<ChatSessionView> {
  return apiRequest(`/agent/chat/${sessionId}`)
}

export function deleteChatSession(sessionId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/agent/chat/${sessionId}`, { method: 'DELETE' })
}

export function fetchHousehold(): Promise<Household> {
  return apiRequest('/household')
}

export function createHouseholdEvent(payload: {
  user_id: string
  event_type: string
  constraint_tags?: string[]
  start_date: string
  end_date: string
  note?: string | null
}): Promise<Household> {
  return apiRequest('/household/events', { method: 'POST', body: JSON.stringify(payload) })
}

export function deleteHouseholdEvent(eventId: string): Promise<void> {
  return apiRequest(`/household/events/${eventId}`, { method: 'DELETE' })
}

export interface RecipeDetail {
  id: string
  name: string
  servings: number
  duration_minutes: number
  kcal_per_serving: number | null
  estimated_cost_cents: number | null
  tags: string[]
  taste_tags: string[]
  allergens: string[]
  steps: string[]
  source_name: string
  ingredients: Array<{
    key: string
    name: string
    quantity: number
    unit: string
    optional: boolean
    available: number | null
    reference_price: number | null
    price_source: string | null
  }>
}

export function fetchRecipeDetail(recipeId: string, diners?: number): Promise<RecipeDetail> {
  const query = diners ? `?diners=${diners}` : ''
  return apiRequest(`/recipes/${recipeId}${query}`)
}

export function streamChat(
  request: ChatStreamRequest,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  return sseStream('/api/v1/agent/chat/stream', request, signal)
}
