document.addEventListener('DOMContentLoaded', initializePlayground);

function initializePlayground() {
    if (playgroundEventsBound) return;
    playgroundEventsBound = true;
    bindPlaygroundControls();
    loadModels();
}

function bindPlaygroundControls() {
    const temperatureSlider = document.getElementById('temperature');
    const temperatureValue = document.getElementById('temperature-value');
    if (temperatureSlider && temperatureValue) {
        updateSliderDisplay(temperatureSlider, temperatureValue, 2);
        temperatureSlider.addEventListener('input', () => updateSliderDisplay(temperatureSlider, temperatureValue, 2));
    }

    const topPSlider = document.getElementById('top-p');
    const topPValue = document.getElementById('top-p-value');
    if (topPSlider && topPValue) {
        updateSliderDisplay(topPSlider, topPValue, 2);
        topPSlider.addEventListener('input', () => updateSliderDisplay(topPSlider, topPValue, 2));
    }

    const generateBtn = document.getElementById('generate-btn');
    generateBtn?.removeEventListener('click', generateResponse);
    generateBtn?.addEventListener('click', generateResponse);

    const clearBtn = document.getElementById('clear-playground-btn') || document.getElementById('clear-btn');
    clearBtn?.addEventListener('click', clearPlayground);
}

function updateSliderDisplay(slider, target, precision = 1) {
    const value = parseFloat(slider.value);
    target.textContent = Number.isFinite(value) ? value.toFixed(precision) : slider.value;
}

// ─── Provider state ───────────────────────────────────────────────────────
const PLAYGROUND_PROVIDER = { id: 'ollama', apiKey: '' };

const EXTERNAL_MODELS = {
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1-mini'],
    anthropic: ['deepseek-v4-pro', 'deepseek-v4-flash'],
    groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768', 'gemma2-9b-it'],
    xai: ['grok-3', 'grok-3-mini', 'grok-2-1212'],
};

const PROVIDER_KEY_HINTS = {
    openai: 'OpenAI key — sk-…',
    anthropic: 'DeepSeek key via ANTHROPIC_API_KEY',
    groq: 'Groq key — gsk_…',
    xai: 'xAI key — xai-…',
};

function selectPlaygroundProvider(provider, btn) {
    PLAYGROUND_PROVIDER.id = provider;
    // Toggle active pill
    document.querySelectorAll('#playground-provider-selector .provider-pill').forEach(p => p.classList.remove('active'));
    if (btn) btn.classList.add('active');

    const keyRow = document.getElementById('playground-api-key-row');
    const keyNote = document.getElementById('playground-key-note');
    const isLocal = provider === 'ollama';

    if (isLocal) {
        keyRow.classList.remove('visible');
        refreshModelListFromCache();   // restore Ollama cards
    } else {
        keyRow.classList.add('visible');
        if (keyNote) keyNote.textContent = PROVIDER_KEY_HINTS[provider] || 'API key';
        // Watch key input
        const keyInput = document.getElementById('playground-api-key');
        if (keyInput) keyInput.oninput = () => { PLAYGROUND_PROVIDER.apiKey = keyInput.value.trim(); };
        populateExternalModels(provider);
    }
}

function refreshModelListFromCache() {
    const modelList = document.getElementById('model-list');
    const modelSelect = document.getElementById('selected-model');
    const DEFAULT = 'llama3.1:8b';

    if (!modelList || !modelSelect) return;
    modelList.innerHTML = '';
    modelSelect.innerHTML = '';

    const models = availableModels.length ? availableModels : [{ id: DEFAULT }];
    models.forEach((model, idx) => {
        // Card
        const item = document.createElement('div');
        item.className = 'model-item' + (idx === 0 ? ' selected' : '');
        item.innerHTML = `
            <div class="model-icon"><i class="fas fa-server"></i></div>
            <div class="model-name">${model.id}</div>
            <div class="model-meta"><span>Ollama · local</span></div>
        `;
        item.addEventListener('click', () => selectModel(model.id));
        modelList.appendChild(item);

        // Option
        const opt = document.createElement('option');
        opt.value = model.id;
        opt.textContent = model.id;
        if (idx === 0) opt.selected = true;
        modelSelect.appendChild(opt);
    });
}

function populateExternalModels(provider) {
    const modelList = document.getElementById('model-list');
    const modelSelect = document.getElementById('selected-model');
    const models = EXTERNAL_MODELS[provider] || [];

    if (modelList) {
        modelList.innerHTML = '';
        models.forEach((id, idx) => {
            const item = document.createElement('div');
            item.className = 'model-item' + (idx === 0 ? ' selected' : '');
            item.innerHTML = `
                <div class="model-icon"><i class="fas fa-cloud"></i></div>
                <div class="model-name">${id}</div>
                <div class="model-meta"><span>${provider}</span></div>
            `;
            item.addEventListener('click', () => selectModel(id));
            modelList.appendChild(item);
        });
    }

    if (modelSelect) {
        modelSelect.innerHTML = '';
        models.forEach((id, idx) => {
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = id;
            if (idx === 0) opt.selected = true;
            modelSelect.appendChild(opt);
        });
    }
}

