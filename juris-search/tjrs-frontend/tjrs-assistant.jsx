import { useState, useRef, useEffect, useCallback } from "react";

const ENV_API_BASE = (import.meta.env.VITE_API_BASE || "")
  .trim()
  .replace(/^['\"]|['\"]$/g, "");

function safeOrigin() {
  const origin = String(window.location?.origin || "").trim();
  if (/^https?:\/\//i.test(origin)) return origin;
  const protocol = window.location?.protocol || "https:";
  const host = window.location?.host || "";
  return host ? `${protocol}//${host}` : "";
}

function normalizeApiBase(value) {
  const origin = safeOrigin();
  let base = String(value || "").trim().replace(/^['\"]|['\"]$/g, "");

  if (!base) return origin ? `${origin}/juris-search` : "/juris-search";
  if (base.startsWith("/")) return origin ? `${origin}${base}` : base;
  if (!/^https?:\/\//i.test(base)) {
    return origin ? `${origin}/${base.replace(/^\/+/, "")}` : `/${base.replace(/^\/+/, "")}`;
  }
  return base;
}

const FALLBACK_API_BASE =
  ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : `${safeOrigin()}/juris-search`;

const API_BASE = normalizeApiBase(ENV_API_BASE || FALLBACK_API_BASE).replace(/\/+$/, "");

function apiUrl(path) {
  const normalizedPath = String(path || "").replace(/^\/+/, "");
  return `${API_BASE}/${normalizedPath}`;
}

function sanitizeUploadFilename(name) {
  const normalized = String(name || "")
    .trim()
    .normalize("NFKC")
    .replace(/[\u0000-\u001F\u007F]/g, "")
    .trim();

  const asciiSafe = normalized
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\x20-\x7E]/g, "_")
    .replace(/[\\"]/g, "_")
    .replace(/[^A-Za-z0-9._ -]/g, "_")
    .replace(/\s+/g, " ")
    .trim();

  if (!asciiSafe) return "documento.bin";
  if (asciiSafe.length <= 180) return asciiSafe;

  const extMatch = asciiSafe.match(/(\.[A-Za-z0-9]{1,10})$/);
  const ext = extMatch ? extMatch[1] : "";
  const maxBaseLength = Math.max(1, 180 - ext.length);
  return `${asciiSafe.slice(0, maxBaseLength)}${ext}`;
}

// ── Theme ───────────────────────────────────────────────────────────────────
const T = {
  bg: "#FAFAF8",
  surface: "#FFFFFF",
  surfaceAlt: "#F5F4F0",
  border: "#E8E6E1",
  borderFocus: "#2D2A26",
  text: "#2D2A26",
  textMuted: "#8A8680",
  textLight: "#B5B0A8",
  accent: "#1A5F3A",
  accentLight: "#E8F3ED",
  accentHover: "#15472D",
  danger: "#C4453C",
  dangerLight: "#FDF0EF",
  tag: "#F0EDE7",
  shadow: "0 1px 3px rgba(45,42,38,0.06)",
  shadowLg: "0 8px 32px rgba(45,42,38,0.08)",
  shadowUp: "0 -2px 12px rgba(45,42,38,0.06)",
  radius: "10px",
  radiusSm: "6px",
  font: "'Source Serif 4', 'Georgia', serif",
  fontMono: "'DM Mono', 'Menlo', monospace",
  fontSans: "'DM Sans', 'Helvetica Neue', sans-serif",
};

// ── Responsive hook ─────────────────────────────────────────────────────────
function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < breakpoint : false
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const handler = (e) => setIsMobile(e.matches);
    setIsMobile(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [breakpoint]);
  return isMobile;
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function parseSearchFields(text) {
  const m = text.match(/<search_fields>\s*([\s\S]*?)\s*<\/search_fields>/);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}
function stripSearchFields(text) {
  return text.replace(/<search_fields>[\s\S]*?<\/search_fields>/, "").trim();
}
function Spinner({ size = 14, color = T.accent }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size,
      border: `2px solid ${color}33`, borderTopColor: color,
      borderRadius: "50%", animation: "spin 0.8s linear infinite",
    }} />
  );
}

// ── Field definitions ───────────────────────────────────────────────────────
const FIELDS = [
  { key: "search_text", label: "Termos de Busca", placeholder: "Ex: dano moral, alimentos..." },
  { key: "tipo_processo", label: "Tipo de Processo", placeholder: "Cível, Criminal..." },
  { key: "classe_cnj", label: "Classe CNJ", placeholder: "Apelação Cível, Agravo..." },
  { key: "assunto_cnj", label: "Assunto CNJ", placeholder: "Direito Civil, Penal..." },
  { key: "comarca_origem", label: "Comarca de Origem", placeholder: "Porto Alegre, Caxias..." },
  { key: "relator", label: "Relator", placeholder: "Nome do Desembargador..." },
  { key: "orgao_julgador", label: "Órgão Julgador", placeholder: "Câmara, Turma..." },
  { key: "tipo_decisao", label: "Tipo de Decisão", placeholder: "Acórdão, Monocrática..." },
  { key: "tribunal", label: "Tribunal", placeholder: "TJSP" },
  { key: "search_index", label: "Buscar em", placeholder: "ementa / inteiro_teor" },
  { key: "max_results", label: "Máx. Resultados", placeholder: "20", type: "number" },
];

const DEFAULT_FIELDS = {
  search_text: "", tipo_processo: "", classe_cnj: "", assunto_cnj: "",
  comarca_origem: "", relator: "", orgao_julgador: "", tipo_decisao: "",
  tribunal: "", search_index: "ementa", max_results: 20,
};

// ── SVG Icons ───────────────────────────────────────────────────────────────
const Icons = {
  chat: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  fields: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 21V9" />
    </svg>
  ),
  results: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
    </svg>
  ),
};

