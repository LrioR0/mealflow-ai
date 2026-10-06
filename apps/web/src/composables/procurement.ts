import { apiRequest } from '../api/client'

export interface ProcurementItem {
  id: string
  ingredient: string
  quantity: string
  unit: string
  checked: boolean
  source: 'agent' | 'manual'
  sourceId?: string
  workspace_id?: string
  checked_at?: string | null
  createdAt?: number
}

const STORAGE_KEY = 'mealflow_procurement_v1'

export function readProcurement(): ProcurementItem[] {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    if (!Array.isArray(data)) return []
    return data.filter((item): item is ProcurementItem =>
      item && typeof item.id === 'string' && typeof item.ingredient === 'string' &&
      typeof item.quantity === 'string' && typeof item.unit === 'string' &&
      typeof item.checked === 'boolean' && ['agent', 'manual'].includes(item.source),
    )
  } catch {
    return []
  }
}

export function saveProcurement(items: ProcurementItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
}

export function fetchProcurement(workspaceId = 'home-workspace'): Promise<ProcurementItem[]> {
  return apiRequest<Array<ProcurementItem & { source_id?: string | null }>>(
    `/workspaces/${workspaceId}/procurement-items`,
  ).then((items) => items.map((item) => ({ ...item, sourceId: item.source_id ?? undefined })))
}

export function createProcurementItem(
  payload: Omit<ProcurementItem, 'id' | 'workspace_id' | 'checked_at'>,
  workspaceId = 'home-workspace',
): Promise<ProcurementItem> {
  return apiRequest(`/workspaces/${workspaceId}/procurement-items`, {
    method: 'POST',
    body: JSON.stringify({
      ingredient: payload.ingredient,
      quantity: payload.quantity,
      unit: payload.unit,
      checked: payload.checked,
      source: payload.source,
      source_id: payload.sourceId ?? null,
    }),
  })
}

export function updateProcurementItem(
  id: string,
  payload: { checked?: boolean; ingredient?: string; quantity?: string; unit?: string },
): Promise<ProcurementItem> {
  return apiRequest(`/procurement-items/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteProcurementItem(id: string): Promise<void> {
  return apiRequest(`/procurement-items/${id}`, { method: 'DELETE' })
}

export async function generateProcurement(
  rows: Array<Record<string, string>>,
  sourceId: string,
): Promise<number> {
  const items = await fetchProcurement()
  let added = 0
  for (const row of rows) {
    const ingredient = String(row.ingredient ?? '').trim()
    if (!ingredient || items.some((item) => item.sourceId === sourceId && item.ingredient === ingredient)) continue
    await createProcurementItem({
      ingredient,
      quantity: String(row.missing_quantity ?? ''),
      unit: String(row.unit ?? ''),
      checked: false,
      source: 'agent',
      sourceId,
    })
    added += 1
  }
  return added
}
