/**
 * Garage OpenClaude Backstage
 * Bridges the Garage UI with OpenClaude's markdown-based agent system.
 *
 * Agents are defined as .md files in .claude/agents/ with YAML frontmatter.
 * This module provides full CRUD, execution, and import/export capabilities.
 */

// ── Module guard ───────────────────────────────────────────────────────────
if (typeof window._openclaudeEventsBound !== 'undefined' && window._openclaudeEventsBound) {
    // Already bound; skip duplicate registration
} else {
    window._openclaudeEventsBound = true;

    document.addEventListener('DOMContentLoaded', () => {
        setupOpenClaudeSection();
    });
}

// ── State ──────────────────────────────────────────────────────────────────
let openclaudeAgents = [];
let openclaudeRunActive = false;
let openclaudeAbortController = null;

// ── Setup ──────────────────────────────────────────────────────────────────
function setupOpenClaudeSection() {
    // Create Agent button
    const createBtn = document.getElementById('oc-create-agent-btn');
    if (createBtn) {
        createBtn.addEventListener('click', showCreateAgentModal);
    }

    // Refresh button
    const refreshBtn = document.getElementById('oc-refresh-agents-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadOpenClaudeAgents());
    }

    // Run Agent button
    const runBtn = document.getElementById('oc-run-agent-btn');
    if (runBtn) {
        runBtn.addEventListener('click', runSelectedAgent);
    }

    // Stop button
    const stopBtn = document.getElementById('oc-stop-agent-btn');
    if (stopBtn) {
        stopBtn.addEventListener('click', stopAgentRun);
    }

    // Agent select change
    const agentSelect = document.getElementById('oc-agent-select');
    if (agentSelect) {
        agentSelect.addEventListener('change', onAgentSelectChange);
    }

    // Import from assistant button
    const importBtn = document.getElementById('oc-import-assistant-btn');
    if (importBtn) {
        importBtn.addEventListener('click', showImportAssistantModal);
    }

    // Import agent (markdown / catalog) button
    const importAgentBtn = document.getElementById('oc-import-agent-btn');
    if (importAgentBtn) {
        importAgentBtn.addEventListener('click', showImportAgentModal);
    }
}

// ── Load Agents ────────────────────────────────────────────────────────────
async function loadOpenClaudeAgents() {
    const grid = document.getElementById('oc-agents-grid');
    const select = document.getElementById('oc-agent-select');
    if (!grid && !select) return;

    try {
        const resp = await fetch('/v1/openclaude/agents');
        const data = await resp.json();
        openclaudeAgents = data.agents || [];

        if (grid) renderAgentGrid(grid);
        if (select) populateAgentSelect(select);

        const count = document.getElementById('oc-agent-count');
        if (count) count.textContent = `${openclaudeAgents.length} agent${openclaudeAgents.length !== 1 ? 's' : ''}`;
    } catch (err) {
        if (grid) {
            grid.innerHTML = `<div class="placeholder-text"><i class="fas fa-exclamation-triangle"></i> Failed to load agents: ${err.message}</div>`;
        }
    }
}

function renderAgentGrid(grid) {
    if (openclaudeAgents.length === 0) {
        grid.innerHTML = `
            <div style="text-align:center;padding:40px;color:var(--gray);grid-column:1/-1">
                <div style="font-size:48px;margin-bottom:16px;color:var(--border-hi)">📋</div>
                <h3>No Agents Found</h3>
                <p>Create your first agent using the markdown standard.</p>
                <button class="btn btn-primary" onclick="showCreateAgentModal()" style="margin-top:12px">
                    <i class="fas fa-plus"></i> Create First Agent
                </button>
            </div>`;
        return;
    }

    grid.innerHTML = openclaudeAgents.map(agent => {
        const toolsStr = Array.isArray(agent.tools)
            ? agent.tools.join(', ')
            : (typeof agent.tools === 'string' ? agent.tools : 'All');
        return `
        <div class="collection-item" onclick="viewAgentDetail('${escapeHtml(agent.name)}')" style="cursor:pointer">
            <h4 style="display:flex;align-items:center;gap:8px">
                <i class="fas fa-file-code" style="color:var(--amber);font-size:12px"></i>
                ${escapeHtml(agent.name)}
            </h4>
            <p style="font-size:12px;color:var(--gray);margin:4px 0">${escapeHtml(agent.description || 'No description')}</p>
            <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
                ${agent.model ? `<span class="badge">${escapeHtml(agent.model)}</span>` : ''}
                <span class="badge">${escapeHtml(toolsStr)}</span>
            </div>
            <div style="display:flex;gap:6px;margin-top:8px">
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();showEditAgentModal('${escapeHtml(agent.name)}')">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();importAgentToAssistant('${escapeHtml(agent.name)}')" title="Import as Assistant" style="color:var(--amber)">
                    <i class="fas fa-file-import"></i>
                </button>
                <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteOpenClaudeAgent('${escapeHtml(agent.name)}')">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>`;
    }).join('');
}

