const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const payload = await response.json()
      detail = typeof payload.detail === 'string'
        ? payload.detail
        : payload.detail?.message || detail
    } catch {
      // Keep the HTTP status as the useful error when the body is not JSON.
    }
    throw new Error(detail)
  }

  return response.json()
}

export function getHealth() {
  return request('/api/health')
}

export function getLibrary() {
  return request('/api/library')
}

export function uploadDocuments(files) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return request('/api/documents', { method: 'POST', body: form })
}

export function sendChat(question, history, sources) {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify(sources?.length ? { question, history, sources } : { question, history }),
  })
}

export function clearLibrary() {
  return request('/api/library', { method: 'DELETE' })
}