// ═════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═════════════════════════════════════════════════════════════════════════════
export default function App() {
  const isMobile = useIsMobile();

  const [messages, setMessages] = useState([{
    role: "assistant",
    content: "Olá! Sou seu assistente de busca de pesquisa jurisprudencial.\n\nDescreva o que procura ou envie um documento (petição, relatório, decisão) para que eu analise e sugira os termos de busca.",
  }]);
  const [input, setInput] = useState("");
  const [fields, setFields] = useState({ ...DEFAULT_FIELDS });
  const [mobileView, setMobileView] = useState("chat");
  const [desktopTab, setDesktopTab] = useState("fields");
  const [results, setResults] = useState([]);
  const [searchStatus, setSearchStatus] = useState(null);
  const [searchError, setSearchError] = useState(null);
  const [isTyping, setIsTyping] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [fieldsHighlight, setFieldsHighlight] = useState(false);

  const chatEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "42px";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [input]);

  // ── Chat ───────────────────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text && !uploadedFile) return;
    let requestUrl = "";
    let uploadStage = "init";
    const userMsg = { role: "user", content: text || `📎 ${uploadedFile.name}` };
    setMessages((p) => [...p, userMsg]);
    setInput("");
    setIsTyping(true);
    try {
      let reply;
      if (uploadedFile) {
        uploadStage = "formdata";
        const fd = new FormData();
        const safeFileName = sanitizeUploadFilename(uploadedFile.file?.name || uploadedFile.name);
        fd.append("file", uploadedFile.file, safeFileName);
        uploadStage = "fetch";
        requestUrl = apiUrl("/api/upload");
        const res = await fetch(requestUrl, { method: "POST", body: fd });
        uploadStage = "response";
        reply = (await res.json()).reply;
        setUploadedFile(null);
      } else {
        const conversation = messages.map((m) => ({ role: m.role, content: m.content }));
        requestUrl = apiUrl("/api/chat");
        const res = await fetch(requestUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, conversation }),
        });
        reply = (await res.json()).reply;
      }
      const parsed = parseSearchFields(reply);
      if (parsed) {
        setFields((p) => {
          const u = { ...p };
          Object.entries(parsed).forEach(([k, v]) => {
            if (v !== null && v !== undefined && k in DEFAULT_FIELDS) u[k] = v;
          });
          return u;
        });
        setFieldsHighlight(true);
        setTimeout(() => setFieldsHighlight(false), 2500);
      }
      const clean = stripSearchFields(reply);
      setMessages((p) => [...p, {
        role: "assistant",
        content: clean + (parsed ? "\n\n✅ Campos de busca atualizados." : ""),
      }]);
    } catch (err) {
      const errorName = err?.name ? `${err.name}: ` : "";
      const errorMessage = err?.message || String(err);
      setMessages((p) => [...p, {
        role: "assistant",
        content: `⚠️ Erro de conexão: ${errorName}${errorMessage}\n\nURL: ${requestUrl || API_BASE}\nEtapa: ${uploadedFile ? uploadStage : "chat"}\nArquivo: ${uploadedFile?.name || "n/a"}\n\nVerifique se o backend está rodando em ${API_BASE}`,
      }]);
    } finally { setIsTyping(false); }
  }, [input, uploadedFile, messages]);

  const handleFileSelect = (e) => {
    const f = e.target.files?.[0];
    if (f) setUploadedFile({ name: f.name, file: f });
    e.target.value = "";
  };
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  // ── Search ─────────────────────────────────────────────────────────────
  const runSearch = async () => {
    if (!fields.search_text && !Object.values(fields).some((v) => v)) return;
    setSearchStatus("running"); setSearchError(null); setResults([]);
    if (isMobile) setMobileView("results"); else setDesktopTab("results");
    try {
      const res = await fetch(apiUrl("/api/search"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      const { job_id } = await res.json();
      const poll = setInterval(async () => {
        try {
          const sd = await (await fetch(apiUrl(`/api/search/status/${job_id}`))).json();
          if (sd.status === "completed") {
            clearInterval(poll);
            const rd = await (await fetch(apiUrl(`/api/results/${job_id}`))).json();
            setResults(rd.results || []); setSearchStatus("completed");
          } else if (sd.status === "error") {
            clearInterval(poll); setSearchError(sd.error); setSearchStatus("error");
          }
        } catch { clearInterval(poll); setSearchStatus("error"); setSearchError("Conexão perdida."); }
      }, 3000);
    } catch (err) { setSearchStatus("error"); setSearchError(err.message); }
  };

  const updateField = (key, value) => setFields((p) => ({ ...p, [key]: value }));
  const clearFields = () => setFields({ ...DEFAULT_FIELDS });

  // ═════════════════════════════════════════════════════════════════════════
  // SUB-COMPONENTS
  // ═════════════════════════════════════════════════════════════════════════

  const ChatView = ({ style }) => (
    <div style={{ display: "flex", flexDirection: "column", background: T.surface, height: "100%", overflow: "hidden", ...style }}>
      {/* Messages */}
      <div style={{
        flex: 1, overflowY: "auto", padding: isMobile ? "14px 12px" : "20px",
        display: "flex", flexDirection: "column", gap: "12px",
        WebkitOverflowScrolling: "touch",
      }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
            background: msg.role === "user" ? T.accent : T.surfaceAlt,
            color: msg.role === "user" ? "#fff" : T.text,
            padding: isMobile ? "11px 14px" : "10px 14px",
            borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
            maxWidth: isMobile ? "90%" : "85%", fontSize: isMobile ? "14.5px" : "13.5px",
            lineHeight: 1.55, whiteSpace: "pre-wrap", wordBreak: "break-word",
            animation: "fadeIn 0.25s ease-out",
          }}>
            {msg.content}
          </div>
        ))}
        {isTyping && (
          <div style={{
            alignSelf: "flex-start", background: T.surfaceAlt,
            padding: "14px 18px", borderRadius: "16px 16px 16px 4px",
            display: "flex", alignItems: "center", gap: "8px",
          }}>
            <Spinner size={12} />
            <span style={{ fontSize: "13px", color: T.textMuted }}>Analisando...</span>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* File chip */}
      {uploadedFile && (
        <div style={{ padding: "0 14px 4px" }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: "6px",
            padding: "5px 12px", borderRadius: "6px",
            background: T.accentLight, color: T.accent,
            fontSize: "12.5px", fontWeight: 500,
          }}>
            📎 {uploadedFile.name}
            <span onClick={() => setUploadedFile(null)}
              style={{ cursor: "pointer", opacity: 0.6, padding: "2px 4px" }}>✕</span>
          </div>
        </div>
      )}

      {/* Input bar */}
      <div style={{
        borderTop: `1px solid ${T.border}`,
        padding: isMobile ? "10px 10px" : "14px 16px",
        paddingBottom: isMobile ? "calc(10px + env(safe-area-inset-bottom, 0px))" : "14px",
        display: "flex", gap: "8px", alignItems: "flex-end", background: T.surface,
      }}>
        <input ref={fileInputRef} type="file"
          accept=".json,.txt,.md,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.bmp"
          style={{ display: "none" }} onChange={handleFileSelect} />
        <button onClick={() => fileInputRef.current?.click()}
          style={{
            background: "transparent", border: `1px solid ${T.border}`,
            borderRadius: T.radiusSm, width: 44, height: 44,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", fontSize: "17px", color: T.textMuted, flexShrink: 0,
          }}>📎</button>
        <textarea ref={textareaRef} value={input}
          onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
          placeholder="Descreva o que procura..."
          rows={1}
          style={{
            flex: 1, resize: "none", border: `1px solid ${T.border}`,
            borderRadius: T.radiusSm, padding: "11px 12px",
            fontSize: isMobile ? "16px" : "13.5px", fontFamily: T.fontSans,
            color: T.text, outline: "none",
            minHeight: "44px", maxHeight: "120px", lineHeight: 1.5,
            background: T.bg, boxSizing: "border-box",
          }} />
        <button onClick={sendMessage} disabled={!input.trim() && !uploadedFile}
          style={{
            background: T.accent, color: "#fff", border: "none",
            borderRadius: T.radiusSm, width: 44, height: 44,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", fontSize: "18px", flexShrink: 0,
            opacity: !input.trim() && !uploadedFile ? 0.35 : 1,
          }}>↑</button>
      </div>
    </div>
  );

  const FieldsView = ({ style }) => (
    <div style={{
      flex: 1, overflowY: "auto", background: T.bg,
      padding: isMobile ? "16px 14px 120px" : "24px 28px",
      WebkitOverflowScrolling: "touch", ...style,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
        <p style={{ fontSize: "12.5px", color: T.textMuted, margin: 0, lineHeight: 1.5, flex: 1 }}>
          Edite os campos antes de buscar.
        </p>
        <button onClick={clearFields} style={{
          background: "transparent", border: "none", fontSize: "12px",
          color: T.danger, cursor: "pointer", padding: "6px 12px",
          borderRadius: T.radiusSm, fontFamily: T.fontSans, whiteSpace: "nowrap",
        }}>Limpar</button>
      </div>

      {FIELDS.map((f) => (
        <div key={f.key} style={{ marginBottom: "14px" }}>
          <label style={{
            display: "block", fontSize: "11px", fontWeight: 600,
            textTransform: "uppercase", letterSpacing: "0.06em",
            color: T.textMuted, marginBottom: "5px", fontFamily: T.fontSans,
          }}>{f.label}</label>
          <input type={f.type || "text"} value={fields[f.key] || ""}
            onChange={(e) => updateField(f.key, f.type === "number" ? parseInt(e.target.value) || "" : e.target.value)}
            placeholder={f.placeholder}
            style={{
              width: "100%", border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm, padding: isMobile ? "12px" : "9px 12px",
              fontSize: isMobile ? "16px" : "13.5px", fontFamily: T.fontSans,
              color: T.text, outline: "none", background: T.surface, boxSizing: "border-box",
            }} />
        </div>
      ))}

      <button onClick={runSearch} disabled={searchStatus === "running"}
        style={{
          width: "100%", padding: isMobile ? "15px" : "12px",
          background: T.accent, color: "#fff", border: "none",
          borderRadius: T.radiusSm, fontSize: isMobile ? "15.5px" : "14px",
          fontWeight: 600, cursor: searchStatus === "running" ? "not-allowed" : "pointer",
          fontFamily: T.fontSans, opacity: searchStatus === "running" ? 0.6 : 1,
          marginTop: "6px", marginBottom: isMobile ? "20px" : "0",
        }}>
        {searchStatus === "running" ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
            <Spinner size={14} color="#fff" /> Buscando...
          </span>
        ) : "Executar Busca"}
      </button>
    </div>
  );

  const ResultsView = ({ style }) => (
    <div style={{
      flex: 1, overflowY: "auto", background: T.bg,
      padding: isMobile ? "12px 10px 120px" : "20px 28px",
      WebkitOverflowScrolling: "touch", ...style,
    }}>
      {searchStatus === "running" && (
        <div style={{
          padding: "12px 14px", background: T.accentLight, borderRadius: T.radiusSm,
          marginBottom: "12px", fontSize: "13px", color: T.accent, fontWeight: 500,
          display: "flex", alignItems: "center", gap: "10px",
        }}>
          <Spinner size={14} color={T.accent} />
          Buscando... pode levar alguns minutos.
        </div>
      )}
      {searchStatus === "error" && (
        <div style={{
          padding: "12px 14px", background: T.dangerLight, borderRadius: T.radiusSm,
          marginBottom: "12px", fontSize: "13px", color: T.danger, fontWeight: 500,
        }}>⚠️ {searchError || "Falha na busca"}</div>
      )}

      {results.length === 0 && searchStatus !== "running" && (
        <div style={{ textAlign: "center", padding: isMobile ? "48px 20px" : "60px 30px", color: T.textLight }}>
          <div style={{ fontSize: "40px", marginBottom: "12px", opacity: 0.4 }}>⚖️</div>
          <div style={{ fontSize: "14px", fontWeight: 500, marginBottom: "6px" }}>
            {searchStatus === "completed" ? "Nenhum resultado" : "Nenhuma busca realizada"}
          </div>
          <div style={{ fontSize: "13px" }}>
            {searchStatus === "completed" ? "Ajuste os termos de busca." : "Configure os campos e execute a busca."}
          </div>
        </div>
      )}

      {results.map((r, i) => (
        <div key={i} style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: T.radius, padding: isMobile ? "14px 12px" : "16px 18px",
          marginBottom: "10px", boxShadow: T.shadow,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
            <div style={{
              fontFamily: T.fontMono, fontSize: isMobile ? "13.5px" : "13px",
              color: T.accent, fontWeight: 600, wordBreak: "break-all", minWidth: 0,
            }}>{r.numero_processo || "—"}</div>
            {r.inteiro_url && (
              <a href={r.inteiro_url} target="_blank" rel="noopener noreferrer"
                style={{
                  fontSize: "11.5px", color: T.accent, textDecoration: "none",
                  fontWeight: 500, padding: isMobile ? "6px 12px" : "4px 10px",
                  borderRadius: "6px", border: `1px solid ${T.accent}33`,
                  whiteSpace: "nowrap", flexShrink: 0,
                }}>Inteiro Teor ↗</a>
            )}
          </div>
          <div style={{ fontSize: "12px", color: T.textMuted, marginTop: "5px", lineHeight: 1.5 }}>
            {[r.tipo_processo, r.relator, r.comarca_origem].filter(Boolean).join(" · ")}
          </div>
          {r.ementa_trecho && (
            <div style={{
              fontSize: isMobile ? "13.5px" : "12.5px", color: T.text,
              marginTop: "8px", lineHeight: 1.55,
              display: "-webkit-box", WebkitLineClamp: isMobile ? 4 : 3,
              WebkitBoxOrient: "vertical", overflow: "hidden",
            }}>{r.ementa_trecho}</div>
          )}
          <div style={{ marginTop: "6px", display: "flex", flexWrap: "wrap", gap: "4px" }}>
            {r.tipo_processo && <span style={{
              padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
              fontWeight: 600, background: T.tag, color: T.textMuted,
            }}>{r.tipo_processo}</span>}
            {r.classe_cnj && <span style={{
              padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
              fontWeight: 600, background: T.tag, color: T.textMuted,
            }}>{r.classe_cnj}</span>}
            {r.ano && <span style={{
              padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
              fontWeight: 600, background: T.tag, color: T.textMuted,
            }}>Ano: {r.ano}</span>}
          </div>
        </div>
      ))}

      {searchStatus === "completed" && results.length > 0 && (
        <div style={{ textAlign: "center", padding: "16px", color: T.textMuted, fontSize: "12.5px" }}>
          {results.length} resultado{results.length !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );

  // ═════════════════════════════════════════════════════════════════════════
  // RENDER
  // ═════════════════════════════════════════════════════════════════════════
  return (
    <div style={{
      height: "100vh", background: T.bg, fontFamily: T.fontSans, color: T.text,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap');
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
        @keyframes pulse { 0%,100%{ opacity:1; } 50%{ opacity:0.5; } }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        html, body { margin:0; padding:0; overscroll-behavior:none; }
        input:focus, textarea:focus { border-color: ${T.borderFocus} !important; }
        ::-webkit-scrollbar { width:5px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:${T.border}; border-radius:3px; }
      `}</style>

      {/* Header */}
      <header style={{
        padding: isMobile ? "12px 14px" : "16px 32px",
        borderBottom: `1px solid ${T.border}`, background: T.surface,
        display: "flex", alignItems: "center", gap: "10px", flexShrink: 0,
      }}>
        <div style={{
          width: isMobile ? 30 : 36, height: isMobile ? 30 : 36,
          borderRadius: "8px", background: T.accent,
          display: "flex", alignItems: "center", justifyContent: "center",
          color: "#fff", fontSize: isMobile ? "13px" : "16px",
          fontWeight: 700, fontFamily: T.font, flexShrink: 0,
        }}>§</div>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontFamily: T.font, fontSize: isMobile ? "14.5px" : "18px",
            fontWeight: 600, letterSpacing: "-0.01em",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {isMobile ? "Jurisprudência" : "Pesquisa Jurisprudencial"}
          </div>
          {!isMobile && (
            <div style={{ fontSize: "12px", color: T.textMuted, marginTop: "1px" }}>
              Assistente inteligente de busca
            </div>
          )}
        </div>
      </header>

      {/* ═══ MOBILE ═══ */}
      {isMobile ? (
        <>
          <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
            {/* Chat */}
            <div style={{
              position: "absolute", inset: 0,
              transform: mobileView === "chat" ? "translateX(0)" : (mobileView === "fields" || mobileView === "results") ? "translateX(-100%)" : "translateX(100%)",
              opacity: mobileView === "chat" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "chat" ? "auto" : "none",
              willChange: "transform",
            }}><ChatView /></div>

            {/* Fields */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "fields" ? "translateX(0)" : mobileView === "chat" ? "translateX(100%)" : "translateX(-100%)",
              opacity: mobileView === "fields" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "fields" ? "auto" : "none",
              willChange: "transform",
            }}><FieldsView /></div>

            {/* Results */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "results" ? "translateX(0)" : "translateX(100%)",
              opacity: mobileView === "results" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "results" ? "auto" : "none",
              willChange: "transform",
            }}><ResultsView /></div>
          </div>

          {/* Bottom Nav */}
          <nav style={{
            display: "flex", background: T.surface,
            borderTop: `1px solid ${T.border}`, boxShadow: T.shadowUp,
            paddingBottom: "env(safe-area-inset-bottom, 8px)",
            flexShrink: 0, position: "relative", zIndex: 10,
          }}>
            {[
              { id: "chat", label: "Chat", icon: Icons.chat },
              { id: "fields", label: "Campos", icon: Icons.fields },
              { id: "results", label: "Resultados", icon: Icons.results },
            ].map((tab) => {
              const active = mobileView === tab.id;
              const highlight = tab.id === "fields" && fieldsHighlight;
              return (
                <button key={tab.id} onClick={() => setMobileView(tab.id)}
                  style={{
                    flex: 1, display: "flex", flexDirection: "column",
                    alignItems: "center", gap: "2px",
                    padding: "10px 0 6px", background: "none", border: "none",
                    cursor: "pointer", position: "relative",
                    animation: highlight ? "pulse 0.6s ease 4" : "none",
                  }}>
                  {tab.icon(active)}
                  <span style={{
                    fontSize: "10px", fontWeight: active ? 600 : 400,
                    color: active ? T.accent : T.textMuted, fontFamily: T.fontSans,
                  }}>{tab.label}</span>
                  {tab.id === "results" && results.length > 0 && (
                    <span style={{
                      position: "absolute", top: 4, right: "calc(50% - 22px)",
                      background: T.accent, color: "#fff",
                      fontSize: "9px", fontWeight: 700,
                      padding: "1px 5px", borderRadius: "8px", minWidth: "16px",
                      textAlign: "center",
                    }}>{results.length}</span>
                  )}
                  {tab.id === "fields" && fieldsHighlight && !active && (
                    <span style={{
                      position: "absolute", top: 4, right: "calc(50% - 18px)",
                      width: 8, height: 8, borderRadius: "50%",
                      background: T.accent, animation: "pulse 0.6s ease infinite",
                    }} />
                  )}
                </button>
              );
            })}
          </nav>
        </>
      ) : (
        /* ═══ DESKTOP ═══ */
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          <div style={{
            width: "420px", minWidth: "360px",
            borderRight: `1px solid ${T.border}`,
            display: "flex", flexDirection: "column",
          }}><ChatView /></div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{
              display: "flex", borderBottom: `1px solid ${T.border}`,
              background: T.surface, padding: "0 24px", flexShrink: 0,
            }}>
              {[
                { id: "fields", label: "Campos de Busca" },
                { id: "results", label: `Resultados${results.length > 0 ? ` (${results.length})` : ""}` },
              ].map((tab) => (
                <button key={tab.id} onClick={() => setDesktopTab(tab.id)}
                  style={{
                    padding: "12px 20px", fontSize: "13px", fontWeight: 500,
                    color: desktopTab === tab.id ? T.accent : T.textMuted,
                    cursor: "pointer", fontFamily: T.fontSans,
                    background: "none", border: "none",
                    borderBottom: `2px solid ${desktopTab === tab.id ? T.accent : "transparent"}`,
                    transition: "all 0.15s",
                    animation: tab.id === "fields" && fieldsHighlight ? "pulse 0.6s ease 3" : "none",
                  }}>{tab.label}</button>
              ))}
            </div>
            {desktopTab === "fields" ? <FieldsView /> : <ResultsView />}
          </div>
        </div>
      )}
    </div>
  );
}
