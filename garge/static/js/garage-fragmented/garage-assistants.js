// ...existing code...

async function loadAssistants() {
    const assistantsList = document.getElementById('assistants-list');
    if (!assistantsList) return;

    assistantsList.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--gray-400);">Loading assistants...</div>';

    try {
        const response = await fetch('/v1/assistants/');
        const data = await response.json();

        let assistants = [];
        if (data.data && Array.isArray(data.data)) {
            assistants = data.data;
        } else if (Array.isArray(data)) {
            assistants = data;
        } else if (data.assistants && Array.isArray(data.assistants)) {
            assistants = data.assistants;
        }

        if (assistants.length === 0) {
            assistantsList.innerHTML = `
                <div style="text-align: center; padding: 40px; background: var(--gray-100); border-radius: 8px;">
                    <div style="font-size: 48px; margin-bottom: 16px; color: var(--gray-400);">🤖</div>
                    <h3>No Assistants Found</h3>
                    <p style="color: var(--gray-400); margin-bottom: 20px;">Create your first custom assistant to get started!</p>
                    <button class="btn btn-primary" onclick="showCreateAssistantModal()">
                        <i class="fas fa-plus"></i> Create First Assistant
                    </button>
                </div>
            `;
            return;
        }

        availableAssistants = assistants;
        populateKnowledgeAssistants();
        assistantsList.innerHTML = '';

        assistants.forEach(assistant => {
            const assistantCard = document.createElement('div');
            assistantCard.className = 'assistant-card';
            assistantCard.style.cursor = 'pointer';
            if (selectedAssistant && selectedAssistant.id === assistant.id) {
                assistantCard.style.border = '2px solid var(--primary)';
                assistantCard.style.background = 'rgba(67,97,238,0.08)';
            }
            
            assistantCard.innerHTML = `
                <div class="assistant-header">
                    <div>
                        <div class="assistant-name">${assistant.name || 'Unnamed Assistant'}</div>
                        <div class="assistant-model">${assistant.model || 'No model specified'}</div>
                    </div>
                    <div class="assistant-actions">
                        <button class="action-btn" onclick="showChatModal('${assistant.id}', '${assistant.name}');event.stopPropagation();" title="Chat">
                            <i class="fas fa-comment"></i>
                        </button>
                        <button class="action-btn" onclick="showEditAssistantModal('${assistant.id}');event.stopPropagation();" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="action-btn" onclick="exportAssistantToOpenClaude('${assistant.id}');event.stopPropagation();" title="Export to OpenClaude Agent" style="color:var(--amber)">
                            <i class="fas fa-file-export"></i>
                        </button>
                        <button class="action-btn" onclick="deleteAssistant('${assistant.id}');event.stopPropagation();" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="assistant-details">
                    <div class="detail-item">
                        <span>ID:</span> <span>${assistant.id}</span>
                    </div>
                    <div class="detail-item">
                        <span>Created:</span> <span>${assistant.created_at ? new Date(assistant.created_at * 1000).toLocaleDateString() : 'Unknown'}</span>
                    </div>
                    <div class="detail-item">
                        <span>Files:</span> <span>${assistant.file_ids ? assistant.file_ids.length : 0}</span>
                    </div>
                    <div class="detail-item">
                        <span>Tools:</span> <span>${assistant.tools ? assistant.tools.length : 0}</span>
                    </div>
                    <div class="detail-item">
                        <span>Language:</span> <span>${assistant.language || 'en'}</span>
                    </div>
                    <div class="detail-item">
                        <span>Collections:</span> <span>${Array.isArray(assistant.collections) && assistant.collections.length ? assistant.collections.join(', ') : 'None'}</span>
                    </div>
                    <div class="detail-item">
                        <span>Max Tokens:</span> <span>${assistant.max_tokens || 500}</span>
                    </div>
                    <div class="detail-item">
                        <span>Temperature:</span> <span>${assistant.temperature ?? 0.7}</span>
                    </div>
                </div>
                ${assistant.instructions ? `
                <div class="assistant-instructions">
                    ${assistant.instructions.substring(0, 150)}${assistant.instructions.length > 150 ? '...' : ''}
                </div>
                ` : ''}
            `;
            
            assistantCard.addEventListener('click', () => {
                selectedAssistant = assistant;
                showNotification(`Selected assistant: ${assistant.name}`, 'info');
                updateSelectedAssistantLabel();
                loadAssistants();
            });
            assistantsList.appendChild(assistantCard);
        });
    } catch (error) {
        assistantsList.innerHTML = `
            <div style="text-align: center; padding: 40px; background: var(--gray-100); border-radius: 8px; border: 1px solid var(--danger);">
                <div style="font-size: 48px; margin-bottom: 16px; color: var(--danger);">❌</div>
                <h3 style="color: var(--danger);">Failed to Load Assistants</h3>
                <p style="color: var(--gray-400); margin-bottom: 20px;">Error: ${error.message}</p>
                <button class="btn btn-secondary" onclick="loadAssistants()">
                    <i class="fas fa-sync-alt"></i> Try Again
                </button>
            </div>
        `;
    }
}

        // ─── Provider picker shared helper ───────────────────────────────────────
        const _ASST_EXTERNAL_MODELS = {
            // Discovery parity: same DeepSeek models with either URL format.
            openai: ['deepseek-v4-pro', 'deepseek-v4-flash'],
            anthropic: ['deepseek-v4-pro', 'deepseek-v4-flash'],
        };

        const _ASST_DEEPSEEK_BASE_URLS = {
            openai: 'https://api.deepseek.com/v1',
            anthropic: 'https://api.deepseek.com/anthropic',
        };

        function inferAssistantProviderFromModel(modelId = '') {
            const id = String(modelId || '').trim().toLowerCase();
            if (!id) return 'ollama';
            if (id.startsWith('deepseek-v4-')) return 'anthropic';
            if (id.startsWith('gpt-') || id.startsWith('o1') || id.startsWith('o3')) return 'openai';
            if (id.startsWith('claude-')) return 'anthropic';
            if (id.startsWith('grok-')) return 'xai';
            if ((id.startsWith('llama-') || id.startsWith('mixtral-')) && !id.includes(':')) return 'groq';
            return 'ollama';
        }

        function getAssistantModelOptions(provider, currentModel) {
            const current = String(currentModel || '').trim();

            if (provider === 'ollama' || provider === 'local') {
                const DEFAULT = 'llama3.1:8b';
                const models = availableModels.length ? availableModels : [{ id: DEFAULT }];
                return models.map((m, i) => {
                    const id = m.id;
                    const selected = current ? id === current : i === 0;
                    return `<option value="${id}"${selected ? ' selected' : ''}>${id}</option>`;
                }).join('');
            }

            const external = [...(_ASST_EXTERNAL_MODELS[provider] || [])];
            if (current && !external.includes(current)) external.unshift(current);
            return external.map((id, i) => {
                const selected = current ? id === current : i === 0;
                return `<option value="${id}"${selected ? ' selected' : ''}>${id}</option>`;
            }).join('');
        }

        function getSelectedAssistantProvider(selectId, fallbackModel = '') {
            const hidden = document.getElementById(`${selectId}-provider`);
            if (hidden?.value) return hidden.value;
            const modelValue = document.getElementById(selectId)?.value || fallbackModel;
            return inferAssistantProviderFromModel(modelValue);
        }

        function buildAssistantProviderMetadata(provider, previousMetadata = {}) {
            const metadata = {
                ...(previousMetadata && typeof previousMetadata === 'object' ? previousMetadata : {}),
            };

            if (provider === 'openai' || provider === 'anthropic') {
                metadata.llm_provider = provider;
                metadata.llm_url_format = provider;
                metadata.llm_base_url = _ASST_DEEPSEEK_BASE_URLS[provider];
            } else {
                delete metadata.llm_provider;
                delete metadata.llm_url_format;
                delete metadata.llm_base_url;
            }

            return metadata;
        }

        /**
         * Build the provider picker + model select HTML for assistant modals.
         * @param {string} selectId   - id for the <select> element
         * @param {string} currentModel - pre-selected model (for edit)
         */
        function buildAssistantProviderPicker(selectId, currentModel, currentProvider = '') {
            const providerGuess = (currentProvider || '').toLowerCase();
            const initialProvider = (
                providerGuess === 'local' || providerGuess === 'ollama' ||
                providerGuess === 'openai' || providerGuess === 'anthropic'
            )
                ? (providerGuess === 'local' ? 'ollama' : providerGuess)
                : inferAssistantProviderFromModel(currentModel);

            const opts = getAssistantModelOptions(initialProvider, currentModel);

            return `
                <div class="provider-selector" id="${selectId}-provider-bar" style="margin-bottom:8px;">
                    <span class="provider-selector-label">Provider</span>
                    <div class="provider-pills">
                        <button type="button" class="provider-pill ${initialProvider === 'ollama' ? 'active' : ''}" data-provider="ollama"
                                onclick="switchAssistantProvider('ollama', this, '${selectId}')">
                            <i class="fas fa-server"></i> Local
                        </button>
                        <button type="button" class="provider-pill ${initialProvider === 'openai' ? 'active' : ''}" data-provider="openai"
                                onclick="switchAssistantProvider('openai', this, '${selectId}')">
                            <i class="fas fa-robot"></i> OpenAI format <span class="pill-badge">key</span>
                        </button>
                        <button type="button" class="provider-pill ${initialProvider === 'anthropic' ? 'active' : ''}" data-provider="anthropic"
                                onclick="switchAssistantProvider('anthropic', this, '${selectId}')">
                            <i class="fas fa-brain"></i> Anthropic format <span class="pill-badge">key</span>
                        </button>
                    </div>
                </div>
                <input type="hidden" id="${selectId}-provider" value="${initialProvider}">
                <select id="${selectId}" name="${selectId}" style="width: 100%;" required>
                    ${opts}
                </select>
            `;
        }

        /** Switch provider in an assistant modal picker. */
        function switchAssistantProvider(provider, btn, selectId) {
            const bar = btn.closest('.provider-selector');
            if (!bar) return;
            bar.querySelectorAll('.provider-pill').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');

            const sel = document.getElementById(selectId);
            if (!sel) return;

            const providerInput = document.getElementById(`${selectId}-provider`);
            if (providerInput) providerInput.value = provider;

            sel.innerHTML = getAssistantModelOptions(provider, '');
        }

        // Expose to window so inline onclick in dynamically-created HTML can reach them
        window.switchAssistantProvider = switchAssistantProvider;

        // =================================================================================
        // ASSISTANT CREATION
        // =================================================================================

        async function showCreateAssistantModal() {
            if (!availableModels.length && typeof loadModels === 'function') {
                await loadModels();
            }
            if (!collections.length && typeof loadCollectionsData === 'function') {
                try {
                    await loadCollectionsData({ showLoader: false });
                } catch (error) {
                    console.warn('Unable to load collections before creating assistant:', error);
                }
            }

            const languageOptions = SUPPORTED_ASSISTANT_LANGUAGES.map(lang => 
                `<option value="${lang.value}">${lang.label}</option>`
            ).join('');
            
            const collectionOptions = collections.length
                ? collections.map(col => `<option value="${col.name}">${col.name}</option>`).join('')
                : '<option value="" disabled>No collections available</option>';

            createModal('Create Assistant', `
                <div class="parameter-group">
                    <label for="modal-assistant-name">Assistant Name *</label>
                    <input type="text" id="modal-assistant-name" name="assistant_name" style="width: 100%;" 
                           placeholder="Enter assistant name" required>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-description">Description</label>
                    <textarea id="modal-assistant-description" name="assistant_description" style="width: 100%; height: 80px;" 
                              placeholder="Enter assistant description"></textarea>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-model">Model *</label>
                    ${buildAssistantProviderPicker('modal-assistant-model', 'llama3.1:8b')}
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-instructions">Instructions</label>
                    <textarea id="modal-assistant-instructions" name="assistant_instructions" style="width: 100%; height: 120px;" 
                              placeholder="Enter detailed instructions for the assistant"></textarea>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-language">Language</label>
                    <select id="modal-assistant-language" name="assistant_language" style="width: 100%;">
                        ${languageOptions}
                    </select>
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Preferred language for responses
                    </small>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-collections">Collections</label>
                    <select id="modal-assistant-collections" name="assistant_collections" multiple style="width: 100%; height: 120px;">
                        ${collectionOptions}
                    </select>
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Select Qdrant collections for knowledge base (hold Ctrl/Cmd to select multiple)
                    </small>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-temperature">Temperature</label>
                    <input type="number" id="modal-assistant-temperature" name="assistant_temperature" value="0.7" 
                           step="0.1" min="0" max="2" style="width: 100%;">
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Controls randomness (0 = focused, 2 = creative)
                    </small>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-assistant-max-tokens">Max Tokens</label>
                    <input type="number" id="modal-assistant-max-tokens" name="assistant_max_tokens" value="500" 
                           min="1" max="4000" style="width: 100%;">
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Maximum response length (1-4000)
                    </small>
                </div>
            `, [
                {
                    text: 'Create',
                    class: 'btn-primary',
                    onclick: createAssistant
                },
                {
                    text: 'Cancel',
                    class: 'btn-secondary',
                    onclick: closeModal
                }
            ], '650px');
        }

        // ...existing code...
        
        async function createAssistant() {
            const name = document.getElementById('modal-assistant-name').value.trim();
            const description = document.getElementById('modal-assistant-description').value.trim();
            const model = document.getElementById('modal-assistant-model').value;
            const instructions = document.getElementById('modal-assistant-instructions').value.trim();
            const temperature = parseFloat(document.getElementById('modal-assistant-temperature').value);
            const maxTokens = parseInt(document.getElementById('modal-assistant-max-tokens').value, 10);
            const language = document.getElementById('modal-assistant-language')?.value || 'en';
            const selectedProvider = getSelectedAssistantProvider('modal-assistant-model', model);
            const collectionSelect = document.getElementById('modal-assistant-collections');
            const collectionsSelected = collectionSelect
                ? Array.from(collectionSelect.selectedOptions).map(opt => opt.value)
                : [];
            const metadata = buildAssistantProviderMetadata(selectedProvider);
        
            // Validation
            if (!name) {
                showNotification('Please enter an assistant name', 'error');
                return;
            }
        
            if (!model) {
                showNotification('Please select a model', 'error');
                return;
            }
        
            if (!Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
                showNotification('Temperature must be between 0 and 2', 'error');
                return;
            }
        
            if (!Number.isFinite(maxTokens) || maxTokens < 1 || maxTokens > 4000) {
                showNotification('Max tokens must be between 1 and 4000', 'error');
                return;
            }
        
            try {
                const response = await fetch('/v1/assistants/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        description: description || '',
                        instructions: instructions || 'You are a helpful assistant.',
                        model,
                        temperature,
                        max_tokens: maxTokens,
                        language,
                        collections: collectionsSelected,
                        metadata,
                    })
                });
        
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(error.detail || 'Failed to create assistant');
                }
        
                closeModal();
                document.getElementById('create-assistant-modal')?.classList.add('hidden');
                showNotification('✅ Assistant created successfully!', 'success');
                await loadAssistants();
            } catch (error) {
                showNotification('❌ Error creating assistant: ' + error.message, 'error');
            }
        }
        
        // ...existing code...


