const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed: ${response.status}`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  const responseText = await response.text()
  if (!responseText) {
    return undefined as T
  }
  return JSON.parse(responseText) as T
}
