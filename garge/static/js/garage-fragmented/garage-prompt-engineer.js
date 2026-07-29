// ===== GLOBAL STATE FOR PROMPT ENGINEER =====
let promptEngineerState = {
    model: 'deepseek-v4-pro',
    apiEndpoint: '/v1/assistants/deepseek-stream-proxy',
    useVectorStore: true,
    useFiles: false,
    useRefPrompts: false,
    useAssistant: false,
    currentAssistant: null,
    currentCollection: '',
    attachedFiles: [],
    templates: [],
    history: [],
    currentPrompt: '',
    promptHistory: [],
    assistants: [],
    metrics: {
        clarity: 8,
        specificity: 7,
        creativity: 6,
        conciseness: 7
    },
    qualityScore: 0,
    currentVersion: 0,
    isGenerating: false,
    // NEW: Track context sources used in last generation
    lastGenerationContext: {
        vectorStoreUsed: false,
        collectionName: '',
        vectorResults: [],
        filesUsed: [],
        fileContents: [],
        temperature: 0.7,
        maxTokens: 2000,
        systemPrompt: '',
        fullPromptSent: ''
    }
};

let promptEngineerEventsBound = false;

// ===== UTILITY FUNCTIONS =====

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
    
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `notification-toast notification-${type}`;
    toast.innerHTML = `
        <span>${escapeHtml(message)}</span>
        <button class="notification-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    const bgColors = {
        error: '#dc3545',
        success: '#28a745',
        info: '#17a2b8',
        warning: '#ffc107'
    };
    
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 40px 12px 20px;
        border-radius: 8px;
        background: ${bgColors[type] || bgColors.info};
        color: ${type === 'warning' ? '#212529' : 'white'};
        z-index: 10000;
        max-width: 400px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;
    
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

async function getApiErrorMessage(response) {
    const fallback = `HTTP ${response.status}`;
    const payload = await response.json().catch(() => null);
    if (!payload) return fallback;

    const detail = payload.detail ?? payload.error ?? payload.message ?? payload;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object') {
        if (typeof detail.message === 'string' && detail.message.trim()) return detail.message;
        if (typeof detail.error === 'string' && detail.error.trim()) return detail.error;
        if (typeof detail.details === 'string' && detail.details.trim()) return detail.details;
        return JSON.stringify(detail);
    }
    return fallback;
}

async function ensureQdrantConnection() {
    const response = await fetch('/v1/qdrant/connect', { method: 'POST' });
    if (!response.ok) {
        const message = await getApiErrorMessage(response);
        throw new Error(message);
    }
    return true;
}

// ===== INITIALIZATION =====

document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('prompt-engineer-section')) {
        setupPromptEngineerSection();
    }
});

function setupPromptEngineerSection() {
    if (promptEngineerEventsBound) return;
    promptEngineerEventsBound = true;

    bindPromptEngineerEvents();
    loadCollectionsForPromptEngineer();
    loadTemplates();
    loadPromptHistory();
    updatePromptEngineerUI();
}

function bindPromptEngineerEvents() {
    // Context source toggles
    document.getElementById('pe-use-vector-store')?.addEventListener('change', function(e) {
        promptEngineerState.useVectorStore = e.target.checked;
        const config = document.getElementById('pe-vector-config');
        if (config) {
            config.style.display = e.target.checked ? 'block' : 'none';
        }
    });

    document.getElementById('pe-use-files')?.addEventListener('change', function(e) {
        promptEngineerState.useFiles = e.target.checked;
        const config = document.getElementById('pe-files-config');
        if (config) {
            config.style.display = e.target.checked ? 'block' : 'none';
        }
    });

    document.getElementById('pe-use-ref-prompts')?.addEventListener('change', function(e) {
        promptEngineerState.useRefPrompts = e.target.checked;
        const config = document.getElementById('pe-ref-prompts-config');
        if (config) {
            config.style.display = e.target.checked ? 'block' : 'none';
        }
    });

    // Collection selection
    document.getElementById('pe-collection-select')?.addEventListener('change', function(e) {
        promptEngineerState.currentCollection = e.target.value;
    });

    // File management
    document.getElementById('pe-add-files')?.addEventListener('click', () => {
        document.getElementById('pe-file-input').click();
    });

    document.getElementById('pe-clear-files')?.addEventListener('click', clearAttachedFiles);
    document.getElementById('pe-file-input')?.addEventListener('change', handleFileUpload);

    // Template management
    document.getElementById('pe-new-template')?.addEventListener('click', createNewTemplate);
    document.getElementById('pe-import-template')?.addEventListener('click', importTemplate);
    document.getElementById('pe-load-examples')?.addEventListener('click', loadPromptExamples);

    // Voice recognition button
    document.getElementById('pe-voice-btn')?.addEventListener('click', toggleVoiceRecording);
    
    // Initialize voice recognition on load
    initVoiceRecognition();
    
    // Quality metrics sliders
    const metrics = ['clarity', 'specificity', 'creativity', 'conciseness'];
    metrics.forEach(metric => {
        const slider = document.getElementById(`pe-metric-${metric}`);
        const valueSpan = document.getElementById(`pe-${metric}-value`);
        
        if (slider && valueSpan) {
            slider.addEventListener('input', function(e) {
                const value = e.target.value;
                valueSpan.textContent = value;
                promptEngineerState.metrics[metric] = parseInt(value);
            });
        }
    });

    // Quick action buttons
    document.getElementById('pe-analyze-needs')?.addEventListener('click', analyzeNeeds);
    document.getElementById('pe-generate-variations')?.addEventListener('click', generateVariations);
    document.getElementById('pe-optimize-prompt')?.addEventListener('click', optimizePrompt);
    document.getElementById('pe-evaluate-prompt')?.addEventListener('click', evaluatePrompt);
    document.getElementById('pe-suggest-improvements')?.addEventListener('click', suggestImprovements);

    // Prompt actions
    document.getElementById('pe-copy-prompt')?.addEventListener('click', copyGeneratedPrompt);
    document.getElementById('pe-format-prompt')?.addEventListener('click', formatPrompt);
    document.getElementById('pe-save-prompt')?.addEventListener('click', saveCurrentPrompt);
    document.getElementById('pe-execute-generate')?.addEventListener('click', generateOrRefinePrompt);
    document.getElementById('pe-export-markdown')?.addEventListener('click', exportPromptToMarkdown);
    document.getElementById('pe-export-clean')?.addEventListener('click', exportCleanPrompt);

    
    // History management
    document.getElementById('pe-load-version')?.addEventListener('click', loadPromptVersion);
    document.getElementById('pe-compare-versions')?.addEventListener('click', comparePromptVersions);
    document.getElementById('pe-clear-history')?.addEventListener('click', clearPromptHistory);

    // Preview tabs
    document.querySelectorAll('.preview-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            const target = this.dataset.target;
            showPreviewTab(target);
        });
    });

    // Advanced settings toggle
    const settingsToggle = document.querySelector('.settings-toggle');
    const settingsContent = document.querySelector('.settings-content');
    if (settingsToggle && settingsContent) {
        settingsToggle.addEventListener('click', function() {
            const isVisible = settingsContent.style.display === 'block';
            settingsContent.style.display = isVisible ? 'none' : 'block';
            const icon = this.querySelector('.toggle-icon');
            if (icon) {
                icon.className = isVisible ? 'fas fa-chevron-down toggle-icon' : 'fas fa-chevron-up toggle-icon';
            }
        });
    }

    // Advanced settings controls
    document.getElementById('pe-temperature')?.addEventListener('input', function(e) {
        document.getElementById('pe-temperature-value').textContent = e.target.value;
    });

    document.getElementById('pe-top-p')?.addEventListener('input', function(e) {
        document.getElementById('pe-top-p-value').textContent = e.target.value;
    });

    document.getElementById('pe-frequency-penalty')?.addEventListener('input', function(e) {
        document.getElementById('pe-frequency-penalty-value').textContent = e.target.value;
    });

    // Prompt input auto-save
    let promptSaveTimeout;
    document.getElementById('pe-generated-prompt')?.addEventListener('input', function() {
        clearTimeout(promptSaveTimeout);
        promptSaveTimeout = setTimeout(() => {
            promptEngineerState.currentPrompt = this.value;
            updatePromptDetails();
        }, 500);
    });

    document.getElementById('pe-generated-prompt')?.addEventListener('input', calculateTokenCount);

    // Assistant selection
    document.getElementById('pe-assistant-select')?.addEventListener('change', function(e) {
        const assistantId = e.target.value;
        if (assistantId) {
            const option = e.target.selectedOptions[0];
            promptEngineerState.useAssistant = true;
            promptEngineerState.currentAssistant = {
                id: assistantId,
                model: option.dataset.model,
                instructions: option.dataset.instructions,
                collections: JSON.parse(option.dataset.collections || '[]')
            };
            
            if (option.dataset.model) {
                promptEngineerState.model = option.dataset.model;
            }
            
            const collections = JSON.parse(option.dataset.collections || '[]');
            if (collections.length > 0) {
                document.getElementById('pe-collection-select').value = collections[0];
                promptEngineerState.currentCollection = collections[0];
                document.getElementById('pe-use-vector-store').checked = true;
                promptEngineerState.useVectorStore = true;
            }
            
            showNotification(`Assistant "${option.textContent}" selected`, 'success');
        } else {
            promptEngineerState.useAssistant = false;
            promptEngineerState.currentAssistant = null;
        }
    });
}

// ===== DATA LOADING FUNCTIONS =====

async function loadCollectionsForPromptEngineer() {
    try {
        await ensureQdrantConnection();
        const collectionsResponse = await fetch('/v1/qdrant/collections');
        if (!collectionsResponse.ok) {
            const message = await getApiErrorMessage(collectionsResponse);
            console.error('❌ Failed to load collections:', message);
            showNotification(`Collections unavailable: ${message}`, 'warning');
        } else {
            const data = await collectionsResponse.json();
            const select = document.getElementById('pe-collection-select');
            if (select) {
                select.innerHTML = '<option value="">Select collection...</option>';
                if (data.collections && data.collections.length > 0) {
                    data.collections.forEach(col => {
                        const option = document.createElement('option');
                        option.value = col.name;
                        option.textContent = `${col.name} (${col.vectors_count || 0} vectors)`;
                        select.appendChild(option);
                    });
                }
            }
        }

        await loadLocalAssistants();
        
    } catch (error) {
        const message = error?.message || String(error);
        console.error('Error loading collections/assistants:', message);
        showNotification(`Failed to load collections or assistants: ${message}`, 'error');
    }
}

async function loadLocalAssistants() {
    try {
        const response = await fetch('/v1/assistants');
        if (!response.ok) {
            throw new Error('Failed to fetch assistants');
        }
        
        const data = await response.json();
        const assistants = data.data || [];
        
        const assistantSelect = document.getElementById('pe-assistant-select');
        if (assistantSelect) {
            assistantSelect.innerHTML = '<option value="">No Assistant (Direct Model)</option>';
            assistants.forEach(assistant => {
                const option = document.createElement('option');
                option.value = assistant.id;
                option.textContent = `${assistant.name || assistant.id}`;
                option.dataset.model = assistant.model;
                option.dataset.instructions = assistant.instructions || '';
                option.dataset.collections = JSON.stringify(assistant.metadata?.collections || []);
                assistantSelect.appendChild(option);
            });
        }
        
        promptEngineerState.assistants = assistants;
        console.log(`Loaded ${assistants.length} local assistants`);
    } catch (error) {
        console.error('Error loading assistants:', error);
        showNotification('Failed to load assistants', 'error');
    }
}

async function loadTemplates() {
    try {
        const saved = localStorage.getItem('promptEngineerTemplates');
        if (saved) {
            promptEngineerState.templates = JSON.parse(saved);
        } else {
            promptEngineerState.templates = [
                {
                    id: 'template-general',
                    name: 'General Prompt',
                    category: 'general',
                    template: `Context: {context}