function populateAgentSelect(select) {
    const currentVal = select.value;
    select.innerHTML = '<option value="">Select an agent to run...</option>';
    openclaudeAgents.forEach(agent => {
        select.innerHTML += `<option value="${escapeHtml(agent.name)}">${escapeHtml(agent.name)}</option>`;
    });
    if (currentVal && openclaudeAgents.some(a => a.name === currentVal)) {
        select.value = currentVal;
    }
}

// ── Agent Detail / View ────────────────────────────────────────────────────
async function viewAgentDetail(name) {
    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(name)}`);
        const agent = await resp.json();

        const detailPanel = document.getElementById('oc-agent-detail');
        if (!detailPanel) return;

        const toolsStr = Array.isArray(agent.tools)
            ? agent.tools.join(', ')
            : (typeof agent.tools === 'string' ? agent.tools : 'All tools available');

        detailPanel.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h2><i class="fas fa-file-code"></i> ${escapeHtml(agent.name)}</h2>
                    <p>${escapeHtml(agent.description || '')}</p>
                </div>
                <div class="card-body">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
                        ${agent.model ? `<div><strong>Model:</strong> ${escapeHtml(agent.model)}</div>` : ''}
                        ${agent.permissionMode ? `<div><strong>Permission Mode:</strong> ${escapeHtml(agent.permissionMode)}</div>` : ''}
                        ${agent.maxTurns ? `<div><strong>Max Turns:</strong> ${agent.maxTurns}</div>` : ''}
                        ${agent.background ? `<div><strong>Background:</strong> Yes</div>` : ''}
                        ${agent.isolation ? `<div><strong>Isolation:</strong> ${escapeHtml(agent.isolation)}</div>` : ''}
                        ${agent.memory ? `<div><strong>Memory:</strong> ${escapeHtml(agent.memory)}</div>` : ''}
                    </div>
                    <div style="margin-bottom:10px"><strong>Tools:</strong> ${escapeHtml(toolsStr)}</div>
                    ${agent.skills ? `<div style="margin-bottom:10px"><strong>Skills:</strong> ${escapeHtml(Array.isArray(agent.skills) ? agent.skills.join(', ') : agent.skills)}</div>` : ''}
                    ${agent.paths ? `<div style="margin-bottom:10px"><strong>Paths:</strong> ${escapeHtml(Array.isArray(agent.paths) ? agent.paths.join(', ') : agent.paths)}</div>` : ''}
                    <h4>System Prompt</h4>
                    <pre style="max-height:300px">${escapeHtml(agent.body || '(empty)')}</pre>
                    <div class="action-bar" style="margin-top:12px">
                        <button class="btn btn-secondary" onclick="showEditAgentModal('${escapeHtml(agent.name)}')">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button class="btn btn-secondary" onclick="importAgentToAssistant('${escapeHtml(agent.name)}')" style="color:var(--amber)">
                            <i class="fas fa-file-import"></i> Import to Assistant
                        </button>
                        <button class="btn btn-download" onclick="downloadAgentMarkdown('${escapeHtml(agent.name)}')">
                            <i class="fas fa-download"></i> Download .md
                        </button>
                        <button class="btn btn-danger" onclick="deleteOpenClaudeAgent('${escapeHtml(agent.name)}')">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            </div>`;
        detailPanel.style.display = 'block';
    } catch (err) {
        showNotification(`Failed to load agent: ${err.message}`, 'error');
    }
}

