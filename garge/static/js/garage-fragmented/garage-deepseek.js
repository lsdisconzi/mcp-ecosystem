// DeepSeek Engineer functionality
class DeepSeekEngineer {
    constructor() {
        this.conversationHistory = [];
        this.contextFiles = new Map();
        this.apiKey = '';
        this.baseURL = 'https://api.deepseek.com';
        this.storageKeys = {
            apiKey: 'deepseekApiKey',
            savedConversations: 'deepseekSavedConversations'
        };
        this.savedConversations = this.loadSavedConversations();
    }

    setApiKey(apiKey) {
        this.apiKey = apiKey;
        localStorage.setItem(this.storageKeys.apiKey, apiKey);
    }

    getApiKey() {
        return this.apiKey || localStorage.getItem(this.storageKeys.apiKey) || '';
    }

    async initialize() {
        // Load saved API key
        const savedKey = this.getApiKey();
        if (savedKey) {
            document.getElementById('deepseek-api-key').value = savedKey;
            this.setApiKey(savedKey);
        }

        this.setupEventListeners();
        this.setupPersistenceControls();
        this.updateSavedConversationOptions();
    }

    setupEventListeners() {
        // API Key input
        document.getElementById('deepseek-api-key').addEventListener('change', (e) => {
            this.setApiKey(e.target.value);
        });

        // Add files button
        document.getElementById('add-files-btn').addEventListener('click', () => {
            document.getElementById('file-input').click();
        });

        // File input handler
        document.getElementById('file-input').addEventListener('change', (e) => {
            this.handleFileSelection(e.target.files);
        });

        // Clear context
        document.getElementById('clear-context-btn').addEventListener('click', () => {
            this.clearContext();
        });

        // Send to engineer
        document.getElementById('send-to-engineer').addEventListener('click', () => {
            this.sendToEngineer();
        });

        // Enter key in prompt
        document.getElementById('engineer-prompt').addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendToEngineer();
            }
        });
    }

    async handleFileSelection(files) {
        for (let file of files) {
            await this.readFileContent(file);
        }
        this.updateFilesDisplay();
    }

    async readFileContent(file) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                this.contextFiles.set(file.webkitRelativePath || file.name, {
                    name: file.name,
                    path: file.webkitRelativePath || file.name,
                    content: e.target.result,
                    type: file.type,
                    size: file.size
                });
                resolve();
            };
            reader.readAsText(file);
        });
    }

    updateFilesDisplay() {
        const filesList = document.getElementById('files-list');
        const contextFiles = document.getElementById('context-files');
        
        if (!filesList || !contextFiles) return; // Guard clause for missing elements

        if (this.contextFiles.size === 0) {
            contextFiles.style.display = 'none';
            filesList.innerHTML = '';
            return;
        }

        contextFiles.style.display = 'block';
        
        // Add summary header
        this.addContextSummary();
        
        // Group files by folder structure
        const fileTree = this.buildFileTree();
        
        // Create a more organized file display
        filesList.innerHTML = this.renderFileTree(fileTree);
        
        // Add event listeners for remove buttons and folder toggles
        this.attachFileEventListeners();
    }

    addContextSummary() {
        const contextFiles = document.getElementById('context-files');
        
        // Remove existing summary if any
        const existingSummary = contextFiles.querySelector('.context-summary');
        if (existingSummary) {
            existingSummary.remove();
        }
        
        const totalFiles = this.contextFiles.size;
        const totalSize = Array.from(this.contextFiles.values()).reduce((sum, file) => sum + file.size, 0);
        
        const summaryHtml = `
            <div class="context-summary" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 12px; background: var(--card-bg); border-radius: 8px; border: 1px solid var(--gray-200);">
                <div>
                    <div style="font-weight: 600; color: var(--primary);">Context Files</div>
                    <div style="font-size: 14px; color: var(--gray-400);">${totalFiles} file${totalFiles !== 1 ? 's' : ''} • ${this.formatFileSize(totalSize)}</div>
                </div>
                <button class="btn btn-secondary" id="clear-all-files-btn" style="padding: 6px 12px;">
                    Clear All
                </button>
            </div>
        `;
        
        contextFiles.insertAdjacentHTML('afterbegin', summaryHtml);

        // Add event listener for clear all button
        document.getElementById('clear-all-files-btn').addEventListener('click', () => {
            this.clearContext();
        });
    }

    buildFileTree() {
        const tree = { 
            name: 'root', 
            type: 'folder', 
            children: [],
            path: ''
        };

        this.contextFiles.forEach((file, path) => {
            const parts = path.split('/');
            let currentLevel = tree;
            
            // Build folder structure
            for (let i = 0; i < parts.length - 1; i++) {
                const folderName = parts[i];
                let folder = currentLevel.children.find(child => 
                    child.name === folderName && child.type === 'folder'
                );
                
                if (!folder) {
                    folder = {
                        name: folderName,
                        type: 'folder',
                        children: [],
                        path: parts.slice(0, i + 1).join('/'),
                        expanded: true // Default to expanded
                    };
                    currentLevel.children.push(folder);
                }
                currentLevel = folder;
            }
            
            // Add file to the appropriate folder
            const fileName = parts[parts.length - 1];
            const fileNode = {
                name: fileName,
                type: 'file',
                fileData: file,
                path: path,
                size: this.formatFileSize(file.size),
                extension: this.getFileExtension(fileName)
            };
            currentLevel.children.push(fileNode);
        });

        // Sort folders and files
        this.sortFileTree(tree);
        return tree;
    }

    sortFileTree(node) {
        if (!node.children) return;
        
        // Sort: folders first, then files, both alphabetically
        node.children.sort((a, b) => {
            if (a.type === 'folder' && b.type !== 'folder') return -1;
            if (a.type !== 'folder' && b.type === 'folder') return 1;
            return a.name.localeCompare(b.name);
        });
        
        // Recursively sort children
        node.children.forEach(child => this.sortFileTree(child));
    }

    renderFileTree(node, level = 0) {
        if (!node.children || node.children.length === 0) return '';
        
        let html = '';
        const indent = level * 20;
        
        node.children.forEach(child => {
            if (child.type === 'folder') {
                html += this.renderFolder(child, level, indent);
            } else {
                html += this.renderFile(child, indent);
            }
        });
        
        return html;
    }

    renderFolder(folder, level, indent) {
        return `
            <div class="folder-item" style="margin-left: ${indent}px;">
                <div class="folder-header" style="display: flex; align-items: center; padding: 8px 12px; border-radius: 6px; cursor: pointer; user-select: none; transition: background 0.2s;">
                    <i class="fas fa-chevron-down" style="margin-right: 8px; font-size: 12px; color: var(--gray-400);"></i>
                    <i class="fas fa-folder" style="margin-right: 8px; color: var(--warning);"></i>
                    <div style="font-weight: 600; color: var(--dark);">${folder.name}</div>
                    <div style="margin-left: 8px; font-size: 12px; color: var(--gray-400);">(${folder.children.length} ${folder.children.length === 1 ? 'item' : 'items'})</div>
                    <button class="btn btn-icon remove-folder" data-path="${folder.path}" style="margin-left: auto; padding: 4px 6px;">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="folder-contents" style="display: block;">
                    ${this.renderFileTree(folder, level + 1)}
                </div>
            </div>
        `;
    }

    renderFile(file, indent) {
        const icon = this.getFileIcon(file.extension);
        const iconColor = this.getFileIconColor(file.extension);
        
        return `
            <div class="file-item" style="margin-left: ${indent}px; display: flex; align-items: center; padding: 8px 12px; border-radius: 6px; transition: background 0.2s;">
                <i class="${icon}" style="margin-right: 8px; color: ${iconColor};"></i>
                <div style="flex: 1;">
                    <div style="font-weight: 500; color: var(--dark);">${file.name}</div>
                    <div style="font-size: 12px; color: var(--gray-400); display: flex; align-items: center; gap: 8px;">
                        <span>${file.extension.toUpperCase()}</span>
                        <span>•</span>
                        <span>${file.size}</span>
                        <span>•</span>
                        <span>${this.getShortPath(file.path)}</span>
                    </div>
                </div>
                <div style="display: flex; gap: 4px;">
                    <button class="btn btn-icon preview-file" data-path="${file.path}" style="padding: 4px 6px;">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button class="btn btn-icon remove-file" data-path="${file.path}" style="padding: 4px 6px;">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;
    }

    getFileExtension(filename) {
        const parts = filename.split('.');
        return parts.length > 1 ? parts.pop().toLowerCase() : 'file';
    }

    getFileIcon(extension) {
        const iconMap = {
            // Code files
            'js': 'fab fa-js-square',
            'ts': 'fas fa-code',
            'jsx': 'fab fa-react',
            'tsx': 'fab fa-react',
            'py': 'fab fa-python',
            'java': 'fab fa-java',
            'cpp': 'fas fa-file-code',
            'c': 'fas fa-file-code',
            'h': 'fas fa-file-code',
            'cs': 'fas fa-file-code',
            'php': 'fab fa-php',
            'rb': 'far fa-gem',
            'go': 'fas fa-code',
            'rs': 'fas fa-code',
            'swift': 'fas fa-code',
            
            // Web files
            'html': 'fab fa-html5',
            'css': 'fab fa-css3-alt',
            'scss': 'fab fa-sass',
            'less': 'fab fa-less',
            'json': 'fas fa-brackets-curly',
            'xml': 'fas fa-code',
            
            // Data files
            'sql': 'fas fa-database',
            'csv': 'fas fa-file-csv',
            'yml': 'fas fa-file-code',
            'yaml': 'fas fa-file-code',
            
            // Document files
            'md': 'fas fa-markdown',
            'txt': 'fas fa-file-alt',
            'pdf': 'fas fa-file-pdf',
            'doc': 'fas fa-file-word',
            'docx': 'fas fa-file-word',
            
            // Config files
            'config': 'fas fa-cog',
            'ini': 'fas fa-cog',
            'toml': 'fas fa-cog',
            
            // Default
            'file': 'fas fa-file'
        };
        
        return iconMap[extension] || 'fas fa-file';
    }

    getFileIconColor(extension) {
        const colorMap = {
            'js': '#f7df1e',
            'ts': '#3178c6',
            'jsx': '#61dafb',
            'tsx': '#61dafb',
            'py': '#3776ab',
            'java': '#ed8b00',
            'html': '#e34f26',
            'css': '#1572b6',
            'scss': '#c69',
            'json': '#f5de19',
            'md': '#083fa1',
            'pdf': '#f40f02',
            'default': 'var(--primary)'
        };
        
        return colorMap[extension] || colorMap.default;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    getShortPath(fullPath) {
        const parts = fullPath.split('/');
        if (parts.length <= 2) return fullPath;
        return '.../' + parts.slice(-2).join('/');
    }

    attachFileEventListeners() {
        // Folder toggle
        document.querySelectorAll('.folder-header').forEach(header => {
            header.addEventListener('click', (e) => {
                if (e.target.closest('.remove-folder')) return;
                
                const folderItem = header.closest('.folder-item');
                const folderContents = folderItem.querySelector('.folder-contents');
                const chevron = header.querySelector('.fa-chevron-down, .fa-chevron-right');
                
                const isExpanded = folderContents.style.display !== 'none';
                folderContents.style.display = isExpanded ? 'none' : 'block';
                chevron.className = isExpanded ? 'fas fa-chevron-right' : 'fas fa-chevron-down';
            });
        });

        // Remove file
        document.querySelectorAll('.remove-file').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const path = e.currentTarget.dataset.path;
                this.contextFiles.delete(path);
                this.updateFilesDisplay();
                showNotification(`Removed file: ${path.split('/').pop()}`, 'success');
            });
        });

        // Remove folder
        document.querySelectorAll('.remove-folder').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const folderPath = e.currentTarget.dataset.path;
                
                // Remove all files in this folder and subfolders
                const filesToRemove = [];
                this.contextFiles.forEach((file, path) => {
                    if (path.startsWith(folderPath + '/') || path === folderPath) {
                        filesToRemove.push(path);
                    }
                });
                
                filesToRemove.forEach(path => this.contextFiles.delete(path));
                this.updateFilesDisplay();
                showNotification(`Removed folder: ${folderPath.split('/').pop()} (${filesToRemove.length} files)`, 'success');
            });
        });

        // Preview file
        document.querySelectorAll('.preview-file').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const path = e.currentTarget.dataset.path;
                const file = this.contextFiles.get(path);
                if (file) {
                    this.showFilePreview(file);
                }
            });
        });
    }

    showFilePreview(file) {
        const modal = createModal(
            `File Preview: ${file.name}`,
            `
            <div style="margin-bottom: 15px;">
                <div><strong>Path:</strong> ${file.path}</div>
                <div><strong>Size:</strong> ${this.formatFileSize(file.size)}</div>
                <div><strong>Type:</strong> ${file.type}</div>
            </div>
            <div style="background: var(--gray-100); padding: 15px; border-radius: 6px; max-height: 400px; overflow-y: auto;">
                <pre>${this.escapeHtml(file.content)}</pre>
            </div>
            `,
            [
                {
                    text: 'Close',
                    class: 'btn-secondary',
                    onclick: closeModal
                }
            ],
            '800px'
        );
    }

    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    clearContext() {
        this.contextFiles.clear();
        this.conversationHistory = [];
        this.updateFilesDisplay();
        this.updateConversationDisplay();
        showNotification('Context cleared', 'success');
    }

    async sendToEngineer() {
        const prompt = document.getElementById('engineer-prompt').value.trim();
        if (!prompt) {
            showNotification('Please enter a prompt', 'error');
            return;
        }

        const sendBtn = document.getElementById('send-to-engineer');
        const originalText = sendBtn.innerHTML;
        sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
        sendBtn.disabled = true;

        try {
            await this.processWithDeepSeek(prompt);
        } catch (error) {
            console.error('DeepSeek Engineer error:', error);
            showNotification(`Error: ${error.message}`, 'error');
        } finally {
            sendBtn.innerHTML = originalText;
            sendBtn.disabled = false;
            document.getElementById('engineer-prompt').value = '';
        }
    }

    async processWithDeepSeek(userPrompt) {
        // Prepare messages
        const messages = this.buildMessages(userPrompt);

        // Show user message
        this.addMessageToConversation('user', userPrompt);

        // Call DeepSeek API
        const response = await fetch('/v1/deepseek-engineer/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                messages: messages,
                api_key: this.getApiKey(),
                context_files: Array.from(this.contextFiles.entries()).map(([path, file]) => ({
                    path: file.path,
                    content: file.content
                }))
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API request failed');
        }

        const data = await response.json();
        
        // Show assistant response
        this.addMessageToConversation('assistant', data.response, data.reasoning);

        // Handle file operations from response
        if (data.file_operations) {
            await this.handleFileOperations(data.file_operations);
        }
    }

    buildMessages(userPrompt) {
        const systemPrompt = `You are an elite software engineer called DeepSeek Engineer with decades of experience across all programming domains.
Your expertise spans system design, algorithms, testing, and best practices.
You provide thoughtful, well-structured solutions while explaining your reasoning.

Core capabilities:
1. Code Analysis & Discussion
   - Analyze code with expert-level insight
   - Explain complex concepts clearly
   - Suggest optimizations and best practices
   - Debug issues with precision

2. File Operations (via function calls):
   - read_file: Read a single file's content
   - read_multiple_files: Read multiple files at once
   - create_file: Create or overwrite a single file
   - create_multiple_files: Create multiple files at once
   - edit_file: Make precise edits to existing files using snippet replacement

Guidelines:
1. Provide natural, conversational responses explaining your reasoning
2. Use function calls when you need to read or modify files
3. For file operations:
   - Always read files first before editing them to understand the context
   - Use precise snippet matching for edits
   - Explain what changes you're making and why
   - Consider the impact of changes on the overall codebase
4. Follow language-specific best practices
5. Suggest tests or validation steps when appropriate
6. Be thorough in your analysis and recommendations

IMPORTANT: In your thinking process, if you realize that something requires a tool call, cut your thinking short and proceed directly to the tool call. Don't overthink - act efficiently when file operations are needed.

Remember: You're a senior engineer - be thoughtful, precise, and explain your reasoning clearly.`;

        const messages = [
            { role: 'system', content: systemPrompt }
        ];

        // Add context files as system messages
        this.contextFiles.forEach((file) => {
            messages.push({
                role: 'system',
                content: `Content of file '${file.path}':\n\n${file.content}`
            });
        });

        // Add conversation history
        // Filter out internal fields like timestamp and reasoning that might cause API validation errors
        const sanitizedHistory = this.conversationHistory.map(msg => ({
            role: msg.role,
            content: msg.content
        }));
        messages.push(...sanitizedHistory);
        
        messages.push({ role: 'user', content: userPrompt });

        return messages;
    }

    addMessageToConversation(role, content, reasoning = null) {
        const timestamp = new Date().toISOString();
        const message = { role, content, timestamp };
        if (reasoning) {
            message.reasoning = reasoning;
        }
        
        this.conversationHistory.push(message);
        this.updateConversationDisplay();
    }

    updateConversationDisplay() {
        const conversationDiv = document.getElementById('engineer-conversation');
        
        if (this.conversationHistory.length === 0) {
            conversationDiv.innerHTML = `
                <div class="conversation-placeholder" style="text-align: center; color: var(--gray-400); padding: 40px;">
                    <i class="fas fa-robot" style="font-size: 48px; margin-bottom: 16px;"></i>
                    <p>Start a conversation with DeepSeek Engineer to analyze code, create files, or refactor code.</p>
                </div>
            `;
            return;
        }

        conversationDiv.innerHTML = '';
        
        this.conversationHistory.forEach((msg) => {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${msg.role}`;
            messageDiv.style.cssText = `
                margin-bottom: 16px;
                padding: 12px 16px;
                border-radius: 12px;
                max-width: 80%;
                ${msg.role === 'user' ? 
                    'background: var(--primary); color: white; margin-left: auto; text-align: right;' : 
                    'background: var(--card-bg); border: 1px solid var(--gray-200);'
                }
            `;

            let content = '';
            
            if (msg.reasoning) {
                content += `<div class="reasoning" style="
                    background: rgba(59, 130, 246, 0.1);
                    border-left: 3px solid var(--primary);
                    padding: 8px 12px;
                    margin-bottom: 8px;
                    border-radius: 4px;
                    font-style: italic;
                "><strong>💭 Reasoning:</strong> ${msg.reasoning}</div>`;
            }

            content += `<div class="content">${this.formatContent(msg.content)}</div>`;
            
            const timestamp = (() => {
                if (!msg.timestamp) return null;
                if (typeof msg.timestamp === 'string') return new Date(msg.timestamp);
                if (msg.timestamp instanceof Date) return msg.timestamp;
                return new Date(msg.timestamp);
            })();
            const timestampLabel = timestamp && !isNaN(timestamp.getTime()) ? timestamp.toLocaleTimeString() : '--:--';
            content += `<div class="timestamp" style="
                font-size: 11px;
                color: ${msg.role === 'user' ? 'rgba(255,255,255,0.7)' : 'var(--gray-400)'};
                margin-top: 4px;
            ">${timestampLabel}</div>`;

            messageDiv.innerHTML = content;
            conversationDiv.appendChild(messageDiv);
        });

        conversationDiv.scrollTop = conversationDiv.scrollHeight;
    }

    formatContent(content) {
        // Simple formatting for code blocks
        return content.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
                     .replace(/`([^`]+)`/g, '<code>$1</code>')
                     .replace(/\n/g, '<br>');
    }

    setupPersistenceControls() {
        const conversationDiv = document.getElementById('engineer-conversation');
        if (!conversationDiv || !conversationDiv.parentNode) return;

        if (!document.getElementById('deepseek-conversation-toolbar')) {
            const toolbar = document.createElement('div');
            toolbar.id = 'deepseek-conversation-toolbar';
            toolbar.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px;';
            toolbar.innerHTML = `
                <button type="button" class="btn btn-secondary" id="save-conversation-btn">
                    <i class="fas fa-save" style="margin-right:6px;"></i>Save
                </button>
                <button type="button" class="btn btn-secondary" id="export-conversation-btn">
                    <i class="fas fa-file-export" style="margin-right:6px;"></i>Export
                </button>
                <div style="display:flex; gap:6px; align-items:center;">
                    <select id="saved-conversations-select" style="min-width:200px; padding:6px 10px; border-radius:6px; border:1px solid var(--gray-200); background:var(--card-bg); color:var(--dark);">
                        <option value="">Saved conversations</option>
                    </select>
                    <button type="button" class="btn btn-secondary" id="load-conversation-btn">
                        <i class="fas fa-upload" style="margin-right:6px;"></i>Load
                    </button>
                </div>
            `;
            conversationDiv.parentNode.insertBefore(toolbar, conversationDiv);
        }

        this.attachPersistenceEventListeners();
    }

    attachPersistenceEventListeners() {
        const saveBtn = document.getElementById('save-conversation-btn');
        if (saveBtn && !saveBtn.dataset.bound) {
            saveBtn.addEventListener('click', () => this.saveConversation());
            saveBtn.dataset.bound = 'true';
        }

        const exportBtn = document.getElementById('export-conversation-btn');
        if (exportBtn && !exportBtn.dataset.bound) {
            exportBtn.addEventListener('click', () => this.exportConversation());
            exportBtn.dataset.bound = 'true';
        }

        const loadBtn = document.getElementById('load-conversation-btn');
        if (loadBtn && !loadBtn.dataset.bound) {
            loadBtn.addEventListener('click', () => {
                const select = document.getElementById('saved-conversations-select');
                if (!select || !select.value) {
                    showNotification('Select a saved conversation to load', 'info');
                    return;
                }
                this.loadConversation(select.value);
            });
            loadBtn.dataset.bound = 'true';
        }
    }

    saveConversation() {
        if (this.conversationHistory.length === 0) {
            showNotification('No responses to save yet', 'info');
            return;
        }

        const defaultName = `Session ${new Date().toLocaleString()}`;
        const name = prompt('Name this conversation', defaultName);
        if (!name) {
            showNotification('Save cancelled', 'info');
            return;
        }

        if (this.savedConversations[name] && !confirm(`Overwrite saved conversation "${name}"?`)) {
            return;
        }

        this.savedConversations[name] = this.getSerializableConversation();
        this.persistSavedConversations();
        this.updateSavedConversationOptions(name);
        showNotification(`Conversation "${name}" saved`, 'success');
    }

    loadConversation(name) {
        const stored = this.savedConversations[name];
        if (!stored) {
            showNotification('Saved conversation not found', 'error');
            return;
        }

        this.conversationHistory = stored.map(msg => ({
            role: msg.role,
            content: msg.content,
            reasoning: msg.reasoning,
            timestamp: msg.timestamp || new Date().toISOString()
        }));
        this.updateConversationDisplay();
        showNotification(`Loaded conversation "${name}"`, 'success');
    }

    exportConversation() {
        if (this.conversationHistory.length === 0) {
            showNotification('No responses to export yet', 'info');
            return;
        }

        const data = JSON.stringify(this.getSerializableConversation(), null, 2);
        const blob = new Blob([data], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = this.getConversationFilename();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showNotification('Conversation exported', 'success');
    }

    getConversationFilename() {
        const timestamp = new Date().toISOString().replace(/[:]/g, '-');
        return `deepseek-conversation-${timestamp}.json`;
    }

    getSerializableConversation() {
        return this.conversationHistory.map(msg => ({
            role: msg.role,
            content: msg.content,
            reasoning: msg.reasoning || null,
            timestamp: typeof msg.timestamp === 'string'
                ? msg.timestamp
                : (msg.timestamp instanceof Date ? msg.timestamp.toISOString() : new Date(msg.timestamp || Date.now()).toISOString())
        }));
    }

    loadSavedConversations() {
        try {
            const raw = localStorage.getItem(this.storageKeys.savedConversations);
            if (!raw) return {};
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (error) {
            console.warn('Unable to parse saved DeepSeek conversations', error);
            return {};
        }
    }

    persistSavedConversations() {
        try {
            localStorage.setItem(this.storageKeys.savedConversations, JSON.stringify(this.savedConversations));
        } catch (error) {
            console.error('Failed to persist DeepSeek conversations', error);
            showNotification('Unable to persist conversation locally', 'error');
        }
    }

    updateSavedConversationOptions(selectedName = '') {
        const select = document.getElementById('saved-conversations-select');
        if (!select) return;

        const options = ['<option value="">Saved conversations</option>'];
        Object.keys(this.savedConversations)
            .sort((a, b) => a.localeCompare(b))
            .forEach(name => {
                const isSelected = selectedName && selectedName === name ? 'selected' : '';
                options.push(`<option value="${name}" ${isSelected}>${name}</option>`);
            });

        select.innerHTML = options.join('');
        if (selectedName) {
            select.value = selectedName;
        }
    }

    async handleFileOperations(operations) {
        for (const op of operations) {
            switch (op.type) {
                case 'create_file':
                    await this.createFile(op.path, op.content);
                    break;
                case 'edit_file':
                    await this.editFile(op.path, op.original_snippet, op.new_snippet);
                    break;
            }
        }
    }

    async createFile(path, content) {
        // Create a blob and download link
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = path.split('/').pop() || 'file.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showNotification(`File created: ${path}`, 'success');
    }

    async editFile(path, originalSnippet, newSnippet) {
        // This would need more sophisticated implementation for actual file editing
        showNotification(`Edit suggested for: ${path}`, 'info');
        console.log(`Edit ${path}:`, { originalSnippet, newSnippet });
    }
}

// Initialize DeepSeek Engineer when the section is loaded
let deepSeekEngineer = null;

document.addEventListener('DOMContentLoaded', function() {
    // Initialize when the deepseek engineer section is shown
    const engineerTab = document.querySelector('[data-section="deepseek-engineer-section"]');
    if (engineerTab) {
        engineerTab.addEventListener('click', function() {
            if (!deepSeekEngineer) {
                deepSeekEngineer = new DeepSeekEngineer();
                deepSeekEngineer.initialize();
            }
        });
    }
});