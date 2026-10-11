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

export interface FoodPreference {
  id: string
  user_id: string
  target_type: 'dish' | 'ingredient'
  target_key: string
  target_name: string
  preference: 'like' | 'dislike'
  source: 'profile' | 'conversation'
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
  food_preferences: FoodPreference[]
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

export interface PantryConfig {
  workspace_id: string
  use_defaults: boolean
  disabled_default_keys: string[]
  custom_keys: string[]
  effective_keys: string[]
  effective_items: Array<{ key: string; label: string; is_custom: boolean }>
}

export interface ChatStreamRequest {
  session_id: string | null
  workspace_id?: string
  site_id?: string
  meal_service_id?: string
  diners_user_ids?: string[]
  model_id?: string
  message: string
}

export interface ChatModel {
  id: string
  label: string
  provider: string
  enabled: boolean
  default: boolean
  is_free: boolean
  supports_tools: boolean
  supports_stream: boolean
  use_case: string
  reason: string | null
}

export function fetchChatModels(): Promise<ChatModel[]> {
  return apiRequest('/agent/chat/models')
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

export function fetchChatSessionCount(
  workspaceId = 'home-workspace',
  excludeSessionId?: string | null,
): Promise<{ count: number }> {
  const query = new URLSearchParams({ workspace_id: workspaceId })
  if (excludeSessionId) query.set('exclude_session_id', excludeSessionId)
  return apiRequest(`/agent/chat/sessions/count?${query.toString()}`)
}

export function fetchChatSession(sessionId: string): Promise<ChatSessionView> {
  return apiRequest(`/agent/chat/${sessionId}`)
}

export function deleteChatSession(sessionId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/agent/chat/${sessionId}`, { method: 'DELETE' })
}

export interface DeleteChatSessionsResult {
  deleted_sessions: number
  deleted_messages: number
}

export function deleteChatSessions(
  workspaceId = 'home-workspace',
  excludeSessionId?: string | null,
): Promise<DeleteChatSessionsResult> {
  const query = new URLSearchParams({ workspace_id: workspaceId })
  if (excludeSessionId) query.set('exclude_session_id', excludeSessionId)
  return apiRequest(`/agent/chat/sessions?${query.toString()}`, { method: 'DELETE' })
}

export function fetchHousehold(): Promise<Household> {
  return apiRequest('/household')
}

export function fetchPantryConfig(workspaceId = 'home-workspace'): Promise<PantryConfig> {
  return apiRequest(`/household/pantry/${workspaceId}`)
}

export function updatePantryConfig(payload: Pick<PantryConfig, 'use_defaults' | 'disabled_default_keys' | 'custom_keys'>, workspaceId = 'home-workspace'): Promise<PantryConfig> {
  return apiRequest(`/household/pantry/${workspaceId}`, { method: 'PUT', body: JSON.stringify(payload) })
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

export function deleteFoodPreference(preferenceId: string): Promise<void> {
  return apiRequest(`/household/preferences/${preferenceId}`, { method: 'DELETE' })
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
