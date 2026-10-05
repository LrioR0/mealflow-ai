import { apiRequest } from './client'

export interface DailyFeedbackEntry {
  rating: number
  tags: string[]
  comment: string | null
  leftover_level: string | null
  submitted_at: string
}

export interface FeedbackDigest {
  sample_count: number
  avg_rating: number | null
  top_tags: string[]
  comment_digest: string[]
}

export interface DailyFeedbackDay {
  date: string
  meal_service_id: string
  meal_service_name: string
  dishes: string[]
  feedback_count: number
  entries: DailyFeedbackEntry[] | null
  summary: FeedbackDigest | null
}

export function fetchDailyFeedback(workspaceId = 'demo-workspace'): Promise<DailyFeedbackDay[]> {
  return apiRequest(`/feedback/daily?workspace_id=${encodeURIComponent(workspaceId)}`)
}