// ── Create Agent Modal ─────────────────────────────────────────────────────
function showCreateAgentModal() {
    createModal('Create OpenClaude Agent', `
        <p style="color:var(--gray);margin-bottom:12px">Define an agent using the markdown standard. Frontmatter fields configure the agent; body content is the system prompt.</p>
        <div class="form-row">
            <div class="form-group">
                <label for="oc-modal-name">Agent Name *</label>
                <input type="text" id="oc-modal-name" name="agent_name" placeholder="my-agent" required>
                <small>Unique identifier (letters, numbers, hyphens, underscores)</small>
            </div>
            <div class="form-group">
                <label for="oc-modal-model">Model</label>
                <select id="oc-modal-model" name="model">
                    <option value="">inherit (use parent model)</option>
                    <option value="haiku">Haiku (fast)</option>
                    <option value="sonnet">Sonnet (balanced)</option>
                    <option value="opus">Opus (powerful)</option>
                </select>
            </div>
        </div>
        <div class="form-group">
            <label for="oc-modal-description">Description *</label>
            <input type="text" id="oc-modal-description" name="description" placeholder="When to use this agent (shown to the model)">
        </div>
        <div class="form-row">
            <div class="form-group">
                <label for="oc-modal-tools">Tools</label>
                <input type="text" id="oc-modal-tools" name="tools" placeholder="Read, Grep, Glob, Bash (comma-separated)">
                <small>Leave empty = all tools; use "*" for all; "[]" for none</small>
            </div>
            <div class="form-group">
                <label for="oc-modal-permission">Permission Mode</label>
                <select id="oc-modal-permission" name="permission_mode">
                    <option value="">Default</option>
                    <option value="acceptEdits">Accept Edits</option>
                    <option value="dontAsk">Don't Ask</option>
                </select>
            </div>
        </div>
        <div class="form-group">
            <label for="oc-modal-body">System Prompt (markdown body)</label>
            <textarea id="oc-modal-body" name="system_prompt" style="min-height:150px;font-family:var(--mono);font-size:13px" placeholder="You are a specialized agent that..."></textarea>
        </div>
        <details style="margin-top:12px">
            <summary style="cursor:pointer;color:var(--gray-hi);font-size:13px">Advanced Options</summary>
            <div style="padding-top:12px" class="form-row">
                <div class="form-group">
                    <label for="oc-modal-max-turns">Max Turns</label>
                    <input type="number" id="oc-modal-max-turns" name="max_turns" placeholder="Unlimited" min="1">
                </div>
                <div class="form-group">
                    <label for="oc-modal-memory">Memory Scope</label>
                    <select id="oc-modal-memory" name="memory_scope">
                        <option value="">None</option>
                        <option value="user">User</option>
                        <option value="project">Project</option>
                        <option value="local">Local</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="oc-modal-isolation">Isolation</label>
                    <select id="oc-modal-isolation" name="isolation">
                        <option value="">None</option>
                        <option value="worktree">Worktree (git)</option>
                    </select>
                </div>
            </div>
        </details>
    `, [
        { text: 'Create Agent', class: 'btn-primary', onclick: createOpenClaudeAgent },
        { text: 'Cancel', class: 'btn-secondary', onclick: closeModal }
    ], '700px');
}

