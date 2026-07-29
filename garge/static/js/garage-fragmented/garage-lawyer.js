// Garage Lawyer - Specialized Legal Assistant for Consumer Protection Cases

class GarageLawyer {
    constructor() {
        this.conversationHistory = [];
        this.caseFiles = new Map();
        this.evidenceFiles = new Map();
        this.apiKey = '';
        this.baseURL = 'https://api.deepseek.com';
        this.storageKeys = {
            apiKey: 'garageLawyerApiKey',
            savedCases: 'garageLawyerSavedCases',
            caseNotes: 'garageLawyerCaseNotes'
        };
        this.savedCases = this.loadSavedCases();
        this.currentCaseId = null;
        
        // Legal knowledge base - Brazilian legislation
        this.legislationBase = this.initializeLegislationBase();
    }

    initializeLegislationBase() {
        return {
            cdc: {
                name: 'Código de Defesa do Consumidor (Lei 8.078/1990)',
                articles: {
                    'art6_iii': {
                        text: 'a informação adequada e clara sobre os diferentes produtos e serviços, com especificação correta de quantidade, características, composição, qualidade, tributos incidentes e preço, bem como sobre os riscos que apresentem',
                        application: 'Direito à informação clara e adequada'
                    },
                    'art6_vi': {
                        text: 'a efetiva prevenção e reparação de danos patrimoniais e morais, individuais, coletivos e difusos',
                        application: 'Reparação de danos morais e patrimoniais'
                    },
                    'art6_viii': {
                        text: 'a facilitação da defesa de seus direitos, inclusive com a inversão do ônus da prova, a seu favor, no processo civil, quando, a critério do juiz, for verossímil a alegação ou quando for ele hipossuficiente',
                        application: 'Inversão do ônus da prova'
                    },
                    'art14': {
                        text: 'O fornecedor de serviços responde, independentemente da existência de culpa, pela reparação dos danos causados aos consumidores por defeitos relativos à prestação dos serviços',
                        application: 'Responsabilidade objetiva do fornecedor'
                    },
                    'art39_ii': {
                        text: 'recusar atendimento às demandas dos consumidores, na exata medida de suas disponibilidades de estoque',
                        application: 'Prática abusiva - recusa de atendimento'
                    },
                    'art39_iv': {
                        text: 'prevalecer-se da fraqueza ou ignorância do consumidor, tendo em vista sua idade, saúde, conhecimento ou condição social',
                        application: 'Prática abusiva - exploração de vulnerabilidade'
                    },
                    'art42': {
                        text: 'o consumidor inadimplente não será exposto a ridículo, nem será submetido a qualquer tipo de constrangimento ou ameaça',
                        application: 'Vedação ao constrangimento'
                    }
                }
            },
            anac: {
                name: 'Resolução ANAC Nº 400/2016',
                articles: {
                    'art42': {
                        text: 'A recusa de embarque ou remoção de passageiro deve ser fundamentada em motivo de segurança da aeronave ou de seus ocupantes',
                        application: 'Fundamentação para remoção de passageiro'
                    },
                    'art43': {
                        text: 'O transportador deve documentar o incidente e fornecer ao passageiro justificativa por escrito quando solicitado',
                        application: 'Obrigação de documentação'
                    },
                    'art44': {
                        text: 'O passageiro tem direito a ser informado sobre os motivos da recusa de embarque ou remoção',
                        application: 'Direito à informação'
                    }
                }
            },
            cf88: {
                name: 'Constituição Federal de 1988',
                articles: {
                    'art5_iii': {
                        text: 'ninguém será submetido a tortura nem a tratamento desumano ou degradante',
                        application: 'Vedação a tratamento degradante'
                    },
                    'art5_x': {
                        text: 'são invioláveis a intimidade, a vida privada, a honra e a imagem das pessoas, assegurado o direito a indenização pelo dano material ou moral decorrente de sua violação',
                        application: 'Proteção à honra e imagem'
                    },
                    'art5_lv': {
                        text: 'aos litigantes, em processo judicial ou administrativo, e aos acusados em geral são assegurados o contraditório e ampla defesa',
                        application: 'Direito ao contraditório e ampla defesa'
                    }
                }
            },
            cc2002: {
                name: 'Código Civil (Lei 10.406/2002)',
                articles: {
                    'art186': {
                        text: 'Aquele que, por ação ou omissão voluntária, negligência ou imprudência, violar direito e causar dano a outrem, ainda que exclusivamente moral, comete ato ilícito',
                        application: 'Definição de ato ilícito'
                    },
                    'art187': {
                        text: 'Também comete ato ilícito o titular de um direito que, ao exercê-lo, excede manifestamente os limites impostos pelo seu fim econômico ou social, pela boa-fé ou pelos bons costumes',
                        application: 'Abuso de direito'
                    },
                    'art927': {
                        text: 'Aquele que, por ato ilícito (arts. 186 e 187), causar dano a outrem, fica obrigado a repará-lo',
                        application: 'Obrigação de indenizar'
                    },
                    'art932_iii': {
                        text: 'o empregador ou comitente, por seus empregados, serviçais e prepostos, no exercício do trabalho que lhes competir, ou em razão dele',
                        application: 'Responsabilidade do empregador'
                    },
                    'art933': {
                        text: 'As pessoas indicadas nos incisos I a V do artigo antecedente, ainda que não haja culpa de sua parte, responderão pelos atos praticados pelos terceiros ali referidos',
                        application: 'Responsabilidade objetiva por ato de terceiro'
                    }
                }
            },
            cba: {
                name: 'Código Brasileiro de Aeronáutica (Lei 7.565/1986)',
                articles: {
                    'art13': {
                        text: 'O comandante da aeronave tem autoridade para tomar as medidas necessárias à segurança do voo e das pessoas a bordo',
                        application: 'Autoridade do comandante'
                    }
                }
            }
        };
    }

