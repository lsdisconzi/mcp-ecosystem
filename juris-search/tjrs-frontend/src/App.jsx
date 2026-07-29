import { useState, useRef, useEffect, useCallback } from "react";
import MasterIndexBrowseView from "./MasterIndexView";
import MasterIndexDetailView from "./MasterIndexDetailView";
import AdminView from "./AdminView";
import JurisprudenceView from "./JurisprudenceView";

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

  if (!base) return origin ? `${origin}/juris` : "/juris";
  if (base.startsWith("/")) return origin ? `${origin}${base}` : base;
  if (!/^https?:\/\//i.test(base)) {
    return origin ? `${origin}/${base.replace(/^\/+/, "")}` : `/${base.replace(/^\/+/, "")}`;
  }
  return base;
}

const FALLBACK_API_BASE =
  ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : `${safeOrigin()}/juris`;

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

function makeDefaultDownloadFolderName() {
  const now = new Date();
  return `juris_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}${String(now.getSeconds()).padStart(2, "0")}`;
}

function sanitizeFolderName(name) {
  const normalized = String(name || "")
    .trim()
    .normalize("NFKC")
    .replace(/[\u0000-\u001F\u007F]/g, "")
    .replace(/[^\p{L}\p{N}\-_\s.]/gu, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[_\-.]+|[_\-.]+$/g, "")
    .slice(0, 90);

  return normalized;
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
  { key: "search_index", label: "Buscar em", placeholder: "acórdão / inteiro_teor" },
  { key: "max_results", label: "Máx. Resultados", placeholder: "20", type: "number" },
];

const DEFAULT_FIELDS = {
  search_text: "", tipo_processo: "", classe_cnj: "", assunto_cnj: "",
  comarca_origem: "", relator: "", orgao_julgador: "", tipo_decisao: "",
  tribunal: "", search_index: "acórdão", max_results: 20,
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
  download: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" />
    </svg>
  ),
  masterIndex: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  admin: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  juris: (active) => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? T.accent : T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v18" /><path d="M5 7l7-3 7 3" /><path d="M5 7l-2 6a4 4 0 0 0 8 0l-2-6" /><path d="M19 7l-2 6a4 4 0 0 0 8 0l-2-6" /><path d="M7 21h10" />
    </svg>
  ),
};

// Master Index style helpers
const filterSelectStyle = {
  padding: "6px 10px", fontSize: "12px", border: `1px solid ${T.border}`,
  borderRadius: T.radius, background: T.bg, color: T.text, fontFamily: T.fontSans,
  outline: "none", minWidth: "100px",
};

const filterInputStyle = {
  padding: "6px 10px", fontSize: "12px", border: `1px solid ${T.border}`,
  borderRadius: T.radius, background: T.bg, color: T.text, fontFamily: T.fontSans,
  outline: "none", width: "100px",
};

const clearButtonStyle = {
  padding: "6px 12px", fontSize: "12px", border: `1px solid ${T.border}`,
  borderRadius: T.radius, background: T.surface, color: T.textMuted,
  cursor: "pointer", fontFamily: T.fontSans,
};

const pageButtonStyle = (disabled) => ({
  padding: "6px 14px", fontSize: "12px", border: `1px solid ${T.border}`,
  borderRadius: T.radius, background: disabled ? T.bg : T.surface,
  color: disabled ? T.textMuted : T.text, cursor: disabled ? "default" : "pointer",
  fontFamily: T.fontSans, opacity: disabled ? 0.5 : 1,
});

const DEFAULT_TRIBUNAL = "TJSP";

const COURTS = [
  // ── Dedicated scrapers ──────────────────────────────────────────────
  { key: "TJRS", name: "TJRS", fullName: "Tribunal de Justiça do Rio Grande do Sul", region: "South", scraperType: "dedicated" },
  { key: "TJSP", name: "TJSP", fullName: "Tribunal de Justiça de São Paulo", region: "Southeast", scraperType: "dedicated" },
  { key: "STF", name: "STF", fullName: "Supremo Tribunal Federal", region: "Federal", scraperType: "dedicated" },
  { key: "TJMG", name: "TJMG", fullName: "Tribunal de Justiça de Minas Gerais", region: "Southeast", scraperType: "dedicated" },
  { key: "TJRJ", name: "TJRJ", fullName: "Tribunal de Justiça do Rio de Janeiro", region: "Southeast", scraperType: "dedicated" },

  // ── Chile ───────────────────────────────────────────────────────────
  { key: "CL", name: "Chile", fullName: "Poder Judicial de Chile — Buscador Unificado de Fallos", region: "Chile", scraperType: "chile" },

  // ── South ───────────────────────────────────────────────────────────
  { key: "TJSC", name: "TJSC", fullName: "Tribunal de Justiça de Santa Catarina", region: "South", scraperType: "esaj" },
  { key: "TJPR", name: "TJPR", fullName: "Tribunal de Justiça do Paraná", region: "South", scraperType: "esaj" },

  // ── Southeast ────────────────────────────────────────────────────────
  { key: "TJES", name: "TJES", fullName: "Tribunal de Justiça do Espírito Santo", region: "Southeast", scraperType: "esaj" },

  // ── Northeast ────────────────────────────────────────────────────────
  { key: "TJBA", name: "TJBA", fullName: "Tribunal de Justiça da Bahia", region: "Northeast", scraperType: "esaj" },
  { key: "TJPE", name: "TJPE", fullName: "Tribunal de Justiça de Pernambuco", region: "Northeast", scraperType: "esaj" },
  { key: "TJCE", name: "TJCE", fullName: "Tribunal de Justiça do Ceará", region: "Northeast", scraperType: "esaj" },
  { key: "TJMA", name: "TJMA", fullName: "Tribunal de Justiça do Maranhão", region: "Northeast", scraperType: "esaj" },
  { key: "TJPB", name: "TJPB", fullName: "Tribunal de Justiça da Paraíba", region: "Northeast", scraperType: "esaj" },
  { key: "TJRN", name: "TJRN", fullName: "Tribunal de Justiça do Rio Grande do Norte", region: "Northeast", scraperType: "esaj" },
  { key: "TJAL", name: "TJAL", fullName: "Tribunal de Justiça de Alagoas", region: "Northeast", scraperType: "esaj" },
  { key: "TJSE", name: "TJSE", fullName: "Tribunal de Justiça de Sergipe", region: "Northeast", scraperType: "esaj" },
  { key: "TJPI", name: "TJPI", fullName: "Tribunal de Justiça do Piauí", region: "Northeast", scraperType: "esaj" },

  // ── North ────────────────────────────────────────────────────────────
  { key: "TJPA", name: "TJPA", fullName: "Tribunal de Justiça do Pará", region: "North", scraperType: "esaj" },
  { key: "TJAM", name: "TJAM", fullName: "Tribunal de Justiça do Amazonas", region: "North", scraperType: "esaj" },
  { key: "TJRO", name: "TJRO", fullName: "Tribunal de Justiça de Rondônia", region: "North", scraperType: "esaj" },
  { key: "TJTO", name: "TJTO", fullName: "Tribunal de Justiça do Tocantins", region: "North", scraperType: "esaj" },
  { key: "TJAC", name: "TJAC", fullName: "Tribunal de Justiça do Acre", region: "North", scraperType: "esaj" },
  { key: "TJRR", name: "TJRR", fullName: "Tribunal de Justiça de Roraima", region: "North", scraperType: "esaj" },
  { key: "TJAP", name: "TJAP", fullName: "Tribunal de Justiça do Amapá", region: "North", scraperType: "esaj" },

  // ── Center-West ──────────────────────────────────────────────────────
  { key: "TJDFT", name: "TJDFT", fullName: "Tribunal de Justiça do Distrito Federal e Territórios", region: "Center-West", scraperType: "esaj" },
  { key: "TJGO", name: "TJGO", fullName: "Tribunal de Justiça de Goiás", region: "Center-West", scraperType: "esaj" },
  { key: "TJMT", name: "TJMT", fullName: "Tribunal de Justiça do Mato Grosso", region: "Center-West", scraperType: "esaj" },
  { key: "TJMS", name: "TJMS", fullName: "Tribunal de Justiça do Mato Grosso do Sul", region: "Center-West", scraperType: "esaj" },
];