async function createOpenClaudeAgent() {
    const name = document.getElementById('oc-modal-name')?.value.trim();
    const description = document.getElementById('oc-modal-description')?.value.trim();
    const body = document.getElementById('oc-modal-body')?.value.trim() || '';

    if (!name) {
        showNotification('Agent name is required', 'error');
        return;
    }

    const toolsRaw = document.getElementById('oc-modal-tools')?.value.trim();
    let tools = null;
    if (toolsRaw) {
        tools = toolsRaw.split(',').map(t => t.trim()).filter(Boolean);
    }

    const payload = {
        name,
        description: description || `Agent: ${name}`,
        model: document.getElementById('oc-modal-model')?.value || undefined,
        tools: tools,
        permissionMode: document.getElementById('oc-modal-permission')?.value || undefined,
        maxTurns: parseInt(document.getElementById('oc-modal-max-turns')?.value) || undefined,
        memory: document.getElementById('oc-modal-memory')?.value || undefined,
        isolation: document.getElementById('oc-modal-isolation')?.value || undefined,
        body,
    };

    try {
        const resp = await fetch('/v1/openclaude/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const result = await resp.json();
        showNotification(`Agent "${result.name}" created`, 'success');
        closeModal();
        loadOpenClaudeAgents();
    } catch (err) {
        showNotification(`Failed to create agent: ${err.message}`, 'error');
    }
}

// ── Edit Agent Modal ───────────────────────────────────────────────────────
async function showEditAgentModal(name) {
    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(name)}`);
        const agent = await resp.json();

        const toolsStr = Array.isArray(agent.tools)
            ? agent.tools.join(', ')
            : (typeof agent.tools === 'string' ? agent.tools : '');

        createModal(`Edit Agent: ${escapeHtml(name)}`, `
            <div class="form-row">
                <div class="form-group">
                    <label for="oc-modal-name">Agent Name *</label>
                    <input type="text" id="oc-modal-name" name="agent_name" value="${escapeHtml(agent.name)}" required>
                </div>
                <div class="form-group">
                    <label for="oc-modal-model">Model</label>
                    <select id="oc-modal-model" name="model">
                        <option value="" ${!agent.model ? 'selected' : ''}>inherit (use parent model)</option>
                        <option value="haiku" ${agent.model === 'haiku' ? 'selected' : ''}>Haiku (fast)</option>
                        <option value="sonnet" ${agent.model === 'sonnet' ? 'selected' : ''}>Sonnet (balanced)</option>
                        <option value="opus" ${agent.model === 'opus' ? 'selected' : ''}>Opus (powerful)</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label for="oc-modal-description">Description *</label>
                <input type="text" id="oc-modal-description" name="description" value="${escapeHtml(agent.description || '')}">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="oc-modal-tools">Tools</label>
                    <input type="text" id="oc-modal-tools" name="tools" value="${escapeHtml(toolsStr)}" placeholder="Read, Grep, Glob (comma-separated)">
                </div>
                <div class="form-group">
                    <label for="oc-modal-permission">Permission Mode</label>
                    <select id="oc-modal-permission" name="permission_mode">
                        <option value="" ${!agent.permissionMode ? 'selected' : ''}>Default</option>
                        <option value="acceptEdits" ${agent.permissionMode === 'acceptEdits' ? 'selected' : ''}>Accept Edits</option>
                        <option value="dontAsk" ${agent.permissionMode === 'dontAsk' ? 'selected' : ''}>Don't Ask</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label for="oc-modal-body">System Prompt (markdown body)</label>
                <textarea id="oc-modal-body" name="system_prompt" style="min-height:150px;font-family:var(--mono);font-size:13px">${escapeHtml(agent.body || '')}</textarea>
            </div>
        `, [
            { text: 'Save Changes', class: 'btn-primary', onclick: () => updateOpenClaudeAgent(name) },
            { text: 'Cancel', class: 'btn-secondary', onclick: closeModal }
        ], '700px');
    } catch (err) {
        showNotification(`Failed to load agent: ${err.message}`, 'error');
    }
}

async function updateOpenClaudeAgent(originalName) {
    const name = document.getElementById('oc-modal-name')?.value.trim();
    const description = document.getElementById('oc-modal-description')?.value.trim();
    const body = document.getElementById('oc-modal-body')?.value.trim() || '';

    if (!name) {
        showNotification('Agent name is required', 'error');
        return;
    }

    const toolsRaw = document.getElementById('oc-modal-tools')?.value.trim();
    let tools = null;
    if (toolsRaw) {
        tools = toolsRaw.split(',').map(t => t.trim()).filter(Boolean);
    }

    const payload = {
        name,
        description: description || `Agent: ${name}`,
        model: document.getElementById('oc-modal-model')?.value || undefined,
        tools: tools,
        permissionMode: document.getElementById('oc-modal-permission')?.value || undefined,
        body,
    };

    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(originalName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        showNotification(`Agent "${name}" updated`, 'success');
        closeModal();
        loadOpenClaudeAgents();
        // Refresh detail if open
        viewAgentDetail(name);
    } catch (err) {
        showNotification(`Failed to update agent: ${err.message}`, 'error');
    }
}

// ── Delete Agent ───────────────────────────────────────────────────────────
async function deleteOpenClaudeAgent(name) {
    if (!confirm(`Delete agent "${name}"? This action cannot be undone.`)) return;

    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(name)}`, {
            method: 'DELETE',
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        showNotification(`Agent "${name}" deleted`, 'success');
        document.getElementById('oc-agent-detail').style.display = 'none';
        loadOpenClaudeAgents();
    } catch (err) {
        showNotification(`Failed to delete agent: ${err.message}`, 'error');
    }
}

// ── Run Agent ──────────────────────────────────────────────────────────────
function onAgentSelectChange() {
    const select = document.getElementById('oc-agent-select');
    const runBtn = document.getElementById('oc-run-agent-btn');
    if (runBtn) runBtn.disabled = !select.value;
}

