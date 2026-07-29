import { useEffect, useState } from "react";

function apiUrl(base, path) {
  const normalizedPath = String(path || "").replace(/^\/+/, "");
  return `${base}/${normalizedPath}`;
}

// The backend stores some fields as objects ({nome, cargo}, {nome, vara, ...}).
// Render the human-readable name, tolerating both string and object shapes.
function nameOf(value) {
  if (value == null) return "";
  if (typeof value === "object") return String(value.nome || "").trim();
  return String(value).trim();
}

export default function MasterIndexDetailView({
  apiBase,
  doc,
  onBack,
  onNavigateDoc,
  isMobile,
  T,
}) {
  const [correlations, setCorrelations] = useState(null);

  useEffect(() => {
    setCorrelations(null);
    if (!doc) return;
    const proc = doc.numero_processo || doc.source_file || "";
    fetch(apiUrl(apiBase, `/api/master-index/document/${encodeURIComponent(proc)}/correlations`))
      .then(res => res.ok ? res.json() : null)
      .then(data => setCorrelations(data))
      .catch(() => setCorrelations(null));
  }, [doc, apiBase]);

  if (!doc) return null;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: isMobile ? "14px" : "20px 28px" }}>
      <button onClick={onBack} style={{
        display: "inline-flex", alignItems: "center", gap: "6px",
        padding: "6px 14px", marginBottom: "16px",
        borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
        background: T.surface, color: T.accent, fontSize: "13px",
        fontWeight: 500, cursor: "pointer", fontFamily: T.fontSans,
      }}>
        <span style={{ fontSize: "16px", lineHeight: 1 }}>{"<"}</span> Voltar ao indice
      </button>

      {/* Document Card */}
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: T.radius, padding: isMobile ? "14px" : "20px 24px",
        boxShadow: T.shadow, marginBottom: "20px",
      }}>
        <div style={{ fontSize: "11px", color: T.textMuted, marginBottom: "4px" }}>
          {(doc.tribunal || "").toUpperCase()}
        </div>
        <div style={{ fontSize: isMobile ? "15px" : "17px", fontWeight: 700, color: T.text, fontFamily: T.fontMono, marginBottom: "12px", wordBreak: "break-all" }}>
          {doc.numero_processo || doc.source_file || "-"}
        </div>

        {/* Metadata grid */}
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "120px 1fr", gap: "6px 12px", fontSize: "13px", marginBottom: "16px" }}>
          {[
            ["Relator", nameOf(doc.relator)],
            ["Orgao", nameOf(doc.orgao_julgador)],
            ["Comarca", nameOf(doc.comarca)],
            ["Classe", doc.classe],
            ["Julgado em", (doc.data_julgamento || "").slice(0, 10)],
            ["Votacao", doc.votacao],
          ].map(([label, value]) => value && (
            <span key={label} style={{ display: "contents" }}>
              <span style={{ color: T.textMuted, fontWeight: 500 }}>{label}:</span>
              <span style={{ color: T.text }}>{String(value)}</span>
            </span>
          ))}
        </div>

      {/* Outcome badges */}
      {(doc.outcome && doc.outcome.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "12px" }}>
          {doc.outcome.map((o, i) => (
            <span key={i} style={{
              fontSize: "11px", padding: "3px 10px", borderRadius: "12px",
              background: T.surfaceAlt, color: T.text, fontWeight: 500,
              border: `1px solid ${T.border}`,
            }}>{o.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}

      {/* Download Action Buttons */}
      {(doc.raw_source_path || doc.docx_path || doc.download_url) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "16px" }}>
          {doc.raw_source_path && (() => {
            const isPdf = doc.raw_source_path.toLowerCase().endsWith('.pdf');
            const isHtml = doc.raw_source_path.toLowerCase().endsWith('.html') || doc.raw_source_path.toLowerCase().endsWith('.htm');
            const label = isPdf ? 'Download PDF (Local)' : isHtml ? 'Download HTML (Local)' : 'Download Document (Local)';
            return (
              <button
                onClick={() => {
                  const url = apiUrl(apiBase, `/api/master-index/download-file?path=${encodeURIComponent(doc.raw_source_path)}`);
                  window.open(url, '_blank');
                }}
                style={{
                  padding: "8px 16px",
                  fontSize: "13px",
                  background: T.accent,
                  color: "#fff",
                  border: "none",
                  borderRadius: T.radiusSm,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: T.fontSans,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  boxShadow: T.shadow,
                  transition: "background 0.2s ease",
                }}
                onMouseOver={(e) => { e.currentTarget.style.background = T.accentHover; }}
                onMouseOut={(e) => { e.currentTarget.style.background = T.accent; }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                {label}
              </button>
            );
          })()}

          {doc.docx_path && (
            <button
              onClick={() => {
                const url = apiUrl(apiBase, `/api/master-index/download-file?path=${encodeURIComponent(doc.docx_path)}`);
                window.open(url, '_blank');
              }}
              style={{
                padding: "8px 16px",
                fontSize: "13px",
                background: T.surfaceAlt,
                color: T.text,
                border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: T.fontSans,
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                boxShadow: T.shadow,
                transition: "background 0.2s ease",
              }}
              onMouseOver={(e) => { e.currentTarget.style.background = T.border; }}
              onMouseOut={(e) => { e.currentTarget.style.background = T.surfaceAlt; }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              Download DOCX
            </button>
          )}

          {doc.download_url && (
            <button
              onClick={() => window.open(doc.download_url, '_blank')}
              style={{
                padding: "8px 16px",
                fontSize: "13px",
                background: T.surface,
                color: T.accent,
                border: `1px solid ${T.accent}`,
                borderRadius: T.radiusSm,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: T.fontSans,
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                boxShadow: T.shadow,
                transition: "background 0.2s ease",
              }}
              onMouseOver={(e) => { e.currentTarget.style.background = T.accentLight; }}
              onMouseOut={(e) => { e.currentTarget.style.background = T.surface; }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
              Download (Web)
            </button>
          )}
        </div>
      )}


      {/* Assuntos */}
      {(doc.assuntos && doc.assuntos.length > 0) && (
        <div style={{ marginBottom: "12px" }}>
          <div style={{ fontSize: "11px", color: T.textMuted, marginBottom: "6px", fontWeight: 600 }}>ASSUNTOS</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "5px" }}>
            {doc.assuntos.map((a, i) => (
              <span key={i} style={{
                fontSize: "11px", padding: "3px 10px", borderRadius: "12px",
                background: T.accent + "15", color: T.accent, fontWeight: 500,
              }}>{a}</span>
            ))}
          </div>
        </div>
      )}

        {/* Legislacao */}
        {(doc.legislacao_citada && doc.legislacao_citada.length > 0) && (
          <div style={{ marginBottom: "12px" }}>
            <div style={{ fontSize: "11px", color: T.textMuted, marginBottom: "6px", fontWeight: 600 }}>LEGISLACAO CITADA</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "5px" }}>
              {doc.legislacao_citada.map((l, i) => (
                <span key={i} style={{
                  fontSize: "11px", padding: "3px 10px", borderRadius: "4px",
                  background: T.surfaceAlt, color: T.textMuted, fontFamily: T.fontMono,
                  border: `1px solid ${T.border}`,
                }}>{l}</span>
              ))}
            </div>
          </div>
        )}

        {/* Partes */}
        {doc.partes && (
          <div style={{ marginBottom: "12px" }}>
            {doc.partes.apelantes && (
              <div style={{ marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", color: T.textMuted, fontWeight: 600 }}>Apelantes: </span>
                <span style={{ fontSize: "12px", color: T.text }}>
                  {typeof doc.partes.apelantes === "string"
                    ? doc.partes.apelantes
                    : doc.partes.apelantes.join(", ")}
                </span>
              </div>
            )}
            {doc.partes.apelados && (
              <div>
                <span style={{ fontSize: "11px", color: T.textMuted, fontWeight: 600 }}>Apelados: </span>
                <span style={{ fontSize: "12px", color: T.text }}>
                  {typeof doc.partes.apelados === "string"
                    ? doc.partes.apelados
                    : doc.partes.apelados.join(", ")}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Ementa */}
      {doc.ementa && (
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: T.radius, padding: isMobile ? "14px" : "20px 24px",
          boxShadow: T.shadow, marginBottom: "20px",
        }}>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "8px", fontWeight: 600 }}>EMENTA</div>
          <div style={{
            fontSize: "13px", color: T.text, lineHeight: 1.7,
            whiteSpace: "pre-wrap", fontFamily: T.fontSerif,
            maxHeight: "500px", overflowY: "auto",
          }}>
            {doc.ementa}
          </div>
        </div>
      )}

      {/* Correlations */}
      {correlations ? (
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: T.radius, padding: isMobile ? "14px" : "20px 24px",
          boxShadow: T.shadow, marginBottom: "20px",
        }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: T.text, marginBottom: "14px" }}>DOCUMENTOS RELACIONADOS</div>
          {[
            { key: "same_relator", label: "Mesmo Relator", count: correlations.total_same_relator, items: correlations.same_relator },
            { key: "same_assuntos", label: "Mesmos Assuntos", count: correlations.total_same_assuntos, items: correlations.same_assuntos },
            { key: "same_legislacao", label: "Mesma Legislacao", count: correlations.total_same_legislacao, items: correlations.same_legislacao },
          ].map(({ key, label, count, items }) => (
            <div key={key} style={{ marginBottom: "12px" }}>
              <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "6px", fontWeight: 500 }}>
                {label} ({count})
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {(items || []).slice(0, 10).map((proc) => (
                  <button key={proc} onClick={() => onNavigateDoc(proc)} style={{
                    fontSize: "12px", fontFamily: T.fontMono, padding: "4px 10px",
                    borderRadius: "4px", border: `1px solid ${T.accent}40`,
                    background: T.accent + "08", color: T.accent, cursor: "pointer",
                    transition: "all 0.15s",
                  }}
                  onMouseEnter={e => { e.target.style.background = T.accent + "20"; }}
                  onMouseLeave={e => { e.target.style.background = T.accent + "08"; }}
                  >{proc}</button>
                ))}
                {(items || []).length === 0 && (
                  <span style={{ fontSize: "12px", color: T.textLight }}>Nenhum</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: "20px", color: T.textMuted, fontSize: "13px" }}>
          Carregando correlacoes...
        </div>
      )}
    </div>
  );
}
