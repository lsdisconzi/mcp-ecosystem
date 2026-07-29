document.addEventListener('DOMContentLoaded', () => {
    initializeApp().catch(error => {
        console.error('Failed to bootstrap garage app:', error);
        showNotification(`❌ Initialization error: ${error.message}`, 'error');
    });

    // Tab Switching Logic
    document.querySelectorAll('.main-tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const sectionId = this.dataset.section;
            switchMainSection(sectionId);
        });
    });

    /* Helper for JS tab switching */
    function switchResourceTab(tabName) {
        // Hide all contents
        document.querySelectorAll('.resource-content').forEach(el => el.style.display = 'none');
        // Show selected
        document.getElementById('resource-' + tabName).style.display = 'block';
        
        // Update tab styling
        document.querySelectorAll('.resource-tab').forEach(el => el.classList.remove('active'));
        event.target.classList.add('active');
    }

    // Theme Toggle
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }
    
    // Periodic Checks
    setInterval(updateServerInfo, 60000);
    setInterval(checkSystemHealth, 30000);

    // Modal close buttons
    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.addEventListener('click', function() {
            this.closest('.modal').classList.add('hidden');
        });
    });

    // Resource tabs
    document.querySelectorAll('.resource-tab').forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            const tabName = this.dataset.tab;
            
            // Hide all tabs
            document.querySelectorAll('.resource-content').forEach(el => {
                el.style.display = 'none';
                el.classList.remove('active');
            });
            document.querySelectorAll('.resource-tab').forEach(el => {
                el.classList.remove('active');
            });
            
            // Show selected tab
            document.getElementById(`resource-${tabName}`).style.display = 'block';
            document.getElementById(`resource-${tabName}`).classList.add('active');
            this.classList.add('active');
        });
    });
});

async function initializeApp() {
    updateServerInfo();
    checkSystemHealth();

    // Load core data in parallel
    await Promise.allSettled([
        loadModels(),
        loadAssistants(), 
        loadFiles(),
        loadTools(),
        loadCollectionsData()
    ]);

    // Initialize specific sections
    prepareKnowledgeSection();
    setupVectorEventHandlers();

    // Preload openclaude agents if the function exists
    if (typeof loadOpenClaudeAgents === 'function') {
        loadOpenClaudeAgents().catch(() => {});
    }
}

function switchMainSection(sectionId) {
    // Hide all sections
    document.querySelectorAll('.main-section').forEach(section => {
        section.style.display = 'none';
    });

    // Show selected section
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.style.display = 'block';
    }

    // Update active tab
    document.querySelectorAll('.main-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    const activeTab = document.querySelector(`[data-section="${sectionId}"]`);
    if (activeTab) {
        activeTab.classList.add('active');
    }

    // Refresh data based on section
    if (sectionId === 'assistants-section') loadAssistants();
    else if (sectionId === 'files-section') loadFiles();
    else if (sectionId === 'knowledge-section') prepareKnowledgeSection();
    else if (sectionId === 'vectors-section') prepareVectorSection();
    else if (sectionId === 'tools-section') {
        loadTools();
        updateAssignedToolsList();
    }
    else if (sectionId === 'openclaude-section') {
        if (typeof loadOpenClaudeAgents === 'function') loadOpenClaudeAgents();
    }
}

async function checkSystemHealth() {
    const statusBadge = document.getElementById('status-badge');
    if (!statusBadge) return;

    try {
        const response = await fetch(`${currentApiUrl}/v1/models`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json();
        
        statusBadge.innerHTML = '<i class="fas fa-check-circle"></i> System Healthy';
        statusBadge.className = 'status-badge';
    } catch (error) {
        statusBadge.innerHTML = '<i class="fas fa-exclamation-circle"></i> System Error';
        statusBadge.style.background = 'var(--danger)';
    }
}

// Theme logic
const themes = ['light', 'dark', 'pastel', 'neon', 'solarized-dark', 'monochrome', 'high-contrast'];

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    let currentIndex = themes.indexOf(currentTheme);
    // Default to 0 if unknown theme
    if (currentIndex === -1) currentIndex = 0;
    
    const nextIndex = (currentIndex + 1) % themes.length;
    const nextTheme = themes[nextIndex];
    
    setTheme(nextTheme);
}

function setTheme(themeName) {
    if (!themes.includes(themeName)) return;
    
    document.documentElement.setAttribute('data-theme', themeName);
    localStorage.setItem('theme', themeName);
    updateThemeIcon(themeName);
}

function updateThemeIcon(theme) {
    const themeIcon = document.querySelector('#themeToggle i');
    if (!themeIcon) return;
    
    switch(theme) {
        case 'light': themeIcon.className = 'fas fa-moon'; break;
        case 'dark': themeIcon.className = 'fas fa-palette'; break;
        case 'pastel': themeIcon.className = 'fas fa-bolt'; break;
        case 'neon': themeIcon.className = 'fas fa-leaf'; break;
        case 'solarized-dark': themeIcon.className = 'fas fa-tv'; break;
        case 'monochrome': themeIcon.className = 'fas fa-adjust'; break;
        case 'high-contrast': themeIcon.className = 'fas fa-sun'; break;
        default: themeIcon.className = 'fas fa-moon';
    }
}

