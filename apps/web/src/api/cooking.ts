import { apiRequest } from './client'

export interface CookingStepPayload {
  title: string
  detail: string
  minutes: number | null
}

export interface CookingRecordPayload {
  id?: string
  workspace_id?: string
  dish_name: string
  cook: string
  cooked_at: string
  servings: number
  duration_minutes: number
  difficulty: string
  tags: string[]
  ingredients: string
  story: string
  steps: CookingStepPayload[]
  rating: number
  next_time_note: string
  image?: string
  reviews?: Array<{ id: string; nickname: string; rating: number; content: string; createdAt: string }>
}

export function fetchCookingRecords(workspaceId = 'home-workspace'): Promise<CookingRecordPayload[]> {
  return apiRequest(`/workspaces/${workspaceId}/cooking-records`)
}

export function createCookingRecord(payload: CookingRecordPayload): Promise<CookingRecordPayload> {
  return apiRequest('/workspaces/home-workspace/cooking-records', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateCookingRecord(
  id: string,
  payload: Partial<CookingRecordPayload>,
): Promise<CookingRecordPayload> {
  return apiRequest(`/cooking-records/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteCookingRecord(id: string): Promise<void> {
  return apiRequest(`/cooking-records/${id}`, { method: 'DELETE' })
}