Goal: {goal}
Audience: {audience}
Format: {format}
Constraints: {constraints}

Generate a response that addresses the above requirements.`
                },
                {
                    id: 'template-creative',
                    name: 'Creative Writing',
                    category: 'creative',
                    template: `Genre: {genre}
Style: {style}
Characters: {characters}
Setting: {setting}
Tone: {tone}

Create a creative response that incorporates these elements.`
                },
                {
                    id: 'template-technical',
                    name: 'Technical Explanation',
                    category: 'technical',
                    template: `Topic: {topic}
Complexity Level: {level}
Prerequisites: {prerequisites}
Examples Needed: {examples}
Key Points: {key_points}

Provide a technical explanation addressing these aspects.`
                }
            ];
        }
        
        renderTemplates();
    } catch (error) {
        console.error('Failed to load templates:', error);
    }
}

function loadPromptHistory() {
    try {
        const saved = localStorage.getItem('promptEngineerHistory');
        if (saved) {
            promptEngineerState.history = JSON.parse(saved);
            renderHistory();
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

// ===== UI UPDATE FUNCTIONS =====

function updatePromptEngineerUI() {
    document.getElementById('pe-use-vector-store').checked = promptEngineerState.useVectorStore;
    document.getElementById('pe-use-files').checked = promptEngineerState.useFiles;
    document.getElementById('pe-use-ref-prompts').checked = promptEngineerState.useRefPrompts;
    
    Object.keys(promptEngineerState.metrics).forEach(metric => {
        const slider = document.getElementById(`pe-metric-${metric}`);
        const valueSpan = document.getElementById(`pe-${metric}-value`);
        if (slider) slider.value = promptEngineerState.metrics[metric];
        if (valueSpan) valueSpan.textContent = promptEngineerState.metrics[metric];
    });
    
    updateStatus('Ready');
}

function updateStatus(message) {
    const statusEl = document.getElementById('prompt-engineer-status');
    if (statusEl) {
        statusEl.textContent = message;
    }
}

function renderTemplates() {
    const container = document.getElementById('pe-templates-list');
    if (!container) return;
    
    container.innerHTML = '';
    
    promptEngineerState.templates.forEach(template => {
        const templateEl = document.createElement('div');
        templateEl.className = 'template-card';
        templateEl.innerHTML = `
            <div class="template-header">
                <span class="template-name">${escapeHtml(template.name)}</span>
                <span class="template-category">${template.category}</span>
            </div>
            <div class="template-preview">
                ${escapeHtml(template.template.substring(0, 100))}${template.template.length > 100 ? '...' : ''}
            </div>
            <div class="template-actions">
                <button class="btn btn-icon" onclick="useTemplate('${template.id}')" title="Use Template">
                    <i class="fas fa-play"></i>
                </button>
                <button class="btn btn-icon" onclick="editTemplate('${template.id}')" title="Edit">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn btn-icon" onclick="deleteTemplate('${template.id}')" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
        container.appendChild(templateEl);
    });
}

function renderHistory() {
    const select = document.getElementById('pe-history-select');
    if (!select) return;
    
    select.innerHTML = '';
    
    if (promptEngineerState.history.length === 0) {
        select.innerHTML = '<option disabled selected>No history yet</option>';
        return;
    }
    
    promptEngineerState.history.forEach((item, index) => {
        const option = document.createElement('option');
        option.value = index;
        const date = new Date(item.timestamp).toLocaleString();
        option.textContent = `${date} - ${item.name || 'Unnamed Prompt'}`;
        select.appendChild(option);
    });
}

function updatePromptDetails() {
    const prompt = document.getElementById('pe-generated-prompt')?.value || '';
    
    const tokenCount = calculateTokenCount();
    const qualityScore = calculateQualityScore(prompt);
    const qualityElement = document.getElementById('pe-quality-score');
    if (qualityElement) {
        qualityElement.textContent = `Quality: ${qualityScore}/10`;
        promptEngineerState.qualityScore = qualityScore;
    }
    
    const readability = calculateReadability(prompt);
    const readabilityElement = document.getElementById('pe-readability-score');
    if (readabilityElement) {
        readabilityElement.textContent = readability;
    }
    
    const structure = evaluateStructure(prompt);
    const structureElement = document.getElementById('pe-structure-score');
    if (structureElement) {
        structureElement.textContent = structure;
    }
}

function calculateQualityScore(prompt) {
    if (!prompt || prompt.trim().length === 0) {
        return 0;
    }
    
    const metricsAverage = Math.round(
        (promptEngineerState.metrics.clarity + 
         promptEngineerState.metrics.specificity + 
         promptEngineerState.metrics.creativity + 
         promptEngineerState.metrics.conciseness) / 4
    );
    
    let adjustedScore = metricsAverage;
    
    if (/#+|===|Context:|Goal:|Format:/i.test(prompt)) {
        adjustedScore = Math.min(10, adjustedScore + 1);
    }
    
    const wordCount = prompt.split(/\s+/).length;
    if (wordCount < 20 || wordCount > 1000) {
        adjustedScore = Math.max(0, adjustedScore - 1);
    }
    
    if (/[-*•]|^\d+\.|^[a-z]\)/.test(prompt)) {
        adjustedScore = Math.min(10, adjustedScore + 1);
    }
    
    return Math.max(0, Math.min(10, adjustedScore));
}

function calculateReadability(text) {
    if (!text || text.trim().length === 0) {
        return 'N/A';
    }
    
    const sentences = text.split(/[.!?]+/).filter(s => s.trim().length > 0);
    if (sentences.length === 0) return 'N/A';
    
    const words = text.split(/\s+/).filter(w => w.length > 0);
    const avgSentenceLength = words.length / sentences.length;
    
    if (avgSentenceLength < 10) return 'Very Easy';
    if (avgSentenceLength < 15) return 'Easy';
    if (avgSentenceLength < 20) return 'Moderate';
    if (avgSentenceLength < 25) return 'Difficult';
    if (avgSentenceLength < 30) return 'Very Difficult';
    return 'Expert Level';
}

