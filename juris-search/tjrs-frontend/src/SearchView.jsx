import { useEffect, useState } from "react";
import JurisprudenceView from "./JurisprudenceView";

const SEARCH_THEME = {
  bg: "#f8f7f4",
  surface: "#ffffff",
  surfaceAlt: "#f1efe8",
  border: "#e1ddd1",
  borderFocus: "#24405f",
  text: "#1b1c1e",
  textMuted: "#8a8b87",
  accent: "#24405f",
  accentLight: "rgba(36, 64, 95, 0.07)",
  accentHover: "#1c3350",
  danger: "#7a3733",
  green: "#3f6b4f",
  blue: "#8a6a2c",
  shadow: "0 1px 3px rgba(20, 20, 18, 0.06)",
  shadowLg: "0 8px 24px rgba(20, 20, 18, 0.08)",
  radius: "4px",
  font: "'Source Serif 4', Georgia, 'Times New Roman', serif",
  fontSerif: "'Source Serif 4', Georgia, 'Times New Roman', serif",
  fontSans: "'Inter', 'Segoe UI', sans-serif",
  fontMono: "'JetBrains Mono', 'Fira Code', monospace",
};

export default function SearchView({ apiBase }) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 720);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 719px)");
    const update = (event) => setIsMobile(event.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return (
    <main style={{ minHeight: "100vh", background: SEARCH_THEME.bg, color: SEARCH_THEME.text }}>
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: "12px", padding: isMobile ? "14px 16px" : "14px 24px",
        borderBottom: `1px solid ${SEARCH_THEME.border}`, background: SEARCH_THEME.surface,
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "9px" }}>
          <span style={{ color: SEARCH_THEME.accent, fontSize: "18px", lineHeight: 1 }}>◆</span>
          <h1 style={{
            margin: 0, fontFamily: SEARCH_THEME.fontSerif, fontSize: "18px",
            fontWeight: 600, color: SEARCH_THEME.text,
          }}>Jurisprudência</h1>
          {!isMobile && <span style={{
            fontFamily: SEARCH_THEME.fontMono, fontSize: "9px", letterSpacing: "0.08em",
            textTransform: "uppercase", color: SEARCH_THEME.textMuted,
          }}>Inteligência Jurisprudencial</span>}
        </div>
        <span style={{
          fontFamily: SEARCH_THEME.fontMono, fontSize: "10px", letterSpacing: "0.06em",
          textTransform: "uppercase", color: SEARCH_THEME.textMuted,
        }}>Pesquisa</span>
      </header>
      <section style={{
        maxWidth: "1240px", margin: "0 auto", minHeight: "calc(100vh - 57px)",
        borderInline: `1px solid ${SEARCH_THEME.border}`,
        background: SEARCH_THEME.bg,
      }}>
        <JurisprudenceView apiBase={apiBase} isMobile={isMobile} T={SEARCH_THEME} />
      </section>
    </main>
  );
}