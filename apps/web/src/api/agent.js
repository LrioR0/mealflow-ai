import { apiRequest } from './client';
export function createAgentRun(requestText) {
    return apiRequest('/agent/runs', {
        method: 'POST',
        body: JSON.stringify({
            workspace_id: 'demo-workspace',
            site_id: 'demo-site',
            meal_service_id: 'demo-lunch',
            request_text: requestText,
        }),
    });
}
export function reviseAgentRun(runId, expectedDiners) {
    return apiRequest(`/agent/runs/${runId}/revise`, {
        method: 'POST',
        body: JSON.stringify({ expected_diners: expectedDiners }),
    });
}
