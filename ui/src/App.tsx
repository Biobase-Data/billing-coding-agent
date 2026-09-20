import { NavLink, Route, Routes } from "react-router-dom"
import QueuePage from "./pages/QueuePage"
import CaseReviewPage from "./pages/CaseReviewPage"
import DecisionLogPage from "./pages/DecisionLogPage"

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Billing &amp; Coding Agent</span>
        <nav className="app-nav">
          <NavLink to="/" end>
            Queue
          </NavLink>
          <NavLink to="/decisions">Decision Log</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/cases/:caseId/runs/:runId" element={<CaseReviewPage />} />
          <Route path="/decisions" element={<DecisionLogPage />} />
        </Routes>
      </main>
    </div>
  )
}
