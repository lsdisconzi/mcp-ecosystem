/**
 * Chat Interface Module
 * Handles AI-assisted chat with vector database context
 */

const QdrantChat = {
    // Chat state
    state: {
        messages: [],
        currentAssistant: null,
        isStreaming: false,
        contextCollection: null,
        sourceType: 'qdrant',       // 'qdrant' | 'neo4j' | 'hybrid'
        neo4jMode: 'cypher',        // 'cypher' | 'schema'
        neo4jCypher: ''
    },

    // Initialize chat
    init() {
        this.setupEventListeners();
        this.loadChatHistory();
    },

    // Setup event listeners
    setupEventListeners() {
        // Send message
        const sendButton = document.getElementById('chat-send-btn');
        const chatInput = document.getElementById('chat-input');
        
        if (sendButton && chatInput) {
            sendButton.addEventListener('click', () => this.sendMessage());
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
        }

        // Clear chat
        const clearButton = document.getElementById('clear-chat-btn');
        if (clearButton) {
            clearButton.addEventListener('click', () => this.clearChat());
        }

        // Save chat
        const saveButton = document.getElementById('save-chat-btn');
        if (saveButton) {
            saveButton.addEventListener('click', () => this.saveChat());
        }

        // Load chat
        const loadButton = document.getElementById('load-chat-btn');
        if (loadButton) {
            loadButton.addEventListener('click', () => this.loadChatFromFile());
        }

        // Assistant selection
        const assistantSelect = document.getElementById('chat-assistant-select');
        if (assistantSelect) {
            assistantSelect.addEventListener('change', (e) => {
                this.state.currentAssistant = e.target.value || null;
            });
        }

        // Collection selection
        const collectionSelect = document.getElementById('chat-collection-select');
        if (collectionSelect) {
            collectionSelect.addEventListener('change', (e) => {
                this.state.contextCollection = e.target.value || null;
            });
        }

        // Knowledge source selection (Qdrant / Neo4j / Hybrid)
        const sourceSelect = document.getElementById('chat-source-type');
        const qdrantBlock = document.getElementById('chat-source-qdrant');
        const neo4jBlock = document.getElementById('chat-source-neo4j');
        const applySourceVisibility = () => {
            const v = this.state.sourceType;
            if (qdrantBlock) qdrantBlock.hidden = (v === 'neo4j');
            if (neo4jBlock) neo4jBlock.hidden = (v === 'qdrant');
        };
        if (sourceSelect) {
            this.state.sourceType = sourceSelect.value || 'qdrant';
            applySourceVisibility();
            sourceSelect.addEventListener('change', (e) => {
                this.state.sourceType = e.target.value || 'qdrant';
                applySourceVisibility();
            });
        }

        const neo4jModeSelect = document.getElementById('chat-neo4j-mode');
        if (neo4jModeSelect) {
            this.state.neo4jMode = neo4jModeSelect.value || 'cypher';
            neo4jModeSelect.addEventListener('change', (e) => {
                this.state.neo4jMode = e.target.value || 'cypher';
            });
        }
        const neo4jCypher = document.getElementById('chat-neo4j-cypher');
        if (neo4jCypher) {
            this.state.neo4jCypher = neo4jCypher.value || '';
            neo4jCypher.addEventListener('input', (e) => {
                this.state.neo4jCypher = e.target.value || '';
            });
        }
    },

    // Unified context fetch dispatching on sourceType
    async getContext(query) {
        const t = this.state.sourceType;
        if (t === 'neo4j') return this.getNeo4jContext(query);
        if (t === 'hybrid') {
            const [q, g] = await Promise.all([
                this.getRAGContext(query).catch(() => ''),
                this.getNeo4jContext(query).catch(() => '')
            ]);
            return [q && `# Vector context\n${q}`, g && `# Graph context\n${g}`]
                .filter(Boolean).join('\n\n---\n\n');
        }
        return this.getRAGContext(query);
    },

    async getNeo4jContext(query) {
        const mode = this.state.neo4jMode || 'cypher';
        if (mode === 'schema') {
            try {
                const r = await fetch('/v1/neo4j/stats');
                if (!r.ok) return '';
                const data = await r.json();
                return `Neo4j graph stats:\n${JSON.stringify(data, null, 2)}`;
            } catch (e) {
                console.warn('Neo4j stats failed:', e);
                return '';
            }
        }
        const cypher = (this.state.neo4jCypher || '').trim();
        if (!cypher) {
            throw new Error('Please enter a Cypher query for the Neo4j source.');
        }
        const r = await fetch('/v1/neo4j/rag-context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, cypher, limit: 25 })
        });
        if (!r.ok) {
            const detail = await r.text();
            throw new Error(`Neo4j context error: ${r.status} ${detail}`);
        }
        const data = await r.json();
        return data.context || '';
    },

    // Send message
    async sendMessage() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        
        if (!message) return;
        
        // Add user message
        this.addMessage(message, 'user');
        input.value = '';
        
        // Show thinking indicator
        const thinkingId = this.showThinking();
        
        try {
            let response;
            
            if (this.state.currentAssistant) {
                // Use AI assistant
                response = await this.getAssistantResponse(message);
            } else {
                // Use manual RAG
                response = await this.getRAGResponse(message);
            }
            
            // Remove thinking indicator
            this.removeThinking(thinkingId);
            
            // Add assistant response
            this.addMessage(response, 'assistant');
            
        } catch (error) {
            console.error('Chat error:', error);
            this.removeThinking(thinkingId);
            this.addMessage(`Error: ${error.message}`, 'error');
        }
    },

    // Get AI assistant response
    async getAssistantResponse(message) {
        const assistantId = this.state.currentAssistant;
        if (!assistantId) {
            throw new Error('No assistant selected');
        }
        
        // Get context (Qdrant / Neo4j / Hybrid)
        let context = '';
        try {
            context = await this.getContext(message);
        } catch (e) {
            console.warn('Context fetch failed:', e);
        }
        
        // Prepare messages
        const messages = [
            ...this.state.messages.map(msg => ({
                role: msg.sender,
                content: msg.content
            })),
            {
                role: 'user',
                content: context ? `${context}\n\nUser question: ${message}` : message
            }
        ];
        
        // Call assistant API
        const response = await fetch(`/api/v1/assistants/${assistantId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: messages,
                stream: false
            })
        });
        
        if (!response.ok) {
            throw new Error(`Assistant API error: ${response.status}`);
        }
        
        const data = await response.json();
        return data.choices[0]?.message?.content || 'No response from assistant';
    },

    // Get RAG response
    async getRAGResponse(message) {
        // Dispatch by source type
        const context = await this.getContext(message);
        if (!context) {
            throw new Error('No context available. Select a collection or provide a Neo4j Cypher query.');
        }

        // Prepare prompt
        const prompt = `
Context from knowledge base:
${context}

Based on the context above, answer the following question:
${message}

If the context doesn't contain enough information to answer the question, 
say "I don't have enough information in my knowledge base to answer this question."
`;
        
        // Call generic chat API
        const response = await fetch('/api/v1/chat/completions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: 'gpt-3.5-turbo',
                messages: [{ role: 'user', content: prompt }],
                temperature: 0.7,
                max_tokens: 500
            })
        });
        
        if (!response.ok) {
            throw new Error(`Chat API error: ${response.status}`);
        }
        
        const data = await response.json();
        return data.choices[0]?.message?.content || 'No response';
    },

    // Get RAG context
    async getRAGContext(query) {
        if (!this.state.contextCollection) return '';
        
        try {
            const searchResults = await QdrantManager.search(
                this.state.contextCollection,
                query,
                { limit: 3 }
            );
            
            return searchResults.results
                .map((result, i) => `Source ${i + 1}: ${result.payload?.text || ''}`)
                .join('\n\n');
        } catch (error) {
            console.warn('Failed to get RAG context:', error);
            return '';
        }
    },

    // UI methods
    addMessage(content, sender) {
        const message = {
            id: Date.now(),
            content: content,
            sender: sender,
            timestamp: new Date().toISOString()
        };
        
        this.state.messages.push(message);
        this.renderMessage(message);
        
        // Save to history
        this.saveChatHistory();
    },

    renderMessage(message) {
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${message.sender}`;
        
        // Format content (handle markdown, code blocks, etc.)
        let formattedContent = this.formatMessageContent(message.content);
        
        messageDiv.innerHTML = `
            <div class="chat-bubble ${message.sender}">
                ${formattedContent}
            </div>
            <div class="chat-timestamp">
                ${new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
        `;
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    },

    formatMessageContent(content) {
        // Simple formatting - in production, use a proper markdown library
        let formatted = QdrantManager.escapeHtml(content);
        
        // Convert URLs to links
        formatted = formatted.replace(
            /(https?:\/\/[^\s]+)/g,
            '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
        );
        
        // Convert line breaks
        formatted = formatted.replace(/\n/g, '<br>');
        
        // Simple code block detection
        formatted = formatted.replace(
            /```(\w+)?\n([\s\S]*?)```/g,
            '<pre><code class="$1">$2</code></pre>'
        );
        
        return formatted;
    },

    showThinking() {
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return null;
        
        const thinkingDiv = document.createElement('div');
        thinkingDiv.id = 'thinking-indicator';
        thinkingDiv.className = 'chat-message assistant';
        
        thinkingDiv.innerHTML = `
            <div class="chat-bubble assistant">
                <div class="thinking-indicator">
                    <div class="thinking-dot"></div>
                    <div class="thinking-dot"></div>
                    <div class="thinking-dot"></div>
                    <span>Thinking...</span>
                </div>
            </div>
        `;
        
        chatMessages.appendChild(thinkingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        return 'thinking-indicator';
    },

    removeThinking(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    },

    clearChat() {
        if (!confirm('Are you sure you want to clear the chat history?')) {
            return;
        }
        
        this.state.messages = [];
        const chatMessages = document.getElementById('chat-messages');
        if (chatMessages) {
            chatMessages.innerHTML = `
                <div class="chat-message assistant">
                    <div class="chat-bubble assistant">
                        Hello! I'm your AI assistant. Select a collection and ask me anything about its content.
                    </div>
                </div>
            `;
        }
        
        this.saveChatHistory();
    },

    saveChat() {
        const chatData = {
            messages: this.state.messages,
            collection: this.state.contextCollection,
            assistant: this.state.currentAssistant,
            timestamp: new Date().toISOString()
        };
        
        const blob = new Blob([JSON.stringify(chatData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        QdrantManager.showNotification('Chat saved successfully!', 'success');
    },

    loadChatFromFile() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            try {
                const text = await file.text();
                const chatData = JSON.parse(text);
                
                // Validate chat data
                if (!Array.isArray(chatData.messages)) {
                    throw new Error('Invalid chat file format');
                }
                
                // Load chat
                this.state.messages = chatData.messages;
                this.state.contextCollection = chatData.collection || null;
                this.state.currentAssistant = chatData.assistant || null;
                
                // Update UI
                this.renderChatHistory();
                
                // Update dropdowns
                if (chatData.collection) {
                    const collectionSelect = document.getElementById('chat-collection-select');
                    if (collectionSelect) collectionSelect.value = chatData.collection;
                }
                
                if (chatData.assistant) {
                    const assistantSelect = document.getElementById('chat-assistant-select');
                    if (assistantSelect) assistantSelect.value = chatData.assistant;
                }
                
                QdrantManager.showNotification('Chat loaded successfully!', 'success');
                
            } catch (error) {
                console.error('Failed to load chat:', error);
                QdrantManager.showNotification(`Error loading chat: ${error.message}`, 'error');
            }
        };
        
        input.click();
    },

    renderChatHistory() {
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;
        
        chatMessages.innerHTML = '';
        
        if (this.state.messages.length === 0) {
            chatMessages.innerHTML = `
                <div class="chat-message assistant">
                    <div class="chat-bubble assistant">
                        Hello! I'm your AI assistant. Select a collection and ask me anything about its content.
                    </div>
                </div>
            `;
            return;
        }
        
        this.state.messages.forEach(message => this.renderMessage(message));
    },

    // Local storage methods
    saveChatHistory() {
        try {
            localStorage.setItem('qdrant_chat_history', JSON.stringify({
                messages: this.state.messages.slice(-50), // Keep last 50 messages
                collection: this.state.contextCollection,
                assistant: this.state.currentAssistant,
                timestamp: new Date().toISOString()
            }));
        } catch (error) {
            console.warn('Failed to save chat history:', error);
        }
    },

    loadChatHistory() {
        try {
            const saved = localStorage.getItem('qdrant_chat_history');
            if (saved) {
                const chatData = JSON.parse(saved);
                this.state.messages = chatData.messages || [];
                this.state.contextCollection = chatData.collection || null;
                this.state.currentAssistant = chatData.assistant || null;
                
                // Update UI
                this.renderChatHistory();
                
                // Update dropdowns
                if (chatData.collection) {
                    const collectionSelect = document.getElementById('chat-collection-select');
                    if (collectionSelect) collectionSelect.value = chatData.collection;
                }
                
                if (chatData.assistant) {
                    const assistantSelect = document.getElementById('chat-assistant-select');
                    if (assistantSelect) assistantSelect.value = chatData.assistant;
                }
            }
        } catch (error) {
            console.warn('Failed to load chat history:', error);
        }
    }
};

// Initialize chat when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    QdrantChat.init();
});

// Export for use in other modules
window.QdrantChat = QdrantChat;