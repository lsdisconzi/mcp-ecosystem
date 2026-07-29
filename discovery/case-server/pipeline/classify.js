/**
 *  Layer 2 — CLASSIFY
 *
 *  Enhanced categorization beyond keyword matching.
 *  - Auto-tags from filename, path, and content patterns
 *  - Language detection (Portuguese, Spanish, English)
 *  - Domain classification (legal, aviation, evidence, etc.)
 *  - Naming pattern detection (generated vs manual, date-stamped, etc.)
 *  - Sub-categorization from directory hierarchy
 */

const path = require("path");

// ── Language detection by common words ─────────────────────────────

const LANG_SIGNATURES = {
  pt: [
    "artigo", "parágrafo", "lei", "decreto", "código", "inciso", "alínea",
    "passageiro", "aeronave", "voo", "aeroporto", "relatório", "análise",
    "conforme", "mediante", "portanto", "entretanto", "sobre", "porque",
    "está", "são", "nesta", "desta", "resultado", "consumidor", "defesa",
    "contrato", "prazo", "dano", "indenização", "responsabilidade",
    "não", "também", "ainda", "mais", "como", "para", "com", "uma",
  ],
  es: [
    "artículo", "párrafo", "ley", "decreto", "código", "inciso",
    "pasajero", "aeronave", "vuelo", "aeropuerto", "informe", "análisis",
    "conforme", "mediante", "por lo tanto", "sin embargo", "sobre",
    "está", "son", "esta", "resultado", "consumidor", "defensa",
    "contrato", "plazo", "daño", "indemnización", "responsabilidad",
    "también", "todavía", "más", "como", "para", "con", "una",
  ],
  en: [
    "article", "paragraph", "law", "decree", "code", "section",
    "passenger", "aircraft", "flight", "airport", "report", "analysis",
    "pursuant", "therefore", "however", "regarding", "moreover",
    "the", "and", "that", "this", "result", "consumer", "defense",
    "contract", "deadline", "damage", "compensation", "liability",
    "also", "still", "more", "between", "with", "from",
  ],
};

function detectLanguage(text) {
  if (!text || text.length < 50) return "unknown";
  const lower = text.toLowerCase().slice(0, 5000);
  const words = lower.split(/\s+/);
  const scores = {};
  for (const [lang, sigs] of Object.entries(LANG_SIGNATURES)) {
    scores[lang] = 0;
    for (const sig of sigs) {
      for (const w of words) {
        if (w === sig || w.startsWith(sig)) scores[lang]++;
      }
    }
  }
  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  if (sorted[0][1] === 0) return "unknown";
  if (sorted.length > 1 && sorted[0][1] === sorted[1][1]) return "mixed";
  return sorted[0][0];
}

// ── Domain classification ──────────────────────────────────────────

const DOMAIN_PATTERNS = {
  legal: [
    /\b(law|lei|ley|decreto|regulamento|código|code|statute|regulation)\b/i,
    /\b(artigo|article|artículo|inciso|parágrafo|paragraph)\b/i,
    /\b(penal|civil|criminal|constitui[cç]|constitu[ct]ion)\b/i,
    /\b(anac|dgac|faa|icao|iata)\b/i,
  ],
  aviation: [
    /\b(flight|voo|vuelo|aircraft|aeronave|airport|aeroporto|aeropuerto)\b/i,
    /\b(pilot|piloto|cabin|cabine|boarding|embarque)\b/i,
    /\b(anac|dgac|faa|icao|iata|rbac)\b/i,
    /\b(terminal|runway|pista|taxiway)\b/i,
  ],
  evidence: [
    /\b(evidence|evidência|prueba|proof|exhibit)\b/i,
    /\b(photo|foto|video|recording|gravação|grabación)\b/i,
    /\b(witness|testemunha|testigo)\b/i,
  ],
  correspondence: [
    /\b(email|e-mail|carta|letter|memo|memorandum)\b/i,
    /\b(from|de|to|para|subject|asunto|assunto)\b/i,
  ],
  financial: [
    /\b(invoice|fatura|factura|receipt|recibo|payment|pagamento|pago)\b/i,
    /\b(tax|imposto|impuesto|fiscal|tributário|tributario)\b/i,
  ],
  incident: [
    /\b(incident|incidente|accident|acidente|accidente)\b/i,
    /\b(report|relatório|informe|narrative|narrativa)\b/i,
    /\b(timeline|cronolog|cronolog)\b/i,
  ],
  transcript: [
    /\b(transcript|transcri[cçp]|segment|audio|recording|gravação)\b/i,
    /\b(speaker|falante|hablante|timestamp)\b/i,
  ],
  analysis: [
    /\b(analysis|análise|análisis|result|resultado)\b/i,
    /\b(violation|violação|violación|breach|infra[cçc]ão)\b/i,
    /\b(finding|conclusion|conclusão|conclusión)\b/i,
  ],
};

