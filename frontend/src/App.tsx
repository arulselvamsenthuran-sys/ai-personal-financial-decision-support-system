import HealthStatus from "./components/HealthStatus";
import "./App.css";

function App() {
  return (
    <div className="app">
      {/* Animated background particles */}
      <div className="bg-particles" aria-hidden="true">
        <div className="particle particle--1" />
        <div className="particle particle--2" />
        <div className="particle particle--3" />
      </div>

      <header className="app-header">
        <div className="logo" id="app-logo">
          <span className="logo__icon">◈</span>
          <span className="logo__text">Finance Support</span>
        </div>
        <span className="app-header__badge">Phase 1</span>
      </header>

      <main className="app-main">
        <section className="hero">
          <h1 className="hero__title">
            AI-Powered Financial
            <br />
            <span className="hero__title--accent">Decision Support</span>
          </h1>
          <p className="hero__subtitle">
            Intelligent analysis for smarter financial decisions.
            <br />
            Phase 1 — Full-stack foundation verified.
          </p>
        </section>

        <section className="dashboard" id="dashboard-health">
          <HealthStatus />
        </section>

        <section className="stack-info">
          <h2>Technology Stack</h2>
          <div className="stack-info__grid">
            <div className="stack-chip">
              <span className="stack-chip__icon">⚛</span> React + TypeScript
            </div>
            <div className="stack-chip">
              <span className="stack-chip__icon">⚡</span> Vite
            </div>
            <div className="stack-chip">
              <span className="stack-chip__icon">🐍</span> FastAPI
            </div>
            <div className="stack-chip">
              <span className="stack-chip__icon">🐘</span> PostgreSQL
            </div>
            <div className="stack-chip">
              <span className="stack-chip__icon">🔄</span> SQLAlchemy
            </div>
            <div className="stack-chip">
              <span className="stack-chip__icon">📦</span> Alembic
            </div>
          </div>
        </section>
      </main>

      <footer className="app-footer">
        <p>Finance Support System &middot; Phase 1 &middot; Development Build</p>
      </footer>
    </div>
  );
}

export default App;