async function loadModels() {
    const DEFAULT = 'llama3.1:8b';
    try {
        const response = await fetch('/v1/models');
        const data = await response.json();

        if (response.ok && data.data && data.data.length) {
            // Backend already returns them sorted (llama3-groq-tool-use:8b first), but honour that here too
            const pinned = data.data.filter(m => m.id === DEFAULT);
            const rest = data.data.filter(m => m.id !== DEFAULT).sort((a, b) => a.id.localeCompare(b.id));
            availableModels = [...pinned, ...rest];
        } else {
            availableModels = [{ id: DEFAULT, owned_by: 'ollama', api_type: 'local' }];
        }
    } catch (error) {
        availableModels = [{ id: DEFAULT, owned_by: 'ollama', api_type: 'local' }];
        console.error('Error loading models:', error);
    }

    // Render local model cards + sync assistant model selects
    refreshModelListFromCache();
    syncAssistantModelSelects();
}

function selectModel(modelId) {
    document.querySelectorAll('.model-item').forEach(item => {
        item.classList.remove('selected');
    });

    // Find the model item and select it
    const modelItems = document.querySelectorAll('.model-item');
    for (let i = 0; i < modelItems.length; i++) {
        const nameElement = modelItems[i].querySelector('.model-name');
        if (nameElement && nameElement.textContent === modelId) {
            modelItems[i].classList.add('selected');
            break;
        }
    }

    const modelSelect = document.getElementById('selected-model');
    if (modelSelect) {
        modelSelect.value = modelId;
    }
}

async function generateResponse() {
    const generateBtn = document.getElementById('generate-btn');
    const resultDiv = document.getElementById('generation-result');
    const modelSelect = document.getElementById('selected-model');
    const promptInput = document.getElementById('prompt-input');

    // Guard clauses
    if (!generateBtn || !resultDiv || !modelSelect || !promptInput) return;

    const model = modelSelect.value;
    const prompt = promptInput.value;

    if (!model || !prompt) {
        showNotification('Please select a model and enter a prompt', 'error');
        return;
    }

    // Validate external provider has an API key
    const provider = PLAYGROUND_PROVIDER.id;
    const apiKey = PLAYGROUND_PROVIDER.apiKey || document.getElementById('playground-api-key')?.value?.trim() || '';
    if (provider && provider !== 'ollama' && !apiKey) {
        showNotification(`Enter an API key for ${provider} to continue`, 'error');
        document.getElementById('playground-api-key')?.focus();
        return;
    }

    const originalText = generateBtn.innerHTML;
    generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
    generateBtn.disabled = true;

    resultDiv.innerHTML = `
        <div style="text-align: center; color: var(--gray-400); margin-top: 20px;">
            <i class="fas fa-spinner fa-spin"></i> Generating response…
        </div>
    `;

    try {
        const body = {
            model,
            messages: [{ role: 'user', content: prompt }],
            temperature: parseFloat(document.getElementById('temperature')?.value || 0.7),
            max_tokens: parseInt(document.getElementById('max-tokens')?.value || 1000),
            top_p: parseFloat(document.getElementById('top-p')?.value || 1.0),
        };
        if (provider && provider !== 'ollama') {
            body.provider = provider;
            body.api_key = apiKey;
        }

        const response = await fetch('/v1/chat/completions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        const data = await response.json();

        if (response.ok && data.choices?.[0]?.message) {
            resultDiv.innerHTML = `
                <div style="background: var(--gray-100); padding: 15px; border-radius: 8px;">
                    <strong>Response:</strong><br>
                    ${data.choices[0].message.content}
                </div>
            `;
        } else {
            throw new Error(data.detail || 'Generation failed');
        }
    } catch (error) {
        resultDiv.innerHTML = `
            <div style="background: rgba(239, 71, 111, 0.1); padding: 15px; border-radius: 8px; border: 1px solid var(--danger); color: var(--danger);">
                <strong>Error:</strong> ${error.message}
            </div>
        `;
    } finally {
        generateBtn.innerHTML = originalText;
        generateBtn.disabled = false;
    }
}

function clearPlayground() {
    const promptInput = document.getElementById('prompt-input');
    const resultDiv = document.getElementById('generation-result');
    const modelSelect = document.getElementById('selected-model');

    if (promptInput) promptInput.value = '';
    if (resultDiv) resultDiv.innerHTML = '';
    if (modelSelect) modelSelect.value = '';

    document.querySelectorAll('.model-item').forEach(item => {
        item.classList.remove('selected');
    });
}

// === Simple Endpoint Tester ===
// (Note: Complex integration tests belong in garage-tests.js)

/** Keep assistant modal model selects in sync with locally loaded models. */
function syncAssistantModelSelects() {
    const DEFAULT = 'llama3-groq-tool-use:8b';
    const selects = [
        document.getElementById('modal-assistant-model'),
        document.getElementById('modal-edit-assistant-model'),
    ];
    selects.forEach(sel => {
        if (!sel) return;
        // Only sync if the select currently shows local models (i.e. no provider header option)
        if (sel.querySelector('option[data-provider]')) return;
        const currentVal = sel.value;
        sel.innerHTML = '';
        availableModels.forEach((m, idx) => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.id;
            if (m.id === DEFAULT) opt.selected = true;
            sel.appendChild(opt);
        });
        // Restore previous selection if still available
        if (currentVal && sel.querySelector(`option[value="${currentVal}"]`)) {
            sel.value = currentVal;
        }
    });
}

