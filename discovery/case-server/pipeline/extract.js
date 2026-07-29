/**
 *  Layer 1 — EXTRACT METADATA
 *
 *  Deep metadata extraction beyond basic filesystem stats.
 *  For text-readable files: encoding, line/word/char counts, preview.
 *  For structured data: schema extraction (JSON keys, CSV columns).
 *  For binary files: marks as binary with format-specific stubs.
 */

const fs = require("fs");

const TEXT_EXTENSIONS = new Set([
  ".txt", ".md", ".html", ".htm", ".css", ".js", ".ts", ".json",
  ".xml", ".yaml", ".yml", ".csv", ".tsv", ".py", ".java", ".c",
  ".cpp", ".h", ".sh", ".sql", ".toml", ".rtf", ".log", ".ini",
  ".cfg", ".env", ".tex", ".eml",
]);

const MAX_READ_SIZE = 2 * 1024 * 1024;  // 2 MB for text analysis
const PREVIEW_LENGTH = 1000;

function isTextFile(ext) {
  return TEXT_EXTENSIONS.has(ext.toLowerCase());
}

function detectEncoding(buffer) {
  // BOM detection
  if (buffer.length >= 3 && buffer[0] === 0xEF && buffer[1] === 0xBB && buffer[2] === 0xBF) return "utf-8-bom";
  if (buffer.length >= 2 && buffer[0] === 0xFF && buffer[1] === 0xFE) return "utf-16le";
  if (buffer.length >= 2 && buffer[0] === 0xFE && buffer[1] === 0xFF) return "utf-16be";
  // Check if valid UTF-8
  let hasHighBytes = false;
  for (let i = 0; i < Math.min(buffer.length, 8192); i++) {
    if (buffer[i] === 0) return "binary";
    if (buffer[i] > 127) hasHighBytes = true;
  }
  return hasHighBytes ? "utf-8" : "ascii";
}

function extractTextStats(filePath, ext) {
  try {
    const stat = fs.statSync(filePath);
    const readSize = Math.min(stat.size, MAX_READ_SIZE);
    const fd = fs.openSync(filePath, "r");
    const buffer = Buffer.alloc(readSize);
    const bytesRead = fs.readSync(fd, buffer, 0, readSize, 0);
    fs.closeSync(fd);

    const raw = buffer.subarray(0, bytesRead);
    const encoding = detectEncoding(raw);

    if (encoding === "binary") {
      return { is_text: false, encoding: "binary" };
    }

    const text = raw.toString("utf8");
    const lines = text.split("\n");
    const words = text.split(/\s+/).filter(Boolean);
    const truncated = stat.size > MAX_READ_SIZE;

    const result = {
      is_text: true,
      encoding,
      line_count: truncated ? lines.length : lines.length,
      word_count: words.length,
      char_count: text.length,
      truncated_analysis: truncated,
      full_text: text,
      preview: text.slice(0, PREVIEW_LENGTH),
    };

    // Format-specific extraction
    if (ext === ".json") {
      Object.assign(result, extractJsonMeta(text));
    } else if (ext === ".csv" || ext === ".tsv") {
      Object.assign(result, extractCsvMeta(text, ext === ".tsv" ? "\t" : ","));
    } else if (ext === ".eml") {
      Object.assign(result, extractEmailMeta(text));
    }

    return result;
  } catch {
    return { is_text: false, encoding: "unknown", error: "read_failed" };
  }
}

function extractJsonMeta(text) {
  try {
    const data = JSON.parse(text);
    const type = Array.isArray(data) ? "array" : typeof data;
    const result = { json_valid: true, json_type: type };
    if (type === "array") {
      result.json_items_count = data.length;
      if (data.length > 0 && typeof data[0] === "object" && data[0] !== null) {
        result.json_item_keys = Object.keys(data[0]);
      }
    } else if (type === "object") {
      result.json_top_keys = Object.keys(data);
      result.json_keys_count = Object.keys(data).length;
    }
    return result;
  } catch {
    return { json_valid: false };
  }
}

function extractCsvMeta(text, delimiter) {
  const lines = text.split("\n").filter((l) => l.trim());
  if (lines.length === 0) return { csv_rows: 0 };
  const header = lines[0].split(delimiter).map((c) => c.trim().replace(/^"|"$/g, ""));
  return {
    csv_columns: header,
    csv_column_count: header.length,
    csv_rows: lines.length - 1, // excluding header
  };
}

function extractEmailMeta(text) {
  const headers = {};
  const headerRegex = /^(From|To|Subject|Date|Cc|Bcc|Message-ID):\s*(.+)$/gmi;
  let match;
  while ((match = headerRegex.exec(text)) !== null) {
    headers[match[1].toLowerCase()] = match[2].trim();
  }
  return { email_headers: headers };
}

function extractBinaryMeta(filePath, ext) {
  const meta = { is_text: false, encoding: "binary" };
  // PDF: extract page count from trailer
  if (ext === ".pdf") {
    try {
      const fd = fs.openSync(filePath, "r");
      const stat = fs.statSync(filePath);
      // Read last 2KB for trailer
      const tailSize = Math.min(stat.size, 2048);
      const buf = Buffer.alloc(tailSize);
      fs.readSync(fd, buf, 0, tailSize, Math.max(0, stat.size - tailSize));
      fs.closeSync(fd);
      const trailer = buf.toString("latin1");
      const pageMatch = trailer.match(/\/N\s+(\d+)/);
      if (pageMatch) meta.pdf_pages = parseInt(pageMatch[1], 10);
      // Try linearized page count
      const countMatch = trailer.match(/\/Count\s+(\d+)/g);
      if (countMatch) {
        const nums = countMatch.map((m) => parseInt(m.match(/\d+/)[0], 10));
        meta.pdf_pages = Math.max(...nums);
      }
    } catch { /* best-effort */ }
  }
  return meta;
}

function sniffTextLikeContent(filePath) {
  try {
    const stat = fs.statSync(filePath);
    if (!stat.size) return { isText: false, isJson: false };

    const readSize = Math.min(stat.size, 4096);
    const fd = fs.openSync(filePath, "r");
    const buffer = Buffer.alloc(readSize);
    const bytesRead = fs.readSync(fd, buffer, 0, readSize, 0);
    fs.closeSync(fd);

    const raw = buffer.subarray(0, bytesRead);
    const encoding = detectEncoding(raw);
    if (encoding === "binary") {
      return { isText: false, isJson: false };
    }

    const probe = raw.toString("utf8").trimStart();
    const isJson = probe.startsWith("{") || probe.startsWith("[");
    return { isText: true, isJson };
  } catch {
    return { isText: false, isJson: false };
  }
}

/**
 * Process a single file through Layer 1
 * @param {string} filePath - Absolute file path
 * @param {string} ext - File extension (lowercase, with dot)
 * @returns {object} Layer 1 enrichment data
 */
function processFile(filePath, ext) {
  if (isTextFile(ext)) {
    return extractTextStats(filePath, ext);
  }

  // Resilience path: when extension is missing/corrupted, sniff content first.
  const sniff = sniffTextLikeContent(filePath);
  if (sniff.isText) {
    return extractTextStats(filePath, sniff.isJson ? ".json" : ".txt");
  }

  return extractBinaryMeta(filePath, ext);
}

module.exports = { processFile };