// =================================================================================
// ASSISTANT CHAT MODAL
// =================================================================================
async function showChatModal(assistantId, assistantName) {
    let isPayloadModalOpen = false;
    let chatMessages = [];
    let attachedFiles = [];
    let enabledFiles = [];
    /** Cache for binary file content (e.g. images) keyed by fileId — base64 data URL */
    let attachedFilesBase64 = {};
    currentThreadId = null;

    function isFileAttachedInChat(fileId) {
        return attachedFiles.some((entry) => {
            const entryId = typeof entry === 'object' ? entry.id : entry;
            return entryId === fileId;
        });
    }

    async function openKnowledgeFilePreview(fileId, fileName) {
        if (!fileId) {
            showNotification('Cannot preview file: missing file identifier.', 'error');
            return;
        }

        const safeName = fileName || fileId;
        createPayloadModal(
            `View · ${safeName}`,
            `
                <div style="display:flex; flex-direction:column; gap:10px;">
                    <div style="font-size:12px; color:var(--aw-gray, #6b6b68);">
                        Preview of the document content (first 4,000 characters).
                    </div>
                    <pre id="knowledge-preview-content" style="max-height:360px; overflow:auto; background:var(--gray-100, #f5f5f3); border:1px solid var(--gray-200, #e5e5e3); border-radius:8px; padding:10px; margin:0; white-space:pre-wrap; word-break:break-word;">Loading preview...</pre>
                    <div style="display:flex; justify-content:flex-end;">
                        <button id="knowledge-open-full-file-btn" class="btn btn-secondary" type="button">
                            <i class="fas fa-external-link-alt"></i> Open Full File in Files
                        </button>
                    </div>
                </div>
            `,
            [
                {
                    text: 'Close',
                    class: 'btn-secondary',
                    onclick: closePayloadModal
                }
            ],
            '760px'
        );

        const previewNode = document.getElementById('knowledge-preview-content');
        const openFullBtn = document.getElementById('knowledge-open-full-file-btn');

        try {
            const content = await getFileContent(fileId);
            const trimmed = (content || '').trim();
            if (!previewNode) return;

            if (!trimmed) {
                previewNode.textContent = 'Preview unavailable or file is empty.';
            } else {
                const maxPreviewChars = 4000;
                const truncated = trimmed.length > maxPreviewChars;
                previewNode.textContent = truncated
                    ? `${trimmed.slice(0, maxPreviewChars)}\n\n[Preview truncated. Use "Open Full File in Files" to view full content.]`
                    : trimmed;
            }
        } catch (error) {
            if (previewNode) {
                previewNode.textContent = `Unable to load preview: ${error.message}`;
            }
        }

        if (openFullBtn) {
            openFullBtn.onclick = async () => {
                closePayloadModal();
                closeModal();

                if (typeof switchMainSection === 'function') {
                    switchMainSection('files-section');
                }

                if (typeof loadFiles === 'function') {
                    await loadFiles();
                }

                const targetFile = availableFiles.find(f => f.id === fileId) || { id: fileId, filename: safeName };
                if (typeof openFilePreview === 'function') {
                    await openFilePreview(targetFile);
                } else {
                    showNotification('Files preview is not available in this context.', 'error');
                }
            };
        }
    }

    function attachKnowledgeFile(fileId, fileName) {
        if (attachedFiles.includes(fileId)) {
            showNotification('This file is already attached.', 'info');
            return;
        }
        attachedFiles.push(fileId);
        enabledFiles.push(fileId);
        renderFileList();
        showNotification(`Attached: ${fileName}`, 'success');
    }

    try {
        const threadResp = await fetch('/v1/threads/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assistant_id: assistantId })
        });
        if (!threadResp.ok) {
            throw new Error('Failed to create thread');
        }
        const threadData = await threadResp.json();
        currentThreadId = threadData.thread_id;
    } catch (error) {
        showNotification('❌ Failed to start chat thread: ' + error.message, 'error');
        return;
    }

    // Create modal
    const modal = createModal(`Chat · ${assistantName}`, `
        <div id="chat-header">
            <div id="knowledge-files-section">
                <button class="btn btn-outline" onclick="toggleKnowledgeFiles()" style="margin-bottom: 8px; font-size:12px;">
                    <i class="fas fa-folder-open"></i> Show Knowledge Files
                </button>
                <div id="knowledge-files-list" style="display:none; margin-top:8px;">
                    <!-- Knowledge files will be loaded here -->
                </div>
            </div>
        </div>
        <div id="chat-files-section" style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--aw-gray, #6b6b68);">Attached Files</span>
                <button id="attach-file-btn" class="btn btn-small" style="font-size:12px;">
                    <i class="fas fa-paperclip"></i> Attach
                </button>
            </div>
            <div id="chat-files-list" style="display: flex; flex-wrap: wrap; gap: 8px; min-height:0;">
                <!-- Files will be listed here -->
            </div>
        </div>
        <div id="chat-messages" style="height: 360px; margin-bottom: 14px; overflow-y: auto; overflow-x: hidden; padding: 8px; border: 1px solid var(--gray-200, #e5e5e3); border-radius: 8px; background: var(--card-bg, #fff); display: flex; flex-direction: column;"></div>
        <div id="chat-composer" style="position: sticky; bottom: 0; background: var(--modal-bg, var(--card-bg, #fff)); padding-top: 8px; margin-top: auto; z-index: 1;">
            <div style="margin-bottom: 10px;">
                <label for="show-payload-toggle" style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                    <input type="checkbox" id="show-payload-toggle" name="show_payload_preview" style="margin:0; accent-color: #c4622d;">
                    <span style="font-size:12px; color:var(--aw-gray, #6b6b68);">Show Payload Preview before sending</span>
                </label>
            </div>
            <div style="display: flex; gap: 8px; align-items: flex-end;">
            <textarea id="chat-input" style="flex: 1; padding: 10px 12px; resize: none; line-height:1.5;" placeholder="Type your message…" rows="3"></textarea>
            <button id="voice-btn" class="btn btn-secondary" title="Voice input" style="height:44px; width:44px; padding:0; flex-shrink:0; display:flex; align-items:center; justify-content:center;">
                <i class="fas fa-microphone"></i>
            </button>
            <button id="send-message-btn" class="btn btn-primary" style="height:44px; padding: 0 20px; flex-shrink:0;">Send</button>
            </div>
        </div>
    `, [
        {
            text: 'Load Chat',
            class: 'btn-secondary',
            onclick: showLoadChatModal
        },
        {
            text: 'Save Chat',
            class: 'btn-secondary',
            onclick: saveChat
        },
        {
            text: 'Close',
            class: 'btn-secondary',
            onclick: closeModal
        }
        // ...existing code...
    ], '600px');

    // Setup DOM references
    const sendBtn = document.getElementById('send-message-btn');
    const chatInput = document.getElementById('chat-input');
    const attachBtn = document.getElementById('attach-file-btn');
    const voiceBtn = document.getElementById('voice-btn');
    const chatMessagesDiv = document.getElementById('chat-messages');

    // Load assistant files
    loadChatFiles(assistantId);

    // --- File attachment logic ---
    if (attachBtn) {
        attachBtn.onclick = attachFileToChat;
    }

    // --- Send message logic ---
    if (sendBtn) {
        sendBtn.onclick = () => {
            if (!isPayloadModalOpen) sendChatMessage(assistantId);
        };
    }

    if (chatInput) {
        chatInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (!isPayloadModalOpen) sendChatMessage(assistantId);
            }
        });
    }

    // --- Voice recognition logic ---
    let recognition;
    let isListening = false;
    let lastFinalTranscript = '';
    if (voiceBtn && (window.SpeechRecognition || window.webkitSpeechRecognition)) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.lang = 'pt-BR';
        recognition.continuous = false;
        recognition.interimResults = true;

        recognition.onresult = function(event) {
            let finalTranscript = '';
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }
            chatInput.value = lastFinalTranscript + finalTranscript + interimTranscript;
            chatInput.focus();
            if (finalTranscript) {
                lastFinalTranscript += finalTranscript;
            }
        };
        recognition.onerror = function() {
            showNotification('Erro no reconhecimento de voz', 'error');
            voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
            voiceBtn.classList.remove('recording');
            isListening = false;
        };
        recognition.onend = function() {
            voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
            voiceBtn.classList.remove('recording');
            isListening = false;
            lastFinalTranscript = '';
        };
        voiceBtn.onclick = function(e) {
            e.preventDefault();
            if (isListening) {
                recognition.stop();
                voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
                voiceBtn.classList.remove('recording');
                isListening = false;
                lastFinalTranscript = '';
            } else {
                lastFinalTranscript = chatInput.value;
                recognition.start();
                voiceBtn.innerHTML = '<i class="fas fa-wave-square"></i>';
                voiceBtn.classList.add('recording');
                isListening = true;
            }
        };
    } else if (voiceBtn) {
        voiceBtn.disabled = true;
        voiceBtn.title = 'Reconhecimento de voz não suportado neste navegador';
    }

    // --- File list rendering ---
    function renderFileList() {
        const filesList = document.getElementById('chat-files-list');
        if (!filesList) return;

        filesList.innerHTML = '';

        attachedFiles.forEach(fileRef => {
            const fileId = typeof fileRef === 'object' ? fileRef.id : fileRef;
            const file = availableFiles.find(f => f.id === fileId) || fileRef;
            if (!file || !fileId) return;

            const fileName = file.filename || file.name || fileId;
            const isEnabled = enabledFiles.includes(fileId);
            const checkboxId = `file-${String(fileId).replace(/[^a-zA-Z0-9_-]/g, '_')}`;

            const fileItem = document.createElement('div');
            fileItem.className = 'file-item';
            fileItem.style = 'display: flex; align-items: center; background: var(--gray-100); padding: 5px 10px; border-radius: 4px;';
            fileItem.innerHTML = `
                <input type="checkbox" id="${checkboxId}" class="file-checkbox" data-fileid="${fileId}" ${isEnabled ? 'checked' : ''} style="margin-right: 8px;">
                <label for="${checkboxId}" style="margin-right: 8px;">${fileName}</label>
                <button class="btn btn-icon remove-file" data-fileid="${fileId}" style="padding: 2px 5px;">
                    <i class="fas fa-times"></i>
                </button>
            `;
            filesList.appendChild(fileItem);
        
            // Remove file logic
            fileItem.querySelector('.remove-file').addEventListener('click', (e) => {
                const removeId = e.currentTarget.dataset.fileid;
                attachedFiles = attachedFiles.filter(id => id !== removeId);
                enabledFiles = enabledFiles.filter(id => id !== removeId);
                renderFileList();
            });
        
            // Checkbox logic
            fileItem.querySelector('.file-checkbox').addEventListener('change', (e) => {
                const toggleId = e.target.dataset.fileid;
                if (e.target.checked) {
                    if (!enabledFiles.includes(toggleId)) enabledFiles.push(toggleId);
                } else {
                    enabledFiles = enabledFiles.filter(id => id !== toggleId);
                }
            });
        });
    }

    // --- File attachment helpers ---
    function attachFileToChat() {
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.style.display = 'none';
        fileInput.addEventListener('change', async (e) => {
            if (fileInput.files.length > 0) {
                const file = fileInput.files[0];
                await uploadFileForChat(file);
            }
        });
        document.body.appendChild(fileInput);
        fileInput.click();
    }

    async function uploadFileForChat(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('purpose', 'assistants');
        try {
            const response = await fetch('/v1/files', {
                method: 'POST',
                body: formData
            });
            if (response.ok) {
                const fileMeta = await response.json();
                attachedFiles.push(fileMeta.id);
                availableFiles.push(fileMeta);
                enabledFiles.push(fileMeta.id);

                // If this is an image, cache its base64 data for vision models
                const ct = (fileMeta.content_type || file.type || '').toLowerCase();
                if (isImageType(ct) || isImageExtension(file.name)) {
                    const reader = new FileReader();
                    reader.onload = function (e) {
                        attachedFilesBase64[fileMeta.id] = e.target.result;
                    };
                    reader.onerror = function () {
                        console.warn(`Failed to read image ${file.name} as base64`);
                    };
                    reader.readAsDataURL(file);
                }

                renderFileList();
                showNotification(`✅ ${file.name} attached to chat!`, 'success');
            } else {
                throw new Error('Upload failed');
            }
        } catch (error) {
            showNotification(`❌ Failed to attach file: ${error.message}`, 'error');
        }
    }

    /** Check if a MIME type is a browser-viewable image. */
    function isImageType(mime) {
        return ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/tiff'].includes(mime);
    }

    /** Fallback: check file extension when content_type is missing. */
    function isImageExtension(filename) {
        const ext = (filename || '').split('.').pop().toLowerCase();
        return ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff'].includes(ext);
    }

    async function getFileContent(fileId) {
        try {
            const file = availableFiles.find(f => f.id === fileId);
            if (!file) {
                console.warn(`File object not found for fileId: ${fileId}`);
                return "";
            }

            // Primary path: use physical_path via /v1/files/read
            if (file.physical_path) {
                const response = await fetch(`/v1/files/read?path=${encodeURIComponent(file.physical_path)}`);
                if (response.ok) {
                    const result = await response.json();
                    const content = result.content || result.extracted_text || "";
                    if (content) return content;
                } else if (response.status === 404) {
                    console.warn(`physical_path 404 for ${fileId}, trying content endpoint`);
                }
            }

            // Fallback: /v1/files/{id}/content — works even without physical_path
            const fallback = await fetch(`/v1/files/${fileId}/content`);
            if (fallback.ok) {
                const text = await fallback.text();
                return text;
            }

            console.warn(`All read attempts failed for ${fileId}`);
            return "";
        } catch (error) {
            console.error(`File fetch failed for ${fileId}:`, error);
            return "";
        }
    }

    async function loadChatFiles(assistantId) {
        try {
            // Get assistant info (to get file_ids)
            const assistant = await fetch(`/v1/assistants/${assistantId}`).then(r => r.json());
            const fileIds = assistant.file_ids || [];

            // Get all files metadata
            const allFilesResp = await fetch('/v1/files');
            const allFilesData = await allFilesResp.json();
            const allFiles = Array.isArray(allFilesData.data) ? allFilesData.data : (Array.isArray(allFilesData) ? allFilesData : []);
            availableFiles = allFiles;

            // Find file objects for attached files
            attachedFiles = allFiles.filter(f => fileIds.includes(f.id)).map(f => f.id);
            enabledFiles = [...attachedFiles];
            renderFileList();
        } catch (error) {
            console.error('Error loading assistant files:', error);
        }
    }

    // --- Chat sending logic ---
    // Place this inside your showChatModal function
    
    async function sendChatMessage(assistantId) {
        if (isPayloadModalOpen) return;
        isPayloadModalOpen = true;
        const assistant = availableAssistants.find(a => a.id === assistantId);
        const instructions = assistant && assistant.instructions ? assistant.instructions : "";
        const message = chatInput.value.trim();
        if (!message) {
            isPayloadModalOpen = false;
            return;
        }
    
        // Build file content for system prompt (text files only)
        // Image files are handled separately as vision content
        let fileContent = "";
        const imageDataList = [];
        const processAttachment = async (name, content) => {
            if (!content || content.trim() === "") {
                return `### FILE: ${name} ###\nFILE EMPTY OR UNREADABLE\n\n`;
            }
            return `### FILE: ${name} ###\n${content.substring(0, 2000)}\n\n`;
        };
        for (const fileId of enabledFiles) {
            const file = availableFiles.find(f => f.id === fileId);
            if (!file) continue;

            // Image file — use cached base64 data for vision models
            if (attachedFilesBase64[fileId]) {
                imageDataList.push(attachedFilesBase64[fileId]);
                continue;
            }

            // Text file — read content and add to system prompt
            try {
                const content = await getFileContent(fileId);
                fileContent += await processAttachment(file.filename, content);
            } catch (e) {
                fileContent += `### FILE: ${file.filename} ###\nERROR READING FILE\n\n`;
            }
        }

        const systemPrompt = (instructions && instructions.trim())
            ? `${instructions.trim()}\n\n### ATTACHED FILES ###\n${fileContent || (imageDataList.length ? 'See images in user message' : 'NO FILES ATTACHED')}`
            : `You are a helpful assistant. You have access to the following files:\n\n### ATTACHED FILES ###\n${fileContent || (imageDataList.length ? 'See images in user message' : 'NO FILES ATTACHED')}`;

        // Build chat history — include image data for vision models
        const userMsg = imageDataList.length > 0
            ? { role: 'user', content: message, images: imageDataList }
            : { role: 'user', content: message };
        const messages = [
            { role: 'system', content: systemPrompt },
            userMsg
        ];
    
        // Determine endpoint and payload — support local Ollama and external providers
        let apiUrl = '/v1/chat/completions';
        const payload = {
            assistant_id: assistantId,
            messages: messages,
            max_tokens: 2000,
            temperature: 0.1,
        };
        // Detect provider (metadata takes precedence over model heuristic)
        const modelId = assistant?.model || '';
        const storedProviderRaw = String(assistant?.metadata?.llm_provider || '').toLowerCase();
        const providerForModel = (
            storedProviderRaw === 'local' ? 'ollama' :
            (storedProviderRaw || inferAssistantProviderFromModel(modelId))
        );
        if (providerForModel !== 'ollama') {
            // Prompt for the key once per session via a small floating badge
            let storedKey = sessionStorage.getItem(`apikey_${providerForModel}`) || '';
            if (!storedKey) {
                storedKey = prompt(`Enter ${providerForModel.toUpperCase()} API key to use ${modelId}:`) || '';
                if (storedKey) sessionStorage.setItem(`apikey_${providerForModel}`, storedKey);
            }
            if (!storedKey) {
                showNotification(`API key required for ${providerForModel}`, 'error');
                isPayloadModalOpen = false;
                sendBtn.disabled = false;
                return;
            }
            payload.provider = providerForModel;
            payload.api_key  = storedKey;
            payload.model    = modelId;

            const metadataBaseUrl = String(assistant?.metadata?.llm_base_url || '').trim();
            const metadataFormat = String(assistant?.metadata?.llm_url_format || '').toLowerCase();
            if (metadataBaseUrl) {
                payload.base_url = metadataBaseUrl;
            } else if (modelId.startsWith('deepseek-v4-') && (providerForModel === 'openai' || providerForModel === 'anthropic')) {
                // Explicitly set DeepSeek base so URL format follows provider choice.
                payload.base_url = metadataFormat === 'openai'
                    ? _ASST_DEEPSEEK_BASE_URLS.openai
                    : (metadataFormat === 'anthropic'
                        ? _ASST_DEEPSEEK_BASE_URLS.anthropic
                        : _ASST_DEEPSEEK_BASE_URLS[providerForModel]);
            }
        }
    
        // Show payload modal if toggled
        const showPayload = document.getElementById('show-payload-toggle')?.checked;
        if (showPayload) {
            createPayloadModal(
                'Preview & Edit Payload',
                `<textarea id="payload-editor" style="width:100%;height:300px;">${JSON.stringify(payload, null, 2)}</textarea>`,
                [
                    {
                        text: 'Send',
                        class: 'btn-primary',
                        onclick: async () => {
                            let editedPayload;
                            try {
                                editedPayload = JSON.parse(document.getElementById('payload-editor').value);
                            } catch (e) {
                                showNotification('Invalid JSON in payload!', 'error');
                                return;
                            }
                            isPayloadModalOpen = false;
                            closePayloadModal();
                            await actuallySendChatMessage(apiUrl, editedPayload, message, chatMessagesDiv, sendBtn, chatInput);
                        }
                    },
                    {
                        text: 'Cancel',
                        class: 'btn-secondary',
                        onclick: () => {
                            isPayloadModalOpen = false;
                            closePayloadModal();
                        }
                    }
                ],
                '600px',
                () => {
                    isPayloadModalOpen = false;
                }
            );
        } else {
            await actuallySendChatMessage(apiUrl, payload, message, chatMessagesDiv, sendBtn, chatInput);
            isPayloadModalOpen = false;
        }
    }
    
    async function actuallySendChatMessage(apiUrl, payload, message, chatMessagesDiv, sendBtn, chatInput) {
            const userMessageDiv = document.createElement('div');
            userMessageDiv.style.cssText = 'margin-bottom: 15px; text-align: right;';
            userMessageDiv.innerHTML = `
                <div style="display: inline-block; background: var(--primary); color: white; padding: 10px 15px; border-radius: 18px; max-width: 70%; text-align: left;">
                    ${message}
                </div>
                <div style="font-size: 11px; color: var(--gray-400); margin-top: 5px;">You • ${new Date().toLocaleTimeString()}</div>
            `;
            chatMessagesDiv.appendChild(userMessageDiv);

            chatInput.value = '';
            sendBtn.disabled = true;

        const loadingDiv = document.createElement('div');
        loadingDiv.style.cssText = 'margin-bottom: 15px;';
        loadingDiv.innerHTML = `
            <div style="display: inline-block; background: var(--gray-200); padding: 10px 15px; border-radius: 18px; max-width: 70%;">
                <i class="fas fa-spinner fa-spin"></i> Thinking...
            </div>
        `;
        chatMessagesDiv.appendChild(loadingDiv);
        chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            let assistantContent;
            if (response.ok && data.choices && data.choices[0] && data.choices[0].message) {
                assistantContent = data.choices[0].message.content;
            } else if (response.ok && data.response) {
                assistantContent = data.response;
            } else {
                throw new Error(data.detail || 'No response from assistant');
            }
            const assistantMessageDiv = document.createElement('div');
            assistantMessageDiv.style.cssText = 'margin-bottom: 15px;';
            assistantMessageDiv.innerHTML = `
                <div style="display: inline-block; background: var(--card-bg); border: 1px solid var(--gray-200); padding: 10px 15px; border-radius: 18px; max-width: 70%;">
                    ${assistantContent}
                </div>
                <div style="font-size: 11px; color: var(--gray-400); margin-top: 5px;">Assistant • ${new Date().toLocaleTimeString()}</div>
            `;
            chatMessagesDiv.appendChild(assistantMessageDiv);
            if (chatMessagesDiv.contains(loadingDiv)) {
                chatMessagesDiv.removeChild(loadingDiv);
            }
            chatInput.value = '';
            chatInput.focus();
            sendBtn.disabled = false;
            sendBtn.innerHTML = 'Send';
            // Update chat history for context
            chatMessages.push(
                { role: 'user', content: message },
                { role: 'assistant', content: assistantContent }
            );
        } catch (error) {
            if (chatMessagesDiv.contains(loadingDiv)) {
                chatMessagesDiv.removeChild(loadingDiv);
            }
            const errorDiv = document.createElement('div');
            errorDiv.style.cssText = 'margin-bottom: 15px;';
            errorDiv.innerHTML = `
                <div style="display: inline-block; background: rgba(239, 71, 111, 0.1); border: 1px solid var(--danger); color: var(--danger); padding: 10px 15px; border-radius: 18px; max-width: 70%;">
                    ❌ Error: ${error.message}
                </div>
            `;
            chatMessagesDiv.appendChild(errorDiv);
        } finally {
            sendBtn.disabled = false;
            sendBtn.innerHTML = 'Send';
            chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
            chatInput.focus();
        }
    }
        // Toggle knowledge files visibility
        window.attachKnowledgeFileInModal = attachKnowledgeFile;
        window.isKnowledgeFileAttachedInModal = isFileAttachedInChat;
        window.viewKnowledgeFileInModal = openKnowledgeFilePreview;
        window.switchAssistantProvider    = switchAssistantProvider;

    // Save chat to localStorage
    function saveChat() {
        const chatData = {
            assistantId,
            timestamp: new Date().toISOString(),
            messages: chatMessages,
            files: attachedFiles
        };
        const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        savedChats.push(chatData);
        localStorage.setItem('savedChats', JSON.stringify(savedChats));
        showNotification('✅ Chat saved successfully!', 'success');
    }
}

    // Add these functions after the saveChat function
    
    function showLoadChatModal() {
        const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        
        if (savedChats.length === 0) {
            showNotification('No saved chats found', 'info');
            return;
        }
    
        let chatListHtml = '<div style="max-height: 400px; overflow-y: auto;">';
        
        savedChats.forEach((chat, index) => {
            const date = new Date(chat.timestamp).toLocaleString();
            const assistantName = availableAssistants.find(a => a.id === chat.assistantId)?.name || chat.assistantId;
            const messageCount = chat.messages.length;
            const preview = chat.messages.length > 0 ? chat.messages[0].content.substring(0, 100) : 'No messages';
            
            chatListHtml += `
                <div class="saved-chat-item" style="
                    border: 1px solid var(--gray-200); 
                    border-radius: 8px; 
                    padding: 15px; 
                    margin-bottom: 10px; 
                    cursor: pointer;
                    transition: var(--transition);
                " onclick="loadSavedChat(${index})">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                        <div>
                            <strong style="color: var(--primary);">${assistantName}</strong>
                            <div style="font-size: 12px; color: var(--gray-400);">${date}</div>
                        </div>
                        <div style="display: flex; gap: 5px;">
                            <button class="btn btn-icon" onclick="exportSavedChat(${index}); event.stopPropagation();" title="Export Chat">
                                <i class="fas fa-download"></i>
                            </button>
                            <button class="btn btn-icon" onclick="deleteSavedChatFromModal(${index}); event.stopPropagation();" title="Delete Chat" style="color: var(--danger);">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div style="font-size: 14px; color: var(--gray-600);">
                        ${messageCount} message${messageCount !== 1 ? 's' : ''}
                    </div>
                    <div style="font-size: 12px; color: var(--gray-400); margin-top: 5px; font-style: italic;">
                        "${preview}${preview.length >= 100 ? '...' : ''}"
                    </div>
                </div>
            `;
        });
            
        createModal('Load Saved Chat', chatListHtml, [
            {
                text: 'Cancel',
                class: 'btn-secondary',
                onclick: closeModal
            }
        ], '600px');
    }
    
    function loadSavedChat(chatIndex) {
        const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        const savedChat = savedChats[chatIndex];
        
        if (!savedChat) {
            showNotification('Chat not found', 'error');
            return;
        }
    
        // Find the assistant
        const assistant = availableAssistants.find(a => a.id === savedChat.assistantId);
        if (!assistant) {
            showNotification('Assistant not found. The assistant may have been deleted.', 'error');
            return;
        }
    
        // Close the load modal
        closeModal();
        
        // Set the attached files from the saved chat
        attachedFiles = [...(savedChat.files || [])];
        
        // Show the chat modal with the assistant
        showChatModal(savedChat.assistantId, assistant.name);
        
        // Wait a moment for the modal to render, then load the messages
        setTimeout(() => {
            loadChatHistory(savedChat.messages);
            showNotification(`Loaded chat with ${savedChat.messages.length} messages`, 'success');
        }, 100);
    }
    
    function loadChatHistory(messages) {
        const chatMessagesDiv = document.getElementById('chat-messages');
        if (!chatMessagesDiv) return;
        
        // Clear existing messages
        chatMessagesDiv.innerHTML = '';
        
        // Add each message to the chat
        messages.forEach((message, index) => {
            const messageDiv = document.createElement('div');
            messageDiv.style.cssText = 'margin-bottom: 15px;';
            
            if (message.role === 'user') {
                messageDiv.style.textAlign = 'right';
                messageDiv.innerHTML = `
                    <div style="display: inline-block; background: var(--primary); color: white; padding: 10px 15px; border-radius: 18px; max-width: 70%; text-align: left;">
                        ${message.content}
                    </div>
                    <div style="font-size: 11px; color: var(--gray-400); margin-top: 5px;">You</div>
                `;
            } else if (message.role === 'assistant') {
                messageDiv.innerHTML = `
                    <div style="display: inline-block; background: var(--card-bg); border: 1px solid var(--gray-200); padding: 10px 15px; border-radius: 18px; max-width: 70%;">
                        ${message.content}
                    </div>
                    <div style="font-size: 11px; color: var(--gray-400); margin-top: 5px;">Assistant</div>
                `;
            }
            
            chatMessagesDiv.appendChild(messageDiv);
        });
        
        // Update the global chat messages array
        chatMessages = [...messages];
        
        // Scroll to the bottom
        chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
        
        // Update the attached files list display
        renderFileList();
    }
    
    function deleteSavedChatFromModal(chatIndex) {
        if (!confirm('Are you sure you want to delete this saved chat?')) {
            return;
        }
        
        let savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        savedChats.splice(chatIndex, 1);
        localStorage.setItem('savedChats', JSON.stringify(savedChats));
        
        showNotification('Chat deleted successfully', 'success');
        
        // Refresh the modal
        closeModal();
        setTimeout(() => showLoadChatModal(), 100);
    }
    
    function exportSavedChat(chatIndex) {
        const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        const chat = savedChats[chatIndex];
        
        if (!chat) {
            showNotification('Chat not found', 'error');
            return;
        }
        
        const assistant = availableAssistants.find(a => a.id === chat.assistantId);
        const assistantName = assistant ? assistant.name : chat.assistantId;
        const timestamp = new Date(chat.timestamp).toISOString().replace(/[:.]/g, '-');
        
        // Create a readable export format
        const exportData = {
            metadata: {
                assistantId: chat.assistantId,
                assistantName: assistantName,
                timestamp: chat.timestamp,
                messageCount: chat.messages.length,
                exportedAt: new Date().toISOString()
            },
            messages: chat.messages,
            files: chat.files || []
        };
        
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportData, null, 2));
        const dlAnchor = document.createElement('a');
        dlAnchor.setAttribute("href", dataStr);
        dlAnchor.setAttribute("download", `chat_${assistantName}_${timestamp}.json`);
        document.body.appendChild(dlAnchor);
        dlAnchor.click();
        document.body.removeChild(dlAnchor);
        
        showNotification('Chat exported successfully', 'success');
    }
    
    // Add CSS for hover effects on saved chat items
    function addSavedChatStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .saved-chat-item:hover {
                background-color: var(--gray-100) !important;
                border-color: var(--primary) !important;
                transform: translateY(-2px);
                box-shadow: var(--shadow-md);
            }
            
            .saved-chat-item .btn-icon {
                opacity: 0.6;
                transition: opacity 0.2s ease;
            }
            
            .saved-chat-item:hover .btn-icon {
                opacity: 1;
            }
        `;
        document.head.appendChild(style);
    }
    
    // Call this when the page loads
    document.addEventListener('DOMContentLoaded', function() {
        addSavedChatStyles();
        // ...existing initialization code...
    });
    
        // ...existing code...
        
        async function showEditAssistantModal(assistantId) {
            const assistant = availableAssistants.find(a => a.id === assistantId);
            if (!assistant) {
                showNotification('Assistant not found', 'error');
                return;
            }
        
            if (!availableFiles.length) {
                try {
                    const resp = await fetch('/v1/files');
                    const data = await resp.json();
                    availableFiles = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : []);
                } catch (error) {
                    console.warn('Unable to load files before editing assistant:', error);
                }
            }
        
            if (!availableTools.length && typeof loadTools === 'function') {
                try {
                    await loadTools();
                } catch (error) {
                    console.warn('Unable to load tools before editing assistant:', error);
                }
            }
        
            if (!collections.length && typeof loadCollectionsData === 'function') {
                try {
                    await loadCollectionsData({ showLoader: false });
                } catch (error) {
                    console.warn('Unable to load collections before editing assistant:', error);
                }
            }
        
            const languageOptions = SUPPORTED_ASSISTANT_LANGUAGES.map(lang => `
                <option value="${lang.value}" ${assistant.language === lang.value ? 'selected' : ''}>
                    ${lang.label}
                </option>
            `).join('');
        
            const filesOptions = availableFiles.length
                ? availableFiles.map(file => `
                    <option value="${file.id}" ${assistant.file_ids?.includes(file.id) ? 'selected' : ''}>
                        ${file.filename || file.id}
                    </option>
                `).join('')
                : '<option disabled>No files uploaded</option>';
        
            const assistantToolIds = (assistant.tools || []).map(tool => {
                if (typeof tool === 'string') return tool;
                return tool.function?.name || tool.id;
            });
        
            const toolsOptions = availableTools.length
                ? availableTools.map(tool => {
                    const toolId = tool.function?.name || tool.id;
                    return `<option value="${toolId}" ${assistantToolIds.includes(toolId) ? 'selected' : ''}>
                        ${tool.function?.name || 'Unnamed Tool'}
                    </option>`;
                }).join('')
                : '<option disabled>No tools available</option>';
        
            const collectionsOptions = collections.length
                ? collections.map(col => `
                    <option value="${col.name}" ${assistant.collections?.includes(col.name) ? 'selected' : ''}>
                        ${col.name}
                    </option>
                `).join('')
                : '<option disabled>No collections available</option>';
        
            const initialProvider = assistant?.metadata?.llm_provider || inferAssistantProviderFromModel(assistant.model || '');

            createModal('Edit Assistant', `
                <div class="parameter-group">
                    <label for="modal-edit-assistant-name">Assistant Name *</label>
                    <input type="text" id="modal-edit-assistant-name" name="assistant_name" style="width: 100%;" 
                           value="${assistant.name || ''}" required>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-description">Description</label>
                    <textarea id="modal-edit-assistant-description" name="assistant_description" style="width: 100%; height: 80px;">${assistant.description || ''}</textarea>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-model">Model *</label>
                    ${buildAssistantProviderPicker('modal-edit-assistant-model', assistant.model, initialProvider)}
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-instructions">Instructions</label>
                    <textarea id="modal-edit-assistant-instructions" name="assistant_instructions" style="width: 100%; height: 120px;">${assistant.instructions || ''}</textarea>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-language">Language</label>
                    <select id="modal-edit-assistant-language" name="assistant_language" style="width: 100%;">
                        ${languageOptions}
                    </select>
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Preferred language for responses
                    </small>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-collections">Collections</label>
                    <select id="modal-edit-assistant-collections" name="assistant_collections" multiple style="width: 100%; height: 120px;">
                        ${collectionsOptions}
                    </select>
                    <small style="color: var(--gray-400); margin-top: 4px; display: block;">
                        Qdrant collections for knowledge base
                    </small>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-temperature">Temperature</label>
                    <input type="number" id="modal-edit-assistant-temperature" name="assistant_temperature" 
                           value="${assistant.temperature ?? 0.7}" step="0.1" min="0" max="2" style="width: 100%;">
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-max-tokens">Max Tokens</label>
                    <input type="number" id="modal-edit-assistant-max-tokens" name="assistant_max_tokens" 
                           value="${assistant.max_tokens ?? 500}" min="1" max="4000" style="width: 100%;">
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-files">Files</label>
                    <select id="modal-edit-assistant-files" name="assistant_files" multiple style="width: 100%; height: 120px;">
                        ${filesOptions}
                    </select>
                </div>
                
                <div class="parameter-group">
                    <label for="modal-edit-assistant-tools">Tools</label>
                    <select id="modal-edit-assistant-tools" name="assistant_tools" multiple style="width: 100%; height: 120px;">
                        ${toolsOptions}
                    </select>
                </div>
            `, [
                {
                    text: 'Save',
                    class: 'btn-primary',
                    onclick: () => saveEditAssistant(assistantId)
                },
                {
                    text: 'Cancel',
                    class: 'btn-secondary',
                    onclick: closeModal
                }
            ], '650px');
        }
        
        // ...existing code...
        
        async function saveEditAssistant(assistantId) {
            const name = document.getElementById('modal-edit-assistant-name').value.trim();
            const description = document.getElementById('modal-edit-assistant-description').value.trim();
            const model = document.getElementById('modal-edit-assistant-model').value;
            const instructions = document.getElementById('modal-edit-assistant-instructions').value.trim();
            const temperature = parseFloat(document.getElementById('modal-edit-assistant-temperature').value);
            const maxTokens = parseInt(document.getElementById('modal-edit-assistant-max-tokens').value, 10);
            const language = document.getElementById('modal-edit-assistant-language')?.value || 'en';
            const filesSelect = document.getElementById('modal-edit-assistant-files');
            const toolsSelect = document.getElementById('modal-edit-assistant-tools');
            const collectionsSelect = document.getElementById('modal-edit-assistant-collections');
            const selectedProvider = getSelectedAssistantProvider('modal-edit-assistant-model', model);
            const currentAssistant = availableAssistants.find(a => a.id === assistantId) || {};
            const metadata = buildAssistantProviderMetadata(selectedProvider, currentAssistant.metadata || {});
        
            // Validation
            if (!name) {
                showNotification('Please enter an assistant name', 'error');
                return;
            }
            if (!model) {
                showNotification('Please select a model', 'error');
                return;
            }
            if (!Number.isFinite(maxTokens) || maxTokens < 1 || maxTokens > 4000) {
                showNotification('Max tokens must be between 1 and 4000', 'error');
                return;
            }
        
            const fileIds = filesSelect ? Array.from(filesSelect.selectedOptions).map(opt => opt.value) : [];
            const toolIds = toolsSelect ? Array.from(toolsSelect.selectedOptions).map(opt => opt.value) : [];
            const selectedCollections = collectionsSelect 
                ? Array.from(collectionsSelect.selectedOptions).map(opt => opt.value) 
                : [];
        
            // Convert tool IDs to proper tool objects
            const tools = toolIds.map(toolId => {
                const tool = availableTools.find(t => (t.function?.name || t.id) === toolId);
                if (tool) {
                    return {
                        type: tool.type || 'function',
                        function: tool.function
                    };
                }
                return {
                    type: 'function',
                    function: {
                        name: toolId,
                        description: '',
                        parameters: {
                            type: 'object',
                            properties: {},
                            required: []
                        }
                    }
                };
            });
        
            try {
                const response = await fetch(`/v1/assistants/${assistantId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        description,
                        model,
                        instructions,
                        temperature,
                        max_tokens: maxTokens,
                        language,
                        collections: selectedCollections,
                        file_ids: fileIds,
                        tools,
                        metadata,
                    })
                });
        
                const payload = await response.json().catch(() => null);
                if (!response.ok) {
                    throw new Error(payload?.detail || payload?.error || 'Failed to update assistant');
                }
        
                const updatedAssistant = payload?.data || payload;
                if (updatedAssistant?.id) {
                    selectedAssistant = updatedAssistant;
                }
        
                showNotification('✅ Assistant updated successfully!', 'success');
                closeModal();
                document.getElementById('create-assistant-modal')?.classList.add('hidden');
                await loadAssistants();
            } catch (error) {
                showNotification(`❌ Failed to update assistant: ${error.message}`, 'error');
            }
        }
        
        // ...existing code...