function evaluateStructure(text) {
    if (!text || text.trim().length === 0) {
        return 'N/A';
    }
    
    const hasSections = /#{1,6}\s|===+|---+|Context:|Goal:|Format:|Instructions:|Requirements:/i.test(text);
    const hasBullets = /[-*•]\s|^\s*\d+\.|^\s*[a-z]\)/m.test(text);
    const hasLineBreaks = (text.match(/\n\s*\n/g) || []).length;
    const hasInlineFormatting = /\*\*|__|\*\w+\*|_\w+_/.test(text);
    
    let score = 0;
    
    if (hasSections) score += 3;
    if (hasBullets) score += 2;
    if (hasLineBreaks >= 2) score += 2;
    if (hasInlineFormatting) score += 1;
    
    if (score >= 7) return 'Excellent';
    if (score >= 5) return 'Good';
    if (score >= 3) return 'Fair';
    if (score >= 1) return 'Poor';
    return 'Very Poor';
}

// ===== ENHANCED FILE HANDLING WITH FULL PATHS =====

function handleFileUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    for (const file of files) {
        // Try to get full path - note: browsers limit this for security
        // webkitRelativePath works when folder is selected
        const relativePath = file.webkitRelativePath || file.name;
        
        // For drag & drop or file input, we can try to reconstruct path
        // The actual full path is not accessible in browsers for security
        // But we can store what we have
        const fileInfo = {
            id: Date.now() + Math.random(),
            name: file.name,
            size: file.size,
            type: file.type,
            file: file,
            path: relativePath,
            // Store a reference path that includes folder structure if available
            fullPath: relativePath !== file.name ? relativePath : file.name
        };
        
        promptEngineerState.attachedFiles.push(fileInfo);
    }
    
    renderFilesList();
    showNotification(`${files.length} file(s) added`, 'success');
    event.target.value = ''; // Reset input
}

function renderFilesList() {
    const container = document.getElementById('pe-files-list');
    if (!container) return;
    
    if (promptEngineerState.attachedFiles.length === 0) {
        container.innerHTML = '<div class="empty">No files attached</div>';
        return;
    }
    
    container.innerHTML = '';
    promptEngineerState.attachedFiles.forEach(file => {
        const fileEl = document.createElement('div');
        fileEl.className = 'file-item';
        fileEl.innerHTML = `
            <div class="file-info">
                <i class="fas fa-file"></i>
                <span class="file-name">${escapeHtml(file.name)}</span>
                <span class="file-size">(${formatFileSize(file.size)})</span>
            </div>
            <button class="btn btn-icon" onclick="removeAttachedFile('${file.id}')" title="Remove">
                <i class="fas fa-times"></i>
            </button>
        `;
        container.appendChild(fileEl);
    });
}

function removeAttachedFile(fileId) {
    promptEngineerState.attachedFiles = promptEngineerState.attachedFiles.filter(f => f.id !== fileId);
    renderFilesList();
    showNotification('File removed', 'info');
}

function clearAttachedFiles() {
    if (promptEngineerState.attachedFiles.length === 0) return;
    
    if (confirm(`Remove all ${promptEngineerState.attachedFiles.length} attached files?`)) {
        promptEngineerState.attachedFiles = [];
        renderFilesList();
        showNotification('All files removed', 'success');
    }
}

// ===== VECTOR STORE INTEGRATION =====

async function searchVectorStore(query, limit = 5) {
    if (!promptEngineerState.currentCollection) {
        throw new Error('No collection selected');
    }
    
    try {
        const response = await fetch('/v1/qdrant/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collection_name: promptEngineerState.currentCollection,
                query_text: query,
                limit: limit
            })
        });
        
        if (!response.ok) {
            throw new Error('Search failed');
        }
        
        const data = await response.json();
        return data.results || [];
    } catch (error) {
        console.error('Vector search error:', error);
        throw error;
    }
}

// ===== ENHANCED VECTOR STORE WITH FULL PATHS =====
async function getContextFromVectorStore(userInput) {
    if (!promptEngineerState.useVectorStore || !promptEngineerState.currentCollection) {
        return { context: '', results: [] };
    }
    
    try {
        const limit = parseInt(document.getElementById('pe-search-limit')?.value || 5);
        const results = await searchVectorStore(userInput, limit);
        
        if (results.length === 0) {
            return { context: '', results: [] };
        }
        
        let context = "=== Relevant Context from Knowledge Base ===\n";
        context += `Collection: ${promptEngineerState.currentCollection}\n`;
        context += `Results Retrieved: ${results.length}\n\n`;
        
        const processedResults = [];
        
        results.forEach((result, index) => {
            const payload = result.payload || {};
            const text = payload.text || payload.content || '';
            
            // Try multiple fields to get the most complete path
            const source = payload.full_path || 
                          payload.filepath || 
                          payload.source_file || 
                          payload.source || 
                          payload.filename || 
                          payload.path ||
                          'Unknown source';
            
            const score = result.score?.toFixed(4) || 'N/A';
            
            // Store full result info with complete path
            processedResults.push({
                index: index + 1,
                score: result.score,
                source: source,
                fullPath: source,
                filepath: source,
                contentPreview: text.substring(0, 200),
                fullContent: text
            });
            
            // Include full path in context
            context += `[${index + 1}] Relevance Score: ${score}\n`;
            context += `Source File: ${source}\n`;
            context += `Full Path: ${source}\n`;
            context += `Content:\n${text}\n\n`;
            context += `---\n\n`;
        });
        
        context += "=== End of Knowledge Base Context ===\n\n";
        
        return { context, results: processedResults };
        
    } catch (error) {
        console.error('Failed to get vector context:', error);
        return { context: '', results: [] };
    }
}

// ===== ENHANCED API CALL WITH TRACKING =====

