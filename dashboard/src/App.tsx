import { NavLink, Route, Routes } from 'react-router-dom'
import AccountsPage from './pages/AccountsPage'
import HistoryPage from './pages/HistoryPage'
import RunDetailPage from './pages/RunDetailPage'
import ScanPage from './pages/ScanPage'

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1>Gmail Cleaner</h1>
          <p>Scan storage, review reports, confirm before trash.</p>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            Accounts
          </NavLink>
          <NavLink to="/scan">Scan</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<AccountsPage />} />
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>
    </div>
  )
}
