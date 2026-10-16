import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const MAX_FILE_BYTES = 15 * 1024 * 1024;

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

async function readApiError(response) {
  try {
    const payload = await response.json();
    return payload.detail || payload.message || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyDelete, setBusyDelete] = useState("");
  const [busyIndex, setBusyIndex] = useState("");
  const [semanticQuery, setSemanticQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchMessage, setSearchMessage] = useState("");
  const [searching, setSearching] = useState(false);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatSources, setChatSources] = useState([]);
  const [chatting, setChatting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const inputRef = useRef(null);

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/documents`);
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setDocuments(payload.items || []);
      setError("");
    } catch (err) {
      setError(`Could not connect to the API. Start FastAPI on port 8000. ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  const filteredDocuments = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return documents;
    return documents.filter((item) => item.original_filename.toLowerCase().includes(term));
  }, [documents, search]);

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setNotice("");
    if (!file.name.toLowerCase().endsWith(".pdf") || file.type && file.type !== "application/pdf") {
      setError("Choose a PDF file. Other file types are not supported yet.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("This file exceeds the 15 MB upload limit.");
      return;
    }
    const body = new FormData();
    body.append("file", file);
    setUploading(true);
    try {
      const response = await fetch(`${API_BASE}/api/documents`, { method: "POST", body });
      if (!response.ok) throw new Error(await readApiError(response));
      const created = await response.json();
      setNotice(`Uploaded ${created.filename}. Extracted ${created.extracted_characters.toLocaleString()} characters from ${created.page_count} page(s).`);
      await loadDocuments();
      const detailResponse = await fetch(`${API_BASE}/api/documents/${created.id}`);
      if (detailResponse.ok) setSelected(await detailResponse.json());
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
    } finally {
      setUploading(false);
    }
  }

  async function openDocument(id) {
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/documents/${id}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setSelected(await response.json());
    } catch (err) {
      setError(err.message);
    }
  }

  async function indexDocument(item) {
    setBusyIndex(item.id);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/documents/${item.id}/index`, { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = await response.json();
      setNotice(`Indexed ${result.filename}: ${result.chunks_indexed} searchable chunks created.`);
      await loadDocuments();
    } catch (err) {
      setError(err.message || "Indexing failed. Please try again.");
    } finally {
      setBusyIndex("");
    }
  }

  async function runSemanticSearch(event) {
    event.preventDefault();
    setSearching(true);
    setError("");
    setSearchMessage("");
    setSearchResults([]);
    try {
      const response = await fetch(`${API_BASE}/api/search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: semanticQuery, limit: 5 }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setSearchResults(payload.items || []);
      setSearchMessage(payload.message || (payload.count ? `Found ${payload.count} relevant passage(s).` : "No matching passages found. Index documents or try a different query."));
    } catch (err) {
      setError(err.message || "Search failed. Please try again.");
    } finally {
      setSearching(false);
    }
  }

  async function submitChat(event) {
    event.preventDefault();
    setChatting(true);
    setChatAnswer("");
    setChatSources([]);
    setError("");
    try {
      const response = await fetch(API_BASE + "/api/chat/stream", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: chatQuestion, limit: 5 }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const reader = response.body?.getReader();
      if (!reader) throw new Error("This browser does not support streamed responses.");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          let eventType = "message";
          const dataLines = [];
          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          const payload = JSON.parse(dataLines.join("\n"));
          if (eventType === "sources") setChatSources(payload);
          else if (eventType === "token") setChatAnswer((previous) => previous + (payload.text || ""));
          else if (eventType === "error") throw new Error(payload.detail || "The AI stream failed.");
        }
        if (done) break;
      }
    } catch (err) {
      setError(err.message || "The AI chat request failed.");
    } finally {
      setChatting(false);
    }
  }

  async function removeDocument(item) {
    if (!window.confirm(`Delete "${item.original_filename}" and its extracted text? This cannot be undone.`)) return;
    setBusyDelete(item.id);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/documents/${item.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      if (selected?.id === item.id) setSelected(null);
      setNotice(`Deleted ${item.original_filename}.`);
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyDelete("");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Legal AI Assistant home">
          <span className="brand-mark">L</span>
          <span>Legal AI <span className="brand-light">/ Intelligence</span></span>
        </a>
        <div className="topbar-right"><span className="api-status"><span className={error && documents.length === 0 ? "status-dot status-error" : "status-dot"} />{error && documents.length === 0 ? "API connection needed" : "Local workspace"}</span><span className="phase-label">PHASE 2 · DOCUMENTS</span></div>
      </header>

      <section className="hero">
        <p className="eyebrow">LEGAL RESEARCH · CASE INTELLIGENCE · COMPLIANCE</p>
        <h1>Evidence first.<br /><em>Answers you can verify.</em></h1>
        <p className="hero-copy">Bring your case documents into one workspace. Upload a PDF, extract its text, and inspect the source before moving on to search and AI-assisted research.</p>
        <div className="hero-foot"><span className="hero-index">01 / DOCUMENT INTELLIGENCE</span><span className="disclaimer">Research support only · Not legal advice</span></div>
      </section>

      <section className="workspace" id="workspace">
        <div className="section-heading">
          <div><p className="eyebrow">YOUR CASE FILES</p><h2>Document library</h2></div>
          <div className="document-count"><strong>{documents.length.toString().padStart(2, "0")}</strong><span>documents</span></div>
        </div>

        <div className="upload-panel">
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15.5v3A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg></div>
          <div className="upload-copy"><h3>Upload a legal document</h3><p>PDF only · Up to 15 MB · Text extraction runs locally through the API</p></div>
          <input ref={inputRef} className="visually-hidden" type="file" accept="application/pdf,.pdf" onChange={handleUpload} />
          <button className="button-primary" type="button" disabled={uploading} onClick={() => inputRef.current?.click()}>{uploading ? <><span className="spinner" /> Processing…</> : "Choose PDF ↗"}</button>
        </div>

        {error && <div className="message message-error" role="alert"><span>!</span><div><strong>Something needs attention</strong><p>{error}</p></div><button className="message-close" onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
        {notice && <div className="message message-success" role="status"><span>✓</span><p>{notice}</p><button className="message-close" onClick={() => setNotice("")} aria-label="Dismiss notice">×</button></div>}

        <section className="semantic-panel">
          <div className="semantic-heading"><div><p className="eyebrow">RETRIEVAL WORKSPACE</p><h3>Search across your documents</h3><p>Ask a question in natural language to find related passages and page references.</p></div><span className="semantic-mark">⌕</span></div>
          <form className="semantic-form" onSubmit={runSemanticSearch}>
            <input value={semanticQuery} onChange={(event) => setSemanticQuery(event.target.value)} minLength={3} maxLength={1000} required placeholder="e.g. What does the contract say about termination notice?" aria-label="Semantic search query" />
            <button className="button-primary" type="submit" disabled={searching || semanticQuery.trim().length < 3}>{searching ? <><span className="spinner" /> Searching…</> : "Find passages ↗"}</button>
          </form>
          {searchMessage && <p className="search-message" role="status">{searchMessage}</p>}
          {searchResults.length > 0 && <div className="search-results">{searchResults.map((result) => <article className="search-result" key={result.document_id + "-" + result.chunk_index}>
            <div className="result-meta"><button onClick={() => openDocument(result.document_id)}>{result.filename}</button><span>Page {result.page_start}{result.page_end !== result.page_start ? "–" + result.page_end : ""}</span><span>Cosine {result.score.toFixed(2)}</span></div>
            <p>{result.text}</p>
          </article>)}</div>}
        </section>

        <section className="chat-panel">
          <div className="chat-heading"><div><p className="eyebrow">DOCUMENT-GROUNDED AI</p><h3>Ask your legal documents</h3><p>Answers use retrieved passages, with source labels and page references. No source, no assumed fact.</p></div><span className="chat-mark">✳</span></div>
          <form className="chat-form" onSubmit={submitChat}>
            <textarea value={chatQuestion} onChange={(event) => setChatQuestion(event.target.value)} minLength={3} maxLength={2000} required rows={3} placeholder="Ask a question about the documents you have indexed…" aria-label="Question for the legal document assistant" />
            <div className="chat-form-footer"><span>Verify legal conclusions and dates against the cited source.</span><button className="button-primary" type="submit" disabled={chatting || chatQuestion.trim().length < 3}>{chatting ? <><span className="spinner" /> Researching…</> : "Ask documents ↗"}</button></div>
          </form>
          {chatAnswer && <div className="chat-answer"><p className="answer-label">AI RESEARCH RESPONSE</p><div className="answer-text">{chatAnswer}</div>
            {chatSources.length > 0 && <div className="chat-sources"><h4>Retrieved sources</h4>{chatSources.map((source) => <article className="chat-source" key={source.source_id}>
              <div><span className="source-id">{source.source_id}</span><button onClick={() => openDocument(source.document_id)}>{source.filename}</button><span className="source-pages">Page {source.page_start}{source.page_end !== source.page_start ? "–" + source.page_end : ""}</span></div>
              <p>{source.excerpt}</p>
            </article>)}</div>}
            <p className="chat-disclaimer">AI-generated research assistance, not legal advice. Check every cited passage in context.</p>
          </div>}
        </section>

        <div className="library-toolbar">
          <div><h3>Stored documents</h3><p>Files are saved to the configured local data directory.</p></div>
          <label className="search-box"><svg viewBox="0 0 24 24" fill="none"><circle cx="10.8" cy="10.8" r="6.8" stroke="currentColor" strokeWidth="1.5"/><path d="m16 16 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search filenames" aria-label="Search filenames" /></label>
        </div>

        {loading ? <div className="empty-state"><span className="spinner spinner-dark" /><p>Loading your document library…</p></div> : filteredDocuments.length === 0 ? (
          <div className="empty-state"><div className="empty-file">PDF</div><h3>{search ? "No matching documents" : "Your document library is ready"}</h3><p>{search ? "Try another filename." : "Upload your first PDF to extract text and see it appear here."}</p><button className="button-secondary" onClick={() => inputRef.current?.click()} disabled={uploading}>Upload a PDF</button></div>
        ) : (
          <div className="document-table-wrap"><table className="document-table"><thead><tr><th>DOCUMENT</th><th>PAGES</th><th>SIZE</th><th>ADDED</th><th><span className="visually-hidden">Actions</span></th></tr></thead><tbody>
            {filteredDocuments.map((item) => <tr key={item.id} className={selected?.id === item.id ? "selected-row" : ""}>
              <td><button className="document-name" onClick={() => openDocument(item.id)}><span className="pdf-badge">PDF</span><span><strong>{item.original_filename}</strong><small>{Number(item.extracted_characters || 0).toLocaleString()} extracted characters</small></span></button></td>
              <td>{item.page_count}</td><td>{formatBytes(item.size_bytes)}</td><td className="date-cell">{formatDate(item.created_at)}</td>
              <td className="row-actions"><button className="index-button" onClick={() => indexDocument(item)} disabled={busyIndex === item.id}>{busyIndex === item.id ? "Indexing…" : item.indexed ? "Re-index" : "Index"}</button><button className="delete-button" onClick={() => removeDocument(item)} disabled={busyDelete === item.id} aria-label={`Delete ${item.original_filename}`}>{busyDelete === item.id ? "…" : "Delete"}</button></td>
            </tr>)}
          </tbody></table></div>
        )}

        {selected && <section className="detail-panel" aria-label="Document extracted text">
          <div className="detail-heading"><div><p className="eyebrow">SOURCE PREVIEW</p><h3>{selected.original_filename}</h3><p>{selected.page_count} page(s) · SHA-256 <code>{selected.sha256}</code></p></div><button className="close-detail" onClick={() => setSelected(null)} aria-label="Close document preview">×</button></div>
          <div className="extracted-text">{selected.extracted_text ? selected.extracted_text : "No selectable text was found in this PDF. It may be a scanned document; OCR support has not been added yet."}</div>
        </section>}
      </section>

      <footer className="footer"><span>LEGAL AI ASSISTANT</span><span>Keep sensitive case files private. Authentication and access controls are the next security milestone.</span></footer>
    </main>
  );
}