async function runSelectedAgent() {
    const select = document.getElementById('oc-agent-select');
    const promptInput = document.getElementById('oc-run-prompt');
    const output = document.getElementById('oc-run-output');

    if (!select || !select.value) {
        showNotification('Select an agent first', 'error');
        return;
    }
    const name = select.value;
    const prompt = promptInput?.value.trim();
    if (!prompt) {
        showNotification('Enter a prompt', 'error');
        return;
    }

    if (output) {
        output.textContent = `Running agent "${name}"...\n\n`;
        output.style.display = 'block';
    }

    openclaudeRunActive = true;
    const stopBtn = document.getElementById('oc-stop-agent-btn');
    if (stopBtn) stopBtn.style.display = 'inline-flex';

    openclaudeAbortController = new AbortController();

    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(name)}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt }),
            signal: openclaudeAbortController.signal,
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();

        while (openclaudeRunActive) {
            const { done, value } = await reader.read();
            if (done) break;
            const text = decoder.decode(value, { stream: true });
            if (output) output.textContent += text;
            // Auto-scroll
            if (output) output.scrollTop = output.scrollHeight;
        }
    } catch (err) {
        if (err.name === 'AbortError') {
            if (output) output.textContent += '\n\n[Run stopped by user]';
        } else {
            if (output) output.textContent += `\n\n[Error: ${err.message}]`;
        }
    } finally {
        openclaudeRunActive = false;
        openclaudeAbortController = null;
        if (stopBtn) stopBtn.style.display = 'none';
    }
}

function stopAgentRun() {
    openclaudeRunActive = false;
    if (openclaudeAbortController) {
        openclaudeAbortController.abort();
    }
}

// ── Import Assistant Modal ─────────────────────────────────────────────────
async function showImportAssistantModal() {
    if (!availableAssistants || availableAssistants.length === 0) {
        if (typeof loadAssistants === 'function') {
            await loadAssistants();
        }
    }

    const options = (availableAssistants || []).map(a =>
        `<option value="${a.id}">${escapeHtml(a.name || a.id)}</option>`
    ).join('');

    createModal('Import Assistant to Agent', `
        <p style="color:var(--gray);margin-bottom:12px">Convert an existing Garage assistant (JSON) to an OpenClaude agent markdown file.</p>
        <div class="form-group">
            <label for="oc-import-assistant-select">Select Assistant</label>
            <select id="oc-import-assistant-select" name="assistant_select" style="width:100%">
                <option value="">Choose an assistant...</option>
                ${options}
            </select>
        </div>
    `, [
        { text: 'Import', class: 'btn-primary', onclick: importAssistantToAgent },
        { text: 'Cancel', class: 'btn-secondary', onclick: closeModal }
    ]);
}

