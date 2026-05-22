import {
  TrendingUp,
  FileText,
  Shield,
  MessageSquare,
  CheckCircle2,
  Database,
  BookOpen,
  Scale,
  RefreshCw,
  ChevronRight,
} from "lucide-react";

/* ──────────────────────────────────────────────
   Static mock data
────────────────────────────────────────────── */

const SCHEMES = [
  { category: "MID CAP",   name: "HDFC Mid Cap Fund" },
  { category: "FLEXI CAP", name: "HDFC Flexi Cap Fund" },
  { category: "FOCUSED",   name: "HDFC Focused Fund" },
  { category: "ELSS",      name: "HDFC ELSS Tax Saver" },
  { category: "LARGE CAP", name: "HDFC Large Cap Fund" },
];

const KB_ITEMS = [
  { icon: FileText,  label: "23 Official Documents" },
  { icon: Database,  label: "HDFC AMC Sources" },
  { icon: BookOpen,  label: "AMFI Guidelines" },
  { icon: Scale,     label: "SEBI References" },
  { icon: RefreshCw, label: "Updated Daily" },
];

const GUARDRAILS = [
  "Facts-only responses",
  "No investment advice",
  "No PII collection",
  "Official public sources only",
];

const SUGGESTED_QUESTIONS = [
  "What is exit load?",
  "Minimum SIP amount?",
  "How to download statements?",
];

/* ──────────────────────────────────────────────
   Sub-components
────────────────────────────────────────────── */

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: "10px",
      fontWeight: 700,
      letterSpacing: "0.1em",
      textTransform: "uppercase",
      color: "#6b7280",
      marginBottom: "10px",
    }}>
      {children}
    </div>
  );
}

function SidebarCard({ children, style = {} }) {
  return (
    <div style={{
      background: "#0e1015",
      border: "1px solid #1f2330",
      borderRadius: "14px",
      padding: "14px",
      boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
      ...style,
    }}>
      {children}
    </div>
  );
}

/* Section 1 — Covered Schemes */
function CoveredSchemes({ onPick }) {
  return (
    <SidebarCard>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "12px" }}>
        <TrendingUp size={13} color="#4ade80" />
        <SectionLabel>Covered Schemes</SectionLabel>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
        {SCHEMES.map((s) => (
          <SchemeRow key={s.category} scheme={s} onPick={onPick} />
        ))}
      </div>
    </SidebarCard>
  );
}

function SchemeRow({ scheme, onPick }) {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onPick(`What is the expense ratio of ${scheme.name}?`)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "7px 9px",
        background: hovered ? "#14171f" : "#0a0c11",
        border: `1px solid ${hovered ? "rgba(74,222,128,0.35)" : "#1f2330"}`,
        borderRadius: "10px",
        cursor: "pointer",
        textAlign: "left",
        transition: "all 0.18s ease",
        transform: hovered ? "translateY(-1px)" : "translateY(0)",
        boxShadow: hovered
          ? "0 4px 14px rgba(74,222,128,0.08)"
          : "none",
        fontFamily: "inherit",
        width: "100%",
      }}
    >
      {/* Category pill */}
      <span style={{
        fontSize: "8px",
        fontWeight: 700,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        padding: "2px 6px",
        borderRadius: "5px",
        background: "rgba(74,222,128,0.1)",
        color: "#4ade80",
        border: "1px solid rgba(74,222,128,0.2)",
        flexShrink: 0,
        boxShadow: hovered ? "0 0 8px rgba(74,222,128,0.25)" : "none",
        transition: "box-shadow 0.18s ease",
        whiteSpace: "nowrap",
      }}>
        {scheme.category}
      </span>

      {/* Scheme name */}
      <span style={{
        fontSize: "11.5px",
        color: hovered ? "#e7eaf0" : "#99a0b1",
        fontWeight: 500,
        transition: "color 0.18s ease",
        flex: 1,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}>
        {scheme.name}
      </span>

      <ChevronRight
        size={11}
        color={hovered ? "#4ade80" : "#2a2f3e"}
        style={{ flexShrink: 0, transition: "color 0.18s ease" }}
      />
    </button>
  );
}

