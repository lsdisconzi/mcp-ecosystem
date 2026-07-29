document.addEventListener('DOMContentLoaded', setupToolsModule);

let selectedTool = null;
let currentToolId = null;

function setupToolsModule() {
    if (toolEventsBound) return;
    toolEventsBound = true;

    document.querySelector('[data-section="tools-section"]')?.addEventListener('click', async () => {
        await ensureAssistantsLoaded();
        await loadTools();
        populateAssistantSelector();
        updateAssignedToolsList();
    });

    document.getElementById('create-tool-btn')?.addEventListener('click', createNewTool);
    document.getElementById('refresh-tools-btn')?.addEventListener('click', loadTools);
    document.getElementById('save-tool-btn')?.addEventListener('click', saveTool);
    document.getElementById('delete-tool-btn')?.addEventListener('click', deleteTool);
    document.getElementById('cancel-tool-btn')?.addEventListener('click', createNewTool);

    const addParameterBtn = document.getElementById('add-parameter-btn');
    if (addParameterBtn) {
        addParameterBtn.addEventListener('click', () => {
            addParameterRow();
            updateJsonPreview();
        });
    }

    document.getElementById('test-tool-btn')?.addEventListener('click', testTool);
    document.getElementById('assign-tool-btn')?.addEventListener('click', assignToolToAssistant);

    const assistantSelector = document.getElementById('assistant-selector');
    assistantSelector?.addEventListener('change', (event) => {
        const selectedId = event.target.value;
        selectedAssistant = availableAssistants.find(assistant => assistant.id === selectedId) || null;
        updateAssignedToolsList();
    });

    document.getElementById('tool-search')?.addEventListener('input', handleToolSearch);

    createNewTool();
}

async function ensureAssistantsLoaded() {
    if (!availableAssistants.length && typeof loadAssistants === 'function') {
        await loadAssistants();
    }
}

async function loadTools() {
    const toolsList = document.getElementById('tools-list');
    if (!toolsList) return;

    toolsList.innerHTML = '<div class="loading">Loading tools...</div>';

    try {
        const response = await fetch('/v1/tools');
        const data = await response.json();
        const tools = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : []);

        availableTools = tools;
        window.allTools = tools;

        if (!tools.length) {
            toolsList.innerHTML = '<div class="empty-state">No tools found</div>';
            return;
        }

        toolsList.innerHTML = '';
        tools.forEach((tool, index) => {
            const element = document.createElement('div');
            element.className = 'tool-item';
            element.innerHTML = `
                <div class="tool-name">${tool.function?.name || 'Unnamed Tool'}</div>
                <div class="tool-desc">${tool.function?.description || ''}</div>
            `;
            element.addEventListener('click', (event) => selectTool(tool, event.currentTarget, index));
            toolsList.appendChild(element);
        });
    } catch (error) {
        toolsList.innerHTML = '<div class="error">Failed to load tools</div>';
        console.error('Error loading tools:', error);
    }
}

function handleToolSearch(event) {
    const searchTerm = event.target.value.toLowerCase();
    document.querySelectorAll('.tool-item').forEach(item => {
        const name = item.querySelector('.tool-name')?.textContent.toLowerCase() || '';
        const desc = item.querySelector('.tool-desc')?.textContent.toLowerCase() || '';
        item.style.display = (name.includes(searchTerm) || desc.includes(searchTerm)) ? 'block' : 'none';
    });
}

function selectTool(tool, element, index) {
    selectedTool = tool;
    currentToolId = tool.function?.name || tool.id;
    window.currentToolIdx = index;

    document.querySelectorAll('.tool-item').forEach(el => el.classList.remove('selected'));
    element?.classList.add('selected');

    const nameInput = document.getElementById('tool-name');
    if (nameInput) {
        nameInput.value = tool.function?.name || '';
    }
    const descriptionInput = document.getElementById('tool-description');
    if (descriptionInput) {
        descriptionInput.value = tool.function?.description || '';
    }
    const typeSelect = document.getElementById('tool-type');
    if (typeSelect) {
        typeSelect.value = tool.type || 'function';
    }

    const paramsContainer = document.getElementById('parameters-container');
    if (paramsContainer) {
        paramsContainer.innerHTML = '';
        const parameters = tool.function?.parameters?.properties || {};
        const required = tool.function?.parameters?.required || [];
        Object.entries(parameters).forEach(([name, param]) => {
            addParameterRow(name, param.type || 'string', param.description || '', required.includes(name));
        });
    }

    const deleteBtn = document.getElementById('delete-tool-btn');
    if (deleteBtn) {
        deleteBtn.style.display = 'inline-block';
    }

    updateJsonPreview();
}