async function importAssistantToAgent() {
    const select = document.getElementById('oc-import-assistant-select');
    if (!select || !select.value) {
        showNotification('Select an assistant to import', 'error');
        return;
    }
    const assistantId = select.value;

    try {
        const resp = await fetch(`/v1/openclaude/agents/import-from-assistant/${encodeURIComponent(assistantId)}`, {
            method: 'POST',
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const result = await resp.json();
        showNotification(`Assistant imported as agent "${result.name}"`, 'success');
        closeModal();
        loadOpenClaudeAgents();
    } catch (err) {
        showNotification(`Import failed: ${err.message}`, 'error');
    }
}

// ── Import Agent to Assistant (reverse bridge) ───────────────────────────
async function importAgentToAssistant(agentName) {
    if (!agentName) {
        showNotification('Agent name is required', 'error');
        return;
    }

    try {
        const resp = await fetch(`/v1/openclaude/agents/export-to-assistant/${encodeURIComponent(agentName)}`, {
            method: 'POST',
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const result = await resp.json();
        showNotification(`Agent imported as assistant "${result.assistant_name}"`, 'success');

        // Keep parity with assistant->agent export UX: jump to destination tab.
        const assistantsTab = document.querySelector('.main-tab-btn[data-section="assistants-section"]');
        if (assistantsTab) assistantsTab.click();
        if (typeof loadAssistants === 'function') {
            loadAssistants();
        }
    } catch (err) {
        showNotification(`Import to assistant failed: ${err.message}`, 'error');
    }
}

// ── Download Agent Markdown ────────────────────────────────────────────────
async function downloadAgentMarkdown(name) {
    try {
        const resp = await fetch(`/v1/openclaude/agents/${encodeURIComponent(name)}`);
        const agent = await resp.json();

        // Reconstruct the markdown
        const fm = {};
        const frontmatterFields = ['name', 'description', 'model', 'tools', 'disallowedTools',
            'permissionMode', 'maxTurns', 'skills', 'hooks', 'memory',
            'background', 'color', 'isolation', 'paths', 'effort', 'mcpServers', 'initialPrompt'];
        frontmatterFields.forEach(f => {
            if (agent[f] !== undefined && agent[f] !== null && agent[f] !== '' && agent[f] !== false) {
                fm[f] = agent[f];
            }
        });
        // Ensure name is first
        const ordered = { name: fm.name };
        Object.assign(ordered, fm);
        delete ordered.name;
        const finalFm = { name: fm.name, ...ordered };

        let md = '---\n';
        Object.entries(finalFm).forEach(([k, v]) => {
            if (v === undefined || v === null || v === '' || v === false) return;
            if (Array.isArray(v)) {
                md += `${k}:\n${v.map(item => `  - ${item}`).join('\n')}\n`;
            } else if (typeof v === 'object') {
                md += `${k}:\n`;
                Object.entries(v).forEach(([sk, sv]) => {
                    md += `  ${sk}: ${sv}\n`;
                });
            } else {
                md += `${k}: ${v}\n`;
            }
        });
        md += '---\n\n';
        md += agent.body || '';

        const blob = new Blob([md], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${name}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (err) {
        showNotification(`Download failed: ${err.message}`, 'error');
    }
}

// ── Export from Assistant (called from assistants tab) ─────────────────────
async function exportAssistantToOpenClaude(assistantId) {
    try {
        const resp = await fetch(`/v1/openclaude/agents/import-from-assistant/${encodeURIComponent(assistantId)}`, {
            method: 'POST',
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const result = await resp.json();
        showNotification(`Exported to OpenClaude agent: "${result.name}"`, 'success');
        // Switch to OpenClaude tab to show the result
        const ocTab = document.querySelector('.main-tab-btn[data-section="openclaude-section"]');
        if (ocTab) ocTab.click();
        loadOpenClaudeAgents();
    } catch (err) {
        showNotification(`Export failed: ${err.message}`, 'error');
    }
}

// ── Import Agent Modal (Markdown file upload + Remote catalog) ─────────────

let _ocCatalogGroups = [];

function showImportAgentModal() {
    createModal('Import Agent', `
        <div style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:16px">
            <button id="oc-import-tab-file" onclick="ocImportSwitchTab('file')" style="
                flex:1;padding:8px 16px;background:var(--amber);color:#fff;
                border:none;border-radius:var(--r) var(--r) 0 0;cursor:pointer;font-weight:600;font-size:13px">
                <i class="fas fa-file-upload"></i> Arquivo .md
            </button>
            <button id="oc-import-tab-catalog" onclick="ocImportSwitchTab('catalog')" style="
                flex:1;padding:8px 16px;background:var(--bg-secondary);color:var(--gray-hi);
                border:none;border-radius:var(--r) var(--r) 0 0;cursor:pointer;font-weight:600;font-size:13px">
                <i class="fas fa-database"></i> Catálogo Remoto
            </button>
        </div>

        <!-- ── Tab: File Upload ── -->
        <div id="oc-import-panel-file">
            <p style="color:var(--gray);margin-bottom:12px;font-size:13px">
                Upload a <code>.md</code> or <code>.agent.md</code> file. The YAML frontmatter
                must include a <code>name</code> field. Extra fields (e.g. <code>tags</code>,
                <code>agent_type</code>) are preserved as a body comment.
            </p>
            <div class="form-group">
                <label for="oc-import-file-input">Select File</label>
                <input type="file" id="oc-import-file-input" name="agent_markdown_file" accept=".md,.agent.md,.txt"
                       onchange="ocImportPreviewFile(this)" style="width:100%">
            </div>
            <div id="oc-import-file-preview" style="display:none;margin-top:10px">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                    <span id="oc-import-file-status" style="font-size:13px"></span>
                </div>
                <pre id="oc-import-file-content" style="
                    max-height:220px;overflow-y:auto;font-size:12px;
                    background:var(--bg-code);border:1px solid var(--border);
                    border-radius:var(--r);padding:10px;white-space:pre-wrap;word-break:break-word"></pre>
            </div>
            <div class="form-group" style="margin-top:10px">
                <label for="oc-import-overwrite" style="display:flex;align-items:center;gap:6px;cursor:pointer">
                    <input type="checkbox" id="oc-import-overwrite" name="overwrite_existing"> Overwrite if name already exists
                </label>
            </div>
        </div>

        <!-- ── Tab: Remote Catalog ── -->
        <div id="oc-import-panel-catalog" style="display:none">
            <p style="color:var(--gray);margin-bottom:12px;font-size:13px">
                Browse agents from the remote Garage instance at <code>localhost:8120</code>.
            </p>
            <div class="action-bar" style="margin-bottom:12px">
                <button class="btn btn-sm btn-secondary" onclick="ocImportLoadCatalog()">
                    <i class="fas fa-sync-alt"></i> Refresh Catalog
                </button>
                <span id="oc-catalog-source" style="font-size:12px;color:var(--gray)"></span>
            </div>
            <div id="oc-catalog-loading" style="display:none;color:var(--gray);font-size:13px">
                <i class="fas fa-spinner fa-spin"></i> Loading catalog…
            </div>
            <div id="oc-catalog-content" style="display:none">
                <div class="form-row">
                    <div class="form-group">
                        <label for="oc-catalog-group-select">Group</label>
                        <select id="oc-catalog-group-select" name="catalog_group" onchange="ocImportPopulateAgents()" style="width:100%">
                            <option value="">All groups…</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="oc-catalog-agent-select">Agent</label>
                        <select id="oc-catalog-agent-select" name="catalog_agent" onchange="ocImportShowAgentPreview()" style="width:100%">
                            <option value="">Select an agent…</option>
                        </select>
                    </div>
                </div>
                <div id="oc-catalog-agent-preview" style="
                    display:none;background:var(--bg-secondary);border:1px solid var(--border);
                    border-radius:var(--r);padding:12px;font-size:13px;margin-top:4px">
                </div>
            </div>
            <div id="oc-catalog-error" style="display:none;color:var(--error);font-size:13px;margin-top:8px"></div>
        </div>
    `, [
        { text: 'Import', class: 'btn-primary', onclick: ocImportExecute },
        { text: 'Cancel', class: 'btn-secondary', onclick: closeModal },
    ], '640px');
}

function ocImportSwitchTab(tab) {
    const isFile = tab === 'file';
    document.getElementById('oc-import-panel-file').style.display = isFile ? '' : 'none';
    document.getElementById('oc-import-panel-catalog').style.display = isFile ? 'none' : '';
    document.getElementById('oc-import-tab-file').style.background = isFile ? 'var(--amber)' : 'var(--bg-secondary)';
    document.getElementById('oc-import-tab-file').style.color = isFile ? '#fff' : 'var(--gray-hi)';
    document.getElementById('oc-import-tab-catalog').style.background = !isFile ? 'var(--amber)' : 'var(--bg-secondary)';
    document.getElementById('oc-import-tab-catalog').style.color = !isFile ? '#fff' : 'var(--gray-hi)';

    if (!isFile && _ocCatalogGroups.length === 0) {
        ocImportLoadCatalog();
    }
}

function ocImportPreviewFile(input) {
    const preview = document.getElementById('oc-import-file-preview');
    const status = document.getElementById('oc-import-file-status');
    const content = document.getElementById('oc-import-file-content');
    if (!input.files || !input.files[0]) { preview.style.display = 'none'; return; }

    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        const hasFrontmatter = /^---\s*\n/.test(text);
        const nameMatch = text.match(/^name:\s*(.+)$/m);

        let statusHtml = '';
        if (!hasFrontmatter) {
            statusHtml = `<i class="fas fa-exclamation-triangle" style="color:var(--error)"></i> <span style="color:var(--error)">No YAML frontmatter found (--- block required)</span>`;
        } else if (!nameMatch) {
            statusHtml = `<i class="fas fa-exclamation-triangle" style="color:orange"></i> <span style="color:orange">No 'name' field in frontmatter — will use filename</span>`;
        } else {
            statusHtml = `<i class="fas fa-check-circle" style="color:var(--success)"></i> <span style="color:var(--success)">Valid — agent: <strong>${escapeHtml(nameMatch[1].trim())}</strong></span>`;
        }
        status.innerHTML = statusHtml;
        content.textContent = text.length > 4000 ? text.slice(0, 4000) + '\n…(truncated)' : text;
        preview.style.display = '';
        input._parsedContent = text;
    };
    reader.readAsText(file);
}

async function ocImportLoadCatalog() {
    const loadingEl = document.getElementById('oc-catalog-loading');
    const contentEl = document.getElementById('oc-catalog-content');
    const errorEl = document.getElementById('oc-catalog-error');
    const sourceEl = document.getElementById('oc-catalog-source');
    if (!loadingEl) return;

    loadingEl.style.display = '';
    contentEl.style.display = 'none';
    errorEl.style.display = 'none';

    try {
        const resp = await fetch('/v1/openclaude/catalog/agents');
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        _ocCatalogGroups = data.groups || [];
        if (sourceEl) {
            sourceEl.textContent = `Fonte: ${data.source} — ${data.total_agents} agente(s) em ${_ocCatalogGroups.length} grupo(s)`;
        }

        const groupSel = document.getElementById('oc-catalog-group-select');
        if (groupSel) {
            groupSel.innerHTML = '<option value="">Todos os grupos…</option>';
            _ocCatalogGroups.forEach(g => {
                groupSel.innerHTML += `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)} (${g.count})</option>`;
            });
        }
        ocImportPopulateAgents();
        loadingEl.style.display = 'none';
        contentEl.style.display = '';
    } catch (err) {
        loadingEl.style.display = 'none';
        errorEl.style.display = '';
        errorEl.textContent = `Erro ao carregar catálogo: ${err.message}`;
    }
}

function ocImportPopulateAgents() {
    const groupSel = document.getElementById('oc-catalog-group-select');
    const agentSel = document.getElementById('oc-catalog-agent-select');
    const previewEl = document.getElementById('oc-catalog-agent-preview');
    if (!agentSel) return;

    const selectedGroup = groupSel?.value || '';
    let agents = [];
    if (!selectedGroup) {
        _ocCatalogGroups.forEach(g => agents.push(...g.agents));
    } else {
        const group = _ocCatalogGroups.find(g => g.id === selectedGroup);
        agents = group ? group.agents : [];
    }

    agentSel.innerHTML = '<option value="">Selecione um agente…</option>';
    agents.forEach(a => {
        const agentKey = a.slug || a.name;
        agentSel.innerHTML += `<option value="${escapeHtml(agentKey)}">${escapeHtml(a.name)}${a.description ? ` — ${escapeHtml(a.description.slice(0, 60))}` : ''}</option>`;
    });
    if (previewEl) previewEl.style.display = 'none';
}

async function ocImportShowAgentPreview() {
    const agentSel = document.getElementById('oc-catalog-agent-select');
    const previewEl = document.getElementById('oc-catalog-agent-preview');
    if (!agentSel || !agentSel.value || !previewEl) return;

    previewEl.style.display = '';
    previewEl.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Loading…`;

    try {
        const resp = await fetch(`/v1/openclaude/catalog/agents/${encodeURIComponent(agentSel.value)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const agent = await resp.json();

        const tools = Array.isArray(agent.tools) ? agent.tools.join(', ') : (agent.tools || '—');
        previewEl.innerHTML = `
            <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:13px">
                <strong>Name:</strong><span>${escapeHtml(agent.name)}</span>
                ${agent.model ? `<strong>Model:</strong><span>${escapeHtml(agent.model)}</span>` : ''}
                <strong>Tools:</strong><span>${escapeHtml(tools)}</span>
                <strong>Description:</strong><span>${escapeHtml(agent.description || '—')}</span>
            </div>
            ${agent.body ? `<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:var(--gray)">System prompt preview</summary>
            <pre style="max-height:120px;overflow-y:auto;font-size:12px;margin-top:6px;white-space:pre-wrap;word-break:break-word">${escapeHtml(agent.body.slice(0, 800))}${agent.body.length > 800 ? '\n…' : ''}</pre>
            </details>` : ''}`;
    } catch (err) {
        previewEl.innerHTML = `<span style="color:var(--error)">Failed to load preview: ${escapeHtml(err.message)}</span>`;
    }
}

async function ocImportExecute() {
    // Determine active tab
    const filePanel = document.getElementById('oc-import-panel-file');
    const isFileTab = filePanel && filePanel.style.display !== 'none';

    if (isFileTab) {
        // ── File upload path ──
        const fileInput = document.getElementById('oc-import-file-input');
        if (!fileInput || !fileInput.files || !fileInput.files[0]) {
            showNotification('Select a .md file first', 'error');
            return;
        }
        const content = fileInput._parsedContent;
        if (!content) {
            showNotification('File not yet read — wait a moment and retry', 'error');
            return;
        }
        const overwrite = document.getElementById('oc-import-overwrite')?.checked || false;

        try {
            const resp = await fetch('/v1/openclaude/agents/import-markdown', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, overwrite }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            const result = await resp.json();
            showNotification(`Agent "${result.name}" imported`, 'success');
            closeModal();
            loadOpenClaudeAgents();
        } catch (err) {
            showNotification(`Import failed: ${err.message}`, 'error');
        }
    } else {
        // ── Remote catalog path ──
        const agentSel = document.getElementById('oc-catalog-agent-select');
        if (!agentSel || !agentSel.value) {
            showNotification('Select an agent from the catalog', 'error');
            return;
        }
        const agentName = agentSel.value;

        try {
            const resp = await fetch(`/v1/openclaude/agents/import-from-catalog/${encodeURIComponent(agentName)}`, {
                method: 'POST',
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            const result = await resp.json();
            showNotification(`Agent "${result.name}" imported from catalog`, 'success');
            closeModal();
            loadOpenClaudeAgents();
        } catch (err) {
            showNotification(`Catalog import failed: ${err.message}`, 'error');
        }
    }
}