// Initialize theme
let savedTheme = localStorage.getItem('theme');
if (!savedTheme || !themes.includes(savedTheme)) {
    savedTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
document.documentElement.setAttribute('data-theme', savedTheme);
updateThemeIcon(savedTheme);

        function prepareKnowledgeSection() {
            populateKnowledgeAssistants();
            populateKnowledgeCollections();

            wireKnowledgeEvents();
        }

        function populateKnowledgeAssistants() {
            const select = document.getElementById('knowledge-assistant-select');
            if (!select) return;

            const previous = select.value || (selectedAssistant ? selectedAssistant.id : '');
            select.innerHTML = '<option value="">Default (No Assistant)</option>';

            availableAssistants.forEach(assistant => {
                const option = document.createElement('option');
                option.value = assistant.id;
                option.textContent = assistant.name || assistant.id;
                select.appendChild(option);
            });

            if (previous) {
                select.value = previous;
            } else if (selectedAssistant) {
                select.value = selectedAssistant.id;
            }
        }

        function populateKnowledgeCollections() {
            const select = document.getElementById('knowledge-collection-select');
            if (!select) return;

            const previous = select.value;
            select.innerHTML = '<option value="">Use assistant default (if configured)</option>';

            if (!collections.length) {
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.disabled = true;
                placeholder.textContent = 'No collections available';
                select.appendChild(placeholder);
                return;
            }

            collections.forEach(col => {
                const option = document.createElement('option');
                option.value = col.name;
                option.textContent = `${col.name} (${col.points_count || 0})`;
                select.appendChild(option);
            });

            if (previous) {
                select.value = previous;
            }
        }

        function wireKnowledgeEvents() {
            const queryBtn = document.getElementById('knowledge-query-btn');
            const queryInput = document.getElementById('knowledge-query-input');
            const assistantSelect = document.getElementById('knowledge-assistant-select');

            if (queryBtn && queryBtn.dataset.bound !== 'true') {
                queryBtn.addEventListener('click', queryKnowledge);
                queryBtn.dataset.bound = 'true';
            }

            if (queryInput && queryInput.dataset.bound !== 'true') {
                queryInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault();
                        queryKnowledge();
                    }
                });
                queryInput.dataset.bound = 'true';
            }

            if (assistantSelect && assistantSelect.dataset.bound !== 'true') {
                assistantSelect.addEventListener('change', (event) => {
                    const assistantId = event.target.value;
                    if (assistantId) {
                        const match = availableAssistants.find(a => a.id === assistantId);
                        if (match) {
                            selectedAssistant = match;
                            updateSelectedAssistantLabel();
                        }
                    }
                });
                assistantSelect.dataset.bound = 'true';
            }
        }
        async function queryKnowledge() {
            const assistantSelect = document.getElementById('knowledge-assistant-select');
            const collectionSelect = document.getElementById('knowledge-collection-select');
            const queryInput = document.getElementById('knowledge-query-input');
            const resultsDiv = document.getElementById('knowledge-results');

            const assistantId = assistantSelect ? assistantSelect.value : '';
            const collectionName = collectionSelect ? collectionSelect.value : '';
            const query = queryInput ? queryInput.value.trim() : '';

            if (!query) {
                showNotification('Please enter a question before querying.', 'error');
                return;
            }

            if (!assistantId && !collectionName) {
                showNotification('Select an assistant or a collection to query.', 'error');
                return;
            }

            if (resultsDiv) {
                resultsDiv.style.display = 'block';
                resultsDiv.innerHTML = '<div class="loading">Searching knowledge base...</div>';
            }

            try {
                let response;
                let data;

                if (assistantId) {
                    const payload = { query, n_results: 5 };
                    if (collectionName) {
                        payload.collection = collectionName;
                    }

                    response = await fetch(`/v1/assistants/${assistantId}/query-knowledge`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.detail || data.error || 'Failed to query knowledge');
                    }

                    const results = data.results || data.matches || [];
                    displayKnowledgeResults(results, {
                        assistantId,
                        collection: collectionName || selectedAssistant?.vector_collection || '',
                        raw: data
                    });
                } else {
                    response = await fetch('/v1/qdrant/search', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            collection_name: collectionName,
                            query_text: query,
                            limit: 5
                        })
                    });
                    data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.detail || data.error || 'Vector search failed');
                    }

                    displayKnowledgeResults(data.results || [], {
                        collection: collectionName,
                        raw: data
                    });
                }
            } catch (error) {
                console.error('Error querying knowledge:', error);
                if (resultsDiv) {
                    resultsDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
        }

        function displayKnowledgeResults(results, meta = {}) {
            const container = document.getElementById('knowledge-results');
            if (!container) return;

            container.style.display = 'block';

            if (!results || !results.length) {
                container.innerHTML = '<div class="empty">No results found</div>';
                return;
            }

            const resultsList = document.createElement('div');
            resultsList.className = 'results-list';

            results.forEach(result => {
                const resultItem = document.createElement('div');
                resultItem.className = 'result-item';

                const payload = result.metadata || result.payload || {};
                const content = payload.text || payload.content || result.content || result.text || '';
                const metadata = Object.entries(payload)
                    .filter(([key]) => key !== 'text' && key !== 'content')
                    .map(([key, val]) => `${key}: ${val}`)
                    .join(' | ');

                resultItem.innerHTML = `
                    <div class="result-content">${content.substring(0, 400)}${content.length > 400 ? '...' : ''}</div>
                    <div class="result-meta">
                        ${result.score ? `<span>Score: ${result.score.toFixed(2)}</span>` : ''}
                        ${result.distance ? `<span>Distance: ${result.distance.toFixed(4)}</span>` : ''}
                        ${metadata ? `<div class="result-metadata">${metadata}</div>` : ''}
                    </div>
                `;

                resultsList.appendChild(resultItem);
            });

            container.innerHTML = '';
            if (meta.collection || meta.assistantId) {
                const summary = document.createElement('div');
                summary.className = 'results-summary';
                summary.textContent = `Source: ${meta.collection || 'Assistant default collection'}${meta.assistantId ? ` • Assistant: ${meta.assistantId}` : ''}`;
                container.appendChild(summary);
            }

            container.appendChild(resultsList);
        }

