const modules = [
  ["01", "Document intelligence", "Upload and organize case documents, contracts, and filings."],
  ["02", "Cited legal research", "Ask questions and trace answers back to source passages."],
  ["03", "Case monitoring", "Track case updates, orders, and hearing-date changes."],
  ["04", "Compliance deadlines", "Identify obligations and manage reminder schedules."],
];
export default function App() {
  return <main className="shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">L</span> Legal AI <span className="muted">/ Intelligence</span></a><span className="environment"><span className="status-dot"/> Phase 1 scaffold</span></header>
    <section className="hero"><p className="eyebrow">LEGAL RESEARCH · CASE INTELLIGENCE · COMPLIANCE</p><h1>Evidence first.<br/><em>Answers you can verify.</em></h1><p className="hero-copy">A workspace for searching legal documents, researching cases with source references, and tracking compliance obligations. Core features will be added incrementally.</p><a className="primary-link" href="#workspace">Explore workspace <span>↘</span></a><p className="small-note">Prototype · Not legal advice</p></section>
    <section id="workspace" className="workspace"><p className="eyebrow">WORKSPACE OVERVIEW</p><h2>Built around your case files.</h2><div className="feature-grid">{modules.map(([number, title, description]) => <article className="feature-card" key={number}><span className="card-number">{number}</span><span className="pill">Planned</span><h3>{title}</h3><p>{description}</p></article>)}</div></section>
    <footer><span>LEGAL AI ASSISTANT</span><span>Verify every source and deadline.</span></footer>
  </main>;
}
