import type { AgentRun } from '../types/agent'
import { apiRequest } from './client'

export function fetchLatestAgentRun(): Promise<AgentRun> {
  return apiRequest('/agent/runs/latest')
}
