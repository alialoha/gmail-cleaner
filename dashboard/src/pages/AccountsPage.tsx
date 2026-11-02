import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Account } from '../api'

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [health, setHealth] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [trashCounts, setTrashCounts] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState<string>('')

  async function load() {
    setError('')
    try {
      const [h, list] = await Promise.all([api.health(), api.accounts()])
      setHealth(`${h.status} · v${h.version}`)
      setAccounts(list)
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message}\nIs the API running? Start: gmail-cleaner serve`
          : 'Failed to load',
      )
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function refreshTrash(accountId: string) {
    setBusy(accountId)
    setError('')
    try {
      const res = await api.trashCount(accountId)
      setTrashCounts((prev) => ({ ...prev, [accountId]: res.count }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Trash count failed')
    } finally {
      setBusy('')
    }
  }

  async function emptyTrash(accountId: string, scope: string) {
    if (scope !== 'full') {
      setError('Empty trash requires account scope=full')
      return
    }
    const count = trashCounts[accountId]
    const ok = window.confirm(
      count != null
        ? `Permanently delete ${count} messages in Trash for ${accountId}?`
        : `Permanently empty Trash for ${accountId}?`,
    )
    if (!ok) return
    setBusy(accountId)
    setError('')
    try {
      const res = await api.emptyTrash(accountId)
      setTrashCounts((prev) => ({ ...prev, [accountId]: 0 }))
      window.alert(`Removed ${res.message_count} messages`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Empty trash failed')
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <section className="panel">
        <h2>Accounts</h2>
        <p className="sub">
          Managed via CLI under <code>~/.gmail-cleaner</code>. API: {health || '…'}
        </p>
        {error ? <p className="error">{error}</p> : null}
        {accounts.length === 0 && !error ? (
          <p className="muted">
            No accounts yet. Run{' '}
            <code>gmail-cleaner accounts add --id personal --email …</code>
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Email</th>
                <th>Scope</th>
                <th>Token</th>
                <th>Trash</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td className="mono">{account.id}</td>
                  <td>{account.email}</td>
                  <td>
                    <span className={`badge ${account.scope === 'full' ? 'ok' : 'muted'}`}>
                      {account.scope}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${account.has_token ? 'ok' : 'warn'}`}>
                      {account.has_token ? 'ready' : 'missing'}
                    </span>
                  </td>
                  <td className="mono">
                    {trashCounts[account.id] != null ? trashCounts[account.id] : '—'}
                  </td>
                  <td>
                    <div className="row">
                      <Link className="badge muted" to={`/scan?account=${account.id}`}>
                        Scan
                      </Link>
                      <button
                        className="secondary"
                        disabled={busy === account.id}
                        onClick={() => void refreshTrash(account.id)}
                      >
                        Count trash
                      </button>
                      <button
                        className="danger"
                        disabled={busy === account.id}
                        onClick={() => void emptyTrash(account.id, account.scope)}
                      >
                        Empty trash
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row" style={{ marginTop: 16 }}>
          <button className="secondary" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </section>
    </>
  )
}
