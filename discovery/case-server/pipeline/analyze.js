/**
 *  Layer 3 — ANALYZE CONTENT
 *
 *  Entity extraction from text content (no external dependencies).
 *  Extracts:
 *  - Dates (various formats)
 *  - Person names (capitalized word sequences)
 *  - Organization names (known patterns + abbreviations)
 *  - Legal references (law numbers, articles, codes)
 *  - Locations (airports, cities, countries)
 *  - Key terms (significant recurring words)
 *
 *  This is regex/heuristic-based. For deeper NLP, an LLM layer
 *  can be added later as Layer 5+ enrichment.
 */

// ── Date extraction ───────────────────────────────────────────────

const DATE_PATTERNS = [
  // ISO: 2024-01-15, 2024-01-15T10:30:00
  { re: /\b(\d{4})-(\d{2})-(\d{2})(?:T[\d:]+(?:\.\d+)?Z?)?\b/g, fmt: "iso" },
  // US: 01/15/2024, 1/15/2024
  { re: /\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/g, fmt: "us" },
  // BR/EU: 15/01/2024
  { re: /\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/g, fmt: "dmy" },
  // Written: January 15, 2024 | 15 de janeiro de 2024 | 15 de enero de 2024
  { re: /\b(\d{1,2})\s+de\s+(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})\b/gi, fmt: "pt-written" },
  { re: /\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b/gi, fmt: "es-written" },
  { re: /\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b/gi, fmt: "en-written" },
];

function extractDates(text) {
  if (!text) return [];
  const dates = [];
  const seen = new Set();
  for (const { re, fmt } of DATE_PATTERNS) {
    let match;
    const regex = new RegExp(re.source, re.flags);
    while ((match = regex.exec(text)) !== null) {
      const raw = match[0];
      if (!seen.has(raw)) {
        seen.add(raw);
        dates.push({ raw, format: fmt, position: match.index });
      }
    }
  }
  return dates;
}

// ── Legal reference extraction ────────────────────────────────────

const LAW_PATTERNS = [
  // Brazilian: Lei nº 7.565/1986, Lei 12.846, Decreto nº 5.910
  /\b(Lei|Decreto|Resolução|Portaria|Instrução Normativa|Medida Provisória|Código)\s*(nº|n°|No\.?)?\s*[\d.,]+(?:\/\d{4})?\b/gi,
  // Articles: Art. 14, Artigo 256, art. 37
  /\b(Art(?:igo)?\.?)\s*(\d+)(?:,?\s*(?:§|parágrafo|inciso|alínea)\s*\w+)*/gi,
  // Codes: Código de Defesa do Consumidor, Código Penal, Código Civil
  /\bCódigo\s+(?:de\s+)?(?:Defesa\s+do\s+Consumidor|Penal|Civil|Aeronáutico|Brasileiro\s+de\s+Aeronáutica|Processo\s+(?:Civil|Penal))\b/gi,
  // ANAC regulations: RBAC nº 141, Resolução ANAC
  /\b(?:RBAC|RBHA)\s*(?:nº|n°)?\s*\d+\b/gi,
  // Generic law patterns: Law No. 123, Section 14
  /\bLaw\s+(?:No\.?|Number)\s*\d+(?:\/\d{4})?\b/gi,
  /\bSection\s+\d+(?:\.\d+)*\b/gi,
  // Chilean: Ley 20.393
  /\bLey\s*(?:nº|n°|No\.?)?\s*[\d.,]+(?:\/\d{4})?\b/gi,
  // Constitutions
  /\bConstituição\s+(?:Federal|da\s+República)/gi,
  /\bConstitución\s+(?:Política|de\s+la\s+República)/gi,
];

function extractLegalRefs(text) {
  if (!text) return [];
  const refs = [];
  const seen = new Set();
  for (const pat of LAW_PATTERNS) {
    let match;
    const regex = new RegExp(pat.source, pat.flags);
    while ((match = regex.exec(text)) !== null) {
      const raw = match[0].trim();
      const normalized = raw.toLowerCase().replace(/\s+/g, " ");
      if (!seen.has(normalized)) {
        seen.add(normalized);
        refs.push({ raw, normalized, position: match.index });
      }
    }
  }
  return refs;
}

// ── Person name extraction (heuristic) ─────────────────────────────

function extractPeople(text) {
  if (!text) return [];
  // Match 2-4 capitalized words in sequence (likely names)
  const namePattern = /\b([A-ZÁÉÍÓÚÀÃÕÂÊÔÇÑ][a-záéíóúàãõâêôçñ]+(?:\s+(?:de|da|do|dos|das|del|la|el|van|von)\s+)?(?:[A-ZÁÉÍÓÚÀÃÕÂÊÔÇÑ][a-záéíóúàãõâêôçñ]+\s*){1,3})\b/g;
  const names = [];
  const seen = new Set();
  // Common false-positive words to exclude
  const stopNames = new Set([
    "the", "this", "that", "with", "from", "also", "para", "como", "esta",
    "código", "artigo", "decreto", "janeiro", "fevereiro", "março", "abril",
    "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro",
    "dezembro", "monday", "tuesday", "wednesday", "thursday", "friday",
    "termos", "conforme", "sendo", "entre", "sobre",
  ]);

  let match;
  while ((match = namePattern.exec(text)) !== null) {
    const raw = match[1].trim();
    if (raw.split(/\s+/).length < 2) continue; // need at least 2 words
    const lower = raw.toLowerCase();
    if (stopNames.has(lower.split(/\s+/)[0])) continue;
    if (!seen.has(lower)) {
      seen.add(lower);
      names.push({ raw, position: match.index });
    }
  }
  return names;
}

// ── Organization extraction ────────────────────────────────────────