// Add this helper for a "stacked" payload modal:
function createPayloadModal(title, content, buttons = [], width = '500px', onClose = null) {
    // Remove existing payload modal only (not the main chat modal)
    const existingPayloadModal = document.querySelector('.modal.payload-modal');
    if (existingPayloadModal) existingPayloadModal.remove();

    const modal = document.createElement('div');
    modal.className = 'modal runtime-modal payload-modal';

    const dismissModal = () => {
        const activeModal = document.querySelector('.modal.payload-modal');
        if (activeModal) activeModal.remove();
        if (typeof onClose === 'function') {
            onClose();
        }
    };

    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            dismissModal();
        }
    });

    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content';
    modalContent.style.width = width;
    modalContent.innerHTML = `
        <div class="modal-header">
            <h2>${title}</h2>
            <button class="modal-close-btn" title="Close">&#x2715;</button>
        </div>
        <div class="modal-body">${content}</div>
        <div class="modal-footer">
            ${buttons.map(btn => `<button class="btn ${btn.class}">${btn.text}</button>`).join('')}
        </div>
    `;
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    // Add button event listeners
    const buttonElements = modalContent.querySelectorAll('.modal-footer .btn');
    buttons.forEach((btn, index) => {
        if (buttonElements[index] && btn.onclick) {
            buttonElements[index].onclick = btn.onclick;
        }
    });

    const closeBtn = modalContent.querySelector('.modal-close-btn');
    if (closeBtn) {
        closeBtn.onclick = dismissModal;
    }

    return modal;
}
function closePayloadModal() {
    const modal = document.querySelector('.modal.payload-modal');
    if (modal) modal.remove();
}