function addParameterRow(name = '', type = 'string', description = '', required = false) {
    const container = document.getElementById('parameters-container');
    if (!container) return;

    const rowId = `param-${Date.now()}-${Math.floor(Math.random() * 10000)}`;

    const row = document.createElement('div');
    row.className = 'parameter-row';
    row.innerHTML = `
        <input type="text" id="${rowId}-name" name="param_name[]" class="param-name" aria-label="Parameter name" placeholder="Name" value="${name}">
        <select id="${rowId}-type" name="param_type[]" class="param-type" aria-label="Parameter type">
            <option value="string" ${type === 'string' ? 'selected' : ''}>String</option>
            <option value="number" ${type === 'number' ? 'selected' : ''}>Number</option>
            <option value="boolean" ${type === 'boolean' ? 'selected' : ''}>Boolean</option>
            <option value="object" ${type === 'object' ? 'selected' : ''}>Object</option>
        </select>
        <input type="text" id="${rowId}-desc" name="param_desc[]" class="param-desc" aria-label="Parameter description" placeholder="Description" value="${description}">
        <label class="param-required">
            <input type="checkbox" id="${rowId}-required" name="param_required[]" aria-label="Parameter required" ${required ? 'checked' : ''}> Required
        </label>
        <button type="button" class="btn btn-icon remove-param" aria-label="Remove parameter row">
            <i class="fas fa-times"></i>
        </button>
    `;

    row.querySelector('.remove-param').addEventListener('click', () => {
        row.remove();
        updateJsonPreview();
    });

    row.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('change', updateJsonPreview);
    });

    container.appendChild(row);
}

function updateJsonPreview() {
    const name = document.getElementById('tool-name')?.value;
    const description = document.getElementById('tool-description')?.value;
    const type = document.getElementById('tool-type')?.value;

    const paramRows = document.querySelectorAll('.parameter-row');
    const properties = {};
    const required = [];

    paramRows.forEach(row => {
        const paramName = row.querySelector('.param-name')?.value;
        const paramType = row.querySelector('.param-type')?.value;
        const paramDesc = row.querySelector('.param-desc')?.value;
        const isRequired = row.querySelector('.param-required input')?.checked;

        if (paramName) {
            properties[paramName] = {
                type: paramType,
                description: paramDesc
            };
            if (isRequired) {
                required.push(paramName);
            }
        }
    });

    const toolJson = {
        type: type || 'function',
        function: {
            name: name || '',
            description: description || '',
            parameters: {
                type: 'object',
                properties,
                required
            }
        }
    };

    const preview = document.getElementById('json-preview');
    if (preview) {
        preview.textContent = JSON.stringify(toolJson, null, 2);
    }
}

async function saveTool() {
    const name = document.getElementById('tool-name')?.value.trim();
    if (!name) {
        showNotification('Tool name is required', 'error');
        return;
    }

    let toolJson;
    try {
        toolJson = JSON.parse(document.getElementById('json-preview').textContent);
    } catch (error) {
        showNotification('Invalid JSON payload for tool.', 'error');
        return;
    }

    try {
        const method = selectedTool ? 'PUT' : 'POST';
        const url = selectedTool ? `/v1/tools/${encodeURIComponent(currentToolId)}` : '/v1/tools';

        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(toolJson)
        });

        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(payload?.detail || 'Failed to save tool');
        }

        showNotification(`Tool ${selectedTool ? 'updated' : 'created'} successfully`, 'success');
        await loadTools();
        createNewTool();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
        console.error('Error saving tool:', error);
    }
}

async function deleteTool() {
    if (!selectedTool || !confirm('Are you sure you want to delete this tool?')) {
        return;
    }

    try {
        const response = await fetch(`/v1/tools/${encodeURIComponent(currentToolId)}`, {
            method: 'DELETE'
        });

        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(payload?.detail || 'Failed to delete tool');
        }

        showNotification('Tool deleted successfully', 'success');
        await loadTools();
        createNewTool();
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
        console.error('Error deleting tool:', error);
    }
}

function createNewTool() {
    selectedTool = null;
    currentToolId = null;

    const nameInput = document.getElementById('tool-name');
    const descriptionInput = document.getElementById('tool-description');
    const typeSelect = document.getElementById('tool-type');
    const paramsContainer = document.getElementById('parameters-container');
    const deleteBtn = document.getElementById('delete-tool-btn');
    const formTitle = document.getElementById('form-title');

    if (nameInput) nameInput.value = '';
    if (descriptionInput) descriptionInput.value = '';
    if (typeSelect) typeSelect.value = 'function';
    if (paramsContainer) {
        paramsContainer.innerHTML = '';
        addParameterRow();
    }
    if (deleteBtn) deleteBtn.style.display = 'none';
    if (formTitle) formTitle.textContent = 'Create New Tool';

    updateJsonPreview();
}

