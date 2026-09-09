/**
 * structured_email.js — Deterministic, evidence-grounded extraction for emails
 *
 * Email markdown artifacts (e.g. `emails/dgac/*.md`, `emails/latam/*.md`) are
 * authored from the original .eml with a YAML frontmatter block that declares
 * the real message metadata:
 *
 *   ---
 *   title: "..."
 *   date: 2025-11-17T14:17:40-0300
 *   from: "REGISTRATURA DGAC <registratura@dgac.gob.cl>"
 *   to: "stockawaredev@gmail.com"
 *   subject: "..."
 *   message_id: "<...>"
 *   folder: dgac
 *   tags: [email]
 *   ---
 *
 * When the extraction LLM returns empty (a known failure mode in this
 * environment), emails can STILL be formalized honestly from this metadata —
 * no fabrication:
 *
 *   - date      → evidence/action timestamps (the real message date)
 *   - subject   → the action description (real, verbatim from the header)
 *   - from/to   → direction (inbound/outbound) + counterparty identification
 *   - folder    → correspondence channel grouping (dgac / latam / …)
 *
 * The outcome is exactly one communication event per dated email artifact, so
 * every email with a date is guaranteed to appear on the timeline — which the
 * LLM path alone could not guarantee (23 of 29 emails degraded to empty).
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const crypto = require('crypto');

const PREFIX = {
  evidence: 'EVID',
  action:   'ACTN',
  actor:    'ROLE',
  violation:'VIOL'
};

function makeNodeId(type) {
  return `${PREFIX[type] || 'NODE'}_${crypto.randomBytes(4).toString('hex')}`;
}

// ─── Text helpers ─────────────────────────────────────────────────────────────

// Decode the HTML entities that .eml→.md conversion leaves in headers
// (&lt; &gt; &quot; &amp; &#39;), then strip any wrapping quotes.
function decodeEntities(s) {
  return String(s || '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&#0?34;/g, '"')
    .replace(/&#0?39;/g, "'");
}

function stripQuotes(s) {
  return String(s || '').trim().replace(/^"|"$/g, '');
}

// Extract a display name ("Name <addr>", maybe quoted) → clean "Name".
function displayName(raw) {
  let s = decodeEntities(stripQuotes(String(raw || ''))).trim();
  // "&quot;Name (LATAM Airlines)&quot; <addr>" style: pull the address off first.
  const addrMatch = s.match(/<[^>]*>$/);
  const addr = addrMatch ? addrMatch[0].replace(/^<|>$/g, '').trim() : null;
  if (addrMatch) s = s.slice(0, addrMatch.index).trim();
  s = s.replace(/^&quot;|&quot;$/g, '').replace(/^"|"$/g, '').trim();
  if (!s) return addr || null;
  return s.slice(0, 80);
}

function addresses(raw) {
  const s = decodeEntities(String(raw || ''));
  const out = [];
  for (const m of s.matchAll(/<?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})>?/g)) {
    out.push(m[1].toLowerCase());
  }
  return out;
}

function cleanSubject(raw) {
  return decodeEntities(stripQuotes(String(raw || '')))
    .replace(/\s+/g, ' ')
    .trim();
}

// ─── Email date parsing ───────────────────────────────────────────────────────
// Frontmatter `date` may be: "2025-11-17T14:17:40-0300", "2025-07-04T15:02:39+0000",
// a quoted string, or a plain RFC3339 date. Returns:
//   { iso:   ISO-8601 UTC  (for evidence.timestamp / sortable datetime)
//     local: YYYY-MM-DDTHH:mm:ss  naive local wall-clock (for display)
//     date:  YYYY-MM-DD }
function parseEmailDate(raw) {
  const s = stripQuotes(String(raw || '')).trim().replace(/\s+/g, ' ');
  if (!s) return null;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?\s*(Z|[+-]\d{2}:?\d{2})?/i);
  if (!m) return null;
  const [, Y, Mo, D, h = '00', mi = '00', se = '00', tz] = m;
  const local = `${Y}-${Mo}-${D}T${h}:${mi}:${se}`;
  let iso = null;
  const withT = `${Y}-${Mo}-${D}T${h}:${mi}:${se}`;
  if (tz && tz.toUpperCase() !== 'Z') {
    let off = tz;
    if (!off.includes(':')) off = `${off.slice(0, 3)}:${off.slice(3)}`;
    const dt = new Date(`${withT}${off}`);
    if (!isNaN(dt)) iso = dt.toISOString();
  } else if (tz && tz.toUpperCase() === 'Z') {
    const dt = new Date(`${withT}Z`);
    if (!isNaN(dt)) iso = dt.toISOString();
  } else {
    // No offset — treat the declared wall-clock as the case-local time (naive,
    // consistent with how narrative transcripts are timestamped).
    iso = `${withT}.000Z`;
  }
  return { iso: iso || `${withT}.000Z`, local, date: `${Y}-${Mo}-${D}` };
}

// ─── Frontmatter parsing ──────────────────────────────────────────────────────
// The .md email artifacts carry a small YAML-ish header. Values are single-line
// and may be quoted (with HTML entities) or plain — enough for a light parser.
function parseFrontmatter(mdText) {
  const text = String(mdText || '');
  const m = text.match(/^\ufeff?---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!m) return null;
  const fm = {};
  for (const line of m[1].split(/\r?\n/)) {
    const lm = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!lm) continue;
    const key = lm[1].trim();
    let val = lm[2].trim();
    if (!val) continue;
    if (/^\[.*\]$/.test(val)) {
      fm[key] = val.slice(1, -1).split(',').map(x => x.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
      continue;
    }
    // Value may span one line only; single-quoted → unescape; else keep raw
    // (double-quoted values are kept including quotes, callers stripQuotes).
    fm[key] = val;
  }
  return fm;
}

// ─── Email identity helpers ───────────────────────────────────────────────────

const PASSENGER_HINTS = [
  /disconzi/i,
  /stockaware/i,
  /leandro/i,
  /@stockaware\./i
];

function isPassengerParty(addrOrName) {
  const s = String(addrOrName || '');
  return PASSENGER_HINTS.some(re => re.test(s));
}

// Map an address/domain to a functional counterparty profile.
// Identity isolation: the returned `name` is ALWAYS an institution or a role
// label — never a third-party person's name. Person-level identity stays inside
// the source email document only.
// { name, role, jurisdiction } — jurisdiction is a *hint*, only emitted when the
// counterparty is clearly tied to a single country's correspondence.
function counterpartyProfile(addrs, folder, subjectText, fromRaw) {
  const all = `${(addrs || []).join(' ')} ${folder || ''} ${subjectText || ''} ${fromRaw || ''}`.toLowerCase();

  if (/dgac|@dgac\.gob\.cl|aeron[ée]utica civil|oficina central de partes/.test(all)) {
    return { name: 'DGAC (Dirección General de Aeronáutica Civil)', role: 'regulator', jurisdiction: 'CL' };
  }
  if (/indh|@indh\.cl/.test(all)) {
    return { name: 'INDH (Instituto Nacional de Derechos Humanos)', role: 'regulator', jurisdiction: 'CL' };
  }
  if (/carabineros|@carabineros\./.test(all)) {
    return { name: 'Carabineros de Chile', role: 'police_officer', jurisdiction: 'CL' };
  }
  if (/mail delivery subsystem|mailer-daemon|postmaster/.test(all) || /delivery status|failure|bounce|undeliver/i.test(subjectText || '')) {
    return { name: 'Mail Delivery Subsystem', role: 'mail_system', jurisdiction: null };
  }
  if (/corboy|demetrio|@corboydemetrio\.|abogad|lawyer|attorney|counsel|servicios judiciales|propuesta de servicios/i.test(all)) {
    return { name: 'Legal counsel', role: 'legal_counsel', jurisdiction: null };
  }
  if (/latam|@latam\.com|sac\.latam|zendesk|servicio al cliente/i.test(all)) {
    return { name: 'LATAM Airlines', role: 'airline_staff', jurisdiction: 'CL' };
  }
  if (folder === 'dgac') {
    return { name: 'DGAC (Dirección General de Aeronáutica Civil)', role: 'regulator', jurisdiction: 'CL' };
  }
  if (folder === 'latam') {
    return { name: 'LATAM Airlines', role: 'airline_staff', jurisdiction: 'CL' };
  }
  return { name: null, role: 'other', jurisdiction: null };
}

// Classify the email by its subject/folder so the UI can group like-for-like.
function inferEmailKind(subjectText, folder) {
  const s = String(subjectText || '');
  const all = `${s} ${folder || ''}`.toLowerCase();
  if (/encuesta|survey/i.test(s)) return 'survey';
  if (/delivery status|failure notification|bounce|undeliver|delivery has failed/i.test(all)) return 'delivery_failure';
  if (/share request|compartiendo|drive/i.test(s)) return 'share_request';
  if (/propuesta|servicios judiciales|legal|abogad|attorney|counsel/i.test(all)) return 'legal_proposal';
  if (/resoluci|resolv|reembols|refund|wallet|solucionado|case.*(?:#|closed)|servicio al cliente/i.test(s)) return 'case_resolution';
  if (/solicitud|request|acceso|informaci|documentation|antecedentes|await|espera|pendiente|pending/i.test(s)) return 'information_request';
  if (/^re:|^fwd:|^enc:/i.test(s)) return 'followup';
  return 'correspondence';
}

function isEmailFile(file, fullText) {
  const ref = String(file?.file_ref || '');
  if (/\/emails\//.test(ref) || /^emails[\\/]/.test(ref)) return true;
  const fm = parseFrontmatter(fullText);
  if (!fm) return false;
  if (fm.tags && Array.isArray(fm.tags) && fm.tags.includes('email')) return true;
  if (fm.folder && (fm.date || fm.subject)) return true;
  return false;
}

// ─── Node assembly ────────────────────────────────────────────────────────────

/**
 * Build grounded ontology nodes from an email markdown artifact on disk.
 * @param {Object} file    - pipeline store file record
 * @param {string} rootDir - absolute workspace root
 * @returns {object|null}  - nodes object, or null if not an email / unreadable
 */
