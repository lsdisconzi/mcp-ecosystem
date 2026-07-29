/* ═══════════════════════════════════════════════════════════════════
   MESHY UI — Shaders view integration for the official
   `meshy-ai-mcp-server` (npm) MCP server, registered as `meshy` in
   .mcp-bridge-config.json.
   Exposes: meshyOpenModal, meshyCloseModal, meshySwitchTab, meshySubmit.
   Strategy: the UI does NOT call Meshy directly. It drafts a natural-
   language instruction for the agent (openclaude), which then selects
   the correct create_/retrieve_/stream_ tool. Task progress/results
   stay inside the Shaders brainstorm lane.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }
  let _meshyCandidateGlbs = [];

  function show(el) { if (el) el.style.display = 'flex'; }
  function hide(el) { if (el) el.style.display = 'none'; }

  function _tail(url) {
    try {
      const clean = String(url || '').split('?')[0].split('#')[0];
      const parts = clean.split('/').filter(Boolean);
      return decodeURIComponent(parts[parts.length - 1] || clean || 'model.glb');
    } catch (_) {
      return String(url || 'model.glb');
    }
  }

  function _dedupeUrls(list) {
    const seen = new Set();
    const out = [];
    (Array.isArray(list) ? list : []).forEach(function (raw) {
      const u = String(raw || '').trim();
      if (!u) return;
      const key = u.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(u);
    });
    return out;
  }

  function setSubmitStatus(message, isError) {
    const el = $('meshySubmitStatus');
    if (!el) return;
    const msg = String(message || '').trim();
    if (!msg) {
      el.textContent = '';
      el.style.display = 'none';
      return;
    }
    el.textContent = msg;
    el.style.display = 'block';
    el.style.color = isError ? '#FCA5A5' : '#A7F3D0';
  }

  function clearSubmitStatus() {
    setSubmitStatus('', false);
  }

  window.meshyChooseImportFromCandidates = function () {
    const urls = _dedupeUrls(_meshyCandidateGlbs);
    if (!urls.length) {
      if (typeof window.shToast === 'function') window.shToast('Nenhum GLB pronto para importar.');
      return;
    }
    if (urls.length === 1) {
      if (typeof window.sh3dLoadGLB === 'function') window.sh3dLoadGLB(urls[0]);
      return;
    }
    const listing = urls.map(function (u, idx) {
      return (idx + 1) + '. ' + _tail(u);
    }).join('\n');
    const raw = window.prompt('Escolha o GLB para importar (numero):\n\n' + listing, '1');
    if (raw === null) return;
    const pick = parseInt(String(raw).trim(), 10);
    if (!Number.isFinite(pick) || pick < 1 || pick > urls.length) {
      if (typeof window.shToast === 'function') window.shToast('Selecao invalida.');
      return;
    }
    if (typeof window.sh3dLoadGLB === 'function') window.sh3dLoadGLB(urls[pick - 1]);
  };

  window.meshyOpenModal = function () {
    const m = $('meshyModal');
    if (!m) return;
    clearSubmitStatus();
    show(m);
    // default focus on the text prompt
    setTimeout(function () { const p = $('meshyTextPrompt'); if (p) p.focus(); }, 50);
  };

  window.meshyCloseModal = function () {
    clearSubmitStatus();
    hide($('meshyModal'));
  };

  window.meshySwitchTab = function (tab) {
    clearSubmitStatus();
    document.querySelectorAll('.meshy-tab-btn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-meshy-tab') === tab);
    });
    document.querySelectorAll('.meshy-tab-panel').forEach(function (p) {
      p.style.display = (p.getAttribute('data-meshy-panel') === tab) ? 'block' : 'none';
    });
  };

  function _validateMeshyPrompt(raw) {
    const text = String(raw || '').trim();
    if (!text) return { ok: false, reason: 'Informe um prompt.' };
    if (text.length > 600) return { ok: false, reason: 'Prompt excede 600 caracteres (' + text.length + ').' };
    return { ok: true, value: text };
  }

  function _validateImageUrls(list) {
    const urls = (Array.isArray(list) ? list : []).map(function (s) { return String(s || '').trim(); }).filter(Boolean);
    if (!urls.length) return { ok: false, reason: 'Informe ao menos 1 URL de imagem.' };
    const bad = urls.filter(function (u) { return !/^https?:\/\//i.test(u); });
    if (bad.length) return { ok: false, reason: 'URL invalida (precisa http/https): ' + bad[0] };
    if (urls.length > 4) return { ok: false, reason: 'Meshy aceita no maximo 4 imagens multi-view (recebidas ' + urls.length + ').' };
    return { ok: true, value: urls };
  }

  function draftTextPrompt() {
    const v = _validateMeshyPrompt(($('meshyTextPrompt') || {}).value);
    if (!v.ok) { setSubmitStatus(v.reason, true); return null; }
    const lowpoly = ($('meshyTextLowpoly') || {}).checked;
    const pbr     = ($('meshyTextPBR') || {}).checked;
    const rig     = ($('meshyTextRig') || {}).checked;

    const previewArgs = {
      mode: 'preview',
      prompt: v.value,
      art_style: 'realistic',
      topology: lowpoly ? 'triangle' : 'quad',
      target_polycount: lowpoly ? 8000 : 30000
    };
    if (rig) previewArgs.ai_model = 'meshy-4';

    const steps = [];
    steps.push('Call create_text_to_3d_task with ' + JSON.stringify(previewArgs) + '.');
    steps.push('Poll retrieve_text_to_3d_task with that id every 5s until status="SUCCEEDED" (or use stream_text_to_3d_task).');
    if (pbr) {
      steps.push(
        'Then call create_text_to_3d_task with {mode: "refine", preview_task_id: <that id>, enable_pbr: true} ' +
        'and poll retrieve_text_to_3d_task until SUCCEEDED.'
      );
    }
    if (rig) {
      steps.push('Finally call create_rigging_task with the SUCCEEDED textured task id and poll retrieve_rigging_task until SUCCEEDED.');
    }
    steps.push('When SUCCEEDED, report model_urls.glb (or result.rigged_character_glb_url for rigging) so the user can import it with sh3dLoadGLB.');
    return 'Generate a 3D model via Meshy (official MCP server):\n\n- ' + steps.join('\n- ');
  }

  function draftImagePrompt() {
    const raw = ($('meshyImageURLs') || {}).value || '';
    const urls = raw.split(/\r?\n/);
    const v = _validateImageUrls(urls);
    if (!v.ok) { setSubmitStatus(v.reason, true); return null; }
    const tex = (($('meshyImageTexPrompt') || {}).value || '').trim();
    const pbr = ($('meshyImagePBR') || {}).checked;
    const remesh = ($('meshyImageRemesh') || {}).checked;

    const payload = {
      enable_pbr: !!pbr,
      should_remesh: !!remesh,
      topology: remesh ? 'quad' : 'triangle'
    };
    if (tex) payload.texture_prompt = tex;

    let call, retrieve;
    if (v.value.length === 1) {
      payload.image_url = v.value[0];
      call = 'create_image_to_3d_task';
      retrieve = 'retrieve_image_to_3d_task';
    } else {
      payload.image_urls = v.value;
      call = 'create_multi_image_to_3d_task';
      retrieve = 'retrieve_multi_image_to_3d_task';
    }

    return (
      'Reconstruct a 3D model from image(s) via Meshy (official MCP server):\n\n' +
      '- Call ' + call + ' with ' + JSON.stringify(payload) + '.\n' +
      '- Poll ' + retrieve + ' with that id every 10s until status="SUCCEEDED" (or use the stream_* variant).\n' +
      '- When SUCCEEDED, report model_urls.glb so the user can import it into the scene.'
    );
  }

  function draftImportPrompt() {
    const id = (($('meshyImportID') || {}).value || '').trim();
    const resource = ($('meshyImportResource') || {}).value || 'text-to-3d';
    if (!id) { setSubmitStatus('Informe o Task ID.', true); return null; }
    if (!/^[0-9a-f-]{8,}$/i.test(id)) { setSubmitStatus('Task ID parece invalido (esperado UUID).', true); return null; }
    const retrieveMap = {
      'text-to-3d': 'retrieve_text_to_3d_task',
      'image-to-3d': 'retrieve_image_to_3d_task',
      'multi-image-to-3d': 'retrieve_multi_image_to_3d_task',
      'remesh': 'retrieve_remesh_task',
      'rigging': 'retrieve_rigging_task'
    };
    const retrieve = retrieveMap[resource] || 'retrieve_text_to_3d_task';
    return (
      'Import a Meshy task into the Shaders 3D scene:\n\n' +
      '- Call ' + retrieve + ' with {task_id: "' + id + '"}.\n' +
      '- If status is "PENDING" or "IN_PROGRESS", keep polling every 10s.\n' +
      '- Once SUCCEEDED, return the GLB URL from model_urls.glb (or result.rigged_character_glb_url for rigging).\n' +
      '- Tell me that URL so I can click "Import into scene".'
    );
  }

  function routeToShadersBrain(text) {
    if (!text) return false;
    if (typeof window.openSidebarToTab === 'function') {
      try { window.openSidebarToTab('shaders'); } catch (_) { /* ignore */ }
    }
    if (typeof window.shSwitchTab === 'function') {
      try { window.shSwitchTab('brainstorm'); } catch (_) { /* ignore */ }
    }

    const input = $('shBrainInput');
    if (!input || typeof window.shBrainSend !== 'function') return false;
    input.value = text;
    try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) { /* ignore */ }
    window.shBrainSend();
    return true;
  }

  window.meshySubmit = function () {
    const activeTab = (document.querySelector('.meshy-tab-btn.active') || {}).getAttribute
      ? document.querySelector('.meshy-tab-btn.active').getAttribute('data-meshy-tab')
      : 'text';
    let text = null;
    if (activeTab === 'text')   text = draftTextPrompt();
    if (activeTab === 'image')  text = draftImagePrompt();
    if (activeTab === 'import') text = draftImportPrompt();

    if (!text) {
      setSubmitStatus('Preencha os campos obrigatorios antes de delegar.', true);
      if (typeof window.shToast === 'function') window.shToast('Preencha os campos obrigatórios.');
      else alert('Preencha os campos obrigatórios.');
      return;
    }

    setSubmitStatus('Enviando para a agente de shaders...', false);
    if (routeToShadersBrain(text)) {
      setSubmitStatus('Delegado com sucesso. Acompanhe no Brainstorm de Shaders.', false);
      setTimeout(function () { window.meshyCloseModal(); }, 900);
      return;
    }

    setSubmitStatus('Agente de shaders ainda nao inicializou. Abra a aba Shaders e tente novamente.', true);
    if (typeof window.shToast === 'function') {
      window.shToast('Agente de shaders ainda nao inicializou. Abra a aba Shaders e tente novamente.');
    } else {
      alert('Agente de shaders ainda nao inicializou. Abra a aba Shaders e tente novamente.');
    }
  };

  /* Surface Meshy tool-call events from the chat stream as a tiny
     HUD chip (best-effort — integrates if stream.js dispatches custom events). */
  window.addEventListener('kout:tool-call', function (ev) {
    try {
      const d = ev.detail || {};
      // Accept both legacy meshy__<name> and official mcp__meshy__<name> / bare meshy task names.
      const rawName = String(d.name || '');
      if (!/meshy/i.test(rawName) && !/(text_to_3d|image_to_3d|remesh|rigging|retexture)_task/i.test(rawName)) return;
      const hud = $('sh3dHud');
      if (!hud) return;
      let chip = $('meshyHudChip');
      if (!chip) {
        chip = document.createElement('div');
        chip.id = 'meshyHudChip';
        chip.className = 'sh-preview-badge';
        chip.style.borderColor = '#E879F9';
        chip.style.color = '#E879F9';
        hud.appendChild(chip);
      }
      const shortName = rawName.replace(/^mcp__meshy__/i, '').replace(/^meshy__/i, '');
      chip.innerHTML = '<i class="fas fa-cube"></i> ' + shortName + (d.progress != null ? (' ' + d.progress + '%') : '…');
      const candidates = _dedupeUrls((Array.isArray(d.glb_urls) ? d.glb_urls : []).concat(d.glb_url ? [d.glb_url] : []));
      if (d.status === 'SUCCEEDED' && candidates.length === 1 && typeof window.sh3dLoadGLB === 'function') {
        chip.innerHTML += ' <a href="#" onclick="event.preventDefault();sh3dLoadGLB(\'' + candidates[0].replace(/'/g, "%27") + '\')" style="color:#4ECDC4;margin-left:6px">➕ Importar</a>';
      } else if (d.status === 'SUCCEEDED' && candidates.length > 1) {
        _meshyCandidateGlbs = candidates;
        chip.innerHTML += ' <a href="#" onclick="event.preventDefault();meshyChooseImportFromCandidates()" style="color:#4ECDC4;margin-left:6px">➕ Escolher (' + candidates.length + ')</a>';
      }
    } catch (_) { /* ignore */ }
  });

  /* ═══════════════════════════════════════════════════════════════════
     MESHY STUDIO — in-preview side panel (texture / remesh / rig / animate / chat)
     Reuses the same delegation pattern (draft → shaders brainstorm agent
     → official meshy-ai MCP tools) but operates on the currently loaded GLB.
     ═══════════════════════════════════════════════════════════════════ */

  function _studioEl(id) { return document.getElementById(id); }

  const _STUDIO_ANIM_CATALOG_URLS = [
    '/kout-workspace/data/meshy-animation-catalog.json',
    'data/meshy-animation-catalog.json'
  ];

  let _STUDIO_ANIM_PRESETS = [
    { id: 'Walking', label: 'Andando', label_en: 'Walking', label_pt: 'Andando', gif: 'https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Walking.gif', aliases: ['Walk'] },
    { id: 'Running', label: 'Correndo', label_en: 'Running', label_pt: 'Correndo', gif: 'https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Running.gif', aliases: ['Run'] },
    { id: 'Idle', label: 'Parado', label_en: 'Idle', label_pt: 'Parado', gif: 'https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Idle.gif' },
    { id: 'Jump', label: 'Salto Regular', label_en: 'Jump', label_pt: 'Salto Regular', gif: 'https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Regular_Jump.gif' }
  ];

  let _studioAnimReady = false;
  let _studioAnimCatalogPromise = null;

  function _studioEsc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _studioUniq(values) {
    const out = [];
    const seen = new Set();
    values.forEach(function (raw) {
      const value = String(raw || '').trim();
      if (!value) return;
      const key = value.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(value);
    });
    return out;
  }

  function _studioNormalizeCatalogEntry(entry) {
    if (!entry || typeof entry !== 'object') return null;
    const id = String(entry.id || entry.token || entry.animation_preset || '').trim();
    if (!id) return null;
    const label = String(entry.label_pt || entry.label || entry.label_en || id).trim() || id;
    const labelEn = String(entry.label_en || entry.label || id).trim() || id;
    const labelPt = String(entry.label_pt || entry.label || '').trim();
    const gif = String(entry.preview_gif || entry.gif || entry.preview || '').trim();
    const aliases = _studioUniq([id, label, labelEn, labelPt].concat(Array.isArray(entry.aliases) ? entry.aliases : []));
    return {
      id: id,
      label: label,
      label_en: labelEn,
      label_pt: labelPt,
      gif: gif,
      aliases: aliases
    };
  }

  async function _studioLoadAnimCatalogFromLocal() {
    if (_studioAnimCatalogPromise) return _studioAnimCatalogPromise;
    _studioAnimCatalogPromise = (async function () {
      for (let i = 0; i < _STUDIO_ANIM_CATALOG_URLS.length; i += 1) {
        const url = _STUDIO_ANIM_CATALOG_URLS[i];
        try {
          const response = await fetch(url, { cache: 'no-store' });
          if (!response.ok) continue;
          const payload = await response.json();
          const rawItems = Array.isArray(payload) ? payload : (Array.isArray(payload.items) ? payload.items : []);
          const normalized = rawItems.map(_studioNormalizeCatalogEntry).filter(Boolean);
          if (!normalized.length) continue;
          _STUDIO_ANIM_PRESETS = normalized;
          return true;
        } catch (_) {
          continue;
        }
      }
      return false;
    })();
    return _studioAnimCatalogPromise;
  }

  function _studioApplyAnimSelectionDefaults() {
    const presetEl = _studioEl('meshyStudioAnimPreset');
    const labelEl = _studioEl('meshyStudioAnimPresetLabel');
    const selectedEl = _studioEl('meshyStudioAnimSelected');
    if (!presetEl) return;

    const fallbackPreset = (_STUDIO_ANIM_PRESETS[0] && _STUDIO_ANIM_PRESETS[0].id) || 'Walking';
    if (!presetEl.value) presetEl.value = fallbackPreset;
    const found = _STUDIO_ANIM_PRESETS.find(function (p) { return p.id === presetEl.value; });
    if (!found) presetEl.value = fallbackPreset;
    const selected = _STUDIO_ANIM_PRESETS.find(function (p) { return p.id === presetEl.value; }) || { id: presetEl.value, label: presetEl.value };
    if (labelEl) labelEl.value = selected.label || selected.id;
    if (selectedEl) selectedEl.textContent = selected.label || selected.id;
  }

  function _studioRenderAnimCatalog() {
    const grid = _studioEl('meshyStudioAnimGrid');
    const searchEl = _studioEl('meshyStudioAnimSearch');
    const presetEl = _studioEl('meshyStudioAnimPreset');
    if (!grid || !presetEl) return;
    const query = String((searchEl && searchEl.value) || '').trim().toLowerCase();
    const selected = String(presetEl.value || ((_STUDIO_ANIM_PRESETS[0] && _STUDIO_ANIM_PRESETS[0].id) || 'Walking'));
    const items = _STUDIO_ANIM_PRESETS.filter(function (p) {
      if (!query) return true;
      const haystack = [p.label, p.label_en, p.label_pt, p.id].concat(Array.isArray(p.aliases) ? p.aliases : []).join(' ').toLowerCase();
      return haystack.indexOf(query) >= 0;
    });
    if (!items.length) {
      grid.innerHTML = '<div class="meshy-studio-hint" style="grid-column:1/-1">Nenhum preset encontrado. Use o campo de prompt customizado abaixo.</div>';
      return;
    }
    grid.innerHTML = items.map(function (p) {
      const active = p.id === selected ? ' active' : '';
      const preview = p.gif
        ? ('<img loading="lazy" src="' + _studioEsc(p.gif) + '" alt="' + _studioEsc(p.label) + '">')
        : '<div class="meshy-studio-anim-noimg">NO PREVIEW</div>';
      return '<button type="button" class="meshy-studio-anim-card' + active + '" title="' + _studioEsc(p.label) + '" onclick="meshyStudioPickAnimation(\'' + _studioEsc(p.id) + '\')">'
        + preview
        + '<span>' + _studioEsc(p.label) + '</span>'
        + '</button>';
    }).join('');
  }

  function _studioEnsureAnimCatalog() {
    const searchEl = _studioEl('meshyStudioAnimSearch');
    const presetEl = _studioEl('meshyStudioAnimPreset');
    if (!presetEl) return;

    if (!_studioAnimReady && searchEl) {
      searchEl.addEventListener('input', _studioRenderAnimCatalog);
    }

    _studioAnimReady = true;
    _studioApplyAnimSelectionDefaults();
    _studioRenderAnimCatalog();

    _studioLoadAnimCatalogFromLocal().then(function () {
      _studioApplyAnimSelectionDefaults();
      _studioRenderAnimCatalog();
    }).catch(function () {
      // Keep curated fallback if local catalog load fails.
    });
  }

  window.meshyStudioPickAnimation = function (id, label) {
    const presetEl = _studioEl('meshyStudioAnimPreset');
    const labelEl = _studioEl('meshyStudioAnimPresetLabel');
    const selectedEl = _studioEl('meshyStudioAnimSelected');
    const found = _STUDIO_ANIM_PRESETS.find(function (p) { return p.id === id; });
    const safeLabel = label || (found && found.label) || id || 'Walking';
    if (presetEl) presetEl.value = String(id || 'Walking');
    if (labelEl) labelEl.value = String(safeLabel);
    if (selectedEl) selectedEl.textContent = String(safeLabel);
    _studioRenderAnimCatalog();
  };

  function _studioStatus(msg, kind) {
    const el = _studioEl('meshyStudioStatus');
    if (!el) return;
    el.textContent = String(msg || '');
    el.className = 'meshy-studio-status' + (kind ? ' ' + kind : '');
  }

  function _studioCurrentModelUrl() {
    // scene3d stores the resolved URL (may be proxied). Prefer the original
    // signed URL if we tracked it; otherwise fall back to sh3dExportConfig().model.
    if (window._meshyLastResolvedUrl) return window._meshyLastResolvedUrl;
    try {
      if (typeof window.sh3dExportConfig === 'function') {
        var raw = window.sh3dExportConfig();
        var cfg = (typeof raw === 'string') ? JSON.parse(raw) : raw;
        if (cfg && cfg.model) return cfg.model;
      }
    } catch (_) { /* ignore */ }
    return '';
  }

  function _studioUpdateModelLabel() {
    const lbl = _studioEl('meshyStudioModelLabel');
    if (!lbl) return;
    const url = _studioCurrentModelUrl();
    if (!url) { lbl.textContent = '—'; lbl.title = 'Nenhum modelo carregado'; return; }
    lbl.textContent = _tail(url);
    lbl.title = url;
  }

  window.meshyStudioToggle = function (force) {
    const panel = _studioEl('meshyStudio');
    if (!panel) return;
    const visible = (force === undefined) ? panel.hasAttribute('hidden') : !!force;
    if (visible) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
    const btn = document.getElementById('sh3dBtnStudio');
    if (btn) btn.classList.toggle('active', visible);
    if (visible) { _studioUpdateModelLabel(); _studioStatus(''); _studioEnsureAnimCatalog(); }
  };

  window.meshyStudioSwitchTab = function (tab) {
    document.querySelectorAll('.meshy-studio-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-studio-tab') === tab);
    });
    document.querySelectorAll('.meshy-studio-pane').forEach(function (p) {
      const match = p.getAttribute('data-studio-pane') === tab;
      if (match) p.removeAttribute('hidden'); else p.setAttribute('hidden', '');
    });
    if (tab === 'animate') _studioEnsureAnimCatalog();
  };

  function _studioRequireModel() {
    const url = _studioCurrentModelUrl();
    if (!url) {
      _studioStatus('Carregue um modelo 3D primeiro (Meshy → Texto/Imagem ou Importar task).', 'err');
      return null;
    }
    return url;
  }

  function _studioDelegate(instruction) {
    if (!instruction) return;
    _studioStatus('Enviando para a agente de shaders…', '');
    const input = _studioEl('shBrainInput');
    if (!input || typeof window.shBrainSend !== 'function') {
      _studioStatus('Agente de shaders não inicializou. Abra a aba Shaders e tente novamente.', 'err');
      return;
    }
    if (typeof window.openSidebarToTab === 'function') {
      try { window.openSidebarToTab('shaders'); } catch (_) { /* ignore */ }
    }
    if (typeof window.shSwitchTab === 'function') {
      try { window.shSwitchTab('brainstorm'); } catch (_) { /* ignore */ }
    }
    input.value = instruction;
    try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) { /* ignore */ }
    window.shBrainSend();
    _studioStatus('Delegado — acompanhe o progresso no Brainstorm de Shaders.', 'ok');
  }

  window.meshyStudioRunTexture = function () {
    const modelUrl = _studioRequireModel();
    if (!modelUrl) return;
    const prompt = ((_studioEl('meshyStudioTexPrompt') || {}).value || '').trim();
    if (!prompt) { _studioStatus('Descreva a textura desejada.', 'err'); return; }
    if (prompt.length > 600) { _studioStatus('Prompt excede 600 caracteres.', 'err'); return; }
    const style = (_studioEl('meshyStudioTexStyle') || {}).value || 'realistic';
    const pbr = (_studioEl('meshyStudioTexPBR') || {}).checked;
    const payload = { model_url: modelUrl, object_prompt: _tail(modelUrl), style_prompt: prompt, art_style: style, enable_pbr: !!pbr };
    const steps = [
      'Call create_retexture_task with ' + JSON.stringify(payload) + '.',
      'Poll retrieve_retexture_task until status="SUCCEEDED".',
      'Report the new GLB URL from model_urls.glb so I can click Importar no chip do HUD.'
    ];
    _studioDelegate('Retexturize the currently loaded Meshy model:\n\n- ' + steps.join('\n- '));
  };

  window.meshyStudioRunRemesh = function () {
    const modelUrl = _studioRequireModel();
    if (!modelUrl) return;
    const topology = (_studioEl('meshyStudioRemeshTopo') || {}).value || 'quad';
    const poly = parseInt((_studioEl('meshyStudioRemeshPoly') || {}).value || '30000', 10);
    if (!Number.isFinite(poly) || poly < 1000) { _studioStatus('Target polycount inválido.', 'err'); return; }
    const pbr = (_studioEl('meshyStudioRemeshPBR') || {}).checked;
    const payload = { input_task_url: modelUrl, topology: topology, target_polycount: poly, preserve_texture: !!pbr };
    const steps = [
      'Call create_remesh_task with ' + JSON.stringify(payload) + '.',
      'Poll retrieve_remesh_task until status="SUCCEEDED".',
      'Report the new GLB URL from model_urls.glb.'
    ];
    _studioDelegate('Remesh the currently loaded Meshy model:\n\n- ' + steps.join('\n- '));
  };

  window.meshyStudioRunRig = function () {
    const modelUrl = _studioRequireModel();
    if (!modelUrl) return;
    const skeleton = (_studioEl('meshyStudioRigType') || {}).value || 'humanoid';
    const height = parseFloat((_studioEl('meshyStudioRigHeight') || {}).value || '1.8');
    const payload = { input_task_url: modelUrl, skeleton_type: skeleton, height_meters: Number.isFinite(height) ? height : 1.8 };
    const steps = [
      'Call create_rigging_task with ' + JSON.stringify(payload) + '.',
      'Poll retrieve_rigging_task until status="SUCCEEDED".',
      'Report result.rigged_character_glb_url so I can import it.'
    ];
    _studioDelegate('Rig the currently loaded Meshy model:\n\n- ' + steps.join('\n- '));
  };

  window.meshyStudioRunAnimate = function () {
    const modelUrl = _studioRequireModel();
    if (!modelUrl) return;
    _studioEnsureAnimCatalog();
    const preset = ((_studioEl('meshyStudioAnimPreset') || {}).value || 'Walking').trim();
    const presetLabel = ((_studioEl('meshyStudioAnimPresetLabel') || {}).value || preset).trim();
    const customAnim = ((_studioEl('meshyStudioAnimCustom') || {}).value || '').trim();
    const animToken = customAnim || preset;
    if (!animToken) { _studioStatus('Escolha um preset ou digite um prompt de animação.', 'err'); return; }
    const duration = parseFloat((_studioEl('meshyStudioAnimDuration') || {}).value || '3');
    const loop = (_studioEl('meshyStudioAnimLoop') || {}).checked;
    const payload = { input_task_url: modelUrl, animation_preset: animToken, duration_seconds: Number.isFinite(duration) ? duration : 3, loop: !!loop };
    const steps = [
      'Precondition: the model must already be rigged. If not, instruct me to run the Rig tab first.',
      (customAnim
        ? ('Use this animation request text: "' + customAnim.replace(/"/g, '\\"') + '".')
        : ('Preferred native preset: "' + presetLabel + '" (token: "' + preset + '").')),
      'If this exact token is unsupported by the API, choose the closest native Meshy equivalent and proceed.',
      'Call create_animation_task with ' + JSON.stringify(payload) + '.',
      'Poll retrieve_animation_task until status="SUCCEEDED".',
      'Report the animated GLB URL (includes skeleton + clip) so I can import it.'
    ];
    _studioDelegate('Animate the currently loaded Meshy model:\n\n- ' + steps.join('\n- '));
  };

  window.meshyStudioChatQuick = function (mode) {
    const area = _studioEl('meshyStudioChatInput');
    if (!area) return;
    const presets = {
      improve:    'Sugira 3 melhorias concretas para este modelo (qualidade da textura, silhueta, iluminação da cena) e execute a que tiver maior impacto com o menor custo de tokens.',
      fix:        'Analise possíveis problemas visíveis (artefatos de textura, topologia, rigging) no modelo atual e proponha correções via ferramentas Meshy — executando a primeira.',
      variations: 'Gere 3 variações do modelo atual mantendo a topologia, mas alterando a textura/estilo (realista, cartoon, escultura). Apresente URLs ao final.'
    };
    area.value = presets[mode] || '';
    area.focus();
  };

  window.meshyStudioChatSend = function () {
    const modelUrl = _studioRequireModel();
    if (!modelUrl) return;
    const text = ((_studioEl('meshyStudioChatInput') || {}).value || '').trim();
    if (!text) { _studioStatus('Digite uma mensagem.', 'err'); return; }
    const ctx = 'Context: the user has loaded the Meshy model at ' + modelUrl + ' in the Shaders 3D preview.\n' +
                'Use the official meshy-ai MCP tools (create_*_task / retrieve_*_task) whenever the user asks for changes.\n' +
                'When a task SUCCEEDS, report the final GLB URL.\n\n' +
                'User request:\n' + text;
    _studioDelegate(ctx);
    (_studioEl('meshyStudioChatInput') || {}).value = '';
  };

  // Keep the model label fresh after every successful GLB load.
  window.addEventListener('kout:tool-call', function (ev) {
    try {
      const d = ev.detail || {};
      if (d.status !== 'SUCCEEDED') return;
      const url = d.glb_url || (Array.isArray(d.glb_urls) && d.glb_urls[0]) || '';
      if (url) window._meshyLastResolvedUrl = url;
      _studioUpdateModelLabel();
    } catch (_) { /* ignore */ }
  });

  // Also refresh when scene3d loads any GLB (scene switch, user upload, etc.).
  window.addEventListener('kout:model-loaded', function () {
    try { _studioUpdateModelLabel(); } catch (_) { /* ignore */ }
  });

})();