// Global variables for tools management
if (!('selectedTool' in window)) {
    window.selectedTool = null;
}
if (!('currentToolId' in window)) {
    window.currentToolId = null;
}

// Initialize tools
async function loadTools() {
    const toolsList = document.getElementById('tools-list');
    toolsList.innerHTML = '<div class="loading">Loading tools...</div>';
    
    try {
        const response = await fetch('/v1/tools');
        const data = await response.json();
        console.log('API response:', data);
        availableTools = data.data || [];
        
        if (availableTools.length === 0) {
            toolsList.innerHTML = '<div class="empty-state">No tools found</div>';
            return;
        }
        
        toolsList.innerHTML = '';
        availableTools.forEach(tool => {
            const toolEl = document.createElement('div');
            toolEl.className = 'tool-item';
            toolEl.innerHTML = `
                <div class="tool-name">${tool.function?.name || 'Unnamed Tool'}</div>
                <div class="tool-desc">${tool.function?.description || ''}</div>
            `;
            toolEl.addEventListener('click', () => selectTool(tool));
            toolsList.appendChild(toolEl);
        });
    } catch (error) {
        toolsList.innerHTML = '<div class="error">Failed to load tools</div>';
        console.error('Error loading tools:', error);
    }
}


function showSavedChatsModal() {
    const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
    if (!savedChats.length) {
        createModal('Saved Chats', '<div>No saved chats found.</div>', [
            { text: 'Close', class: 'btn-secondary', onclick: closeModal }
        ]);
        return;
    }
    let content = '<ul style="list-style:none;padding:0;">';
    savedChats.forEach((chat, idx) => {
        content += `
            <li style="margin-bottom:18px;">
                <strong>Assistant:</strong> ${chat.assistantId} <br>
                <strong>Date:</strong> ${new Date(chat.timestamp).toLocaleString()}<br>
                <button class="btn btn-small" onclick="viewSavedChat(${idx})">View</button>
            </li>
        `;
    });
    content += '</ul>';
    createModal('Saved Chats', content, [
        { text: 'Close', class: 'btn-secondary', onclick: closeModal }
    ], '600px');
}