function buildFromEmail(file, rootDir) {
  if (!file || !rootDir || !file.file_ref) return null;

  let raw;
  try {
    raw = fs.readFileSync(path.resolve(rootDir, file.file_ref), 'utf8');
  } catch {
    return null;
  }
  if (!isEmailFile(file, raw)) return null;

  const fm = parseFrontmatter(raw);
  const dateInfo = parseEmailDate(fm && fm.date);
  if (!dateInfo) return null; // no date → caller falls back to LLM

  const subject = cleanSubject(fm.subject) || cleanSubject(fm.title) || 'Correspondence';
  const folder = String((fm.folder || '').trim() || (path.dirname(file.file_ref).split(path.sep).pop()) || '');

  // Direction & counterparty relative to the passenger.
  const fromAddrs = addresses(fm.from);
  const toAddrs = addresses(fm.to);
  const fromIsPassenger = isPassengerParty(fm.from) || fromAddrs.some(isPassengerParty);
  const direction = fromIsPassenger ? 'outbound' : 'inbound';

  // Counterparty = the non-passenger side: `from` for inbound, `to` for outbound.
  const cpRaw = direction === 'inbound' ? fm.from : (fm.to || fm.cc);
  const cpAddrs = (direction === 'inbound' ? fromAddrs : toAddrs.concat(addresses(fm.cc)))
    .filter(a => !isPassengerParty(a));
  const profile = counterpartyProfile(cpAddrs, folder, subject, cpRaw);

  const kind = inferEmailKind(subject, folder);
  const now = new Date().toISOString();
  const iso = dateInfo.iso || now;
  const evidenceId = makeNodeId('evidence');

  const evidence = {
    node_id:        evidenceId,
    type:           'Evidence',
    evidence_type:  'email',
    source:         file.file_ref,
    timestamp:      iso,
    local_datetime: dateInfo.local,
    description:    subject,
    _source_file_id: file.layers?.L0?.file_node_id || null,
    _chunk_index:   0
  };

  // One communication action per dated email artifact — grounded in the real
  // message header (date + subject + direction + counterparty). Nothing here is
  // invented; it is the email's own metadata surfaced as a timeline event.
  const actionId = makeNodeId('action');
  const cpLabel = profile.name
    || (folder === 'dgac' ? 'DGAC (Dirección General de Aeronáutica Civil)'
        : folder === 'latam' ? 'LATAM Airlines'
        : 'Correspondent');
  const directionLabel = direction === 'outbound' ? 'Email sent to' : 'Email received from';
  const description =
    `${directionLabel} ${cpLabel} — ${subject}`.slice(0, 220);

  const action = {
    node_id:            actionId,
    type:               'Action',
    action_type:        'email_correspondence',
    description,
    timestamp:          iso,
    local_datetime:     dateInfo.local,
    sequence_index:     1,
    location:           null,
    _performed_by_role_id: null,
    _evidence_id:       evidenceId,
    _segment_ids:       [],
    // ── Facets surfaced on events so emails are displayable & groupable ──
    channel:            'email',
    email_folder:       folder || null,
    direction,
    subject:            subject.slice(0, 200),
    email_kind:         kind,
    counterparty:       cpLabel,
    party_role:         profile.role || 'other',
    jurisdiction_hint:  profile.jurisdiction || null
  };

  const actorProfile = profile.name
    ? { node_id: makeNodeId('actor'), type: 'ActorRole', function: profile.role || 'other', context: null }
    : null;

  return {
    evidence,
    actions: [action],
    actors:  actorProfile ? [actorProfile] : [],
    segments: [],
    violations: [],
    llm_runs: [],
    contexts: [{
      document_type:      'email',
      primary_language:   'es',
      approximate_date:   dateInfo.date,
      jurisdiction_hint:  profile.jurisdiction || null,
      subject_matter:     subject,
      key_entities:       [cpLabel].filter(Boolean)
    }],
    _extraction_source: 'structured_email',
    _heuristic: true,
    _degraded: false
  };
}

module.exports = {
  buildFromEmail,
  isEmailFile,
  parseFrontmatter,
  parseEmailDate,
  inferEmailKind,
  counterpartyProfile,
  isPassengerParty,
  displayName,
  decodeEntities
};
