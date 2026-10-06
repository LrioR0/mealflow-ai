import { apiRequest } from './client'
import { fetchHousehold, type Household } from './chat'

export type Residency = 'resident' | 'guest'
export type RestrictionType = 'allergy' | 'dislike'

export const HOME_WORKSPACE_ID = 'home-workspace'

export interface MemberPayload {
  display_name: string
  gender?: string | null
  residency: Residency
  taboo?: string | null
  note?: string | null
}

export interface RestrictionPayload {
  user_id: string
  type: RestrictionType
  ingredient_key: string
  workspace_id?: string
}

export interface MemberEventPayload {
  user_id: string
  event_type: string
  constraint_tags?: string[]
  start_date: string
  end_date: string
  note?: string | null
  workspace_id?: string
}

export function createMember(payload: MemberPayload): Promise<Household> {
  return apiRequest('/household/members', {
    method: 'POST',
    body: JSON.stringify({ workspace_id: HOME_WORKSPACE_ID, ...payload }),
  })
}

export function updateMember(
  userId: string,
  payload: Partial<MemberPayload>,
): Promise<Household> {
  return apiRequest(`/household/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteMember(userId: string): Promise<Household> {
  await apiRequest(`/household/members/${userId}`, { method: 'DELETE' })
  return fetchHousehold()
}

/** 红线/忌口(永久档案):过敏为硬过滤,忌口为规避 */
export function createRestriction(payload: RestrictionPayload): Promise<Household> {
  return apiRequest('/household/restrictions', {
    method: 'POST',
    body: JSON.stringify({ workspace_id: HOME_WORKSPACE_ID, ...payload }),
  })
}

export async function deleteRestriction(restrictionId: string): Promise<Household> {
  await apiRequest(`/household/restrictions/${restrictionId}`, { method: 'DELETE' })
  return fetchHousehold()
}

/** 特殊事件(带生效期):仅日期窗口内生效,不写入长期档案 */
export function createMemberEvent(payload: MemberEventPayload): Promise<Household> {
  return apiRequest('/household/events', {
    method: 'POST',
    body: JSON.stringify({ workspace_id: HOME_WORKSPACE_ID, ...payload }),
  })
}

export async function deleteMemberEvent(eventId: string): Promise<Household> {
  await apiRequest(`/household/events/${eventId}`, { method: 'DELETE' })
  return fetchHousehold()
}