async function callDeepSeekAPI(systemPrompt, userMessage, contextInfo = {}) {
    try {
        updateStatus('Calling DeepSeek API...');
        
        const temperature = parseFloat(document.getElementById('pe-temperature')?.value || 0.1);
        const maxTokens = parseInt(document.getElementById('pe-max-tokens')?.value || 2000);
        
        const payload = {
            messages: [
                { role: 'system', content: systemPrompt },
                { role: 'user', content: userMessage }
            ],
            model: promptEngineerState.model,
            stream: false,
            temperature: temperature,
            max_tokens: maxTokens
        };

        // Store generation context for debugging/display
        promptEngineerState.lastGenerationContext = {
            ...promptEngineerState.lastGenerationContext,
            temperature: temperature,
            maxTokens: maxTokens,
            systemPrompt: systemPrompt,
            fullPromptSent: userMessage,
            ...contextInfo
        };

        console.log('=== Generation Context ===');
        console.log('Temperature:', temperature);
        console.log('Max Tokens:', maxTokens);
        console.log('Vector Store Used:', contextInfo.vectorStoreUsed || false);
        console.log('Collection:', contextInfo.collectionName || 'N/A');
        console.log('Vector Results:', contextInfo.vectorResults?.length || 0);
        console.log('Files Used:', contextInfo.filesUsed?.length || 0);
        console.log('Full Message Length:', userMessage.length);
        console.log('==========================');

        const response = await fetch(promptEngineerState.apiEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        return data.response || data.choices?.[0]?.message?.content || '';
        
    } catch (error) {
        console.error('DeepSeek API error:', error);
        throw error;
    }
}

// ===== ENHANCED GENERATION WITH FULL TRACKING =====

async function generateOrRefinePrompt() {
    if (promptEngineerState.isGenerating) {
        showNotification('Generation already in progress', 'warning');
        return;
    }

    const userInput = document.getElementById('pe-input-description')?.value.trim();
    if (!userInput) {
        showNotification('Please describe your prompt needs', 'warning');
        return;
    }

    try {
        promptEngineerState.isGenerating = true;
        updateStatus('Gathering context...');
        
        // Build system prompt
        let systemPrompt = document.getElementById('pe-system-instruction')?.value || 
            'You are a professional prompt engineer. Generate high-quality prompts that are clear, specific, and effective. Respond with only the generated prompt, no explanations.';
        
        if (promptEngineerState.useAssistant && promptEngineerState.currentAssistant) {
            systemPrompt = `${promptEngineerState.currentAssistant.instructions}\n\n${systemPrompt}`;
        }
        
        // Initialize context tracking
        let fullMessage = '';
        const contextInfo = {
            vectorStoreUsed: false,
            collectionName: '',
            vectorResults: [],
            filesUsed: [],
            fileContents: [],
            temperature: parseFloat(document.getElementById('pe-temperature')?.value || 0.7),
            maxTokens: parseInt(document.getElementById('pe-max-tokens')?.value || 2000),
            systemPrompt: systemPrompt,
            fullPromptSent: ''
        };
        
        // 1. Get Vector Store Context
        if (promptEngineerState.useVectorStore && promptEngineerState.currentCollection) {
            updateStatus('Searching vector store...');
            const vectorData = await getContextFromVectorStore(userInput);
            if (vectorData.context) {
                fullMessage += vectorData.context;
                contextInfo.vectorStoreUsed = true;
                contextInfo.collectionName = promptEngineerState.currentCollection;
                contextInfo.vectorResults = vectorData.results;
                
                console.log('📚 Vector Store Results:', vectorData.results.length);
                vectorData.results.forEach((r, i) => {
                    console.log(`  [${i+1}] Score: ${r.score?.toFixed(4)} | Source: ${r.source}`);
                });
            }
        }
        
        // 2. Get Attached Files Context
        if (promptEngineerState.useFiles && promptEngineerState.attachedFiles.length > 0) {
            updateStatus('Reading attached files...');
            const filesData = await getAttachedFilesContext();
            if (filesData.context) {
                fullMessage += filesData.context;
                contextInfo.filesUsed = filesData.filesUsed;
                contextInfo.fileContents = filesData.fileContents;
                
                console.log('📎 Files Attached:', filesData.filesUsed.length);
                filesData.filesUsed.forEach((f, i) => {
                    console.log(`  [${i+1}] ${f.path} (${formatFileSize(f.size)})`);
                });
            }
        }
        
        // 3. Add user input
        fullMessage += `\n=== User Request ===\n${userInput}\n`;
        contextInfo.fullPromptSent = fullMessage;
        
        // Log full context info
        console.log('=== GENERATION CONTEXT SUMMARY ===');
        console.log('Temperature:', contextInfo.temperature);
        console.log('Max Tokens:', contextInfo.maxTokens);
        console.log('Vector Store:', contextInfo.vectorStoreUsed ? contextInfo.collectionName : 'Not used');
        console.log('Vector Results:', contextInfo.vectorResults.length);
        console.log('Files Used:', contextInfo.filesUsed.length);
        console.log('Full Message Length:', fullMessage.length, 'chars');
        console.log('==================================');
        
        // 4. Call API
        updateStatus('Generating prompt...');
        const generatedPrompt = await callDeepSeekAPI(systemPrompt, fullMessage, contextInfo);
        
        // Store context for later export
        promptEngineerState.lastGenerationContext = contextInfo;
        
        // Update UI
        document.getElementById('pe-generated-prompt').value = generatedPrompt;
        promptEngineerState.currentPrompt = generatedPrompt;
        
        // Save to history with full context
        saveToHistory({
            timestamp: new Date().toISOString(),
            name: `Prompt ${promptEngineerState.history.length + 1}`,
            input: userInput,
            prompt: generatedPrompt,
            model: promptEngineerState.model,
            context: {
                vectorStore: contextInfo.vectorStoreUsed ? {
                    collection: contextInfo.collectionName,
                    resultsCount: contextInfo.vectorResults.length,
                    sources: contextInfo.vectorResults.map(r => r.source)
                } : null,
                files: contextInfo.filesUsed.length > 0 ? contextInfo.filesUsed.map(f => f.path) : null,
                settings: {
                    temperature: contextInfo.temperature,
                    maxTokens: contextInfo.maxTokens
                }
            }
        });
        
        // Update displays
        updatePromptDetails();
        updateContextDisplay(contextInfo);
        
        updateStatus('Prompt generated successfully');
        showNotification('Prompt generated with full context tracking!', 'success');
        
    } catch (error) {
        console.error('Error generating prompt:', error);
        showNotification(`Generation failed: ${error.message}`, 'error');
        updateStatus('Generation failed');
    } finally {
        promptEngineerState.isGenerating = false;
    }
}

// ===== NEW: Display Context Information =====

function updateContextDisplay(contextInfo) {
    // Update the Raw Preview tab with context information
    const rawPreview = document.querySelector('#pe-raw-preview pre');
    if (rawPreview) {
        let contextDisplay = '=== GENERATION CONTEXT REPORT ===\n\n';
        
        // Settings
        contextDisplay += '📊 SETTINGS:\n';
        contextDisplay += `   Temperature: ${promptEngineerState.lastGenerationContext.temperature}\n`;
        contextDisplay += `   Max Tokens: ${promptEngineerState.lastGenerationContext.maxTokens}\n\n`;
        
        // Vector Store
        contextDisplay += '🗄️ VECTOR STORE:\n';
        if (contextInfo.vectorStoreUsed) {
            contextDisplay += `   ✅ Used: Yes\n`;
            contextDisplay += `   Collection: ${contextInfo.collectionName}\n`;
            contextDisplay += `   Results Retrieved: ${contextInfo.vectorResults.length}\n`;
            contextInfo.vectorResults.forEach((r, i) => {
                contextDisplay += `   [${i + 1}] Score: ${r.score?.toFixed(4)} | Source: ${r.source}\n`;
            });
        } else {
            contextDisplay += `   ❌ Used: No\n`;
        }
        contextDisplay += '\n';
        
        // Attached Files
        contextDisplay += '📎 ATTACHED FILES:\n';
        if (contextInfo.filesUsed && contextInfo.filesUsed.length > 0) {
            contextDisplay += `   ✅ Files Used: ${contextInfo.filesUsed.length}\n`;
            contextInfo.filesUsed.forEach((f, i) => {
                contextDisplay += `   [${i + 1}] ${f.path} (${formatFileSize(f.size)})\n`;
            });
        } else {
            contextDisplay += `   ❌ No files attached\n`;
        }
        contextDisplay += '\n';
        
        // Full prompt sent (truncated)
        contextDisplay += '📝 FULL MESSAGE SENT (preview):\n';
        const fullPrompt = promptEngineerState.lastGenerationContext.fullPromptSent || '';
        contextDisplay += `   Length: ${fullPrompt.length} characters\n`;
        contextDisplay += `   Preview:\n${fullPrompt.substring(0, 500)}${fullPrompt.length > 500 ? '...' : ''}\n`;
        
        rawPreview.textContent = contextDisplay;
    }
    
    // Update Analysis Preview with detailed breakdown
    const analysisPreview = document.querySelector('#pe-analysis-preview .analysis-content');
    if (analysisPreview) {
        analysisPreview.innerHTML = `
            <div class="context-analysis">
                <h5>🔍 Context Sources Used</h5>
                
                <div class="context-section">
                    <h6>⚙️ Generation Settings</h6>
                    <ul>
                        <li><strong>Model:</strong> ${promptEngineerState.model}</li>
                        <li><strong>Temperature:</strong> ${promptEngineerState.lastGenerationContext.temperature}</li>
                        <li><strong>Max Tokens:</strong> ${promptEngineerState.lastGenerationContext.maxTokens}</li>
                    </ul>
                </div>
                
                ${contextInfo.vectorStoreUsed ? `
                    <div class="context-section vector-section">
                        <h6>🗄️ Vector Store Context</h6>
                        <ul>
                            <li><strong>Collection:</strong> ${contextInfo.collectionName}</li>
                            <li><strong>Documents Retrieved:</strong> ${contextInfo.vectorResults.length}</li>
                        </ul>
                        <table class="context-table">
                            <thead>
                                <tr><th>#</th><th>Score</th><th>Source File</th></tr>
                            </thead>
                            <tbody>
                                ${contextInfo.vectorResults.map(r => `
                                    <tr>
                                        <td>${r.index}</td>
                                        <td>${r.score?.toFixed(4)}</td>
                                        <td><code>${escapeHtml(r.source)}</code></td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                ` : '<div class="context-section"><h6>🗄️ Vector Store: Not Used</h6></div>'}
                
                ${contextInfo.filesUsed && contextInfo.filesUsed.length > 0 ? `
                    <div class="context-section files-section">
                        <h6>📎 Attached Files</h6>
                        <table class="context-table">
                            <thead>
                                <tr><th>#</th><th>File Path</th><th>Type</th><th>Size</th></tr>
                            </thead>
                            <tbody>
                                ${contextInfo.filesUsed.map((f, i) => `
                                    <tr>
                                        <td>${i + 1}</td>
                                        <td><code>${escapeHtml(f.path)}</code></td>
                                        <td>${f.type || 'unknown'}</td>
                                        <td>${formatFileSize(f.size)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                ` : '<div class="context-section"><h6>📎 Attached Files: None</h6></div>'}
            </div>
        `;
    }
}

// ===== ENHANCED FILE READING =====

async function readFileContent(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (e) => {
            const content = e.target.result;
            resolve({
                name: file.name,
                path: file.webkitRelativePath || file.name,
                size: file.size,
                type: file.type,
                content: content
            });
        };
        
        reader.onerror = (e) => {
            reject(new Error(`Failed to read file: ${file.name}`));
        };
        
        // Read as text for text files, otherwise as data URL
        if (file.type.startsWith('text/') || 
            file.name.endsWith('.md') || 
            file.name.endsWith('.json') ||
            file.name.endsWith('.js') ||
            file.name.endsWith('.py') ||
            file.name.endsWith('.html') ||
            file.name.endsWith('.css') ||
            file.name.endsWith('.xml') ||
            file.name.endsWith('.yaml') ||
            file.name.endsWith('.yml') ||
            file.name.endsWith('.txt')) {
            reader.readAsText(file);
        } else {
            // For binary files, just note that they're attached
            resolve({
                name: file.name,
                path: file.webkitRelativePath || file.name,
                size: file.size,
                type: file.type,
                content: `[Binary file: ${file.name} (${formatFileSize(file.size)})]`
            });
        }
    });
}

async function analyzeNeeds() {
    const userInput = document.getElementById('pe-input-description')?.value.trim();
    if (!userInput) {
        showNotification('Please describe your prompt needs', 'warning');
        return;
    }

    try {
        updateStatus('Analyzing your needs...');
        
        const systemPrompt = `You are an expert prompt analyst. Analyze the user's request and provide:
1. A concise analysis of their needs
2. Key requirements identified
3. Practical suggestions

Format your response as:
ANALYSIS: [brief analysis]
REQUIREMENTS:
- [requirement 1]
- [requirement 2]
SUGGESTIONS:
- [suggestion 1]
- [suggestion 2]`;

        const result = await callDeepSeekAPI(systemPrompt, userInput);
        
        const analysis = {
            analysis: result,
            requirements: extractList(result, 'REQUIREMENTS'),
            suggestions: extractList(result, 'SUGGESTIONS')
        };
        
        showAnalysisModal(analysis);
        updateStatus('Analysis complete');
        showNotification('Analysis complete!', 'success');
        
    } catch (error) {
        console.error('Error analyzing needs:', error);
        showNotification(`Analysis failed: ${error.message}`, 'error');
        updateStatus('Analysis failed');
    }
}

async function generateVariations() {
    const currentPrompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!currentPrompt) {
        showNotification('No prompt to generate variations from', 'warning');
        return;
    }

    try {
        updateStatus('Generating variations...');
        
        const systemPrompt = `You are a creative prompt engineer. Generate 3 different variations of the given prompt. Each variation should maintain the core intent but approach it differently. 
        
Separate each variation with "---VARIATION---"

Output format:
[Variation 1 content]
---VARIATION---
[Variation 2 content]
---VARIATION---
[Variation 3 content]`;

        const result = await callDeepSeekAPI(systemPrompt, currentPrompt);
        const variations = result.split('---VARIATION---').map(v => v.trim()).filter(v => v);
        
        showVariationsModal(variations);
        updateStatus('Variations generated');
        showNotification('Variations generated!', 'success');
        
    } catch (error) {
        console.error('Error generating variations:', error);
        showNotification(`Variation generation failed: ${error.message}`, 'error');
        updateStatus('Generation failed');
    }
}

async function optimizePrompt() {
    const currentPrompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!currentPrompt) {
        showNotification('No prompt to optimize', 'warning');
        return;
    }

    try {
        updateStatus('Optimizing prompt...');
        
        const metricsText = Object.entries(promptEngineerState.metrics)
            .map(([k, v]) => `${k}: ${v}/10`)
            .join(', ');
        
        const systemPrompt = `You are an expert at optimizing prompts. Analyze and improve the following prompt to maximize: ${metricsText}

Provide ONLY the optimized prompt, nothing else.`;

        const optimized = await callDeepSeekAPI(systemPrompt, currentPrompt);
        
        document.getElementById('pe-generated-prompt').value = optimized;
        promptEngineerState.currentPrompt = optimized;
        updatePromptDetails();
        
        updateStatus('Prompt optimized');
        showNotification('Prompt optimized!', 'success');
        
    } catch (error) {
        console.error('Error optimizing prompt:', error);
        showNotification(`Optimization failed: ${error.message}`, 'error');
        updateStatus('Optimization failed');
    }
}