function classifyDomain(text, filePath) {
  const scores = {};
  const combined = (text || "").slice(0, 5000) + " " + filePath.toLowerCase();

  for (const [domain, patterns] of Object.entries(DOMAIN_PATTERNS)) {
    scores[domain] = 0;
    for (const pat of patterns) {
      const matches = combined.match(pat);
      if (matches) scores[domain] += matches.length;
    }
  }

  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]).filter(([, v]) => v > 0);
  if (sorted.length === 0) return { primary_domain: "general", domains: [] };

  return {
    primary_domain: sorted[0][0],
    domains: sorted.map(([d, s]) => ({ domain: d, score: s })),
  };
}

// ── Tag generation ────────────────────────────────────────────────

function generateTags(filePath, ext, contentPreview) {
  const tags = new Set();
  const lower = filePath.toLowerCase();
  const basename = path.basename(filePath, ext).toLowerCase();
  const dirs = path.dirname(filePath).toLowerCase().split(path.sep);

  // From extension
  const extTags = {
    ".pdf": "pdf", ".json": "json", ".txt": "text", ".md": "markdown",
    ".csv": "csv", ".eml": "email", ".docx": "word", ".html": "html",
    ".js": "javascript", ".py": "python", ".sql": "sql", ".tex": "latex",
  };
  if (extTags[ext]) tags.add(extTags[ext]);

  // From directory structure
  for (const d of dirs) {
    if (d.match(/^\d{3,4}[_\-]/)) tags.add("numbered-section");
    if (d.match(/law|legal|lei|ley/i)) tags.add("legal");
    if (d.match(/transcript|transcri/i)) tags.add("transcript");
    if (d.match(/evidence|evidencia/i)) tags.add("evidence");
    if (d.match(/result|resultado/i)) tags.add("analysis-result");
    if (d.match(/violation|violacao/i)) tags.add("violation");
    if (d.match(/final/i)) tags.add("final");
    if (d.match(/draft|rascunho/i)) tags.add("draft");
    if (d.match(/stg_\d+/i)) tags.add("staged");
  }

  // From filename patterns
  if (basename.match(/result[_\s]/i)) tags.add("result");
  if (basename.match(/prompt/i)) tags.add("prompt");
  if (basename.match(/generat/i)) tags.add("generated");
  if (basename.match(/summary|resumo/i)) tags.add("summary");
  if (basename.match(/narrative|narrativa/i)) tags.add("narrative");
  if (basename.match(/timeline|cronolog/i)) tags.add("timeline");
  if (basename.match(/\d{4}[_\-]\d{2}[_\-]\d{2}/)) tags.add("date-stamped");
  if (basename.match(/_v\d+|_rev\d+/i)) tags.add("versioned");

  return [...tags];
}

// ── Naming pattern detection ──────────────────────────────────────

function detectNamingPattern(filename) {
  const patterns = [];
  if (filename.match(/^[a-z_]+_\d+/i)) patterns.push("snake_case_numbered");
  if (filename.match(/[A-Z][a-z]+[A-Z]/)) patterns.push("camelCase");
  if (filename.match(/\d{4}[\-_]\d{2}[\-_]\d{2}/)) patterns.push("date-prefixed");
  if (filename.match(/_result_|_output_|_generated/)) patterns.push("generated-output");
  if (filename.match(/_v\d+|_rev\d+|_final/i)) patterns.push("versioned");
  if (filename.length > 80) patterns.push("long-name");
  if (filename.match(/^[A-Z]{2,}/)) patterns.push("acronym-prefixed");
  return patterns.length > 0 ? patterns : ["standard"];
}

// ── Subcategory from path hierarchy ───────────────────────────────

function extractSubCategory(relPath) {
  const parts = relPath.split(path.sep).filter(Boolean);
  if (parts.length <= 1) return null;
  // Return the immediate parent directory as a sub-category
  return parts[parts.length - 2];
}

/**
 * Process a single file through Layer 2
 * @param {string} filePath - Relative file path
 * @param {string} ext - Extension
 * @param {string|null} textPreview - First N chars of content (from Layer 1) or null
 * @returns {object} Layer 2 enrichment data
 */
function processFile(filePath, ext, textPreview) {
  const language = detectLanguage(textPreview);
  const domainResult = classifyDomain(textPreview, filePath);
  const tags = generateTags(filePath, ext, textPreview);
  const namingPatterns = detectNamingPattern(path.basename(filePath));
  const subCategory = extractSubCategory(filePath);

  return {
    language,
    ...domainResult,
    tags,
    naming_patterns: namingPatterns,
    sub_category: subCategory,
    is_generated: tags.includes("generated") || tags.includes("analysis-result"),
  };
}

module.exports = { processFile, detectLanguage, classifyDomain };
