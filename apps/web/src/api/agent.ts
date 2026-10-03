import type { AgentRun } from '../types/agent'
import { apiRequest } from './client'

export function createAgentRun(requestText: string): Promise<AgentRun> {
  return apiRequest('/agent/runs', {
    method: 'POST',
    body: JSON.stringify({
      workspace_id: 'demo-workspace',
      site_id: 'demo-site',
      meal_service_id: 'demo-lunch',
      request_text: requestText,
    }),
  })
}

export function reviseAgentRun(runId: string, expectedDiners: number): Promise<AgentRun> {
  return apiRequest(`/agent/runs/${runId}/revise`, {
    method: 'POST',
    body: JSON.stringify({ expected_diners: expectedDiners }),
  })
}