async function evaluatePrompt() {
    const currentPrompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!currentPrompt) {
        showNotification('No prompt to evaluate', 'warning');
        return;
    }

    try {
        updateStatus('Evaluating prompt...');
        
        const systemPrompt = `You are an expert prompt evaluator. Evaluate the prompt on these criteria and respond in this exact format:

CLARITY: [0-10]
SPECIFICITY: [0-10]
STRUCTURE: [0-10]
CONCISENESS: [0-10]
FEEDBACK: [brief feedback]
STRENGTHS:
- [strength 1]
- [strength 2]
IMPROVEMENTS:
- [improvement 1]
- [improvement 2]`;

        const result = await callDeepSeekAPI(systemPrompt, currentPrompt);
        
        const evaluation = {
            scores: extractScores(result),
            feedback: extractField(result, 'FEEDBACK'),
            strengths: extractList(result, 'STRENGTHS'),
            weaknesses: extractList(result, 'IMPROVEMENTS')
        };
        
        showEvaluationModal(evaluation);
        updateStatus('Evaluation complete');
        showNotification('Evaluation complete!', 'success');
        
    } catch (error) {
        console.error('Error evaluating prompt:', error);
        showNotification(`Evaluation failed: ${error.message}`, 'error');
        updateStatus('Evaluation failed');
    }
}

async function suggestImprovements() {
    const currentPrompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!currentPrompt) {
        showNotification('No prompt to improve', 'warning');
        return;
    }

    try {
        updateStatus('Suggesting improvements...');
        
        const systemPrompt = `You are an expert at improving prompts. Analyze this prompt and provide improvement suggestions.

First, list improvements as bullet points, then provide an optimized version.

Format:
IMPROVEMENTS:
- [improvement 1]
- [improvement 2]
- [improvement 3]

OPTIMIZED_VERSION:
[provide the improved prompt here]`;

        const result = await callDeepSeekAPI(systemPrompt, currentPrompt);
        
        const improvements = {
            improvements: extractList(result, 'IMPROVEMENTS'),
            optimized_version: extractField(result, 'OPTIMIZED_VERSION')
        };
        
        showImprovementsModal(improvements);
        updateStatus('Improvements suggested');
        showNotification('Improvements suggested!', 'success');
        
    } catch (error) {
        console.error('Error suggesting improvements:', error);
        showNotification(`Improvement suggestion failed: ${error.message}`, 'error');
        updateStatus('Suggestion failed');
    }
}

// ===== HELPER FUNCTIONS =====

function extractScores(text) {
    const scores = {};
    const metrics = ['CLARITY', 'SPECIFICITY', 'STRUCTURE', 'CONCISENESS'];
    
    metrics.forEach(metric => {
        const regex = new RegExp(`${metric}:\\s*(\\d+)`, 'i');
        const match = text.match(regex);
        if (match) {
            scores[metric.toLowerCase()] = parseInt(match[1]);
        }
    });
    
    return scores;
}

function extractField(text, fieldName) {
    const regex = new RegExp(`${fieldName}:\\s*(.+?)(?=\\n[A-Z_]+:|$)`, 'is');
    const match = text.match(regex);
    return match ? match[1].trim() : '';
}

function extractList(text, listName) {
    const regex = new RegExp(`${listName}:\\s*((?:[-•]\\s*.+\\n?)+)`, 'i');
    const match = text.match(regex);
    if (!match) return [];
    
    return match[1]
        .split('\n')
        .filter(line => line.trim().startsWith('-') || line.trim().startsWith('•'))
        .map(line => line.replace(/^[-•]\s*/, '').trim())
        .filter(line => line);
}

function calculateTokenCount() {
    const prompt = document.getElementById('pe-generated-prompt')?.value || '';
    const tokenCount = Math.ceil(prompt.length / 4);
    document.getElementById('pe-token-count').textContent = tokenCount;
    return tokenCount;
}

function copyGeneratedPrompt() {
    const prompt = document.getElementById('pe-generated-prompt');
    if (!prompt || !prompt.value.trim()) {
        showNotification('No prompt to copy', 'warning');
        return;
    }
    
    prompt.select();
    document.execCommand('copy');
    showNotification('Prompt copied to clipboard', 'success');
}

// ===== HELPER FUNCTION TO EXTRACT TITLE =====