function viewSavedChat(idx) {
    const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
    const chat = savedChats[idx];
    if (!chat) return;
    let content = `<div><strong>Assistant:</strong> ${chat.assistantId}<br><strong>Date:</strong> ${new Date(chat.timestamp).toLocaleString()}</div><hr>`;
    chat.messages.forEach(msg => {
        content += `<div style="margin-bottom:10px;"><b>${msg.role}:</b> <pre style="white-space:pre-wrap;">${msg.content}</pre></div>`;
    });
    createModal('Chat Details', content, [
        {
            text: 'Export',
            class: 'btn-primary',
            onclick: () => exportSavedChat(idx)
        },
        {
            text: 'Delete',
            class: 'btn-danger',
            onclick: () => deleteSavedChat(idx)
        },
        { text: 'Close', class: 'btn-secondary', onclick: closeModal }
    ], '600px');

    function exportSavedChat(idx) {
        const savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        const chat = savedChats[idx];
        if (!chat) return;
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(chat, null, 2));
        const dlAnchor = document.createElement('a');
        dlAnchor.setAttribute("href", dataStr);
        dlAnchor.setAttribute("download", `chat_${chat.assistantId}_${chat.timestamp}.json`);
        document.body.appendChild(dlAnchor);
        dlAnchor.click();
        document.body.removeChild(dlAnchor);
    }
 
    function deleteSavedChat(idx) {
        let savedChats = JSON.parse(localStorage.getItem('savedChats') || '[]');
        if (!confirm('Delete this saved chat?')) return;
        savedChats.splice(idx, 1);
        localStorage.setItem('savedChats', JSON.stringify(savedChats));
        closeModal();
        showSavedChatsModal();
    }}

