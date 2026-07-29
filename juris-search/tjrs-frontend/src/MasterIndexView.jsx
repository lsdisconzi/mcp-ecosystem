import { useCallback, useEffect, useState } from "react";

/* Reuse the App's apiUrl via a prop since it depends on runtime variables */
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

export default function MasterIndexBrowseView({
  apiBase,
  masterStats,
  onOpenDoc,
  isMobile,
  T,
  filterInputStyle,
}) {
  const [filters, setFilters] = useState({
    tribunal: "", outcome: "", year: "", relator: "", assunto: "", comarca: "", text: "",
  });
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const limit = 50;

  const fetchDocuments = useCallback(async (currentFilters, currentOffset) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(currentFilters).forEach(([k, v]) => { if (v) params.set(k, v); });
      params.set("limit", String(limit));
      params.set("offset", String(currentOffset));
      const res = await fetch(apiUrl(apiBase, `/api/master-index/documents?${params.toString()}`));
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const data = await res.json();
      setResults(data.items || []);
      setTotal(data.total || 0);
    } catch (_) {
      setResults([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [apiBase, limit]);

  useEffect(() => {
    fetchDocuments(filters, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const handleSearch = () => {
    setOffset(0);
    fetchDocuments(filters, 0);
  };

  const handleClear = () => {
    const cleared = { tribunal: "", outcome: "", year: "", relator: "", assunto: "", comarca: "", text: "" };
    setFilters(cleared);
    setOffset(0);
    fetchDocuments(cleared, 0);
  };

  const handlePrevPage = () => {
    const nextOffset = Math.max(0, offset - limit);
    setOffset(nextOffset);
    fetchDocuments(filters, nextOffset);
  };

  const handleNextPage = () => {
    const nextOffset = offset + limit;
    setOffset(nextOffset);
    fetchDocuments(filters, nextOffset);
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: isMobile ? "12px" : "20px 28px" }}>
      {/* Stats Bar */}
      {masterStats && (
        <div style={{
          display: "flex", gap: isMobile ? "8px" : "16px", marginBottom: "16px",
          flexWrap: "wrap",
        }}>
          {[
            ["Total", masterStats.total_documents],
            ["TJSP", masterStats.by_tribunal?.TJSP],
            ["TJRS", masterStats.by_tribunal?.TJRS],
            ["TJMS", masterStats.by_tribunal?.TJMS],
            ["TJCE", masterStats.by_tribunal?.TJCE],
          ].map(([label, value]) => (
            <div key={label} style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm, padding: "8px 14px",
              textAlign: "center", minWidth: isMobile ? "56px" : "72px",
            }}>
              <div style={{ fontSize: isMobile ? "16px" : "20px", fontWeight: 700, color: T.accent }}>
                {value ?? "-"}
              </div>
              <div style={{ fontSize: "10px", color: T.textMuted }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter Bar */}
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: T.radius, padding: isMobile ? "10px" : "14px 16px",
        marginBottom: "16px", boxShadow: T.shadow,
      }}>
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "flex-end",
        }}>
          <select id="filter-tribunal" name="filter-tribunal" value={filters.tribunal} onChange={e => handleFilterChange("tribunal", e.target.value)}
            style={filterInputStyle}>
            <option value="">Todos tribunais</option>
            {(masterStats?.by_tribunal ? Object.keys(masterStats.by_tribunal) : ["TJSP","TJRS","TJMS","TJCE"])
              .map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select id="filter-year" name="filter-year" value={filters.year} onChange={e => handleFilterChange("year", e.target.value)}
            style={filterInputStyle}>
            <option value="">Todos anos</option>
            {(masterStats?.by_year ? Object.keys(masterStats.by_year).sort().reverse() : ["2026","2025","2024","2023","2022","2021","2020","2019","2018"])
              .map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <select id="filter-outcome" name="filter-outcome" value={filters.outcome} onChange={e => handleFilterChange("outcome", e.target.value)}
            style={filterInputStyle}>
            <option value="">Todos resultados</option>
            {(masterStats?.by_outcome ? Object.keys(masterStats.by_outcome) : ["negado_provimento","dado_provimento","provimento_parcial","procedente","improcedente","unanime","reformada","mantida"])
              .map(o => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
          </select>
          <input
            type="text" id="filter-relator" name="filter-relator" placeholder="Relator..."
            value={filters.relator}
            onChange={e => handleFilterChange("relator", e.target.value)}
            style={filterInputStyle}
          />
          <input
            type="text" id="filter-assunto" name="filter-assunto" placeholder="Assunto..."
            value={filters.assunto}
            onChange={e => handleFilterChange("assunto", e.target.value)}
            style={filterInputStyle}
          />
          <input
            type="text" id="filter-comarca" name="filter-comarca" placeholder="Comarca..."
            value={filters.comarca}
            onChange={e => handleFilterChange("comarca", e.target.value)}
            style={filterInputStyle}
          />
          <input
            type="text" id="filter-text" name="filter-text" placeholder="Buscar no texto..."
            value={filters.text}
            onChange={e => handleFilterChange("text", e.target.value)}
            style={{ ...filterInputStyle, minWidth: "140px", flex: 2 }}
          />
          <button onClick={handleSearch} style={{
            padding: "7px 16px", borderRadius: T.radiusSm, border: "none",
            background: T.accent, color: "#fff", fontSize: "12px", fontWeight: 600,
            cursor: "pointer", fontFamily: T.fontSans,
          }}>Filtrar</button>
          <button onClick={handleClear} style={{
            padding: "7px 12px", borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
            background: T.surface, color: T.textMuted, fontSize: "12px",
            cursor: "pointer", fontFamily: T.fontSans,
          }}>Limpar</button>
        </div>
      </div>

      {/* Results */}
      {loading ? (
        <div style={{
          display: "flex", justifyContent: "center", padding: "40px",
          color: T.textMuted, fontSize: "14px",
        }}>Carregando...</div>
      ) : (
        <>
          <div style={{ fontSize: "12px", color: T.textMuted, marginBottom: "8px" }}>
            {total > 0
              ? `Mostrando ${offset + 1}-${Math.min(offset + limit, total)} de ${total} documentos`
              : "Nenhum documento encontrado"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {results.map((doc, i) => (
              <div key={i} onClick={() => onOpenDoc(doc)} style={{
                background: T.surface, border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm, padding: isMobile ? "10px 12px" : "12px 16px",
                cursor: "pointer", transition: "all 0.15s",
                boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "4px", flexWrap: "wrap" }}>
                      <span style={{
                        fontSize: "10px", padding: "1px 6px", borderRadius: "4px",
                        background: T.surfaceAlt, color: T.textMuted, fontWeight: 600,
                      }}>{doc.tribunal || "-"}</span>
                      <span style={{
                        fontSize: isMobile ? "12.5px" : "13px", fontWeight: 600, color: T.text,
                        fontFamily: T.fontMono,
                      }}>{doc.numero_processo || doc.source_file || "-"}</span>
                    </div>
                    <div style={{ fontSize: "12px", color: T.textMuted }}>
                      {(nameOf(doc.relator) || "") && <span>{nameOf(doc.relator)}</span>}
                      {(doc.data_julgamento || "") && <span> - {(doc.data_julgamento || "").slice(0, 10)}</span>}
                      {(nameOf(doc.comarca) || "") && <span> - {nameOf(doc.comarca)}</span>}
                    </div>
                    {(doc.ementa || "") && (
                      <div style={{
                        fontSize: "11.5px", color: T.textMuted, marginTop: "6px",
                        lineHeight: 1.5, overflow: "hidden", display: "-webkit-box",
                        WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                      }}>
                        {(doc.ementa || "").slice(0, 300)}
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "3px", alignItems: "flex-end", flexShrink: 0 }}>
                    {(doc.outcome || []).slice(0, 3).map((o, j) => (
                      <span key={j} style={{
                        fontSize: "9px", padding: "2px 7px", borderRadius: "8px",
                        background: T.surfaceAlt, color: T.textMuted, fontWeight: 500,
                        whiteSpace: "nowrap",
                      }}>{o.replace(/_/g, " ")}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {total > limit && (
            <div style={{
              display: "flex", justifyContent: "center", gap: "12px",
              marginTop: "16px", paddingBottom: "20px",
            }}>
              <button onClick={handlePrevPage} disabled={offset === 0} style={{
                padding: "7px 14px", borderRadius: T.radiusSm,
                border: `1px solid ${T.border}`, background: T.surface,
                color: offset === 0 ? T.textLight : T.text,
                fontSize: "12px", cursor: offset === 0 ? "default" : "pointer",
                fontFamily: T.fontSans,
              }}>Anterior</button>
              <button onClick={handleNextPage} disabled={offset + limit >= total} style={{
                padding: "7px 14px", borderRadius: T.radiusSm,
                border: `1px solid ${T.border}`, background: T.surface,
                color: offset + limit >= total ? T.textLight : T.text,
                fontSize: "12px", cursor: offset + limit >= total ? "default" : "pointer",
                fontFamily: T.fontSans,
              }}>Proximo</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
