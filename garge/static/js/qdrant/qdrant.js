// Global error handler
window.addEventListener('error', function(e) {
    console.error('Global error caught:', e.error);
    if (e.error instanceof TypeError && e.error.message.includes('null')) {
        showNotification('Page not fully loaded. Please refresh.', 'error');
    }
});

// Handle promise rejections
window.addEventListener('unhandledrejection', function(e) {
    console.error('Unhandled promise rejection:', e.reason);
});
// Utility function for safe DOM value access
function safeGetElementValue(id) {
    const element = document.getElementById(id);
    return element ? element.value : null;
}

/**
 * Toggle advanced settings panel
 */
function toggleAdvancedSettings() {
    const panel = document.getElementById('advanced-settings');
    const btn = document.getElementById('toggle-advanced-btn');
    
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        btn.innerHTML = '<i class="fas fa-chevron-up"></i> Hide';
    } else {
        panel.style.display = 'none';
        btn.innerHTML = '<i class="fas fa-chevron-down"></i> Show';
    }
}

/**
 * Quick-set vector size
 */
function setVectorSize(size) {
    document.getElementById('vector-size').value = size;
    validateConfiguration(false);
}

/**
 * Use case templates with optimal configurations
 */
const USE_CASE_TEMPLATES = {
    legal_documents: {
        vectorSize: 768,
        distanceMetric: 'Cosine',
        contentType: 'legal',
        fileTypes: ['pdf', 'txt', 'docx'],
        onDiskPayload: true,
        hnswM: 32,
        hnswEfConstruct: 200,
        fullScanThreshold: 5000,
        description: 'Optimized for legal documents with high precision requirements'
    },
    transcripts: {
        vectorSize: 384,
        distanceMetric: 'Cosine',
        contentType: 'transcript',
        fileTypes: ['json', 'txt'],
        onDiskPayload: true,
        hnswM: 16,
        hnswEfConstruct: 100,
        fullScanThreshold: 10000,
        description: 'Balanced configuration for audio/video transcripts'
    },
    code: {
        vectorSize: 768,
        distanceMetric: 'Dot',
        contentType: 'code',
        fileTypes: ['txt', 'md', 'json'],
        onDiskPayload: false,
        hnswM: 16,
        hnswEfConstruct: 100,
        fullScanThreshold: 20000,
        description: 'Optimized for source code and technical documentation'
    },
    general: {
        vectorSize: 384,
        distanceMetric: 'Cosine',
        contentType: 'general',
        fileTypes: ['pdf', 'txt', 'json'],
        onDiskPayload: true,
        hnswM: 16,
        hnswEfConstruct: 100,
        fullScanThreshold: 10000,
        description: 'General purpose configuration for mixed content'
    }
};

// Add this right after the USE_CASE_TEMPLATES definition (around line 2400)

