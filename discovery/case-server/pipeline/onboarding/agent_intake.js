/**
 * agent_intake.js — Conversational, scripted intake agent.
 *
 * Drives the same intake_spec the form mode produces, but one question at a time.
 * Deterministic parsers cover all required fields; an optional LLM step
 * (callLLM) can be used to normalize freeform replies — but the flow does not
 * require an LLM key to complete successfully.
 *
 * State lives at <workspace>/.discovery/agent_intake.json:
 *   {
 *     spec_version: "1.0.0",
 *     turn: <number>,
 *     completed: <bool>,
 *     partial_spec: { ...intake_spec fields collected so far... },
 *     history: [{ role: "agent" | "user", text, at }],
 *     pending: { kind, prompt, ... }   // current question awaiting user reply
 *   }
 */

"use strict";

const fs = require("fs");
const path = require("path");

const META_DIR = ".discovery";
const FILE_AGENT_INTAKE = "agent_intake.json";

// Curated option lists kept in sync with the form-mode UI ────────────
const DOMAINS = [
  "legal_case",
  "research",
  "business_records",
  "technical_docs",
  "personal_archive",
  "investigation",
  "mixed",
  "other",
];

const PRIVACY_LEVELS = ["public", "confidential", "privileged", "sealed"];

const FILE_KINDS = [
  "transcripts",
  "audio_recordings",
  "video_recordings",
  "photos",
  "screenshots",
  "emails",
  "chat_logs",
  "contracts",
  "filings",
  "court_documents",
  "regulatory_documents",
  "law_texts",
  "case_law",
  "reports",
  "spreadsheets",
  "structured_data",
  "boarding_passes_or_tickets",
  "id_documents",
  "personal_notes",
  "other",
];

const JURISDICTIONS = ["BR", "CL", "AR", "US", "EU", "UK", "MX", "INT", "UN"];

const TEMPLATE_BY_DOMAIN = {
  legal_case: "legal-case",
  investigation: "legal-case",
  research: "blank",
  business_records: "blank",
  technical_docs: "blank",
  personal_archive: "blank",
  mixed: "blank",
  other: "blank",
};

// ── persistence ─────────────────────────────────────────────────────
function statePath(workspaceRoot) {
  return path.join(workspaceRoot, META_DIR, FILE_AGENT_INTAKE);
}

function loadState(workspaceRoot) {
  const p = statePath(workspaceRoot);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (_) {
    return null;
  }
}

function saveState(workspaceRoot, state) {
  const p = statePath(workspaceRoot);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(state, null, 2));
}

function clearState(workspaceRoot) {
  const p = statePath(workspaceRoot);
  if (fs.existsSync(p)) fs.unlinkSync(p);
}

// ── parsers ─────────────────────────────────────────────────────────
function normalizeText(s) {
  return String(s == null ? "" : s).trim();
}

