import { apiRequest } from './client'

export const HOME_WORKSPACE_ID = 'home-workspace'

export interface InventoryItem {
  id: string
  ingredient_key: string
  ingredient_name: string
  category: string
  quantity: string
  unit: string
  expires_on: string | null
  is_expiring: boolean
}

export interface IngredientOption {
  key: string
  name: string
  category: string
  default_unit: string
}

export interface InventoryCreateInput {
  ingredient_key?: string | null
  ingredient_name?: string | null
  category?: string | null
  quantity: number
  unit?: string | null
  expires_on?: string | null
}

export function fetchInventory(workspaceId = HOME_WORKSPACE_ID): Promise<InventoryItem[]> {
  return apiRequest(`/workspaces/${workspaceId}/inventory`)
}

export function addInventoryItem(
  payload: InventoryCreateInput,
  workspaceId = HOME_WORKSPACE_ID,
): Promise<InventoryItem> {
  return apiRequest(`/workspaces/${workspaceId}/inventory`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateInventoryItem(
  itemId: string,
  payload: { quantity?: number; unit?: string; expires_on?: string | null },
): Promise<InventoryItem> {
  return apiRequest(`/inventory/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteInventoryItem(itemId: string): Promise<void> {
  return apiRequest(`/inventory/${itemId}`, { method: 'DELETE' })
}

export function fetchIngredients(): Promise<IngredientOption[]> {
  return apiRequest('/ingredients')
}