async function testEndpoint(row) {
    const endpoint = row.dataset.endpoint;
    const method = row.dataset.method;
    const statusIcon = row.querySelector('.status-icon');
    const responseDiv = row.nextElementSibling.querySelector('.endpoint-response');

    if (statusIcon) statusIcon.className = 'status-icon status-loading';

    try {
        const options = { method: method };

        if (method === 'POST') {
            options.headers = { 'Content-Type': 'application/json' };
            options.body = JSON.stringify(getTestPayload(endpoint));
        }

        const response = await fetch(endpoint, options);
        const data = await response.json();
        console.log(`Response from ${endpoint}:`, data);

        if (response.ok) {
            if (statusIcon) statusIcon.className = 'status-icon status-success';
            if (responseDiv) responseDiv.textContent = JSON.stringify(data, null, 2);
        } else {
            throw new Error(`${response.status}: ${response.statusText}`);
        }
    } catch (error) {
        if (statusIcon) statusIcon.className = 'status-icon status-error';
        if (responseDiv) responseDiv.textContent = `Error: ${error.message}`;
    }
}

function getTestPayload(endpoint) {
    const model = availableModels[0]?.id || 'llama3.1:8b';
    const payloads = {
        // Chat & Completions
        '/v1/chat/completions': {
            model,
            messages: [{ role: 'user', content: 'Hello, how are you?' }],
            max_tokens: 50
        },
        '/v1/deepseek-engineer/chat': {
            messages: [{ role: 'user', content: 'Hello' }]
        },

        // Assistants
        '/v1/assistants/': {
            name: 'Test Assistant',
            model,
            instructions: 'You are a helpful test assistant.'
        },

        // Files
        '/v1/files/summarize': {
            file_ids: ['file_test'],
            model,
            temperature: 0.1
        },

        // Qdrant
        '/v1/qdrant/collections': {
            name: 'test_collection',
            vector_size: 384
        },
        '/v1/qdrant/collections/structured_ingest': {
            collection_name: 'test_collection',
            data_type: 'transcript',
            items: [{ id: '1', text: 'Sample transcript text for testing' }]
        },
        '/v1/qdrant/embed-case-directory': {
            case_directory: 'case_001',
            collection_name: 'case_001_collection',
            embedding_dim: 384
        },
        '/v1/qdrant/query': {
            collection_name: 'test_collection',
            query_vector: Array(384).fill(0.01)
        },
        '/v1/qdrant/search': {
            collection_name: 'test_collection',
            query_text: 'test search query'
        },

        // Knowledge
        '/v1/knowledge/query': {
            collection_name: 'test_collection',
            query: 'test query',
            limit: 5
        },
        '/v1/knowledge/ingest/text': {
            collection_name: 'test_collection',
            text: 'Sample knowledge text for testing'
        },

        // Tools
        '/v1/tools/execute': {
            tool_name: 'echo',
            parameters: { text: 'hello' }
        },
        '/v1/v1/tools': {
            type: 'function',
            function: { name: 'echo', description: 'Echoes input', parameters: { text: 'hello' } }
        },
        '/v1/tools/deep_reasoning': {
            question: 'What are the key security requirements?'
        },

        // Prompt Engineer
        '/v1/prompt-engineer/generate': {
            model,
            user_input: 'Write a security checklist',
            system_prompt: 'You are a prompt engineering expert. Be concise.'
        },
        '/v1/prompt-engineer/analyze': {
            user_input: 'Help me write a legal summary',
            model
        },
        '/v1/prompt-engineer/variations': {
            prompt: 'Summarize the following document briefly.',
            count: 3,
            model
        },
        '/v1/prompt-engineer/optimize': {
            prompt: 'Summarize this legal document.',
            metrics: { clarity: 8, specificity: 7, creativity: 5, conciseness: 9 },
            model
        },
        '/v1/prompt-engineer/evaluate': {
            prompt: 'Summarize this legal document.',
            model
        },
        '/v1/prompt-engineer/improve': {
            prompt: 'Summarize this legal document.',
            metrics: { clarity: 6, specificity: 5, creativity: 4, conciseness: 7 },
            model
        },

        // Ingestion
        '/v1/ingestion/ingest-legal-folder': {
            folder_path: '/tmp/test_docs',
            collection_name: 'legal_documents'
        },
        '/v2/legal-ingestion/ingest-legal-folder': {
            folder_path: '/tmp/test_docs',
            collection_name: 'legal_documents'
        },

        // Threads (no required fields)
        '/v1/threads/': {}
    };

    return payloads[endpoint] ?? {};
}