const ORG_PATTERNS = [
  /\b(ANAC|DGAC|FAA|ICAO|IATA|DECEA|CENIPA|SERIPA)\b/g,
  /\b(Carabineros|PDI|Policía|Polícia|Polícia Federal|Polícia Civil)\b/gi,
  /\b(LATAM|GOL|Azul|Avianca|Copa Airlines|JetSMART)\b/gi,
  /\b(Tribunal|Juizado|Vara|Comarca|Ministério Público|Defensoria)\b/gi,
  /\b(PROCON|SENACON|INAC|OSA|JCAB)\b/g,
  /\b(Aeroporto|Airport|Aeropuerto)\s+(?:[A-Z][a-záéíóú]+\s*)+/gi,
];

function extractOrganizations(text) {
  if (!text) return [];
  const orgs = [];
  const seen = new Set();
  for (const pat of ORG_PATTERNS) {
    let match;
    const regex = new RegExp(pat.source, pat.flags);
    while ((match = regex.exec(text)) !== null) {
      const raw = match[0].trim();
      const normalized = raw.toUpperCase();
      if (!seen.has(normalized)) {
        seen.add(normalized);
        orgs.push({ raw, normalized, position: match.index });
      }
    }
  }
  return orgs;
}

// ── Location extraction ───────────────────────────────────────────

const LOCATION_PATTERNS = [
  /\b(Santiago|São Paulo|Rio de Janeiro|Brasília|Buenos Aires|Lima|Bogotá|México|Montevideo|Asunción)\b/gi,
  /\b(Chile|Brasil|Brazil|Argentina|Peru|Perú|Colombia|México|Mexico|Uruguay|Paraguay|Bolivia|Ecuador)\b/gi,
  /\b(Aeroporto|Airport|Aeropuerto)\s+(?:(?:Internacional|International)\s+)?(?:de\s+)?([A-Z][a-záéíóú]+(?:\s+[A-Z][a-záéíóú]+)*)/gi,
  // IATA codes (3 uppercase letters near aviation context)
  /\b(SCL|GRU|GIG|EZE|LIM|BOG|MEX|MVD|ASU|BSB|CGH|SDU|VCP|CWB|POA|SSA|REC|FOR|BEL|MAO)\b/g,
];

function extractLocations(text) {
  if (!text) return [];
  const locs = [];
  const seen = new Set();
  for (const pat of LOCATION_PATTERNS) {
    let match;
    const regex = new RegExp(pat.source, pat.flags);
    while ((match = regex.exec(text)) !== null) {
      const raw = match[0].trim();
      const normalized = raw.toLowerCase();
      if (!seen.has(normalized)) {
        seen.add(normalized);
        locs.push({ raw, normalized, position: match.index });
      }
    }
  }
  return locs;
}

// ── Key term extraction ───────────────────────────────────────────

const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
  "of", "with", "by", "from", "is", "it", "its", "was", "are", "be",
  "has", "had", "have", "been", "will", "would", "could", "should", "may",
  "can", "do", "does", "did", "not", "no", "nor", "if", "then", "than",
  "so", "as", "up", "out", "about", "into", "over", "after", "before",
  "de", "da", "do", "dos", "das", "em", "no", "na", "nos", "nas", "um",
  "uma", "o", "os", "as", "que", "se", "por", "com", "para", "como",
  "mais", "ou", "foi", "ser", "ter", "está", "são", "este", "esta",
  "esse", "essa", "pelo", "pela", "pelos", "pelas", "ao", "aos",
  "el", "la", "los", "las", "del", "al", "en", "con", "por", "que",
  "es", "un", "una", "su", "sus", "este", "esta", "estos", "estas",
  "null", "true", "false", "undefined", "function", "return", "var", "let", "const",
]);

function extractKeyTerms(text, maxTerms = 30) {
  if (!text) return [];
  const words = text.toLowerCase()
    .replace(/[^\w\sáéíóúàãõâêôçñü]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 3 && !STOP_WORDS.has(w) && !/^\d+$/.test(w));

  const freq = {};
  for (const w of words) {
    freq[w] = (freq[w] || 0) + 1;
  }

  return Object.entries(freq)
    .filter(([, c]) => c >= 2) // at least 2 occurrences
    .sort((a, b) => b[1] - a[1])
    .slice(0, maxTerms)
    .map(([term, count]) => ({ term, count }));
}

/**
 * Process a single file through Layer 3
 * @param {string|null} text - File text content (from Layer 1 preview/full read)
 * @param {string} filePath - Relative file path (for filename-based extraction)
 * @returns {object} Layer 3 enrichment data
 */
function processFile(text, filePath) {
  // Also extract from filename/path
  const pathText = filePath.replace(/[_\-\/\\]/g, " ");
  const combined = (text || "") + " " + pathText;

  const dates = extractDates(combined);
  const legalRefs = extractLegalRefs(combined);
  const people = extractPeople(text || "");
  const organizations = extractOrganizations(combined);
  const locations = extractLocations(combined);
  const keyTerms = extractKeyTerms(text);

  return {
    entities: {
      dates: dates.slice(0, 50),
      legal_refs: legalRefs.slice(0, 50),
      people: people.slice(0, 30),
      organizations: organizations.slice(0, 30),
      locations: locations.slice(0, 30),
    },
    key_terms: keyTerms,
    entity_counts: {
      dates: dates.length,
      legal_refs: legalRefs.length,
      people: people.length,
      organizations: organizations.length,
      locations: locations.length,
    },
    has_entities: (dates.length + legalRefs.length + people.length + organizations.length + locations.length) > 0,
  };
}

module.exports = { processFile, extractDates, extractLegalRefs, extractPeople, extractOrganizations, extractLocations };
