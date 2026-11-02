import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type Account } from '../api'

export default function ScanPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [params] = useSearchParams()
  const navigate = useNavigate()

  useEffect(() => {
    void api
      .accounts()
      .then((list) => {
        setAccounts(list)
        const preset = params.get('account')
        if (preset && list.some((a) => a.id === preset)) {
          setAccountId(preset)
        } else if (list[0]) {
          setAccountId(list[0].id)
        }
      })
      .catch((err: Error) => setError(err.message))
  }, [params])

  async function startScan() {
    if (!accountId) return
    setStarting(true)
    setError('')
    try {
      const res = await api.startScan(accountId)
      navigate(`/runs/${res.run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed to start')
      setStarting(false)
    }
  }

  return (
    <section className="panel">
      <h2>New scan</h2>
      <p className="sub">
        Dry-run only. Large mailboxes take several minutes; progress streams into the run
        log.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <div className="row">
        <label className="field">
          Account
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.id} · {account.email}
              </option>
            ))}
          </select>
        </label>
        <button disabled={!accountId || starting} onClick={() => void startScan()}>
          {starting ? 'Starting…' : 'Start scan'}
        </button>
        <Link to="/history" className="badge muted">
          View history
        </Link>
      </div>
    </section>
  )
}
