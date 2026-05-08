import { useEffect, useRef, useState, useCallback } from "react";
import "@/App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Generate a stable session ID per browser tab.
const SESSION_ID = `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

/* ─────────────────── Brand & Header ─────────────────── */

function Logo() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <path d="M3 17l4-4 4 4 4-8 6 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="3" cy="17" r="1.4" fill="currentColor" />
        </svg>
      </div>
      <div className="brand-text">
        <div className="brand-title">Groww MF Assistant</div>
        <div className="brand-sub">HDFC Mutual Fund · Facts only</div>
      </div>
    </div>
  );
}

function Disclaimer() {
  return (
    <div className="disclaimer-banner" data-testid="disclaimer-banner">
      <span className="disclaimer-dot" />
      <span>Facts-only · No investment advice</span>
    </div>
  );
}

/* ─────────────────── Sidebar ─────────────────── */

function MetaPanel({ meta }) {
  if (!meta) return null;
  return (
    <div className="meta-panel" data-testid="meta-panel">
      <div className="meta-row">
        <span className="meta-label">AMC</span>
        <span className="meta-value">{meta.amc}</span>
      </div>
      <div className="meta-row">
        <span className="meta-label">Schemes</span>
        <span className="meta-value">{meta.schemes?.length ?? 0}</span>
      </div>
      <div className="meta-row">
        <span className="meta-label">Indexed chunks</span>
        <span className="meta-value">{meta.n_chunks ?? 0}</span>
      </div>
      {meta.last_refresh_at && (
        <div className="meta-row">
          <span className="meta-label">Refreshed</span>
          <span className="meta-value mono">{formatDate(meta.last_refresh_at)}</span>
        </div>
      )}
    </div>
  );
}

function SchemeChips({ schemes, onPick }) {
  if (!schemes?.length) return null;
  return (
    <div className="scheme-chips" data-testid="scheme-chips">
      {schemes.map((s) => (
        <button
          key={s.id}
          className="scheme-chip"
          onClick={() => onPick(`What is the expense ratio of ${s.name}?`)}
          data-testid={`scheme-chip-${s.id}`}
        >
          <span className="scheme-chip-cat">{s.category}</span>
          <span className="scheme-chip-name">{shortName(s.name)}</span>
        </button>
      ))}
    </div>
  );
}

/* ─────────────────── Welcome screen ─────────────────── */

function WelcomeScreen({ examples, onPick }) {
  return (
    <div className="welcome">
      <div className="welcome-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
          <path d="M3 17l4-4 4 4 4-8 6 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="3" cy="17" r="1.2" fill="currentColor" />
        </svg>
      </div>
      <div className="welcome-eyebrow">Groww Mutual Fund Facts</div>
      <h1 className="welcome-title">What would you like to know?</h1>
      <p className="welcome-sub">
        I can look up factual details like expense ratio, exit load, risk level, lock-in,
        benchmark, or SIP minimum for HDFC mutual fund schemes.
      </p>
      <div className="quick-actions">
        {["Expense ratio", "Exit load", "Risk level", "Minimum SIP", "Benchmark"].map((label) => (
          <button
            key={label}
            className="quick-chip"
            onClick={() => onPick(`What is the ${label.toLowerCase()} of HDFC Mid Cap Fund?`)}
          >
            {label}
          </button>
        ))}
      </div>
      {examples?.length > 0 && (
        <div className="examples" data-testid="examples">
          <div className="examples-label">Or try a specific question:</div>
          <div className="examples-list">
            {examples.map((q, i) => (
              <button
                key={i}
                className="example-chip"
                onClick={() => onPick(q)}
                data-testid={`example-chip-${i}`}
              >
                <span className="example-icon">→</span>
                <span>{q}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────── Messages ─────────────────── */

function MessageBubble({ msg, onSuggestionClick }) {
  if (msg.role === "user") {
    return (
      <div className="message message-user" data-testid="msg-user">
        <div className="bubble bubble-user">{msg.content}</div>
      </div>
    );
  }
  const { intent, body, citation_url, last_updated, suggestions } = msg;
  const intentClass = intent ? `intent-${intent}` : "";
  const intentLabel = labelForIntent(intent);
  return (
    <div className="message message-assistant" data-testid="msg-assistant">
      <div className={`bubble bubble-assistant ${intentClass}`}>
        {intentLabel && (
          <div className={`intent-tag ${intentClass}`}>
            <span className="intent-dot" />
            {intentLabel}
          </div>
        )}
        <div className="bubble-body" data-testid="answer-body">{body || msg.content}</div>
        {citation_url && (
          <div className="citation" data-testid="answer-source">
            <span className="citation-label">Source</span>
            <a
              className="citation-link"
              href={citation_url}
              target="_blank"
              rel="noopener nofollow noreferrer"
            >
              {prettyUrl(citation_url)}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
          </div>
        )}
        {last_updated && (
          <div className="footer-meta" data-testid="answer-last-updated">
            Last updated from sources: <span className="mono">{last_updated}</span>
          </div>
        )}
      </div>
      {/* Follow-up suggestion chips */}
      {suggestions?.length > 0 && (
        <div className="suggestion-chips">
          {suggestions.map((s, i) => (
            <button
              key={i}
              className="suggestion-chip"
              onClick={() => onSuggestionClick(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="message message-assistant" data-testid="loading-bubble">
      <div className="bubble bubble-assistant typing-bubble">
        <div className="typing-indicator">
          <div className="typing-text">Looking up facts</div>
          <div className="thinking">
            <span /><span /><span />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────── Helpers ─────────────────── */

function labelForIntent(intent) {
  switch (intent) {
    case "factual": return "Verified Fact";
    case "advisory": return "Can't Advise";
    case "comparison": return "Can't Compare";
    case "prediction": return "Can't Predict";
    case "capital_gains_walkthrough": return "Outside My Scope";
    case "pii": return "Privacy Protected";
    case "greeting": return null; // No tag for greetings — feels more natural.
    case "conversational": return null;
    case "dont_know": return null;
    default: return null;
  }
}

function prettyUrl(url) {
  try {
    const u = new URL(url);
    return u.host + u.pathname;
  } catch { return url; }
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch { return iso; }
}

function shortName(name) {
  return name?.replace(" - Direct Growth", "").replace(" - Direct Plan Growth", "") || name;
}

/* ─────────────────── Main App ─────────────────── */

function App() {
  const [meta, setMeta] = useState(null);
  const [examples, setExamples] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [reingestState, setReingestState] = useState({ running: false, last: null });
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { loadMeta(); loadExamples(); }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, loading]);

  async function loadMeta() {
    try {
      const { data } = await axios.get(`${API}/meta`);
      setMeta(data);
    } catch (e) {
      setError("Could not load corpus metadata. Is the backend running?");
    }
  }

  async function loadExamples() {
    try {
      const { data } = await axios.get(`${API}/examples`);
      setExamples(data.examples || []);
    } catch (e) { /* Silent. */ }
  }

  const send = useCallback(async (rawQuery) => {
    const query = (rawQuery ?? input).trim();
    if (!query || loading) return;
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setInput("");
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/ask`, {
        query,
        session_id: SESSION_ID,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          intent: data.intent,
          body: data.body,
          citation_url: data.citation_url,
          last_updated: data.last_updated,
          content: data.answer,
          suggestions: data.suggestions || [],
        },
      ]);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Unknown error";
      setError(`Request failed: ${detail}`);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          intent: "dont_know",
          body: "I couldn't reach the assistant right now. Please try again in a moment.",
          content: "",
          suggestions: [],
        },
      ]);
    } finally {
      setLoading(false);
      // Refocus input after response.
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [input, loading]);

  async function startReingest() {
    if (reingestState.running) return;
    setReingestState({ running: true, last: reingestState.last });
    try {
      await axios.post(`${API}/reingest?force=true`);
      let elapsed = 0;
      const poll = setInterval(async () => {
        elapsed += 4;
        try {
          const { data } = await axios.get(`${API}/refresh-status`);
          if (data) {
            setReingestState({ running: false, last: data });
            clearInterval(poll);
            await loadMeta();
          }
        } catch (_) {}
        if (elapsed > 180) {
          clearInterval(poll);
          setReingestState((s) => ({ ...s, running: false }));
        }
      }, 4000);
    } catch (e) {
      setReingestState({ running: false, last: reingestState.last });
      setError("Re-ingest could not be started.");
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const hasMessages = messages.length > 0;

  return (
    <div className="App">
      <header className="app-header">
        <Logo />
        <Disclaimer />
      </header>

      <main className="app-main">
        <aside className="sidebar">
          <MetaPanel meta={meta} />
          {meta?.schemes?.length > 0 && (
            <div className="sidebar-block">
              <div className="sidebar-title">Covered schemes</div>
              <SchemeChips schemes={meta.schemes} onPick={send} />
            </div>
          )}
          <div className="sidebar-block">
            <div className="sidebar-title">Maintenance</div>
            <button
              className="reingest-btn"
              onClick={startReingest}
              disabled={reingestState.running}
              data-testid="reingest-btn"
            >
              {reingestState.running ? (
                <><span className="spinner" /> Re-ingesting…</>
              ) : (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                  Re-ingest now
                </>
              )}
            </button>
            {reingestState.last && (
              <div className="reingest-status" data-testid="reingest-status">
                <div>Last run: <span className="mono">{formatDate(reingestState.last.finished_at)}</span></div>
                <div>Outcome: <span className={`outcome outcome-${reingestState.last.outcome}`}>{reingestState.last.outcome}</span></div>
                <div>Chunks: <span className="mono">{reingestState.last.n_chunks}</span></div>
              </div>
            )}
          </div>
        </aside>

        <section className="chat-area">
          <div className="chat-scroll" ref={scrollRef}>
            {!hasMessages && (
              <WelcomeScreen examples={examples} onPick={send} />
            )}
            {messages.map((m, i) => (
              <MessageBubble key={i} msg={m} onSuggestionClick={send} />
            ))}
            {loading && <TypingIndicator />}
          </div>

          <div className="composer">
            {error && (
              <div className="error-banner" data-testid="error-banner">{error}</div>
            )}
            <div className="composer-row">
              <input
                ref={inputRef}
                type="text"
                className="composer-input"
                placeholder="Ask about any HDFC scheme…  (e.g. exit load of HDFC Flexi Cap)"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                disabled={loading}
                data-testid="composer-input"
                autoFocus
              />
              <button
                className="composer-send"
                onClick={() => send()}
                disabled={loading || !input.trim()}
                data-testid="composer-send"
              >
                {loading ? (
                  <span className="spinner" />
                ) : (
                  <>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                  </>
                )}
              </button>
            </div>
            <div className="composer-helper">
              Press Enter to send · No advice · No PII
            </div>
          </div>
        </section>
      </main>

      <footer className="app-footer">
        <span>RAG over closed corpus · 5 official Groww scheme pages · ChromaDB + BM25 + cross-encoder rerank</span>
      </footer>
    </div>
  );
}

export default App;
