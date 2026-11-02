export type Account = {
  id: string
  email: string
  scope: string
  has_token: boolean
}

export type RunSummary = {
  run_id: string
  account_id: string
  mode: string
  status: string
  started_at: string
  finished_at: string | null
  summary_json: string | null
}

export type Finding = {
  id: number
  run_id: string
  bucket: string
  sender: string | null
  query: string | null
  message_count: number
  est_bytes: number
  sample_ids_json: string
}

export type RunDetail = RunSummary & {
  findings: Finding[]
  actions: Record<string, unknown>[]
  events: { id: number; level: string; message: string; created_at: string }[]
}

export type ScanOptions = {
  modes: { id: string; label: string }[]
  locations: { id: string; label: string }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function formatBytes(num: number): string {
  let value = num
  for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
    if (value < 1024 || unit === 'TB') {
      return unit === 'B' ? `${value} ${unit}` : `${value.toFixed(2)} ${unit}`
    }
    value /= 1024
  }
  return `${num} B`
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  accounts: () => request<Account[]>('/api/accounts'),
  runs: (limit = 50) => request<RunSummary[]>(`/api/runs?limit=${limit}`),
  run: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),
  trashCount: (accountId: string) =>
    request<{ account_id: string; count: number }>(
      `/api/accounts/${accountId}/trash-count`,
    ),
  scanOptions: () => request<ScanOptions>('/api/scan-options'),
  startScan: (
    accountId: string,
    opts?: { mode?: string; location?: string; maxPerQuery?: number },
  ) =>
    request<{ run_id: string; status: string; account_id: string }>('/api/scan', {
      method: 'POST',
      body: JSON.stringify({
        account_id: accountId,
        mode: opts?.mode ?? 'storage',
        location: opts?.location ?? 'all',
        max_per_query: opts?.maxPerQuery ?? null,
        background: true,
      }),
    }),
  preview: (
    accountId: string,
    opts: { sender?: string; query?: string; location?: string },
  ) =>
    request<{
      message_count: number
      message_ids: string[]
      all_message_ids: string[]
      query: string | null
    }>('/api/preview', {
      method: 'POST',
      body: JSON.stringify({
        account_id: accountId,
        sender: opts.sender || null,
        query: opts.query || null,
        location: opts.location || null,
      }),
    }),
  cleanup: (payload: {
    account_id: string
    message_ids?: string[]
    sender?: string
    query?: string
    confirm: boolean
    permanent?: boolean
    i_understand_permanent?: boolean
  }) =>
    request<{ run_id: string; action: string; message_count: number }>('/api/cleanup', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  emptyTrash: (accountId: string) =>
    request<{ run_id: string; message_count: number }>('/api/empty-trash', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, confirm: true }),
    }),
}
