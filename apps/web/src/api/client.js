const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
export async function apiRequest(path, init) {
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: {
            'Content-Type': 'application/json',
            ...init?.headers,
        },
    });
    if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Request failed: ${response.status}`);
    }
    return response.json();
}