function tokensFromList(text) {
  return normalizeText(text)
    .split(/[,;\n]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function parseDomain(text) {
  const t = normalizeText(text).toLowerCase();
  if (!t) return null;
  // exact slug
  if (DOMAINS.includes(t)) return t;
  // fuzzy keywords
  if (/(legal|case|court|lawsuit|filing|complaint)/.test(t)) return "legal_case";
  if (/(research|study|academic|paper)/.test(t)) return "research";
  if (/(business|company|corporate|finance)/.test(t)) return "business_records";
  if (/(tech|engineering|software|api|spec)/.test(t)) return "technical_docs";
  if (/(personal|family|archive|memoir)/.test(t)) return "personal_archive";
  if (/(investigat|incident|forensic|inquiry)/.test(t)) return "investigation";
  if (/(mixed|various|multiple|several)/.test(t)) return "mixed";
  if (/(other|else|unsure)/.test(t)) return "other";
  return null;
}

function parsePrivacy(text) {
  const t = normalizeText(text).toLowerCase();
  if (!t) return null;
  for (const lvl of PRIVACY_LEVELS) if (t.includes(lvl)) return lvl;
  if (/secret|seal|sealed/.test(t)) return "sealed";
  if (/priv/.test(t)) return "privileged";
  if (/conf/.test(t)) return "confidential";
  if (/public/.test(t)) return "public";
  return null;
}

function parseJurisdictions(text) {
  const tokens = tokensFromList(text).map((t) => t.toUpperCase());
  if (tokens.length === 1 && /^(NONE|SKIP|N\/A)$/.test(tokens[0])) return [];
  const out = [];
  for (const tok of tokens) {
    const code = tok.replace(/[^A-Z]/g, "");
    if (JURISDICTIONS.includes(code)) out.push(code);
  }
  return out;
}

function parseFileKinds(text) {
  const tokens = tokensFromList(text).map((t) => t.toLowerCase().replace(/\s+/g, "_"));
  if (tokens.length === 1 && /^(none|skip|n\/a)$/.test(tokens[0])) return [];
  const out = new Set();
  for (const tok of tokens) {
    if (FILE_KINDS.includes(tok)) {
      out.add(tok);
      continue;
    }
    // Loose keyword matching
    if (/(transcript)/.test(tok)) out.add("transcripts");
    else if (/(audio|recording|mp3|wav)/.test(tok)) out.add("audio_recordings");
    else if (/(video|mp4|mov)/.test(tok)) out.add("video_recordings");
    else if (/(photo|image|jpeg|jpg|png)/.test(tok)) out.add("photos");
    else if (/(screenshot|screen)/.test(tok)) out.add("screenshots");
    else if (/(email|mail)/.test(tok)) out.add("emails");
    else if (/(chat|message|sms|whatsapp)/.test(tok)) out.add("chat_logs");
    else if (/(contract)/.test(tok)) out.add("contracts");
    else if (/(filing)/.test(tok)) out.add("filings");
    else if (/(court)/.test(tok)) out.add("court_documents");
    else if (/(regulat)/.test(tok)) out.add("regulatory_documents");
    else if (/(law|statute)/.test(tok)) out.add("law_texts");
    else if (/(case.?law|jurisprud)/.test(tok)) out.add("case_law");
    else if (/(report)/.test(tok)) out.add("reports");
    else if (/(spreadsheet|xlsx|csv)/.test(tok)) out.add("spreadsheets");
    else if (/(json|xml|database|db|structured)/.test(tok)) out.add("structured_data");
    else if (/(ticket|boarding|pass)/.test(tok)) out.add("boarding_passes_or_tickets");
    else if (/(id|passport|license)/.test(tok)) out.add("id_documents");
    else if (/(note)/.test(tok)) out.add("personal_notes");
  }
  return Array.from(out);
}

function parseTimeframe(text) {
  const t = normalizeText(text).toLowerCase();
  if (!t || /^(skip|none|no|n\/a)$/.test(t)) return null;
  const tf = {};
  if (/ongoing/.test(t)) tf.is_ongoing = true;
  // extract dates YYYY-MM-DD
  const dates = (t.match(/\d{4}-\d{2}-\d{2}/g) || []).slice(0, 2);
  if (dates[0]) tf.from = dates[0];
  if (dates[1]) tf.to = dates[1];
  // year-only fallback "2022 to 2024"
  if (!dates.length) {
    const years = (t.match(/(19|20)\d{2}/g) || []).slice(0, 2);
    if (years[0]) tf.from = `${years[0]}-01-01`;
    if (years[1]) tf.to = `${years[1]}-12-31`;
  }
  return Object.keys(tf).length ? tf : null;
}

function parseTags(text) {
  const t = normalizeText(text);
  if (!t || /^(skip|none|no|n\/a)$/i.test(t)) return [];
  return tokensFromList(t).map((s) => s.replace(/^#/, "").trim()).filter(Boolean);
}

function parseYesNo(text) {
  const t = normalizeText(text).toLowerCase();
  if (!t) return null;
  if (/^(y|yes|yeah|yep|sure|ok|okay|confirm|go|save|do it)/.test(t)) return true;
  if (/^(n|no|nope|cancel|stop|wait)/.test(t)) return false;
  return null;
}

// ── question script ─────────────────────────────────────────────────
const QUESTIONS = [
  {
    kind: "goal",
    prompt:
      "Hi — I'll set up your case workspace. In one paragraph, what is this corpus about and what do you want to do with it?",
    hints: ["e.g. 'Prepare evidence for a regulatory complaint covering events of April–July 2024.'"],
    parse: (text) => {
      const t = normalizeText(text);
      return t.length >= 8 ? t : null;
    },
    apply: (spec, value) => {
      spec.goal = spec.goal || {};
      spec.goal.summary = value;
    },
    retryHint: "I need at least a sentence. Try a one-paragraph description of the goal.",
  },
  {
    kind: "domain",
    prompt: "What kind of corpus is this?",
    hints: [
      "Pick one: legal_case · research · business_records · technical_docs · personal_archive · investigation · mixed · other",
    ],
    parse: parseDomain,
    apply: (spec, value) => {
      spec.domain = value;
    },
    retryHint: "Reply with one of: legal_case, research, business_records, technical_docs, personal_archive, investigation, mixed, other.",
  },
  {
    kind: "jurisdictions",
    prompt: "Which jurisdictions apply? (comma-separated codes — or 'none')",
    hints: ["e.g. 'BR, US, EU' · valid: BR · CL · AR · US · EU · UK · MX · INT · UN"],
    skipWhen: (spec) => !["legal_case", "investigation"].includes(spec.domain),
    parse: (text) => {
      const list = parseJurisdictions(text);
      return list; // always accept (empty allowed)
    },
    apply: (spec, value) => {
      if (value && value.length) spec.jurisdictions = value;
    },
    retryHint: null,
  },
  {
    kind: "expected_file_kinds",
    prompt: "What kinds of files will you upload? (comma-separated — or 'skip')",
    hints: ["e.g. 'transcripts, emails, contracts'"],
    parse: (text) => parseFileKinds(text),
    apply: (spec, value) => {
      if (value && value.length) spec.expected_file_kinds = value;
    },
    retryHint: null,
  },
  {
    kind: "timeframe",
    prompt: "Does this corpus cover a specific period? Reply with 'YYYY-MM-DD to YYYY-MM-DD', 'ongoing', or 'skip'.",
    hints: ["e.g. '2024-04-01 to 2024-07-31' or 'ongoing'"],
    parse: (text) => {
      const t = normalizeText(text).toLowerCase();
      if (/^(skip|none|n\/a)$/.test(t)) return { _skip: true };
      return parseTimeframe(text) || { _skip: true };
    },
    apply: (spec, value) => {
      if (value && !value._skip) spec.timeframe = value;
    },
    retryHint: null,
  },
  {
    kind: "privacy_level",
    prompt: "Privacy level? (public / confidential / privileged / sealed) — confidential is the default.",
    hints: [],
    parse: (text) => {
      const t = normalizeText(text).toLowerCase();
      if (!t || /^(skip|default)$/.test(t)) return "confidential";
      return parsePrivacy(text);
    },
    apply: (spec, value) => {
      spec.privacy_level = value;
    },
    retryHint: "Reply with public, confidential, privileged, or sealed.",
  },
  {
    kind: "tags",
    prompt: "Any tags to attach? Comma-separated, or 'skip'.",
    hints: ["e.g. 'litigation, compliance-audit, q3-2024'"],
    parse: (text) => parseTags(text),
    apply: (spec, value) => {
      if (value && value.length) {
        spec.goal = spec.goal || {};
        spec.goal.tags = value;
      }
    },
    retryHint: null,
  },
  {
    kind: "template",
    prompt: null, // computed below
    hints: ["valid templates: legal-case, blank"],
    buildPrompt: (spec, templates) => {
      const suggested = TEMPLATE_BY_DOMAIN[spec.domain] || "blank";
      const ids = (templates || []).map((t) => t.id).filter(Boolean);
      const valid = ids.length ? ids : ["legal-case", "blank"];
      return `I'll seed the structure with the **${suggested}** template. Reply 'yes' to accept, or pick another (${valid.join(" / ")}).`;
    },
    parse: (text, ctx) => {
      const t = normalizeText(text).toLowerCase();
      const suggested = TEMPLATE_BY_DOMAIN[ctx.partial_spec.domain] || "blank";
      const yes = parseYesNo(text);
      if (yes === true || !t) return suggested;
      const ids = (ctx.templates || []).map((tt) => tt.id).filter(Boolean);
      if (ids.includes(t)) return t;
      if (["legal-case", "blank"].includes(t)) return t;
      return null;
    },
    apply: (spec, value) => {
      spec.template_id = value;
    },
    retryHint: "Reply 'yes' to accept the suggestion, or one of: legal-case, blank.",
  },
  {
    kind: "confirm",
    prompt: null,
    buildPrompt: (spec) => {
      const lines = [
        "Here's what I have:",
        `· goal: ${spec.goal && spec.goal.summary ? spec.goal.summary : "(missing)"}`,
        `· domain: ${spec.domain || "(missing)"}`,
      ];
      if (spec.jurisdictions && spec.jurisdictions.length) lines.push(`· jurisdictions: ${spec.jurisdictions.join(", ")}`);
      if (spec.expected_file_kinds && spec.expected_file_kinds.length)
        lines.push(`· file kinds: ${spec.expected_file_kinds.join(", ")}`);
      if (spec.timeframe) lines.push(`· timeframe: ${JSON.stringify(spec.timeframe)}`);
      lines.push(`· privacy: ${spec.privacy_level}`);
      if (spec.goal && spec.goal.tags && spec.goal.tags.length) lines.push(`· tags: ${spec.goal.tags.join(", ")}`);
      lines.push(`· template: ${spec.template_id}`);
      lines.push("");
      lines.push("Save and generate blueprint v1? (yes / no)");
      return lines.join("\n");
    },
    parse: (text) => {
      const yn = parseYesNo(text);
      return yn === null ? null : { confirmed: yn };
    },
    apply: () => {},
    retryHint: "Please reply 'yes' to save, or 'no' to abort.",
  },
];

// ── flow control ────────────────────────────────────────────────────
function nextQuestion(state, templates) {
  for (let i = state.turn; i < QUESTIONS.length; i += 1) {
    const q = QUESTIONS[i];
    if (q.skipWhen && q.skipWhen(state.partial_spec)) {
      state.turn = i + 1;
      continue;
    }
    const prompt = q.buildPrompt
      ? q.buildPrompt(state.partial_spec, templates)
      : q.prompt;
    return {
      kind: q.kind,
      prompt,
      hints: q.hints || [],
      progress: { step: i + 1, total: QUESTIONS.length },
    };
  }
  return null;
}

function startSession({ workspaceRoot, sessionId, templates }) {
  const state = {
    spec_version: "1.0.0",
    session_id: sessionId,
    started_at: new Date().toISOString(),
    turn: 0,
    completed: false,
    partial_spec: {
      intake_mode: "agent",
      privacy_level: "confidential",
    },
    history: [],
    pending: null,
  };
  const q = nextQuestion(state, templates);
  state.pending = q;
  state.history.push({ role: "agent", text: q.prompt, at: new Date().toISOString() });
  saveState(workspaceRoot, state);
  return { state, question: q };
}

function applyReply({ workspaceRoot, replyText, templates }) {
  const state = loadState(workspaceRoot);
  if (!state) {
    const err = new Error("No agent intake session found. Call /intake/agent/start first.");
    err.statusCode = 404;
    throw err;
  }
  if (state.completed) {
    return { state, question: null, completed: true };
  }
  const current = QUESTIONS[state.turn];
  if (!current) {
    state.completed = true;
    saveState(workspaceRoot, state);
    return { state, question: null, completed: true };
  }

  state.history.push({ role: "user", text: String(replyText || ""), at: new Date().toISOString() });

  const ctx = { partial_spec: state.partial_spec, templates };
  let parsed;
  try {
    parsed = current.parse(replyText, ctx);
  } catch (e) {
    parsed = null;
  }

  // For multi-select / optional questions, accept null/empty arrays as "skip"
  const optionalKinds = new Set(["jurisdictions", "expected_file_kinds", "tags"]);
  const acceptedNull =
    optionalKinds.has(current.kind) && (parsed === null || (Array.isArray(parsed) && !parsed.length));

  if (parsed === null && !acceptedNull) {
    // ask again
    const retry = current.retryHint || "Sorry, I didn't catch that — could you rephrase?";
    state.pending = {
      kind: current.kind,
      prompt: retry,
      hints: current.hints || [],
      progress: { step: state.turn + 1, total: QUESTIONS.length },
      retry: true,
    };
    state.history.push({ role: "agent", text: retry, at: new Date().toISOString() });
    saveState(workspaceRoot, state);
    return { state, question: state.pending, completed: false };
  }

  // confirm question — if user answered "no", reset turn back so they can edit
  if (current.kind === "confirm") {
    if (parsed && parsed.confirmed) {
      state.completed = true;
      state.pending = null;
      saveState(workspaceRoot, state);
      return { state, question: null, completed: true, confirmed: true };
    }
    // user said no → clear and ask goal again
    state.turn = 0;
    state.partial_spec = { intake_mode: "agent", privacy_level: "confidential" };
    const q = nextQuestion(state, templates);
    state.pending = q;
    state.history.push({ role: "agent", text: q.prompt, at: new Date().toISOString() });
    saveState(workspaceRoot, state);
    return { state, question: q, completed: false, restarted: true };
  }

  current.apply(state.partial_spec, parsed);
  state.turn += 1;
  const next = nextQuestion(state, templates);
  if (!next) {
    state.completed = true;
    state.pending = null;
    saveState(workspaceRoot, state);
    return { state, question: null, completed: true };
  }
  state.pending = next;
  state.history.push({ role: "agent", text: next.prompt, at: new Date().toISOString() });
  saveState(workspaceRoot, state);
  return { state, question: next, completed: false };
}

function getState(workspaceRoot) {
  return loadState(workspaceRoot);
}

function buildFinalSpec(state) {
  const spec = { ...state.partial_spec };
  if (!spec.template_id) spec.template_id = TEMPLATE_BY_DOMAIN[spec.domain] || "blank";
  if (!spec.privacy_level) spec.privacy_level = "confidential";
  spec.intake_mode = "agent";
  return spec;
}

module.exports = {
  startSession,
  applyReply,
  getState,
  clearState,
  buildFinalSpec,
  QUESTIONS,
  // exposed for tests
  parseDomain,
  parsePrivacy,
  parseJurisdictions,
  parseFileKinds,
  parseTimeframe,
  parseTags,
  parseYesNo,
};
