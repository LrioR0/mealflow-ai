export interface ProcurementItem {
  id: string
  ingredient: string
  quantity: string
  unit: string
  checked: boolean
  source: 'agent' | 'manual'
  sourceId?: string
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

export function generateProcurement(rows: Array<Record<string, string>>, sourceId: string): number {
  const items = readProcurement()
  let added = 0
  for (const row of rows) {
    const ingredient = String(row.ingredient ?? '').trim()
    if (!ingredient || items.some((item) => item.sourceId === sourceId && item.ingredient === ingredient)) continue
    items.unshift({
      id: crypto.randomUUID(),
      ingredient,
      quantity: String(row.missing_quantity ?? ''),
      unit: String(row.unit ?? ''),
      checked: false,
      source: 'agent',
      sourceId,
    })
    added += 1
  }
  saveProcurement(items)
  return added
}