async function testTool() {
    if (!selectedTool) {
        showNotification('Please select a tool first', 'error');
        return;
    }

    const testInputField = document.getElementById('test-tool-input');
    const outputEl = document.getElementById('test-tool-output');

    if (!testInputField || !outputEl) return;

    const testInput = testInputField.value;
    if (!testInput) {
        showNotification('Please enter test parameters', 'error');
        return;
    }

    try {
        const params = JSON.parse(testInput);
        outputEl.textContent = 'Testing...';

        const response = await fetch(`/v1/tools/${encodeURIComponent(currentToolId)}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Tool execution failed');
        }
        outputEl.textContent = JSON.stringify(result, null, 2);
    } catch (error) {
        outputEl.textContent = `Error: ${error.message}`;
    }
}

async function assignToolToAssistant() {
    if (!selectedAssistant || !selectedTool) {
        showNotification('Select both an assistant and a tool.', 'error');
        return;
    }

    try {
        const response = await fetch(`/v1/assistants/${selectedAssistant.id}/tools`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_id: selectedTool.function?.name })
        });

        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(payload?.detail || 'Failed to assign tool');
        }

        showNotification('Tool assigned!', 'success');
        await loadAssistants();
        populateAssistantSelector();
        selectedAssistant = availableAssistants.find(a => a.id === selectedAssistant.id) || selectedAssistant;
        updateAssignedToolsList();
    } catch (error) {
        showNotification('Error assigning tool: ' + error.message, 'error');
    }
}

function populateAssistantSelector() {
    const selector = document.getElementById('assistant-selector');
    if (!selector) return;

    const previous = selector.value;
    selector.innerHTML = '<option value="">Select assistant...</option>';
    availableAssistants.forEach(assistant => {
        const option = document.createElement('option');
        option.value = assistant.id;
        option.textContent = assistant.name || assistant.id;
        if (selectedAssistant && assistant.id === selectedAssistant.id) {
            option.selected = true;
        }
        selector.appendChild(option);
    });

    if (previous && selector.querySelector(`option[value="${previous}"]`)) {
        selector.value = previous;
    }
}

function updateAssignedToolsList() {
    const assignedList = document.getElementById('assigned-tools-list');
    if (!assignedList) return;

    assignedList.innerHTML = '';
    if (!selectedAssistant) {
        assignedList.innerHTML = '<div style="color:var(--gray-400);padding:8px;">No assistant selected.</div>';
        return;
    }

    const assignedToolIds = selectedAssistant.tools || [];
    if (!assignedToolIds.length) {
        assignedList.innerHTML = '<div style="color:var(--gray-400);padding:8px;">No tools assigned.</div>';
        return;
    }

    assignedToolIds.forEach(toolId => {
        const tool = availableTools.find(t => (t.function?.name || t.id) === toolId);
        assignedList.innerHTML += `
            <div class="model-item" style="margin-bottom:6px;">
                <span style="font-weight:600;">${tool ? (tool.function?.name || tool.id) : toolId}</span>
                <span style="color:var(--gray-400);margin-left:8px;">${tool ? (tool.function?.description || '') : ''}</span>
            </div>
        `;
    });
}

function showToolJsonEditor(idx) {
    const tool = availableTools[idx];
    if (!tool) return;

    const textarea = document.getElementById('tool-json-area');
    const editor = document.getElementById('tool-json-editor');
    const testSection = document.getElementById('tool-test-section');

    if (!textarea || !editor || !testSection) return;

    textarea.value = JSON.stringify(tool, null, 2);
    editor.style.display = 'block';
    testSection.style.display = 'none';
    window.currentToolIdx = idx;
}

function showToolTest(idx) {
    const tool = availableTools[idx];
    if (!tool) return;

    const testSection = document.getElementById('tool-test-section');
    const editor = document.getElementById('tool-json-editor');
    const input = document.getElementById('tool-test-input');

    if (!testSection || !editor || !input) return;

    testSection.style.display = 'block';
    editor.style.display = 'none';

    input.value = JSON.stringify(
        Object.fromEntries(
            Object.entries(tool.function?.parameters?.properties || {}).map(([key, value]) => {
                if (value.type === 'string') return [key, ''];
                if (value.type === 'number') return [key, 0];
                if (value.type === 'boolean') return [key, false];
                return [key, null];
            })
        ),
        null,
        2
    );
    window.currentToolIdx = idx;
}