const ALL_COURT_KEYS = COURTS.map((court) => court.key);

function getCourtInfo(key) {
  return COURTS.find((c) => c.key === key) || COURTS[0];
}

function getGreeting(courtKey) {
  const info = getCourtInfo(courtKey);
  return `Olá! Sou seu assistente de pesquisa jurisprudencial.\n\nFonte de pesquisa selecionada: ${info.fullName} (${info.name}).\n\nDescreva o que procura ou envie um documento (petição, relatório, decisão) para que eu analise e sugira os termos de busca.`;
}

function normalizeSelectedCourts(courts) {
  const valid = Array.isArray(courts)
    ? courts.filter((courtKey) => ALL_COURT_KEYS.includes(courtKey))
    : [];
  const unique = [...new Set(valid)];
  return unique.length > 0 ? unique : [DEFAULT_TRIBUNAL];
}

function hasAllCourtsSelected(courts) {
  const normalized = normalizeSelectedCourts(courts);
  return ALL_COURT_KEYS.every((courtKey) => normalized.includes(courtKey));
}

function getSelectionGreeting(selectedCourts) {
  const normalized = normalizeSelectedCourts(selectedCourts);
  if (hasAllCourtsSelected(normalized)) {
    const allNames = ALL_COURT_KEYS.map((k) => getCourtInfo(k).name).join(", ");
    return `Olá! Sou seu assistente de pesquisa jurisprudencial.\n\nFontes de pesquisa selecionadas: ${allNames}.\n\nDescreva o que procura ou envie um documento para que eu sugira campos de busca para todas as fontes marcadas.`;
  }
  if (normalized.length === 1) {
    return getGreeting(normalized[0]);
  }
  return `Olá! Sou seu assistente de pesquisa jurisprudencial.\n\nFontes de pesquisa selecionadas: ${normalized.join(", ")}.\n\nDescreva o que procura ou envie um documento para que eu sugira campos de busca para as fontes marcadas.`;
}

function getSelectionLabel(selectedCourts) {
  const normalized = normalizeSelectedCourts(selectedCourts);
  if (hasAllCourtsSelected(normalized)) return "Todos";
  return normalized.join(", ");
}

function getSelectionFullName(selectedCourts) {
  const normalized = normalizeSelectedCourts(selectedCourts);
  if (hasAllCourtsSelected(normalized)) {
    const allNames = ALL_COURT_KEYS.map((k) => getCourtInfo(k).name).join(", ");
    return `Tribunais selecionados: ${allNames}`;
  }
  return normalized.map((courtKey) => getCourtInfo(courtKey).fullName).join(" • ");
}

function normalizeCourtLabel(value) {
  const raw = String(value || "").trim();
  const upper = raw.toUpperCase();
  if (!raw) return "";

  // Direct match on court key or short name
  const direct = COURTS.find((c) => c.key === upper || c.name === upper);
  if (direct) return direct.key;

  // Substring match (check longer keys first to avoid false positives)
  const sorted = [...COURTS].sort((a, b) => b.key.length - a.key.length);
  for (const c of sorted) {
    if (c.key.length >= 3 && upper.includes(c.key)) return c.key;
  }

  // Chile-specific patterns (CL is too short for safe substring matching)
  if (upper.includes("CHILE") || upper.includes("CORTE SUPREMA") ||
    upper.includes("PODER JUDICIAL") || upper.includes("APELACIONES")) return "CL";

  return raw;
}

function splitClasseAssunto(value) {
  const raw = String(value || "").trim();
  if (!raw) return { classe: "", assunto: "" };

  const separators = [" / ", " - ", " | ", ";", "/", "-"];
  for (const separator of separators) {
    const index = raw.indexOf(separator);
    if (index > 0) {
      return {
        classe: raw.slice(0, index).trim(),
        assunto: raw.slice(index + separator.length).trim(),
      };
    }
  }

  return { classe: raw, assunto: "" };
}

function stripComarcaPrefix(value) {
  return String(value || "").replace(/^de\s+origem:\s*/i, "").trim();
}

function normalizeResultForDisplay(result) {
  const classeAssunto = splitClasseAssunto(result?.classe_assunto);
  const classeCnj = String(result?.classe_cnj || classeAssunto.classe || "").trim();
  const assuntoCnj = String(result?.assunto_cnj || classeAssunto.assunto || "").trim();
  const tipoProcesso = String(result?.tipo_processo || classeCnj || "").trim();

  // Chile-specific fields
  const isChile = (result?.tribunal || result?.court || "").toUpperCase() === "CL";
  const numeroProcesso = String(result?.numero_processo || result?.cdacordao || (isChile ? result?.rol : "") || "").trim();
  const ementaTrecho = String(
    result?.ementa_trecho || result?.ementa || result?.result_description || result?.texto_preview || ""
  ).trim();
  const relator = String(result?.relator || result?.relatora || (isChile ? result?.juez : "") || "").trim();
  const orgaoJulgador = String(result?.orgao_julgador || (isChile ? result?.tribunal : "") || "").trim();
  const dataJulgamento = String(result?.data_julgamento || (isChile ? result?.fecha : "") || "").trim();
  const caratulado = String(result?.caratulado || "").trim();
  const materia = String(result?.materia || "").trim();
  const categoria = String(result?.categoria || "").trim();

  return {
    tribunal: normalizeCourtLabel(result?.tribunal || result?.court),
    numeroProcesso,
    inteiroUrl: String(result?.inteiro_url || "").trim(),
    relator,
    orgaoJulgador,
    comarcaOrigem: stripComarcaPrefix(result?.comarca_origem || result?.comarca),
    dataJulgamento,
    dataPublicacao: String(result?.data_publicacao || "").trim(),
    ementaTrecho,
    tipoProcesso,
    classeCnj,
    assuntoCnj,
    ano: String(result?.ano || "").trim(),
    // Chile-specific
    caratulado,
    materia,
    categoria,
  };
}

function makeResultKey(result, index) {
  return `${result?.numero_processo || "item"}::${result?.inteiro_url || ""}::${index}`;
}

