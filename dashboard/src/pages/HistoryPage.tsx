import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type RunSummary } from '../api'

function statusClass(status: string) {
  if (status === 'completed') return 'ok'
  if (status === 'running') return 'warn'
  if (status === 'failed') return 'danger'
  return 'muted'
}

export default function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setRuns(await api.runs())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history')
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <section className="panel">
      <h2>History</h2>
      <p className="sub">Scans and cleanup actions from this machine.</p>
      {error ? <p className="error">{error}</p> : null}
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Account</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td>
                <Link className="mono" to={`/runs/${run.run_id}`}>
                  {run.run_id}
                </Link>
              </td>
              <td>{run.account_id}</td>
              <td>{run.mode}</td>
              <td>
                <span className={`badge ${statusClass(run.status)}`}>{run.status}</span>
              </td>
              <td className="mono muted">{run.started_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!runs.length && !error ? <p className="muted">No runs yet.</p> : null}
    </section>
  )
}
