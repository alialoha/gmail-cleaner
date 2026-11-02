import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type Account, type ScanOptions } from '../api'

export default function ScanPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [options, setOptions] = useState<ScanOptions | null>(null)
  const [accountId, setAccountId] = useState('')
  const [mode, setMode] = useState('subscriptions')
  const [location, setLocation] = useState('promotions')
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [params] = useSearchParams()
  const navigate = useNavigate()

  useEffect(() => {
    void Promise.all([api.accounts(), api.scanOptions()])
      .then(([list, opts]) => {
        setAccounts(list)
        setOptions(opts)
        const preset = params.get('account')
        if (preset && list.some((a) => a.id === preset)) {
          setAccountId(preset)
        } else if (list[0]) {
          setAccountId(list[0].id)
        }
        const modePreset = params.get('mode')
        const locPreset = params.get('location')
        if (modePreset && opts.modes.some((m) => m.id === modePreset)) {
          setMode(modePreset)
        }
        if (locPreset && opts.locations.some((l) => l.id === locPreset)) {
          setLocation(locPreset)
        }
      })
      .catch((err: Error) => setError(err.message))
  }, [params])

  async function startScan() {
    if (!accountId) return
    setStarting(true)
    setError('')
    try {
      const res = await api.startScan(accountId, { mode, location })
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
        Choose a profile and mailbox area. Dry-run only — nothing is deleted until you
        confirm on the run page.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <div className="grid two">
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
        <label className="field">
          Scan mode
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {(options?.modes || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Location / tab
          <select value={location} onChange={(e) => setLocation(e.target.value)}>
            {(options?.locations || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted" style={{ marginTop: 12 }}>
        Tip: start with <strong>Subscriptions + Promotions</strong> to list newsletter/ad
        senders, then use Storage + Entire mailbox for big attachments.
      </p>
      <div className="row" style={{ marginTop: 16 }}>
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