// ═════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═════════════════════════════════════════════════════════════════════════════
export default function App() {
  const isMobile = useIsMobile();
  const [selectedCourts, setSelectedCourts] = useState([DEFAULT_TRIBUNAL]);
  const [showSourceMenu, setShowSourceMenu] = useState(false);

  const normalizedSelection = normalizeSelectedCourts(selectedCourts);
  const primaryCourt = normalizedSelection[0] || DEFAULT_TRIBUNAL;
  const selectionLabel = getSelectionLabel(normalizedSelection);
  const selectionFullName = getSelectionFullName(normalizedSelection);
  const allSourcesSelected = hasAllCourtsSelected(normalizedSelection);

  const [messages, setMessages] = useState([{
    role: "assistant",
    content: getSelectionGreeting([DEFAULT_TRIBUNAL]),
  }]);
  const [input, setInput] = useState("");
  const [fields, setFields] = useState({ ...DEFAULT_FIELDS });
  const [mobileView, setMobileView] = useState("chat");
  const [desktopTab, setDesktopTab] = useState("fields");
  const [results, setResults] = useState([]);
  const [selectedResultKeys, setSelectedResultKeys] = useState(() => new Set());
  const [searchStatus, setSearchStatus] = useState(null);
  const [searchError, setSearchError] = useState(null);
  const [downloadStatus, setDownloadStatus] = useState(null);
  const [downloadError, setDownloadError] = useState(null);
  const [downloadedFiles, setDownloadedFiles] = useState([]);
  const [downloadDir, setDownloadDir] = useState("");
  const [downloadJobId, setDownloadJobId] = useState(null);
  const [downloadFolderName, setDownloadFolderName] = useState(() => makeDefaultDownloadFolderName());
  const [storagePaths, setStoragePaths] = useState(null);
  const [storageError, setStorageError] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [historyStatus, setHistoryStatus] = useState("idle");
  const [historyFilePath, setHistoryFilePath] = useState("");
  const [historySavedAt, setHistorySavedAt] = useState("");
  const [storageSync, setStorageSync] = useState(null);
  const [searchBreakdown, setSearchBreakdown] = useState([]);
  const [searchCourtErrors, setSearchCourtErrors] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [fieldsHighlight, setFieldsHighlight] = useState(false);
  const [showCourtSidebar, setShowCourtSidebar] = useState(false);
  const [courtData, setCourtData] = useState(null);

  // Master Index state
  const [masterView, setMasterView] = useState("browse"); // "browse" | "detail"
  const [selectedMasterDoc, setSelectedMasterDoc] = useState(null);
  const [masterStats, setMasterStats] = useState(null);

  const chatEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const downloadPollRef = useRef(null);
  const sourceMenuRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "42px";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [input]);

  useEffect(() => {
    return () => {
      if (downloadPollRef.current) clearInterval(downloadPollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!showSourceMenu) return undefined;

    const handleOutsideClick = (event) => {
      if (!sourceMenuRef.current?.contains(event.target)) {
        setShowSourceMenu(false);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [showSourceMenu]);

  // ── Court data fetch ───────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(apiUrl("/api/courts"));
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setCourtData(data);
      } catch (_) { /* keep previous data */ }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // ── Master Index handlers ─────────────────────────────────────────────
  const fetchMasterStats = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/master-index/stats"));
      if (res.ok) {
        const data = await res.json();
        if (data.available) setMasterStats(data);
      }
    } catch (_) { /* keep previous */ }
  }, []);

  const handleMasterOpenDoc = useCallback(async (doc) => {
    setSelectedMasterDoc(doc);
    setMasterView("detail");
  }, []);

  const handleMasterNavigateDoc = useCallback(async (proc) => {
    try {
      const res = await fetch(apiUrl(`/api/master-index/document/${encodeURIComponent(proc)}`));
      if (!res.ok) return;
      const doc = await res.json();
      setSelectedMasterDoc(doc);
    } catch (_) { /* ignore */ }
  }, []);

  const handleMasterBackToBrowse = useCallback(() => {
    setMasterView("browse");
    setSelectedMasterDoc(null);
  }, []);

  // Auto-fetch stats on mount
  useEffect(() => {
    fetchMasterStats();
  }, [fetchMasterStats]);

  const applySourceSelection = useCallback((nextSelection) => {
    const normalized = normalizeSelectedCourts(nextSelection);
    setSelectedCourts(normalized);
    setMessages([{ role: "assistant", content: getSelectionGreeting(normalized) }]);
    setFields({ ...DEFAULT_FIELDS, tribunal: normalized.length === 1 ? normalized[0] : "ALL" });
    setResults([]);
    setSelectedResultKeys(new Set());
    setSearchStatus(null);
    setSearchError(null);
    setSearchBreakdown([]);
    setSearchCourtErrors([]);
  }, []);

  const toggleAllSources = useCallback(() => {
    if (hasAllCourtsSelected(normalizedSelection)) {
      applySourceSelection([DEFAULT_TRIBUNAL]);
    } else {
      applySourceSelection(ALL_COURT_KEYS);
    }
  }, [applySourceSelection, normalizedSelection]);

  const toggleSource = useCallback((courtKey) => {
    if (!ALL_COURT_KEYS.includes(courtKey)) return;
    const currentlySelected = normalizeSelectedCourts(normalizedSelection);
    if (currentlySelected.includes(courtKey)) {
      const next = currentlySelected.filter((item) => item !== courtKey);
      applySourceSelection(next.length > 0 ? next : [DEFAULT_TRIBUNAL]);
      return;
    }
    applySourceSelection([...currentlySelected, courtKey]);
  }, [applySourceSelection, normalizedSelection]);

  const refreshStoragePaths = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/storage/paths"));
      if (!res.ok) throw new Error(`Falha ao obter paths (${res.status})`);
      const payload = await res.json();
      setStoragePaths(payload || null);
      setStorageError(null);
    } catch (err) {
      setStorageError(err?.message || "Falha ao carregar paths de storage.");
    }
  }, []);

  const refreshHistoryList = useCallback(async () => {
    setHistoryStatus("loading");
    try {
      const res = await fetch(apiUrl("/api/search/history?limit=12"));
      if (!res.ok) throw new Error(`Falha ao obter histórico (${res.status})`);
      const payload = await res.json();
      setHistoryItems(Array.isArray(payload?.items) ? payload.items : []);
      setHistoryStatus("ready");
    } catch (err) {
      setHistoryStatus("error");
      setHistoryItems([]);
    }
  }, []);

  useEffect(() => {
    refreshStoragePaths();
    refreshHistoryList();
  }, [refreshStoragePaths, refreshHistoryList]);

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
        fd.append("court", primaryCourt);
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
          body: JSON.stringify({ message: text, conversation, court: primaryCourt }),
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
  }, [input, uploadedFile, messages, primaryCourt]);

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
    setSearchBreakdown([]);
    setSearchCourtErrors([]);
    setHistoryFilePath("");
    setHistorySavedAt("");
    setSelectedResultKeys(new Set());
    setDownloadStatus(null); setDownloadError(null); setDownloadedFiles([]); setDownloadDir(""); setDownloadJobId(null);
    if (isMobile) setMobileView("results"); else setDesktopTab("results");
    try {
      const res = await fetch(apiUrl("/api/search"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...fields,
          court: primaryCourt,
          courts: normalizedSelection,
          tribunal: normalizedSelection.length === 1 ? normalizedSelection[0] : "ALL",
        }),
      });
      const { job_id } = await res.json();
      const poll = setInterval(async () => {
        try {
          const sd = await (await fetch(apiUrl(`/api/search/status/${job_id}`))).json();
          if (sd.status === "completed") {
            clearInterval(poll);
            const rd = await (await fetch(apiUrl(`/api/results/${job_id}`))).json();
            setResults(rd.results || []);
            setSearchBreakdown(Array.isArray(rd.per_court) ? rd.per_court : []);
            setSearchCourtErrors(Array.isArray(rd.court_errors) ? rd.court_errors : []);
            setSearchStatus("completed");
            setHistoryFilePath(rd.search_history_path || rd.history_file || "");
            setHistorySavedAt(rd.saved_at || "");
            refreshHistoryList();
          } else if (sd.status === "error") {
            clearInterval(poll);
            setSearchBreakdown(Array.isArray(sd.per_court) ? sd.per_court : []);
            setSearchCourtErrors(Array.isArray(sd.court_errors) ? sd.court_errors : []);
            setSearchError(sd.error);
            setSearchStatus("error");
          }
        } catch { clearInterval(poll); setSearchStatus("error"); setSearchError("Conexão perdida."); }
      }, 3000);
    } catch (err) { setSearchStatus("error"); setSearchError(err.message); }
  };

  const downloadableResults = results.filter((r) => Boolean(r?.inteiro_url));
  const selectedDownloadableResults = results.filter((r, i) => (
    Boolean(r?.inteiro_url) && selectedResultKeys.has(makeResultKey(r, i))
  ));
  const selectedCount = selectedDownloadableResults.length;
  const allDownloadableSelected = downloadableResults.length > 0 && selectedCount === downloadableResults.length;

  const toggleResultSelection = (result, index) => {
    const key = makeResultKey(result, index);
    setSelectedResultKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSelectAllDownloadable = () => {
    if (allDownloadableSelected) {
      setSelectedResultKeys(new Set());
      return;
    }
    const next = new Set();
    results.forEach((r, i) => {
      if (r?.inteiro_url) next.add(makeResultKey(r, i));
    });
    setSelectedResultKeys(next);
  };

  const startDownload = async (mode = "all") => {
    const payloadResults = mode === "selected" ? selectedDownloadableResults : downloadableResults;
    if (!payloadResults.length) {
      setDownloadStatus("error");
      setDownloadError(mode === "selected"
        ? "Selecione pelo menos um resultado com inteiro teor para baixar."
        : "Nenhum resultado com inteiro teor disponível para baixar.");
      if (isMobile) setMobileView("downloads"); else setDesktopTab("downloads");
      return;
    }

    setDownloadStatus("running");
    setDownloadError(null);
    setDownloadedFiles([]);
    setDownloadDir("");
    setDownloadJobId(null);
    setStorageSync(null);
    if (isMobile) setMobileView("downloads"); else setDesktopTab("downloads");

    const folderName = sanitizeFolderName(downloadFolderName) || makeDefaultDownloadFolderName();
    if (folderName !== downloadFolderName) {
      setDownloadFolderName(folderName);
    }

    try {
      const res = await fetch(apiUrl("/api/download"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          results: payloadResults,
          folder_name: folderName,
          tribunal: normalizedSelection.length === 1 ? primaryCourt : null,
        }),
      });
      if (!res.ok) throw new Error(`Falha ao iniciar download (${res.status})`);
      const { job_id } = await res.json();
      setDownloadJobId(job_id);

      if (downloadPollRef.current) clearInterval(downloadPollRef.current);
      downloadPollRef.current = setInterval(async () => {
        try {
          const stRes = await fetch(apiUrl(`/api/download/status/${job_id}`));
          if (!stRes.ok) throw new Error(`Falha ao consultar download (${stRes.status})`);
          const statusPayload = await stRes.json();
          if (statusPayload.status === "completed") {
            clearInterval(downloadPollRef.current);
            downloadPollRef.current = null;
            setDownloadStatus("completed");
            setDownloadedFiles(statusPayload.downloaded_files || []);
            setDownloadDir(statusPayload.download_dir || "");
            setStorageSync(statusPayload.storage_sync || null);
            refreshStoragePaths();
            refreshHistoryList();
          } else if (statusPayload.status === "error") {
            clearInterval(downloadPollRef.current);
            downloadPollRef.current = null;
            setDownloadStatus("error");
            setDownloadError(statusPayload.error || "Falha no download.");
          }
        } catch (err) {
          clearInterval(downloadPollRef.current);
          downloadPollRef.current = null;
          setDownloadStatus("error");
          setDownloadError(err.message || "Falha ao acompanhar download.");
        }
      }, 3000);
    } catch (err) {
      if (downloadPollRef.current) {
        clearInterval(downloadPollRef.current);
        downloadPollRef.current = null;
      }
      setDownloadStatus("error");
      setDownloadError(err.message || "Falha ao iniciar download.");
    }
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
        <input ref={fileInputRef} type="file" id="file-upload" name="file-upload"
          accept=".json,.txt,.md,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.bmp"
          style={{ display: "none" }} onChange={handleFileSelect} />
        <button onClick={() => fileInputRef.current?.click()}
          style={{
            background: "transparent", border: `1px solid ${T.border}`,
            borderRadius: T.radiusSm, width: 44, height: 44,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", fontSize: "17px", color: T.textMuted, flexShrink: 0,
          }}>📎</button>
        <textarea ref={textareaRef} id="chat-input" name="chat-input" value={input}
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
          <label htmlFor={`field-${f.key}`} style={{
            display: "block", fontSize: "11px", fontWeight: 600,
            textTransform: "uppercase", letterSpacing: "0.06em",
            color: T.textMuted, marginBottom: "5px", fontFamily: T.fontSans,
          }}>{f.label}</label>
          <input id={`field-${f.key}`} name={`field-${f.key}`} type={f.type || "text"} value={fields[f.key] || ""}
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
      {historyFilePath && (
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius,
          padding: isMobile ? "10px" : "10px 12px", marginBottom: "12px", boxShadow: T.shadow,
        }}>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "4px" }}>
            Histórico da busca salvo com sucesso.
          </div>
          <div style={{ fontSize: "11.5px", color: T.text, wordBreak: "break-all" }}>
            {historyFilePath}
          </div>
          {historySavedAt && (
            <div style={{ fontSize: "11px", color: T.textMuted, marginTop: "4px" }}>
              {historySavedAt}
            </div>
          )}
        </div>
      )}

      {searchBreakdown.length > 0 && (
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius,
          padding: isMobile ? "10px" : "10px 12px", marginBottom: "12px", boxShadow: T.shadow,
        }}>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "6px" }}>
            Fontes consultadas
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            {searchBreakdown.map((item) => (
              <div key={item.court} style={{ fontSize: "12px", color: T.text }}>
                {item.court}: {item.status === "completed" ? `${item.total || 0} resultado(s)` : `erro (${item.error || "falha"})`}
              </div>
            ))}
          </div>
        </div>
      )}

      {searchCourtErrors.length > 0 && searchStatus === "completed" && (
        <div style={{
          padding: "12px 14px", background: T.dangerLight, borderRadius: T.radiusSm,
          marginBottom: "12px", fontSize: "12.5px", color: T.danger,
        }}>
          Algumas fontes falharam nesta execução. Revise o quadro "Fontes consultadas" para detalhes.
        </div>
      )}

      {results.length > 0 && (
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius,
          padding: isMobile ? "10px" : "12px 14px", marginBottom: "12px", boxShadow: T.shadow,
        }}>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "8px" }}>
            {downloadableResults.length} resultado{downloadableResults.length !== 1 ? "s" : ""} com inteiro teor disponível.
          </div>
          <div style={{ fontSize: "11.5px", color: T.textMuted, marginBottom: "10px", lineHeight: 1.5 }}>
            Padrão exibido: Processo, Tribunal, Relator, Órgão Julgador, Comarca, Data de Julgamento e Ementa.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
            <button onClick={toggleSelectAllDownloadable}
              style={{
                padding: "7px 10px", borderRadius: T.radiusSm,
                border: `1px solid ${T.border}`, background: T.surface,
                color: T.text, fontSize: "12px", cursor: "pointer",
              }}>
              {allDownloadableSelected ? "Limpar seleção" : "Selecionar todos"}
            </button>
            <button onClick={() => startDownload("selected")} disabled={selectedCount === 0 || downloadStatus === "running"}
              style={{
                padding: "7px 10px", borderRadius: T.radiusSm,
                border: `1px solid ${T.accent}55`, background: T.accentLight,
                color: T.accent, fontSize: "12px", cursor: selectedCount === 0 ? "not-allowed" : "pointer",
                opacity: selectedCount === 0 || downloadStatus === "running" ? 0.6 : 1,
              }}>
              Baixar selecionados ({selectedCount})
            </button>
            <button onClick={() => startDownload("all")} disabled={downloadableResults.length === 0 || downloadStatus === "running"}
              style={{
                padding: "7px 10px", borderRadius: T.radiusSm,
                border: "none", background: T.accent,
                color: "#fff", fontSize: "12px", cursor: downloadableResults.length === 0 ? "not-allowed" : "pointer",
                opacity: downloadableResults.length === 0 || downloadStatus === "running" ? 0.6 : 1,
              }}>
              Baixar tudo
            </button>
          </div>
        </div>
      )}

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

      {results.map((r, i) => {
        const normalized = normalizeResultForDisplay(r);
        const isChile = normalized.tribunal === "CL";
        const metaParts = isChile
          ? [
            normalized.caratulado ? `Caratulado: ${normalized.caratulado}` : "",
            normalized.relator ? `Juez(a): ${normalized.relator}` : "",
            normalized.materia ? `Matéria: ${normalized.materia}` : "",
            normalized.dataJulgamento ? `Data: ${normalized.dataJulgamento}` : "",
          ].filter(Boolean)
          : [
            normalized.tipoProcesso,
            normalized.relator ? `Relator(a): ${normalized.relator}` : "",
            normalized.orgaoJulgador ? `Órgão: ${normalized.orgaoJulgador}` : "",
            normalized.comarcaOrigem ? `Comarca: ${normalized.comarcaOrigem}` : "",
            normalized.dataJulgamento ? `Julgamento: ${normalized.dataJulgamento}` : "",
          ].filter(Boolean);
        const selectable = Boolean(normalized.inteiroUrl);
        const selected = selectedResultKeys.has(makeResultKey(r, i));
        return (
          <div key={i} style={{
            background: T.surface, border: `1px solid ${T.border}`,
            borderRadius: T.radius, padding: isMobile ? "14px 12px" : "16px 18px",
            marginBottom: "10px", boxShadow: T.shadow,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
              <div style={{
                fontFamily: T.fontMono, fontSize: isMobile ? "13.5px" : "13px",
                color: T.accent, fontWeight: 600, wordBreak: "break-all", minWidth: 0,
              }}>{normalized.numeroProcesso || "—"}</div>
              {selectable && (
                <label style={{ display: "inline-flex", alignItems: "center", gap: "5px", fontSize: "11px", color: T.textMuted }}>
                  <input
                    type="checkbox"
                    id={`select-result-${i}`}
                    name={`select-result-${i}`}
                    checked={selected}
                    onChange={() => toggleResultSelection(r, i)}
                  />
                  Selecionar
                </label>
              )}
              {normalized.inteiroUrl && (
                <a href={normalized.inteiroUrl} target="_blank" rel="noopener noreferrer"
                  style={{
                    fontSize: "11.5px", color: T.accent, textDecoration: "none",
                    fontWeight: 500, padding: isMobile ? "6px 12px" : "4px 10px",
                    borderRadius: "6px", border: `1px solid ${T.accent}33`,
                    whiteSpace: "nowrap", flexShrink: 0,
                  }}>Inteiro Teor ↗</a>
              )}
            </div>
            {metaParts.length > 0 && (
              <div style={{ fontSize: "12px", color: T.textMuted, marginTop: "5px", lineHeight: 1.5 }}>
                {metaParts.join(" · ")}
              </div>
            )}
            {normalized.ementaTrecho && (
              <div style={{
                fontSize: isMobile ? "13.5px" : "12.5px", color: T.text,
                marginTop: "8px", lineHeight: 1.55,
                display: "-webkit-box", WebkitLineClamp: isMobile ? 4 : 3,
                WebkitBoxOrient: "vertical", overflow: "hidden",
              }}>{normalized.ementaTrecho}</div>
            )}
            <div style={{ marginTop: "6px", display: "flex", flexWrap: "wrap", gap: "4px" }}>
              {normalized.tribunal && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 700, background: T.accentLight, color: T.accent,
              }}>{normalized.tribunal}</span>}
              {normalized.tipoProcesso && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>{normalized.tipoProcesso}</span>}
              {normalized.classeCnj && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>{normalized.classeCnj}</span>}
              {normalized.assuntoCnj && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>{normalized.assuntoCnj}</span>}
              {normalized.dataPublicacao && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>Publicação: {normalized.dataPublicacao}</span>}
              {normalized.ano && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>Ano: {normalized.ano}</span>}
              {normalized.categoria && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>{normalized.categoria}</span>}
              {normalized.materia && <span style={{
                padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px",
                fontWeight: 600, background: T.tag, color: T.textMuted,
              }}>{normalized.materia}</span>}
            </div>
          </div>
        );
      })}

      {searchStatus === "completed" && results.length > 0 && (
        <div style={{ textAlign: "center", padding: "16px", color: T.textMuted, fontSize: "12.5px" }}>
          {results.length} resultado{results.length !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );

  const DownloadsView = ({ style }) => (
    <div style={{
      flex: 1, overflowY: "auto", background: T.bg,
      padding: isMobile ? "12px 10px 120px" : "20px 28px",
      WebkitOverflowScrolling: "touch", ...style,
    }}>
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius,
        padding: isMobile ? "12px" : "14px 16px", boxShadow: T.shadow,
      }}>
        <div style={{ fontSize: "14px", fontWeight: 600, marginBottom: "6px" }}>Downloads de Inteiro Teor</div>
        <div style={{ fontSize: "12px", color: T.textMuted, lineHeight: 1.5, marginBottom: "10px" }}>
          Baixe todos os resultados encontrados ou apenas os selecionados na aba Resultados.
        </div>
        <div style={{ marginBottom: "10px" }}>
          <label htmlFor="download-folder-name" style={{
            display: "block", fontSize: "11px", fontWeight: 600,
            textTransform: "uppercase", letterSpacing: "0.06em",
            color: T.textMuted, marginBottom: "5px", fontFamily: T.fontSans,
          }}>
            Nome da Pasta de Download
          </label>
          <div style={{ display: "flex", gap: "8px" }}>
            <input
              id="download-folder-name" name="download-folder-name"
              value={downloadFolderName}
              onChange={(e) => setDownloadFolderName(e.target.value)}
              placeholder="Ex: pesquisa_juris"
              style={{
                flex: 1,
                border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm,
                padding: "8px 10px",
                fontSize: "12.5px",
                fontFamily: T.fontSans,
                color: T.text,
                background: T.surfaceAlt,
                outline: "none",
              }}
            />
            <button
              onClick={() => setDownloadFolderName(makeDefaultDownloadFolderName())}
              style={{
                padding: "8px 10px",
                borderRadius: T.radiusSm,
                border: `1px solid ${T.border}`,
                background: T.surface,
                color: T.textMuted,
                fontSize: "12px",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              Auto
            </button>
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "10px" }}>
          <button onClick={() => startDownload("all")} disabled={downloadableResults.length === 0 || downloadStatus === "running"}
            style={{
              padding: "8px 12px", borderRadius: T.radiusSm,
              border: "none", background: T.accent, color: "#fff",
              fontSize: "12px", cursor: downloadableResults.length === 0 ? "not-allowed" : "pointer",
              opacity: downloadableResults.length === 0 || downloadStatus === "running" ? 0.6 : 1,
            }}>
            Baixar tudo ({downloadableResults.length})
          </button>
          <button onClick={() => startDownload("selected")} disabled={selectedCount === 0 || downloadStatus === "running"}
            style={{
              padding: "8px 12px", borderRadius: T.radiusSm,
              border: `1px solid ${T.accent}55`, background: T.accentLight,
              color: T.accent, fontSize: "12px",
              cursor: selectedCount === 0 ? "not-allowed" : "pointer",
              opacity: selectedCount === 0 || downloadStatus === "running" ? 0.6 : 1,
            }}>
            Baixar selecionados ({selectedCount})
          </button>
        </div>
        {downloadJobId && (
          <div style={{ fontSize: "11px", color: T.textMuted, marginBottom: "8px" }}>
            Job de download: {downloadJobId}
          </div>
        )}
      </div>

      <div style={{
        marginTop: "12px",
        background: T.surface,
        border: `1px solid ${T.border}`,
        borderRadius: T.radius,
        padding: isMobile ? "12px" : "14px 16px",
        boxShadow: T.shadow,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", gap: "8px" }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: T.text }}>
            Storage Local
          </div>
          <button
            onClick={refreshStoragePaths}
            style={{
              padding: "6px 10px",
              borderRadius: T.radiusSm,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.textMuted,
              fontSize: "11px",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            Atualizar
          </button>
        </div>
        {storageError ? (
          <div style={{ fontSize: "12px", color: T.danger }}>{storageError}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {[
              ["Downloads", storagePaths?.download_dir],
              ["Histórico", storagePaths?.search_history_dir],
              ["DOCX", storagePaths?.docx_dir],
              ["JSON", storagePaths?.json_dir],
              ["Shared", storagePaths?.shared_link_root],
              ["Agents", storagePaths?.agents_link_root],
            ].map(([label, value]) => (
              <div key={label} style={{ fontSize: "11.5px", color: T.textMuted }}>
                <span style={{ color: T.text }}>{label}:</span> {value || "-"}
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{
        marginTop: "12px",
        background: T.surface,
        border: `1px solid ${T.border}`,
        borderRadius: T.radius,
        padding: isMobile ? "12px" : "14px 16px",
        boxShadow: T.shadow,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", gap: "8px" }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: T.text }}>
            Histórico de Buscas
          </div>
          <button
            onClick={refreshHistoryList}
            style={{
              padding: "6px 10px",
              borderRadius: T.radiusSm,
              border: `1px solid ${T.border}`,
              background: T.surface,
              color: T.textMuted,
              fontSize: "11px",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            Atualizar
          </button>
        </div>

        {historyStatus === "loading" && (
          <div style={{ fontSize: "12px", color: T.textMuted }}>Carregando histórico...</div>
        )}
        {historyStatus === "error" && (
          <div style={{ fontSize: "12px", color: T.danger }}>Falha ao carregar histórico.</div>
        )}
        {historyStatus !== "loading" && historyItems.length === 0 && (
          <div style={{ fontSize: "12px", color: T.textMuted }}>Nenhum histórico encontrado.</div>
        )}
        {historyItems.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {historyItems.slice(0, 8).map((item) => (
              <div key={item.filename} style={{
                border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm,
                padding: "8px 10px",
                background: T.surfaceAlt,
              }}>
                <div style={{ fontSize: "11.5px", color: T.text, fontWeight: 600, wordBreak: "break-all" }}>
                  {item.filename}
                </div>
                <div style={{ fontSize: "11px", color: T.textMuted, marginTop: "2px" }}>
                  {item.total || 0} resultado(s) · {item.search_text || "sem termo principal"}
                </div>
                {item.saved_at && (
                  <div style={{ fontSize: "10.5px", color: T.textMuted, marginTop: "2px" }}>
                    {item.saved_at}
                  </div>
                )}
                {item.path && (
                  <div style={{ fontSize: "10.5px", color: T.textMuted, marginTop: "2px", wordBreak: "break-all" }}>
                    {item.path}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {downloadStatus === "running" && (
        <div style={{
          marginTop: "12px", padding: "12px 14px", background: T.accentLight,
          borderRadius: T.radiusSm, display: "flex", alignItems: "center", gap: "10px",
          color: T.accent, fontSize: "13px", fontWeight: 500,
        }}>
          <Spinner size={14} color={T.accent} />
          Baixando arquivos... isso pode levar alguns minutos.
        </div>
      )}

      {downloadStatus === "error" && (
        <div style={{
          marginTop: "12px", padding: "12px 14px", background: T.dangerLight,
          borderRadius: T.radiusSm, color: T.danger, fontSize: "13px", fontWeight: 500,
        }}>
          ⚠️ {downloadError || "Falha no download."}
        </div>
      )}

      {downloadStatus === "completed" && (
        <div style={{
          marginTop: "12px", padding: "12px 14px", background: T.surface,
          border: `1px solid ${T.border}`, borderRadius: T.radiusSm, boxShadow: T.shadow,
        }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: T.accent, marginBottom: "6px" }}>
            ✅ Download concluído
          </div>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "8px" }}>
            {downloadedFiles.length} arquivo{downloadedFiles.length !== 1 ? "s" : ""} salvo{downloadedFiles.length !== 1 ? "s" : ""}.
          </div>
          {downloadDir && (
            <div style={{ fontSize: "12px", color: T.text, marginBottom: "10px", wordBreak: "break-all" }}>
              Pasta: {downloadDir}
            </div>
          )}
          {storageSync && (
            <div style={{
              marginBottom: "10px",
              padding: "8px 10px",
              borderRadius: T.radiusSm,
              background: T.surfaceAlt,
              border: `1px solid ${T.border}`,
              fontSize: "11.5px",
              color: T.textMuted,
              lineHeight: 1.5,
            }}>
              <div>
                DOCX: {storageSync?.docx?.converted_count ?? 0} convertido(s) · {storageSync?.docx?.failed_count ?? 0} falha(s)
              </div>
              <div>
                JSON: {storageSync?.json?.processed_count ?? 0} processado(s) · {storageSync?.json?.failed_count ?? 0} falha(s)
              </div>
            </div>
          )}
          {downloadedFiles.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              {downloadedFiles.slice(0, 30).map((filePath, idx) => (
                <div key={idx} style={{ fontSize: "11.5px", color: T.textMuted, wordBreak: "break-all" }}>
                  {String(filePath).split("/").pop()}
                </div>
              ))}
            </div>
          )}
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
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{
            fontFamily: T.font, fontSize: isMobile ? "14.5px" : "18px",
            fontWeight: 600, letterSpacing: "-0.01em",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            Pesquisa Jurisprudencial
          </div>
          {!isMobile && (
            <div style={{ fontSize: "12px", color: T.textMuted, marginTop: "1px" }}>
              {selectionFullName}
            </div>
          )}
        </div>
        <div ref={sourceMenuRef} style={{ position: "relative", flexShrink: 0 }}>
          <button
            onClick={() => setShowSourceMenu((prev) => !prev)}
            style={{
              padding: isMobile ? "6px 8px" : "7px 10px",
              borderRadius: T.radiusSm,
              border: `1px solid ${showSourceMenu ? T.accent : T.border}`,
              background: T.surfaceAlt,
              color: T.text,
              fontSize: isMobile ? "12px" : "13px",
              fontFamily: T.fontSans,
              cursor: "pointer",
              outline: "none",
              minWidth: isMobile ? "94px" : "140px",
              textAlign: "left",
            }}
          >
          </button>

          {showSourceMenu && (
            <div style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              right: 0,
              zIndex: 40,
              width: isMobile ? "210px" : "280px",
              maxHeight: "70vh",
              overflowY: "auto",
              borderRadius: T.radiusSm,
              border: `1px solid ${T.border}`,
              background: T.surface,
              boxShadow: T.shadowLg,
              padding: "8px",
            }}>
              <label style={{
                display: "flex", alignItems: "center", gap: "8px",
                padding: "7px 8px", borderRadius: "6px", cursor: "pointer",
                fontSize: "12px", color: T.text, fontWeight: 600,
              }}>
                <input
                  id="select-all-sources" name="select-all-sources"
                  type="checkbox"
                  checked={allSourcesSelected}
                  onChange={toggleAllSources}
                />
                Todas as fontes
              </label>

              <div style={{ height: "1px", background: T.border, margin: "6px 0" }} />

              {COURTS.map((item) => (
                <label key={item.key} style={{
                  display: "flex", alignItems: "center", gap: "8px",
                  padding: "7px 8px", borderRadius: "6px", cursor: "pointer",
                  fontSize: "12px", color: T.text,
                }}>
                  <input
                    id={`source-${item.key}`} name={`source-${item.key}`}
                    type="checkbox"
                    checked={normalizedSelection.includes(item.key)}
                    onChange={() => toggleSource(item.key)}
                  />
                  <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
                    <span style={{ fontWeight: 600 }}>{item.name}</span>
                    <span style={{ color: T.textMuted, fontSize: "11px" }}>{item.fullName}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Court sidebar toggle */}
        <button
          onClick={() => setShowCourtSidebar((prev) => !prev)}
          title="Informações das fontes"
          style={{
            padding: isMobile ? "6px 8px" : "7px 10px",
            borderRadius: T.radiusSm,
            border: `1px solid ${showCourtSidebar ? T.accent : T.border}`,
            background: showCourtSidebar ? T.accentLight : T.surfaceAlt,
            color: showCourtSidebar ? T.accent : T.text,
            fontSize: isMobile ? "12px" : "13px",
            fontFamily: T.fontSans,
            cursor: "pointer",
            outline: "none",
            whiteSpace: "nowrap",
          }}
        >
          &#9432; {courtData?.totals?.courts || COURTS.length} fontes
        </button>
      </header>

      {/* ═══ Court Sidebar ═══ */}
      {showCourtSidebar && (
        <>
          <div
            onClick={() => setShowCourtSidebar(false)}
            style={{
              position: "fixed", inset: 0, zIndex: 90,
              background: "rgba(45,42,38,0.35)",
            }}
          />
          <aside style={{
            position: "fixed", top: 0, right: 0, bottom: 0,
            zIndex: 91, width: isMobile ? "100vw" : "360px",
            maxWidth: "100vw",
            background: T.surface,
            borderLeft: `1px solid ${T.border}`,
            boxShadow: T.shadowLg,
            display: "flex", flexDirection: "column",
            animation: "slideInRight 0.25s ease-out",
          }}>
            <style>{`
              @keyframes slideInRight {
                from { transform: translateX(100%); }
                to { transform: translateX(0); }
              }
            `}</style>

            {/* Sidebar header */}
            <div style={{
              padding: "16px 20px", borderBottom: `1px solid ${T.border}`,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              flexShrink: 0,
            }}>
              <div>
                <div style={{ fontFamily: T.font, fontSize: "16px", fontWeight: 600, color: T.text }}>
                  Fontes de Pesquisa
                </div>
                <div style={{ fontSize: "12px", color: T.textMuted, marginTop: "2px" }}>
                  {courtData?.totals?.courts || COURTS.length} tribunais &bull; {courtData?.totals?.documents || 0} documentos indexados
                </div>
              </div>
              <button
                onClick={() => setShowCourtSidebar(false)}
                style={{
                  width: 32, height: 32, borderRadius: T.radiusSm,
                  border: "none", background: T.surfaceAlt,
                  color: T.textMuted, fontSize: "18px",
                  cursor: "pointer", display: "flex",
                  alignItems: "center", justifyContent: "center",
                }}
              >&times;</button>
            </div>

            {/* Sidebar body */}
            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
              {(() => {
                const courts = courtData?.courts || COURTS.map(c => ({
                  key: c.key, name: c.fullName, short_name: c.name,
                  scraper_type: c.scraperType, jurisdiction: c.key === "CL" ? "CL" : "BR",
                  region: c.region, document_count: 0,
                }));

                const groups = [
                  { label: "Brasil — Dedicados", courts: courts.filter(c => c.jurisdiction === "BR" && c.scraper_type === "dedicated") },
                  { label: "Chile", courts: courts.filter(c => c.jurisdiction === "CL") },
                  { label: "Brasil — e-SAJ Sul", courts: courts.filter(c => c.region === "South" && c.scraper_type === "esaj") },
                  { label: "Brasil — e-SAJ Sudeste", courts: courts.filter(c => c.region === "Southeast" && c.scraper_type === "esaj") },
                  { label: "Brasil — e-SAJ Nordeste", courts: courts.filter(c => c.region === "Northeast" && c.scraper_type === "esaj") },
                  { label: "Brasil — e-SAJ Norte", courts: courts.filter(c => c.region === "North" && c.scraper_type === "esaj") },
                  { label: "Brasil — e-SAJ Centro-Oeste", courts: courts.filter(c => c.region === "Center-West" && c.scraper_type === "esaj") },
                ].filter(g => g.courts.length > 0);

                const scraperLabels = { dedicated: "Portal próprio", esaj: "Portal e-SAJ", chile: "Poder Judicial CL" };

                return groups.map((group) => (
                  <div key={group.label} style={{ marginBottom: "20px" }}>
                    <div style={{
                      fontSize: "11px", fontWeight: 600, color: T.textMuted,
                      textTransform: "uppercase", letterSpacing: "0.06em",
                      marginBottom: "8px", paddingLeft: "4px",
                    }}>
                      {group.label}
                    </div>
                    {group.courts.map((c) => {
                      const isSelected = normalizedSelection.includes(c.key);
                      return (
                        <div
                          key={c.key}
                          onClick={() => { toggleSource(c.key); }}
                          style={{
                            padding: "8px 10px", borderRadius: T.radiusSm,
                            marginBottom: "4px", cursor: "pointer",
                            background: isSelected ? T.accentLight : "transparent",
                            border: `1px solid ${isSelected ? T.accent : "transparent"}`,
                            display: "flex", alignItems: "center",
                            justifyContent: "space-between",
                            transition: "background 0.15s, border-color 0.15s",
                          }}
                        >
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{
                              fontSize: "12.5px", fontWeight: 600, color: T.text,
                              display: "flex", alignItems: "center", gap: "6px",
                            }}>
                              {c.key}
                              {c.document_count > 0 && (
                                <span style={{
                                  fontSize: "10px", padding: "1px 6px",
                                  borderRadius: "10px", background: T.tag,
                                  color: T.textMuted, fontWeight: 500,
                                }}>
                                  {c.document_count} docs
                                </span>
                              )}
                            </div>
                            <div style={{
                              fontSize: "11px", color: T.textMuted,
                              whiteSpace: "nowrap", overflow: "hidden",
                              textOverflow: "ellipsis", marginTop: "1px",
                            }}>
                              {c.name}
                            </div>
                          </div>
                          <span style={{
                            fontSize: "10px", color: T.textLight,
                            background: T.surfaceAlt, padding: "2px 6px",
                            borderRadius: "4px", flexShrink: 0, marginLeft: "8px",
                          }}>
                            {scraperLabels[c.scraper_type] || c.scraper_type}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ));
              })()}
            </div>
          </aside>
        </>
      )}

      {/* ═══ MOBILE ═══ */}
      {isMobile ? (
        <>
          <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
            {/* Chat */}
            <div style={{
              position: "absolute", inset: 0,
              transform: mobileView === "chat" ? "translateX(0)" : (mobileView === "fields" || mobileView === "results" || mobileView === "downloads" || mobileView === "mindex") ? "translateX(-100%)" : "translateX(100%)",
              opacity: mobileView === "chat" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "chat" ? "auto" : "none",
              willChange: "transform",
            }}>{ChatView({})}</div>

            {/* Fields */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "fields" ? "translateX(0)" : mobileView === "chat" ? "translateX(100%)" : "translateX(-100%)",
              opacity: mobileView === "fields" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "fields" ? "auto" : "none",
              willChange: "transform",
            }}>{FieldsView({})}</div>

            {/* Results */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "results" ? "translateX(0)" : mobileView === "downloads" ? "translateX(-100%)" : "translateX(100%)",
              opacity: mobileView === "results" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "results" ? "auto" : "none",
              willChange: "transform",
            }}>{ResultsView({})}</div>

            {/* Downloads */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "downloads" ? "translateX(0)" : "translateX(100%)",
              opacity: mobileView === "downloads" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "downloads" ? "auto" : "none",
              willChange: "transform",
            }}>{DownloadsView({})}</div>

            {/* Master Index */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "mindex" ? "translateX(0)" : "translateX(100%)",
              opacity: mobileView === "mindex" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "mindex" ? "auto" : "none",
              willChange: "transform",
            }}>
              {masterView === "detail" && selectedMasterDoc
                ? <MasterIndexDetailView apiBase={API_BASE} doc={selectedMasterDoc} onBack={handleMasterBackToBrowse} onNavigateDoc={handleMasterNavigateDoc} isMobile={true} T={T} />
                : <MasterIndexBrowseView apiBase={API_BASE} masterStats={masterStats} onOpenDoc={handleMasterOpenDoc} isMobile={true} T={T} filterInputStyle={filterInputStyle} />}
            </div>

            {/* Admin */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "admin" ? "translateX(0)" : "translateX(100%)",
              opacity: mobileView === "admin" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "admin" ? "auto" : "none",
              willChange: "transform",
            }}>
              <AdminView apiBase={API_BASE} isMobile={true} T={T} />
            </div>

            {/* Jurisprudência (expanded master index) */}
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              transform: mobileView === "juris" ? "translateX(0)" : "translateX(100%)",
              opacity: mobileView === "juris" ? 1 : 0,
              transition: "transform 0.3s cubic-bezier(.4,0,.2,1), opacity 0.2s ease",
              pointerEvents: mobileView === "juris" ? "auto" : "none",
              willChange: "transform",
            }}>
              <JurisprudenceView apiBase={API_BASE} isMobile={true} T={T} />
            </div>
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
              { id: "downloads", label: "Download", icon: Icons.download },
              { id: "mindex", label: "Índice", icon: Icons.masterIndex },
              { id: "juris", label: "Juris", icon: Icons.juris },
              { id: "admin", label: "Admin", icon: Icons.admin },
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
          }}>{ChatView({})}</div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{
              display: "flex", borderBottom: `1px solid ${T.border}`,
              background: T.surface, padding: "0 24px", flexShrink: 0,
            }}>
              {[
                { id: "fields", label: "Campos de Busca" },
                { id: "results", label: `Resultados${results.length > 0 ? ` (${results.length})` : ""}` },
                { id: "downloads", label: "Downloads" },
                { id: "mindex", label: "Índice Mestre" },
                { id: "juris", label: "Jurisprudência" },
                { id: "admin", label: "Admin" },
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
            {desktopTab === "mindex"
              ? (masterView === "detail" && selectedMasterDoc
                ? <MasterIndexDetailView apiBase={API_BASE} doc={selectedMasterDoc} onBack={handleMasterBackToBrowse} onNavigateDoc={handleMasterNavigateDoc} isMobile={false} T={T} />
                : <MasterIndexBrowseView apiBase={API_BASE} masterStats={masterStats} onOpenDoc={handleMasterOpenDoc} isMobile={false} T={T} filterInputStyle={filterInputStyle} />)
              : desktopTab === "admin"
                ? <AdminView apiBase={API_BASE} isMobile={false} T={T} />
                : desktopTab === "juris"
                  ? <JurisprudenceView apiBase={API_BASE} isMobile={false} T={T} />
                  : desktopTab === "fields" ? FieldsView({}) : desktopTab === "results" ? ResultsView({}) : DownloadsView({})}
          </div>
        </div>
      )}
    </div>
  );
}
