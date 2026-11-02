import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, formatBytes, type Finding, type RunDetail } from '../api'

function parseSummary(raw: string | null) {
  if (!raw) return null
  try {
    return JSON.parse(raw) as {
      total_messages?: number
      total_est_bytes?: number
      failed_metadata?: number
      mode?: string
      location?: string
      location_label?: string
      top_senders?: { sender: string; message_count: number; est_bytes: number }[]
      queries?: { name: string; message_count: number; est_bytes: number }[]
      error?: string
    }
  } catch {
    return null
  }
}

export default function RunDetailPage() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState('')
  const [selectedSender, setSelectedSender] = useState<string>('')
  const [previewCount, setPreviewCount] = useState<number | null>(null)
  const [previewIds, setPreviewIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [customQuery, setCustomQuery] = useState('')

  async function load() {
    if (!runId) return
    try {
      const detail = await api.run(runId)
      setRun(detail)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load run')
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 2500)
    return () => window.clearInterval(timer)
  }, [runId])

  const summary = useMemo(() => parseSummary(run?.summary_json ?? null), [run])

  const scanMeta = useMemo(() => {
    if (summary?.mode || summary?.location) {
      return {
        mode: summary.mode || 'storage',
        location: summary.location || 'all',
        label: summary.location_label || summary.location || 'all',
      }
    }
    const parts = (run?.mode || '').split(':')
    if (parts.length >= 3 && parts[0] === 'scan') {
      return { mode: parts[1], location: parts[2], label: parts[2] }
    }
    return { mode: 'storage', location: 'all', label: 'all' }
  }, [run, summary])

  const senderFindings: Finding[] = useMemo(
    () =>
      (run?.findings || [])
        .filter((f) => f.bucket === 'sender')
        .sort((a, b) => b.est_bytes - a.est_bytes),
    [run],
  )

  const queryFindings: Finding[] = useMemo(
    () => (run?.findings || []).filter((f) => f.bucket === 'query'),
    [run],
  )

  async function previewSender(sender: string) {
    if (!run) return
    setBusy(true)
    setError('')
    setSelectedSender(sender)
    try {
      const res = await api.preview(run.account_id, {
        sender,
        location: scanMeta.location,
      })
      setPreviewCount(res.message_count)
      setPreviewIds(res.all_message_ids)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setBusy(false)
    }
  }

  async function previewQuery() {
    if (!run || !customQuery.trim()) return
    setBusy(true)
    setError('')
    setSelectedSender('')
    try {
      const res = await api.preview(run.account_id, { query: customQuery.trim() })
      setPreviewCount(res.message_count)
      setPreviewIds(res.all_message_ids)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setBusy(false)
    }
  }

  async function confirmTrash() {
    if (!run || previewCount == null || previewCount === 0) return
    const label = selectedSender || customQuery
    const ok = window.confirm(
      `Move ${previewCount} messages to Trash?\n\nTarget: ${label}\nAccount: ${run.account_id}\n\nTrash still counts toward quota until emptied.`,
    )
    if (!ok) return
    setBusy(true)
    setError('')
    try {
      const res = await api.cleanup({
        account_id: run.account_id,
        message_ids: previewIds,
        confirm: true,
        permanent: false,
      })
      window.alert(`Moved ${res.message_count} messages to Trash (run ${res.run_id})`)
      setPreviewCount(null)
      setPreviewIds([])
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cleanup failed')
    } finally {
      setBusy(false)
    }
  }

  if (!run && !error) {
    return (
      <section className="panel">
        <p className="muted">Loading run…</p>
      </section>
    )
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <h2>
              Run <span className="mono">{runId}</span>
            </h2>
            <p className="sub">
              {run?.account_id} · {scanMeta.mode} · {scanMeta.label} ·{' '}
              <span
                className={`badge ${
                  run?.status === 'completed'
                    ? 'ok'
                    : run?.status === 'running'
                      ? 'warn'
                      : 'danger'
                }`}
              >
                {run?.status}
              </span>
            </p>
          </div>
          <Link to="/history" className="badge muted">
            Back to history
          </Link>
        </div>
        {error ? <p className="error">{error}</p> : null}
        <div className="grid two">
          <div className="stat">
            <span className="muted">Messages scanned</span>
            <strong>{summary?.total_messages ?? '—'}</strong>
          </div>
          <div className="stat">
            <span className="muted">Estimated size</span>
            <strong>
              {summary?.total_est_bytes != null ? formatBytes(summary.total_est_bytes) : '—'}
            </strong>
          </div>
        </div>
        {summary?.error ? <p className="error">{summary.error}</p> : null}
      </section>

      {queryFindings.length > 0 ? (
        <section className="panel">
          <h2>Query buckets</h2>
          <p className="sub">What matched each storage query.</p>
          <table>
            <thead>
              <tr>
                <th>Query</th>
                <th>Messages</th>
                <th>Est. size</th>
              </tr>
            </thead>
            <tbody>
              {queryFindings.map((f) => (
                <tr key={f.id}>
                  <td className="mono">{f.query}</td>
                  <td>{f.message_count}</td>
                  <td>{formatBytes(f.est_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="panel">
        <h2>Top senders</h2>
        <p className="sub">
          Ranked by {scanMeta.mode === 'subscriptions' ? 'message count' : 'size'}.
          Preview stays scoped to this scan location when possible, then confirm Trash.
        </p>
        <table>
          <thead>
            <tr>
              <th>Sender</th>
              <th>Messages</th>
              <th>Est. size</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {senderFindings.slice(0, 40).map((f) => (
              <tr key={f.id}>
                <td className="mono">{f.sender}</td>
                <td>{f.message_count}</td>
                <td>{formatBytes(f.est_bytes)}</td>
                <td>
                  <button
                    className="secondary"
                    disabled={busy || run?.status === 'running'}
                    onClick={() => void previewSender(f.sender || '')}
                  >
                    Preview delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!senderFindings.length ? (
          <p className="muted">
            {run?.status === 'running'
              ? 'Scan still running… senders will appear when finished.'
              : 'No sender findings on this run.'}
          </p>
        ) : null}
      </section>

      <section className="panel">
        <h2>Custom query</h2>
        <p className="sub">
          Gmail search syntax, e.g. <code>in:sent larger:5M</code> or{' '}
          <code>category:promotions older_than:2y</code>
        </p>
        <div className="row">
          <label className="field">
            Query
            <input
              value={customQuery}
              onChange={(e) => setCustomQuery(e.target.value)}
              placeholder="in:sent larger:5M"
            />
          </label>
          <button
            className="secondary"
            disabled={busy || !customQuery.trim()}
            onClick={() => void previewQuery()}
          >
            Preview
          </button>
        </div>
      </section>

      {previewCount != null ? (
        <section className="panel confirm-box">
          <div>
            <h2>Confirm trash</h2>
            <p className="sub" style={{ marginBottom: 0 }}>
              {selectedSender
                ? `Sender ${selectedSender}`
                : `Query ${customQuery}`}{' '}
              · <strong>{previewCount}</strong> messages matched
            </p>
          </div>
          <div className="row">
            <button disabled={busy || previewCount === 0} onClick={() => void confirmTrash()}>
              Confirm move to Trash
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                setPreviewCount(null)
                setPreviewIds([])
              }}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <h2>Live log</h2>
        <p className="sub">Newest events while the scan runs.</p>
        <div className="events">
          {(run?.events || []).slice(-40).map((event) => (
            <div key={event.id}>
              [{event.level}] {event.message}
            </div>
          ))}
          {!run?.events?.length ? <div className="muted">No events yet.</div> : null}
        </div>
      </section>
    </>
  )
}
