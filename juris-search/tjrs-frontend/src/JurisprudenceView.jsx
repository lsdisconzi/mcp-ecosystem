import { useEffect, useState } from "react";

/* Reuse the App's apiUrl via a prop since it depends on runtime variables */
function apiUrl(base, path) {
  const normalizedPath = String(path || "").replace(/^\/+/, "");
  return `${base}/${normalizedPath}`;
}

const CATEGORY_LABEL = {
  esaj: "e-SAJ",
  stf: "STF",
  chile: "Chile",
  "custom-portal": "Portal custom",
};

export default function JurisprudenceView({ apiBase, isMobile, T }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("courts");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(apiUrl(apiBase, "/api/master-index/jurisprudence"))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json) => { if (!cancelled) setData(json); })
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [apiBase]);

  const wrap = {
    padding: isMobile ? "16px 12px 32px" : "24px 24px 48px",
    maxWidth: "1200px", margin: "0 auto", width: "100%",
    color: T.text, fontFamily: T.fontSans, overflowY: "auto", height: "100%",
  };

  if (loading) {
    return (
      <div style={wrap}>
        <div style={{ textAlign: "center", padding: "48px 0", color: T.textMuted }}>
          Carregando índice expandido…
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={wrap}>
        <div style={{ textAlign: "center", padding: "48px 0", color: T.textMuted }}>
          Erro ao carregar o índice: {error || "sem dados"}
        </div>
      </div>
    );
  }

  const courts = data.courts?.list || [];
  const routes = data.api?.routes || [];
  const totals = data.totals || {};

  const TabBtn = ({ id, label }) => (
    <button onClick={() => setTab(id)}
      style={{
        padding: "8px 14px", fontSize: "13px", fontWeight: 500,
        color: tab === id ? T.accent : T.textMuted, cursor: "pointer",
        background: "none", border: "none",
        borderBottom: `2px solid ${tab === id ? T.accent : "transparent"}`,
        transition: "all 0.15s", fontFamily: T.fontSans,
      }}>{label}</button>
  );

  return (
    <div style={wrap}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "4px" }}>
        <h2 style={{ fontFamily: T.fontSerif || T.fontSans, fontWeight: 600, fontSize: "22px", margin: 0, color: T.text }}>
          Jurisprudência (índice expandido)
        </h2>
        {data.generated_at && (
          <span style={{ fontSize: "11px", color: T.textMuted }}>
            gerado em {data.generated_at}
          </span>
        )}
      </div>

      {/* summary stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "10px", margin: "16px 0 20px" }}>
        {[
          ["Documentos", totals.documents],
          ["Tribunais", `${data.courts?.operational_count || 0}/${data.courts?.supported_count || 0}`],
          ["Rotas de API", data.api?.route_count || 0],
          ["Jobs de busca", totals.search_jobs],
        ].map(([label, val]) => (
          <div key={label} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius, padding: "12px 16px", textAlign: "center" }}>
            <div style={{ fontFamily: T.fontSerif || T.fontSans, fontSize: "24px", fontWeight: 600, color: T.accent }}>{val}</div>
            <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.06em", color: T.textMuted, marginTop: "2px" }}>{label}</div>
          </div>
        ))}
      </div>

      {/* tab bar */}
      <div style={{ display: "flex", gap: "2px", borderBottom: `1px solid ${T.border}`, marginBottom: "16px", flexWrap: "wrap" }}>
        <TabBtn id="courts" label="Tribunais" />
        <TabBtn id="api" label="API" />
        <TabBtn id="agg" label="Agregações" />
        <TabBtn id="frontend" label="Frontend" />
      </div>

      {tab === "courts" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "10px" }}>
          {courts.map((c) => (
            <div key={c.key} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius, padding: "12px 14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
                <span style={{ fontFamily: T.fontMono || T.fontSans, fontSize: "13px", fontWeight: 600, color: T.accent }}>{c.key}</span>
                <span style={{ fontSize: "9px", padding: "2px 8px", borderRadius: "999px",
                  background: c.operational ? "rgba(107,170,122,0.14)" : "transparent",
                  border: `1px solid ${c.operational ? "rgba(107,170,122,0.3)" : T.border}`,
                  color: c.operational ? T.green || "#6baa7a" : T.textMuted }}>
                  {c.operational ? `${c.documents_indexed} docs` : "config."}
                </span>
              </div>
              <div style={{ fontSize: "12px", color: T.text, marginTop: "4px" }}>{c.name}</div>
              <div style={{ fontSize: "10px", color: T.textMuted, marginTop: "6px" }}>
                {CATEGORY_LABEL[c.category] || c.category} · <code style={{ fontFamily: T.fontMono || "monospace" }}>{c.scraper_class}</code>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "api" && (
        <div>
          <p style={{ fontSize: "12px", color: T.textMuted, marginBottom: "10px" }}>{data.api?.base_path_note}</p>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {routes.map((r, i) => (
              <div key={i} style={{ display: "flex", gap: "10px", alignItems: "center", background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius, padding: "6px 10px" }}>
                <span style={{
                  fontSize: "10px", fontWeight: 700, padding: "2px 8px", borderRadius: "4px",
                  background: "rgba(90,143,201,0.15)", color: T.blue || "#5a8fc9", minWidth: "56px", textAlign: "center",
                }}>{r.method}</span>
                <code style={{ fontFamily: T.fontMono || "monospace", fontSize: "12px", color: T.text }}>{r.path}</code>
                <span style={{ fontSize: "10px", color: T.textMuted, marginLeft: "auto" }}>{r.module}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "agg" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "14px" }}>
          {[
            ["Por tribunal", data.by_tribunal],
            ["Por ano", data.by_year],
            ["Por resultado", data.by_outcome],
          ].map(([label, mapping]) => (
            <div key={label} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius, padding: "12px 14px" }}>
              <h4 style={{ fontFamily: T.fontMono || T.fontSans, fontSize: "10px", letterSpacing: "0.1em", textTransform: "uppercase", color: T.accent, margin: "0 0 8px" }}>{label}</h4>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                <tbody>
                  {Object.entries(mapping || {}).sort((a, b) => (b[1] || 0) - (a[1] || 0)).map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ padding: "3px 0", color: T.text }}>{k}</td>
                      <td style={{ padding: "3px 0", textAlign: "right", color: T.textMuted, fontFamily: T.fontMono || "monospace" }}>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {tab === "frontend" && (
        <div>
          <p style={{ fontSize: "12px", color: T.textMuted, marginBottom: "10px" }}>
            Fonte: <code style={{ fontFamily: T.fontMono || "monospace" }}>{data.frontend?.view_file}</code>
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "10px" }}>
            {(data.frontend?.panels || []).map((p) => (
              <div key={p.id} style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.radius, padding: "12px 14px" }}>
                <div style={{ fontSize: "13px", fontWeight: 500, color: T.text }}>
                  {p.label} <span style={{ fontSize: "10px", color: T.textMuted, fontFamily: T.fontMono || "monospace" }}>({p.id})</span>
                </div>
                <div style={{ fontSize: "11px", color: T.textMuted, marginTop: "6px" }}>{p.purpose}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
