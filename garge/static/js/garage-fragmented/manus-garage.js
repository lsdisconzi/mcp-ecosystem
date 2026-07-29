/**
 * ManusGarageIntegration connects the Manus backend with the Garage UI using
 * user-selected files and assistants instead of raw endpoints.
 * The class focuses purely on transport, while the UI logic is handled by
 * the ManusGarageModule defined later in this file.
 */
const DEFAULT_LLM_CONFIG = {
    provider: 'ollama',
    model: 'llama3.1:8b',
    max_tokens: 8192,
    temperature: 0.0
};

const SUPPORTED_MANUS_PROVIDERS = ['ollama', 'deepseek'];

const FALLBACK_PROVIDER_MODELS = [
    { provider: 'ollama', model: 'llama3.1:8b', label: 'llama3.1:8b' },
    { provider: 'ollama', model: 'qwen2.5:7b', label: 'qwen2.5:7b' },
    { provider: 'deepseek', model: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
    { provider: 'deepseek', model: 'deepseek-v4-pro', label: 'deepseek-v4-pro' }
];

// Manus service (port 8078): proxied through Garage at /manus/* to avoid CORS.
// Files & assistants registry lives on the Garage app (current page origin, served at /v1/*).
const LOCAL_SERVICE_ORIGIN = 'http://localhost:8078';
const DEFAULT_MANUS_API_BASE = '/manus';
const DEFAULT_FILES_API_BASE = '/v1';

class ManusGarageIntegration {
    constructor(options = {}) {
        this.baseUrl = this.#resolveServiceBaseUrl(options.baseUrl || this.#readLocal('manusGarage.baseUrl'));
        this.filesApiBase = this.#resolveFilesApiBase(options.filesApiBase).replace(/\/+$/, '');
        this.requestTimeout = options.requestTimeout || 60000;
        this.historyKey = options.historyKey || 'manusGarage.history';
        this.historyLimit = options.historyLimit || 50;
        this.llmConfig = {
            ...DEFAULT_LLM_CONFIG,
            ...(options.llmConfig || {})
        };

        this.agentActive = false;
        this.agentSession = null;
        this.garage = null;
        this.currentStream = null;
        this.isStreaming = false;

        this.history = this.#loadHistory();
        this.eventTarget = new EventTarget();
    }

    setBaseUrl(url) {
        if (!url) return;
        this.baseUrl = this.#resolveServiceBaseUrl(url);
        this.#writeLocal('manusGarage.baseUrl', this.baseUrl);
        this.emit('config-change', { baseUrl: this.baseUrl });
    }

    initializeWithGarage(garageContext = {}) {
        this.garage = garageContext;
        this.emit('garage-context', garageContext);
    }

    on(event, handler) {
        this.eventTarget.addEventListener(event, handler);
    }

    off(event, handler) {
        this.eventTarget.removeEventListener(event, handler);
    }

    emit(event, detail) {
        this.eventTarget.dispatchEvent(new CustomEvent(event, { detail }));
    }

    async checkHealth(timeout = 5000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const [healthResponse, catalogResponse] = await Promise.all([
                fetch(`${this.baseUrl}/health`, {
                    method: 'GET',
                    signal: controller.signal
                }).catch(() => null),
                fetch(`http://34.44.115.131:3229/api/models/catalog`, {
                    method: 'GET',
                    signal: controller.signal
                })
            ]);

            if (!catalogResponse?.ok) {
                return { healthy: false, error: `HTTP ${catalogResponse?.status || 'catalog unavailable'}` };
            }

            const health = healthResponse?.ok ? await healthResponse.json().catch(() => ({})) : null;
            const catalog = await catalogResponse.json().catch(() => ({}));

            return {
                healthy: true,
                data: {
                    health,
                    catalog,
                    models: this.#normalizeCatalogModels(catalog)
                }
            };
        } catch (error) {
            return {
                healthy: false,
                error: error.name === 'AbortError' ? 'Connection timed out' : error.message
            };
        } finally {
            clearTimeout(timer);
        }
    }

    setLLMConfig(nextConfig = {}) {
        if (!nextConfig || typeof nextConfig !== 'object') return;
        const provider = this.#normalizeProvider(nextConfig.provider || this.llmConfig.provider);
        const model = (nextConfig.model || this.llmConfig.model || '').trim();
        this.llmConfig = {
            ...this.llmConfig,
            ...nextConfig,
            provider,
            model: model || this.llmConfig.model
        };
    }

    async fetchModelCatalog() {
        const response = await fetch(`http://34.44.115.131:3229/api/models/catalog`, {
            method: 'GET'
        });
        if (!response.ok) {
            throw new Error(`Failed to load model catalog: HTTP ${response.status}`);
        }
        const payload = await response.json().catch(() => ({}));
        return this.#normalizeCatalogModels(payload);
    }

    async startAgent() {
        const health = await this.checkHealth();
        if (!health.healthy) {
            throw new Error(`LLM unreachable: ${health.error || 'unknown error'}`);
        }

        const response = await fetch(`${this.baseUrl}/api/agent/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(`HTTP ${response.status}: ${text || 'Failed to start agent'}`);
        }

        const data = await response.json().catch(() => ({}));
        this.agentSession = {
            id: `garage_session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            startTime: new Date().toISOString(),
            backendStatus: data.status || 'started',
            files: [],
            assistants: [],
            status: 'active'
        };

        this.agentActive = true;
        this.emit('agent-state', { active: true, session: this.agentSession });
        return this.agentSession;
    }

    async stopAgent() {
        if (this.isStreaming && this.currentStream) {
            try {
                this.currentStream.abort();
            } catch (e) {
                console.warn('Failed to abort Manus stream', e);
            }
        }

        if (this.agentSession) {
            this.agentSession.endTime = new Date().toISOString();
            this.agentSession.status = 'stopped';
        }

        this.agentActive = false;
        this.isStreaming = false;
        this.currentStream = null;
        this.emit('agent-state', { active: false, session: this.agentSession });
    }

    async analyzeFiles(payload, options = {}) {
        if (options.stream) {
            return this.analyzeFilesStream(payload, options.callbacks || {});
        }
        return this.analyzeFilesWithAssistants(payload, options.onProgress);
    }

    async analyzeFilesWithAssistants(payload, onProgress = null) {
        await this.#ensureAgent();
        const { files, assistants, prompt } = this.#validatePayload(payload);
        const fileContents = await this.#getFileContents(files);
        const assistantDetails = await this.#getAssistantDetails(assistants);
        const analysisRequest = this.#buildAnalysisRequest(payload, fileContents, assistantDetails);
        if (onProgress) {
            const model = analysisRequest.options?.model || this.llmConfig.model;
            const provider = analysisRequest.options?.provider || this.llmConfig.provider;
            onProgress(10, `Sending analysis request to ${provider}/${model}...`);
        }
        const llmResponse = await this.#callLLMCompletion(analysisRequest, { stream: false });

        const formatted = this.#formatResult({
            raw: llmResponse,
            payload,
            stream: false,
            text: this.#extractLLMText(llmResponse)
        });

        this.saveToGarageHistory(formatted);
        if (onProgress) onProgress(100, 'Completed');
        return formatted;
    }

    async analyzeFilesStream(payload, callbacks = {}) {
        await this.#ensureAgent();
        if (this.isStreaming) throw new Error('A streaming request is already in progress');
        const { files, assistants, prompt } = this.#validatePayload(payload);
        const fileContents = await this.#getFileContents(files);
        const assistantDetails = await this.#getAssistantDetails(assistants);
        const analysisRequest = this.#buildAnalysisRequest(payload, fileContents, assistantDetails);
        await this.#callLLMStream(analysisRequest, callbacks);
    }

    saveToGarageHistory(entry) {
        this.history.unshift(entry);
        if (this.history.length > this.historyLimit) {
            this.history.length = this.historyLimit;
        }
        this.#persistHistory();
        this.emit('history', this.history.slice());
    }

    // Private helpers -------------------------------------------------------

    #readLocal(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    #writeLocal(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch (e) {
            console.warn('Failed to write to localStorage', e);
        }
    }

    #resolveServiceBaseUrl(url) {
        const candidate = (url || '').trim();
        if (!candidate || candidate === '/api/manus' || candidate.endsWith('/api/manus')) {
            return DEFAULT_MANUS_API_BASE;
        }
        // Coerce direct localhost:8078 (or similar) absolute URLs to the same-origin
        // /manus proxy so the browser does not hit a cross-origin endpoint.
        if (/^https?:\/\/[^/]*:8078(\/|$)/i.test(candidate)) {
            return DEFAULT_MANUS_API_BASE;
        }
        if (/^https?:\/\//i.test(candidate)) {
            return candidate.replace(/\/+$/, '');
        }
        return `/${candidate.replace(/^\/+/, '').replace(/\/+$/, '')}`;
    }

    #resolveFilesApiBase(url) {
        const candidate = (url || '').trim();
        if (!candidate) {
            return DEFAULT_FILES_API_BASE;
        }
        if (/^https?:\/\//i.test(candidate)) {
            return candidate.replace(/\/+$/, '');
        }
        // Relative paths (e.g. "/v1") resolve against the current page origin
        // which is the Garage app where files & assistants are managed.
        return `/${candidate.replace(/^\/+/, '').replace(/\/+$/, '')}`;
    }

    #loadHistory() {
        try {
            const raw = this.#readLocal(this.historyKey);
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    #persistHistory() {
        this.#writeLocal(this.historyKey, JSON.stringify(this.history));
    }

    async #ensureAgent() {
        if (!this.agentActive) {
            await this.startAgent();
        }
    }

    #validatePayload(payload = {}) {
        const files = Array.isArray(payload.files) ? payload.files.filter(Boolean) : [];
        const assistants = Array.isArray(payload.assistants) ? payload.assistants.filter(Boolean) : [];
        const prompt = (payload.prompt || '').trim();

        if (!files.length) throw new Error('Select at least one file');
        if (!assistants.length) throw new Error('Select at least one assistant');
        if (!prompt) throw new Error('Enter a prompt for the agent');

        return { files, assistants, prompt };
    }

    async #getFileContents(fileIds) {
        const results = [];
        for (const id of fileIds) {
            const meta = this.#lookupFileMeta(id);
            let content = '';

            if (this.garage?.getFileContent) {
                content = await this.garage.getFileContent(id);
            } else if (meta?.content) {
                content = meta.content;
            } else {
                // Prefer fetching by file id via the registry endpoint, which
                // resolves the actual stored path (with extension). Fall back
                // to /files/read?path=... only if the id-based endpoint fails.
                try {
                    content = await this.#fetchFileContentById(id);
                } catch (idError) {
                    const relPath =
                        meta?.path ||
                        meta?.filepath ||
                        meta?.relative_path ||
                        meta?.absolute_path ||
                        meta?.storage_path ||
                        '';
                    if (!relPath) throw idError;
                    content = await this.#fetchFileContentByPath(relPath);
                }
            }

            results.push({
                id,
                name: meta?.filename || meta?.name || `file_${id}`,
                content,
                metadata: meta || null
            });
        }
        return results;
    }

    async #fetchFileContentById(fileId) {
        const url = `${this.filesApiBase}/files/${encodeURIComponent(fileId)}/content`;
        const resp = await fetch(url);
        if (!resp.ok) {
            const text = await resp.text().catch(() => '');
            throw new Error(`Failed to read file (${fileId}): ${resp.status} ${text || ''}`.trim());
        }
        const ct = String(resp.headers.get('content-type') || '').toLowerCase();
        if (ct.includes('application/json')) {
            const data = await resp.json().catch(() => ({}));
            return data?.content || data?.text || '';
        }
        return await resp.text();
    }

    async #fetchFileContentByPath(path) {
        const url = `${this.filesApiBase}/files/read?path=${encodeURIComponent(path)}`;
        const resp = await fetch(url);
        if (!resp.ok) {
            const text = await resp.text();
            throw new Error(`Failed to read file (${path}): ${resp.status} ${text || ''}`.trim());
        }
        const data = await resp.json().catch(() => ({}));
        return data?.content || '';
    }

    async #getAssistantDetails(assistantIds) {
        const results = [];
        for (const id of assistantIds) {
            const meta = this.#lookupAssistantMeta(id);
            if (meta) {
                results.push(meta);
                continue;
            }

            const resp = await fetch(`${this.filesApiBase}/assistants/${id}`);
            if (!resp.ok) throw new Error(`Failed to load assistant ${id}`);
            const assistant = await resp.json();
            results.push(assistant);
        }
        return results;
    }

    #lookupFileMeta(id) {
        const sources = [
            this.garage?.files,
            window?.garageFiles,
            window?.availableFiles,
            window?.filesCache,
            window?.GARAGE_FILES_CACHE
        ].filter(Boolean);

        for (const collection of sources) {
            const found = collection.find?.((item) => item.id === id || item.file_id === id);
            if (found) return found;
        }
        return null;
    }

    #lookupAssistantMeta(id) {
        const sources = [
            this.garage?.assistants,
            window?.garageAssistants,
            window?.availableAssistants,
            window?.assistantsCache,
            window?.GARAGE_ASSISTANTS_CACHE
        ].filter(Boolean);

        for (const collection of sources) {
            const found = collection.find?.((item) => item.id === id || item.assistant_id === id);
            if (found) return found;
        }
        return null;
    }

    #buildAnalysisRequest(payload, fileContents, assistantDetails) {
        return {
            files: fileContents,
            assistants: assistantDetails,
            userPrompt: payload.prompt,
            analysisType: payload.analysisType || 'comprehensive',
            timestamp: new Date().toISOString(),
            sessionId: this.agentSession?.id,
            context: {
                fileOrder: payload.selectedFilesOrder || payload.files,
                assistantFileIds: payload.assistantContextFiles || [],
                includeAssistantProfile: payload.contextOptions?.includeAssistantProfile ?? true,
                urls: payload.additionalUrls || []
            },
            options: {
                temperature: payload.temperature ?? this.llmConfig.temperature,
                top_p: payload.top_p ?? 0.9,
                timeout: payload.timeout || 60,
                stream: !!payload.stream,
                provider: this.#normalizeProvider(payload.provider || this.llmConfig.provider),
                model: (payload.model || this.llmConfig.model || '').trim() || this.llmConfig.model
            }
        };
    }

    #formatResult({ raw, payload, stream, text }) {
        const files = Array.isArray(payload?.files)
            ? payload.files.map((item) => (typeof item === 'string' ? item : item?.id || item?.name || '')).filter(Boolean)
            : [];
        const assistants = Array.isArray(payload?.assistants)
            ? payload.assistants.map((item) => (typeof item === 'string' ? item : item?.id || item?.name || '')).filter(Boolean)
            : [];
        return {
            id: `manus_result_${Date.now()}`,
            status: 'completed',
            sessionId: this.agentSession?.id,
            prompt: payload?.prompt || payload?.userPrompt || '',
            files,
            assistants,
            analysisType: payload?.analysisType || null,
            streamed: !!stream,
            result: text || raw?.analysis || raw?.result || raw?.message || '',
            backendResponse: raw,
            provider: payload?.options?.provider || this.llmConfig.provider,
            model: payload?.options?.model || this.llmConfig.model,
            timestamp: new Date().toISOString()
        };
    }

    #extractLLMText(response) {
        if (!response) return '';
        if (typeof response === 'string') return response.trim();
        if (Array.isArray(response?.choices) && response.choices.length) {
            return response.choices
                .map((choice) => choice?.message?.content || choice?.delta?.content || choice?.text || '')
                .join('')
                .trim();
        }
        if (typeof response?.response === 'string') return response.response.trim();
        if (typeof response?.result === 'string') return response.result.trim();
        if (typeof response?.message === 'string') return response.message.trim();
        if (typeof response?.message?.content === 'string') return response.message.content.trim();
        if (typeof response?.text === 'string') return response.text.trim();
        return '';
    }

    #composeMessages(request) {
        const fileSections = request.files.map((file, idx) => {
            const truncated = this.#truncateText(file.content);
            return `### File ${idx + 1}: ${file.name}\n${truncated}`;
        }).join('\n\n');

        const assistantSections = request.assistants.map((assistant) => {
            return `Assistant ${assistant.name || assistant.id}\nInstructions: ${assistant.instructions || assistant.description || 'N/A'}`;
        }).join('\n\n') || 'No assistant context provided.';

        const urlsSection = (request.context?.urls || []).length
            ? `### External URLs\n${request.context.urls.join('\n')}`
            : '';

        const systemPrompt = [
            'You are Manus, a senior compliance, governance, and risk analyst working inside AI Garage.',
            'Follow the user prompt exactly, cite evidence by filename, preserve file order, and highlight Sarbanes–Oxley mapping when applicable.'
        ].join(' ');

        const userContent = [
            '### Files (ordered)',
            fileSections || 'No files were provided.',
            '### Assistant Context',
            assistantSections,
            urlsSection,
            '### Task',
            request.userPrompt
        ].filter(Boolean).join('\n\n');

        return [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userContent }
        ];
    }

    #truncateText(text = '', limit = 12000) {
        if (text.length <= limit) return text;
        return `${text.slice(0, limit)}\n\n[TRUNCATED ${text.length - limit} CHARS]`;
    }

    #normalizeProvider(provider) {
        const raw = String(provider || '').trim().toLowerCase();
        if (!raw) return DEFAULT_LLM_CONFIG.provider;
        if (raw.includes('deepseek')) return 'deepseek';
        if (raw.includes('ollama') || raw === 'local') return 'ollama';
        return SUPPORTED_MANUS_PROVIDERS.includes(raw) ? raw : DEFAULT_LLM_CONFIG.provider;
    }

    #inferProviderFromModel(model) {
        const value = String(model || '').toLowerCase();
        if (!value) return DEFAULT_LLM_CONFIG.provider;
        if (value.includes('deepseek')) return 'deepseek';
        return 'ollama';
    }

    #normalizeCatalogModels(payload) {
        let models = [];
        if (Array.isArray(payload)) {
            models = payload;
        } else if (Array.isArray(payload?.models)) {
            models = payload.models;
        } else if (Array.isArray(payload?.data?.models)) {
            models = payload.data.models;
        } else if (Array.isArray(payload?.data)) {
            models = payload.data;
        }

        const normalized = models
            .map((entry) => {
                const model = String(entry?.id || entry?.model || entry?.name || entry?.slug || '').trim();
                if (!model) return null;
                const provider = this.#normalizeProvider(entry?.provider || entry?.vendor || this.#inferProviderFromModel(model));
                if (!SUPPORTED_MANUS_PROVIDERS.includes(provider)) return null;
                const label = String(entry?.label || entry?.display_name || entry?.name || model).trim();
                return {
                    provider,
                    model,
                    label,
                    raw: entry
                };
            })
            .filter(Boolean);

        const merged = [...normalized];
        for (const fallback of FALLBACK_PROVIDER_MODELS) {
            if (!merged.find((item) => item.provider === fallback.provider && item.model === fallback.model)) {
                merged.push({ ...fallback, raw: null });
            }
        }

        return merged;
    }

    #buildAssistantChatPayload(request, stream) {
        const messages = this.#composeMessages(request);
        const userMessage = messages[messages.length - 1]?.content || request.userPrompt || '';
        return {
            message: userMessage,
            history: messages.slice(0, -1),
            model: request.options?.model || this.llmConfig.model,
            provider: request.options?.provider || this.llmConfig.provider,
            temperature: request.options?.temperature ?? this.llmConfig.temperature,
            max_tokens: this.llmConfig.max_tokens,
            stream: !!stream
        };
    }

    #extractStreamChunk(parsed) {
        if (!parsed) return '';
        if (typeof parsed === 'string') return parsed;
        return parsed?.choices?.[0]?.delta?.content || parsed?.delta?.content || parsed?.content || parsed?.token || parsed?.text || '';
    }

    #isStreamDone(parsed) {
        if (!parsed || typeof parsed !== 'object') return false;
        return parsed?.done === true || parsed?.type === 'done' || parsed?.event === 'done' || parsed?.status === 'completed';
    }

    async #readSSEToText(response) {
        const reader = response.body?.getReader?.();
        if (!reader) return '';
        const decoder = new TextDecoder();
        let buffer = '';
        let text = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const data = line.slice(5).trim();
                if (!data || data === '[DONE]') continue;
                let parsed = data;
                try {
                    parsed = JSON.parse(data);
                } catch {
                    parsed = data;
                }
                const chunk = this.#extractStreamChunk(parsed);
                if (chunk) text += chunk;
            }
        }

        return text.trim();
    }

    async #callLLMCompletion(request, { stream }) {
        const controller = new AbortController();
        this.currentStream = controller;
        const body = this.#buildAssistantChatPayload(request, stream);
        const response = await fetch(`${this.baseUrl}/api/assistant/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': stream ? 'text/event-stream' : 'application/json, text/event-stream'
            },
            body: JSON.stringify(body),
            signal: controller.signal
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`LLM call failed: HTTP ${response.status} ${text || ''}`.trim());
        }

        const contentType = String(response.headers.get('content-type') || '').toLowerCase();
        if (stream || contentType.includes('text/event-stream')) {
            if (stream) return response;
            const text = await this.#readSSEToText(response);
            return {
                choices: [{ message: { content: text } }],
                provider: body.provider,
                model: body.model
            };
        }

        return response.json().catch(() => ({}));
    }

    async #callLLMStream(request, { onChunk, onProgress, onComplete, onError }) {
        const activeProvider = request.options?.provider || this.llmConfig.provider;
        if (onProgress) onProgress(10, `Opening ${activeProvider} stream...`);
        this.isStreaming = true;
        try {
            const response = await this.#callLLMCompletion(request, { stream: true });
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let accumulatedText = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data:')) continue;
                    const data = line.slice(5).trim();
                    if (!data || data === '[DONE]') {
                        const formatted = this.#formatResult({
                            raw: { choices: [{ message: { content: accumulatedText } }] },
                            payload: request,
                            stream: true,
                            text: accumulatedText
                        });
                        this.saveToGarageHistory(formatted);
                        if (onProgress) onProgress(100, 'Stream completed');
                        if (onComplete) onComplete(formatted);
                        this.isStreaming = false;
                        this.currentStream = null;
                        return formatted;
                    }

                    try {
                        const parsed = JSON.parse(data);
                        if (this.#isStreamDone(parsed)) {
                            const formatted = this.#formatResult({
                                raw: { choices: [{ message: { content: accumulatedText } }] },
                                payload: request,
                                stream: true,
                                text: accumulatedText
                            });
                            this.saveToGarageHistory(formatted);
                            if (onProgress) onProgress(100, 'Stream completed');
                            if (onComplete) onComplete(formatted);
                            this.isStreaming = false;
                            this.currentStream = null;
                            return formatted;
                        }

                        const maybeError = typeof parsed?.error === 'string' ? parsed.error : '';
                        if (maybeError) {
                            throw new Error(maybeError);
                        }

                        const chunk = this.#extractStreamChunk(parsed);
                        if (chunk) {
                            accumulatedText += chunk;
                            if (onChunk) onChunk(chunk, accumulatedText);
                            if (onProgress) {
                                const pct = Math.min(95, 30 + (accumulatedText.length / 4000) * 60);
                                onProgress(pct, 'Receiving stream...');
                            }
                        }
                    } catch (err) {
                        if (data) {
                            accumulatedText += data;
                            if (onChunk) onChunk(data, accumulatedText);
                        }
                        console.warn('Failed to parse stream chunk', err, data);
                    }
                }
            }

            const formatted = this.#formatResult({
                raw: { choices: [{ message: { content: accumulatedText } }] },
                payload: request,
                stream: true,
                text: accumulatedText
            });
            this.saveToGarageHistory(formatted);
            if (onProgress) onProgress(100, 'Stream completed');
            if (onComplete) onComplete(formatted);
            this.isStreaming = false;
            this.currentStream = null;
            return formatted;
        } catch (error) {
            if (onError) onError(error);
            this.isStreaming = false;
            this.currentStream = null;
            throw error;
        }
    }

    saveToGarageHistory(entry) {
        this.history.unshift(entry);
        if (this.history.length > this.historyLimit) {
            this.history.length = this.historyLimit;
        }
        this.#persistHistory();
        this.emit('history', this.history.slice());
    }
}

/**
 * UI wiring for the Manus Agent section inside garage.html.
 * This module stays dormant if the Manus section is not present.
 */
const ManusGarageModule = (() => {
    const settingsKey = 'manusGarage.settings';
    const outcomesKey = 'manusGarage.savedOutcomes';
    const API_BASE = DEFAULT_FILES_API_BASE;
    let integration = null;
    let settings = {
        baseUrl: DEFAULT_MANUS_API_BASE,
        timeout: 60,
        analysisType: 'comprehensive',
        llmProvider: DEFAULT_LLM_CONFIG.provider,
        llmModel: DEFAULT_LLM_CONFIG.model,
        streamByDefault: true,
        selectedAssistant: '',
        selectedFiles: [],
        sourceSelections: {
            files: true,
            assistant: true,
            urls: false
        },
        additionalUrls: [],
        assistantFileSelections: {}
    };

    const dom = {};
    let filesCache = [];
    let assistantsCache = [];
    let assistantFilesCache = [];
    let assistantFileSelection = new Set();
    let responseBuffer = '';
    let currentAssistantId = '';
    let currentOutcome = null;
    let savedOutcomes = [];
    let modelCatalog = FALLBACK_PROVIDER_MODELS.map((item) => ({ ...item }));
    let initialized = false;

    function init() {
        if (initialized) return;
        dom.section = document.getElementById('manus-agent-section');
        if (!dom.section) return; // Manus section not rendered yet
        initialized = true;

        cacheDom();
        loadSettings();
        savedOutcomes = loadSavedOutcomes();
        hydrateForm();

        integration = new ManusGarageIntegration({
            baseUrl: settings.baseUrl,
            requestTimeout: (settings.timeout || 60) * 3000,
            filesApiBase: API_BASE,
            llmConfig: {
                provider: settings.llmProvider,
                model: settings.llmModel
            }
        });

        integration.initializeWithGarage(window?.garageContext || {});
        integration.on('history', ({ detail }) => renderHistory(detail));
        integration.on('agent-state', ({ detail }) => updateStatusBadge(detail?.active));

        attachEvents();
        refreshOptions();
        refreshModelCatalog().catch((error) => {
            console.warn('Failed to refresh Manus model catalog', error);
            refreshModelSelect();
        });
        renderHistory(integration.history);
        renderSavedOutcomes();
        updateStatusBadge(integration.agentActive);

        document.addEventListener('garage-data-ready', refreshOptions);
        document.addEventListener('garage-data-refreshed', refreshOptions);
    }

    function cacheDom() {
        dom.statusBadge = document.getElementById('manus-agent-status');
        dom.baseUrl = document.getElementById('manus-backend-url');
        dom.timeout = document.getElementById('manus-timeout');
        dom.analysisType = document.getElementById('manus-analysis-type');
        dom.llmProvider = document.getElementById('manus-llm-provider');
        dom.llmModel = document.getElementById('manus-llm-model');
        dom.refreshModelsBtn = document.getElementById('manus-refresh-models');
        dom.streamToggle = document.getElementById('manus-stream-toggle');
        dom.filesSelect = document.getElementById('manus-files-select');
        dom.uploadBtn = document.getElementById('manus-upload-file-btn');
        dom.fileInput = document.getElementById('manus-file-input');
        dom.selectedOrder = document.getElementById('manus-selected-order');
        dom.assistantSelect = document.getElementById('manus-assistant-select');
        dom.assistantLabel = document.getElementById('manus-active-assistant');
        dom.assistantFilesList = document.getElementById('manus-assistant-files');
        dom.assistantAddAllBtn = document.getElementById('manus-add-assistant-files');
        dom.sourceFilesToggle = document.getElementById('manus-source-files');
        dom.sourceAssistantToggle = document.getElementById('manus-source-assistant');
        dom.sourceUrlsToggle = document.getElementById('manus-source-urls');
        dom.urlAdder = document.getElementById('manus-url-adder');
        dom.urlInput = document.getElementById('manus-url-input');
        dom.addUrlBtn = document.getElementById('manus-add-url-btn');
        dom.urlList = document.getElementById('manus-url-list');
        dom.prompt = document.getElementById('manus-prompt');
        dom.progressBar = document.getElementById('manus-progress-bar');
        dom.progressLabel = document.getElementById('manus-progress-label');
        dom.responseWrapper = document.getElementById('manus-response');
        dom.responseContent = document.getElementById('manus-response-content');
        dom.saveOutcomeBtn = document.getElementById('manus-save-outcome');
        dom.exportOutcomesBtn = document.getElementById('manus-export-outcomes');
        dom.importOutcomesBtn = document.getElementById('manus-import-outcomes');
        dom.importOutcomesInput = document.getElementById('manus-import-outcomes-input');
        dom.savedOutcomesSelect = document.getElementById('manus-saved-outcomes');
        dom.loadOutcomeBtn = document.getElementById('manus-load-outcome');
        dom.continueOutcomeBtn = document.getElementById('manus-continue-outcome');
        dom.deleteOutcomeBtn = document.getElementById('manus-delete-outcome');
        dom.clearBtn = document.getElementById('manus-clear-response');
        dom.runBtn = document.getElementById('manus-run-once');
        dom.streamBtn = document.getElementById('manus-run-stream');
        dom.testBtn = document.getElementById('manus-test-backend');
        dom.startBtn = document.getElementById('manus-start-agent');
        dom.stopBtn = document.getElementById('manus-stop-agent');
        dom.historyList = document.getElementById('manus-history');
        dom.progressBar = document.getElementById('manus-progress-bar');
        dom.progressLabel = document.getElementById('manus-progress-label');
    }

    function attachEvents() {
        dom.baseUrl?.addEventListener('change', () => {
            settings.baseUrl = normalizeManusBaseUrl(dom.baseUrl.value);
            dom.baseUrl.value = settings.baseUrl;
            integration?.setBaseUrl(settings.baseUrl);
            persistSettings();
            refreshModelCatalog().catch((error) => {
                console.warn('Failed to refresh model catalog after backend URL change', error);
                refreshModelSelect();
            });
        });

        dom.timeout?.addEventListener('change', () => {
            settings.timeout = Number(dom.timeout.value) || 60;
            persistSettings();
        });

        dom.analysisType?.addEventListener('change', () => {
            settings.analysisType = dom.analysisType.value;
            persistSettings();
        });

        dom.llmProvider?.addEventListener('change', handleProviderChange);
        dom.llmModel?.addEventListener('change', () => {
            settings.llmModel = dom.llmModel.value;
            integration?.setLLMConfig({
                provider: settings.llmProvider,
                model: settings.llmModel
            });
            persistSettings();
        });
        dom.refreshModelsBtn?.addEventListener('click', handleRefreshModels);

        dom.streamToggle?.addEventListener('change', () => {
            settings.streamByDefault = dom.streamToggle.checked;
            persistSettings();
        });

        dom.assistantSelect?.addEventListener('change', handleAssistantChange);
        dom.filesSelect?.addEventListener('change', handleFilesSelectChange);
        dom.uploadBtn?.addEventListener('click', () => dom.fileInput?.click());
        dom.fileInput?.addEventListener('change', handleFileUploadSelection);
        dom.assistantFilesList?.addEventListener('change', handleAssistantFileToggle);
        dom.assistantAddAllBtn?.addEventListener('click', addAllAssistantFiles);
        dom.selectedOrder?.addEventListener('click', handleOrderAction);

        dom.sourceFilesToggle?.addEventListener('change', handleSourceToggle);
        dom.sourceAssistantToggle?.addEventListener('change', handleSourceToggle);
        dom.sourceUrlsToggle?.addEventListener('change', handleSourceToggle);
        dom.addUrlBtn?.addEventListener('click', handleAddUrl);
        dom.urlList?.addEventListener('click', handleUrlListClick);

        dom.testBtn?.addEventListener('click', handleTestBackend);
        dom.startBtn?.addEventListener('click', handleStartAgent);
        dom.stopBtn?.addEventListener('click', () => integration?.stopAgent());
        dom.runBtn?.addEventListener('click', () => runAnalysis({ stream: false }));
        dom.streamBtn?.addEventListener('click', () => runAnalysis({ stream: true }));
        dom.clearBtn?.addEventListener('click', clearResponse);
        dom.saveOutcomeBtn?.addEventListener('click', handleSaveOutcome);
        dom.exportOutcomesBtn?.addEventListener('click', handleExportOutcomes);
        dom.importOutcomesBtn?.addEventListener('click', () => dom.importOutcomesInput?.click());
        dom.importOutcomesInput?.addEventListener('change', handleImportOutcomes);
        dom.loadOutcomeBtn?.addEventListener('click', handleLoadOutcome);
        dom.continueOutcomeBtn?.addEventListener('click', handleContinueOutcome);
        dom.deleteOutcomeBtn?.addEventListener('click', handleDeleteOutcome);
    }

    async function refreshOptions() {
        filesCache = await fetchFilesFromApi();
        assistantsCache = await fetchAssistantsFromApi();

        settings.selectedFiles = settings.selectedFiles.filter((id) =>
            filesCache.some((file) => file.id === id)
        );

        populateSelect(dom.filesSelect, filesCache, {
            valueKey: 'id',
            labelKey: 'filename',
            placeholder: '-- No files available --',
            multiple: true,
            selected: settings.selectedFiles
        });

        populateSelect(dom.assistantSelect, assistantsCache, {
            valueKey: 'id',
            labelKey: 'name',
            placeholder: '-- Select assistant --',
            selected: [settings.selectedAssistant]
        });

        updateFileSelectFromSettings();
        updateSelectedOrderList();
        updateActiveAssistantLabel();
        renderUrlList();
        syncUrlAdderVisibility();

        if (settings.selectedAssistant) {
            await loadAssistantFiles(settings.selectedAssistant);
        } else {
            assistantFilesCache = [];
            renderAssistantFiles();
        }
    }

    function collectPayload() {
        const filesSourceEnabled = !!dom.sourceFilesToggle?.checked;
        const assistantSourceEnabled = !!dom.sourceAssistantToggle?.checked;
        const urlsEnabled = !!dom.sourceUrlsToggle?.checked;
        const assistantId = dom.assistantSelect?.value;
        const provider = normalizeProviderId(settings.llmProvider || dom.llmProvider?.value);
        const model = (settings.llmModel || dom.llmModel?.value || '').trim();
        const prompt = dom.prompt?.value?.trim();
        if (!assistantId) {
            notify('Select an assistant first', 'warning');
            return null;
        }
        if (!model) {
            notify('Select a model before running the analysis', 'warning');
            return null;
        }
        if (!prompt) {
            notify('Enter a prompt before running the analysis', 'warning');
            return null;
        }
        const orderedFiles = filesSourceEnabled ? getOrderedSelectedFiles({ sync: true }) : [];
        const assistantContextFiles = assistantSourceEnabled ? getAssistantContextFileIds(orderedFiles) : [];
        const combinedFiles = dedupe([...orderedFiles, ...assistantContextFiles]);
        const urlSources = urlsEnabled ? settings.additionalUrls.slice() : [];
        if (!combinedFiles.length && !urlSources.length) {
            notify('Select at least one context source (files, assistant files, or URLs)', 'warning');
            return null;
        }
        return {
            files: combinedFiles,
            assistants: [assistantId],
            prompt,
            provider,
            model,
            temperature: undefined,
            top_p: undefined,
            selectedFilesOrder: orderedFiles,
            assistantContextFiles,
            additionalUrls: urlSources,
            contextOptions: {
                includeAssistantProfile: assistantSourceEnabled,
                useSelectedFiles: filesSourceEnabled,
                includeUrls: urlsEnabled,
                urls: urlSources
            }
        };
    }

    function hydrateForm() {
        if (dom.baseUrl) dom.baseUrl.value = settings.baseUrl;
        if (dom.timeout) dom.timeout.value = settings.timeout;
        if (dom.analysisType) dom.analysisType.value = settings.analysisType;
        if (dom.llmProvider) dom.llmProvider.value = settings.llmProvider;
        if (dom.streamToggle) dom.streamToggle.checked = settings.streamByDefault;
        if (dom.sourceFilesToggle) dom.sourceFilesToggle.checked = settings.sourceSelections.files;
        if (dom.sourceAssistantToggle) dom.sourceAssistantToggle.checked = settings.sourceSelections.assistant;
        if (dom.sourceUrlsToggle) dom.sourceUrlsToggle.checked = settings.sourceSelections.urls;
        refreshModelSelect();
        renderUrlList();
        syncUrlAdderVisibility();
    }

    function loadSettings() {
        try {
            const raw = localStorage.getItem(settingsKey);
            if (raw) {
                const stored = JSON.parse(raw);
                settings = {
                    ...settings,
                    ...stored,
                    sourceSelections: {
                        ...settings.sourceSelections,
                        ...(stored.sourceSelections || {})
                    },
                    additionalUrls: stored.additionalUrls || [],
                    assistantFileSelections: stored.assistantFileSelections || {}
                };
                settings.baseUrl = normalizeManusBaseUrl(settings.baseUrl);
                settings.llmProvider = normalizeProviderId(settings.llmProvider || inferProviderFromModelId(settings.llmModel));
                if (!settings.llmModel) {
                    settings.llmModel = modelCatalogForProvider(settings.llmProvider)[0]?.model || DEFAULT_LLM_CONFIG.model;
                }
            }
        } catch (error) {
            console.warn('Failed to read Manus settings', error);
        }
    }

    function normalizeManusBaseUrl(url) {
        const candidate = (url || '').trim();
        if (!candidate || candidate === '/api/manus' || candidate.endsWith('/api/manus')) {
            return DEFAULT_MANUS_API_BASE;
        }
        if (/^https?:\/\/[^/]*:8078(\/|$)/i.test(candidate)) {
            return DEFAULT_MANUS_API_BASE;
        }
        if (/^https?:\/\//i.test(candidate)) {
            return candidate.replace(/\/+$/, '');
        }
        return `/${candidate.replace(/^\/+/, '').replace(/\/+$/, '')}`;
    }

    function normalizeProviderId(provider) {
        const raw = String(provider || '').trim().toLowerCase();
        if (raw.includes('deepseek')) return 'deepseek';
        if (raw.includes('ollama') || raw === 'local') return 'ollama';
        return SUPPORTED_MANUS_PROVIDERS.includes(raw) ? raw : DEFAULT_LLM_CONFIG.provider;
    }

    function inferProviderFromModelId(model) {
        const value = String(model || '').toLowerCase();
        if (value.includes('deepseek')) return 'deepseek';
        return 'ollama';
    }

    function modelCatalogForProvider(provider) {
        const normalized = normalizeProviderId(provider);
        return modelCatalog.filter((item) => item.provider === normalized);
    }

    function refreshModelSelect() {
        if (!dom.llmModel) return;

        const provider = normalizeProviderId(settings.llmProvider || dom.llmProvider?.value);
        if (dom.llmProvider) dom.llmProvider.value = provider;

        const options = modelCatalogForProvider(provider);
        const fallback = FALLBACK_PROVIDER_MODELS.filter((item) => item.provider === provider);
        const candidates = options.length ? options : fallback;

        if (!candidates.length) {
            dom.llmModel.innerHTML = '<option value="">-- No models available --</option>';
            settings.llmModel = '';
            return;
        }

        const selectedModel = settings.llmModel || candidates[0].model;
        dom.llmModel.innerHTML = '';
        for (const item of candidates) {
            const option = document.createElement('option');
            option.value = item.model;
            option.textContent = item.label || item.model;
            dom.llmModel.appendChild(option);
        }

        if (candidates.some((item) => item.model === selectedModel)) {
            dom.llmModel.value = selectedModel;
            settings.llmModel = selectedModel;
        } else {
            dom.llmModel.value = candidates[0].model;
            settings.llmModel = candidates[0].model;
        }

        integration?.setLLMConfig({
            provider,
            model: settings.llmModel
        });
    }

    async function refreshModelCatalog() {
        if (!integration) {
            refreshModelSelect();
            return;
        }

        try {
            const catalog = await integration.fetchModelCatalog();
            if (Array.isArray(catalog) && catalog.length) {
                modelCatalog = catalog;
            } else {
                modelCatalog = FALLBACK_PROVIDER_MODELS.map((item) => ({ ...item }));
            }
        } catch (error) {
            modelCatalog = FALLBACK_PROVIDER_MODELS.map((item) => ({ ...item }));
            notify(`Model catalog unavailable, using defaults: ${error.message}`, 'warning');
        }

        refreshModelSelect();
        persistSettings();
    }

    function handleProviderChange() {
        settings.llmProvider = normalizeProviderId(dom.llmProvider?.value);
        refreshModelSelect();
        persistSettings();
    }

    async function handleRefreshModels() {
        setBusy(dom.refreshModelsBtn, true, 'Refreshing...');
        try {
            await refreshModelCatalog();
            notify('Model catalog refreshed', 'success');
        } catch (error) {
            notify(`Failed to refresh models: ${error.message}`, 'error');
        } finally {
            setBusy(dom.refreshModelsBtn, false);
        }
    }

    function persistSettings() {
        try {
            localStorage.setItem(settingsKey, JSON.stringify(settings));
        } catch (error) {
            console.warn('Failed to persist Manus settings', error);
        }
    }

    function setBusy(button, busy, text) {
        if (!button) return;
        if (busy) {
            button.dataset.originalText = button.innerHTML;
            button.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${text || 'Working...'}`;
            button.disabled = true;
        } else {
            button.innerHTML = button.dataset.originalText || 'Action';
            button.disabled = false;
        }
    }

    function notify(message, type = 'info') {
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else {
            console[type === 'error' ? 'error' : 'log'](`[Manus] ${message}`);
        }
    }

    function formatMarkdown(text) {
        if (window.marked) {
            return window.marked.parse(text);
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function escapeHtml(str = '') {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    async function handleAssistantChange() {
        const assistantId = dom.assistantSelect?.value || '';
        settings.selectedAssistant = assistantId;
        persistSettings();
        updateActiveAssistantLabel();
        await loadAssistantFiles(assistantId);
    }

    async function loadAssistantFiles(assistantId) {
        currentAssistantId = assistantId;
        if (!assistantId) {
            assistantFilesCache = [];
            renderAssistantFiles();
            return;
        }

        dom.assistantFilesList.innerHTML = '<li class="loading">Loading assistant files...</li>';
        try {
            const resp = await fetch(`${API_BASE}/assistants/${assistantId}/files`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const payload = await resp.json();
            assistantFilesCache = (Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []).map((file) => ({
                ...file,
                id: file.id || file.file_id,
                filename: file.filename || file.name || file.id,
                path: file.path || file.filepath || file.relative_path || file.absolute_path || file.storage_path || `data/files/${file.id || file.file_id}`
            }));
        } catch (error) {
            assistantFilesCache = [];
            notify(`Failed to load assistant files: ${error.message}`, 'error');
        }

        applyAssistantFileDefaults();
        renderAssistantFiles();
        updateSelectedOrderList();
    }

    function applyAssistantFileDefaults() {
        if (!currentAssistantId) return;
        const saved = settings.assistantFileSelections?.[currentAssistantId];
        if (Array.isArray(saved)) {
            assistantFileSelection = new Set(saved);
        } else {
            assistantFileSelection = new Set(assistantFilesCache.map((file) => file.id));
        }
        syncAssistantSelections();
    }

    function syncAssistantSelections() {
        const includeIds = Array.from(assistantFileSelection || []);
        includeIds.forEach((id) => addFileToSelection(id, { silent: true }));
        assistantFilesCache.forEach((file) => {
            if (!assistantFileSelection?.has(file.id)) {
                removeFileFromSelection(file.id, { silent: true });
            }
        });
        persistAssistantSelection();
        renderAssistantFiles();
        updateSelectedOrderList();
    }

    function persistAssistantSelection() {
        if (!currentAssistantId) return;
        settings.assistantFileSelections[currentAssistantId] = Array.from(assistantFileSelection || []);
        persistSettings();
    }

    function renderAssistantFiles() {
        if (!dom.assistantFilesList) return;
        if (!assistantFilesCache.length) {
            dom.assistantFilesList.innerHTML = '<li class="empty">No files attached to this assistant.</li>';
            return;
        }

        dom.assistantFilesList.innerHTML = assistantFilesCache.map((file) => {
            const checked = settings.selectedFiles.includes(file.id);
            const size = file.bytes ? ` (${formatBytes(file.bytes)})` : '';
            return `
                <li>
                    <label>
                        <input type="checkbox" data-file-id="${file.id}" ${checked ? 'checked' : ''}>
                        <span>${escapeHtml(file.filename || file.name || file.id)}${size}</span>
                    </label>
                </li>
            `;
        }).join('');
    }

    function handleAssistantFileToggle(event) {
        const target = event.target;
        if (!target.matches('input[type="checkbox"][data-file-id]')) return;

        const fileId = target.dataset.fileId;
        if (target.checked) {
            assistantFileSelection?.add(fileId);
            addFileToSelection(fileId);
        } else {
            assistantFileSelection?.delete(fileId);
            removeFileFromSelection(fileId);
        }
        persistAssistantSelection();
    }

    function addAllAssistantFiles() {
        if (!assistantFilesCache.length) return;
        assistantFileSelection = new Set(assistantFilesCache.map((file) => file.id));
        syncAssistantSelections();
    }

    function handleFilesSelectChange() {
        const selectedIds = Array.from(dom.filesSelect?.selectedOptions || []).map((opt) => opt.value);
        const ordered = settings.selectedFiles.filter((id) => selectedIds.includes(id));
        selectedIds.forEach((id) => {
            if (!ordered.includes(id)) ordered.push(id);
        });
        settings.selectedFiles = ordered;
        persistSettings();
        updateSelectedOrderList();
        renderAssistantFiles();
    }

    function addFileToSelection(fileId, { silent } = {}) {
        if (!fileId || settings.selectedFiles.includes(fileId)) return;
        settings.selectedFiles.push(fileId);
        updateFileSelectFromSettings();
        if (!silent) {
            persistSettings();
            updateSelectedOrderList();
        }
    }

    function removeFileFromSelection(fileId, { silent } = {}) {
        const index = settings.selectedFiles.indexOf(fileId);
        if (index === -1) return;
        settings.selectedFiles.splice(index, 1);
        updateFileSelectFromSettings();
        if (!silent) {
            persistSettings();
            updateSelectedOrderList();
            renderAssistantFiles();
        }
    }

    function updateSelectedOrderList() {
        if (!dom.selectedOrder) return;
        if (!settings.selectedFiles.length) {
            dom.selectedOrder.innerHTML = '<li class="empty">No files selected.</li>';
            persistSettings();
            return;
        }

        dom.selectedOrder.innerHTML = settings.selectedFiles.map((id, idx) => {
            const meta = resolveFileMeta(id);
            const label = meta?.filename || meta?.name || id;
            return `
                <li class="order-item" data-file-id="${id}">
                    <div class="order-text">
                        <strong>${escapeHtml(label)}</strong>
                        ${meta?.purpose ? `<small>${escapeHtml(meta.purpose)}</small>` : ''}
                    </div>
                    <div class="order-actions">
                        <button type="button" class="btn btn-light btn-sm" data-action="move-up" data-file-id="${id}" ${idx === 0 ? 'disabled' : ''}>
                            <i class="fas fa-chevron-up"></i>
                        </button>
                        <button type="button" class="btn btn-light btn-sm" data-action="move-down" data-file-id="${id}" ${idx === settings.selectedFiles.length - 1 ? 'disabled' : ''}>
                            <i class="fas fa-chevron-down"></i>
                        </button>
                        <button type="button" class="btn btn-light btn-sm" data-action="remove" data-file-id="${id}">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </li>
            `;
        }).join('');
        persistSettings();
    }

    function handleOrderAction(event) {
        const actionBtn = event.target.closest('[data-action]');
        if (!actionBtn) return;

        const { action, fileId } = actionBtn.dataset;
        if (action === 'remove') {
            removeFileFromSelection(fileId);
            assistantFileSelection?.delete(fileId);
            persistAssistantSelection();
            renderAssistantFiles();
            return;
        }

        const delta = action === 'move-up' ? -1 : 1;
        moveFileInSelection(fileId, delta);
    }

    function moveFileInSelection(fileId, delta) {
        const idx = settings.selectedFiles.indexOf(fileId);
        if (idx < 0) return;
        const newIdx = idx + delta;
        if (newIdx < 0 || newIdx >= settings.selectedFiles.length) return;

        const [item] = settings.selectedFiles.splice(idx, 1);
        settings.selectedFiles.splice(newIdx, 0, item);
        updateSelectedOrderList();
    }

    function updateFileSelectFromSettings() {
        if (!dom.filesSelect) return;
        const selectedSet = new Set(settings.selectedFiles);
        Array.from(dom.filesSelect.options).forEach((opt) => {
            opt.selected = selectedSet.has(opt.value);
        });
    }

    async function handleFileUploadSelection(event) {
        const files = Array.from(event.target.files || []);
        if (!files.length) return;
        await uploadFilesToApi(files);
        dom.fileInput.value = '';
    }

    async function uploadFilesToApi(files) {
        if (!files.length) return;
        setBusy(dom.uploadBtn, true, 'Uploading...');
        try {
            for (const file of files) {
                const formData = new FormData();
                formData.append('purpose', 'assistants');
                formData.append('file', file);
                const resp = await fetch(`${API_BASE}/files`, {
                    method: 'POST',
                    body: formData
                });
                if (!resp.ok) throw new Error(`Upload failed: HTTP ${resp.status}`);
            }
            notify('Files uploaded successfully', 'success');
            await refreshOptions();
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            setBusy(dom.uploadBtn, false);
        }
    }

    function handleSourceToggle() {
        settings.sourceSelections = {
            files: !!dom.sourceFilesToggle?.checked,
            assistant: !!dom.sourceAssistantToggle?.checked,
            urls: !!dom.sourceUrlsToggle?.checked
        };
        persistSettings();
        syncUrlAdderVisibility();
    }

    function syncUrlAdderVisibility() {
        if (!dom.sourceUrlsToggle || !dom.urlAdder) return;
        if (dom.sourceUrlsToggle.checked) {
            dom.urlAdder.classList.remove('hidden');
        } else {
            dom.urlAdder.classList.add('hidden');
        }
    }

    function handleAddUrl() {
        const url = dom.urlInput?.value?.trim();
        if (!url) return;
        try {
            new URL(url);
        } catch {
            notify('Enter a valid URL', 'warning');
            return;
        }

        if (!settings.additionalUrls.includes(url)) {
            settings.additionalUrls.push(url);
            persistSettings();
            renderUrlList();
        }
        dom.urlInput.value = '';
    }

    function handleUrlListClick(event) {
        const btn = event.target.closest('[data-action="remove-url"]');
        if (!btn) return;
        const index = Number(btn.dataset.index);
        if (Number.isNaN(index)) return;
        settings.additionalUrls.splice(index, 1);
        persistSettings();
        renderUrlList();
    }

    function renderUrlList() {
        if (!dom.urlList) return;
        if (!settings.additionalUrls.length) {
            dom.urlList.innerHTML = '<li class="empty">No URLs added.</li>';
            return;
        }

        dom.urlList.innerHTML = settings.additionalUrls.map((url, index) => `
            <li>
                <span>${escapeHtml(url)}</span>
                <button type="button" class="btn btn-light btn-sm" data-action="remove-url" data-index="${index}">
                    <i class="fas fa-times"></i>
                </button>
            </li>
        `).join('');
    }

    async function fetchFilesFromApi() {
        try {
            const resp = await fetch(`${API_BASE}/files`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const payload = await resp.json();
            const data = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : [];
            return data.map((file) => ({
                ...file,
                id: file.id || file.file_id || file.uuid || file.name,
                filename: file.filename || file.name || file.id,
                path: file.path || file.filepath || file.relative_path || file.absolute_path || file.storage_path || `data/files/${file.id || file.file_id}`
            }));
        } catch (error) {
            console.warn('Failed to fetch files from API', error);
            notify('Falling back to cached files', 'warning');
            return gatherFiles();
        }
    }

    async function fetchAssistantsFromApi() {
        try {
            const resp = await fetch(`${API_BASE}/assistants`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const payload = await resp.json();
            const data = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : [];
            return data.map((assistant) => ({
                ...assistant,
                id: assistant.id || assistant.assistant_id,
                name: assistant.name || assistant.display_name || assistant.id
            }));
        } catch (error) {
            console.warn('Failed to fetch assistants from API', error);
            notify('Falling back to cached assistants', 'warning');
            return gatherAssistantsFromWindow();
        }
    }

    function gatherAssistantsFromWindow() {
        const sources = [
            window?.garageAssistants,
            window?.availableAssistants,
            window?.assistantsCache,
            window?.GARAGE_ASSISTANTS_CACHE
        ].filter(Boolean);

        const merged = [];
        for (const collection of sources) {
            for (const item of collection) {
                const id = item.id || item.assistant_id;
                if (!id) continue;
                if (!merged.find((existing) => (existing.id || existing.assistant_id) === id)) {
                    merged.push({ ...item, id });
                }
            }
        }
        return merged;
    }

    function resolveFileMeta(fileId) {
        const collections = [filesCache, assistantFilesCache].filter(Boolean);
        for (const list of collections) {
            const found = list?.find?.((item) => item.id === fileId || item.file_id === fileId);
            if (found) return found;
        }
        return null;
    }

    function formatBytes(bytes) {
        if (!bytes && bytes !== 0) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unit = 0;
        while (size >= 1024 && unit < units.length - 1) {
            size /= 1024;
            unit++;
        }
        return `${size.toFixed(1)}${units[unit]}`;
    }

    function updateActiveAssistantLabel() {
        if (!dom.assistantLabel) return;
        const assistantId = settings.selectedAssistant;
        const assistant = assistantsCache.find((item) => item.id === assistantId);
        dom.assistantLabel.textContent = assistant ? assistant.name || assistantId : 'None';
    }

    function updateStatusBadge(active = false) {
        if (!dom.statusBadge) return;
        dom.statusBadge.classList.toggle('active', !!active);
        dom.statusBadge.textContent = active ? 'Agent Active' : 'Agent Idle';
    }

    function getAssistantContextFileIds(currentSelection = settings.selectedFiles) {
        const assistantIds = new Set(assistantFilesCache.map((file) => file.id));
        return currentSelection.filter((id) => assistantIds.has(id));
    }

    function dedupe(list) {
        const seen = new Set();
        return list.filter((item) => {
            if (seen.has(item)) return false;
            seen.add(item);
            return true;
        });
    }

    function toggleInteraction(disabled) {
        [
            dom.runBtn,
            dom.streamBtn,
            dom.startBtn,
            dom.stopBtn,
            dom.testBtn,
            dom.filesSelect,
            dom.assistantSelect,
            dom.llmProvider,
            dom.llmModel,
            dom.refreshModelsBtn,
            dom.prompt,
            dom.uploadBtn,
            dom.addUrlBtn
        ]
            .filter(Boolean)
            .forEach((el) => {
                el.disabled = !!disabled;
            });
    }

    document.addEventListener('DOMContentLoaded', init);

    async function handleTestBackend() {
        if (!integration) {
            notify('Manus module not ready yet', 'warning');
            return;
        }

        setBusy(dom.testBtn, true, 'Testing...');
        try {
            const result = await integration.checkHealth();
            if (result.healthy) {
                const modelCount = Array.isArray(result?.data?.models) ? result.data.models.length : 0;
                notify(`Manus backend is reachable (${modelCount} models available)`, 'success');
            } else {
                notify(`Backend unhealthy: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            setBusy(dom.testBtn, false);
        }
    }

    async function handleStartAgent() {
        if (!integration) {
            notify('Manus module not ready yet', 'warning');
            return;
        }

        setBusy(dom.startBtn, true, 'Starting...');
        try {
            await integration.startAgent();
            notify('Manus agent started', 'success');
        } catch (error) {
            notify(error.message || 'Failed to start Manus agent', 'error');
        } finally {
            setBusy(dom.startBtn, false);
        }
    }

    async function runAnalysis({ stream }) {
        if (!integration) return;

        const payload = collectPayload();
        if (!payload) return;

        integration.setLLMConfig({
            provider: payload.provider,
            model: payload.model
        });

        payload.analysisType = settings.analysisType;
        payload.timeout = settings.timeout;
        payload.stream = stream;

        toggleInteraction(true);
        updateProgress(5, 'Preparing analysis...');
        responseBuffer = '';
        clearResponse();

        try {
            if (stream) {
                await integration.analyzeFilesStream(payload, {
                    onChunk: handleStreamChunk,
                    onProgress: updateProgress,
                    onComplete: renderResponse,
                    onError: (error) => renderError(error)
                });
                notify('Streaming analysis completed', 'success');
            } else {
                const result = await integration.analyzeFilesWithAssistants(payload, updateProgress);
                renderResponse(result);
                notify('Analysis completed', 'success');
            }
        } catch (error) {
            renderError(error);
            notify(error.message || 'Analysis failed', 'error');
        } finally {
            toggleInteraction(false);
            updateProgress(0, 'Idle');
        }
    }

    function handleStreamChunk(chunk, cumulative) {
        responseBuffer = cumulative;
        if (dom.responseContent) {
            dom.responseWrapper?.classList.remove('hidden');
            dom.responseContent.innerHTML = formatMarkdown(responseBuffer);
        }
    }

    function renderResponse(result) {
        if (!dom.responseWrapper || !dom.responseContent) return;
        currentOutcome = result;
        dom.responseWrapper.classList.remove('hidden');
        dom.responseContent.innerHTML = formatMarkdown(result?.result || '');
    }

    function renderError(error) {
        if (!dom.responseWrapper || !dom.responseContent) return;
        currentOutcome = null;
        dom.responseWrapper.classList.remove('hidden');
        dom.responseContent.innerHTML = `<div class="error">${escapeHtml(error?.message || 'Unknown error')}</div>`;
    }

    function updateProgress(percent = 0, label = 'Idle') {
        if (dom.progressBar) dom.progressBar.style.width = `${percent}%`;
        if (dom.progressLabel) dom.progressLabel.textContent = label;
    }

    function renderHistory(history = []) {
        if (!dom.historyList) return;
        if (!history.length) {
            dom.historyList.innerHTML = '<li class="empty">No Manus runs yet.</li>';
            return;
        }
        dom.historyList.innerHTML = history.slice(0, 10).map((item) => {
            const time = new Date(item.timestamp).toLocaleString();
            return `
                <li class="manus-history-item">
                    <div class="manus-history-meta">
                        <span>${time}</span>
                        <span>${item.analysisType || 'default'}</span>
                    </div>
                    <div class="manus-history-prompt">${escapeHtml(item.prompt || '')}</div>
                </li>
            `;
        }).join('');
    }

    function populateSelect(select, items, {
        valueKey = 'id',
        labelKey = 'name',
        placeholder = '-- none --',
        multiple = false,
        selected = []
    } = {}) {
        if (!select) return;

        const selectedSet = new Set(selected.map(String));
        select.innerHTML = '';

        if (!items.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = placeholder;
            option.disabled = true;
            option.selected = true;
            select.appendChild(option);
            return;
        }

        items.forEach((item) => {
            const value = String(item[valueKey]);
            const option = document.createElement('option');
            option.value = value;
            option.textContent = item[labelKey] || value;
            option.selected = multiple ? selectedSet.has(value) : selectedSet.size ? selectedSet.has(value) : false;
            select.appendChild(option);
        });
    }

    function gatherFiles() {
        const sources = [
            window?.garageFiles,
            window?.availableFiles,
            window?.filesCache,
            window?.GARAGE_FILES_CACHE
        ].filter(Boolean);

        const merged = [];
        for (const collection of sources) {
            for (const item of collection) {
                const id = item.id || item.file_id;
                if (!id) continue;
                if (!merged.find((existing) => (existing.id || existing.file_id) === id)) {
                    merged.push({ ...item, id });
                }
            }
        }
        return merged;
    }
    function clearResponse() {
        if (!dom.responseWrapper || !dom.responseContent) return;
        dom.responseContent.innerHTML = '';
        dom.responseWrapper.classList.add('hidden');
        responseBuffer = '';
        currentOutcome = null;
    }

    function getOrderedSelectedFiles({ sync = false } = {}) {
        const domSelected = Array.from(dom.filesSelect?.selectedOptions || [])
            .map((opt) => opt.value)
            .filter(Boolean);

        let ordered = settings.selectedFiles.slice();

        if (domSelected.length) {
            ordered = ordered.filter((id) => domSelected.includes(id));
            domSelected.forEach((id) => {
                if (!ordered.includes(id)) ordered.push(id);
            });
        }

        if (sync) {
            settings.selectedFiles = ordered;
            persistSettings();
            updateSelectedOrderList();
            updateFileSelectFromSettings();
        }

        return ordered;
    }

    function renderSavedOutcomes() {
        if (!dom.savedOutcomesSelect) return;
        dom.savedOutcomesSelect.innerHTML = '';

        if (!savedOutcomes.length) {
            const option = document.createElement('option');
            option.textContent = 'No saved outcomes yet.';
            option.disabled = true;
            option.selected = true;
            dom.savedOutcomesSelect.appendChild(option);
            return;
        }

        savedOutcomes.forEach((outcome) => {
            const option = document.createElement('option');
            option.value = outcome.id;
            option.textContent = `${new Date(outcome.createdAt).toLocaleString()} — ${outcome.title}`;
            dom.savedOutcomesSelect.appendChild(option);
        });
    }

    function loadSavedOutcomes() {
        try {
            const raw = localStorage.getItem(outcomesKey);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            console.warn('Failed to load saved outcomes', error);
            return [];
        }
    }

    function persistSavedOutcomes() {
        try {
            localStorage.setItem(outcomesKey, JSON.stringify(savedOutcomes.slice(0, 100)));
        } catch (error) {
            console.warn('Failed to persist outcomes', error);
        }
    }

    function getSelectedOutcome() {
        const selectedId = dom.savedOutcomesSelect?.value;
        if (!selectedId) return null;
        return savedOutcomes.find((item) => item.id === selectedId) || null;
    }

    function handleSaveOutcome() {
        const outcome = currentOutcome;
        if (!outcome?.result) {
            notify('Run an analysis before saving.', 'warning');
            return;
        }

        const title = prompt('Name this outcome:', outcome.prompt?.slice(0, 60) || 'Untitled outcome');
        if (!title) return;

        const entry = {
            id: `outcome_${Date.now()}`,
            title,
            createdAt: new Date().toISOString(),
            data: outcome
        };

        savedOutcomes.unshift(entry);
        persistSavedOutcomes();
        renderSavedOutcomes();
        notify('Outcome saved.', 'success');
    }

    function handleLoadOutcome() {
        const outcome = getSelectedOutcome();
        if (!outcome) {
            notify('Select an outcome to load.', 'warning');
            return;
        }

        currentOutcome = outcome.data;
        renderResponse(outcome.data);
        notify('Outcome loaded into preview.', 'success');
    }

    function handleContinueOutcome() {
        const outcome = getSelectedOutcome() || (currentOutcome ? { data: currentOutcome, title: currentOutcome.prompt?.slice(0, 40) || 'Current outcome' } : null);
        if (!outcome?.data?.result) {
            notify('Select or load an outcome first.', 'warning');
            return;
        }

        const block = `\n\n[Outcome Context: ${outcome.title || 'Previous Result'}]\n${outcome.data.result}\n`;
        dom.prompt.value = `${dom.prompt.value.trim()}\n${block}`.trim();
        notify('Outcome context appended to prompt.', 'success');
    }

    function handleDeleteOutcome() {
        const outcome = getSelectedOutcome();
        if (!outcome) {
            notify('Select an outcome to delete.', 'warning');
            return;
        }
        savedOutcomes = savedOutcomes.filter((item) => item.id !== outcome.id);
        persistSavedOutcomes();
        renderSavedOutcomes();
        notify('Outcome deleted.', 'success');
    }

    function handleExportOutcomes() {
        if (!savedOutcomes.length) {
            notify('No saved outcomes to export.', 'warning');
            return;
        }

        const blob = new Blob([JSON.stringify(savedOutcomes, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `manus-outcomes-${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        notify('Outcomes exported.', 'success');
    }

    async function handleImportOutcomes(event) {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        try {
            const text = await file.text();
            const parsed = JSON.parse(text);
            if (!Array.isArray(parsed)) throw new Error('Invalid file format');
            savedOutcomes = parsed.concat(savedOutcomes).slice(0, 100);
            persistSavedOutcomes();
            renderSavedOutcomes();
            notify('Outcomes imported.', 'success');
        } catch (error) {
            notify(`Failed to import outcomes: ${error.message}`, 'error');
        }
    }
})();