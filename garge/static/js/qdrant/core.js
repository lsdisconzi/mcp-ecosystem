/**
 * Qdrant Manager Core JavaScript
 * Main functionality for Qdrant Vector Database management UI
 */

// Global state management
const QdrantManager = {
    // Application state
    state: {
        collections: [],
        assistants: [],
        models: [],
        currentCollection: null,
        chatHistory: [],
        searchResults: [],
        workflowSteps: []
    },

    // Configuration
    config: {
        apiBaseUrl: '/v1/qdrant',
        defaultVectorSize: 768,
        defaultLimit: 10,
        supportedVectorSizes: [384, 768],
        distanceMetrics: ['cosine', 'euclid', 'dot']
    },

    // API endpoints
    endpoints: {
        collections: '/collections',
        search: '/search',
        ingestFile: '/collections/{collection}/ingest/file',
        ingestStructured: '/collections/{collection}/ingest/structured',
        health: '/health',
        metadata: {
            list: '/api/v1/metadata/list',
            json: '/api/v1/metadata/{audio}/json',
            pdf: '/api/v1/metadata/{audio}/pdf'
        }
    },

    // Initialization
    async init() {
        console.log('Qdrant Manager initializing...');
        await this.checkHealth();
        await this.loadCollections();
        await this.loadAssistants();
        this.setupEventListeners();
        console.log('Qdrant Manager ready');
    },

    // Health check
    async checkHealth() {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/health`);
            const data = await response.json();
            
            const statusElement = document.getElementById('connection-status');
            if (statusElement) {
                if (data.status === 'healthy') {
                    statusElement.className = 'status-badge success';
                    statusElement.innerHTML = '<i class="fas fa-check-circle"></i><span>Connected</span>';
                } else {
                    statusElement.className = 'status-badge error';
                    statusElement.innerHTML = '<i class="fas fa-exclamation-triangle"></i><span>Connection Failed</span>';
                }
            }
            
            return data;
        } catch (error) {
            console.error('Health check failed:', error);
            return { status: 'unhealthy', error: error.message };
        }
    },

    // Collection management
    async loadCollections() {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/collections`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const collections = await response.json();
            this.state.collections = collections;
            
            // Update UI
            this.renderCollectionsList(collections);
            this.updateCollectionDropdowns(collections);
            
            return collections;
        } catch (error) {
            console.error('Failed to load collections:', error);
            this.showNotification(`Error loading collections: ${error.message}`, 'error');
            return [];
        }
    },

    async createCollection(collectionData) {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/collections`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(collectionData)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to create collection');
            }
            
            const result = await response.json();
            this.showNotification(`Collection "${collectionData.name}" created successfully!`, 'success');
            
            // Refresh collections
            await this.loadCollections();
            
            return result;
        } catch (error) {
            console.error('Create collection failed:', error);
            this.showNotification(`Error: ${error.message}`, 'error');
            throw error;
        }
    },

    async deleteCollection(collectionName) {
        if (!confirm(`Are you sure you want to delete collection "${collectionName}"? This action cannot be undone.`)) {
            return;
        }
        
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/collections/${collectionName}`, {
                method: 'DELETE'
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to delete collection');
            }
            
            this.showNotification(`Collection "${collectionName}" deleted`, 'success');
            
            // Refresh collections
            await this.loadCollections();
            
        } catch (error) {
            console.error('Delete collection failed:', error);
            this.showNotification(`Error: ${error.message}`, 'error');
        }
    },

    // File ingestion
    async ingestFiles(collectionName, files, options = {}) {
        const formData = new FormData();
        
        // Add files
        for (const file of files) {
            formData.append('files', file);
        }
        
        // Add options
        formData.append('chunk_size', options.chunkSize || 1000);
        formData.append('chunk_overlap', options.chunkOverlap || 100);
        if (options.docType) {
            formData.append('doc_type', options.docType);
        }
        
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/collections/${collectionName}/ingest/file`, {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to ingest files');
            }
            
            const result = await response.json();
            this.showNotification(`Successfully ingested ${files.length} file(s)`, 'success');
            
            // Refresh collections to update counts
            await this.loadCollections();
            
            return result;
        } catch (error) {
            console.error('File ingestion failed:', error);
            this.showNotification(`Error: ${error.message}`, 'error');
            throw error;
        }
    },

    // Search
    async search(collectionName, query, options = {}) {
        const searchRequest = {
            collection_name: collectionName,
            query_text: query,
            limit: options.limit || this.config.defaultLimit,
            filters: options.filters,
            min_score: options.minScore || 0.0
        };
        
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(searchRequest)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Search failed');
            }
            
            const result = await response.json();
            this.state.searchResults = result.results;
            
            // Render results
            this.renderSearchResults(result.results);
            
            return result;
        } catch (error) {
            console.error('Search failed:', error);
            this.showNotification(`Error: ${error.message}`, 'error');
            throw error;
        }
    },

    // UI rendering methods
    renderCollectionsList(collections) {
        const container = document.getElementById('collections-list');
        if (!container) return;
        
        if (collections.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-database fa-3x"></i>
                    <h3>No Collections Found</h3>
                    <p>Create your first collection to get started</p>
                </div>
            `;
            return;
        }
        
        let html = '';
        collections.forEach(collection => {
            html += `
                <div class="collection-card" data-name="${collection.name}">
                    <div class="collection-header">
                        <div class="collection-name">${this.escapeHtml(collection.name)}</div>
                        <div class="collection-actions">
                            <button class="btn btn-sm btn-info" onclick="QdrantManager.viewCollectionDetails('${collection.name}')">
                                <i class="fas fa-info-circle"></i>
                            </button>
                            <button class="btn btn-sm btn-danger" onclick="QdrantManager.deleteCollection('${collection.name}')">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div class="collection-meta">
                        <div><strong>Points:</strong> ${collection.points_count?.toLocaleString() || '0'}</div>
                        <div><strong>Vector Size:</strong> ${collection.vector_size}</div>
                        <div><strong>Distance:</strong> ${collection.distance_metric}</div>
                        ${collection.status ? `<div><strong>Status:</strong> ${collection.status}</div>` : ''}
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
    },

    renderSearchResults(results) {
        const container = document.getElementById('search-results');
        if (!container) return;
        
        if (!results || results.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-search fa-3x"></i>
                    <h3>No Results Found</h3>
                    <p>Try a different search query</p>
                </div>
            `;
            return;
        }
        
        let html = `
            <div class="results-header">
                <h3>Search Results (${results.length})</h3>
                <button class="btn btn-sm btn-secondary" onclick="QdrantManager.exportSearchResults()">
                    <i class="fas fa-download"></i> Export
                </button>
            </div>
        `;
        
        results.forEach((result, index) => {
            const scorePercent = Math.round(result.score * 100);
            const payload = result.payload || {};
            
            html += `
                <div class="search-result-card">
                    <div class="result-header">
                        <div class="result-score">
                            <div class="score-bar" style="width: ${scorePercent}%"></div>
                            <span>Score: ${result.score.toFixed(4)} (${scorePercent}%)</span>
                        </div>
                        <div class="result-id">ID: ${result.id}</div>
                    </div>
                    ${payload.source ? `<div class="result-source">Source: ${this.escapeHtml(payload.source)}</div>` : ''}
                    ${payload.text ? `
                        <div class="result-text">
                            ${this.escapeHtml(payload.text.substring(0, 300))}
                            ${payload.text.length > 300 ? '...' : ''}
                        </div>
                    ` : ''}
                    ${payload.doc_type ? `<div class="result-type">Type: ${payload.doc_type}</div>` : ''}
                </div>
            `;
        });
        
        container.innerHTML = html;
    },

    // Utility methods
    updateCollectionDropdowns(collections) {
        const selectors = [
            'ingest-collection-select',
            'search-collection-select',
            'chat-collection-select',
            'workflow-collection-select'
        ];
        
        selectors.forEach(selector => {
            const element = document.getElementById(selector);
            if (element) {
                element.innerHTML = '<option value="">Select a collection...</option>';
                collections.forEach(collection => {
                    const option = document.createElement('option');
                    option.value = collection.name;
                    option.textContent = collection.name;
                    element.appendChild(option);
                });
            }
        });
    },

    async loadAssistants() {
        try {
            const response = await fetch('/api/v1/assistants');
            if (response.ok) {
                const data = await response.json();
                this.state.assistants = data.data || [];
                
                // Update assistant dropdowns
                const selectors = ['chat-assistant-select', 'workflow-assistant-select'];
                selectors.forEach(selector => {
                    const element = document.getElementById(selector);
                    if (element) {
                        element.innerHTML = '<option value="">Manual RAG (No Assistant)</option>';
                        this.state.assistants.forEach(assistant => {
                            const option = document.createElement('option');
                            option.value = assistant.id;
                            option.textContent = `${assistant.name} (${assistant.model})`;
                            element.appendChild(option);
                        });
                    }
                });
            }
        } catch (error) {
            console.warn('Failed to load assistants:', error);
        }
    },

    showNotification(message, type = 'info') {
        console.log(`[${type.toUpperCase()}] ${message}`);
        
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        
        // Set colors based on type
        const colors = {
            success: '#10b981',
            error: '#ef4444',
            warning: '#f59e0b',
            info: '#3b82f6'
        };
        
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${colors[type] || colors.info};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10000;
            animation: slideIn 0.3s ease-out;
            max-width: 400px;
        `;
        
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px;">
                <i class="fas fa-${this.getNotificationIcon(type)}"></i>
                <span>${this.escapeHtml(message)}</span>
                <button onclick="this.parentElement.parentElement.remove()" 
                        style="background: none; border: none; color: white; cursor: pointer; margin-left: 10px;">
                    ×
                </button>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    },

    getNotificationIcon(type) {
        const icons = {
            success: 'check-circle',
            error: 'exclamation-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
        return icons[type] || 'info-circle';
    },

    escapeHtml(text) {
        if (typeof text !== 'string') return text;
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    viewCollectionDetails(collectionName) {
        const collection = this.state.collections.find(c => c.name === collectionName);
        if (!collection) return;
        
        // Create or show modal
        let modal = document.getElementById('collection-details-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'collection-details-modal';
            modal.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
            `;
            document.body.appendChild(modal);
        }
        
        modal.innerHTML = `
            <div style="background: white; border-radius: 12px; padding: 24px; max-width: 600px; max-height: 80vh; overflow-y: auto;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h2 style="margin: 0;">Collection: ${this.escapeHtml(collectionName)}</h2>
                    <button onclick="document.getElementById('collection-details-modal').remove()" 
                            style="background: none; border: none; font-size: 24px; cursor: pointer; color: #666;">
                        ×
                    </button>
                </div>
                
                <div style="margin-bottom: 20px;">
                    <h3>Quick Actions</h3>
                    <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px;">
                        <button class="btn btn-primary" onclick="QdrantManager.setSearchCollection('${collectionName}')">
                            <i class="fas fa-search"></i> Search This Collection
                        </button>
                        <button class="btn btn-secondary" onclick="QdrantManager.ingestToCollection('${collectionName}')">
                            <i class="fas fa-upload"></i> Ingest Files
                        </button>
                    </div>
                </div>
                
                <h3>Collection Information</h3>
                <div style="background: #f8f9fa; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
                    <pre style="margin: 0; font-size: 14px; overflow-x: auto;">${this.escapeHtml(JSON.stringify(collection, null, 2))}</pre>
                </div>
                
                <div style="text-align: right;">
                    <button class="btn btn-secondary" onclick="document.getElementById('collection-details-modal').remove()">
                        Close
                    </button>
                </div>
            </div>
        `;
        
        modal.style.display = 'flex';
    },

    setSearchCollection(collectionName) {
        const searchSelect = document.getElementById('search-collection-select');
        if (searchSelect) {
            searchSelect.value = collectionName;
        }
        const modal = document.getElementById('collection-details-modal');
        if (modal) modal.remove();
        // Switch to search tab if available
        const searchTab = document.querySelector('[data-tab="search"]');
        if (searchTab) searchTab.click();
    },

    ingestToCollection(collectionName) {
        const ingestSelect = document.getElementById('ingest-collection-select');
        if (ingestSelect) {
            ingestSelect.value = collectionName;
        }
        const modal = document.getElementById('collection-details-modal');
        if (modal) modal.remove();
        // Switch to ingest tab if available
        const ingestTab = document.querySelector('[data-tab="ingest"]');
        if (ingestTab) ingestTab.click();
    },

    setupEventListeners() {
        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(`${tabId}-tab`)?.classList.add('active');
            });
        });

        // Create collection form
        const createCollectionForm = document.getElementById('create-collection-form');
        if (createCollectionForm) {
            createCollectionForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(createCollectionForm);
                const collectionData = {
                    name: formData.get('name'),
                    vector_size: parseInt(formData.get('vector_size')),
                    distance_metric: formData.get('distance_metric'),
                    description: formData.get('description')
                };
                
                await this.createCollection(collectionData);
                createCollectionForm.reset();
            });
        }

        // Search form
        const searchForm = document.getElementById('search-form');
        if (searchForm) {
            searchForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(searchForm);
                await this.search(
                    formData.get('collection'),
                    formData.get('query'),
                    {
                        limit: parseInt(formData.get('limit')) || 10
                    }
                );
            });
        }

        // File upload
        const fileUpload = document.getElementById('file-upload');
        if (fileUpload) {
            fileUpload.addEventListener('change', (e) => {
                const files = Array.from(e.target.files);
                const fileList = document.getElementById('file-list');
                if (fileList) {
                    fileList.innerHTML = files.map(file => 
                        `<div>${this.escapeHtml(file.name)} (${(file.size / 1024).toFixed(1)} KB)</div>`
                    ).join('');
                }
            });
        }

        // Ingest form
        const ingestForm = document.getElementById('ingest-form');
        if (ingestForm) {
            ingestForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(ingestForm);
                const files = Array.from(document.getElementById('file-upload').files);
                
                if (files.length === 0) {
                    this.showNotification('Please select at least one file', 'error');
                    return;
                }
                
                await this.ingestFiles(
                    formData.get('collection'),
                    files,
                    {
                        chunkSize: parseInt(formData.get('chunk_size')) || 1000,
                        chunkOverlap: parseInt(formData.get('chunk_overlap')) || 100,
                        docType: formData.get('doc_type')
                    }
                );
            });
        }
    }
};

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    QdrantManager.init();
});

// Export for use in other modules
window.QdrantManager = QdrantManager;