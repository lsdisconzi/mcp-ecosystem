// ===== COLLECTION DATA LOADING =====

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
            try {
                const response = await fetch('/v1/qdrant/connect', { method: 'POST' });
                if (!response.ok) {
                    const errorMessage = await getApiErrorMessage(response);
                    throw new Error(errorMessage);
                }
                return true;
            } catch (error) {
                throw new Error(error?.message || 'Unable to initialize Qdrant connection');
            }
        }

        async function loadCollectionsData({ showLoader = true } = {}) {
            const grid = document.getElementById('collections-list');
            if (grid && showLoader) {
                grid.innerHTML = '<div class="loading">Loading collections...</div>';
            }
 
            try {
                await ensureQdrantConnection();
                const response = await fetch('/v1/qdrant/collections');
        
        // Check content type before parsing
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            const text = await response.text();
            console.error('Non-JSON response:', text.substring(0, 500));
            throw new Error('Server returned non-JSON response');
        }

                if (!response.ok) {
            const errorMessage = await getApiErrorMessage(response);
            throw new Error(errorMessage);
                }

                const data = await response.json();
                
                let overview = [];
                if (data.collections && Array.isArray(data.collections)) {
                    overview = data.collections;
                } else if (Array.isArray(data)) {
                    overview = data;
                } else if (data.result && data.result.collections) {
                    overview = data.result.collections;
                }

                collections = overview.map(col => {
                    const vectorsCount = Number(
                        col.vectors_count ?? col.vectors ?? col.points_count ?? col.points ?? 0
                    ) || 0;
                    const pointsCount = Number(
                        col.points_count ?? col.points ?? col.vectors_count ?? col.vectors ?? 0
                    ) || 0;

                    return {
                        name: col.name,
                        status: col.status || col.state || (vectorsCount >= 0 ? 'ready' : 'unknown'),
                        vectors_count: vectorsCount,
                        points_count: pointsCount,
                        vector_size: Number(col.vector_size ?? col.dimension ?? 0) || 0
                    };
                });

                updateCollectionConsumers();
            } catch (error) {
                if (grid) {
                    const hint = (error?.message || '').toLowerCase().includes('vector database unavailable')
                        ? 'Qdrant is unavailable. Check service status and QDRANT_URL.'
                        : (error?.message || 'Failed to load collections.');
                    grid.innerHTML = `<div class="error">${escapeHtml(hint)}</div>`;
                }
                console.error('Collection load failed:', error);
                showNotification(`❌ Failed to load collections: ${error.message}`, 'error');
            }

            return collections;
        }

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

        function updateCollectionConsumers() {
            populateKnowledgeCollections();
            populateVectorDropdowns();
            renderCollectionsGrid();
        }

        function populateVectorDropdowns() {
            const selectIds = ['ingest-collection-select', 'search-collection-select', 'query-collection', 'points-collection', 'ingest-legal-collection'];
            selectIds.forEach(id => {
                const select = document.getElementById(id);
                if (!select) return;

                const previous = select.value;
                select.innerHTML = '<option value="">Select collection...</option>';

                collections.forEach(col => {
                    const option = document.createElement('option');
                    option.value = col.name;
                    option.textContent = `${col.name} (${col.points_count || col.vectors_count || 0})`;
                    select.appendChild(option);
                });

                if (previous) {
                    select.value = previous;
                }
            });
        }

        function renderCollectionsGrid() {
            const grid = document.getElementById('collections-list');
            if (!grid) return;

            if (!collections.length) {
                grid.innerHTML = '<div class="empty-state">No collections found. Create one to get started.</div>';
                return;
            }

            grid.innerHTML = '';
            collections.forEach(col => {
                const card = document.createElement('div');
                card.className = 'collection-card';
                card.innerHTML = `
                    <h4>${col.name}</h4>
                    <p>Status: ${col.status || 'unknown'}</p>
                    <p>Vectors: ${col.vectors_count || 0}</p>
                    <p>Points: ${col.points_count || 0}</p>
                    ${col.vector_size ? `<p>Dim: ${col.vector_size}</p>` : ''}
                `;
                grid.appendChild(card);
            });
        }

                // ===== VECTOR MANAGEMENT FUNCTIONS =====

        function prepareVectorSection() {
            setupVectorEventHandlers();
            loadCollectionsData();
        }

        function setupVectorEventHandlers() {
            if (vectorEventsBound) return;
            vectorEventsBound = true;

            const showModalBtn = document.getElementById('show-create-collection-modal-btn');
            const modal = document.getElementById('create-collection-modal');
            const confirmCreateBtn = document.getElementById('confirm-create-collection-btn');
            const closeButtons = modal ? modal.querySelectorAll('.close-modal') : [];

            showModalBtn?.addEventListener('click', () => toggleCollectionModal(true));
            closeButtons.forEach(btn => btn.addEventListener('click', () => toggleCollectionModal(false)));
            confirmCreateBtn?.addEventListener('click', createCollectionFromModal);

            const refreshBtn = document.getElementById('refresh-collections-btn');
            refreshBtn?.addEventListener('click', () => loadCollectionsData({ showLoader: true }));

            const ingestSelect = document.getElementById('ingest-collection-select');
            const ingestInput = document.getElementById('ingest-file-input');
            const ingestBtn = document.getElementById('ingest-files-btn');
            ingestSelect?.addEventListener('change', updateIngestButtonState);
            ingestInput?.addEventListener('change', updateIngestButtonState);
            ingestBtn?.addEventListener('click', handleFileIngestion);

            const searchSelect = document.getElementById('search-collection-select');
            const searchInput = document.getElementById('search-text-input');
            const searchBtn = document.getElementById('text-search-btn');
            searchSelect?.addEventListener('change', updateSearchButtonState);
            searchInput?.addEventListener('input', updateSearchButtonState);
            searchBtn?.addEventListener('click', runTextSearch);

            const queryBtn = document.getElementById('execute-query-btn');
            queryBtn?.addEventListener('click', runVectorQuery);

            const upsertBtn = document.getElementById('upsert-points-btn');
            upsertBtn?.addEventListener('click', upsertPoints);

            const deleteBtn = document.getElementById('delete-points-btn');
            deleteBtn?.addEventListener('click', deletePoints);

            // Legal Ingestion Handlers
            const legalFile = document.getElementById('ingest-legal-file');
            const legalCol = document.getElementById('ingest-legal-collection');
            const legalBtn = document.getElementById('ingest-legal-file-btn');
            const analyzeBtn = document.getElementById('analyze-legal-doc-btn');
            const legalFolder = document.getElementById('ingest-legal-folder');
            const legalFolderBtn = document.getElementById('ingest-legal-folder-btn');

            legalFile?.addEventListener('change', updateLegalButtonState);
            legalCol?.addEventListener('change', updateLegalButtonState);
            legalFolder?.addEventListener('input', updateLegalButtonState);
            legalBtn?.addEventListener('click', handleLegalIngestion);
            analyzeBtn?.addEventListener('click', handleLegalAnalysis);
            legalFolderBtn?.addEventListener('click', handleLegalFolderIngestion);

            updateIngestButtonState();
            updateSearchButtonState();
            updateLegalButtonState();
        }

        function updateLegalButtonState() {
            const file = document.getElementById('ingest-legal-file');
            const col = document.getElementById('ingest-legal-collection');
            const btn = document.getElementById('ingest-legal-file-btn');
            const analyzeBtn = document.getElementById('analyze-legal-doc-btn');
            const folderInput = document.getElementById('ingest-legal-folder');
            const folderBtn = document.getElementById('ingest-legal-folder-btn');
            
            const hasFile = file && file.files && file.files.length > 0;
            const hasCol = col && col.value;
            const hasFolder = folderInput && folderInput.value.trim().length > 0;
            
            if (btn) btn.disabled = !(hasFile && hasCol);
            if (analyzeBtn) analyzeBtn.disabled = !hasFile;
            if (folderBtn) folderBtn.disabled = !(hasFolder && hasCol);
        }

        async function handleLegalIngestion() {
            const fileInput = document.getElementById('ingest-legal-file');
            const colSelect = document.getElementById('ingest-legal-collection');
            const modelSelect = document.getElementById('legal-model-select');
            const enhancedCheck = document.getElementById('legal-enhanced-mode');
            const recreateCheck = document.getElementById('legal-force-recreate');
            const chunkSizeInput = document.getElementById('legal-chunk-size');
            const chunkOverlapInput = document.getElementById('legal-chunk-overlap');
            const metadataText = document.getElementById('legal-metadata-json');
            const btn = document.getElementById('ingest-legal-file-btn');
            const status = document.getElementById('ingest-legal-status');

            if (!fileInput?.files?.length || !colSelect?.value) return;

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ingesting...';
            status.style.display = 'block';
            status.innerHTML = '<div class="loading">Processing legal documents...</div>';

            try {
                const formData = new FormData();
                // Append all files
                for (let i = 0; i < fileInput.files.length; i++) {
                    formData.append('files', fileInput.files[i]);
                }
                
                formData.append('collection_name', colSelect.value);
                formData.append('force_recreate', recreateCheck?.checked || false);
                formData.append('enhanced', enhancedCheck?.checked !== false);
                
                if (modelSelect?.value) formData.append('model_name', modelSelect.value);
                if (chunkSizeInput?.value) formData.append('chunk_size', chunkSizeInput.value);
                if (chunkOverlapInput?.value) formData.append('chunk_overlap', chunkOverlapInput.value);
                if (metadataText?.value.trim()) formData.append('metadata_json', metadataText.value.trim());

                const response = await fetch('/v2/legal-ingestion/ingest-legal-file-enhanced', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Ingestion failed');

                let resultsHtml = '';
                if (data.results && Array.isArray(data.results)) {
                    resultsHtml = data.results.map(res => `
                        <div class="file-result ${res.status === 'success' ? 'success' : 'error'}" style="margin-bottom: 5px; padding: 5px; border-bottom: 1px solid #eee;">
                            <strong>${res.filename}</strong>: ${res.status === 'success' ? '<span style="color:green">Success</span>' : '<span style="color:red">Failed</span>'}
                            ${res.error ? `<br><small style="color:red">${res.error}</small>` : ''}
                            ${res.document_info ? `<br><small>Chunks: ${res.document_info.total_chunks}, Sections: ${res.document_info.total_sections}</small>` : ''}
                        </div>
                    `).join('');
                }

                status.innerHTML = `
                    <div class="success-message">
                        <h4><i class="fas fa-check-circle"></i> Ingestion Completed</h4>
                        <p>Total processed: ${data.total_processed || 0}</p>
                        <p>Successful: ${data.successful || 0}</p>
                        <p>Failed: ${data.failed || 0}</p>
                        <div class="results-list" style="max-height: 200px; overflow-y: auto; margin-top: 10px; border: 1px solid #ddd; padding: 5px; background: #f9f9f9;">
                            ${resultsHtml}
                        </div>
                    </div>
                `;
                showNotification('Legal ingestion completed.', 'success');
                loadCollectionsData({ showLoader: false });
            } catch (error) {
                console.error('Legal ingestion error:', error);
                status.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        async function handleLegalFolderIngestion() {
            const folderInput = document.getElementById('ingest-legal-folder');
            const colSelect = document.getElementById('ingest-legal-collection');
            const modelSelect = document.getElementById('legal-model-select');
            const enhancedCheck = document.getElementById('legal-enhanced-mode');
            const recreateCheck = document.getElementById('legal-force-recreate');
            const chunkSizeInput = document.getElementById('legal-chunk-size');
            const chunkOverlapInput = document.getElementById('legal-chunk-overlap');
            const metadataText = document.getElementById('legal-metadata-json');
            const btn = document.getElementById('ingest-legal-folder-btn');
            const status = document.getElementById('ingest-legal-status');

            if (!folderInput?.value.trim() || !colSelect?.value) return;

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ingesting...';
            status.style.display = 'block';
            status.innerHTML = '<div class="loading">Processing folder documents...</div>';

            try {
                const payload = {
                    folder_path: folderInput.value.trim(),
                    collection_name: colSelect.value,
                    force_recreate: recreateCheck?.checked || false,
                    enhanced: enhancedCheck?.checked !== false,
                    model_name: modelSelect?.value || null,
                    chunk_size: chunkSizeInput?.value ? parseInt(chunkSizeInput.value) : 1500,
                    chunk_overlap: chunkOverlapInput?.value ? parseInt(chunkOverlapInput.value) : 150,
                    metadata_json: metadataText?.value.trim() || null
                };

                const response = await fetch('/v2/legal-ingestion/ingest-legal-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Folder ingestion failed');

                status.innerHTML = `
                    <div class="success-message">
                        <h4><i class="fas fa-check-circle"></i> Folder Ingestion Completed</h4>
                        <p>Total processed: ${data.total_processed || 0}</p>
                        <p>Successful: ${data.successful || 0}</p>
                        <p>Failed: ${data.failed || 0}</p>
                    </div>
                `;
                showNotification('Folder ingestion completed.', 'success');
                loadCollectionsData({ showLoader: false });
            } catch (error) {
                console.error('Folder ingestion error:', error);
                status.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        async function handleLegalAnalysis() {
            const fileInput = document.getElementById('ingest-legal-file');
            const btn = document.getElementById('analyze-legal-doc-btn');
            const status = document.getElementById('ingest-legal-status');

            if (!fileInput?.files?.length) return;

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
            status.style.display = 'block';
            status.innerHTML = '<div class="loading">Analyzing document structure...</div>';

            try {
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);

                const response = await fetch('/v1/ingestion/analyze-document-structure', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Analysis failed');

                let sectionsHtml = data.sections?.map(s => `
                    <div class="section-preview">
                        <strong>${s.title} (${s.type})</strong>
                        <p class="small">${s.content_preview}</p>
                    </div>
                `).join('') || 'No sections detected';

                status.innerHTML = `
                    <div class="analysis-results">
                        <h4><i class="fas fa-microscope"></i> Document Analysis</h4>
                        <p><strong>File:</strong> ${data.filename}</p>
                        <p><strong>Sections:</strong> ${data.total_sections}</p>
                        <div class="sections-list" style="max-height: 200px; overflow-y: auto; margin: 10px 0; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 4px;">
                            ${sectionsHtml}
                        </div>
                        <p><strong>Extracted Metadata:</strong></p>
                        <pre>${JSON.stringify(data.metadata_extracted || {}, null, 2)}</pre>
                    </div>
                `;
            } catch (error) {
                console.error('Legal analysis error:', error);
                status.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        function toggleCollectionModal(show) {
            const modal = document.getElementById('create-collection-modal');
            if (!modal) return;
            if (show) {
                modal.classList.remove('hidden');
            } else {
                modal.classList.add('hidden');
            }
        }

        async function createCollectionFromModal() {
            const nameInput = document.getElementById('collection-name-input');
            const vectorSizeInput = document.getElementById('vector-size-input');
            const metricSelect = document.getElementById('distance-metric-select');
            const confirmBtn = document.getElementById('confirm-create-collection-btn');

            if (!nameInput || !vectorSizeInput || !metricSelect || !confirmBtn) return;

            const name = nameInput.value.trim();
            const vectorSize = parseInt(vectorSizeInput.value, 10);
            const metric = metricSelect.value || 'cosine';

            if (!name || Number.isNaN(vectorSize)) {
                showNotification('Please provide a collection name and vector size.', 'error');
                return;
            }

            const originalLabel = confirmBtn.innerHTML;
            confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
            confirmBtn.disabled = true;

            try {
                const response = await fetch(`/v1/qdrant/collections/${encodeURIComponent(name)}/create?vector_size=${vectorSize}&distance_metric=${encodeURIComponent(metric)}`, {
                    method: 'POST'
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to create collection');
                }
                showNotification(`Collection "${name}" created successfully.`, 'success');
                toggleCollectionModal(false);
                loadCollectionsData({ showLoader: true });
            } catch (error) {
                console.error('Create collection failed:', error);
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                confirmBtn.innerHTML = originalLabel;
                confirmBtn.disabled = false;
            }
        }

        function updateIngestButtonState() {
            const select = document.getElementById('ingest-collection-select');
            const fileInput = document.getElementById('ingest-file-input');
            const btn = document.getElementById('ingest-files-btn');
            if (!btn) return;
            const hasFiles = fileInput && fileInput.files && fileInput.files.length > 0;
            btn.disabled = !(select && select.value && hasFiles);
        }

        async function handleFileIngestion() {
            const select = document.getElementById('ingest-collection-select');
            const fileInput = document.getElementById('ingest-file-input');
            const btn = document.getElementById('ingest-files-btn');
            const status = document.getElementById('ingest-status');

            if (!select || !fileInput || !btn || !status) return;
            if (!select.value || !fileInput.files.length) {
                showNotification('Select a collection and at least one file to ingest.', 'error');
                return;
            }

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ingesting...';
            status.style.display = 'block';
            status.innerHTML = '<div class="loading">Uploading files...</div>';

            try {
                const formData = new FormData();
                Array.from(fileInput.files).forEach(file => formData.append('files', file));
                formData.append('chunk_size', '1000');
                formData.append('chunk_overlap', '100');
                formData.append('metadata', JSON.stringify({ uploaded_via: 'garage-ui' }));

                const response = await fetch(`/v1/qdrant/collections/${encodeURIComponent(select.value)}/ingest/files`, {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to ingest files');
                }
                status.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                showNotification('Files queued for ingestion.', 'success');
                fileInput.value = '';
                updateIngestButtonState();
                loadCollectionsData({ showLoader: false });
            } catch (error) {
                console.error('File ingestion error:', error);
                status.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        function updateSearchButtonState() {
            const select = document.getElementById('search-collection-select');
            const input = document.getElementById('search-text-input');
            const btn = document.getElementById('text-search-btn');
            if (!btn) return;
            btn.disabled = !(select && select.value && input && input.value.trim());
        }

        async function runTextSearch() {
            const select = document.getElementById('search-collection-select');
            const input = document.getElementById('search-text-input');
            const limitInput = document.getElementById('search-limit-input');
            const btn = document.getElementById('text-search-btn');
            const resultsArea = document.getElementById('search-results-area');

            if (!select || !input || !limitInput || !btn || !resultsArea) return;
            if (!select.value || !input.value.trim()) {
                showNotification('Provide a collection and search text.', 'error');
                return;
            }

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Searching...';
            resultsArea.style.display = 'block';
            resultsArea.innerHTML = '<div class="loading">Searching collection...</div>';

            try {
                const response = await fetch('/v1/qdrant/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        collection_name: select.value,
                        query_text: input.value.trim(),
                        limit: parseInt(limitInput.value, 10) || 5
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Search failed');
                }
                renderVectorSearchResults(data.results || [], resultsArea);
            } catch (error) {
                console.error('Vector search error:', error);
                resultsArea.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        function renderVectorSearchResults(results, container) {
            if (!container) return;
            if (!results || !results.length) {
                container.innerHTML = '<div class="empty">No matches found</div>';
                return;
            }

            const list = document.createElement('div');
            list.className = 'results-list';
            results.forEach(result => {
                const payload = result.payload || {};
                const text = payload.text || result.text || '';
                const item = document.createElement('div');
                item.className = 'result-item';
                item.innerHTML = `
                    <div class="result-content">${text.substring(0, 400)}${text.length > 400 ? '...' : ''}</div>
                    <div class="result-meta">
                        ${result.score ? `<span>Score: ${result.score.toFixed(2)}</span>` : ''}
                        ${payload.source_file ? `<span>Source: ${payload.source_file}</span>` : ''}
                    </div>
                `;
                list.appendChild(item);
            });
            container.innerHTML = '';
            container.appendChild(list);
        }

        async function runVectorQuery() {
            const collectionSelect = document.getElementById('query-collection');
            const vectorInput = document.getElementById('query-vector');
            const limitInput = document.getElementById('query-limit');
            const btn = document.getElementById('execute-query-btn');
            const resultsArea = document.getElementById('query-results');

            if (!collectionSelect || !vectorInput || !btn || !resultsArea) return;
            if (!collectionSelect.value || !vectorInput.value.trim()) {
                showNotification('Collection and vector values are required.', 'error');
                return;
            }

            const vector = vectorInput.value.split(',').map(v => parseFloat(v.trim())).filter(v => !Number.isNaN(v));
            if (!vector.length) {
                showNotification('Provide a comma-separated list of numbers for the vector.', 'error');
                return;
            }

            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Querying...';
            resultsArea.innerHTML = '<div class="loading">Querying vector space...</div>';

            try {
                const response = await fetch('/v1/qdrant/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        collection_name: collectionSelect.value,
                        query_vector: vector,
                        limit: parseInt(limitInput?.value, 10) || 10
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Query failed');
                }
                renderVectorSearchResults(data.results || data.matches || [], resultsArea);
            } catch (error) {
                console.error('Vector query error:', error);
                resultsArea.innerHTML = `<div class="error">${error.message}</div>`;
                showNotification(`❌ ${error.message}`, 'error');
            } finally {
                btn.innerHTML = original;
                btn.disabled = false;
            }
        }

        async function upsertPoints() {
            const collectionSelect = document.getElementById('points-collection');
            const payloadInput = document.getElementById('points-data');

            if (!collectionSelect || !payloadInput) return;
            if (!collectionSelect.value || !payloadInput.value.trim()) {
                showNotification('Provide a collection and JSON payload to upsert.', 'error');
                return;
            }

            let documents;
            try {
                const parsed = JSON.parse(payloadInput.value);
                documents = Array.isArray(parsed) ? parsed : [parsed];
            } catch (error) {
                showNotification('Invalid JSON payload.', 'error');
                return;
            }

            try {
                const response = await fetch(`/v1/qdrant/collections/${encodeURIComponent(collectionSelect.value)}/ingest/text?chunk_size=1000&chunk_overlap=100`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ documents })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to upsert points');
                }
                showNotification('Documents queued for ingestion.', 'success');
                loadCollectionsData({ showLoader: false });
            } catch (error) {
                console.error('Upsert error:', error);
                showNotification(`❌ ${error.message}`, 'error');
            }
        }

        async function deletePoints() {
            const collectionSelect = document.getElementById('points-collection');
            const idsInput = document.getElementById('points-to-delete');

            if (!collectionSelect || !idsInput) return;
            const ids = idsInput.value.split(',').map(id => id.trim()).filter(Boolean);
            if (!collectionSelect.value || !ids.length) {
                showNotification('Provide a collection and at least one point ID.', 'error');
                return;
            }

            if (!confirm(`Delete ${ids.length} point(s) from ${collectionSelect.value}?`)) {
                return;
            }

            try {
                const response = await fetch(`/v1/qdrant/collections/${encodeURIComponent(collectionSelect.value)}/points`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ point_ids: ids })
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to delete points');
                }
                showNotification('Points removed from collection.', 'success');
                idsInput.value = '';
                loadCollectionsData({ showLoader: false });
            } catch (error) {
                console.error('Delete points error:', error);
                showNotification(`❌ ${error.message}`, 'error');
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
                option.textContent = `${col.name} (${col.points_count || col.vectors_count || 0})`;
                select.appendChild(option);
            });

            if (previous) {
                select.value = previous;
            }
        } 