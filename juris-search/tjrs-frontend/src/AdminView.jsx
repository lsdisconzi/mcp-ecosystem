import { useState, useEffect, useCallback } from "react";

function apiUrl(base, path) {
  const normalizedPath = String(path || "").replace(/^\/+/, "");
  return `${base}/${normalizedPath}`;
}

function Spinner({ size = 14, color = "#1A5F3A" }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size,
      border: `2px solid ${color}33`, borderTopColor: color,
      borderRadius: "50%", animation: "spin 0.8s linear infinite",
    }} />
  );
}

const API_TESTER_ENDPOINTS = [
  { label: "GET /api/stats", path: "/api/stats" },
  { label: "GET /api/courts", path: "/api/courts" },
  { label: "GET /api/master-index/stats", path: "/api/master-index/stats" },
  { label: "GET /api/storage/paths", path: "/api/storage/paths" },
  { label: "GET /api/docx/index", path: "/api/docx/index" },
  { label: "GET /api/json/index", path: "/api/json/index" },
  { label: "GET /api/search/history?limit=5", path: "/api/search/history?limit=5" },
  { label: "GET /api/admin/qdrant-collections", path: "/api/admin/qdrant-collections" },
];

export default function AdminView({ apiBase, isMobile, T }) {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [courts, setCourts] = useState(null);
  const [masterStats, setMasterStats] = useState(null);
  const [docxIndex, setDocxIndex] = useState(null);
  const [jsonIndex, setJsonIndex] = useState(null);
  const [storagePaths, setStoragePaths] = useState(null);
  const [qdrantCollections, setQdrantCollections] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [actionStatus, setActionStatus] = useState(null);
  const [actionRunning, setActionRunning] = useState(null);
  const [apiTesterEndpoint, setApiTesterEndpoint] = useState(API_TESTER_ENDPOINTS[0].label);
  const [apiTesterResponse, setApiTesterResponse] = useState(null);
  const [apiTesterLoading, setApiTesterLoading] = useState(false);

  // PDF upload -> extract + ingest to Qdrant
  const [pdfFile, setPdfFile] = useState(null);
  const [pdfTribunal, setPdfTribunal] = useState("TJPR");
  const [pdfUploading, setPdfUploading] = useState(false);
  const [pdfProcessing, setPdfProcessing] = useState(false);
  const [pdfFileId, setPdfFileId] = useState(null);
  const [pdfStatus, setPdfStatus] = useState(null); // { error, message, details }

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    const fetchers = [
      { key: "stats", url: "/api/stats" },
      { key: "courts", url: "/api/courts" },
      { key: "masterStats", url: "/api/master-index/stats" },
      { key: "docxIndex", url: "/api/docx/index" },
      { key: "jsonIndex", url: "/api/json/index" },
      { key: "storagePaths", url: "/api/storage/paths" },
      { key: "qdrantCollections", url: "/api/admin/qdrant-collections" },
      { key: "historyItems", url: "/api/search/history?limit=5" },
    ];
    const results = await Promise.allSettled(
      fetchers.map(f => fetch(apiUrl(apiBase, f.url)).then(r => r.ok ? r.json() : null).catch(() => null))
    );
    results.forEach((r, i) => {
      if (r.status !== "fulfilled" || !r.value) return;
      const key = fetchers[i].key;
      const data = r.value;
      if (key === "stats") setStats(data);
      else if (key === "courts") setCourts(data);
      else if (key === "masterStats") setMasterStats(data);
      else if (key === "docxIndex") setDocxIndex(data);
      else if (key === "jsonIndex") setJsonIndex(data);
      else if (key === "storagePaths") setStoragePaths(data);
      else if (key === "qdrantCollections") setQdrantCollections(data);
      else if (key === "historyItems") setHistoryItems(Array.isArray(data?.items) ? data.items : []);
    });
    setLoading(false);
  }, [apiBase]);

  useEffect(() => { fetchAllData(); }, [fetchAllData]);

  const runAction = async (label, url, options = {}) => {
    setActionRunning(label);
    setActionStatus(null);
    try {
      const res = await fetch(apiUrl(apiBase, url), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `Status ${res.status}`);
      setActionStatus({ type: label, message: JSON.stringify(data, null, 2), error: false });
      setTimeout(() => fetchAllData(), 1000);
    } catch (err) {
      setActionStatus({ type: label, message: err.message, error: true });
    } finally {
      setActionRunning(null);
    }
  };

  const testEndpoint = async () => {
    setApiTesterLoading(true);
    setApiTesterResponse(null);
    try {
      const ep = API_TESTER_ENDPOINTS.find(e => e.label === apiTesterEndpoint);
      const res = await fetch(apiUrl(apiBase, ep.path));
      const data = await res.json();
      setApiTesterResponse({ ok: res.ok, status: res.status, body: data });
    } catch (err) {
      setApiTesterResponse({ ok: false, error: err.message });
    } finally {
      setApiTesterLoading(false);
    }
  };

  // ── PDF upload + ingest ─────────────────────────────────────────────────────
  const handlePdfFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setPdfFile(e.target.files[0]);
      setPdfStatus(null);
      setPdfFileId(null);
    }
  };

  const handlePdfUpload = async () => {
    if (!pdfFile) return;
    setPdfUploading(true);
    setPdfStatus(null);
    try {
      const formData = new FormData();
      formData.append("pdf", pdfFile);
      const res = await fetch(apiUrl(apiBase, "/api/ingest-pdf/upload"), {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `Status ${res.status}`);
      setPdfFileId(data.fileId);
      setPdfStatus({ error: false, message: `Arquivo enviado: ${data.filename}` });
    } catch (err) {
      setPdfStatus({ error: true, message: err.message });
    } finally {
      setPdfUploading(false);
    }
  };

  const handlePdfProcess = async () => {
    if (!pdfFileId) return;
    setPdfProcessing(true);
    setPdfStatus(null);
    try {
      const res = await fetch(apiUrl(apiBase, "/api/ingest-pdf/process"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fileId: pdfFileId, tribunal: pdfTribunal }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `Status ${res.status}`);
      setPdfStatus({
        error: !data.ok,
        message:
          `Processado: ${data.casesExtracted} caso(s) extraído(s), ` +
          `${data.jsonWritten} JSON(s) salvos, ${data.ingested} ingerido(s)` +
          `${data.failed ? `, ${data.failed} falha(s)` : ""}` +
          `${data.masterIndexUpdated ? ". Índice mestre atualizado." : ""}.`,
        details: data.details,
      });
      // Refresh the System Overview so the Qdrant vector count updates.
      setTimeout(() => fetchAllData(), 1000);
    } catch (err) {
      setPdfStatus({ error: true, message: err.message });
    } finally {
      setPdfProcessing(false);
    }
  };

  const sectionStyle = {
    background: T.surface, border: `1px solid ${T.border}`,
    borderRadius: T.radius, padding: isMobile ? "12px" : "14px 16px",
    marginBottom: "14px", boxShadow: T.shadow,
  };

  const sectionTitleStyle = {
    fontSize: "13px", fontWeight: 600, color: T.text,
    marginBottom: "10px", fontFamily: T.fontSans,
    display: "flex", alignItems: "center", gap: "8px",
  };

  if (loading) {
    return (
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        background: T.bg, gap: "10px",
      }}>
        <Spinner size={18} color={T.accent} />
        <span style={{ fontSize: "13px", color: T.textMuted }}>Carregando dados administrativos...</span>
      </div>
    );
  }

  // ── Pipeline stage helper ──────────────────────────────────────────────────
  function stageStatusColor(ok, hasErrors) {
    if (hasErrors) return T.danger;
    if (ok) return "#2D8A4E";
    return T.textMuted;
  }

  const pipelineStages = [
    {
      label: "Search", labelPt: "Busca",
      ok: historyItems.length > 0,
      count: historyItems.length ? `${historyItems.length} jobs` : "0",
      time: historyItems[0]?.saved_at?.slice(0, 10) || null,
    },
    {
      label: "Download", labelPt: "Download",
      ok: (stats?.downloaded_files || 0) > 0,
      count: `${stats?.downloaded_files || 0} files`,
      time: null,
    },
    {
      label: "DOCX Pipeline", labelPt: "DOCX",
      ok: (docxIndex?.ready_entries || docxIndex?.total_entries || 0) > 0,
      hasErrors: (docxIndex?.failed_entries || 0) > 0,
      count: `${docxIndex?.ready_entries || 0}/${docxIndex?.total_entries || 0}`,
      time: docxIndex?.index_generated_at?.slice(0, 10) || docxIndex?.generated_at?.slice(0, 10) || null,
    },
    {
      label: "JSON Pipeline", labelPt: "JSON",
      ok: (jsonIndex?.ready_entries || jsonIndex?.total_entries || 0) > 0,
      hasErrors: (jsonIndex?.failed_entries || 0) > 0,
      count: `${jsonIndex?.ready_entries || 0}/${jsonIndex?.total_entries || 0}`,
      time: jsonIndex?.index_generated_at?.slice(0, 10) || jsonIndex?.generated_at?.slice(0, 10) || null,
    },
    {
      label: "Court Extraction", labelPt: "Extração",
      ok: (masterStats?.total_documents || 0) > 0,
      count: `${masterStats?.total_documents || 0} docs`,
      time: null,
    },
    {
      label: "Qdrant Ingestion", labelPt: "Qdrant",
      ok: qdrantCollections?.ok ?? null,
      count: qdrantCollections?.total != null ? `${qdrantCollections.total} colls` : "?",
      time: masterStats?.qdrant?.ok ? (masterStats?.last_scan?.ran_at?.slice(0, 10) || null) : null,
    },
    {
      label: "Master Index", labelPt: "Índice",
      ok: masterStats?.available,
      count: `${masterStats?.total_documents || 0} docs`,
      time: masterStats?.generated_at?.slice(0, 10) || null,
    },
    {
      label: "Export Links", labelPt: "Links",
      ok: stats?.links_enabled,
      count: stats?.links_enabled ? "on" : "off",
      time: null,
    },
  ];

  return (
    <div style={{
      flex: 1, overflowY: "auto", background: T.bg,
      padding: isMobile ? "12px 10px 120px" : "20px 28px",
      WebkitOverflowScrolling: "touch",
    }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: "12px",
      }}>
        <div>
          <div style={{ fontFamily: T.font, fontSize: isMobile ? "15px" : "17px", fontWeight: 600, color: T.text }}>
            Administração do Sistema
          </div>
          <div style={{ fontSize: "11px", color: T.textMuted, marginTop: "2px" }}>
            Pipeline · Qdrant · Endpoints
          </div>
        </div>
        <button onClick={fetchAllData} style={{
          padding: "6px 12px", borderRadius: T.radiusSm,
          border: `1px solid ${T.border}`, background: T.surface,
          color: T.textMuted, fontSize: "11px", cursor: "pointer",
          fontFamily: T.fontSans,
        }}>Atualizar</button>
      </div>

      {/* ═══ Section 1: System Overview ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> Visão Geral do Sistema
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {[
            ["Total Docs", masterStats?.total_documents || 0],
            ["Tribunais", courts?.totals?.courts || 0],
            ["Jobs Ativos", stats?.jobs_running || 0],
            ["Jobs Completos", stats?.jobs_completed || 0],
            ["Histórico", String(stats?.search_history_count || 0)],
            ["DOCX Ready", String(docxIndex?.ready_entries || 0)],
            ["JSON Ready", String(jsonIndex?.ready_entries || 0)],
            ["Qdrant Vectors", String((qdrantCollections?.ok && Array.isArray(qdrantCollections?.collections))
              ? qdrantCollections.collections.reduce((s, c) => s + (c.vectors_count || 0), 0) : 0)],
            ["Último Scan", masterStats?.last_scan?.ran_at?.slice(0, 10) || "-"],
          ].map(([label, value]) => (
            <div key={label} style={{
              background: T.surfaceAlt, border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm, padding: "8px 12px",
              textAlign: "center", minWidth: isMobile ? "60px" : "80px",
              flex: isMobile ? "1 1 40%" : "none",
            }}>
              <div style={{ fontSize: isMobile ? "15px" : "18px", fontWeight: 700, color: T.accent }}>
                {value ?? "-"}
              </div>
              <div style={{ fontSize: "9.5px", color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                {label}
              </div>
            </div>
          ))}
        </div>

        {/* Top tribunals row */}
        {masterStats?.by_tribunal && (
          <div style={{
            marginTop: "12px", display: "flex", flexWrap: "wrap", gap: "8px",
          }}>
            {Object.entries(masterStats.by_tribunal)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 6)
              .map(([trib, count]) => (
                <span key={trib} style={{
                  padding: "3px 10px", borderRadius: "12px",
                  fontSize: "11px", fontWeight: 600,
                  background: T.accentLight, color: T.accent,
                }}>
                  {trib}: {count}
                </span>
              ))}
          </div>
        )}
      </div>

      {/* ═══ Section 2: Pipeline Diagram ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> Status do Pipeline
        </div>
        <div style={{
          display: "flex", alignItems: "flex-start", gap: "0px",
          overflowX: "auto", paddingBottom: "6px",
        }}>
          {pipelineStages.map((stage, i) => (
            <div key={stage.label} style={{ display: "flex", alignItems: "flex-start" }}>
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                padding: "6px 5px", minWidth: isMobile ? "52px" : "72px",
                background: T.surfaceAlt, borderRadius: T.radiusSm,
                border: `1px solid ${T.border}`, flexShrink: 0,
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: "50%",
                  background: stageStatusColor(stage.ok, stage.hasErrors),
                  marginBottom: "3px",
                }} />
                <div style={{
                  fontSize: "9px", fontWeight: 600, color: T.text,
                  textAlign: "center", lineHeight: 1.2,
                }}>
                  {stage.labelPt}
                </div>
                <div style={{
                  fontSize: "8.5px", color: T.textMuted, textAlign: "center",
                  marginTop: "1px", lineHeight: 1.2,
                }}>
                  {stage.count}
                </div>
                {stage.time && (
                  <div style={{
                    fontSize: "8px", color: T.textLight, textAlign: "center",
                    marginTop: "1px",
                  }}>
                    {stage.time}
                  </div>
                )}
              </div>
              {i < pipelineStages.length - 1 && (
                <div style={{
                  display: "flex", alignItems: "center",
                  padding: "0 1px", color: T.textLight,
                  flexShrink: 0, marginTop: "12px",
                }}>
                  <span style={{ fontSize: "14px" }}>&#8594;</span>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div style={{
          marginTop: "10px", display: "flex", gap: "14px", fontSize: "10px", color: T.textMuted,
        }}>
          <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#2D8A4E", display: "inline-block" }} />
            OK
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: T.danger, display: "inline-block" }} />
            Erro
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: T.textMuted, display: "inline-block" }} />
            Indisponível
          </span>
        </div>
      </div>

      {/* ═══ Section 3: Qdrant Collections ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> Coleções Qdrant
        </div>
        {qdrantCollections?.ok && Array.isArray(qdrantCollections?.collections) ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            {/* Header */}
            <div style={{
              display: "flex", gap: "8px", fontSize: "10px", fontWeight: 600,
              color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.05em",
              padding: "0 4px",
            }}>
              <span style={{ flex: 3 }}>Collection</span>
              <span style={{ flex: 1, textAlign: "center" }}>Points</span>
              <span style={{ flex: 1, textAlign: "center" }}>Dim</span>
            </div>
            {qdrantCollections.collections.map((c) => (
              <div key={c.name} style={{
                display: "flex", alignItems: "center", gap: "10px",
                padding: "6px 8px", borderRadius: T.radiusSm,
                background: T.surfaceAlt, border: `1px solid ${T.border}`,
              }}>
                <span style={{
                  fontFamily: T.fontMono, fontSize: "11px", fontWeight: 600, color: T.text,
                  flex: 3, wordBreak: "break-all",
                }}>{c.name}</span>
                <span style={{ flex: 1, textAlign: "center", fontSize: "12px", fontWeight: 700, color: T.accent, fontFamily: T.fontMono }}>
                  {c.vectors_count ?? "-"}
                </span>
                <span style={{ flex: 1, textAlign: "center", fontSize: "11px", color: T.textMuted }}>
                  {c.vector_size != null ? `${c.vector_size}d` : "-"}
                </span>
              </div>
            ))}
            <div style={{ fontSize: "10px", color: T.textMuted, textAlign: "right", marginTop: "2px" }}>
              {qdrantCollections.total} collection(s)
            </div>
          </div>
        ) : qdrantCollections?.ok === false ? (
          <div style={{
            padding: "8px 10px", borderRadius: T.radiusSm,
            background: T.dangerLight, color: T.danger,
            fontSize: "11px",
          }}>
            Qdrant unreachable: {qdrantCollections.error}
          </div>
        ) : (
          <div style={{ fontSize: "12px", color: T.textMuted }}>Dados de coleções Qdrant indisponíveis.</div>
        )}
      </div>

      {/* ═══ Section 4: Admin Actions ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> Ações Administrativas
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {[
            { label: "Rebuild Master Index", url: "/api/master-index/rebuild", body: {}, variant: "primary" },
            { label: "Force Re-ingest Qdrant", url: "/api/master-index/rebuild", body: { force_ingest: true }, variant: "accent" },
            { label: "Rebuild Storage", url: "/api/storage/rebuild", body: {}, variant: "primary" },
            { label: "Rebuild DOCX", url: "/api/docx/rebuild", body: {}, variant: "secondary" },
            { label: "Rebuild JSON", url: "/api/json/rebuild", body: {}, variant: "secondary" },
            { label: "Pause Ingestion", url: "/api/master-index/pause", body: {}, variant: "danger" },
            { label: "Resume Ingestion", url: "/api/master-index/resume", body: {}, variant: "primary" },
          ].map(({ label, url, body, variant }) => {
            const isRunning = actionRunning === label;
            const bg = variant === "danger" ? T.danger : variant === "secondary" ? T.surfaceAlt : T.accent;
            const fg = variant === "secondary" ? T.text : "#fff";
            const border = variant === "secondary" ? `1px solid ${T.border}` : "none";
            return (
              <button key={label} onClick={() => runAction(label, url, { body })}
                disabled={!!actionRunning}
                style={{
                  padding: "7px 14px", borderRadius: T.radiusSm,
                  border, background: bg, color: fg,
                  fontSize: "11.5px", fontWeight: 500, cursor: actionRunning ? "not-allowed" : "pointer",
                  fontFamily: T.fontSans, opacity: actionRunning ? 0.6 : 1,
                  display: "inline-flex", alignItems: "center", gap: "6px",
                }}>
                {isRunning && <Spinner size={11} color={fg} />}
                {label}
              </button>
            );
          })}
        </div>

        {/* Ingestion pause state */}
        {masterStats?.pause && (
          <div style={{
            marginTop: "10px", padding: "6px 10px", borderRadius: T.radiusSm,
            background: masterStats.pause.paused ? T.dangerLight : T.accentLight,
            fontSize: "11px", color: masterStats.pause.paused ? T.danger : T.accent,
          }}>
            {masterStats.pause.paused
              ? `Ingestion suspended: ${(masterStats.pause.paused_collections || []).join(", ") || "all"}`
              : "Ingestion active"}
          </div>
        )}

        {/* Action status */}
        {actionStatus && (
          <div style={{
            marginTop: "10px", padding: "8px 12px", borderRadius: T.radiusSm,
            background: actionStatus.error ? T.dangerLight : T.accentLight,
            border: `1px solid ${actionStatus.error ? T.danger : T.accent}33`,
          }}>
            <div style={{
              fontSize: "11px", fontWeight: 600,
              color: actionStatus.error ? T.danger : T.accent,
              marginBottom: "4px",
            }}>
              {actionStatus.error ? "Falha" : "Sucesso"}: {actionStatus.type}
            </div>
            <pre style={{
              margin: 0, fontSize: "10px", fontFamily: T.fontMono,
              color: T.textMuted, whiteSpace: "pre-wrap",
              wordBreak: "break-all", maxHeight: "150px", overflowY: "auto",
            }}>
              {actionStatus.message}
            </pre>
          </div>
        )}
      </div>

      {/* ═══ Section 4.5: Upload de PDF para ingestão ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> Upload de Documentos (PDF)
        </div>
        <div style={{ fontSize: "11.5px", color: T.textMuted, marginBottom: "10px" }}>
          Envie um PDF contendo um ou mais julgamentos. Cada caso é extraído e ingerido no Qdrant.
        </div>

        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
          <input
            id="pdf-upload"
            type="file"
            accept=".pdf"
            onChange={handlePdfFileChange}
            disabled={pdfUploading || pdfProcessing}
            style={{
              padding: "5px 8px", fontSize: "11.5px",
              border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
              background: T.surfaceAlt, color: T.text,
              fontFamily: T.fontSans, outline: "none", flex: 1, minWidth: "180px",
            }}
          />

          <select
            id="pdf-tribunal"
            name="pdf_tribunal"
            value={pdfTribunal}
            onChange={(e) => setPdfTribunal(e.target.value)}
            disabled={pdfUploading || pdfProcessing}
            style={{
              padding: "6px 10px", fontSize: "12px",
              border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
              background: T.surfaceAlt, color: T.text,
              fontFamily: T.fontSans, outline: "none",
            }}
          >
            {["TJPR", "TJSP", "TJMS", "TJCE", "TJRS"].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <button
            onClick={handlePdfUpload}
            disabled={!pdfFile || pdfUploading || pdfProcessing}
            style={{
              padding: "7px 14px", borderRadius: T.radiusSm, border: "none",
              background: T.accent, color: "#fff", fontSize: "11.5px",
              fontWeight: 500, cursor: (!pdfFile || pdfUploading || pdfProcessing) ? "not-allowed" : "pointer",
              fontFamily: T.fontSans, opacity: (!pdfFile || pdfUploading || pdfProcessing) ? 0.6 : 1,
              display: "inline-flex", alignItems: "center", gap: "6px",
            }}
          >
            {pdfUploading && <Spinner size={11} color="#fff" />}
            {pdfUploading ? "Enviando..." : "Enviar"}
          </button>

          {pdfFileId && (
            <button
              onClick={handlePdfProcess}
              disabled={pdfProcessing || pdfUploading}
              style={{
                padding: "7px 14px", borderRadius: T.radiusSm, border: "none",
                background: T.accent, color: "#fff", fontSize: "11.5px",
                fontWeight: 500, cursor: (pdfProcessing || pdfUploading) ? "not-allowed" : "pointer",
                fontFamily: T.fontSans, opacity: (pdfProcessing || pdfUploading) ? 0.6 : 1,
                display: "inline-flex", alignItems: "center", gap: "6px",
              }}
            >
              {pdfProcessing && <Spinner size={11} color="#fff" />}
              {pdfProcessing ? "Processando..." : "Processar"}
            </button>
          )}
        </div>

        {pdfFile && !pdfFileId && (
          <div style={{ fontSize: "11px", color: T.textMuted, marginTop: "8px" }}>
            Arquivo selecionado: {pdfFile.name} ({(pdfFile.size / 1024).toFixed(1)} KB)
          </div>
        )}

        {pdfStatus && (
          <div style={{
            marginTop: "10px", padding: "8px 12px", borderRadius: T.radiusSm,
            background: pdfStatus.error ? T.dangerLight : T.accentLight,
            border: `1px solid ${pdfStatus.error ? T.danger : T.accent}33`,
          }}>
            <div style={{
              fontSize: "11px", fontWeight: 600,
              color: pdfStatus.error ? T.danger : T.accent, marginBottom: "4px",
            }}>
              {pdfStatus.error ? "Falha" : "Sucesso"}
            </div>
            <div style={{ fontSize: "11px", color: T.text }}>{pdfStatus.message}</div>
            {pdfStatus.details && pdfStatus.details.length > 0 && (
              <pre style={{
                margin: "6px 0 0", fontSize: "10px", fontFamily: T.fontMono,
                color: T.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-all",
                maxHeight: "150px", overflowY: "auto",
              }}>
                {JSON.stringify(pdfStatus.details, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

      {/* ═══ Section 5: API Tester ═══ */}
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <span style={{ color: T.accent }}>&#9632;</span> API Endpoint Tester
        </div>
        <div style={{ display: "flex", gap: "8px", marginBottom: "10px", flexWrap: "wrap" }}>
          <select id="api-tester-endpoint" name="api_tester_endpoint" value={apiTesterEndpoint} onChange={e => setApiTesterEndpoint(e.target.value)}
            style={{
              padding: "6px 10px", fontSize: "12px", border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm, background: T.surfaceAlt, color: T.text,
              fontFamily: T.fontSans, outline: "none", flex: 1, minWidth: "180px",
            }}>
            {API_TESTER_ENDPOINTS.map(ep => (
              <option key={ep.label} value={ep.label}>{ep.label}</option>
            ))}
          </select>
          <button onClick={testEndpoint} disabled={apiTesterLoading}
            style={{
              padding: "6px 16px", borderRadius: T.radiusSm, border: "none",
              background: T.accent, color: "#fff", fontSize: "12px",
              fontWeight: 600, cursor: "pointer", fontFamily: T.fontSans,
              display: "inline-flex", alignItems: "center", gap: "6px",
              opacity: apiTesterLoading ? 0.6 : 1,
            }}>
            {apiTesterLoading && <Spinner size={11} color="#fff" />}
            Test
          </button>
        </div>

        {apiTesterResponse && (
          <div>
            <div style={{
              fontSize: "11px", color: apiTesterResponse.ok ? T.accent : T.danger,
              marginBottom: "6px", fontWeight: 600,
            }}>
              Status: {apiTesterResponse.status || "N/A"}
              {apiTesterResponse.error ? ` - ${apiTesterResponse.error}` : ""}
            </div>
            {apiTesterResponse.body && (
              <pre style={{
                background: T.surfaceAlt, border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm, padding: "10px",
                fontSize: "10.5px", fontFamily: T.fontMono,
                color: T.text, maxHeight: isMobile ? "250px" : "350px",
                overflowY: "auto", whiteSpace: "pre-wrap",
                wordBreak: "break-all", margin: 0,
              }}>
                {JSON.stringify(apiTesterResponse.body, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