/* Section 2 — Verified Knowledge Base */
function VerifiedKnowledgeBase() {
  return (
    <SidebarCard>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "12px" }}>
        <div style={{
          width: "22px", height: "22px",
          borderRadius: "6px",
          background: "rgba(74,222,128,0.12)",
          border: "1px solid rgba(74,222,128,0.2)",
          display: "grid", placeItems: "center",
          flexShrink: 0,
        }}>
          <Database size={11} color="#4ade80" />
        </div>
        <div>
          <div style={{ fontSize: "12px", fontWeight: 600, color: "#e7eaf0", letterSpacing: "-0.01em" }}>
            Verified Knowledge Base
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "1px" }}>
            <span style={{
              width: "5px", height: "5px",
              borderRadius: "50%",
              background: "#4ade80",
              boxShadow: "0 0 6px #4ade80",
              display: "inline-block",
            }} />
            <span style={{ fontSize: "9.5px", color: "#4ade80", fontWeight: 500 }}>Live</span>
          </div>
        </div>
      </div>

      {/* Items */}
      <div style={{ display: "flex", flexDirection: "column", gap: "7px" }}>
        {KB_ITEMS.map(({ icon: Icon, label }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div style={{
              width: "18px", height: "18px",
              borderRadius: "4px",
              background: "#14171f",
              border: "1px solid #1f2330",
              display: "grid", placeItems: "center",
              flexShrink: 0,
            }}>
              <Icon size={9} color="#6b7280" />
            </div>
            <span style={{ fontSize: "11.5px", color: "#99a0b1", fontWeight: 450 }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Footer note */}
      <div style={{
        marginTop: "12px",
        paddingTop: "10px",
        borderTop: "1px solid #1f2330",
        fontSize: "10px",
        color: "#4b5563",
        lineHeight: 1.5,
      }}>
        RAG-backed · Retrieval from official regulatory sources only
      </div>
    </SidebarCard>
  );
}

/* Section 3 — Compliance Guardrails */
function ComplianceGuardrails() {
  return (
    <SidebarCard>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "12px" }}>
        <div style={{
          width: "22px", height: "22px",
          borderRadius: "6px",
          background: "rgba(96,165,250,0.1)",
          border: "1px solid rgba(96,165,250,0.2)",
          display: "grid", placeItems: "center",
          flexShrink: 0,
        }}>
          <Shield size={11} color="#60a5fa" />
        </div>
        <div style={{ fontSize: "12px", fontWeight: 600, color: "#e7eaf0", letterSpacing: "-0.01em" }}>
          Compliance Guardrails
        </div>
      </div>

      {/* Checklist */}
      <div style={{ display: "flex", flexDirection: "column", gap: "7px" }}>
        {GUARDRAILS.map((item) => (
          <div key={item} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <CheckCircle2
              size={13}
              color="#4ade80"
              style={{ flexShrink: 0 }}
            />
            <span style={{ fontSize: "11.5px", color: "#99a0b1", fontWeight: 450 }}>{item}</span>
          </div>
        ))}
      </div>

      {/* Badge */}
      <div style={{
        marginTop: "12px",
        padding: "6px 10px",
        background: "rgba(96,165,250,0.06)",
        border: "1px solid rgba(96,165,250,0.15)",
        borderRadius: "8px",
        fontSize: "10px",
        color: "#60a5fa",
        fontWeight: 500,
        textAlign: "center",
        letterSpacing: "0.02em",
      }}>
        SEBI Compliant · Production Ready
      </div>
    </SidebarCard>
  );
}

/* Section 4 — Suggested Questions */
function SuggestedQuestions({ onPick }) {
  return (
    <SidebarCard>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "10px" }}>
        <MessageSquare size={13} color="#a78bfa" />
        <SectionLabel>Suggested Questions</SectionLabel>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <SuggestedButton key={q} label={q} onPick={onPick} />
        ))}
      </div>
    </SidebarCard>
  );
}

function SuggestedButton({ label, onPick }) {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onPick(label)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 10px",
        background: hovered ? "rgba(167,139,250,0.07)" : "#0a0c11",
        border: `1px solid ${hovered ? "rgba(167,139,250,0.35)" : "#1f2330"}`,
        borderRadius: "9px",
        cursor: "pointer",
        textAlign: "left",
        color: hovered ? "#c4b5fd" : "#99a0b1",
        fontSize: "11.5px",
        fontWeight: 500,
        fontFamily: "inherit",
        transition: "all 0.18s ease",
        boxShadow: hovered ? "0 0 12px rgba(167,139,250,0.1)" : "none",
        width: "100%",
      }}
    >
      <span style={{
        color: hovered ? "#a78bfa" : "#4b5563",
        fontSize: "10px",
        flexShrink: 0,
        transition: "color 0.18s ease",
      }}>→</span>
      {label}
    </button>
  );
}

/* ──────────────────────────────────────────────
   Main Sidebar export
────────────────────────────────────────────── */

import { useState } from "react";

export default function Sidebar({ onPick }) {
  return (
    <aside style={{
      width: "300px",
      minWidth: "300px",
      display: "flex",
      flexDirection: "column",
      gap: "10px",
      position: "sticky",
      top: "72px",
      alignSelf: "start",
      maxHeight: "calc(100vh - 100px)",
      overflowY: "auto",
      paddingRight: "2px",
      scrollbarWidth: "none",
    }}>
      <style>{`
        aside::-webkit-scrollbar { display: none; }
      `}</style>

      <CoveredSchemes onPick={onPick} />
      <VerifiedKnowledgeBase />
      <ComplianceGuardrails />
      <SuggestedQuestions onPick={onPick} />
    </aside>
  );
}