    setApiKey(apiKey) {
        this.apiKey = apiKey;
        localStorage.setItem(this.storageKeys.apiKey, apiKey);
    }

    getApiKey() {
        return this.apiKey || localStorage.getItem(this.storageKeys.apiKey) || '';
    }

    async initialize() {
        const savedKey = this.getApiKey();
        if (savedKey) {
            const apiKeyInput = document.getElementById('lawyer-api-key');
            if (apiKeyInput) {
                apiKeyInput.value = savedKey;
            }
            this.setApiKey(savedKey);
        }

        this.setupEventListeners();
        this.setupPersistenceControls();
        this.updateSavedCaseOptions();
        this.populateLegislationPanel();
    }

    setupEventListeners() {
        // API Key input
        const apiKeyInput = document.getElementById('lawyer-api-key');
        if (apiKeyInput) {
            apiKeyInput.addEventListener('change', (e) => {
                this.setApiKey(e.target.value);
            });
        }

        // Add evidence files button
        const addEvidenceBtn = document.getElementById('add-evidence-btn');
        if (addEvidenceBtn) {
            addEvidenceBtn.addEventListener('click', () => {
                document.getElementById('evidence-file-input').click();
            });
        }

        // Evidence file input handler
        const evidenceInput = document.getElementById('evidence-file-input');
        if (evidenceInput) {
            evidenceInput.addEventListener('change', (e) => {
                this.handleEvidenceSelection(e.target.files);
            });
        }

        // Clear evidence
        const clearEvidenceBtn = document.getElementById('clear-evidence-btn');
        if (clearEvidenceBtn) {
            clearEvidenceBtn.addEventListener('click', () => {
                this.clearEvidence();
            });
        }

        // Send consultation
        const sendConsultationBtn = document.getElementById('send-consultation');
        if (sendConsultationBtn) {
            sendConsultationBtn.addEventListener('click', () => {
                this.sendConsultation();
            });
        }

        // Enter key in prompt
        const consultationInput = document.getElementById('lawyer-prompt');
        if (consultationInput) {
            consultationInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendConsultation();
                }
            });
        }

        // Quick action buttons
        this.setupQuickActions();

        // Analysis type selector
        const analysisType = document.getElementById('analysis-type');
        if (analysisType) {
            analysisType.addEventListener('change', (e) => {
                this.updateAnalysisContext(e.target.value);
            });
        }
    }

    setupQuickActions() {
        const quickActions = {
            'quick-analyze-case': 'Analise o caso apresentado e identifique os fundamentos legais aplicáveis, indicando os artigos de lei relevantes e a jurisprudência pertinente.',
            'quick-draft-petition': 'Elabore um esboço de petição inicial com base nos fatos apresentados, incluindo qualificação das partes, fatos, fundamentos jurídicos e pedidos.',
            'quick-calculate-damages': 'Calcule os danos morais e materiais aplicáveis ao caso, considerando a jurisprudência atual e os parâmetros utilizados pelos tribunais.',
            'quick-find-precedents': 'Busque jurisprudência relevante para o caso, identificando decisões do STJ, TJSP e outros tribunais que fundamentem a tese.',
            'quick-identify-violations': 'Identifique todas as violações legais cometidas pela parte ré, classificando-as por gravidade e impacto no caso.'
        };

        Object.entries(quickActions).forEach(([id, prompt]) => {
            const btn = document.getElementById(id);
            if (btn) {
                btn.addEventListener('click', () => {
                    const promptInput = document.getElementById('lawyer-prompt');
                    if (promptInput) {
                        promptInput.value = prompt;
                        this.sendConsultation();
                    }
                });
            }
        });
    }

    populateLegislationPanel() {
        const container = document.getElementById('legislation-reference');
        if (!container) return;

        let html = '';
        Object.entries(this.legislationBase).forEach(([key, law]) => {
            html += `
                <div class="law-section" data-law="${key}">
                    <div class="law-header" onclick="garageLawyer.toggleLawSection('${key}')">
                        <i class="fas fa-chevron-right law-chevron"></i>
                        <span class="law-title">${law.name}</span>
                    </div>
                    <div class="law-articles" style="display: none;">
                        ${Object.entries(law.articles).map(([artKey, article]) => `
                            <div class="article-item" onclick="garageLawyer.insertArticleReference('${key}', '${artKey}')">
                                <div class="article-ref">${this.formatArticleKey(artKey)}</div>
                                <div class="article-application">${article.application}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;
    }

    formatArticleKey(key) {
        return key.replace('art', 'Art. ')
                  .replace('_', ', ')
                  .replace(/([ivxlcdm]+)$/i, (m) => m.toUpperCase());
    }

    toggleLawSection(lawKey) {
        const section = document.querySelector(`.law-section[data-law="${lawKey}"]`);
        if (!section) return;

        const articles = section.querySelector('.law-articles');
        const chevron = section.querySelector('.law-chevron');
        
        if (articles.style.display === 'none') {
            articles.style.display = 'block';
            chevron.classList.remove('fa-chevron-right');
            chevron.classList.add('fa-chevron-down');
        } else {
            articles.style.display = 'none';
            chevron.classList.remove('fa-chevron-down');
            chevron.classList.add('fa-chevron-right');
        }
    }

    insertArticleReference(lawKey, articleKey) {
        const law = this.legislationBase[lawKey];
        const article = law.articles[articleKey];
        
        const reference = `\n\n**Referência Legal:**\n${law.name}\n${this.formatArticleKey(articleKey)}: "${article.text}"\n*Aplicação: ${article.application}*\n\n`;
        
        const promptInput = document.getElementById('lawyer-prompt');
        if (promptInput) {
            promptInput.value += reference;
            promptInput.focus();
        }

        showNotification(`Artigo inserido: ${this.formatArticleKey(articleKey)}`, 'success');
    }

    async handleEvidenceSelection(files) {
        for (let file of files) {
            await this.readEvidenceFile(file);
        }
        this.updateEvidenceDisplay();
    }

    async readEvidenceFile(file) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const evidenceId = `evidence_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                this.evidenceFiles.set(evidenceId, {
                    id: evidenceId,
                    name: file.name,
                    content: e.target.result,
                    type: file.type,
                    size: file.size,
                    uploadedAt: new Date().toISOString(),
                    category: this.categorizeEvidence(file.name, file.type)
                });
                resolve();
            };
            
            if (file.type.startsWith('image/')) {
                reader.readAsDataURL(file);
            } else {
                reader.readAsText(file);
            }
        });
    }

    categorizeEvidence(filename, type) {
        const name = filename.toLowerCase();
        
        if (name.includes('audio') || type.startsWith('audio/')) return 'audio';
        if (name.includes('video') || type.startsWith('video/')) return 'video';
        if (name.includes('foto') || name.includes('photo') || type.startsWith('image/')) return 'image';
        if (name.includes('contrato') || name.includes('contract')) return 'contract';
        if (name.includes('bilhete') || name.includes('ticket') || name.includes('boarding')) return 'ticket';
        if (name.includes('email') || name.includes('mensagem')) return 'communication';
        if (name.includes('laudo') || name.includes('report')) return 'report';
        if (name.includes('nota') || name.includes('recibo') || name.includes('receipt')) return 'receipt';
        if (name.endsWith('.md') || name.endsWith('.markdown')) return 'markdown';
        if (name.endsWith('.json')) return 'data';
        if (name.endsWith('.csv')) return 'data';
        if (name.includes('legisla') || name.includes('lei') || name.includes('law')) return 'legislation';
        
        return 'document';
    }

    updateEvidenceDisplay() {
        const evidenceList = document.getElementById('evidence-files-list');
        const evidencePanel = document.getElementById('evidence-context-panel');
        
        if (!evidenceList || !evidencePanel) return;

        if (this.evidenceFiles.size === 0) {
            evidencePanel.style.display = 'none';
            evidenceList.innerHTML = '';
            return;
        }

        evidencePanel.style.display = 'block';
        
        const categoryIcons = {
            audio: 'fa-microphone',
            video: 'fa-video',
            image: 'fa-image',
            contract: 'fa-file-contract',
            ticket: 'fa-ticket-alt',
            communication: 'fa-envelope',
            report: 'fa-file-medical',
            receipt: 'fa-receipt',
            document: 'fa-file-alt',
            markdown: 'fa-file-code',
            data: 'fa-database',
            legislation: 'fa-gavel'
        };

        const categoryColors = {
            audio: '#e74c3c',
            video: '#9b59b6',
            image: '#3498db',
            contract: '#2ecc71',
            ticket: '#f39c12',
            communication: '#1abc9c',
            report: '#e67e22',
            receipt: '#95a5a6',
            document: '#34495e',
            markdown: '#6c5ce7',
            data: '#00b894',
            legislation: '#d63031'
        };

        let html = `
            <div class="evidence-summary" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 12px; background: var(--card-bg); border-radius: 8px; border: 1px solid var(--gray-200);">
                <div>
                    <div style="font-weight: 600; color: var(--primary);">📁 Evidências do Caso</div>
                    <div style="font-size: 14px; color: var(--gray-400);">${this.evidenceFiles.size} arquivo${this.evidenceFiles.size !== 1 ? 's' : ''}</div>
                </div>
                <button class="btn btn-secondary" id="clear-all-evidence-btn" style="padding: 6px 12px;">
                    Limpar Tudo
                </button>
            </div>
        `;

        this.evidenceFiles.forEach((evidence, id) => {
            const icon = categoryIcons[evidence.category] || 'fa-file';
            const color = categoryColors[evidence.category] || '#34495e';
            
            html += `
                <div class="evidence-item" style="display: flex; align-items: center; padding: 10px 12px; border-radius: 8px; background: var(--gray-100); margin-bottom: 8px;">
                    <i class="fas ${icon}" style="margin-right: 12px; color: ${color}; font-size: 18px;"></i>
                    <div style="flex: 1;">
                        <div style="font-weight: 500; color: var(--dark);">${evidence.name}</div>
                        <div style="font-size: 12px; color: var(--gray-400);">
                            <span class="evidence-category" style="background: ${color}20; color: ${color}; padding: 2px 6px; border-radius: 4px; margin-right: 8px;">
                                ${evidence.category}
                            </span>
                            ${this.formatFileSize(evidence.size)}
                        </div>
                    </div>
                    <div style="display: flex; gap: 4px;">
                        <button class="btn btn-icon preview-evidence" data-id="${id}" style="padding: 4px 6px;">
                            <i class="fas fa-eye"></i>
                        </button>
                        <button class="btn btn-icon remove-evidence" data-id="${id}" style="padding: 4px 6px;">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
            `;
        });

        evidenceList.innerHTML = html;
        this.attachEvidenceEventListeners();
    }

    attachEvidenceEventListeners() {
        // Clear all evidence
        const clearAllBtn = document.getElementById('clear-all-evidence-btn');
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', () => this.clearEvidence());
        }

        // Preview evidence
        document.querySelectorAll('.preview-evidence').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.dataset.id;
                const evidence = this.evidenceFiles.get(id);
                if (evidence) {
                    this.showEvidencePreview(evidence);
                }
            });
        });

        // Remove evidence
        document.querySelectorAll('.remove-evidence').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.dataset.id;
                this.evidenceFiles.delete(id);
                this.updateEvidenceDisplay();
                showNotification('Evidência removida', 'success');
            });
        });
    }

    showEvidencePreview(evidence) {
        let contentHtml = '';
        
        if (evidence.type.startsWith('image/')) {
            contentHtml = `<img src="${evidence.content}" style="max-width: 100%; border-radius: 8px;" alt="${evidence.name}">`;
        } else {
            contentHtml = `<pre style="background: var(--gray-100); padding: 15px; border-radius: 6px; max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${this.escapeHtml(evidence.content)}</pre>`;
        }

        const modal = createModal(
            `📄 ${evidence.name}`,
            `
            <div style="margin-bottom: 15px;">
                <div><strong>Categoria:</strong> ${evidence.category}</div>
                <div><strong>Tamanho:</strong> ${this.formatFileSize(evidence.size)}</div>
                <div><strong>Upload:</strong> ${new Date(evidence.uploadedAt).toLocaleString('pt-BR')}</div>
            </div>
            ${contentHtml}
            `,
            [
                { text: 'Fechar', class: 'btn-secondary', onclick: closeModal }
            ],
            '800px'
        );
    }

    clearEvidence() {
        this.evidenceFiles.clear();
        this.updateEvidenceDisplay();
        showNotification('Evidências removidas', 'success');
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    async sendConsultation() {
        const prompt = document.getElementById('lawyer-prompt').value.trim();
        if (!prompt) {
            showNotification('Por favor, insira sua consulta jurídica', 'error');
            return;
        }

        if (false) { // Ollama: no API key required
            showNotification('Por favor, configure sua chave de API', 'error');
            return;
        }

        const sendBtn = document.getElementById('send-consultation');
        const originalText = sendBtn.innerHTML;
        sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analisando...';
        sendBtn.disabled = true;

        try {
            await this.processLegalQuery(prompt);
        } catch (error) {
            console.error('Garage Lawyer error:', error);
            showNotification(`Erro: ${error.message}`, 'error');
        } finally {
            sendBtn.innerHTML = originalText;
            sendBtn.disabled = false;
            document.getElementById('lawyer-prompt').value = '';
        }
    }

    async processLegalQuery(userPrompt) {
        const messages = this.buildLegalMessages(userPrompt);
        this.addMessageToConversation('user', userPrompt);

        // Build context files array from evidence
        const contextFiles = [];
        this.evidenceFiles.forEach((evidence) => {
            if (!evidence.type.startsWith('image/')) {
                contextFiles.push({
                    path: evidence.name,
                    content: evidence.content
                });
            }
        });

        const requestBody = {
            messages: messages,
            api_key: '',
            model: 'llama3.2:1b',
            stream: false
        };

        // Only add context_files if there are files
        if (contextFiles.length > 0) {
            requestBody.context_files = contextFiles;
        }

        console.log('Sending request to DeepSeek:', JSON.stringify(requestBody, null, 2));

        const response = await fetch('/v1/deepseek-engineer/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('API Error Response:', errorText);
            let errorMessage = 'Falha na requisição da API';
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage = errorJson.detail || errorJson.error || errorMessage;
            } catch (e) {
                errorMessage = errorText || errorMessage;
            }
            throw new Error(errorMessage);
        }

        const data = await response.json();
        this.addMessageToConversation('assistant', data.response || data.content, data.reasoning);
    }

    buildLegalMessages(userPrompt) {
        const systemPrompt = `Você é um advogado especialista brasileiro com décadas de experiência em:
- Direito do Consumidor (CDC - Lei 8.078/1990)
- Direito Aeronáutico e Regulações da ANAC
- Responsabilidade Civil (Código Civil 2002)
- Direitos Fundamentais (Constituição Federal 1988)

## BASE DE CONHECIMENTO JURÍDICO

### Código de Defesa do Consumidor (Lei 8.078/1990)
${this.formatLegislationForPrompt('cdc')}

### Resolução ANAC Nº 400/2016
${this.formatLegislationForPrompt('anac')}

### Constituição Federal de 1988
${this.formatLegislationForPrompt('cf88')}

### Código Civil (Lei 10.406/2002)
${this.formatLegislationForPrompt('cc2002')}

### Código Brasileiro de Aeronáutica (Lei 7.565/1986)
${this.formatLegislationForPrompt('cba')}

## DIRETRIZES DE ATUAÇÃO

1. **Análise de Casos:**
   - Identifique todos os dispositivos legais violados
   - Cite artigos específicos com numeração correta
   - Referencie jurisprudência relevante (STJ, TJSP, etc.)
   - Calcule danos morais com base em precedentes

2. **Elaboração de Documentos:**
   - Petições iniciais completas e bem fundamentadas
   - Recursos com jurisprudência atualizada
   - Notificações extrajudiciais eficazes
   - Reclamações para órgãos reguladores (PROCON, ANAC)

3. **Cálculo de Danos:**
   - Danos morais: R$ 5.000 a R$ 50.000 para casos de companhias aéreas
   - Considere agravantes: exposição pública, acusações falsas, vulnerabilidade
   - Danos materiais: todos os gastos documentados
   - Lucros cessantes quando aplicável

4. **Formato de Resposta:**
   - Use formatação clara com títulos e subtítulos
   - Cite artigos no formato: "Art. X, Lei Y/Ano"
   - Inclua ementas de jurisprudência quando relevante
   - Sempre indique próximos passos práticos

5. **Linguagem:**
   - Responda sempre em português brasileiro
   - Use terminologia jurídica adequada
   - Explique termos técnicos quando necessário
   - Seja preciso e fundamentado

IMPORTANTE: Você está atuando como advogado consultor. Todas as orientações devem ser tecnicamente corretas e aplicáveis ao ordenamento jurídico brasileiro.`;

        const messages = [
            { role: 'system', content: systemPrompt }
        ];

        // Add evidence files as context
        this.evidenceFiles.forEach((evidence) => {
            if (!evidence.type.startsWith('image/')) {
                messages.push({
                    role: 'system',
                    content: `Evidência do caso - ${evidence.category.toUpperCase()} - '${evidence.name}':\n\n${evidence.content}`
                });
            }
        });

        // Add conversation history
        const sanitizedHistory = this.conversationHistory.map(msg => ({
            role: msg.role,
            content: msg.content
        }));
        messages.push(...sanitizedHistory);
        
        messages.push({ role: 'user', content: userPrompt });

        return messages;
    }

    formatLegislationForPrompt(lawKey) {
        const law = this.legislationBase[lawKey];
        if (!law) return '';

        let text = '';
        Object.entries(law.articles).forEach(([artKey, article]) => {
            text += `\n**${this.formatArticleKey(artKey)}:** "${article.text}"\n`;
            text += `*Aplicação: ${article.application}*\n`;
        });
        return text;
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
        const conversationDiv = document.getElementById('lawyer-conversation');
        
        if (!conversationDiv) return;

        if (this.conversationHistory.length === 0) {
            conversationDiv.innerHTML = `
                <div class="conversation-placeholder" style="text-align: center; color: var(--gray-400); padding: 40px;">
                    <i class="fas fa-balance-scale" style="font-size: 48px; margin-bottom: 16px;"></i>
                    <p>Inicie uma consulta jurídica descrevendo seu caso ou utilizando os botões de ação rápida.</p>
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
                padding: 16px;
                border-radius: 12px;
                max-width: 90%;
                ${msg.role === 'user' ? 
                    'background: var(--primary); color: white; margin-left: auto;' : 
                    'background: var(--card-bg); border: 1px solid var(--gray-200); border-left: 4px solid var(--success);'
                }
            `;

            let content = '';
            
            if (msg.reasoning) {
                content += `<div class="reasoning" style="
                    background: rgba(46, 204, 113, 0.1);
                    border-left: 3px solid var(--success);
                    padding: 10px 14px;
                    margin-bottom: 12px;
                    border-radius: 6px;
                    font-style: italic;
                "><strong>💭 Raciocínio Jurídico:</strong><br>${msg.reasoning}</div>`;
            }

            content += `<div class="content">${this.formatLegalContent(msg.content)}</div>`;
            
            const timestamp = msg.timestamp ? new Date(msg.timestamp) : new Date();
            content += `<div class="timestamp" style="
                font-size: 11px;
                color: ${msg.role === 'user' ? 'rgba(255,255,255,0.7)' : 'var(--gray-400)'};
                margin-top: 8px;
            ">${timestamp.toLocaleString('pt-BR')}</div>`;

            messageDiv.innerHTML = content;
            conversationDiv.appendChild(messageDiv);
        });

        conversationDiv.scrollTop = conversationDiv.scrollHeight;
    }

    formatLegalContent(content) {
        // Format legal content with proper styling
        return content
            // Headers
            .replace(/^### (.*$)/gm, '<h4 style="color: var(--primary); margin-top: 16px; margin-bottom: 8px;">$1</h4>')
            .replace(/^## (.*$)/gm, '<h3 style="color: var(--primary); margin-top: 20px; margin-bottom: 10px;">$1</h3>')
            .replace(/^# (.*$)/gm, '<h2 style="color: var(--primary); margin-top: 24px; margin-bottom: 12px;">$1</h2>')
            // Bold
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Code blocks
            .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre style="background: var(--gray-100); padding: 12px; border-radius: 6px; overflow-x: auto;"><code>$2</code></pre>')
            // Inline code / article references
            .replace(/`([^`]+)`/g, '<code style="background: rgba(74, 107, 223, 0.1); color: var(--primary); padding: 2px 6px; border-radius: 4px;">$1</code>')
            // Blockquotes (for legal citations)
            .replace(/^> (.*$)/gm, '<blockquote style="border-left: 3px solid var(--primary); padding-left: 12px; margin: 12px 0; color: var(--gray-600); font-style: italic;">$1</blockquote>')
            // Line breaks
            .replace(/\n/g, '<br>');
    }

    setupPersistenceControls() {
        const conversationDiv = document.getElementById('lawyer-conversation');
        if (!conversationDiv || !conversationDiv.parentNode) return;

        if (!document.getElementById('lawyer-conversation-toolbar')) {
            const toolbar = document.createElement('div');
            toolbar.id = 'lawyer-conversation-toolbar';
            toolbar.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px;';
            toolbar.innerHTML = `
                <button type="button" class="btn btn-secondary" id="save-case-btn">
                    <i class="fas fa-save" style="margin-right:6px;"></i>Salvar Caso
                </button>
                <button type="button" class="btn btn-secondary" id="export-case-btn">
                    <i class="fas fa-file-export" style="margin-right:6px;"></i>Exportar
                </button>
                <button type="button" class="btn btn-secondary" id="new-case-btn">
                    <i class="fas fa-plus" style="margin-right:6px;"></i>Novo Caso
                </button>
                <div style="display:flex; gap:6px; align-items:center;">
                    <select id="saved-cases-select" style="min-width:200px; padding:6px 10px; border-radius:6px; border:1px solid var(--gray-200); background:var(--card-bg); color:var(--dark);">
                        <option value="">Casos salvos</option>
                    </select>
                    <button type="button" class="btn btn-secondary" id="load-case-btn">
                        <i class="fas fa-upload" style="margin-right:6px;"></i>Carregar
                    </button>
                </div>
            `;
            conversationDiv.parentNode.insertBefore(toolbar, conversationDiv);
        }

        this.attachPersistenceEventListeners();
    }

    attachPersistenceEventListeners() {
        const saveBtn = document.getElementById('save-case-btn');
        if (saveBtn && !saveBtn.dataset.bound) {
            saveBtn.addEventListener('click', () => this.saveCase());
            saveBtn.dataset.bound = 'true';
        }

        const exportBtn = document.getElementById('export-case-btn');
        if (exportBtn && !exportBtn.dataset.bound) {
            exportBtn.addEventListener('click', () => this.exportCase());
            exportBtn.dataset.bound = 'true';
        }

        const newCaseBtn = document.getElementById('new-case-btn');
        if (newCaseBtn && !newCaseBtn.dataset.bound) {
            newCaseBtn.addEventListener('click', () => this.newCase());
            newCaseBtn.dataset.bound = 'true';
        }

        const loadBtn = document.getElementById('load-case-btn');
        if (loadBtn && !loadBtn.dataset.bound) {
            loadBtn.addEventListener('click', () => {
                const select = document.getElementById('saved-cases-select');
                if (!select || !select.value) {
                    showNotification('Selecione um caso para carregar', 'info');
                    return;
                }
                this.loadCase(select.value);
            });
            loadBtn.dataset.bound = 'true';
        }
    }

    saveCase() {
        if (this.conversationHistory.length === 0) {
            showNotification('Nenhuma consulta para salvar', 'info');
            return;
        }

        const defaultName = `Caso ${new Date().toLocaleDateString('pt-BR')} - ${new Date().toLocaleTimeString('pt-BR')}`;
        const name = prompt('Nome do caso:', defaultName);
        if (!name) {
            showNotification('Salvamento cancelado', 'info');
            return;
        }

        if (this.savedCases[name] && !confirm(`Sobrescrever caso "${name}"?`)) {
            return;
        }

        this.savedCases[name] = {
            conversation: this.getSerializableConversation(),
            evidence: Array.from(this.evidenceFiles.entries()),
            savedAt: new Date().toISOString()
        };
        this.persistSavedCases();
        this.updateSavedCaseOptions(name);
        showNotification(`Caso "${name}" salvo com sucesso`, 'success');
    }

    loadCase(name) {
        const stored = this.savedCases[name];
        if (!stored) {
            showNotification('Caso não encontrado', 'error');
            return;
        }

        this.conversationHistory = stored.conversation.map(msg => ({
            role: msg.role,
            content: msg.content,
            reasoning: msg.reasoning,
            timestamp: msg.timestamp || new Date().toISOString()
        }));

        // Restore evidence files
        this.evidenceFiles.clear();
        if (stored.evidence) {
            stored.evidence.forEach(([id, evidence]) => {
                this.evidenceFiles.set(id, evidence);
            });
        }

        this.updateConversationDisplay();
        this.updateEvidenceDisplay();
        showNotification(`Caso "${name}" carregado`, 'success');
    }

    newCase() {
        if (this.conversationHistory.length > 0) {
            if (!confirm('Deseja iniciar um novo caso? O caso atual não salvo será perdido.')) {
                return;
            }
        }

        this.conversationHistory = [];
        this.evidenceFiles.clear();
        this.currentCaseId = null;
        this.updateConversationDisplay();
        this.updateEvidenceDisplay();
        showNotification('Novo caso iniciado', 'success');
    }

    exportCase() {
        if (this.conversationHistory.length === 0) {
            showNotification('Nenhuma consulta para exportar', 'info');
            return;
        }

        const caseData = {
            conversation: this.getSerializableConversation(),
            evidence: Array.from(this.evidenceFiles.entries()).map(([id, e]) => ({
                id,
                name: e.name,
                category: e.category,
                size: e.size,
                uploadedAt: e.uploadedAt
            })),
            exportedAt: new Date().toISOString(),
            version: '1.0'
        };

        const data = JSON.stringify(caseData, null, 2);
        const blob = new Blob([data], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `caso-juridico-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showNotification('Caso exportado com sucesso', 'success');
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

    loadSavedCases() {
        try {
            const raw = localStorage.getItem(this.storageKeys.savedCases);
            if (!raw) return {};
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (error) {
            console.warn('Erro ao carregar casos salvos', error);
            return {};
        }
    }

    persistSavedCases() {
        try {
            localStorage.setItem(this.storageKeys.savedCases, JSON.stringify(this.savedCases));
        } catch (error) {
            console.error('Erro ao persistir casos', error);
            showNotification('Erro ao salvar localmente', 'error');
        }
    }

    updateSavedCaseOptions(selectedName = '') {
        const select = document.getElementById('saved-cases-select');
        if (!select) return;

        const options = ['<option value="">Casos salvos</option>'];
        Object.keys(this.savedCases)
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

    updateAnalysisContext(type) {
        const contextHints = {
            'consumer': 'Foco em direitos do consumidor, CDC, práticas abusivas e danos morais.',
            'aviation': 'Foco em regulamentações da ANAC, overbooking, atrasos e cancelamentos.',
            'civil': 'Foco em responsabilidade civil, danos materiais e morais, obrigação de indenizar.',
            'constitutional': 'Foco em direitos fundamentais, garantias constitucionais e dignidade.',
            'general': 'Análise completa considerando todos os aspectos jurídicos aplicáveis.'
        };

        const hint = contextHints[type] || contextHints.general;
        showNotification(hint, 'info');
    }
}

// Initialize Garage Lawyer
let garageLawyer = null;

document.addEventListener('DOMContentLoaded', function() {
    const lawyerTab = document.querySelector('[data-section="lawyer-section"]');
    if (lawyerTab) {
        lawyerTab.addEventListener('click', function() {
            if (!garageLawyer) {
                garageLawyer = new GarageLawyer();
                garageLawyer.initialize();
            }
        });
    }
});

// Export for global access
window.garageLawyer = garageLawyer;