const SUPPORTED_ASSISTANT_LANGUAGES = [
    { value: 'en', label: 'English' },
    { value: 'pt', label: 'Portuguese (Português)' },
    { value: 'es', label: 'Spanish (Español)' },
    { value: 'it', label: 'Italian (Italiano)' },
    { value: 'de', label: 'German (Deutsch)' },
    { value: 'fr', label: 'French (Français)' },
    { value: 'zh', label: 'Chinese (中文)' },
    { value: 'ja', label: 'Japanese (日本語)' },
];

document.addEventListener('DOMContentLoaded', setupAssistantsSection);

function setupAssistantsSection() {
    if (assistantEventsBound) return;
    assistantEventsBound = true;

    document.getElementById('create-assistant-btn')?.addEventListener('click', showCreateAssistantModal);
    document.getElementById('refresh-assistants-btn')?.addEventListener('click', loadAssistants);

    document.querySelector('[data-section="assistants-section"]')?.addEventListener('click', () => {
        loadAssistants();
    });

    loadAssistants();
}

    function updateSelectedAssistantLabel() {
        const label = document.getElementById('selected-assistant-label');
        label.textContent = selectedAssistant ? `Active: ${selectedAssistant.name}` : 'No Assistant Selected';
    }

// ...existing code...
function updateAssignedToolsList() {
    const assignedList = document.getElementById('assigned-tools-list');
    if (!assignedList) return;

    assignedList.innerHTML = '';
    if (!selectedAssistant) {
        assignedList.innerHTML = '<div style="color:var(--gray-400);padding:8px;">No assistant selected.</div>';
        return;
    }

    // Extract tool IDs from tool objects
    const assignedToolIds = (selectedAssistant.tools || []).map(tool => {
        if (typeof tool === 'string') return tool;
        return tool.function?.name || tool.id;
    });

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

// Add this function if it doesn't exist:
async function deleteAssistant(assistantId) {
    if (!confirm(`Are you sure you want to delete assistant ${assistantId}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/v1/assistants/${assistantId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete assistant');
        }
        
        // Refresh the assistants list
        if (typeof loadAssistants === 'function') {
            await loadAssistants();
        }
        
        // Clear selection if deleted assistant was selected
        if (typeof selectedAssistant !== 'undefined' && selectedAssistant?.id === assistantId) {
            selectedAssistant = null;
            if (typeof clearAssistantForm === 'function') {
                clearAssistantForm();
            }
        }
        
        console.log(`✅ Assistant ${assistantId} deleted`);
        
    } catch (error) {
        console.error('Error deleting assistant:', error);
        alert(`Failed to delete assistant: ${error.message}`);
    }
}

// Make sure it's globally accessible
window.deleteAssistant = deleteAssistant;