// Complete COLLECTION_PURPOSES configuration
const COLLECTION_PURPOSES = {
    'laws_regulations': {
        name: 'Laws & Regulations',
        description: 'Optimized for storing legal codes, statutes, and regulatory frameworks with article-level granularity.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 2000,
        chunkOverlap: 300,
        reasoning: 'Legal documents require high precision. 768d vectors capture nuanced legal language better than smaller models.',
        metricReason: 'Cosine distance works best for legal text where semantic similarity matters more than magnitude.',
        metadataFields: [
            '✓ <strong>jurisdiction</strong>: Country/region (e.g., "Brazil", "Chile")',
            '✓ <strong>framework_type</strong>: regulation, law, code, decree',
            '✓ <strong>legal_domain</strong>: consumer_protection, aviation, labor, etc.',
            '✓ <strong>articles</strong>: Array of article numbers',
            '✓ <strong>effective_date</strong>: When law became effective',
            '✓ <strong>issuing_authority</strong>: Legislative body',
            '✓ <strong>specificity_score</strong>: 0-1 (auto-calculated)'
        ],
        chunkingStrategy: [
            '• <strong>Article-Aware Chunking</strong>: Preserves article boundaries when possible',
            '• <strong>Citation Preservation</strong>: Maintains references intact',
            '• <strong>Large Overlap</strong>: 300 chars to capture cross-article context',
            '• <strong>Sentence Boundary Detection</strong>: Never splits mid-sentence'
        ],
        fileTypes: ['pdf', 'txt', 'docx', 'xml'],
        hnswM: 32,
        hnswEf: 200,
        fullScanThreshold: 5000
    },
    'legal_frameworks': {
        name: 'Legal Frameworks & Guidelines',
        description: 'For regulatory guidelines, compliance frameworks, and interpretive documents.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 1800,
        chunkOverlap: 250,
        reasoning: 'Frameworks often cross-reference other documents. 768d ensures accurate matching.',
        metricReason: 'Cosine captures semantic relationships between framework provisions.',
        metadataFields: [
            '✓ <strong>framework_name</strong>: Official name',
            '✓ <strong>jurisdiction</strong>: Applicable region',
            '✓ <strong>framework_type</strong>: guideline, circular, standard',
            '✓ <strong>version</strong>: Document version/revision',
            '✓ <strong>related_laws</strong>: Array of referenced laws',
            '✓ <strong>compliance_level</strong>: mandatory, recommended, best_practice'
        ],
        chunkingStrategy: [
            '• <strong>Section-Based Chunking</strong>: Groups related provisions',
            '• <strong>Cross-Reference Linking</strong>: Tracks document relationships',
            '• <strong>Hierarchy Preservation</strong>: Maintains parent-child structure'
        ],
        fileTypes: ['pdf', 'txt', 'md', 'docx'],
        hnswM: 24,
        hnswEf: 150,
        fullScanThreshold: 8000
    },
    'violation_reports': {
        name: 'Violation Reports & Findings',
        description: 'Stores identified violations, audit findings, and compliance issues.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1200,
        chunkOverlap: 150,
        reasoning: 'Violations are typically shorter. 384d is sufficient and faster.',
        metricReason: 'Cosine works well for matching similar violation patterns.',
        metadataFields: [
            '✓ <strong>violation_id</strong>: Unique identifier',
            '✓ <strong>violation_type</strong>: Classification',
            '✓ <strong>severity</strong>: critical, high, medium, low',
            '✓ <strong>detected_date</strong>: When violation was found',
            '✓ <strong>applicable_laws</strong>: Array of violated provisions'
        ],
        chunkingStrategy: [
            '• <strong>Violation-Level Granularity</strong>: Each violation as separate chunk',
            '• <strong>Context Inclusion</strong>: Includes surrounding circumstances'
        ],
        fileTypes: ['json', 'txt', 'pdf'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 10000
    },
    'audio_transcripts': {
        name: 'Audio/Call Transcripts (Diarized)',
        description: 'Optimized for speaker-diarized transcripts.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1000,
        chunkOverlap: 100,
        reasoning: 'Conversational text is shorter. 384d balances speed and accuracy.',
        metricReason: 'Cosine captures conversational similarity effectively.',
        metadataFields: [
            '✓ <strong>audio_id</strong>: Source recording identifier',
            '✓ <strong>speaker</strong>: Speaker identifier/name',
            '✓ <strong>segment_id</strong>: Utterance position',
            '✓ <strong>timestamp_start</strong>: Start time (seconds)',
            '✓ <strong>timestamp_end</strong>: End time (seconds)'
        ],
        chunkingStrategy: [
            '• <strong>Speaker Turn Chunking</strong>: Preserves individual utterances',
            '• <strong>Minimal Overlap</strong>: 100 chars (1-2 sentences)',
            '• <strong>Temporal Ordering</strong>: Maintains conversation flow'
        ],
        fileTypes: ['json', 'txt'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 15000
    },
    'compliance_audits': {
        name: 'Compliance Audits & Assessments',
        description: 'For audit reports and compliance evaluation documents.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 1500,
        chunkOverlap: 200,
        reasoning: 'Audit reports contain complex evaluations requiring nuanced understanding.',
        metricReason: 'Cosine captures assessment similarity across different compliance areas.',
        metadataFields: [
            '✓ <strong>audit_id</strong>: Unique audit identifier',
            '✓ <strong>audit_date</strong>: Date conducted',
            '✓ <strong>entity_audited</strong>: Organization/department',
            '✓ <strong>audit_type</strong>: internal, external, regulatory'
        ],
        chunkingStrategy: [
            '• <strong>Finding-Based Chunking</strong>: Groups related findings',
            '• <strong>Evidence Preservation</strong>: Keeps supporting data with findings'
        ],
        fileTypes: ['pdf', 'docx', 'txt', 'json'],
        hnswM: 24,
        hnswEf: 150,
        fullScanThreshold: 8000
    },
    'case_law': {
        name: 'Case Law & Jurisprudence',
        description: 'Court decisions and legal precedents.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 2000,
        chunkOverlap: 300,
        reasoning: 'Case law requires understanding complex legal reasoning.',
        metricReason: 'Cosine best for finding similar legal reasoning patterns.',
        metadataFields: [
            '✓ <strong>case_id</strong>: Court docket number',
            '✓ <strong>court</strong>: Court name',
            '✓ <strong>decision_date</strong>: Date of ruling',
            '✓ <strong>jurisdiction</strong>: Legal jurisdiction'
        ],
        chunkingStrategy: [
            '• <strong>Opinion-Based</strong>: Preserves judicial reasoning',
            '• <strong>Citation Tracking</strong>: Links to precedents'
        ],
        fileTypes: ['pdf', 'txt', 'docx'],
        hnswM: 32,
        hnswEf: 200,
        fullScanThreshold: 5000
    },
    'contracts': {
        name: 'Contracts & Agreements',
        description: 'Legal contracts and binding agreements.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 1500,
        chunkOverlap: 200,
        reasoning: 'Contracts have precise legal language requiring high-quality embeddings.',
        metricReason: 'Cosine for semantic similarity in contract clauses.',
        metadataFields: [
            '✓ <strong>contract_id</strong>: Unique identifier',
            '✓ <strong>parties</strong>: Contracting parties',
            '✓ <strong>effective_date</strong>: When contract begins',
            '✓ <strong>contract_type</strong>: Type of agreement'
        ],
        chunkingStrategy: [
            '• <strong>Clause-Based</strong>: Each clause as a chunk',
            '• <strong>Cross-Reference</strong>: Links related clauses'
        ],
        fileTypes: ['pdf', 'docx', 'txt'],
        hnswM: 24,
        hnswEf: 150,
        fullScanThreshold: 8000
    },
    'incident_records': {
        name: 'Incident Records & Complaints',
        description: 'Customer complaints and incident reports.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1000,
        chunkOverlap: 150,
        reasoning: 'Incidents are concise. 384d provides good performance.',
        metricReason: 'Cosine for finding similar complaint patterns.',
        metadataFields: [
            '✓ <strong>incident_id</strong>: Unique identifier',
            '✓ <strong>incident_date</strong>: When occurred',
            '✓ <strong>incident_type</strong>: Classification',
            '✓ <strong>severity</strong>: Impact level'
        ],
        chunkingStrategy: [
            '• <strong>Incident-Level</strong>: One chunk per incident',
            '• <strong>Context Retention</strong>: Includes timeline'
        ],
        fileTypes: ['json', 'txt', 'pdf'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 10000
    },
    'meeting_transcripts': {
        name: 'Meeting Transcripts',
        description: 'Business meeting transcripts and minutes.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1200,
        chunkOverlap: 150,
        reasoning: 'Meeting text is conversational. 384d is sufficient.',
        metricReason: 'Cosine for topic similarity across meetings.',
        metadataFields: [
            '✓ <strong>meeting_id</strong>: Unique identifier',
            '✓ <strong>meeting_date</strong>: Date held',
            '✓ <strong>participants</strong>: Attendees',
            '✓ <strong>meeting_type</strong>: Category'
        ],
        chunkingStrategy: [
            '• <strong>Topic-Based</strong>: Groups by discussion topic',
            '• <strong>Speaker Transitions</strong>: Respects turn-taking'
        ],
        fileTypes: ['txt', 'json', 'docx'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 12000
    },
    'customer_communications': {
        name: 'Customer Communications',
        description: 'Customer service interactions and correspondence.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1000,
        chunkOverlap: 100,
        reasoning: 'Customer messages are short. 384d is fast and effective.',
        metricReason: 'Cosine for finding similar customer issues.',
        metadataFields: [
            '✓ <strong>message_id</strong>: Unique identifier',
            '✓ <strong>customer_id</strong>: Customer reference',
            '✓ <strong>channel</strong>: Communication method',
            '✓ <strong>sentiment</strong>: Positive/negative/neutral'
        ],
        chunkingStrategy: [
            '• <strong>Message-Level</strong>: Each message as chunk',
            '• <strong>Thread Context</strong>: Links related messages'
        ],
        fileTypes: ['json', 'txt', 'csv'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 15000
    },
    'mixed_legal': {
        name: 'Mixed Legal Content',
        description: 'Flexible configuration for diverse legal documents.',
        vectorSize: 768,
        vectorModel: 'all-mpnet-base-v2 (768d)',
        distanceMetric: 'Cosine',
        chunkSize: 1500,
        chunkOverlap: 200,
        reasoning: 'Balanced configuration suitable for various legal document types.',
        metricReason: 'Cosine provides reliable similarity measurement across document types.',
        metadataFields: [
            '✓ <strong>document_type</strong>: law, regulation, transcript, violation, etc.',
            '✓ <strong>jurisdiction</strong>: Applicable region',
            '✓ <strong>legal_domain</strong>: Area of law'
        ],
        chunkingStrategy: [
            '• <strong>Adaptive Chunking</strong>: Adjusts based on content type',
            '• <strong>Standard Overlap</strong>: 200 chars for context'
        ],
        fileTypes: ['pdf', 'txt', 'json', 'md', 'docx'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 10000
    },
    'custom': {
        name: 'Custom Configuration',
        description: 'Manually configure all settings for specialized use cases.',
        vectorSize: 384,
        vectorModel: 'all-MiniLM-L6-v2 (384d)',
        distanceMetric: 'Cosine',
        chunkSize: 1500,
        chunkOverlap: 200,
        reasoning: 'Default settings. You can modify all parameters.',
        metricReason: 'Default to Cosine. Change based on your requirements.',
        metadataFields: [
            '• Configure metadata during ingestion based on your needs'
        ],
        chunkingStrategy: [
            '• Customize chunking parameters during ingestion'
        ],
        fileTypes: ['pdf', 'txt', 'json'],
        hnswM: 16,
        hnswEf: 100,
        fullScanThreshold: 10000
    }
};

// Add the missing createCollection function (simplified version for the old form)
async function createCollection() {
    const name = document.getElementById('collection-name').value.trim();
    const vectorSize = parseInt(document.getElementById('vector-size').value);
    const distanceMetric = document.getElementById('distance-metric').value;

    if (!name || !vectorSize) {
        showNotification('Please provide collection name and vector size', 'error');
        return;
    }

    try {
        const response = await fetch('/v1/qdrant/collections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                vector_size: vectorSize,
                distance_metric: distanceMetric
            })
        });

        if (response.ok) {
            showNotification(`Collection "${name}" created successfully!`, 'success');
            document.getElementById('create-collection-form').style.display = 'none';
            document.getElementById('collection-name').value = '';
            setTimeout(() => loadCollections(), 500);
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create collection');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

/**
 * Validate collection configuration
 */

function validateConfiguration(showNotifications = true) {
    const name = document.getElementById('collection-name').value.trim();
    const vectorSize = parseInt(document.getElementById('vector-size').value);
    const distanceMetric = document.getElementById('distance-metric').value;
    const hnswM = parseInt(document.getElementById('hnsw-m').value);
    const hnswEf = parseInt(document.getElementById('hnsw-ef-construct').value);
    
    const validationSummary = document.getElementById('validation-summary');
    const issues = [];
    const warnings = [];
    const tips = [];
    
    // Validate collection name
    if (!name) {
        issues.push('Collection name is required');
    } else if (!/^[a-z0-9_-]+$/.test(name)) {
        issues.push('Collection name should only contain lowercase letters, numbers, underscores, and hyphens');
    } else if (name.length < 3) {
        warnings.push('Collection name is very short. Consider a more descriptive name');
    }
    
    // Validate vector size
    if (!vectorSize || vectorSize < 1) {
        issues.push('Vector size must be a positive number');
    } else if (vectorSize > 4096) {
        warnings.push('Very large vector size may impact performance');
    } else if (![384, 768, 1024, 1536, 3072].includes(vectorSize)) {
        tips.push(`Vector size ${vectorSize} is non-standard. Ensure it matches your embedding model`);
    }
    
    // Validate HNSW parameters
    if (hnswM < 4 || hnswM > 64) {
        warnings.push('HNSW M parameter should be between 4 and 64');
    }
    if (hnswEf < 50) {
        warnings.push('Low EF Construct value may result in poor index quality');
    }
    
    // Memory estimation
    const estimatedMemoryPerDoc = vectorSize * 4 + 500; // bytes (4 bytes per float + payload overhead)
    const memoryFor10k = (estimatedMemoryPerDoc * 10000 / 1024 / 1024).toFixed(1);
    tips.push(`Estimated memory: ~${memoryFor10k} MB per 10,000 documents`);
    
    // Check if using recommended settings
    if (distanceMetric === 'Cosine' && vectorSize === 384) {
        tips.push('✓ Using recommended settings for text embeddings (fast & efficient)');
    }
    
    // Display validation results
    if (issues.length > 0 || warnings.length > 0 || tips.length > 0) {
        validationSummary.style.display = 'block';
        
        let summaryClass = 'validation-success';
        if (issues.length > 0) summaryClass = 'validation-error';
        else if (warnings.length > 0) summaryClass = 'validation-warning';
        
        validationSummary.className = summaryClass;
        
        let html = '<div style="font-size: 14px; line-height: 1.8;">';
        
        if (issues.length > 0) {
            html += '<div style="color: #991b1b; margin-bottom: 8px;"><strong>❌ Issues:</strong><ul style="margin: 4px 0 0 20px;">';
            issues.forEach(issue => html += `<li>${issue}</li>`);
            html += '</ul></div>';
        }
        
        if (warnings.length > 0) {
            html += '<div style="color: #92400e; margin-bottom: 8px;"><strong>⚠️ Warnings:</strong><ul style="margin: 4px 0 0 20px;">';
            warnings.forEach(warning => html += `<li>${warning}</li>`);
            html += '</ul></div>';
        }
        
        if (tips.length > 0) {
            html += '<div style="color: #065f46;"><strong>💡 Tips:</strong><ul style="margin: 4px 0 0 20px;">';
            tips.forEach(tip => html += `<li>${tip}</li>`);
            html += '</ul></div>';
        }
        
        html += '</div>';
        validationSummary.innerHTML = html;
        
        if (showNotifications) {
            if (issues.length > 0) {
                showNotification('Configuration has errors that must be fixed', 'error');
            } else if (warnings.length > 0) {
                showNotification('Configuration has warnings but can be created', 'warning');
            } else {
                showNotification('Configuration looks good!', 'success');
            }
        }
    } else {
        validationSummary.style.display = 'none';
    }
    
    return issues.length === 0;
}


document.addEventListener('DOMContentLoaded', async function() {
            setupEventListeners();
            checkConnection();
            const collections = await loadCollections();
            const { assistants, models } = await loadAssistantsAndModels();
            initWorkflowBuilder(collections, assistants, models);
        });
// Add this function near the top of your script section
function sanitizeJsonResponse(response) {
    if (typeof response !== 'string') {
        return response;
    }
    
    // Remove markdown code fences
    let cleaned = response.replace(/```json\s*/g, '').replace(/```\s*$/g, '');
    
    // Try to extract JSON if still wrapped in other text
    const jsonRegex = /(\{[\s\S]*\}|\[[\s\S]*\])/;
    const match = cleaned.match(jsonRegex);
    if (match) {
        cleaned = match[0];
    }
    
    try {
        return JSON.parse(cleaned);
    } catch (e) {
        console.error("JSON parsing failed:", e);
        return { error: "Failed to parse JSON", raw_content: response };
    }
}


        // --- Global State ---
        let allCollectionsData = [];
        let savedSteps = [];
        let availableAssistants = [];
        let availableModels = [];
        let chatHistory = [];
        let lastQueryResults = []; // NEW: To store search results

        // Replace the setupEventListeners function (around line 2300-2450)
        
        function setupEventListeners() {
            // DOMContentLoaded protection and required element existence warnings
            const requiredElements = [
                'enhanced-collection-select',
                'enhanced-file-upload',
                'structured-collection-select',
                'ingest-collection-select'
            ];
            requiredElements.forEach(id => {
                if (!document.getElementById(id)) {
                    console.warn(`Element #${id} not found in DOM`);
                }
            });

            // Tab switching
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    this.classList.add('active');
                    document.getElementById(`${this.dataset.tab}-tab`).classList.add('active');
                });
            });
        
            // Collection management
            const createCollectionBtn = document.getElementById('create-collection-btn');
            if (createCollectionBtn) {
                createCollectionBtn.addEventListener('click', openCreateCollectionModal);
            }
        
            const cancelCollectionBtn = document.getElementById('cancel-collection-btn');
            if (cancelCollectionBtn) {
                cancelCollectionBtn.addEventListener('click', () => {
                    document.getElementById('create-collection-form').style.display = 'none';
                });
            }
        
            const refreshCollectionsBtn = document.getElementById('refresh-collections-btn');
            if (refreshCollectionsBtn) {
                refreshCollectionsBtn.addEventListener('click', loadCollections);
            }
        
            const submitCollectionBtn = document.getElementById('submit-collection-btn');
            if (submitCollectionBtn) {
                submitCollectionBtn.addEventListener('click', createCollection);
            }
        
            const collectionsList = document.getElementById('collections-list');
            if (collectionsList) {
                collectionsList.addEventListener('click', handleCollectionCardClick);
            }

            // Ingestion & Querying 
            const ingestCollectionSelect = document.getElementById('ingest-collection-select');
            if (!ingestCollectionSelect) {
                console.error('Ingest collection select not found');
            }
            const ingestFilesBtn = document.getElementById('ingest-files-btn');
            if (ingestFilesBtn) {
                ingestFilesBtn.addEventListener('click', ingestFiles);
            }
        
            const querySearchBtn = document.getElementById('query-search-btn');
            if (querySearchBtn) {
                querySearchBtn.addEventListener('click', searchCollection);
            }
        
            const loadQueryResultsBtn = document.getElementById('load-query-results-btn');
            if (loadQueryResultsBtn) {
                loadQueryResultsBtn.addEventListener('click', loadQueryResults);
            }
        
            // Chat UI
            const chatSendBtn = document.getElementById('chat-send-btn');
            if (chatSendBtn) {
                chatSendBtn.addEventListener('click', sendChatMessage);
            }
        
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.addEventListener('keypress', e => { 
                    if (e.key === 'Enter' && !e.shiftKey) { 
                        e.preventDefault(); 
                        sendChatMessage(); 
                    } 
                });
            }
        
            const chatAssistantSelect = document.getElementById('chat-assistant-select');
            if (chatAssistantSelect) {
                chatAssistantSelect.addEventListener('change', handleAssistantSelection);
            }
        
            document.querySelectorAll('.quick-prompt-btn').forEach(btn => {
                btn.addEventListener('click', handleQuickPrompt);
            });
        
            const saveChatBtn = document.getElementById('save-chat-btn');
            if (saveChatBtn) {
                saveChatBtn.addEventListener('click', saveChatHistory);
            }
        
            const loadChatBtn = document.getElementById('load-chat-btn');
            if (loadChatBtn) {
                loadChatBtn.addEventListener('click', loadChatHistory);
            }
        
            const clearChatBtn = document.getElementById('clear-chat-btn');
            if (clearChatBtn) {
                clearChatBtn.addEventListener('click', clearChatHistory);
            }
        
            // Enhanced ingestion mode toggle
            const ingestModeSelect = document.getElementById('ingest-mode-select');
            if (ingestModeSelect) {
                ingestModeSelect.addEventListener('change', function() {
                    const filePanel = document.getElementById('file-ingest-panel');
                    const structuredPanel = document.getElementById('structured-ingest-panel');
                    const enhancedPanel = document.getElementById('enhanced-ingest-panel');
                    
                    if (filePanel) filePanel.style.display = 'none';
                    if (structuredPanel) structuredPanel.style.display = 'none';
                    if (enhancedPanel) enhancedPanel.style.display = 'none';
                    
                    if (this.value === 'file' && filePanel) {
                        filePanel.style.display = 'block';
                    } else if (this.value === 'structured' && structuredPanel) {
                        structuredPanel.style.display = 'block';
                    } else if (this.value === 'enhanced' && enhancedPanel) {
                        enhancedPanel.style.display = 'block';
                    }
                });
            }
        
            // Enhanced ingestion buttons
            const enhancedIngestBtn = document.getElementById('enhanced-ingest-btn');
            if (enhancedIngestBtn) {
                enhancedIngestBtn.addEventListener('click', startEnhancedIngestion);
            }
        
            const createMetadataBtn = document.getElementById('create-sample-metadata-btn');
            if (createMetadataBtn) {
                createMetadataBtn.addEventListener('click', generateSampleMetadata);
            }
        
            // Validation button
            const validateConfigBtn = document.getElementById('validate-config-btn');
            if (validateConfigBtn) {
                validateConfigBtn.addEventListener('click', () => {
                    if (validateConfiguration(true)) {
                        showConfigurationSummary();
                    }
                });
            }
        
            // Collection name input validation
            const collectionNameInput = document.getElementById('collection-name');
            if (collectionNameInput) {
                collectionNameInput.addEventListener('input', function() {
                    const purpose = document.getElementById('collection-purpose');
                    if (purpose && purpose.value) {
                        if (this.value.trim().length > 0) {
                            validateConfiguration(false);
                            if (this.value.trim().length >= 3) {
                                showConfigurationSummary();
                            }
                        }
                    }
                });
            }
        
            // Modal event listeners
            const collectionDetailsModal = document.getElementById('collection-details-modal');
            if (collectionDetailsModal) {
                const closeBtn = collectionDetailsModal.querySelector('.modal-close');
                if (closeBtn) {
                    closeBtn.addEventListener('click', () => collectionDetailsModal.style.display = 'none');
                }
                window.addEventListener('click', e => { 
                    if (e.target == collectionDetailsModal) {
                        collectionDetailsModal.style.display = 'none';
                    }
                });
            }
        
            // Cross-connections modal
            const findCrossConnectionsBtn = document.getElementById('find-cross-connections-btn');
            if (findCrossConnectionsBtn) {
                findCrossConnectionsBtn.addEventListener('click', openCrossConnectionsModal);
            }
        
            const confirmCrossConnectionsBtn = document.getElementById('confirm-cross-connections-btn');
            if (confirmCrossConnectionsBtn) {
                confirmCrossConnectionsBtn.addEventListener('click', confirmCrossConnections);
            }
        
            const cancelCrossConnectionsBtn = document.getElementById('cancel-cross-connections-btn');
            if (cancelCrossConnectionsBtn) {
                cancelCrossConnectionsBtn.addEventListener('click', closeCrossConnectionsModal);
            }
        
            const crossModal = document.getElementById('cross-connections-modal');
            if (crossModal) {
                const crossCloseBtn = crossModal.querySelector('.modal-close');
                if (crossCloseBtn) {
                    crossCloseBtn.addEventListener('click', closeCrossConnectionsModal);
                }
                window.addEventListener('click', e => { 
                    if (e.target == crossModal) {
                        closeCrossConnectionsModal();
                    }
                });
            }
        
            // Cross-collection selector interactivity
            const crossCollectionsContainer = document.getElementById('cross-collections-options');
            if (crossCollectionsContainer) {
                crossCollectionsContainer.addEventListener('click', (e) => {
                    if (!e.target.matches('input[type="checkbox"]')) {
                        crossCollectionsContainer.classList.toggle('open');
                    }
                });
            }
        
            // Saved steps container
            const stepsContainer = document.getElementById('saved-steps-container');
            if (stepsContainer) {
                stepsContainer.addEventListener('click', (e) => {
                    if (!e.target.matches('input[type="checkbox"]')) {
                        stepsContainer.classList.toggle('open');
                    }
                });
                
                document.addEventListener('click', (e) => {
                    if (!stepsContainer.contains(e.target)) {
                        stepsContainer.classList.remove('open');
                    }
                });
            }
        
        }

        function isExternalAssistant(assistant) {
            const metadata = assistant?.metadata || {};
            const provider = String(metadata.llm_provider || '').toLowerCase();
            const urlFormat = String(metadata.llm_url_format || '').toLowerCase();

            if (metadata.type === 'external') return true;
            if (provider && provider !== 'ollama' && provider !== 'local') return true;
            if (urlFormat && urlFormat !== 'ollama' && urlFormat !== 'local') return true;
            return false;
        }

        function handleAssistantSelection() {
            const modelSelect = document.getElementById('chat-model-select');
            const endpointInput = document.getElementById('chat-endpoint-input');
            const assistantSelect = document.getElementById('chat-assistant-select');
            const selectedAssistantId = assistantSelect.value;
            const assistant = availableAssistants.find(a => a.id === selectedAssistantId);

            if (assistant) { // An assistant IS selected
                modelSelect.disabled = true;
                endpointInput.disabled = false; // Endpoint is now determined automatically
                
                // NEW: Show the user which endpoint will be used
                if (isExternalAssistant(assistant)) {
                    endpointInput.value = 'External API (auto-selected)';
                } else {
                    endpointInput.value = 'Local API (auto-selected)';
                }
                showNotification('Assistant selected. Endpoint is now managed automatically.', 'info');
            } else { // No assistant (Manual RAG mode)
                modelSelect.disabled = false;
                endpointInput.disabled = false;
                endpointInput.value = '/v1/assistants/${assistant_id}/chat'; // Restore default for manual mode
                showNotification('Switched to Manual RAG mode.', 'info');
            }
        }

        // ...existing code...
        function handleQuickPrompt() {
            if (this.id === 'find-cross-connections-btn') return;  // Skip sending message for this button
            document.getElementById('chat-input').value = this.dataset.prompt;
            sendChatMessage();
        }

        function handleCollectionCardClick(event) {
            const deleteButton = event.target.closest('.delete-collection');
            if (deleteButton) {
                event.stopPropagation();
                deleteCollection(deleteButton.dataset.name);
                return;
            }
            const collectionCard = event.target.closest('.collection-card');
            if (collectionCard) {
                showCollectionDetails(collectionCard.dataset.name);
            }
        }

        // --- API Calls & Data Loading ---
        async function checkConnection() {
            const statusDiv = document.getElementById('connection-status');
            try {
                const response = await fetch('/v1/qdrant/connect', { method: 'POST' });
                if (!response.ok) throw new Error('Connection failed');
                const data = await response.json();
                statusDiv.className = 'status-badge success';
                statusDiv.innerHTML = `<i class="fas fa-check-circle"></i><span>Connected</span>`;
            } catch (error) {
                statusDiv.className = 'status-badge error';
                statusDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i><span>Connection Failed</span>`;
            }
        }

        async function loadAssistantsAndModels() {
            try {
                const [assistantsRes, modelsRes] = await Promise.all([
                    fetch('/v1/assistants/'),
                    fetch('/v1/models')
                ]);

                if (assistantsRes.ok) {
                    const data = await assistantsRes.json();
                    availableAssistants = data.data || [];
                    const selects = document.querySelectorAll('#chat-assistant-select, #step-ai-assistant-select');
                    selects.forEach(select => {
                        select.innerHTML = '<option value="">Manual RAG (No Assistant)</option>';
                        availableAssistants.forEach(a => select.innerHTML += `<option value="${a.id}">${a.name} (${a.model})</option>`);
                    });
                }

                if (modelsRes.ok) {
                    const data = await modelsRes.json();
                    availableModels = data.data || [];
                    const selects = document.querySelectorAll('#chat-model-select, #step-ai-model-select');
                    selects.forEach(select => {
                        select.innerHTML = '<option value="">Select a model...</option>';
                        availableModels.forEach(m => select.innerHTML += `<option value="${m.id}">${m.id}</option>`);
                    });
                }
                return { assistants: availableAssistants, models: availableModels };
            } catch (error) {
                showNotification('Failed to load assistants or models.', 'error');
                return { assistants: [], models: [] };
            }
        }


/**
 * Start enhanced ingestion with quality validation and legal extraction
 */
async function startEnhancedIngestion() {
    const collectionName = document.getElementById('enhanced-collection-select').value;
    const fileInput = document.getElementById('enhanced-file-upload');
    const statusDiv = document.getElementById('ingestion-status-area');
    const ingestBtn = document.getElementById('enhanced-ingest-btn');

    if (!collectionName) {
        showNotification('Please select a target collection.', 'error');
        return;
    }

    if (fileInput.files.length === 0) {
        showNotification('Please select at least one file to upload.', 'error');
        return;
    }

    // Collect metadata
    const metadata = {
        framework_type: document.getElementById('enhanced-framework-type').value,
        jurisdiction: document.getElementById('enhanced-jurisdiction').value.trim(),
        legal_domain: document.getElementById('enhanced-legal-domain').value.trim(),
        specificity_level: document.getElementById('enhanced-specificity').value,
        language: document.getElementById('enhanced-language').value,
        authority: document.getElementById('enhanced-authority').value.trim() || null
    };

    // Collect configuration
    const config = {
        chunk_size: parseInt(document.getElementById('enhanced-chunk-size').value),
        chunk_overlap: parseInt(document.getElementById('enhanced-chunk-overlap').value),
        with_mpnet: document.getElementById('enhanced-dense-vectors').checked,
        skip_existing: document.getElementById('enhanced-skip-existing').checked,
        validate_before_ingest: document.getElementById('enhanced-validate-before').checked
    };

    // Validation checks
    if (!metadata.jurisdiction || metadata.jurisdiction === 'unknown') {
        if (!confirm('Jurisdiction is not specified. Continue anyway?')) {
            return;
        }
    }

    if (config.chunk_size < 500 || config.chunk_size > 5000) {
        showNotification('Chunk size must be between 500 and 5000 characters.', 'error');
        return;
    }

    if (config.chunk_overlap >= config.chunk_size) {
        showNotification('Chunk overlap must be less than chunk size.', 'error');
        return;
    }

    statusDiv.style.display = 'block';
    statusDiv.innerHTML = `
        <div style="text-align:center;padding:20px">
            <div class="loading-spinner" style="margin:0 auto 12px"></div>
            <div style="font-weight:700;margin-bottom:8px">Starting Enhanced Ingestion</div>
            <div style="font-size:13px;color:#666">
                Processing ${fileInput.files.length} file(s) with:
            </div>
            <div style="margin-top:12px;text-align:left;max-width:400px;margin-left:auto;margin-right:auto;font-size:12px;color:#555;line-height:1.8">
                ✓ Chunk size: ${config.chunk_size} chars (overlap: ${config.chunk_overlap})<br>
                ✓ Framework: ${metadata.framework_type} (${metadata.jurisdiction})<br>
                ✓ Domain: ${metadata.legal_domain}<br>
                ✓ Validation: ${config.validate_before_ingest ? 'Enabled' : 'Disabled'}<br>
                ✓ Deduplication: ${config.skip_existing ? 'Enabled' : 'Disabled'}
            </div>
        </div>
    `;
    ingestBtn.disabled = true;

    try {
        // Build the request body
        const requestBody = {
            directory: null, // Not using directory mode
            with_mpnet: config.with_mpnet,
            collection_name: collectionName,
            chunk_size: config.chunk_size,
            chunk_overlap: config.chunk_overlap,
            skip_existing: config.skip_existing,
            validate_before_ingest: config.validate_before_ingest
        };

        // If only one file, use single file upload endpoint with metadata
        if (fileInput.files.length === 1) {
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
        
            // Add source_name for single file
            const singleFileMetadata = { ...metadata, source_name: fileInput.files[0].name };
            const metadataParam = encodeURIComponent(JSON.stringify(singleFileMetadata));
            const url = `/v1/qdrant/collections/${collectionName}/ingest/file?metadata=${metadataParam}`;
        
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });
            // ...existing code...

            const result = await response.json();

            if (response.ok) {
                displayIngestionResults(result, statusDiv, 'single');
                fileInput.value = '';
                loadCollections();
            } else {
                throw new Error(result.detail || 'Enhanced ingestion failed');
            }
        } else {
            // Multiple files - need to upload each with metadata
            let totalChunks = 0;
            let totalErrors = 0;
            const fileResults = [];

            // ...inside startEnhancedIngestion, before the multi-file loop...
            // ...existing code...
            for (const file of fileInput.files) {
                // Define fileMetadata before using it
                const fileMetadata = { ...metadata, source_name: file.name };
            
                const formData = new FormData();
                formData.append('metadata', JSON.stringify(fileMetadata));
                formData.append('files', file); // backend accepts multiple files; append per-file
                const url = `/v1/qdrant/collections/${collectionName}/ingest/legacy`;
            
                try {
                    const response = await fetch(url, {
                        method: 'POST',
                        body: formData
                    });
            
                    const result = await response.json();
            
                    if (response.ok) {
                        totalChunks += result.chunks_created || 0;
                        fileResults.push({
                            filename: file.name,
                            status: 'success',
                            chunks: result.chunks_created,
                            upserted: result.upserted
                        });
                    } else {
                        totalErrors++;
                        fileResults.push({
                            filename: file.name,
                            status: 'error',
                            error: result.detail || 'Unknown error'
                        });
                    }
                } catch (error) {
                    totalErrors++;
                    fileResults.push({
                        filename: file.name,
                        status: 'error',
                        error: error.message
                    });
                }
            
                // Update progress
                statusDiv.innerHTML = `
                    <div style="text-align:center;padding:20px">
                        <div class="loading-spinner" style="margin:0 auto 12px"></div>
                        <div style="font-weight:700;margin-bottom:8px">Processing Files</div>
                        <div style="font-size:13px;color:#666">
                            ${fileResults.length} of ${fileInput.files.length} completed
                        </div>
                    </div>
                `;
            }
            // ...existing code...

            // Display final results
            const summaryResult = {
                status: totalErrors > 0 ? 'completed_with_errors' : 'completed',
                chunks_ingested: totalChunks,
                files_processed: fileResults.length,
                errors: fileResults.filter(r => r.status === 'error').map(r => r.error),
                file_details: fileResults
            };

            displayIngestionResults(summaryResult, statusDiv, 'multiple');
            fileInput.value = '';
            loadCollections();
        }

        showNotification('Enhanced ingestion completed!', 'success');

    } catch (error) {
        statusDiv.innerHTML = `
            <div style="padding:20px;text-align:center">
                <div style="font-size:48px;color:var(--danger);margin-bottom:12px">⚠️</div>
                <div style="font-weight:700;color:var(--danger);margin-bottom:8px">Ingestion Failed</div>
                <div style="color:#666">${escapeHtml(error.message)}</div>
            </div>
        `;
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        ingestBtn.disabled = false;
    }
}

/**
 * Display enhanced ingestion results with detailed metrics
 */
function displayIngestionResults(result, container, mode) {
    let html = '';

    if (mode === 'single') {
        html = `
            <div style="padding:20px">
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
                    <div style="width:64px;height:64px;background:linear-gradient(135deg,#10b981,#059669);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:32px">
                        <i class="fas fa-check"></i>
                    </div>
                    <div>
                        <div style="font-size:24px;font-weight:700;color:#059669">Success!</div>
                        <div style="color:#666">File processed successfully</div>
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px">
                    <div style="background:#f0fdf4;padding:14px;border-radius:8px;border-left:4px solid #10b981">
                        <div style="font-size:11px;color:#166534;font-weight:600">CHUNKS CREATED</div>
                        <div style="font-size:28px;font-weight:700;color:#059669">${result.chunks_created || 0}</div>
                    </div>
                    <div style="background:#f0fdf4;padding:14px;border-radius:8px;border-left:4px solid #10b981">
                        <div style="font-size:11px;color:#166534;font-weight:600">CHUNKS UPSERTED</div>
                        <div style="font-size:28px;font-weight:700;color:#059669">${result.upserted || 0}</div>
                    </div>
                </div>

                <div style="font-size:13px;color:#666">
                    <strong>File:</strong> ${result.filename || 'Unknown'}<br>
                    <strong>Status:</strong> ${result.status}
                </div>
            </div>
        `;
    } else if (mode === 'multiple') {
        const successCount = result.file_details.filter(f => f.status === 'success').length;
        const errorCount = result.file_details.filter(f => f.status === 'error').length;

        html = `
            <div style="padding:20px">
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
                    <div style="width:64px;height:64px;background:linear-gradient(135deg,${errorCount > 0 ? '#f59e0b,#d97706' : '#10b981,#059669'});border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:32px">
                        <i class="fas ${errorCount > 0 ? 'fa-exclamation-triangle' : 'fa-check'}"></i>
                    </div>
                    <div>
                        <div style="font-size:24px;font-weight:700;color:${errorCount > 0 ? '#d97706' : '#059669'}">${errorCount > 0 ? 'Completed with Errors' : 'All Files Processed'}</div>
                        <div style="color:#666">${successCount} succeeded, ${errorCount} failed</div>
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px">
                    <div style="background:#f0fdf4;padding:14px;border-radius:8px;border-left:4px solid #10b981">
                        <div style="font-size:11px;color:#166534;font-weight:600">TOTAL CHUNKS</div>
                        <div style="font-size:28px;font-weight:700;color:#059669">${result.chunks_ingested || 0}</div>
                    </div>
                    <div style="background:#f0fdf4;padding:14px;border-radius:8px;border-left:4px solid #10b981">
                        <div style="font-size:11px;color:#166534;font-weight:600">FILES PROCESSED</div>
                        <div style="font-size:28px;font-weight:700;color:#059669">${result.files_processed || 0}</div>
                    </div>
                    <div style="background:#fef3c7;padding:14px;border-radius:8px;border-left:4px solid #f59e0b">
                        <div style="font-size:11px;color:#92400e;font-weight:600">ERRORS</div>
                        <div style="font-size:28px;font-weight:700;color:#d97706">${errorCount}</div>
                    </div>
                </div>

                <div style="max-height:300px;overflow-y:auto">
                    <h4 style="margin-bottom:12px">File Details</h4>
                    ${result.file_details.map(file => `
                        <div style="background:${file.status === 'success' ? '#f0fdf4' : '#fef2f2'};padding:12px;border-radius:6px;margin-bottom:8px;border-left:3px solid ${file.status === 'success' ? '#10b981' : '#ef4444'}">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                                <div style="font-weight:600;color:${file.status === 'success' ? '#059669' : '#dc2626'}">${escapeHtml(file.filename)}</div>
                                <div style="font-size:11px;padding:2px 8px;border-radius:10px;background:${file.status === 'success' ? '#059669' : '#dc2626'};color:white">
                                    ${file.status.toUpperCase()}
                                </div>
                            </div>
                            ${file.status === 'success' ? `
                                <div style="font-size:12px;color:#166534">
                                    Chunks: ${file.chunks || 0} | Upserted: ${file.upserted || 0}
                                </div>
                            ` : `
                                <div style="font-size:12px;color:#991b1b">
                                    Error: ${escapeHtml(file.error || 'Unknown error')}
                                </div>
                            `}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

/**
 * Generate a sample .meta.json file for download
 */
function generateSampleMetadata() {
    const sampleMetadata = {
        source_name: "Brazilian Consumer Defense Code",
        source_id: "BR_CDC_1990",
        framework_type: "code",
        jurisdiction: "Brazil",
        legal_domain: "consumer_protection",
        specificity_level: "specific",
        articles: ["1", "2", "3", "6", "14", "18"],
        sections: [],
        effective_date: "1990-09-11",
        supersedes: null,
        authority: "Brazilian National Congress",
        language: "pt-BR",
        source_url: "http://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm"
    };

    const blob = new Blob([JSON.stringify(sampleMetadata, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sample_document.meta.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showNotification('Sample metadata file downloaded! Place it next to your document with the same name.', 'success');
}

/**
 * Show a richer “detail + actions” view in modal.
 */
async function viewCollectionDetails(collectionName) {
    const collection = allCollectionsData.find(c => c.name === collectionName || c.collection_name === collectionName);
    if (!collection) {
        showNotification('Collection not found', 'error');
        return;
    }
    const modal = document.getElementById('collection-details-modal');
    const modalTitle = document.getElementById('modal-collection-name');
    const modalBody = document.getElementById('modal-collection-details');

    modalTitle.textContent = `Collection: ${collectionName}`;

    // Try to re-derive info for display
    const vectorSize = collection.config?.vectors?.default?.size
                      ?? collection.vectors_config?.params?.size
                      ?? collection.size
                      ?? 'N/A';

    const distanceMetric = collection.config?.vectors?.default?.distance
                          ?? collection.vectors_config?.params?.distance
                          ?? collection.metric
                          ?? collection.distance
                          ?? 'N/A';

    const docsCount = collection.points_count ?? collection.vectors_count ?? 0;

    modalBody.innerHTML = `
      <div style="margin-bottom: 20px;">
        <h3>Collection Information</h3>
        <div style="background: #f3f3f3; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
          <p><strong>Name:</strong> ${collectionName}</p>
          <p><strong>Vector Size:</strong> ${vectorSize}</p>
          <p><strong>Distance Metric:</strong> ${distanceMetric}</p>
          <p><strong>Documents (points):</strong> ${docsCount.toLocaleString()}</p>
        </div>

        <h4>Actions</h4>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <button class="btn btn-primary" onclick="performSearchInCollection('${collectionName}')">
            <i class="fas fa-search"></i> Search This Collection
          </button>
          <button class="btn btn-secondary" onclick="browseCollectionPoints('${collectionName}')">
            <i class="fas fa-eye"></i> Browse Points
          </button>
          <button class="btn btn-secondary" onclick="exportCollectionData('${collectionName}')">
            <i class="fas fa-download"></i> Export Data
          </button>
        </div>

        <h4 style="margin-top: 20px;">Full Configuration / Raw Data</h4>
        <pre style="background: #f3f3f3; padding: 12px; border-radius: 6px; max-height: 300px; overflow-y: auto;">${JSON.stringify(collection, null, 2)}</pre>
      </div>
    `;

    modal.style.display = 'block';
}



// Replace the modal-related functions (around line 4200-4400)

/**
 * Open create collection modal and initialize
 */
function openCreateCollectionModal() {
    const modal = document.getElementById('create-collection-modal');
    resetCreateCollectionModalForm();
    modal.style.display = 'block';
}

/**
 * Close create collection modal
 */
function closeCreateCollectionModal() {
    document.getElementById('create-collection-modal').style.display = 'none';
}

/**
 * Reset modal form to defaults
 */
function resetCreateCollectionModalForm() {
    document.getElementById('modal-collection-name-input').value = '';
    document.getElementById('modal-collection-purpose').value = '';
    document.getElementById('modal-vector-size').value = 384;
    document.getElementById('modal-distance-metric').value = 'Cosine';
    document.getElementById('modal-validation-summary').style.display = 'none';
    document.getElementById('modal-submit-collection-btn').disabled = true;
    
    // Hide purpose description
    document.getElementById('modal-purpose-description').style.display = 'none';
}

/**
 * Enhanced validation for modal inputs
 */
function validateModalConfiguration(showNotifications = true) {
    const name = document.getElementById('modal-collection-name-input').value.trim();
    const purpose = document.getElementById('modal-collection-purpose').value;
    const vectorSize = parseInt(document.getElementById('modal-vector-size').value);
    
    const validationSummary = document.getElementById('modal-validation-summary');
    const issues = [];
    const warnings = [];
    const tips = [];
    
    console.log('Validation check:', { name, purpose, vectorSize }); // Debug log
    
    // Validate purpose
    if (!purpose) {
        issues.push('Please select a collection purpose');
    }
    
    // Validate collection name
    if (!name) {
        issues.push('Collection name is required');
    } else if (!/^[a-z0-9_-]+$/.test(name)) {
        issues.push('Collection name should only contain lowercase letters, numbers, underscores, and hyphens');
    } else if (name.length < 3) {
        warnings.push('Collection name is very short. Use descriptive names like "br_consumer_laws"');
    }
    
    // Validate vector size
    if (!vectorSize || vectorSize < 1) {
        issues.push('Vector size must be a positive number');
    } else if (vectorSize > 4096) {
        warnings.push('Very large vector size may impact performance');
    } else if (![384, 768, 1024, 1536, 3072].includes(vectorSize)) {
        tips.push(`Vector size ${vectorSize} is non-standard. Ensure it matches your embedding model`);
    }
    
    // Memory estimation
    const estimatedMemoryPerDoc = vectorSize * 4 + 500;
    const memoryFor10k = (estimatedMemoryPerDoc * 10000 / 1024 / 1024).toFixed(1);
    tips.push(`Estimated memory: ~${memoryFor10k} MB per 10,000 documents`);
    
    // Display results
    if (issues.length > 0 || warnings.length > 0 || tips.length > 0) {
        validationSummary.style.display = 'block';
        
        let summaryClass = 'validation-success';
        if (issues.length > 0) summaryClass = 'validation-error';
        else if (warnings.length > 0) summaryClass = 'validation-warning';
        
        validationSummary.className = summaryClass;
        
        let html = '<div style="font-size: 14px; line-height: 1.8;">';
        
        if (issues.length > 0) {
            html += '<div style="color: #991b1b; margin-bottom: 8px;"><strong>❌ Issues:</strong><ul style="margin: 4px 0 0 20px;">';
            issues.forEach(issue => html += `<li>${issue}</li>`);
            html += '</ul></div>';
        }
        
        if (warnings.length > 0) {
            html += '<div style="color: #92400e; margin-bottom: 8px;"><strong>⚠️ Warnings:</strong><ul style="margin: 4px 0 0 20px;">';
            warnings.forEach(warning => html += `<li>${warning}</li>`);
            html += '</ul></div>';
        }
        
        if (tips.length > 0) {
            html += '<div style="color: #065f46;"><strong>💡 Tips:</strong><ul style="margin: 4px 0 0 20px;">';
            tips.forEach(tip => html += `<li>${tip}</li>`);
            html += '</ul></div>';
        }
        
        html += '</div>';
        validationSummary.innerHTML = html;
        
        if (showNotifications) {
            if (issues.length > 0) {
                showNotification('Configuration has errors. Please fix them.', 'error');
                document.getElementById('modal-submit-collection-btn').disabled = true;
            } else {
                showNotification('Configuration validated successfully!', 'success');
                document.getElementById('modal-submit-collection-btn').disabled = false;
            }
        }
    } else {
        validationSummary.style.display = 'none';
        document.getElementById('modal-submit-collection-btn').disabled = false;
    }
    
    return issues.length === 0;
}

/**
 * Handle purpose selection in modal
 */
document.addEventListener('DOMContentLoaded', function() {
    const purposeSelect = document.getElementById('modal-collection-purpose');
    if (purposeSelect) {
        purposeSelect.addEventListener('change', function() {
            const purpose = this.value;
            const descDiv = document.getElementById('modal-purpose-description');
            
            if (!purpose) {
                descDiv.style.display = 'none';
                return;
            }
            
            const config = COLLECTION_PURPOSES[purpose];
            if (config) {
                descDiv.style.display = 'block';
                descDiv.innerHTML = `
                    <strong>${config.name}</strong><br>
                    ${config.description}<br><br>
                    <strong>Auto-configured settings:</strong><br>
                    • Vector Size: ${config.vectorSize}d (${config.vectorModel})<br>
                    • Distance: ${config.distanceMetric}<br>
                    • Chunk Size: ${config.chunkSize} chars<br>
                    • Overlap: ${config.chunkOverlap} chars
                `;
                
                // Auto-fill settings
                document.getElementById('modal-vector-size').value = config.vectorSize;
                document.getElementById('modal-distance-metric').value = config.distanceMetric;
                
                showNotification(`Template applied: ${config.name}`, 'info');
            }
            
            validateModalConfiguration(false);
        });
    }
    
    // Validate on name input
    const nameInput = document.getElementById('modal-collection-name-input');
    if (nameInput) {
        nameInput.addEventListener('input', function() {
            const purpose = document.getElementById('modal-collection-purpose').value;
            if (purpose && this.value.trim().length >= 3) {
                validateModalConfiguration(false);
            }
        });
    }
    
    // Validate button
    const validateBtn = document.getElementById('modal-validate-config-btn');
    if (validateBtn) {
        validateBtn.addEventListener('click', () => validateModalConfiguration(true));
    }
    
    // Submit button
    const submitBtn = document.getElementById('modal-submit-collection-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', createCollectionFromModal);
    }
});

/**
 * Create collection from modal
 */
async function createCollectionFromModal() {
    if (!validateModalConfiguration(true)) {
        return;
    }
    
    const name = document.getElementById('modal-collection-name-input').value.trim();
    const purpose = document.getElementById('modal-collection-purpose').value;
    const vectorSize = parseInt(document.getElementById('modal-vector-size').value);
    const distanceMetric = document.getElementById('modal-distance-metric').value;
    
    const config = COLLECTION_PURPOSES[purpose];
    
    try {
        const payload = {
            name: name,
            vector_size: vectorSize,
            distance_metric: distanceMetric,
            metadata: {
                created_at: new Date().toISOString(),
                created_from: 'qdrant-manager-ui-v2',
                purpose: purpose,
                purpose_config: config.name,
                vector_config: {
                    size: vectorSize,
                    distance: distanceMetric,
                    model_recommended: config.vectorModel
                },
                description: `${config.name} collection`,
                tags: ['user-created', 'ui-v2', purpose]
            },
            on_disk_payload: true,
            hnsw_config: {
                m: config.hnswM,
                ef_construct: config.hnswEf,
                full_scan_threshold: config.fullScanThreshold
            }
        };
        
        const submitBtn = document.getElementById('modal-submit-collection-btn');
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        submitBtn.disabled = true;
        
        const response = await fetch('/v1/qdrant/collections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            showNotification(`Collection "${name}" created successfully!`, 'success');
            closeCreateCollectionModal();
            setTimeout(() => loadCollections(), 500);
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create collection');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        const submitBtn = document.getElementById('modal-submit-collection-btn');
        submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Create Collection';
        submitBtn.disabled = false;
    }
}


        async function deleteCollection(collectionName) {
            if (!confirm(`Are you sure you want to delete the collection "${collectionName}"? This is permanent.`)) {
                return;
            }
            try {
                const response = await fetch(`/v1/qdrant/collections/${collectionName}`, { method: 'DELETE' });
                if (response.ok) {
                    showNotification(`Collection "${collectionName}" deleted.`, 'success');
                    loadCollections();
                } else {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to delete collection');
                }
            } catch (error) {
                showNotification(`Error: ${error.message}`, 'error');
            }
        }
        async function ingestFiles() {
            const collectionName = document.getElementById('ingest-collection-select').value;
            const fileInput = document.getElementById('file-upload');
            const statusDiv = document.getElementById('ingestion-status-area');
            const ingestBtn = document.getElementById('ingest-files-btn');
            if (statusDiv) {
                statusDiv.style.display = 'none';
            }
            if (!collectionName) {
                showNotification('Please select a target collection.', 'error');
                return;
            }
            if (fileInput.files.length === 0) {
                showNotification('Please select at least one file to upload.', 'error');
                return;
            }

            const formData = new FormData();
            for (const file of fileInput.files) {
                formData.append('files', file);
            }

            statusDiv.style.display = 'block';
            statusDiv.innerHTML = `<p>Uploading and processing ${fileInput.files.length} file(s)...</p>`;
            ingestBtn.disabled = true;

            try {
                const response = await fetch(`/v1/qdrant/collections/${collectionName}/ingest`, {
                    method: 'POST',
                    body: formData,
                });
                const result = await response.json();

                if (response.ok) {
                    let statusHTML = `<p style="color:var(--success);">${result.message}</p>`;
                    if (result.errors && result.errors.length > 0) {
                        statusHTML += `<p style="color:var(--danger);">Some files failed:</p><ul>`;
                        result.errors.forEach(e => { statusHTML += `<li>${e.file}: ${e.error}</li>`; });
                        statusHTML += `</ul>`;
                    }
                    statusDiv.innerHTML = statusHTML;
                    showNotification('Ingestion process completed!', 'success');
                    fileInput.value = '';
                    loadCollections();
                } else {
                    throw new Error(result.detail || 'Ingestion failed');
                }
            } catch (error) {
                statusDiv.innerHTML = `<p style="color:var(--danger);">Error: ${error.message}</p>`;
                showNotification(`Error: ${error.message}`, 'error');
            } finally {
                ingestBtn.disabled = false;
            }
        }

        async function searchCollection() {
            const collectionName = document.getElementById('query-collection-select').value;
            const queryText = document.getElementById('query-text-input').value.trim();
            const limit = document.getElementById('query-limit-input').value;
            const resultsArea = document.getElementById('query-results-area');
            const searchBtn = document.getElementById('query-search-btn');

            if (!collectionName || !queryText) {
                showNotification('Please select a collection and enter a query.', 'error');
                return;
            }

            resultsArea.style.display = 'block';
            resultsArea.innerHTML = '<p>Searching...</p>';
            searchBtn.disabled = true;

            try {
                const response = await fetch('/v1/qdrant/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        collection_name: collectionName,
                        query_text: queryText,
                        limit: parseInt(limit)
                    })
                });

                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || 'Search failed');
                }

                lastQueryResults = result.results || []; // Store results
                renderQueryResults(); // Render results

            } catch (error) {
                resultsArea.innerHTML = `<p style="color:var(--danger);">Error: ${error.message}</p>`;
                showNotification(`Error: ${error.message}`, 'error');
            } finally {
                searchBtn.disabled = false;
            }
        }

        function renderQueryResults() {
            const resultsArea = document.getElementById('query-results-area');
            resultsArea.style.display = 'block';

            if (lastQueryResults.length > 0) {
                let html = `
                    <div class="action-bar" style="justify-content: flex-end; margin-bottom: 10px;">
                        <button class="btn btn-sm btn-secondary" onclick="saveQueryResults()">
                            <i class="fas fa-download"></i> Save Results
                        </button>
                    </div>
                    <h3>Search Results</h3>
                `;
                lastQueryResults.forEach(hit => {
                    html += `
                        <div class="search-result-card">
                            <div class="result-score">Score: ${hit.score.toFixed(4)}</div>
                            <div class="result-source">Source: ${hit.payload.source || 'N/A'}</div>
                            <div class="result-text">${hit.payload.text || 'No text in payload.'}</div>
                        </div>
                    `;
                });
                resultsArea.innerHTML = html;
            } else {
                resultsArea.innerHTML = '<p>No results found.</p>';
            }
        }

        function saveQueryResults() {
            if (lastQueryResults.length === 0) {
                showNotification('No results to save.', 'error');
                return;
            }
            const collectionName = document.getElementById('query-collection-select').value;
            const dataToSave = {
                collection: collectionName,
                query: document.getElementById('query-text-input').value,
                timestamp: new Date().toISOString(),
                results: lastQueryResults
            };
            const blob = new Blob([JSON.stringify(dataToSave, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `query_results_${collectionName || 'unsaved'}_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showNotification('Query results saved!', 'success');
        }

        async function loadQueryResults() {
            const fileInput = document.getElementById('query-file-input');
            fileInput.click();
            fileInput.onchange = function() {
                const file = fileInput.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(e) {
                    try {
                        const data = JSON.parse(e.target.result);
                        if (data.results && Array.isArray(data.results)) {
                            lastQueryResults = data.results;
                            if (data.collection) document.getElementById('query-collection-select').value = data.collection;
                            if (data.query) document.getElementById('query-text-input').value = data.query;
                            renderQueryResults();
                            showNotification('Query results loaded!', 'success');
                        } else {
                            throw new Error('Invalid query results file format.');
                        }
                    } catch (error) {
                        showNotification(`Error loading results: ${error.message}`, 'error');
                    }
                };
                reader.readAsText(file);
                fileInput.value = ''; // Reset for next load
            };
        }

        // --- Core Chat Logic (CONSOLIDATED) ---
        /**
         * Appends a message to the chat UI
         * @param {string} content - Message content
         * @param {string} role - 'user' or 'assistant'
         * @param {boolean} isThinking - Whether this is a "thinking" indicator
         * @returns {HTMLElement} The message element
         */
        function appendMessage(content, role, isThinking = false) {
            const chatMessages = document.getElementById('chat-messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `chat-message ${role}`;
            
            if (isThinking) {
                // Create typing indicator
                messageDiv.innerHTML = `
                    <div class="chat-bubble ${role}">
                        <div class="typing-indicator">
                            <span>Thinking</span>
                            <div class="typing-dot"></div>
                            <div class="typing-dot"></div>
                            <div class="typing-dot"></div>
                        </div>
                    </div>
                `;
            } else {
                // Handle normal messages with proper rendering
                let formattedContent = content;
                
                // Check if content has markdown code blocks
                if (content.includes('```')) {
                    // Use a regex to find code blocks and wrap them
                    formattedContent = content.replace(/```(\w*)([\s\S]*?)```/g, function(match, language, code) {
                        return `<pre class="code-block ${language}"><code>${escapeHtml(code.trim())}</code></pre>`;
                    });
                }
                
                // Process line breaks (convert \n to <br>)
                formattedContent = formattedContent.replace(/\n/g, '<br>');
                
                messageDiv.innerHTML = `<div class="chat-bubble ${role}">${formattedContent}</div>`;
            }
            
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight; // Auto-scroll to bottom
            return messageDiv;
        }


        async function sendChatMessage() {
            const assistantId = document.getElementById('chat-assistant-select').value;
            const userMessage = document.getElementById('chat-input').value.trim();
            if (!userMessage) return;

            appendMessage(userMessage, 'user');
            document.getElementById('chat-input').value = '';
            const thinkingIndicator = appendMessage('', 'assistant', true);
            chatHistory.push({ role: 'user', content: userMessage });

            try {
                let aiResponse;
                if (assistantId) {
                    aiResponse = await sendAssistantChatMessage(assistantId);
                } else {
                    aiResponse = await sendManualRagChatMessage();
                }
                thinkingIndicator.remove();
                appendMessage(aiResponse, 'assistant');
                chatHistory.push({ role: 'assistant', content: aiResponse });
            } catch (error) {
                thinkingIndicator.remove();
                const errorBubble = appendMessage(`Error: ${error.message}`, 'assistant');
                errorBubble.querySelector('.chat-bubble').style.backgroundColor = 'var(--danger)';
                errorBubble.querySelector('.chat-bubble').style.color = 'white';
                chatHistory.pop(); // Remove failed user message from history
            }
        }



        // Add function to render violations in a structured way (if used in your system)
        function renderViolations(response) {
            if (!response.violations || response.violations.length === 0) {
                return response.raw_text || "No violations found.";
            }
            
            let html = `<strong>Detected ${response.violations.length} potential violations:</strong><br><br>`;
            
            response.violations.forEach((v, i) => {
                html += `<strong>${i+1}. ${v.regulation || 'Unknown Regulation'}</strong><br>`;
                html += `${v.description || 'No description'}<br>`;
                if (v.explanation) html += `<em>Explanation: ${v.explanation}</em><br>`;
                html += "<br>";
            });
            
            if (response.additional_findings && response.additional_findings.length > 0) {
                html += "<br><strong>Additional Findings:</strong><br>";
                response.additional_findings.forEach((finding, i) => {
                    html += `${i+1}. ${finding}<br>`;
                });
            }
            
            if (response.recommendations && response.recommendations.length > 0) {
                html += "<br><strong>Recommendations:</strong><br>";
                response.recommendations.forEach((rec, i) => {
                    html += `${i+1}. ${rec}<br>`;
                });
            }
            
            return html;
        }

        // Helper function for safely parsing JSON
        function safeJSONParse(text) {
            try {
                return JSON.parse(text);
            } catch (e) {
                return { raw_text: text };
            }
        }

        function tryParseJson(text) {
            try {
                return JSON.parse(text);
            } catch (e) {
                return null;
            }
        }

        function extractNestedErrorText(value) {
            if (typeof value !== 'string') return '';

            const raw = value.trim();
            if (!raw) return '';

            // Common pattern: "Ollama API error 404: {\"error\":{\"message\":\"model ... not found\"}}"
            const marker = ': {';
            const markerIndex = raw.indexOf(marker);
            if (markerIndex > -1) {
                const suffix = raw.slice(markerIndex + 2).trim();
                const parsedSuffix = tryParseJson(suffix);
                if (parsedSuffix) {
                    const nested = getErrorMessageFromPayload(parsedSuffix);
                    if (nested) return nested;
                }
            }

            const parsedRaw = tryParseJson(raw);
            if (parsedRaw) {
                const nested = getErrorMessageFromPayload(parsedRaw);
                if (nested) return nested;
            }

            return raw;
        }

        function getErrorMessageFromPayload(payload) {
            if (!payload || typeof payload !== 'object') return '';
            if (typeof payload.detail === 'string') {
                const detail = extractNestedErrorText(payload.detail);
                if (detail) return detail;
            }
            if (typeof payload.message === 'string') {
                const message = extractNestedErrorText(payload.message);
                if (message) return message;
            }
            if (payload.error) {
                if (typeof payload.error === 'string') {
                    const errorText = extractNestedErrorText(payload.error);
                    if (errorText) return errorText;
                }
                if (typeof payload.error.message === 'string') {
                    const errorMessage = extractNestedErrorText(payload.error.message);
                    if (errorMessage) return errorMessage;
                }
                if (typeof payload.error.detail === 'string') {
                    const errorDetail = extractNestedErrorText(payload.error.detail);
                    if (errorDetail) return errorDetail;
                }
            }
            return '';
        }

        function getContentFromPayload(payload) {
            if (!payload || typeof payload !== 'object') return '';

            const choice = payload.choices?.[0];
            const messageContent = choice?.message?.content;
            if (typeof messageContent === 'string') return messageContent;

            const deltaContent = choice?.delta?.content;
            if (typeof deltaContent === 'string') return deltaContent;

            if (typeof payload.response === 'string') return payload.response;
            if (typeof payload.content === 'string') return payload.content;
            if (typeof payload.text === 'string') return payload.text;

            return '';
        }

        async function readStreamingChatResponse(response) {
            const reader = response.body?.getReader?.();
            if (!reader) return '';

            const decoder = new TextDecoder();
            let buffer = '';
            let raw = '';
            let aggregated = '';

            const handleLine = (rawLine) => {
                let line = String(rawLine || '').trim();
                if (!line) return;
                if (line.startsWith('data:')) line = line.slice(5).trim();
                if (!line || line === '[DONE]') return;

                const parsed = tryParseJson(line);
                if (!parsed) {
                    return;
                }

                const payloadError = getErrorMessageFromPayload(parsed);
                if (payloadError) {
                    throw new Error(payloadError);
                }

                const piece = getContentFromPayload(parsed);
                if (piece) {
                    aggregated += piece;
                }
            };

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunkText = decoder.decode(value, { stream: true });
                raw += chunkText;
                buffer += chunkText;

                const lines = buffer.split(/\r?\n/);
                buffer = lines.pop() || '';

                for (const line of lines) {
                    handleLine(line);
                }
            }

            const tail = decoder.decode();
            if (tail) {
                raw += tail;
                buffer += tail;
            }

            if (buffer.trim()) {
                const finalParts = buffer.split(/\r?\n/);
                for (const line of finalParts) {
                    handleLine(line);
                }
            }

            if (aggregated.trim()) {
                return aggregated;
            }

            const rawTrimmed = raw.trim();
            if (!rawTrimmed) return '';

            const parsedRaw = tryParseJson(rawTrimmed);
            if (parsedRaw) {
                const payloadError = getErrorMessageFromPayload(parsedRaw);
                if (payloadError) throw new Error(payloadError);

                const rawContent = getContentFromPayload(parsedRaw);
                if (rawContent) return rawContent;
            }

            return rawTrimmed;
        }

        async function parseChatResponse(response, streamRequested) {
            if (!response.ok) {
                let errorMessage = `Server returned status ${response.status}`;
                try {
                    const err = await response.json();
                    errorMessage = getErrorMessageFromPayload(err) || errorMessage;
                } catch (e) {
                    try {
                        const text = await response.text();
                        if (text && text.trim()) errorMessage = text.trim();
                    } catch (_) {
                        // Keep status-based fallback when response body is unreadable.
                    }
                }
                throw new Error(errorMessage);
            }

            if (streamRequested) {
                const streamedText = await readStreamingChatResponse(response);
                if (streamedText && streamedText.trim()) {
                    return streamedText;
                }
                throw new Error('Empty streaming response from assistant');
            }

            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const data = await response.json();
                const payloadError = getErrorMessageFromPayload(data);
                if (payloadError) throw new Error(payloadError);

                const content = getContentFromPayload(data);
                if (content) return content;

                throw new Error('No response content from model');
            }

            const text = await response.text();
            if (text && text.trim()) return text;

            throw new Error('Empty response from model');
        }
        
        function clearChatHistory() {
            if (confirm('Are you sure you want to clear the chat history?')) {
                chatHistory = [];
                const chatMessages = document.getElementById('chat-messages');
                chatMessages.innerHTML = `
                    <div class="chat-message assistant">
                        <div class="chat-bubble">
                            Hello! I'm your AI assistant for exploring the data in your Qdrant collections. 
                            Select a collection and ask me anything about its content.
                        </div>
                    </div>
                `;
                showNotification('Chat history cleared.', 'info');
            }
        }

        async function getRagContext() {
            const collectionName = document.getElementById('chat-collection-select').value;
            const userMessage = chatHistory[chatHistory.length - 1].content;

            if (!document.getElementById('include-search-results').checked) {
                return null; // RAG is disabled by the user
            }
            if (!collectionName) {
                throw new Error("To include search results, you must select a collection.");
            }

            try {
                const searchLimit = document.getElementById('chat-limit-input').value;
                const searchResponse = await fetch('/v1/qdrant/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ collection_name: collectionName, query_text: userMessage, limit: parseInt(searchLimit) })
                });
                if (searchResponse.ok) {
                    const searchData = await searchResponse.json();
                    if (searchData.results?.length > 0) {
                        return "--- CONTEXT FROM DATABASE ---\n" + searchData.results.map(hit => hit.payload.text).join("\n---\n");
                    }
                    return "No relevant context found in the database.";
                }
                return "Warning: Could not retrieve context from the database.";
            } catch (e) {
                console.error("Failed to fetch RAG context:", e);
                return "Error: Failed to fetch context from the database.";
            }
        }

        async function sendAssistantChatMessage(assistantId) {
            const assistant = availableAssistants.find(a => a.id === assistantId);
            if (!assistant) throw new Error("Selected assistant not found.");

            const context = await getRagContext();
            const messages = [...chatHistory];

            if (context) {
                const systemPrompt = `Before answering, review the following context which has been retrieved from a vector database based on the user's query. Use this information to provide a more accurate and relevant response.\n\n${context}`;
                messages.unshift({ role: "system", content: systemPrompt });
            }
            
            // --- NEW: Dynamic Endpoint Routing for Assistants ---
            let endpoint = '';
            if (isExternalAssistant(assistant)) {
                // This is an external assistant like DeepSeek
                endpoint = `/v1/assistants/deepseek-stream-proxy`;
            } else {
                // This is a local assistant
                endpoint = `/v1/assistants/${assistantId}/chat`;
            }
            // --- END NEW ROUTING LOGIC ---

            const streamRequested = document.getElementById('stream-responses').checked;
            const payload = {
                model: assistant.model,
                messages: messages,
                stream: streamRequested
            };
            document.getElementById('chat-payload-preview').textContent = JSON.stringify(payload, null, 2);

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            return await parseChatResponse(response, streamRequested);
        }

        async function sendManualRagChatMessage() {
            const collectionName = document.getElementById('chat-collection-select').value;
            const model = document.getElementById('chat-model-select').value;
            const userMessage = chatHistory[chatHistory.length - 1].content;
        
            // Validation
            if (!collectionName) {
                throw new Error("Please select a collection for Manual RAG chat.");
            }
            if (!model) {
                throw new Error("Please select a Model for Manual RAG chat.");
            }
        
            // Build context from search (if enabled)
            let context = "No relevant context found.";
            if (document.getElementById('include-search-results').checked) {
                try {
                    const searchLimit = parseInt(document.getElementById('chat-limit-input').value) || 3;
                    
                    // FIX: Validate payload before sending
                    const searchPayload = {
                        collection_name: collectionName,
                        query_text: userMessage,
                        limit: searchLimit
                    };
                    
                    console.log('Search payload:', searchPayload); // Debug log
                    
                    const searchResponse = await fetch('/v1/qdrant/search', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(searchPayload)
                    });
                    
                    if (!searchResponse.ok) {
                        const errorData = await searchResponse.json().catch(() => ({}));
                        console.error('Search error response:', errorData);
                        throw new Error(errorData.detail || `Search failed with status ${searchResponse.status}`);
                    }
                    
                    const searchData = await searchResponse.json();
                    if (searchData.results?.length > 0) {
                        context = "--- CONTEXT FROM DATABASE ---\n" + 
                            searchData.results
                                .map(hit => hit.payload?.text || JSON.stringify(hit))
                                .join("\n---\n");
                    }
                } catch (e) {
                    console.error("RAG context fetch error:", e);
                    context = `Warning: Failed to fetch context. ${e.message}`;
                }
            }
        
            const systemPrompt = `You are a helpful assistant. Answer the user's question based ONLY on the following context. If the context doesn't contain the answer, say you don't have enough information.\n\n${context}`;
            
            const messages = [
                { role: "system", content: systemPrompt },
                ...chatHistory
            ];
        
            const streamRequested = document.getElementById('stream-responses').checked || false;
            const payload = {
                model: model,
                messages: messages,
                stream: streamRequested
            };
            
            document.getElementById('chat-payload-preview').textContent = JSON.stringify(payload, null, 2);
        
            console.log('Chat payload:', payload); // Debug log
        
            // FIX: Correct endpoint routing
            let endpoint = '/v1/chat/completions'; // Standard OpenAI-compatible endpoint
            
            // If model is DeepSeek, use specialized endpoint
            if (model && (model.includes('deepseek') || model.includes('reasoner'))) {
                endpoint = '/v1/chat/completions'; // DeepSeek also uses standard endpoint
            }
        
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
        
                return await parseChatResponse(response, streamRequested);
                
            } catch (error) {
                console.error('Full error details:', error);
                throw new Error(`Chat failed: ${error.message}`);
            }
        }

        // --- Ingestion Mode Toggle ---
        const ingestModeSelect = document.getElementById('ingest-mode-select');
        if (ingestModeSelect) {
            ingestModeSelect.addEventListener('change', function() {
                const filePanel = document.getElementById('file-ingest-panel');
                const structuredPanel = document.getElementById('structured-ingest-panel');
                const enhancedPanel = document.getElementById('enhanced-ingest-panel');

                if (filePanel) filePanel.style.display = 'none';
                if (structuredPanel) structuredPanel.style.display = 'none';
                if (enhancedPanel) enhancedPanel.style.display = 'none';

                if (this.value === 'file' && filePanel) {
                    filePanel.style.display = 'block';
                } else if (this.value === 'structured' && structuredPanel) {
                    structuredPanel.style.display = 'block';
                    if (typeof updateStructuredButtonState === 'function') updateStructuredButtonState();
                } else if (this.value === 'enhanced' && enhancedPanel) {
                    enhancedPanel.style.display = 'block';
                }
            });
        }

        // REVISED: Fully revised executeWorkflow function with frontend context handling
        async function executeWorkflow() {
            const workflowContainer = document.getElementById('workflow-steps-order');
            const stepElements = Array.from(workflowContainer.querySelectorAll('.workflow-step'));
            const resultsArea = document.getElementById('workflow-results-area');
            const executeBtn = document.getElementById('workflow-execute-btn');

            if (stepElements.length === 0) {
                showNotification('Please add at least one step to the workflow.', 'error');
                return;
            }

            resultsArea.style.display = 'block';
            resultsArea.innerHTML = `
                <div class="action-bar" style="justify-content: space-between; align-items: center;">
                    <h3>Workflow Results</h3>
                    <button class="btn btn-sm btn-secondary" onclick="saveWorkflowOutput()">
                        <i class="fas fa-download"></i> Save Output
                    </button>
                </div>
            `;
            executeBtn.disabled = true;

            let executionContext = {};

            for (let i = 0; i < stepElements.length; i++) {
                const stepElement = stepElements[i];
                const stepId = stepElement.dataset.stepId;
                const stepConfig = savedSteps.find(s => s.id === stepId);
                
                const resultPlaceholder = document.createElement('div');
                resultPlaceholder.innerHTML = `<h4>Step ${i + 1}: ${stepConfig.name}</h4><p>Executing...</p>`;
                resultsArea.appendChild(resultPlaceholder);

                try {
                    let stepResult;
                    // NEW: Check for the special passenger regulation search step
                    if (stepConfig.name.includes('[PASSENGER-REG-SEARCH]')) {
                        stepResult = await executePassengerRegulationSearch(stepConfig, executionContext);
                    } else if (stepConfig.type === 'search') {
                        stepResult = await executeSearchStep(stepConfig, executionContext);
                    } else if (stepConfig.type === 'ai_call') {
                        stepResult = await executeAiCallStep(stepConfig, executionContext);
                    }

                    if (stepElement.dataset.passContext === 'true') {
                        executionContext[`step_${i + 1}_result`] = JSON.stringify(stepResult, null, 2);
                    }
                    
                    renderIndividualStepResult(stepConfig, stepResult, i, resultPlaceholder);

                } catch (error) {
                    resultPlaceholder.innerHTML = `<h4>Step ${i + 1}: ${stepConfig.name}</h4><p style="color:var(--danger);">Error: ${error.message}</p>`;
                    showNotification(`Error in step ${i + 1}: ${error.message}`, 'error');
                    break;
                }
            }

            executeBtn.disabled = false;
            showNotification('Workflow execution finished.', 'success');
        }

        // NEW: Add the new custom workflow step logic based on the Python snippet
        /**
         * Custom step to find, filter, and prioritize passenger-focused regulations.
         * Mirrors the logic from the provided Python snippet.
         * @param {object} stepConfig - The configuration for the current step.
         * @param {object} context - The execution context from previous steps.
         * @returns {string} A JSON string of the formatted references.
         */
        async function executePassengerRegulationSearch(stepConfig, context) {
            // 1. Get the search query from the step's description, processing context variables
            let query = stepConfig.description;
            for (const key in context) {
                query = query.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), context[key]);
            }

            // 2. Search for regulations using the existing search endpoint
            const searchResponse = await fetch('/v1/qdrant/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    collection_name: stepConfig.collection,
                    query_text: query,
                    limit: stepConfig.parameters?.limit || 15 // Fetch more to allow for filtering
                })
            });
            const searchResult = await searchResponse.json();
            if (!searchResponse.ok) throw new Error(searchResult.detail || 'Regulation search failed');
            
            const docs = searchResult.results || [];

            // 3. Filter for passenger-focused content (from search_regulations)
            const passengerKeywords = ["passenger", "boarding", "delay", "cancellation", "consumer"];
            const filteredDocs = docs.filter(doc => {
                // Check against keywords in payload if they exist, otherwise check text
                const contentToCheck = (doc.payload?.keywords || doc.payload?.text || "").toLowerCase();
                return passengerKeywords.some(kw => contentToCheck.includes(kw));
            });

            // 4. Format the references with priority levels (from format_references)
            const formatted = [];
            const priorityTitles = ["Res. ANAC 400/2016", "RBAC 121", "CDC"];
            
            filteredDocs.forEach(doc => {
                const title = doc.payload?.title || doc.payload?.source || "Unknown Document";
                const priority = priorityTitles.some(pt => title.includes(pt)) ? 1 : 2;
                
                formatted.push({
                    "document_title": title,
                    "article_section": doc.payload?.article || doc.payload?.section || "",
                    "text_excerpt": doc.payload?.text || "",
                    "priority_level": priority,
                    "score": doc.score
                });
            });

            // 5. Sort by priority and then by score
            formatted.sort((a, b) => {
                if (a.priority_level !== b.priority_level) {
                    return a.priority_level - b.priority_level;
                }
                return (b.score || 0) - (a.score || 0); // Higher score first
            });

            // 6. Return the final formatted list (as an object, not a string, for consistency)
            return formatted;
        }

        // REVISED: Helper function to execute a single search step
        async function executeSearchStep(stepConfig, context) {
            let queryText = stepConfig.description;
            for (const key in context) {
                queryText = queryText.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), context[key]);
            }

            const response = await fetch('/v1/qdrant/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    collection_name: stepConfig.collection,
                    query_text: queryText,
                    limit: stepConfig.parameters?.limit || 5
                })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Search step failed');
            return result.results; // Returns an array
        }

        // ...existing code...
        async function executeAiCallStep(stepConfig, context) {
            let prompt = stepConfig.ai_config.prompt_template;
            
            // Add schema enforcement to the prompt
            const schemaPrefix = "Respond ONLY with a valid JSON object. Do not include markdown fences (```), explanations, or extra text.\n\n";
            prompt = schemaPrefix + prompt;
            
            for (const key in context) {
                const value = context[key].replace(/^"|"$/g, '');
                prompt = prompt.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), value);
            }
        
            const payload = {
                model: stepConfig.ai_config.model || 'lfm2.5:8b:8b',
                messages: [{ role: 'user', content: prompt }],
                ...stepConfig.parameters
            };
        
            // FIX: Correct the response_format parameter if it exists and is incorrect.
            if (payload.response_format && payload.response_format === 'json') {
                payload.response_format = { "type": "json_object" };
            }
        
            let attempts = 0;
            const maxAttempts = 2;
            
            while (attempts < maxAttempts) {
                attempts++;
                try {
                    const response = await fetch("/v1/assistants/deepseek-stream-proxy", {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    
                    const result = await response.json();
                    if (!response.ok) {
                        const errorMessage = result.detail || (result.error ? result.error.message : 'AI step failed');
                        throw new Error(`DeepSeek API error ${response.status}: ${errorMessage}`);
                    }
                    
                    // Extract content from the response
                    if (result.choices && result.choices.length > 0) {
                        const content = result.choices[0].message.content;
                        
                        // Try to parse and validate JSON
                        try {
                            const parsedContent = sanitizeJsonResponse(content);
                            result.choices[0].message.parsed_content = parsedContent;
                            return result;
                        } catch (parseError) {
                            if (attempts < maxAttempts) {
                                // Retry with more explicit JSON instructions
                                payload.messages = [
                                    { role: 'user', content: prompt },
                                    { role: 'assistant', content: content },
                                    { role: 'user', content: "Your response contains formatting issues. Return the same content as strict JSON without any markdown formatting, explanations, or text outside the JSON object." }
                                ];
                                continue; // Try again
                            } else {
                                throw parseError;
                            }
                        }
                    }
                    
                    return result;
                } catch (error) {
                    if (attempts >= maxAttempts) {
                        throw error;
                    }
                    // If it's the first attempt, retry with more explicit instructions
                    payload.messages.push({ 
                        role: 'user', 
                        content: "Your previous response had formatting issues. Respond ONLY with a valid JSON object. No markdown, no explanations."
                    });
                }
            }
        }

        // ...existing code...
        function renderIndividualStepResult(stepConfig, resultData, index, container) {
            let previewHtml;
            let fullDataJson;
            
            // Handle AI responses with potential JSON parsing issues
            if (stepConfig.type === 'ai_call') {
                if (resultData.choices?.length > 0) {
                    // Check if we have successfully parsed JSON content
                    if (resultData.choices[0].message.parsed_content) {
                        fullDataJson = JSON.stringify(resultData.choices[0].message.parsed_content, null, 2);
                        previewHtml = `<div style="white-space: pre-wrap;">${fullDataJson}</div>`;
                    } else {
                        // Fall back to raw content
                        const aiContent = resultData.choices[0].message.content;
                        
                        // Try to sanitize the content
                        try {
                            const sanitized = sanitizeJsonResponse(aiContent);
                            fullDataJson = JSON.stringify(sanitized, null, 2);
                            previewHtml = `<div style="white-space: pre-wrap;">${fullDataJson}</div>`;
                        } catch (e) {
                            fullDataJson = JSON.stringify(resultData, null, 2);
                            previewHtml = `<div style="white-space: pre-wrap;">${aiContent}</div>`;
                        }
                    }
                } else {
                    fullDataJson = JSON.stringify(resultData, null, 2);
                    previewHtml = `<pre style="white-space: pre-wrap; font-size: 14px;">${fullDataJson}</pre>`;
                }
            } else if (stepConfig.type === 'search' && Array.isArray(resultData)) {
                // Normalize search results into a schema
                const normalizedResults = {
                    schema_version: "1.0",
                    laws: resultData.map(item => ({
                        law_id: item.id,
                        law_ref: item.payload.file_path || "Unknown",
                        law_type: "Penal Code",
                        text: item.payload.text,
                        relevance_score: item.score,
                        metadata: item.payload.metadata || {}
                    }))
                };
                
                fullDataJson = JSON.stringify(normalizedResults, null, 2);
                
                previewHtml = `
                    <div><strong>Found ${resultData.length} results:</strong></div>
                    ${resultData.slice(0, 3).map((item, idx) => `
                        <div style="margin: 8px 0; padding: 8px; border-left: 3px solid var(--primary); background: white;">
                            <div style="font-size: 12px; color: var(--gray-600);">Result ${idx + 1} (Score: ${item.score?.toFixed(4) || 'N/A'})</div>
                            <div style="font-size: 14px;">${(item.payload?.text || JSON.stringify(item)).substring(0, 200)}...</div>
                        </div>
                    `).join('')}
                    ${resultData.length > 3 ? `<div style="color: var(--gray-600); font-style: italic;">...and ${resultData.length - 3} more results</div>` : ''}
                `;
            } else {
                // For any other data type
                fullDataJson = JSON.stringify(resultData, null, 2);
                previewHtml = `<pre style="white-space: pre-wrap; font-size: 14px;">${fullDataJson.substring(0, 500)}${fullDataJson.length > 500 ? '...' : ''}</pre>`;
            }
        
            container.className = 'workflow-step-result';
            container.innerHTML = `
                <h4>Step ${index + 1}: ${stepConfig.name}</h4>
                <p><strong>Type:</strong> ${stepConfig.type}</p>
                <div class="step-result-preview" style="max-height: 200px; overflow-y: auto; border: 1px solid var(--gray-300); padding: 12px; border-radius: 6px; background: var(--gray-50);">
                    ${previewHtml}
                </div>
                <button class="btn btn-sm btn-secondary toggle-full-result" data-step-index="${index}" style="margin-top: 8px;">
                    <i class="fas fa-expand"></i> Show Full Result
                </button>
                <div class="step-result-full" style="display: none; max-height: 400px; overflow-y: auto; border: 1px solid var(--gray-300); padding: 12px; border-radius: 6px; background: var(--gray-50); margin-top: 8px;">
                    <pre>${escapeHtml(fullDataJson)}</pre>
                </div>
                <div class="full-result-data" data-full-result='${escapeHtml(fullDataJson)}' style="display:none;"></div>
            `;
            
            // Add event listener for the toggle button
            container.querySelector('.toggle-full-result').addEventListener('click', function() {
                const fullResult = container.querySelector('.step-result-full');
                const previewResult = container.querySelector('.step-result-preview');
                
                if (fullResult.style.display === 'none') {
                    fullResult.style.display = 'block';
                    previewResult.style.display = 'none';
                    this.innerHTML = '<i class="fas fa-compress"></i> Show Preview';
                } else {
                    fullResult.style.display = 'none';
                    previewResult.style.display = 'block';
                    this.innerHTML = '<i class="fas fa-expand"></i> Show Full Result';
                }
            });
        }
        
        // Helper function to escape HTML (add this if not already present)
        function escapeHtml(unsafe) {
            if (typeof unsafe !== 'string') {
                unsafe = JSON.stringify(unsafe);
            }
            return unsafe
                 .replace(/&/g, "&amp;")
                 .replace(/</g, "&lt;")
                 .replace(/>/g, "&gt;")
                 .replace(/"/g, "&quot;")
                 .replace(/'/g, "&#039;");
        }

        // Helper function to sanitize and parse JSON responses
        function normalizeSearchResults(results) {
        return {
            "schema_version": "1.0",
            "laws": results.map(item => ({
            "law_id": item.id,
            "law_ref": item.payload.file_path || "Unknown",
            "law_text": item.payload.text,
            "relevance_score": item.score,
            "source_doc": item.payload.file_path
            }))
        };
        }

        // NEW: Cross-Connections Functions
        function openCrossConnectionsModal() {
            const mainCollection = document.getElementById('chat-collection-select').value;
            if (!mainCollection) {
                showNotification('Please select a main collection first.', 'error');
                return;
            }
            document.getElementById('main-collection-name').textContent = mainCollection;
            const optionsDiv = document.getElementById('cross-collections-options').querySelector('.multi-select-options');
            optionsDiv.innerHTML = '';
            allCollectionsData.forEach(collection => {
                if (collection.name !== mainCollection) {
                    const label = document.createElement('label');
                    label.innerHTML = `<input type="checkbox" name="cross_collections" value="${collection.name}"> ${collection.name}`;
                    optionsDiv.appendChild(label);
                }
            });
            document.getElementById('cross-connections-modal').style.display = 'block';
        }

        function closeCrossConnectionsModal() {
            document.getElementById('cross-connections-modal').style.display = 'none';
        }

        function confirmCrossConnections() {
            const mainCollection = document.getElementById('chat-collection-select').value;
            const selectedCollections = Array.from(document.querySelectorAll('#cross-collections-options input:checked')).map(cb => cb.value);
            if (selectedCollections.length === 0) {
                showNotification('Please select at least one additional collection.', 'error');
                return;
            }
            const prompt = `Find connections between the main collection "${mainCollection}" and the following collections: ${selectedCollections.join(', ')}. Analyze similarities, relationships, or overlapping themes in the data.`;
            document.getElementById('chat-input').value = prompt;
            closeCrossConnectionsModal();
            sendChatMessage();
        }

        // NEW: Save and Load Chat History Functions
        function saveChatHistory() {
            if (chatHistory.length === 0) {
                showNotification('No chat history to save.', 'error');
                return;
            }
            const mainCollection = document.getElementById('chat-collection-select').value;
            const chatData = {
                collection: mainCollection,
                timestamp: new Date().toISOString(),
                history: chatHistory
            };
            const blob = new Blob([JSON.stringify(chatData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `chat_history_${mainCollection || 'no_collection'}_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showNotification('Chat history saved successfully!', 'success');
        }

        function loadChatHistory() {
            const fileInput = document.getElementById('chat-file-input');
            fileInput.click();
            fileInput.onchange = function() {
                const file = fileInput.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(e) {
                    try {
                        const chatData = JSON.parse(e.target.result);
                        if (chatData.history && Array.isArray(chatData.history)) {
                            chatHistory = chatData.history;
                            // Clear current chat messages
                            document.getElementById('chat-messages').innerHTML = '';
                            // Re-append all messages
                            chatHistory.forEach(msg => appendMessage(msg.content, msg.role));
                            // Set the collection if available
                            if (chatData.collection) {
                                document.getElementById('chat-collection-select').value = chatData.collection;
                            }
                            showNotification('Chat history loaded successfully!', 'success');
                        } else {
                            throw new Error('Invalid chat history format.');
                        }
                    } catch (error) {
                        showNotification(`Error loading chat history: ${error.message}`, 'error');
                    }
                };
                reader.readAsText(file);
                fileInput.value = ''; // Reset for next load
            };
        }


/**
 * Enhanced collection loading that works with list endpoint only
 */
async function loadCollections() {
    const collectionsList = document.getElementById('collections-list');
    const ingestSelect = document.getElementById('ingest-collection-select');
    const structuredSelect = document.getElementById('structured-collection-select');
    const querySelect = document.getElementById('query-collection-select');
    const chatSelect = document.getElementById('chat-collection-select');
    const workflowSelect = document.getElementById('step-collection-select');
    const enhancedSelect = document.getElementById('enhanced-collection-select');

    collectionsList.innerHTML = '<p>Loading collections...</p>';

    try {
        const response = await fetch('/v1/qdrant/collections');
        if (!response.ok) {
            throw new Error(`Failed to fetch collections. HTTP ${response.status}`);
        }
        const data = await response.json();

        console.debug('Collections API Response:', data);

        // Extract collections array from various possible response structures
        let allCollections = 
            data.result?.collections || 
            data.collections || 
            data.result || 
            (Array.isArray(data) ? data : []);

        if (!Array.isArray(allCollections)) {
            console.warn('Unrecognized collections structure', data);
            allCollections = data.collections ? Object.values(data.collections) : [];
        }

        allCollectionsData = allCollections;
        window.collections = allCollections;

        // Clear UI
        collectionsList.innerHTML = '';
        const selects = [ingestSelect, structuredSelect, querySelect, chatSelect, workflowSelect];
        if (enhancedSelect) selects.push(enhancedSelect);
        
        selects.forEach(sel => {
            if (sel) sel.innerHTML = '<option value="">Select a collection...</option>';
        });

        if (allCollections.length === 0) {
            collectionsList.innerHTML = '<p>No collections found. Create one to get started.</p>';
            return allCollectionsData;
        }

        // Process each collection with the data we have from list endpoint
        for (const collection of allCollections) {
            const collName = collection.name || collection.collection_name || collection.id;
            if (!collName) {
                console.warn('Skipping collection without name:', collection);
                continue;
            }

            try {
                // Build metadata from list response only (no individual GET calls)
                const collectionMetadata = buildCollectionMetadataFromList(collName, collection);

                // Render collection card
                renderCollectionCard(collName, collectionMetadata, collectionsList);

                // Populate dropdowns
                populateCollectionDropdowns(collName, selects.filter(Boolean));

            } catch (err) {
                console.warn(`Error processing collection ${collName}:`, err);
                renderErrorCollectionCard(collName, collectionsList);
            }
        }

        return allCollectionsData;
    } catch (err) {
        console.error('Error loading collections:', err);
        collectionsList.innerHTML = `<p style="color: var(--danger);">Error: ${err.message}</p>`;
        return [];
    }
}

/**
 * Build collection metadata from list endpoint response only
 * This avoids 405 errors by not making individual GET requests
 */
function buildCollectionMetadataFromList(collName, collection) {
    // Extract points count with multiple fallback paths
    const pointsCount = 
        collection.points_count ||
        collection.vectors_count ||
        collection.status?.points_count ||
        collection.info?.points_count ||
        collection.indexed_vectors_count ||
        collection.points ||
        0;

    // Extract vector configuration
    let vectorSize = 'N/A';
    let distanceMetric = 'N/A';

    // Try multiple paths for vector config
    const vectorSources = [
        collection.config?.params?.vectors,
        collection.config?.vectors,
        collection.vectors_config?.params,
        collection.vectors_config,
        collection.vector_config
    ];

    for (const vecs of vectorSources) {
        if (!vecs) continue;

        if (typeof vecs === 'object' && !Array.isArray(vecs)) {
            // Named vectors - get first one
            const firstVector = Object.values(vecs)[0];
            if (firstVector) {
                vectorSize = firstVector.size || firstVector.vector_size || firstVector.dim || vectorSize;
                distanceMetric = firstVector.distance || firstVector.metric || distanceMetric;
                if (vectorSize !== 'N/A') break;
            }
        } else if (vecs.size || vecs.vector_size) {
            // Direct vector config
            vectorSize = vecs.size || vecs.vector_size;
            distanceMetric = vecs.distance || vecs.metric || distanceMetric;
            break;
        }
    }

    // Fallback to direct properties
    if (vectorSize === 'N/A') {
        vectorSize = collection.vector_size || collection.dimension || collection.size || vectorSize;
    }
    if (distanceMetric === 'N/A') {
        distanceMetric = collection.distance || collection.metric || distanceMetric;
    }

    // Check metadata if available
    if (collection.metadata?.vector_config) {
        if (vectorSize === 'N/A') vectorSize = collection.metadata.vector_config.size;
        if (distanceMetric === 'N/A') distanceMetric = collection.metadata.vector_config.distance;
    }

    // Normalize distance metric
    if (typeof distanceMetric === 'string' && distanceMetric !== 'N/A') {
        distanceMetric = distanceMetric.charAt(0).toUpperCase() + distanceMetric.slice(1).toLowerCase();
    }

    // Extract content type
    const contentType = 
        collection.metadata?.content_type || 
        collection.content_type || 
        collection.type ||
        'Unknown';

    // Extract framework info
    const framework = collection.metadata?.framework || collection.framework || null;

    // Extract creation date
    let createdDate = null;
    const createField = 
        collection.created_at || 
        collection.creation_time || 
        collection.metadata?.created_at;
    
    if (createField) {
        try {
            const dt = new Date(createField);
            if (!isNaN(dt.getTime())) {
                createdDate = dt;
            }
        } catch (e) {
            console.debug('Could not parse creation date:', e);
        }
    }

    // Get collection status
    const statusValue = collection.status?.status || collection.status || collection.state || 'ready';
    const statusLower = String(statusValue).toLowerCase();
    
    let status = statusLower;
    let statusColor = 'var(--success)'; // Default to green
    
    if (statusLower.includes('green') || statusLower === 'ready' || statusLower === 'ok') {
        status = 'Ready';
        statusColor = 'var(--success)';
    } else if (statusLower.includes('yellow') || statusLower === 'indexing') {
        status = 'Indexing';
        statusColor = 'var(--warning)';
    } else if (statusLower.includes('red') || statusLower === 'error') {
        status = 'Error';
        statusColor = 'var(--danger)';
    }

    // Calculate size category
    let sizeCategory = 'Empty';
    if (pointsCount > 0) {
        if (pointsCount < 1000) sizeCategory = 'Small';
        else if (pointsCount < 10000) sizeCategory = 'Medium';
        else if (pointsCount < 100000) sizeCategory = 'Large';
        else sizeCategory = 'Very Large';
    }

    // Detect if this might be segmented data based on naming
    const isSegmented = collName.includes('segment') || 
                       collName.includes('chunk') || 
                       collName.includes('transcription');

    return {
        name: collName,
        pointsCount,
        vectorSize,
        distanceMetric,
        contentType,
        framework,
        createdDate,
        isSegmented,
        status,
        statusColor,
        sizeCategory,
        fullData: collection
    };
}

/**
 * Render a collection card with all available metadata
 */
function renderCollectionCard(collName, metadata, container) {
    const card = document.createElement('div');
    card.className = 'collection-card';
    card.dataset.name = collName;

    const statusBadge = `<span style="background: ${metadata.statusColor}; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; margin-left: 8px;">${metadata.status}</span>`;

    const creationInfo = metadata.createdDate 
        ? `<div><strong>Created:</strong> ${metadata.createdDate.toLocaleDateString()}</div>` 
        : '';

    const frameworkInfo = metadata.framework 
        ? `<div><strong>Framework:</strong> ${escapeHtml(metadata.framework)}</div>` 
        : '';

    const segmentInfo = metadata.isSegmented 
        ? `<div style="color: var(--info); font-size: 12px;"><i class="fas fa-cut"></i> Segmented Data</div>` 
        : '';

    card.innerHTML = `
        <div>
            <div class="collection-header">
                <div class="collection-name">${escapeHtml(collName)}${statusBadge}</div>
            </div>
            <div class="collection-meta">
                <div><strong>Documents:</strong> ${metadata.pointsCount.toLocaleString()}</div>
                <div><strong>Vector Dim:</strong> ${metadata.vectorSize}</div>
                <div><strong>Distance:</strong> ${metadata.distanceMetric}</div>
                <div><strong>Content:</strong> ${escapeHtml(metadata.contentType)}</div>
                ${frameworkInfo}
                ${segmentInfo}
                <div><strong>Size:</strong> ${metadata.sizeCategory}</div>
                ${creationInfo}
            </div>
        </div>
        <div class="collection-actions">
            <button class="btn btn-sm btn-secondary view-details-btn" data-name="${collName}" title="View Details">
                <i class="fas fa-info-circle"></i>
            </button>
            <button class="btn btn-danger btn-sm delete-collection" data-name="${collName}" title="Delete">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `;

    // Add event listener for view details button
    card.querySelector('.view-details-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        showCollectionDetails(collName);
    });

    container.appendChild(card);
}

/**
 * Show collection details in modal using stored data (no API call)
 */
function showCollectionDetails(collectionName) {
    const collection = allCollectionsData.find(c => 
        c.name === collectionName || 
        c.collection_name === collectionName ||
        c.id === collectionName
    );
    
    if (!collection) {
        showNotification('Collection not found', 'error');
        return;
    }

    const modal = document.getElementById('collection-details-modal');
    const modalTitle = document.getElementById('modal-collection-name');
    const modalBody = document.getElementById('modal-collection-details');

    if (!modal || !modalTitle || !modalBody) {
        console.error('Collection details modal elements not found in DOM');
        showNotification('Modal elements not found. Please refresh the page.', 'error');
        return;
    }

    modalTitle.textContent = `Collection: ${collectionName}`;

    // Format the collection data nicely
    const formattedData = JSON.stringify(collection, null, 2);
    
    modalBody.innerHTML = `
        <div style="margin-bottom: 16px;">
            <h4>Quick Actions</h4>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px;">
                <button class="btn btn-primary" onclick="document.getElementById('query-collection-select').value='${collectionName}';document.querySelector('[data-tab=query]').click();document.getElementById('collection-details-modal').style.display='none'">
                    <i class="fas fa-search"></i> Search This Collection
                </button>
                <button class="btn btn-primary" onclick="document.getElementById('chat-collection-select').value='${collectionName}';document.querySelector('[data-tab=chat]').click();document.getElementById('collection-details-modal').style.display='none'">
                    <i class="fas fa-comments"></i> Chat with This Data
                </button>
                <button class="btn btn-secondary" onclick="navigator.clipboard.writeText('${collectionName}');showNotification('Collection name copied!','success')">
                    <i class="fas fa-copy"></i> Copy Name
                </button>
            </div>
        </div>
        
        <h4>Full Configuration</h4>
        <pre style="background: #f3f3f3; padding: 12px; border-radius: 6px; max-height: 400px; overflow-y: auto; font-size: 12px;">${escapeHtml(formattedData)}</pre>
        
        <div style="margin-top: 16px; padding: 12px; background: #e7f3ff; border-radius: 6px; border-left: 4px solid #0ea5e9;">
            <strong>💡 Tip:</strong> Use the enhanced ingestion mode to add legal documents with automatic structure extraction and quality validation.
        </div>
    `;

    modal.style.display = 'block';
}
/**
 * Build comprehensive collection metadata from multiple sources
 * FIX: Updated signature to accept collName as first parameter
 */
function buildCollectionMetadata(collName, collection, detailObj, payloadMetadata) {
    const merged = { ...collection, ...(detailObj || {}), _sample_payload: payloadMetadata };

    // Extract points count with multiple fallback paths
    const pointsCount = 
        merged.points_count ||
        merged.vectors_count ||
        merged.status?.points_count ||
        merged.info?.points_count ||
        merged.indexed_vectors_count ||
        detailObj?.points_count ||
        0;

    // Extract vector configuration with comprehensive paths
    let vectorSize = 'N/A';
    let distanceMetric = 'N/A';

    // Path 1: config.params.vectors (standard Qdrant structure)
    if (merged.config?.params?.vectors) {
        const vecs = merged.config.params.vectors;
        if (typeof vecs === 'object' && !Array.isArray(vecs)) {
            const firstVector = Object.values(vecs)[0];
            if (firstVector) {
                vectorSize = firstVector.size || firstVector.vector_size || vectorSize;
                distanceMetric = firstVector.distance || distanceMetric;
            }
        } else {
            vectorSize = vecs.size || vecs.vector_size || vectorSize;
            distanceMetric = vecs.distance || distanceMetric;
        }
    }

    // Path 2: config.vectors (alternative structure)
    if (vectorSize === 'N/A' && merged.config?.vectors) {
        const vecs = merged.config.vectors;
        if (typeof vecs === 'object') {
            const firstVector = Object.values(vecs)[0];
            if (firstVector) {
                vectorSize = firstVector.size || firstVector.vector_size || vectorSize;
                distanceMetric = firstVector.distance || distanceMetric;
            }
        }
    }

    // Path 3: vectors_config (legacy)
    if (vectorSize === 'N/A' && merged.vectors_config?.params) {
        vectorSize = merged.vectors_config.params.size || vectorSize;
        distanceMetric = merged.vectors_config.params.distance || distanceMetric;
    }

    // Path 4: Direct properties
    if (vectorSize === 'N/A') {
        vectorSize = merged.vector_size || merged.dimension || merged.size || vectorSize;
    }
    if (distanceMetric === 'N/A') {
        distanceMetric = merged.distance || merged.metric || distanceMetric;
    }

    // Path 5: From metadata (our custom field)
    if (vectorSize === 'N/A' && merged.metadata?.vector_config) {
        vectorSize = merged.metadata.vector_config.size || vectorSize;
        distanceMetric = merged.metadata.vector_config.distance || distanceMetric;
    }

    // Normalize distance metric
    if (typeof distanceMetric === 'string' && distanceMetric !== 'N/A') {
        distanceMetric = distanceMetric.charAt(0).toUpperCase() + distanceMetric.slice(1).toLowerCase();
    }

    // Extract content type from multiple sources
    const contentTypes = new Set();
    if (payloadMetadata.doc_type) contentTypes.add(payloadMetadata.doc_type);
    if (payloadMetadata.data_type) contentTypes.add(payloadMetadata.data_type);
    if (payloadMetadata.type) contentTypes.add(payloadMetadata.type);
    if (payloadMetadata.content_type) contentTypes.add(payloadMetadata.content_type);
    if (merged.metadata?.content_type) contentTypes.add(merged.metadata.content_type);

    const contentType = contentTypes.size > 0 
        ? Array.from(contentTypes).join(', ') 
        : 'Unknown';

    // Extract framework info
    const framework = payloadMetadata.framework || merged.metadata?.framework || null;

    // Extract creation date
    let createdDate = null;
    const createField = 
        merged.created_at || 
        merged.creation_time || 
        merged.metadata?.created_at;
    
    if (createField) {
        try {
            const dt = new Date(createField);
            if (!isNaN(dt.getTime())) {
                createdDate = dt;
            }
        } catch (e) {
            console.warn('Error parsing creation date:', e);
        }
    }

    // Detect if collection has segmented data
    const isSegmented = !!(
        payloadMetadata.segment_id || 
        payloadMetadata.chunk_id ||
        payloadMetadata.chunk_index !== undefined
    );

    // Get collection status
    const status = merged.status?.status || merged.status || merged.state || 'unknown';
    const statusColor = {
        'green': 'var(--success)',
        'yellow': 'var(--warning)',
        'red': 'var(--danger)',
        'unknown': 'var(--gray-500)'
    }[status] || 'var(--gray-500)';

    // Calculate size category
    let sizeCategory = 'Empty';
    if (pointsCount > 0) {
        if (pointsCount < 1000) sizeCategory = 'Small';
        else if (pointsCount < 10000) sizeCategory = 'Medium';
        else sizeCategory = 'Large';
    }

    return {
        name: collName,
        pointsCount,
        vectorSize,
        distanceMetric,
        contentType,
        framework,
        createdDate,
        isSegmented,
        status,
        statusColor,
        sizeCategory,
        fullData: merged
    };
}

/**
 * Render error state for collection card
 */
function renderErrorCollectionCard(collName, container) {
    const card = document.createElement('div');
    card.className = 'collection-card';
    card.dataset.name = collName;
    card.innerHTML = `
        <div>
            <div class="collection-header">
                <div class="collection-name">${collName}</div>
            </div>
            <div class="collection-meta">
                <div style="color: var(--warning);"><strong>Status:</strong> Error loading details</div>
                <div style="font-size: 12px; color: var(--gray-600);">Click to retry</div>
            </div>
        </div>
        <div class="collection-actions">
            <button class="btn btn-danger delete-collection" data-name="${collName}">
                <i class="fas fa-trash"></i> Delete
            </button>
        </div>
    `;
    container.appendChild(card);
}

/**
 * Populate collection dropdowns
 */
function populateCollectionDropdowns(collName, selects) {
    selects.forEach(sel => {
        const option = document.createElement('option');
        option.value = collName;
        option.textContent = collName;
        sel.appendChild(option);
    });
}

function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
    
    const toast = document.createElement('div');
    toast.className = `notification notification-${type}`;
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

// Add this to qdrant-vector.html script section
function initWorkflowBuilder(collections, assistants, models) {
    console.log('Workflow builder initialized with:', {
        collections: collections?.length || 0,
        assistants: assistants?.length || 0,
        models: models?.length || 0
    });
    // Initialize workflow UI components here
}

// Add this to your page to diagnose issues
async function debugChatSetup() {
    console.log('=== Chat Setup Debug ===');
    
    const collection = document.getElementById('chat-collection-select').value;
    const model = document.getElementById('chat-model-select').value;
    
    console.log('Collection:', collection);
    console.log('Model:', model);
    
    // Test search endpoint
    try {
        const testSearch = await fetch('/v1/qdrant/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collection_name: collection,
                query_text: "test",
                limit: 1
            })
        });
        console.log('Search endpoint status:', testSearch.status);
        console.log('Search response:', await testSearch.json());
    } catch (e) {
        console.error('Search test failed:', e);
    }
}

// ===== STRUCTURED JSON INGESTION =====

// Toggle advanced options
function toggleAdvancedOptions() {
    const optionsDiv = document.getElementById('advanced-structured-options');
    if (optionsDiv.style.display === 'none') {
        optionsDiv.style.display = 'block';
    } else {
        optionsDiv.style.display = 'none';
    }
}

// Handle structured file selection
let structuredFiles = [];

document.getElementById('structured-file-upload')?.addEventListener('change', function(e) {
    const files = Array.from(e.target.files);
    structuredFiles = files;
    
    const previewDiv = document.getElementById('structured-files-preview');
    const filesList = document.getElementById('structured-files-list');
    
    if (files.length > 0) {
        previewDiv.style.display = 'block';
        filesList.innerHTML = '';
        
        files.forEach((file, index) => {
            const fileSize = file.size < 1024 
                ? `${file.size} bytes` 
                : file.size < 1048576 
                    ? `${(file.size / 1024).toFixed(1)} KB`
                    : `${(file.size / 1048576).toFixed(2)} MB`;
            
            const item = document.createElement('div');
            item.className = 'file-preview-item';
            item.innerHTML = `
                <div class="file-info">${file.name}</div>
                <div class="file-size">${fileSize}</div>
                <button class="remove-file" data-index="${index}" title="Remove file">
                    <i class="fas fa-times"></i>
                </button>
            `;
            filesList.appendChild(item);
        });
        
        // Add remove file functionality
        document.querySelectorAll('.remove-file').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.getAttribute('data-index'));
                structuredFiles.splice(index, 1);
                
                // Update the file input
                const dataTransfer = new DataTransfer();
                structuredFiles.forEach(file => dataTransfer.items.add(file));
                document.getElementById('structured-file-upload').files = dataTransfer.files;
                
                // Trigger change event to update preview
                document.getElementById('structured-file-upload').dispatchEvent(new Event('change'));
            });
        });
        
        // Enable/disable buttons
        updateStructuredButtonState();
    } else {
        previewDiv.style.display = 'none';
    }
});

// Update button state based on selection
function updateStructuredButtonState() {
    const collectionSelect = document.getElementById('structured-collection-select');
    const dataTypeSelect = document.getElementById('structured-data-type');
    const ingestBtn = document.getElementById('ingest-structured-btn');
    const validateBtn = document.getElementById('validate-structured-btn');
    
    const hasCollection = collectionSelect && collectionSelect.value;
    const hasDataType = dataTypeSelect && dataTypeSelect.value;
    const hasFiles = structuredFiles.length > 0;
    
    if (ingestBtn) ingestBtn.disabled = !(hasCollection && hasDataType && hasFiles);
    if (validateBtn) validateBtn.disabled = !(hasCollection && hasDataType && hasFiles);
}

// Add event listeners for collection and data type changes
document.getElementById('structured-collection-select')?.addEventListener('change', updateStructuredButtonState);
document.getElementById('structured-data-type')?.addEventListener('change', updateStructuredButtonState);

async function parseStructuredJsonFiles(files) {
    const parsedFiles = [];
    const allValidItems = [];
    let totalValidItems = 0;
    let totalInvalidItems = 0;

    for (const file of files) {
        const fileResult = {
            filename: file.name,
            status: 'processed',
            is_valid_json: true,
            item_count: 0,
            valid_items: 0,
            invalid_items: 0,
            errors: []
        };

        try {
            const raw = await file.text();
            const parsed = JSON.parse(raw);
            const items = Array.isArray(parsed) ? parsed : [parsed];
            fileResult.item_count = items.length;

            for (const item of items) {
                if (item && typeof item === 'object' && !Array.isArray(item)) {
                    fileResult.valid_items += 1;
                    allValidItems.push({ ...item, _source_file: file.name });
                } else {
                    fileResult.invalid_items += 1;
                    fileResult.errors.push('Item is not a JSON object.');
                }
            }

            totalValidItems += fileResult.valid_items;
            totalInvalidItems += fileResult.invalid_items;
            if (fileResult.valid_items === 0) {
                fileResult.status = 'error';
                fileResult.is_valid_json = false;
            }
        } catch (e) {
            fileResult.status = 'error';
            fileResult.is_valid_json = false;
            fileResult.errors.push(`Invalid JSON: ${e.message}`);
            totalInvalidItems += 1;
        }

        parsedFiles.push(fileResult);
    }

    return {
        files: parsedFiles,
        validItems: allValidItems,
        total_valid_items: totalValidItems,
        total_invalid_items: totalInvalidItems
    };
}

async function collectionExistsByName(collectionName) {
    if (Array.isArray(window.collections) && window.collections.length > 0) {
        return window.collections.some(c => String(c?.name || c?.collection_name || '').trim() === collectionName);
    }

    try {
        const response = await fetch('/v1/qdrant/collections');
        if (!response.ok) return false;
        const data = await response.json();
        const collections = data.result?.collections || data.collections || data.result || (Array.isArray(data) ? data : []);
        return Array.isArray(collections)
            ? collections.some(c => String(c?.name || c?.collection_name || '').trim() === collectionName)
            : false;
    } catch {
        return false;
    }
}

// Validate structured files
document.getElementById('validate-structured-btn')?.addEventListener('click', async function() {
    const collectionSelect = document.getElementById('structured-collection-select');
    const dataTypeSelect = document.getElementById('structured-data-type');
    
    if (!collectionSelect.value || !dataTypeSelect.value || structuredFiles.length === 0) {
        showNotification('Please select a collection, data type, and at least one JSON file.', 'error');
        return;
    }
    
    const validateBtn = this;
    const originalText = validateBtn.innerHTML;
    validateBtn.disabled = true;
    validateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Validating...';
    
    const statusArea = document.getElementById('ingestion-status-area');
    statusArea.style.display = 'block';
    statusArea.innerHTML = '<div class="loading">Validating JSON files...</div>';
    
    try {
        const parsed = await parseStructuredJsonFiles(structuredFiles);
        const exists = await collectionExistsByName(collectionSelect.value);
        const data = {
            is_valid: parsed.total_valid_items > 0 && parsed.total_invalid_items === 0,
            collection_exists: exists,
            files: parsed.files,
            total_valid_items: parsed.total_valid_items,
            total_invalid_items: parsed.total_invalid_items
        };
        
        // Display validation results
        let validationHtml = `
            <div class="validation-results" style="background: ${data.is_valid ? '#d1fae5' : '#fef3c7'}; 
                    padding: 16px; border-radius: 8px; border-left: 4px solid ${data.is_valid ? '#10b981' : '#f59e0b'};">
                <h4 style="margin: 0 0 12px 0; display: flex; align-items: center; gap: 8px;">
                    <i class="fas fa-${data.is_valid ? 'check-circle' : 'exclamation-triangle'}" 
                       style="color: ${data.is_valid ? '#10b981' : '#f59e0b'}"></i>
                    File Validation Results
                </h4>
        `;
        
        if (!data.collection_exists) {
            validationHtml += `
                <div class="warning" style="background: #fef3c7; padding: 8px; border-radius: 4px; margin-bottom: 12px;">
                    <i class="fas fa-exclamation-triangle" style="color: #f59e0b;"></i>
                    Collection does not exist. Please create it first.
                </div>
            `;
        }
        
        validationHtml += `
            <p><strong>Total Files:</strong> ${data.files?.length || 0}</p>
            <p><strong>Valid Items:</strong> ${data.total_valid_items || 0}</p>
            <p><strong>Invalid Items:</strong> ${data.total_invalid_items || 0}</p>
            <p><strong>Collection Compatible:</strong> ${data.collection_exists ? 'Yes' : 'No'}</p>
        `;
        
        if (data.files && data.files.length > 0) {
            validationHtml += `<div style="margin-top: 12px; max-height: 200px; overflow-y: auto;">`;
            data.files.forEach(file => {
                validationHtml += `
                    <div style="margin-bottom: 8px; padding: 8px; background: white; border-radius: 4px; 
                         border: 1px solid ${file.is_valid_json ? '#d1fae5' : '#fecaca'}">
                        <div style="font-weight: 500; margin-bottom: 4px;">${file.filename}</div>
                        <div style="font-size: 12px; color: var(--gray-600);">
                            Items: ${file.item_count || 0} | 
                            Valid: ${file.valid_items || 0} | 
                            Invalid: ${file.invalid_items || 0}
                            ${file.status !== 'processed' ? `<br><span style="color: #dc2626;">${file.errors?.[0] || 'Error'}</span>` : ''}
                        </div>
                    </div>
                `;
            });
            validationHtml += `</div>`;
        }
        
        validationHtml += `</div>`;
        statusArea.innerHTML = validationHtml;
        
        if (data.is_valid && data.collection_exists) {
            showNotification(`Validation passed! Ready to ingest ${data.total_valid_items} items.`, 'success');
        } else {
            showNotification('Validation completed with warnings.', 'warning');
        }
        
    } catch (error) {
        console.error('Validation error:', error);
        statusArea.innerHTML = `<div class="error">${error.message}</div>`;
        showNotification(`❌ Validation failed: ${error.message}`, 'error');
    } finally {
        validateBtn.innerHTML = originalText;
        validateBtn.disabled = false;
    }
});

// Ingest structured files
document.getElementById('ingest-structured-btn')?.addEventListener('click', async function() {
    const collectionSelect = document.getElementById('structured-collection-select');
    const dataTypeSelect = document.getElementById('structured-data-type');
    const skipExisting = document.getElementById('skip-existing-checkbox')?.checked ?? true;
    const customIdField = document.getElementById('custom-id-field')?.value || null;
    const customTextField = document.getElementById('custom-text-field')?.value || null;
    
    if (!collectionSelect.value || !dataTypeSelect.value || structuredFiles.length === 0) {
        showNotification('Please select a collection, data type, and at least one JSON file.', 'error');
        return;
    }
    
    const ingestBtn = this;
    const originalText = ingestBtn.innerHTML;
    ingestBtn.disabled = true;
    ingestBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ingesting...';
    
    const statusArea = document.getElementById('ingestion-status-area');
    statusArea.style.display = 'block';
    statusArea.innerHTML = `
        <div class="loading">
            <div>Preparing to ingest ${structuredFiles.length} file(s)...</div>
            <div class="upload-progress" style="margin-top: 16px;">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: 0%"></div>
                </div>
                <div class="progress-text">0%</div>
            </div>
        </div>
    `;
    
    try {
        const parsed = await parseStructuredJsonFiles(structuredFiles);
        const validItems = parsed.validItems;
        if (!validItems.length) {
            throw new Error('No valid JSON objects found in selected files.');
        }

        const exists = await collectionExistsByName(collectionSelect.value);
        if (!exists) {
            throw new Error(`Collection '${collectionSelect.value}' does not exist.`);
        }

        const dedupedItems = (() => {
            if (!skipExisting || !customIdField) return validItems;
            const seen = new Set();
            return validItems.filter(item => {
                const rawKey = item?.[customIdField];
                if (rawKey === undefined || rawKey === null || String(rawKey).trim() === '') return true;
                const key = String(rawKey).trim();
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        })();

        const itemsForApi = dedupedItems.map(item => {
            const next = { ...item };
            if (customTextField && next.text === undefined && next[customTextField] !== undefined) {
                next.text = next[customTextField];
            }
            return next;
        });

        const response = await fetch('/v1/qdrant/collections/structured_ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collection_name: collectionSelect.value,
                data_type: dataTypeSelect.value,
                items: itemsForApi
            })
        });
        
        // Update progress
        const progressFill = statusArea.querySelector('.progress-fill');
        const progressText = statusArea.querySelector('.progress-text');
        if (progressFill && progressText) {
            progressFill.style.width = '50%';
            progressText.textContent = '50% - Processing files...';
        }
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ingestion failed');
        }
        
        // Update progress to completion
        if (progressFill && progressText) {
            progressFill.style.width = '100%';
            progressText.textContent = '100% - Complete!';
        }
        
        // Display results
        setTimeout(() => {
            const ingestedCount = Number(data.count || data.total || data.summary?.total_items_ingested || itemsForApi.length || 0);
            const skippedCount = Math.max(0, validItems.length - itemsForApi.length);
            let resultsHtml = `
                <div class="success-message" style="background: #d1fae5; padding: 16px; border-radius: 8px; 
                     border-left: 4px solid #10b981;">
                    <h4 style="margin: 0 0 12px 0; display: flex; align-items: center; gap: 8px;">
                        <i class="fas fa-check-circle" style="color: #10b981;"></i>
                        Ingestion Complete!
                    </h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px;">
                        <div style="background: white; padding: 12px; border-radius: 6px;">
                            <div style="font-size: 12px; color: var(--gray-600);">Files Processed</div>
                            <div style="font-size: 24px; font-weight: 600;">${structuredFiles.length}</div>
                        </div>
                        <div style="background: white; padding: 12px; border-radius: 6px;">
                            <div style="font-size: 12px; color: var(--gray-600);">Items Ingested</div>
                            <div style="font-size: 24px; font-weight: 600;">${ingestedCount}</div>
                        </div>
                        <div style="background: white; padding: 12px; border-radius: 6px;">
                            <div style="font-size: 12px; color: var(--gray-600);">Items Skipped</div>
                            <div style="font-size: 24px; font-weight: 600;">${skippedCount}</div>
                        </div>
                    </div>
            `;
            
            if (data.files && data.files.length > 0) {
                resultsHtml += `<div style="margin-top: 12px; max-height: 300px; overflow-y: auto;">`;
                resultsHtml += `<h5 style="margin: 0 0 8px 0; font-size: 14px;">File Details:</h5>`;
                
                data.files.forEach(file => {
                    resultsHtml += `
                        <div style="margin-bottom: 8px; padding: 8px; background: white; border-radius: 4px; 
                             border: 1px solid ${file.status === 'processed' ? '#d1fae5' : '#fecaca'}">
                            <div style="font-weight: 500; margin-bottom: 4px; display: flex; justify-content: space-between;">
                                <span>${file.filename}</span>
                                <span style="font-size: 12px; color: ${file.status === 'processed' ? '#10b981' : '#dc2626'};">
                                    ${file.status === 'processed' ? '✓' : '✗'}
                                </span>
                            </div>
                            <div style="font-size: 12px; color: var(--gray-600);">
                                Processed: ${file.items_processed || 0} | 
                                Ingested: ${file.items_ingested || 0} | 
                                Skipped: ${file.items_skipped || 0}
                            </div>
                            ${file.errors && file.errors.length > 0 ? `
                                <div style="margin-top: 4px; font-size: 11px; color: #dc2626;">
                                    ${file.errors.slice(0, 2).map(err => `• ${err}`).join('<br>')}
                                    ${file.errors.length > 2 ? `<br>... and ${file.errors.length - 2} more errors` : ''}
                                </div>
                            ` : ''}
                        </div>
                    `;
                });
                resultsHtml += `</div>`;
            }
            
            resultsHtml += `</div>`;
            statusArea.innerHTML = resultsHtml;
            
            // Clear file selection
            structuredFiles = [];
            document.getElementById('structured-file-upload').value = '';
            document.getElementById('structured-files-preview').style.display = 'none';
            
            // Refresh collections
            loadCollections();
            
            showNotification(`Successfully ingested ${ingestedCount} items!`, 'success');
        }, 500);
        
    } catch (error) {
        console.error('Ingestion error:', error);
        statusArea.innerHTML = `<div class="error">${error.message}</div>`;
        showNotification(`❌ Ingestion failed: ${error.message}`, 'error');
    } finally {
        ingestBtn.innerHTML = originalText;
        ingestBtn.disabled = false;
        updateStructuredButtonState();
    }
});

// Also need to ensure the ingestion mode selector works properly
document.getElementById('ingest-mode-select')?.addEventListener('change', function(e) {
    const mode = e.target.value;
    
    // Hide all panels
    document.getElementById('file-ingest-panel').style.display = 'none';
    document.getElementById('enhanced-ingest-panel').style.display = 'none';
    document.getElementById('structured-ingest-panel').style.display = 'none';
    
    // Show selected panel
    if (mode === 'file') {
        document.getElementById('file-ingest-panel').style.display = 'block';
    } else if (mode === 'enhanced') {
        document.getElementById('enhanced-ingest-panel').style.display = 'block';
    } else if (mode === 'structured') {
        document.getElementById('structured-ingest-panel').style.display = 'block';
        // Populate collections for structured panel
        populateCollectionDropdown('structured-collection-select');
    }
});

// Helper function to populate collection dropdowns
function populateCollectionDropdown(dropdownId) {
    const select = document.getElementById(dropdownId);
    if (!select) return;
    
    const currentValue = select.value;
    select.innerHTML = '<option value="">Select a collection...</option>';
    
    // Assuming 'collections' array is available globally
    if (window.collections && Array.isArray(window.collections)) {
        window.collections.forEach(col => {
            const option = document.createElement('option');
            option.value = col.name;
            option.textContent = `${col.name} (${col.points_count || 0} points)`;
            select.appendChild(option);
        });
    }
    
    if (currentValue) {
        select.value = currentValue;
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    // Initially populate dropdowns
    populateCollectionDropdown('structured-collection-select');
    populateCollectionDropdown('enhanced-collection-select');
    populateCollectionDropdown('ingest-collection-select');
    
    // Add event listener for collection refresh
    document.getElementById('refresh-collections-btn')?.addEventListener('click', function() {
        loadCollections().then(() => {
            populateCollectionDropdown('structured-collection-select');
            populateCollectionDropdown('enhanced-collection-select');
            populateCollectionDropdown('ingest-collection-select');
            populateCollectionDropdown('query-collection-select');
            populateCollectionDropdown('chat-collection-select');
        });
    })
});