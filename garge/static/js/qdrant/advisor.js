/**
 * Qdrant Manager — Ingestion Advisor
 *
 * A chat-style assistant that knows this project's Qdrant infrastructure
 * (collections, embedding models, ingestion endpoints) and helps the user
 * turn a description + sample files into a concrete ingestion plan.
 *
 * UI element ids (see templates/qdrant.html, #advisor-tab):
 *   - advisor-assistant-select, advisor-model-select, advisor-target-collection
 *   - advisor-stream
 *   - advisor-intent-input
 *   - advisor-file-input, advisor-drop, advisor-browse, advisor-file-list
 *   - advisor-send-btn, advisor-clear-btn, advisor-copy-plan-btn
 *   - advisor-messages, advisor-payload-preview
 *   - .quick-prompt-btn[data-advisor-prompt]
 */
(function () {
  'use strict';

  // ── Project knowledge baked into the system prompt ──────────────────────
  // Keep this concise — it's sent on every request.
  const PROJECT_BRIEF = [
    'You are the Ingestion Advisor for the "Garage" Qdrant project.',
    'Your job: read the user\'s intent + sample file metadata/previews and produce a concrete ingestion plan they can execute against this project\'s HTTP API.',
    '',
    '== Embedding models available ==',
    '- all-MiniLM-L6-v2  → 384 dims (fast, English/multilingual ok)',
    '- BAAI/bge-base / nomic-embed-text → 768 dims (default for richer text)',
    'Distance metric default: Cosine (use Dot for normalized vectors, Euclid rarely).',
    '',
    '== Ingestion endpoints (FastAPI, base http://localhost:8066) ==',
    'Generic Qdrant router (routes/qdrant_router.py):',
    '  POST /v1/qdrant/collections                      create collection {name, vectors:{size,distance}, ...}',
    '  POST /v1/qdrant/collections/{name}/ingest        upload files (multipart) — generic chunked text+embed',
    '  POST /v1/qdrant/collections/structured_ingest    ingest pre-built {points:[{id,vector,payload}]}',
    '  POST /v1/qdrant/collections/{name}/ensure-indexes ensure payload indexes (legal/compliance fields)',
    '  POST /v1/qdrant/embed-case-directory             scan a folder of legal case files and embed everything',
    '  POST /v1/qdrant/search                            text search → embeds query and runs vector search',
    '  POST /v1/qdrant/query                             vector search with raw vector',
    '  GET  /v1/qdrant/collections                       list collections',
    '  GET  /v1/qdrant/collections/{name}/summary        stats',
    '',
    'Generic ingestion router (routes/ingestion.py, prefix /v1/ingestion or similar):',
    '  POST /ingest-directory      bulk ingest a server-side directory',
    '  POST /ingest-file           single-file ingestion with chunking',
    '  POST /ingest-legal-file     legal-aware chunking + structure extraction',
    '  POST /analyze-document-structure  dry-run: detects sections/articles/clauses',
    '',
    'Legal v2 router (routes/legal_doc_ingestion_v2.py):',
    '  POST /ingest-legal-file-enhanced   legal extraction + quality validation',
    '  POST /ingest-legal-folder          batch over a folder of legal docs',
    '  POST /analyze-document-structure   dry-run analyzer',
    '',
    'Legal CSV router (routes/legal_ingestion.py):',
    '  POST /upload-csv                   ingest a CSV of jurisprudence rows',
    '  POST /ingest-file                  legal-CSV-style ingestion',
    '  POST /search/{collection_name}     semantic search over legal collections',
    '',
    'Transcript router (routes/transcript_ingestion.py):',
    '  POST /analyze            preview transcript structure (speakers, segments)',
    '  POST /ingest-enhanced    transcripts with speaker/time-aware chunking',
    '  POST /ingest-json        ingest pre-structured transcript JSON',
    '',
    '== Decision rules you should apply ==',
    '1. PDFs/DOCX of laws, rulings, contracts → use the legal v2 routes (`/ingest-legal-file-enhanced` or `/ingest-legal-folder`) + `ensure-indexes`.',
    '2. CSV of case metadata → `/upload-csv` (legal_ingestion). Recommend index fields (case_number, judge, court, date).',
    '3. Transcript JSON / VTT / SRT / speaker-tagged text → transcript router (`/ingest-enhanced` or `/ingest-json`).',
    '4. Generic prose (markdown, articles, notes) → `/v1/qdrant/collections/{name}/ingest` after creating a collection with the right vector size.',
    '5. Pre-embedded vectors → `/v1/qdrant/collections/structured_ingest` with points.',
    '',
    '== What every plan must include ==',
    '- Recommended collection name, vector size, distance, payload schema, indexed fields.',
    '- Whether to create a NEW collection or reuse one of the existing ones (listed in the runtime context block).',
    '- Concrete `curl` commands (one per step) against `http://localhost:8066` using the endpoints above.',
    '- Suggested chunking strategy and metadata fields tailored to the user\'s files.',
    '- A brief search-query example showing how the user will retrieve later.',
    '',
    'Be terse, structured, and use Markdown headings + fenced ```bash blocks for curl. Never invent endpoints that are not in the list above.'
  ].join('\n');

  // ── Internal state ──────────────────────────────────────────────────────
  const state = {
    files: [],          // [{name, size, type, preview, isText}]
    history: [],        // chat history (excluding system prompt)
    assistants: [],
    collections: [],
    booted: false,
  };

  const MAX_FILES = 10;
  const TEXT_PREVIEW_BYTES = 4096;
  const TEXT_EXT = /\.(txt|md|markdown|json|jsonl|ndjson|csv|tsv|yaml|yml|xml|html|htm|log|rst|py|js|ts|sql|vtt|srt)$/i;

  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function fmtBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(2) + ' MB';
  }

  // ── Population of selects ──────────────────────────────────────────────
  async function loadCollections() {
    try {
      const r = await fetch('/v1/qdrant/collections');
      if (!r.ok) return;
      const data = await r.json();
      const list = Array.isArray(data) ? data : (data.collections || data.result?.collections || []);
      state.collections = list.map(c => (typeof c === 'string' ? { name: c } : c));
      const sel = $('advisor-target-collection');
      if (!sel) return;
      const current = sel.value;
      sel.innerHTML = '<option value="">— Let the agent recommend / create new —</option>';
      state.collections.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name || c;
        opt.textContent = c.name || c;
        sel.appendChild(opt);
      });
      if (current) sel.value = current;
    } catch (e) {
      console.warn('Advisor: failed to load collections', e);
    }
  }

  async function loadAssistants() {
    try {
      const r = await fetch('/v1/assistants/');
      if (!r.ok) return;
      const data = await r.json();
      const list = Array.isArray(data) ? data : (data.data || data.assistants || []);
      state.assistants = list;
      const sel = $('advisor-assistant-select');
      if (!sel) return;
      list.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a.id || a.name;
        opt.textContent = (a.name || a.id) + (a.model ? ` (${a.model})` : '');
        sel.appendChild(opt);
      });
    } catch (e) {
      console.warn('Advisor: failed to load assistants', e);
    }
  }

  // ── File handling ──────────────────────────────────────────────────────
  function renderFileList() {
    const ul = $('advisor-file-list');
    if (!ul) return;
    ul.innerHTML = '';
    state.files.forEach((f, idx) => {
      const li = document.createElement('li');
      li.innerHTML = `
        <span><i class="fas fa-file"></i> ${escapeHtml(f.name)}</span>
        <span class="meta">${escapeHtml(f.type || 'binary')} · ${fmtBytes(f.size)}${f.isText ? ' · preview' : ''}</span>
        <button title="Remove" data-idx="${idx}"><i class="fas fa-times"></i></button>`;
      ul.appendChild(li);
    });
    ul.querySelectorAll('button[data-idx]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.files.splice(parseInt(btn.dataset.idx, 10), 1);
        renderFileList();
      });
    });
  }

  async function readFilePreview(file) {
    const isText = TEXT_EXT.test(file.name) || (file.type && file.type.startsWith('text/'));
    let preview = '';
    if (isText) {
      try {
        const slice = file.slice(0, TEXT_PREVIEW_BYTES);
        preview = await slice.text();
      } catch (e) {
        preview = '';
      }
    }
    return {
      name: file.name,
      size: file.size,
      type: file.type || '',
      isText,
      preview,
    };
  }

  async function addFiles(fileList) {
    const remaining = MAX_FILES - state.files.length;
    const incoming = Array.from(fileList).slice(0, remaining);
    for (const f of incoming) {
      const meta = await readFilePreview(f);
      state.files.push(meta);
    }
    renderFileList();
  }

  function buildFilesBlock() {
    if (!state.files.length) return '';
    const parts = ['## Attached files'];
    state.files.forEach((f, i) => {
      parts.push(`### File ${i + 1}: ${f.name}`);
      parts.push(`- size: ${fmtBytes(f.size)}`);
      parts.push(`- mime: ${f.type || '(unknown)'}`);
      if (f.isText && f.preview) {
        const trimmed = f.preview.length > TEXT_PREVIEW_BYTES
          ? f.preview.slice(0, TEXT_PREVIEW_BYTES) + '\n...[truncated]'
          : f.preview;
        parts.push('```\n' + trimmed + '\n```');
      } else {
        parts.push('_(binary file — only metadata sent)_');
      }
    });
    return parts.join('\n');
  }

  function buildRuntimeContext() {
    const cols = state.collections.length
      ? state.collections.map(c => `- ${c.name}${c.vectors_config?.size ? ` (vec=${c.vectors_config.size})` : ''}`).join('\n')
      : '_(no collections yet)_';
    const target = $('advisor-target-collection')?.value || '';
    return [
      '## Runtime context',
      '### Existing collections',
      cols,
      target ? `### User-selected target collection\n- ${target}` : '### Target collection\n_user has not pre-selected one — recommend one_',
    ].join('\n');
  }

  // ── Rendering ──────────────────────────────────────────────────────────
  function renderMarkdown(text) {
    if (window.marked && typeof window.marked.parse === 'function') {
      try { return window.marked.parse(text); } catch (e) { /* fall through */ }
    }
    return escapeHtml(text).replace(/\n/g, '<br>');
  }

  function appendMessage(role, content) {
    const wrap = $('advisor-messages');
    if (!wrap) return null;
    const msg = document.createElement('div');
    msg.className = `chat-message ${role === 'user' ? 'user' : 'assistant'}`;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = role === 'user' ? escapeHtml(content).replace(/\n/g, '<br>') : renderMarkdown(content);
    msg.appendChild(bubble);
    wrap.appendChild(msg);
    wrap.scrollTop = wrap.scrollHeight;
    return bubble;
  }

  // ── Streaming response parsing (handles SSE-ish chunked text) ─────────
  async function readStreamInto(response, bubble) {
    const reader = response.body && response.body.getReader ? response.body.getReader() : null;
    if (!reader) {
      const txt = await response.text();
      const out = extractAssistantText(txt);
      bubble.innerHTML = renderMarkdown(out);
      return out;
    }
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let acc = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Try to parse SSE-style "data: {...}" frames; otherwise treat each line as NDJSON or raw text.
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const raw of lines) {
        const line = raw.trim();
        if (!line) continue;
        const payload = line.startsWith('data:') ? line.slice(5).trim() : line;
        if (payload === '[DONE]') continue;
        let delta = '';
        try {
          const obj = JSON.parse(payload);
          delta = obj.choices?.[0]?.delta?.content
                ?? obj.choices?.[0]?.message?.content
                ?? obj.delta
                ?? obj.content
                ?? obj.response
                ?? '';
        } catch {
          delta = payload;
        }
        if (delta) {
          acc += delta;
          bubble.innerHTML = renderMarkdown(acc);
          const wrap = $('advisor-messages');
          if (wrap) wrap.scrollTop = wrap.scrollHeight;
        }
      }
    }
    if (buffer.trim()) {
      const tail = extractAssistantText(buffer.trim());
      if (tail) {
        acc += tail;
        bubble.innerHTML = renderMarkdown(acc);
      }
    }
    return acc;
  }

  function extractAssistantText(txt) {
    try {
      const obj = JSON.parse(txt);
      return obj.choices?.[0]?.message?.content
          ?? obj.choices?.[0]?.delta?.content
          ?? obj.content
          ?? obj.response
          ?? obj.detail
          ?? obj.error?.message
          ?? txt;
    } catch {
      return txt;
    }
  }

  // ── Main: send to advisor ──────────────────────────────────────────────
  function isExternalAssistant(a) {
    if (!a) return false;
    const m = (a.model || '').toLowerCase();
    const id = (a.id || '').toLowerCase();
    return m.includes('deepseek') || m.includes('gpt') || m.includes('claude')
        || id.includes('deepseek') || id.includes('openai') || id.includes('anthropic');
  }

  async function send() {
    const intent = ($('advisor-intent-input')?.value || '').trim();
    if (!intent && !state.files.length) {
      appendMessage('assistant', '_Please describe what you want to ingest, or attach at least one sample file._');
      return;
    }

    await loadCollections(); // refresh so the agent sees latest list

    const assistantId = $('advisor-assistant-select')?.value || '';
    const assistant = state.assistants.find(a => (a.id || a.name) === assistantId);
    const model = $('advisor-model-select')?.value || 'deepseek-chat';
    const stream = $('advisor-stream')?.checked !== false;

    const userBlocks = [];
    if (intent) userBlocks.push('## User intent\n' + intent);
    userBlocks.push(buildRuntimeContext());
    const filesBlock = buildFilesBlock();
    if (filesBlock) userBlocks.push(filesBlock);
    userBlocks.push('## Task\nProduce a step-by-step ingestion plan tailored to the above. Include collection design, chunking strategy, exact endpoint(s) from the project list, and runnable curl examples.');
    const userMessage = userBlocks.join('\n\n');

    state.history.push({ role: 'user', content: userMessage });
    appendMessage('user', intent || `(${state.files.length} file(s) attached)`);
    const bubble = appendMessage('assistant', '_Thinking…_');

    const messages = [
      { role: 'system', content: PROJECT_BRIEF },
      ...state.history,
    ];

    let endpoint;
    let payload;
    if (assistant && !isExternalAssistant(assistant)) {
      endpoint = `/v1/assistants/${assistant.id || assistantId}/chat`;
      payload = { model: assistant.model || model, messages, stream };
    } else {
      endpoint = '/v1/assistants/deepseek-stream-proxy';
      payload = { model: assistant?.model || model, messages, stream };
    }

    const previewEl = $('advisor-payload-preview');
    if (previewEl) {
      previewEl.textContent = JSON.stringify({ endpoint, ...payload }, null, 2);
    }

    const sendBtn = $('advisor-send-btn');
    if (sendBtn) sendBtn.disabled = true;

    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': stream ? 'text/event-stream' : 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const errTxt = await resp.text().catch(() => '');
        bubble.innerHTML = renderMarkdown(`**Error ${resp.status}**: ${escapeHtml(extractAssistantText(errTxt) || resp.statusText)}`);
        return;
      }

      let final = '';
      if (stream) {
        bubble.innerHTML = '';
        final = await readStreamInto(resp, bubble);
      } else {
        const txt = await resp.text();
        final = extractAssistantText(txt);
        bubble.innerHTML = renderMarkdown(final);
      }
      if (final && final.trim()) {
        state.history.push({ role: 'assistant', content: final });
      } else {
        bubble.innerHTML = renderMarkdown('_(no content returned)_');
      }
      // Clear intent for next turn but keep files
      const intentEl = $('advisor-intent-input');
      if (intentEl) intentEl.value = '';
    } catch (e) {
      console.error('Advisor send failed', e);
      bubble.innerHTML = renderMarkdown(`**Network error**: ${escapeHtml(e.message || String(e))}`);
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  // ── Wiring ─────────────────────────────────────────────────────────────
  function wire() {
    const drop = $('advisor-drop');
    const fileInput = $('advisor-file-input');
    const browse = $('advisor-browse');

    if (browse) browse.addEventListener('click', (e) => { e.preventDefault(); fileInput?.click(); });
    if (drop) {
      drop.addEventListener('click', (e) => { if (e.target.tagName !== 'A') fileInput?.click(); });
      drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('drag-over'); });
      drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
      drop.addEventListener('drop', (e) => {
        e.preventDefault();
        drop.classList.remove('drag-over');
        if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
      });
    }
    if (fileInput) {
      fileInput.addEventListener('change', (e) => {
        if (e.target.files?.length) addFiles(e.target.files);
        e.target.value = '';
      });
    }

    $('advisor-send-btn')?.addEventListener('click', send);
    $('advisor-intent-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
    });

    $('advisor-clear-btn')?.addEventListener('click', () => {
      state.history = [];
      const wrap = $('advisor-messages');
      if (wrap) {
        wrap.innerHTML = `<div class="chat-message assistant"><div class="chat-bubble">Conversation cleared. Tell me what you want to ingest.</div></div>`;
      }
    });

    $('advisor-copy-plan-btn')?.addEventListener('click', async () => {
      const lastAssistant = [...state.history].reverse().find(m => m.role === 'assistant');
      if (!lastAssistant) return;
      try {
        await navigator.clipboard.writeText(lastAssistant.content);
        const btn = $('advisor-copy-plan-btn');
        if (btn) {
          const orig = btn.innerHTML;
          btn.innerHTML = '<i class="fas fa-check"></i> Copied';
          setTimeout(() => { btn.innerHTML = orig; }, 1500);
        }
      } catch (e) {
        console.warn('Clipboard failed', e);
      }
    });

    document.querySelectorAll('.quick-prompt-btn[data-advisor-prompt]').forEach(btn => {
      btn.addEventListener('click', () => {
        const prompt = btn.dataset.advisorPrompt || '';
        const intent = $('advisor-intent-input');
        if (intent) {
          intent.value = intent.value ? (intent.value.trim() + '\n' + prompt) : prompt;
          intent.focus();
        }
      });
    });

    // Refresh selects when the Advisor tab is opened
    document.querySelectorAll('.tab-btn[data-tab="advisor"]').forEach(b => {
      b.addEventListener('click', () => {
        loadCollections();
        if (!state.booted) { loadAssistants(); state.booted = true; }
      });
    });
  }

  function init() {
    if (!$('advisor-tab')) return; // not on this page
    wire();
    // Lazy-load on first render too — cheap.
    loadCollections();
    loadAssistants();
    state.booted = true;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