function extractPromptTitle(prompt) {
    if (!prompt) return null;
    
    // Try to find a markdown heading (# Title)
    const headingMatch = prompt.match(/^#\s+(.+?)(?:\n|$)/m);
    if (headingMatch) {
        return headingMatch[1].trim();
    }
    
    // Try to find a title-like first line (all caps or title case)
    const firstLine = prompt.split('\n')[0]?.trim();
    if (firstLine && firstLine.length > 0 && firstLine.length < 100) {
        return firstLine;
    }
    
    return null;
}

function sanitizeFilename(title) {
    if (!title) return null;
    
    // Remove or replace invalid filename characters
    return title
        .replace(/[<>:"/\\|?*]/g, '') // Remove invalid chars
        .replace(/\s+/g, '_')          // Replace spaces with underscores
        .replace(/_+/g, '_')           // Collapse multiple underscores
        .replace(/^_|_$/g, '')         // Trim leading/trailing underscores
        .substring(0, 100);            // Limit length
}

// ===== ENHANCED EXPORT WITH FULL CONTEXT =====

function exportPromptToMarkdown() {
    const prompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!prompt) {
        showNotification('No prompt to export', 'warning');
        return;
    }
    
    const userInput = document.getElementById('pe-input-description')?.value || '';
    const timestamp = new Date().toLocaleString();
    const model = promptEngineerState.model;
    const ctx = promptEngineerState.lastGenerationContext;
    
    // Extract title for filename
    const promptTitle = extractPromptTitle(prompt);
    const sanitizedTitle = sanitizeFilename(promptTitle);
    const filename = sanitizedTitle 
        ? `${sanitizedTitle}.md` 
        : `prompt_${Date.now()}.md`;
    
    let markdownContent = `<!-- filepath: ${filename} -->\n`;
    markdownContent += `# Generated Prompt\n\n`;
    markdownContent += `**Generated:** ${timestamp}\n\n`;
    markdownContent += `**Model:** ${model}\n\n`;
    markdownContent += `**API Endpoint:** ${promptEngineerState.apiEndpoint}\n\n`;
    
    // ...existing code for building markdown content...
    
    // Generation Settings
    markdownContent += `## Generation Settings\n\n`;
    markdownContent += `| Setting | Value |\n`;
    markdownContent += `|---------|-------|\n`;
    markdownContent += `| Temperature | ${ctx.temperature || 0.7} |\n`;
    markdownContent += `| Max Tokens | ${ctx.maxTokens || 2000} |\n`;
    markdownContent += `| Vector Store Used | ${ctx.vectorStoreUsed ? 'Yes' : 'No'} |\n`;
    markdownContent += `| Files Attached | ${ctx.filesUsed?.length || 0} |\n\n`;
    
    // Vector Store Context Section
    if (ctx.vectorStoreUsed && ctx.vectorResults?.length > 0) {
        markdownContent += `## Vector Store Context\n\n`;
        markdownContent += `**Collection:** \`${ctx.collectionName}\`\n\n`;
        markdownContent += `**Documents Retrieved:** ${ctx.vectorResults.length}\n\n`;
        markdownContent += `| # | Score | Source File Path |\n`;
        markdownContent += `|---|-------|------------------|\n`;
        ctx.vectorResults.forEach((r, i) => {
            const sourcePath = r.source || r.filepath || 'Unknown';
            markdownContent += `| ${i + 1} | ${r.score?.toFixed(4) || 'N/A'} | \`${sourcePath}\` |\n`;
        });
        markdownContent += `\n`;
        
        markdownContent += `### Retrieved Content\n\n`;
        ctx.vectorResults.forEach((r, i) => {
            markdownContent += `#### [${i + 1}] ${r.source || 'Unknown Source'}\n\n`;
            markdownContent += `\`\`\`\n${r.fullContent || r.contentPreview || 'No content available'}\n\`\`\`\n\n`;
        });
    }
    
    // Attached Files Section
    if (ctx.filesUsed?.length > 0) {
        markdownContent += `## Attached Files\n\n`;
        markdownContent += `| # | File Path | Type | Size |\n`;
        markdownContent += `|---|-----------|------|------|\n`;
        ctx.filesUsed.forEach((f, i) => {
            markdownContent += `| ${i + 1} | \`${f.path || f.name}\` | ${f.type || 'unknown'} | ${formatFileSize(f.size)} |\n`;
        });
        markdownContent += `\n`;
        
        if (ctx.fileContents?.length > 0) {
            markdownContent += `### File Contents\n\n`;
            ctx.fileContents.forEach((fc, i) => {
                markdownContent += `#### [${i + 1}] \`${fc.path || fc.name}\`\n\n`;
                markdownContent += `\`\`\`${getFileExtension(fc.name)}\n${fc.content || 'Content not available'}\n\`\`\`\n\n`;
            });
        }
    }
    
    if (userInput) {
        markdownContent += `## Original Request\n\n${userInput}\n\n`;
    }
    
    if (ctx.systemPrompt) {
        markdownContent += `## System Prompt Used\n\n`;
        markdownContent += `\`\`\`\n${ctx.systemPrompt}\n\`\`\`\n\n`;
    }
    
    markdownContent += `## Generated Prompt\n\n${prompt}\n\n`;
    
    if (ctx.fullPromptSent) {
        markdownContent += `## Full Context Sent to API\n\n`;
        markdownContent += `<details>\n<summary>Click to expand (${ctx.fullPromptSent.length} characters)</summary>\n\n`;
        markdownContent += `\`\`\`\n${ctx.fullPromptSent}\n\`\`\`\n\n`;
        markdownContent += `</details>\n\n`;
    }
    
    if (Object.keys(promptEngineerState.metrics).length > 0) {
        markdownContent += `## Quality Metrics\n\n`;
        Object.entries(promptEngineerState.metrics).forEach(([metric, value]) => {
            markdownContent += `- **${metric.charAt(0).toUpperCase() + metric.slice(1)}:** ${value}/10\n`;
        });
        markdownContent += `\n`;
    }
    
    const blob = new Blob([markdownContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showNotification(`Exported as: ${filename}`, 'success');
}


// NEW: Export CLEAN prompt only (what's shown in UI)
function exportCleanPrompt() {
    const prompt = document.getElementById('pe-generated-prompt')?.value.trim();
    if (!prompt) {
        showNotification('No prompt to export', 'warning');
        return;
    }
    
    const userInput = document.getElementById('pe-input-description')?.value || '';
    const timestamp = new Date().toLocaleString();
    const ctx = promptEngineerState.lastGenerationContext;
    
    // Extract title for filename
    const promptTitle = extractPromptTitle(prompt);
    const sanitizedTitle = sanitizeFilename(promptTitle);
    const filename = sanitizedTitle 
        ? `${sanitizedTitle}.md` 
        : `agent_prompt_${Date.now()}.md`;
    
    let markdownContent = `# AI Agent Prompt\n\n`;
    markdownContent += `**Generated:** ${timestamp}\n\n`;
    
    // Add source files reference with FULL PATHS
    if (ctx.vectorStoreUsed || (ctx.filesUsed && ctx.filesUsed.length > 0)) {
        markdownContent += `## Source Context\n\n`;
        
        if (ctx.vectorStoreUsed && ctx.vectorResults?.length > 0) {
            markdownContent += `### Knowledge Base Sources\n`;
            markdownContent += `**Collection:** \`${ctx.collectionName}\`\n\n`;
            ctx.vectorResults.forEach((r, i) => {
                const fullPath = r.source || r.filepath || r.fullPath || 'Unknown source';
                markdownContent += `- \`${fullPath}\` (Score: ${r.score?.toFixed(4) || 'N/A'})\n`;
            });
            markdownContent += `\n`;
        }
        
        if (ctx.filesUsed && ctx.filesUsed.length > 0) {
            markdownContent += `### Attached Files\n`;
            ctx.filesUsed.forEach((f, i) => {
                const fullPath = f.fullPath || f.path || f.name;
                markdownContent += `- \`${fullPath}\` (${formatFileSize(f.size)})\n`;
            });
            markdownContent += `\n`;
        }
    }
    
    if (userInput) {
        markdownContent += `## Original Request\n\n${userInput}\n\n`;
    }
    
    markdownContent += `## Prompt\n\n${prompt}\n`;
    
    const blob = new Blob([markdownContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showNotification(`Exported as: ${filename}`, 'success');
}


function getFileExtension(filename) {
    if (!filename) return '';
    const ext = filename.split('.').pop()?.toLowerCase();
    const langMap = {
        'js': 'javascript',
        'py': 'python',
        'ts': 'typescript',
        'md': 'markdown',
        'json': 'json',
        'html': 'html',
        'css': 'css',
        'yaml': 'yaml',
        'yml': 'yaml',
        'xml': 'xml',
        'txt': 'text'
    };
    return langMap[ext] || ext || '';
}

// ===== ENHANCED FILE CONTEXT WITH FULL PATHS =====

async function getAttachedFilesContext() {
    if (!promptEngineerState.useFiles || promptEngineerState.attachedFiles.length === 0) {
        return { context: '', filesUsed: [], fileContents: [] };
    }
    
    const filesUsed = [];
    const fileContents = [];
    let context = "\n=== Attached Files Context ===\n\n";
    
    for (const fileInfo of promptEngineerState.attachedFiles) {
        try {
            const fileContent = await readFileContent(fileInfo.file);
            
            // Use the stored path info, with full path priority
            const fullPath = fileInfo.fullPath || fileInfo.path || fileInfo.name;
            
            const fileData = {
                name: fileContent.name,
                path: fullPath,
                fullPath: fullPath,
                size: fileContent.size,
                type: fileContent.type
            };
            filesUsed.push(fileData);
            
            // Store full content for export
            fileContents.push({
                name: fileContent.name,
                path: fullPath,
                fullPath: fullPath,
                content: fileContent.content
            });
            
            // Include full path in context sent to AI
            context += `--- File: ${fullPath} ---\n`;
            context += `Full Path: ${fullPath}\n`;
            context += `Type: ${fileContent.type || 'unknown'}\n`;
            context += `Size: ${formatFileSize(fileContent.size)}\n`;
            context += `Content:\n${fileContent.content}\n\n`;
            
        } catch (error) {
            console.error(`Error reading file ${fileInfo.name}:`, error);
            context += `--- File: ${fileInfo.name} (Error reading file) ---\n\n`;
        }
    }
    
    context += "=== End of Attached Files ===\n\n";
    
    return { context, filesUsed, fileContents };
}


function formatPrompt() {
    const prompt = document.getElementById('pe-generated-prompt');
    if (!prompt || !prompt.value.trim()) {
        showNotification('No prompt to format', 'warning');
        return;
    }
    
    let formatted = prompt.value
        .replace(/\n\s*\n\s*\n+/g, '\n\n')
        .replace(/([.!?])\s*(?=[A-Z])/g, '$1\n')
        .trim();
    
    prompt.value = formatted;
    showNotification('Prompt formatted', 'success');
}

function saveCurrentPrompt() {
    const prompt = document.getElementById('pe-generated-prompt')?.value.trim();
    
    if (!prompt) {
        showNotification('No prompt to save', 'error');
        return;
    }
    
    // Extract title from prompt for the name
    const promptTitle = extractPromptTitle(prompt);
    const name = promptTitle || `Saved Prompt ${promptEngineerState.history.length + 1}`;
    
    saveToHistory({
        name: name,
        input: document.getElementById('pe-input-description')?.value || '',
        prompt: prompt,
        timestamp: new Date().toISOString(),
        metrics: { ...promptEngineerState.metrics }
    });
    
    showNotification(`Prompt saved: "${name}"`, 'success');
}

function saveToHistory(item) {
    promptEngineerState.history.unshift(item);
    
    if (promptEngineerState.history.length > 50) {
        promptEngineerState.history = promptEngineerState.history.slice(0, 50);
    }
    
    localStorage.setItem('promptEngineerHistory', JSON.stringify(promptEngineerState.history));
    renderHistory();
}

function loadPromptVersion() {
    const select = document.getElementById('pe-history-select');
    const index = select?.value;
    
    if (!index || index < 0 || index >= promptEngineerState.history.length) {
        showNotification('Please select a version to load', 'error');
        return;
    }
    
    const item = promptEngineerState.history[index];
    document.getElementById('pe-generated-prompt').value = item.prompt;
    promptEngineerState.currentPrompt = item.prompt;
    
    if (item.input && document.getElementById('pe-input-description')) {
        document.getElementById('pe-input-description').value = item.input;
    }
    
    if (item.metrics) {
        Object.keys(item.metrics).forEach(metric => {
            if (document.getElementById(`pe-metric-${metric}`)) {
                document.getElementById(`pe-metric-${metric}`).value = item.metrics[metric];
                document.getElementById(`pe-${metric}-value`).textContent = item.metrics[metric];
                promptEngineerState.metrics[metric] = item.metrics[metric];
            }
        });
    }
    
    showNotification(`Loaded version: ${item.name}`, 'success');
    updatePromptDetails();
}

function comparePromptVersions() {
    const select = document.getElementById('pe-history-select');
    const selected = Array.from(select?.selectedOptions || []).map(opt => opt.value);
    
    if (selected.length < 2) {
        showNotification('Please select at least 2 versions to compare', 'error');
        return;
    }
    
    const items = selected.map(idx => promptEngineerState.history[idx]);
    
    const modalContent = `
        <div class="comparison-container">
            ${items.map((item, i) => `
                <div class="version-comparison">
                    <h5>${item.name}</h5>
                    <div class="version-info">
                        <small>${new Date(item.timestamp).toLocaleString()}</small>
                        <pre style="max-height: 200px; overflow: auto;">${escapeHtml(item.prompt)}</pre>
                    </div>
                </div>
            `).join('<hr>')}
        </div>
    `;
    
    peCreateModal('Compare Prompt Versions', modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '800px');
}

function clearPromptHistory() {
    if (promptEngineerState.history.length === 0) {
        showNotification('History is already empty', 'info');
        return;
    }
    
    if (confirm(`Clear all ${promptEngineerState.history.length} history items?`)) {
        promptEngineerState.history = [];
        localStorage.removeItem('promptEngineerHistory');
        renderHistory();
        showNotification('History cleared', 'success');
    }
}

function showPreviewTab(tabId) {
    document.querySelectorAll('.preview-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    
    document.querySelectorAll('.preview-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    const pane = document.getElementById(tabId);
    const tab = document.querySelector(`[data-target="${tabId}"]`);
    
    if (pane) pane.classList.add('active');
    if (tab) tab.classList.add('active');
}

// ===== TEMPLATE MANAGEMENT =====

function createNewTemplate() {
    const name = prompt('Enter template name:', 'New Template');
    if (!name) return;
    
    const category = prompt('Enter category (general, creative, technical, etc.):', 'general');
    
    const defaultTemplate = `# Template Structure
Context: {context}
Goal: {goal}
Audience: {audience}
Constraints: {constraints}

# Generated Response
{your_response_here}`;
    
    const template = prompt('Enter template content:', defaultTemplate);
    if (!template) return;
    
    const newTemplate = {
        id: 'template-' + Date.now(),
        name: name,
        category: category || 'general',
        template: template
    };
    
    promptEngineerState.templates.push(newTemplate);
    saveTemplates();
    renderTemplates();
    
    showNotification('Template created', 'success');
}

function useTemplate(templateId) {
    const template = promptEngineerState.templates.find(t => t.id === templateId);
    if (!template) return;
    
    document.getElementById('pe-input-description').value = 
        `Using template: ${template.name}\n\n` +
        template.template.replace(/\{.*?\}/g, '[fill me]');
    
    showNotification(`Template "${template.name}" loaded`, 'success');
}

function editTemplate(templateId) {
    const template = promptEngineerState.templates.find(t => t.id === templateId);
    if (!template) return;
    
    const newName = prompt('Edit template name:', template.name);
    if (newName === null) return;
    
    const newCategory = prompt('Edit category:', template.category);
    if (newCategory === null) return;
    
    const newContent = prompt('Edit template content:', template.template);
    if (newContent === null) return;
    
    template.name = newName || template.name;
    template.category = newCategory || template.category;
    template.template = newContent || template.template;
    
    saveTemplates();
    renderTemplates();
    showNotification('Template updated', 'success');
}

function deleteTemplate(templateId) {
    if (!confirm('Delete this template?')) return;
    
    promptEngineerState.templates = promptEngineerState.templates.filter(t => t.id !== templateId);
    saveTemplates();
    renderTemplates();
    showNotification('Template deleted', 'success');
}

function importTemplate() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.style.display = 'none';
    
    input.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        try {
            const text = await file.text();
            const imported = JSON.parse(text);
            
            if (Array.isArray(imported)) {
                promptEngineerState.templates.push(...imported);
            } else if (imported.templates) {
                promptEngineerState.templates.push(...imported.templates);
            } else {
                promptEngineerState.templates.push(imported);
            }
            
            saveTemplates();
            renderTemplates();
            showNotification('Templates imported successfully', 'success');
        } catch (error) {
            showNotification(`Import failed: ${error.message}`, 'error');
        }
        
        document.body.removeChild(input);
    });
    
    document.body.appendChild(input);
    input.click();
}

function saveTemplates() {
    localStorage.setItem('promptEngineerTemplates', JSON.stringify(promptEngineerState.templates));
}

async function loadPromptExamples() {
    const category = document.getElementById('pe-ref-category')?.value || 'general';
    
    const localExamples = {
        general: [
            'What are the key benefits of this approach?',
            'Explain this concept in simple terms.',
            'How does this process work step by step?'
        ],
        creative: [
            'Write a short story about an unexpected adventure.',
            'Compose a poem that captures the essence of change.',
            'Imagine a scenario where technology and nature coexist.'
        ],
        technical: [
            'Outline the steps to implement this solution.',
            'Describe the architecture of this system.',
            'How do you troubleshoot this common issue?'
        ]
    };
    
    const examples = localExamples[category] || [];
    const modalContent = `
        <div class="examples-container">
            ${examples.map((ex, i) => `
                <div class="example-item">
                    <h6>Example ${i + 1}</h6>
                    <pre>${escapeHtml(ex)}</pre>
                </div>
            `).join('<hr>')}
        </div>
    `;
    
    peCreateModal(`Prompt Examples - ${category}`, modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '600px');
}

// ===== MODAL HELPER FUNCTIONS =====

function showAnalysisModal(analysis) {
    const modalContent = `
        <div class="analysis-results">
            <div class="analysis-section">
                <h5><i class="fas fa-chart-line"></i> Analysis Results</h5>
                <div class="analysis-content">
                    ${escapeHtml(analysis.analysis)}
                </div>
            </div>
            
            ${analysis.requirements && analysis.requirements.length > 0 ? `
                <div class="requirements-section">
                    <h6><i class="fas fa-list-check"></i> Identified Requirements</h6>
                    <ul>
                        ${analysis.requirements.map(req => `<li>${escapeHtml(req)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
            
            ${analysis.suggestions && analysis.suggestions.length > 0 ? `
                <div class="suggestions-section">
                    <h6><i class="fas fa-lightbulb"></i> Suggestions</h6>
                    <ul>
                        ${analysis.suggestions.map(sug => `<li>${escapeHtml(sug)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
        </div>
    `;
    
    peCreateModal('Prompt Analysis', modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '600px');
}

function showVariationsModal(variations) {
    const modalContent = `
        <div class="variations-container">
            ${variations.map((variation, index) => `
                <div class="variation-item">
                    <div class="variation-header">
                        <h6>Variation ${index + 1}</h6>
                        <button class="btn btn-sm btn-primary" onclick="selectVariation(\`${variation.replace(/`/g, '\\`')}\`)">
                            Use This
                        </button>
                    </div>
                    <pre class="variation-content">${escapeHtml(variation)}</pre>
                </div>
            `).join('<hr>')}
        </div>
    `;
    
    peCreateModal('Prompt Variations', modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '800px');
}

function showEvaluationModal(evaluation) {
    const scores = evaluation.scores || {};
    const feedback = evaluation.feedback || 'Evaluation completed.';
    const strengths = evaluation.strengths || [];
    const weaknesses = evaluation.weaknesses || [];
    
    const modalContent = `
        <div class="evaluation-results">
            <div class="scores-section">
                <h5><i class="fas fa-star"></i> Quality Scores</h5>
                <div class="scores-grid">
                    ${Object.entries(scores).map(([metric, score]) => `
                        <div class="score-item">
                            <span class="metric-name">${metric.charAt(0).toUpperCase() + metric.slice(1)}</span>
                            <span class="score-value">${score}/10</span>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <div class="feedback-section">
                <h6><i class="fas fa-comments"></i> Detailed Feedback</h6>
                <div class="feedback-content">${escapeHtml(feedback)}</div>
            </div>
            
            ${strengths.length > 0 ? `
                <div class="strengths-section">
                    <h6><i class="fas fa-check-circle text-success"></i> Strengths</h6>
                    <ul>
                        ${strengths.map(str => `<li>${escapeHtml(str)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
            
            ${weaknesses.length > 0 ? `
                <div class="weaknesses-section">
                    <h6><i class="fas fa-exclamation-triangle text-warning"></i> Areas for Improvement</h6>
                    <ul>
                        ${weaknesses.map(weak => `<li>${escapeHtml(weak)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
        </div>
    `;
    
    peCreateModal('Prompt Evaluation', modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '700px');
}

function showImprovementsModal(improvements) {
    const modalContent = `
        <div class="improvements-container">
            ${improvements.improvements && improvements.improvements.length > 0 ? `
                <div class="improvements-section">
                    <h5><i class="fas fa-wrench"></i> Suggested Improvements</h5>
                    <ul>
                        ${improvements.improvements.map(imp => `<li>${escapeHtml(imp)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
            
            ${improvements.optimized_version ? `
                <div class="optimized-section">
                    <h6><i class="fas fa-magic"></i> Optimized Version</h6>
                    <pre class="optimized-content">${escapeHtml(improvements.optimized_version)}</pre>
                    <button class="btn btn-primary mt-2" onclick="useOptimizedVersion(\`${improvements.optimized_version.replace(/`/g, '\\`')}\`)">
                        Use Optimized Version
                    </button>
                </div>
            ` : ''}
        </div>
    `;
    
    peCreateModal('Improvement Suggestions', modalContent, [
        { text: 'Close', class: 'btn-secondary', onclick: 'peCloseModal()' }
    ], '700px');
}

function peCreateModal(title, content, buttons = [], width = '500px') {
    const existingModal = document.getElementById('prompt-engineer-modal');
    if (existingModal) {
        existingModal.remove();
    }
    
    const modal = document.createElement('div');
    modal.id = 'prompt-engineer-modal';
    modal.className = 'modal-overlay';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10001;
    `;
    
    const modalDialog = document.createElement('div');
    modalDialog.className = 'modal-dialog';
    modalDialog.style.cssText = `
        background: white;
        border-radius: 8px;
        max-width: ${width};
        max-height: 80vh;
        overflow-y: auto;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    `;
    
    const buttonsHtml = buttons.map(btn => 
        `<button class="btn ${btn.class || 'btn-primary'}" onclick="${btn.onclick}">${btn.text}</button>`
    ).join('');
    
    modalDialog.innerHTML = `
        <div class="modal-header" style="padding: 1rem; border-bottom: 1px solid #dee2e6;">
            <h4 class="modal-title">${escapeHtml(title)}</h4>
            <button type="button" class="btn btn-icon" onclick="peCloseModal()" style="margin-left: auto;" aria-label="Close dialog">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="modal-body" style="padding: 1rem;">
            ${content}
        </div>
        <div class="modal-footer" style="padding: 1rem; border-top: 1px solid #dee2e6; text-align: right;">
            ${buttonsHtml}
        </div>
    `;
    
    modal.appendChild(modalDialog);
    document.body.appendChild(modal);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            peCloseModal();
        }
    });
}

function peCloseModal() {
    const modal = document.getElementById('prompt-engineer-modal');
    if (modal) {
        modal.remove();
    }
}

function selectVariation(variation) {
    document.getElementById('pe-generated-prompt').value = variation;
    promptEngineerState.currentPrompt = variation;
    updatePromptDetails();
    peCloseModal();
    showNotification('Variation selected', 'success');
}

function useOptimizedVersion(optimized) {
    document.getElementById('pe-generated-prompt').value = optimized;
    promptEngineerState.currentPrompt = optimized;
    updatePromptDetails();
    peCloseModal();
    showNotification('Optimized version applied', 'success');
}

// ===== VOICE RECOGNITION =====

let peVoiceRecognition = null;
let peIsRecording = false;

function initVoiceRecognition() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        console.warn('Voice recognition not supported in this browser');
        return false;
    }
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    peVoiceRecognition = new SpeechRecognition();
    
    peVoiceRecognition.continuous = true;
    peVoiceRecognition.interimResults = true;
    peVoiceRecognition.lang = 'en-US';
    
    peVoiceRecognition.onstart = function() {
        peIsRecording = true;
        updateVoiceButtonState(true);
        showNotification('Listening... Speak now', 'info');
    };
    
    peVoiceRecognition.onend = function() {
        peIsRecording = false;
        updateVoiceButtonState(false);
    };
    
    peVoiceRecognition.onresult = function(event) {
        let finalTranscript = '';
        let interimTranscript = '';
        
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalTranscript += transcript;
            } else {
                interimTranscript += transcript;
            }
        }
        
        if (finalTranscript) {
            const inputField = document.getElementById('pe-input-description');
            if (inputField) {
                // Append to existing text with a space
                const currentText = inputField.value.trim();
                inputField.value = currentText ? `${currentText} ${finalTranscript}` : finalTranscript;
                inputField.dispatchEvent(new Event('input'));
            }
        }
        
        // Show interim results in a status indicator
        if (interimTranscript) {
            updateStatus(`Hearing: "${interimTranscript}"`);
        }
    };
    
    peVoiceRecognition.onerror = function(event) {
        console.error('Voice recognition error:', event.error);
        peIsRecording = false;
        updateVoiceButtonState(false);
        
        const errorMessages = {
            'no-speech': 'No speech detected. Please try again.',
            'audio-capture': 'No microphone found. Please check your settings.',
            'not-allowed': 'Microphone access denied. Please allow microphone access.',
            'network': 'Network error. Please check your connection.',
            'aborted': 'Voice recognition stopped.',
            'service-not-allowed': 'Speech service not allowed.'
        };
        
        const message = errorMessages[event.error] || `Voice error: ${event.error}`;
        showNotification(message, 'error');
        updateStatus('Ready');
    };
    
    return true;
}

function toggleVoiceRecording() {
    if (!peVoiceRecognition) {
        if (!initVoiceRecognition()) {
            showNotification('Voice recognition not supported in this browser', 'error');
            return;
        }
    }
    
    if (peIsRecording) {
        peVoiceRecognition.stop();
        showNotification('Voice recording stopped', 'info');
        updateStatus('Ready');
    } else {
        try {
            peVoiceRecognition.start();
        } catch (error) {
            console.error('Error starting voice recognition:', error);
            showNotification('Failed to start voice recording', 'error');
        }
    }
}

function updateVoiceButtonState(isRecording) {
    const voiceBtn = document.getElementById('pe-voice-btn');
    if (!voiceBtn) return;
    
    if (isRecording) {
        voiceBtn.classList.add('recording');
        voiceBtn.innerHTML = '<i class="fas fa-stop"></i>';
        voiceBtn.title = 'Stop Recording';
        voiceBtn.style.background = '#dc3545';
        voiceBtn.style.animation = 'pulse-recording 1s infinite';
    } else {
        voiceBtn.classList.remove('recording');
        voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
        voiceBtn.title = 'Start Voice Input';
        voiceBtn.style.background = '';
        voiceBtn.style.animation = '';
    }
}
