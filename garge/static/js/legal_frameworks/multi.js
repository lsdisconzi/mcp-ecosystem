/* ====== MULTI-FRAMEWORK LEGAL ANALYSIS PANEL - ENHANCED ====== */

(function injectMultiFrameworkPanel() {
  if (document.getElementById('multiFrameworkPanel')) return;

  const host = document.createElement('section');
  host.id = 'multiFrameworkPanel';
  host.className = 'card compact multi-framework-container';
  
  // Add enhanced styling
  const style = document.createElement('style');
  style.textContent = `
    .multi-framework-container {
      width: 50%;
      min-width: 600px;
      max-width: 90%;
      transition: all 0.3s ease;
      position: relative;
    }
    
    .multi-framework-container.maximized {
      width: 95% !important;
      height: 95vh;
      position: fixed;
      top: 2.5vh;
      left: 2.5%;
      z-index: 1000;
      background: white;
      box-shadow: 0 0 50px rgba(0,0,0,0.3);
      overflow: auto;
    }
    
    .multi-framework-container.maximized .pre {
      max-height: 50vh !important;
    }
    
    .container-toggle {
      background: transparent;
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 4px 8px;
      font-size: 0.8rem;
      cursor: pointer;
      margin-left: 8px;
    }
    
    .container-toggle:hover {
      background: var(--hover);
    }
    
    .framework-section {
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 16px;
      overflow: hidden;
    }
    
    .framework-title {
      background: var(--brand);
      color: white;
      padding: 8px 12px;
      font-weight: 600;
      font-size: 0.9rem;
    }
    
    .stream-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      background: var(--hover);
      border-bottom: 1px solid var(--border);
    }
    
    .stream-status {
      font-size: 0.8rem;
      color: var(--muted);
    }
    
    .stream-content {
      padding: 12px;
      min-height: 60px;
      max-height: 400px;
      overflow-y: auto;
      background: white;
    }
    
    .stream-pulse {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: var(--brand);
      border-radius: 50%;
      margin-right: 8px;
      animation: pulse 1.5s infinite;
    }
    
    .stream-complete {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #4CAF50;
      border-radius: 50%;
      margin-right: 8px;
    }
    
    .stream-error {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #f44336;
      border-radius: 50%;
      margin-right: 8px;
    }
    
    .reasoning-section {
      background: #f8f9fa;
      border-left: 4px solid var(--brand);
      padding: 8px 12px;
      margin-bottom: 12px;
      font-family: monospace;
      font-size: 0.8rem;
      color: #555;
    }
    
    .analysis-section {
      background: white;
      border-left: 4px solid #4CAF50;
      padding: 8px 12px;
      margin-top: 12px;
    }
    
    @keyframes pulse {
      0% { opacity: 1; }
      50% { opacity: 0.4; }
      100% { opacity: 1; }
    }
    
    .context-slot {
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 8px;
      margin-bottom: 8px;
    }
    
    .context-slot.has-file {
      border-color: var(--brand);
      background: rgba(var(--brand-rgb), 0.05);
    }
    
    .slot-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    
    .imported-analysis-item {
      padding: 8px;
      margin: 4px 0;
      background: rgba(0,0,0,0.05);
      border-radius: 4px;
      font-size: 0.8rem;
    }
    
    .framework-checkbox {
      margin-bottom: 8px;
      padding: 4px 0;
    }
    
    .chain-mode-selector, .analysis-mode-selector {
      margin-left: 24px;
      margin-top: 4px;
      font-size: 0.8rem;
    }
    
    .pill {
      display: inline-block;
      background: var(--brand);
      color: white;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 0.8rem;
      margin: 2px;
    }
    
    .framework-chain {
      background: rgba(var(--brand-rgb), 0.05);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 12px;
      margin-top: 8px;
    }
    
    .api-config {
      background: rgba(0,0,0,0.03);
      border-radius: 4px;
      padding: 8px;
      margin-bottom: 12px;
    }
    
    .api-config .field {
      margin-bottom: 8px;
    }
    
    .api-config label {
      font-size: 0.8rem;
      font-weight: 600;
    }
    
    .api-config input, .api-config select {
      width: 100%;
      padding: 4px 8px;
      font-size: 0.8rem;
    }

    .toggle-label {
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      width: 100%;
    }

    .toggle-indicator {
      font-size: 0.9em;
      margin-left: 8px;
      transition: transform 0.2s;
    }

    .toggle-indicator.collapsed {
      transform: rotate(-90deg);
    }
  `;
  document.head.appendChild(style);

  // Initialize global frameworks registry
  window.frameworks = window.frameworks || {};

  // Framework registration
  function registerFramework(name, config) {
    window.frameworks[name] = config;
  }

  // Global store for imported analysis results
  window.importedAnalyses = window.importedAnalyses || {};

  // Framework path - base directory for all legal frameworks
  const baseFrameworkPath = '/static/js/legal_frameworks';
  const fallbackFrameworkDirs = [
    'ANACResolution138Analyzer',
    'AmericanConventionOnHumanRightsAnalyzer',
    'AmericanConventionOnHumanRightsArt5to10Analyzer',
    'AnacResolucao400Analyzer',
    'AnacResolution400Analyzer',
    'Annex15AISAnalyzer',
    'Annex17Analyzer',
    'Annex18DangerousGoodsAnalyzer',
    'Annex3Analyzer',
    'Annex9FacilitationAnalyzer',
    'Annex9FacilitationChapter6Analyzer',
    'Annex9FacilitationChapter8Analyzer',
    'BalanceGestionIntegralAnalyzer',
    'BrazilianAeronauticsCodeAnalyzer',
    'CartasAeronauticasDAN04Analyzer',
    'CertificationOperationAnalyzer',
    'ChileConstitutionAnalyzer',
    'ChileConstitutionArt19Analyzer',
    'ChileDecreto56MC1999Analyzer',
    'CodigoAeronauticoAnalyzer',
    'CodigoAeronauticoDeChileAnalyzer',
    'CodigoAeronauticoLey18916Analyzer',
    'CodigoDefesaConsumidorAnalyzer',
    'CodigoPenalDeChileAnalyzer',
    'ConsumerDefenseCodeAnalyzer',
    'ConvenioDeAviacionCivilInternacionalAnalyzer',
    'ConvenioMarcoAnalyzer',
    'ConventionAgainstTorturePartIAnalyzer',
    'ConventionAgainstTorturePartIIAnalyzer',
    'ConventionAgainstTorturePartIIIAnalyzer',
    'ConventionOnRightsOfChildAnalyzer',
    'ConventionOnTheRightsOfTheChildAnalyzer',
    'ConventionRightsChildAnalyzer',
    'ConventionRightsChildArticles9and18Analyzer',
    'ConventionUnificationRulesAirAnalyzer',
    'CorsiaAnalyzer',
    'DAN03Analyzer',
    'DAN05Analyzer'
  ];

  function getAiEndpoint() {
    const endpointEl = document.getElementById('multiAiEndpoint') || document.getElementById('aiEndpoint');
    return endpointEl ? endpointEl.value.trim() : '';
  }
  
  // Framework chain tracking with enhanced options
  let frameworkChain = [];
  let frameworkChainModes = {}; // Stores chaining mode for each framework
  
  // Centralized state management
  const AnalysisState = {
    currentInput: null,
    selectedFrameworks: [],
    chainConfig: {},
    importedAnalyses: new Map(),
    uiState: {
      isMaximized: false,
      activeTab: 'input'
    },
    
    setInput(data) {
      this.currentInput = data;
      this.triggerUpdate('inputChanged');
    },
    
    setMaximized(isMaximized) {
      this.uiState.isMaximized = isMaximized;
      this.triggerUpdate('layoutChanged');
    },
    
    triggerUpdate(event) {
      // Could be used for reactive updates in the future
      console.log(`State updated: ${event}`);
    }
  };

  // Function to discover available frameworks by scanning directories
  async function discoverFrameworks() {
    try {
      console.log('Discovering legal frameworks...');
      
      // Fetch the directory listing (requires server support for directory listing or a specific API endpoint)
      const response = await fetch(`${baseFrameworkPath}/framework_list.json`);
      
      if (!response.ok) {
        console.warn('Could not fetch framework list, trying fallback detection...');
        // Fallback: try to load a few known directories
        return detectFrameworksFromKnownDirs();
      }
      
      const frameworks = await response.json();
      console.log('Discovered frameworks:', frameworks);
      return frameworks;
    } catch (error) {
      console.error('Error discovering frameworks:', error);
      // Fallback to manual detection
      return detectFrameworksFromKnownDirs();
    }
  }

  // Fallback function to detect frameworks from known directories
  async function detectFrameworksFromKnownDirs() {
    console.log('Using fallback framework detection...');
    
        // Add a function to fetch directories (needs server support)
        async function getFrameworkDirectories() {
          try {
            // Try to get directory listing from server
            const response = await fetch(`${baseFrameworkPath}/framework_list.json`);
            if (response.ok) {
              const dirs = await response.json();
              if (Array.isArray(dirs)) return dirs;
              if (dirs && typeof dirs === 'object') return Object.keys(dirs);
            }
            // If response is not OK, use local fallback directories
            return [...fallbackFrameworkDirs];
          } catch (error) {
            console.error('Error getting directory list:', error);
            return [...fallbackFrameworkDirs];
          }
        }
        
        // Get the directories
    // ...existing code...
    
    // Get the directories
    const knownDirs = await getFrameworkDirectories();
    console.log('Detected framework directories:', knownDirs);
    
    const frameworks = {};
    
    // Try to load config.json from each known directory
    for (const dir of knownDirs) {
      try {
        // Skip non-framework directories (like the multi_legal_frameworks.js itself)
        if (!dir.endsWith('Analyzer') && !dir.includes('Convention') && !dir.includes('Rights')) {
          console.log(`Skipping non-framework directory: ${dir}`);
          continue;
        }
        
        const configPath = `${baseFrameworkPath}/${dir}/config.json`;
        const response = await fetch(configPath);
        
        if (response.ok) {
          const config = await response.json();
          
          // Generate a key based on the directory name
          const key = dir.replace(/Analyzer$/, '').toLowerCase();
          
          frameworks[key] = {
            name: config.framework_name || formatFrameworkName(dir),
            description: config.framework_description || config.framework_type ? 
              `${config.framework_type} - ${config.responsible_entity || ''}` : 
              `Analysis framework for ${formatFrameworkName(dir)}`,
            defaultPrompt: config.default_prompt || `Analyze the transcript for compliance with ${config.framework_name || formatFrameworkName(dir)}...`,
            path: `${baseFrameworkPath}/${dir}`,
            directory: dir,
            config: config, // Store the complete config for reference
            
            // ADD THESE LINES: Preserve jurisdiction data if present in config
            primary_jurisdiction: config.primary_jurisdiction || 'Unknown',
            flag: config.flag || '🏳️'
          };
          
          console.log(`✅ Detected framework: ${frameworks[key].name}`);
          
          // Also check for the existence of generated_prompt.txt right away
          try {
            const promptPath = `${baseFrameworkPath}/${dir}/generated_prompt.txt`;
            const promptResponse = await fetch(promptPath);
            
            if (promptResponse.ok) {
              const promptText = await promptResponse.text();
              frameworks[key].generatedPrompt = promptText;
              frameworks[key].generatedPromptLoaded = true;
              console.log(`✅ Also loaded prompt for: ${frameworks[key].name}`);
            }
          } catch (promptErr) {
            console.log(`No prompt file found for ${dir}, will try to load it later.`);
          }
        } else {
          console.warn(`⚠️ Could not load config for ${dir} - HTTP ${response.status}`);
        }
      } catch (error) {
        console.warn(`⚠️ Error loading framework from ${dir}:`, error);
      }
    }
    
    return frameworks;
  }


  // load frameworks indexed
  let jurisdictionIndex = null;
  
  async function loadJurisdictionIndex() {
    if (jurisdictionIndex) return jurisdictionIndex;
    try {
      const resp = await fetch('/static/js/legalframeworks-repository/jurisdiction_index.json');
      if (!resp.ok) throw new Error('Failed to load jurisdiction index');
      jurisdictionIndex = await resp.json();
      return jurisdictionIndex;
    } catch (e) {
      console.error('Could not load jurisdiction index:', e);
      jurisdictionIndex = {};
      return jurisdictionIndex;
    }
  }

  // Map frameworks to jurisdictions using the index
  // ...existing code...
  
  async function groupFrameworksByJurisdictionAndFlag(frameworks) {
      const index = await loadJurisdictionIndex();
      const grouped = {};
    
      // Build a reverse lookup: key -> {jurisdiction, flag, name}
      const keyToJurisdiction = {};
      for (const [jurisdiction, items] of Object.entries(index)) {
        for (const item of items) {
          keyToJurisdiction[item.key] = {
            jurisdiction,
            flag: item.flag || '🌐',
            name: item.name,
            categories: item.categories || []
          };
        }
      }
    
      for (const key in frameworks) {
        const fw = frameworks[key];
        
        // PRIORITY 1: Use primary_jurisdiction and flag from framework_list.json if available
        let meta;
        if (fw.primary_jurisdiction && fw.flag) {
          meta = {
            jurisdiction: fw.primary_jurisdiction,
            flag: fw.flag,
            name: fw.name,
            categories: fw.categories || []
          };
          console.log(`✓ Using framework_list.json data for ${key}: ${meta.jurisdiction} ${meta.flag}`);
        } else {
          // PRIORITY 2: Fall back to jurisdiction_index.json
          meta = keyToJurisdiction[key];
          
          if (meta) {
            console.log(`✓ Using jurisdiction_index.json data for ${key}: ${meta.jurisdiction} ${meta.flag}`);
          } else {
            // PRIORITY 3: Final fallback
            meta = { 
              jurisdiction: 'Unknown', 
              flag: '🏳️', 
              name: fw.name, 
              categories: [] 
            };
            console.warn(`⚠ No jurisdiction data found for ${key}, using Unknown`);
          }
        }
        
        const groupKey = `${meta.flag} ${meta.jurisdiction}`;
        if (!grouped[groupKey]) grouped[groupKey] = [];
        grouped[groupKey].push({
          key,
          ...fw,
          jurisdiction: meta.jurisdiction,
          flag: meta.flag,
          categories: meta.categories
        });
      }
      return grouped;
    }
  
  // ...existing code...


  // Helper function to format framework name from directory
  function formatFrameworkName(dirName) {
    return dirName
      .replace(/([A-Z])/g, ' $1') // Add spaces before capital letters
      .replace(/Analyzer$/, '') // Remove Analyzer suffix
      .replace(/_/g, ' ') // Replace underscores with spaces
      .trim();
  }

  // Function to dynamically load a script
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      // Check if script is already loaded
      if (document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }
      
      // If src ends with undefined or contains undefined, try to fix it
      if (src.includes('undefined') || src.endsWith('undefined')) {
        console.warn(`Invalid script path detected: ${src}, attempting to fix...`);
        
        // Extract directory name
        const parts = src.split('/');
        const dirName = parts[parts.length - 2]; // Get the directory name
        
        // Assume the JS file has the same name as the directory
        const correctedSrc = `${baseFrameworkPath}/${dirName}/${dirName}.js`;
        console.log(`Corrected path: ${correctedSrc}`);
        
        // Update the src
        src = correctedSrc;
      }
      
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = () => {
        console.log(`✅ Successfully loaded: ${src}`);
        resolve();
      };
      script.onerror = (err) => {
        console.error(`❌ Failed to load script: ${src}`, err);
        reject(new Error(`Failed to load script: ${src}`));
      };
      document.head.appendChild(script);
    });
  }

  // Function to load all framework scripts and prompts
  async function loadFrameworks() {
    try {
      // First discover available frameworks
      const discoveredFrameworks = await discoverFrameworks();
      
      // Store discovered frameworks in the global object
      window.frameworks = discoveredFrameworks;
      
      // Build a list of scripts to load
      const frameworkScripts = [];
      
      // For each framework, determine the main JS file to load
      for (const key in discoveredFrameworks) {
        const fw = discoveredFrameworks[key];
        const dir = fw.directory || key;
        
        // Match your exact structure - JS file has same name as the directory
        const scriptFile = `${fw.path}/${dir}.js`;
        
        console.log(`Will load script: ${scriptFile}`);
        frameworkScripts.push(scriptFile);
      }
      
      // Load all scripts
      await Promise.all(frameworkScripts.map(loadScript));
      console.log('All legal frameworks loaded successfully.');
      
      // Then try to load generated prompts for each framework
      for (const key in window.frameworks) {
        await loadGeneratedPrompt(key);
      }
      
      // After loading, ensure the checkboxes are updated
      setupFrameworkCheckboxes();
      
      // Update the UI to show which frameworks have loaded prompts
      updateFrameworkUI();
    } catch (error) {
      console.error('Error loading legal frameworks:', error);
      // Still try to setup with discovered definitions as fallback
      setupFrameworkCheckboxes();
    }
  }

  // Function to update UI elements based on loaded frameworks
  function updateFrameworkUI() {
    const promptTextarea = document.getElementById('multiPrompt');
    
    // Update the textarea placeholder to indicate that framework-specific prompts will be used
    if (promptTextarea) {
      promptTextarea.placeholder = 'Custom instruction (framework-specific prompts will be used if available)';
      
      // Add a note about framework prompts
      const noteDiv = document.createElement('div');
      noteDiv.className = 'prompt-note';
      noteDiv.style.fontSize = '0.7rem';
      noteDiv.style.color = 'var(--muted)';
      noteDiv.style.marginTop = '4px';
      noteDiv.textContent = 'Framework-specific prompts will be used by default when available.';
      
      // Insert after the textarea
      promptTextarea.parentNode.appendChild(noteDiv);
    }
    
    // Add a framework status indicator
    const statusDiv = document.createElement('div');
    statusDiv.id = 'frameworkLoadStatus';
    statusDiv.style.fontSize = '0.7rem';
    statusDiv.style.marginTop = '8px';
    statusDiv.style.padding = '4px 8px';
    statusDiv.style.background = 'rgba(0,0,0,0.05)';
    statusDiv.style.borderRadius = '4px';
    
    const loadedFrameworks = Object.keys(window.frameworks).length;
    
    if (loadedFrameworks > 0) {
      statusDiv.style.color = '#4CAF50';
      statusDiv.innerHTML = `<span style="font-weight:600;">✓ ${loadedFrameworks} frameworks loaded</span>`;
    } else {
      statusDiv.style.color = '#FFC107';
      statusDiv.innerHTML = `<span style="font-weight:600;">⚠ No frameworks loaded</span>`;
    }
     
    const container = document.getElementById('frameworkCheckboxes');
    if (container) {
      container.parentNode.appendChild(statusDiv);
    }
  }

  // Build UI with enhanced chaining options and universal input
  host.innerHTML = `
    <h3 style="display:flex;align-items:center;gap:8px;">
      <button id="containerToggle" class="container-toggle" title="Toggle container size">⛶</button>
      Multi-Framework Legal Analysis
      <button id="multiBuildBtn" class="btn small" style="margin-left:auto;">Generate Payloads</button>
      <button id="multiSendBtn" class="btn small primary">Send</button>
      <button id="multiExportBtn" class="btn small">Export</button>
      <button id="enhancedExportBtn" class="btn small primary">Export Enhanced</button>
      <button id="multiImportBtn" class="btn small">Import Previous</button>
    </h3>
    
    <!-- API Configuration Section -->
    <div class="field">
      <label class="toggle-label">API Configuration<span class="toggle-indicator">▼</span></label>
      <div class="toggle-content">
        <div class="api-config">
          <div class="field">
            <label>API Endpoint</label>
            <input type="text" id="multiAiEndpoint" value="/v1/assistants/deepseek-stream-proxy" placeholder="API endpoint" />
          </div>
          <div class="field">
            <label>AI Model</label>
            <select id="aiModel">
              <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
              <option value="gpt-4">GPT-4</option>
              <option value="claude-3-sonnet">Claude 3 Sonnet</option>
            </select>
          </div>
        </div>
      </div>
    </div>

      <!-- Base Context Section -->
      <div class="field">
        <label class="toggle-label">Base Context Documents<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div id="baseContextSlots" class="base-context-slots">
            <div class="context-slot">
              <div class="slot-header">
                <span>Master Report</span>
                <button class="btn small clear" data-slot="0">Clear</button>
              </div>
              <input type="file" class="context-file" data-slot="0" accept=".txt,.md"/>
            </div>
            <div class="context-slot">
              <div class="slot-header">
                <span>Comprehensive Violations</span>
                <button class="btn small clear" data-slot="1">Clear</button>
              </div>
              <input type="file" class="context-file" data-slot="1" accept=".txt,.md"/>
            </div>
            <div class="context-slot">
              <div class="slot-header">
                <span>Synthesized Narrative</span>
                <button class="btn small clear" data-slot="2">Clear</button>
              </div>
              <input type="file" class="context-file" data-slot="2" accept=".txt,.md"/>
            </div>
          </div>
        </div>
      </div>
      
      <div class="field">
        <label class="toggle-label">Transcript Selection<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div style="display:flex;gap:8px;align-items:center;">
            <select id="transcriptSelector" style="flex:1;"></select>
            <button id="viewTranscriptBtn" class="btn small">View</button>
          </div>
        </div>
      </div>
      <div id="transcriptDisplayModal" style="display:none;position:fixed;top:10vh;left:50%;transform:translateX(-50%);width:60vw;max-width:900px;max-height:70vh;overflow:auto;background:white;border:1px solid #ccc;box-shadow:0 8px 32px rgba(0,0,0,0.2);z-index:9999;padding:24px;border-radius:8px;">
        <button id="closeTranscriptModal" style="position:absolute;top:8px;right:12px;" class="btn small">Close</button>
        <h4>Transcript Preview</h4>
        <pre id="transcriptDisplayContent" style="white-space:pre-wrap;font-size:0.95em;background:#f8f8f8;padding:12px;border-radius:4px;max-height:60vh;overflow:auto;"></pre>
      </div>
    </div>    
    <div class="content" style="padding-top:6px;">
      <!-- Universal Input Section -->
      <div class="field">
        <label class="toggle-label">Universal Input Source<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div style="display: flex; gap: 8px; margin-bottom: 8px;">
            <button id="useTranscriptBtn" class="btn small primary">Use Current Transcript</button>
            <button id="useDocumentBtn" class="btn small">Upload Document</button>
            <button id="useTextBtn" class="btn small">Paste Text</button>
          </div>
          <div id="documentInputSection" style="display: none; margin-top: 8px;">
            <input type="file" id="documentUpload" accept=".txt,.html,.pdf,.msg,.eml,.md" />
            <div style="font-size: 0.8rem; color: var(--muted); margin-top: 4px;">
              Supported: Text files, HTML, PDF, Email files (.msg, .eml, .md)
            </div> 
          </div>
          <div id="textInputSection" style="display: none; margin-top: 8px;">
            <textarea id="pastedText" placeholder="Paste text content here..." style="width: 100%; min-height: 100px; font-family: monospace; font-size: 0.9rem;"></textarea>
            <button id="processTextBtn" class="btn small" style="margin-top: 8px;">Process Text</button>
          </div>
          <div id="inputSourceInfo" style="margin-top: 8px; padding: 8px; background: rgba(0,0,0,0.03); border-radius: 4px; font-size: 0.8rem;">
            Current source: <span id="currentSource">Transcript</span>
          </div>
        </div>
      </div>
      
      <!-- Import Chain Configuration Section -->
      <div class="field">
        <label class="toggle-label">Import Chain Configuration<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content" style="display: none;">
          <p style="font-size: 0.8rem; color: var(--muted); margin-bottom: 8px;">Load a chain configuration file (chain_analysis.json) to automatically configure frameworks and chaining modes.</p>
          <input type="file" id="chainConfigImport" accept=".json" />
        </div>
      </div>

      <!-- Add import section -->
      <div class="field" id="importSection" style="display: none;">
        <label class="toggle-label">Import Previous Analysis<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <input type="file" id="analysisImport" accept=".zip" style="margin-bottom: 8px;" />
          <div id="importedAnalyses" class="imported-analyses" style="margin-top: 8px;"></div>
        </div>
      </div>
      
      <div class="field">
        <label class="toggle-label">Select frameworks<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div id="frameworkCheckboxes" class="framework-selector"></div>
        </div>
      </div>
      
      <!-- Add section for imported analyses -->
      <div class="field" id="previousAnalysesSection" style="display: none;">
        <label class="toggle-label">Previous Analyses (can be used as context)<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div id="previousAnalysesCheckboxes" class="framework-selector"></div>
        </div>
      </div>
      
      <div class="field">
        <label class="toggle-label">Chain analysis<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div id="frameworkChain" class="framework-chain" style="display:none;">
            <strong>Analysis sequence:</strong>
            <div id="chainOrder"></div>
            <div id="chainModes" style="margin-top: 8px; font-size: 0.8rem;"></div>
          </div>
        </div>
      </div>
      <div class="field">
        <label class="toggle-label">Prompt / Instructions (applied per framework)<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <textarea id="multiPrompt" placeholder="Custom instruction"></textarea>
        </div>
      </div>
      <div class="field">
        <label class="toggle-label">Payloads JSON<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <pre id="multiPayloadsPre" class="pre">—</pre>
        </div>
      </div>
      <!-- Enhanced AI Reasoning Output -->
      <div class="field">
        <label class="toggle-label">AI Reasoning Process<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <div id="aiReasoningContainer" style="display: none;">
            <div class="reasoning-header" style="display: flex; justify-content: space-between; align-items: center;">
              <h4>Step-by-Step Reasoning</h4>
              <button id="toggleReasoning" class="btn small" style="font-size: 0.7rem;">Show/Hide</button>
            </div>
            <div id="ai-reasoning-output" style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px; padding: 12px; max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 12px; line-height: 1.4; color: #555;">
              The AI's thought process will appear here...
            </div>
          </div>
        </div>
      </div>
      <div class="field">
        <label class="toggle-label">Output<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <pre id="multiOutput" class="pre">—</pre>
        </div>
      </div>
 
      <!-- Combined Report Section -->
      <div class="field" id="combinedReportSection" style="display: none;">
        <label class="toggle-label">Combined Analysis Report<span class="toggle-indicator">▼</span></label>
        <div class="toggle-content">
          <pre id="combinedReport" class="pre">—</pre>
        </div>
      </div>
    </div>
  `;

  // Current input source data
  let currentInputData = null;

  // Inject when ready
  function injectWhenReady() {
    const target = document.querySelector('#runs .grid-main') || document.querySelector('#runs');
    if (target) {
      target.appendChild(host);
      setupFrameworkCheckboxes();
      setupEventListeners();
      setupContainerToggle();
      setupSectionToggles(); // Add this call
      loadFrameworks();
      // If runsState is empty, load from backend
      if (!window.runsState || !window.runsState.runs || window.runsState.runs.length === 0) {
        fetchAndSetBackendTranscript().then(() => {
          useCurrentTranscript().catch(console.error);
          populateTranscriptSelector();
          // Initialize enhanced features after transcript and selector are ready
          if (typeof initializeEnhancedFeatures === 'function') initializeEnhancedFeatures();
        });
      } else {
        useCurrentTranscript().catch(console.error);
        if (typeof initializeEnhancedFeatures === 'function') initializeEnhancedFeatures();
      }
    } else {
      setTimeout(injectWhenReady, 100);
    }
  }

  // Setup container toggle functionality
  function setupContainerToggle() {
    const toggleBtn = document.getElementById('containerToggle');
    if (!toggleBtn) return;
    
    toggleBtn.onclick = function() {
      const isMaximized = host.classList.toggle('maximized');
      
      // Update button icon and title
      this.innerHTML = isMaximized ? '⛶' : '⛶';
      this.title = isMaximized ? 'Restore size' : 'Maximize';
      
      // Handle layout adjustments
      if (isMaximized) {
        enterMaximizedMode();
      } else {
        exitMaximizedMode();
      }
      
      // Update state
      AnalysisState.setMaximized(isMaximized);
      
      // Notify other components if needed
      window.dispatchEvent(new CustomEvent('containerResized', {
        detail: { isMaximized }
      }));
    };
  }

  function enterMaximizedMode() {
    // Store previous state
    host.dataset.previousWidth = host.style.width;
    
    // Apply maximize styles
    Object.assign(host.style, {
      position: 'fixed',
      top: '2.5vh',
      left: '2.5%',
      width: '95%',
      height: '95vh',
      zIndex: '1000',
      backgroundColor: 'white',
      boxShadow: '0 0 50px rgba(0,0,0,0.3)',
      overflow: 'auto'
    });
    
    // Adjust internal elements for better use of space
    document.querySelectorAll('.pre').forEach(pre => {
      pre.style.maxHeight = '50vh';
    });
  }

  function exitMaximizedMode() {
    // Restore previous state
    Object.assign(host.style, {
      position: '',
      top: '',
      left: '',
      width: host.dataset.previousWidth || '50%',
      height: '',
      zIndex: '',
      backgroundColor: '',
      boxShadow: '',
      overflow: ''
    });
    
    // Reset internal elements
    document.querySelectorAll('.pre').forEach(pre => {
      pre.style.maxHeight = '';
    });
  }

  // Function to setup section toggles
  function setupSectionToggles() {
    host.querySelectorAll('.toggle-label').forEach(label => {
      const content = label.nextElementSibling;
      const indicator = label.querySelector('.toggle-indicator');
      
      // Hide all sections by default except a few key ones
      const isInitiallyOpen = ['Select frameworks', 'Universal Input Source', 'Output'].includes(label.innerText.trim());
      if (!isInitiallyOpen && content) {
        content.style.display = 'none';
        indicator.classList.add('collapsed');
      }

      label.addEventListener('click', () => {
        if (content) {
          const isCollapsed = content.style.display === 'none';
          content.style.display = isCollapsed ? '' : 'none';
          indicator.classList.toggle('collapsed', !isCollapsed);
        }
      });
    });
  }

// Replace your old setupFrameworkCheckboxes with this
function setupFrameworkCheckboxes() {
  const container = document.getElementById('frameworkCheckboxes');
  if (!container) return;

  // Ensure globals exist
  window.frameworkSelectionOrder = window.frameworkSelectionOrder || [];
  window.frameworkChainModes = window.frameworkChainModes || {};
  window.frameworkChain = window.frameworkChain || [];

  // Helper: support both sync and promise-based grouping functions
  const groupedPromise = (typeof groupFrameworksByJurisdictionAndFlag === 'function')
    ? Promise.resolve(groupFrameworksByJurisdictionAndFlag(window.frameworks))
    : Promise.resolve(groupFrameworksByJurisdictionAndFlagSync(window.frameworks));

  groupedPromise.then(grouped => {
    // Preferred ordering for groups
    const preferredOrder = ['🇧🇷 Brazil', '🇨🇱 Chile', '🌐 International'];

    const groupKeys = Object.keys(grouped).sort((a, b) => {
      const ia = preferredOrder.indexOf(a);
      const ib = preferredOrder.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b);
    });

    // Create or get the card container
    let cardContainer = document.getElementById('frameworkGroupCardContainer');
    if (!cardContainer) {
      cardContainer = document.createElement('div');
      cardContainer.id = 'frameworkGroupCardContainer';
      cardContainer.style.display = 'flex';
      cardContainer.style.gap = '12px';
      cardContainer.style.marginBottom = '12px';
      cardContainer.style.flexWrap = 'wrap';
      container.parentNode.insertBefore(cardContainer, container);
    }
    cardContainer.innerHTML = '';

    // Selected groups (persist as JSON in dataset)
    let selectedGroups = new Set();
    try {
      const persisted = cardContainer.dataset.selectedGroups;
      if (persisted) JSON.parse(persisted).forEach(k => selectedGroups.add(k));
    } catch (e) { /* ignore parse errors */ }

    // Default: select first group if none are selected
    if (selectedGroups.size === 0 && groupKeys.length) {
      selectedGroups.add(groupKeys[0]);
      cardContainer.dataset.selectedGroups = JSON.stringify(Array.from(selectedGroups));
    }

    // Utility: find groupKey for a framework key
    function findGroupKeyForFramework(fwKey) {
      for (const [gk, arr] of Object.entries(grouped)) {
        if (arr.find(a => a.key === fwKey)) return gk;
      }
      return 'Unknown';
    }

    // Render group cards
    function renderCards() {
      cardContainer.innerHTML = '';
      groupKeys.forEach(key => {
        const card = document.createElement('div');
        card.className = 'framework-group-card';
        card.style.cursor = 'pointer';
        card.style.padding = '10px 18px';
        card.style.borderRadius = '8px';
        card.style.border = '2px solid var(--border)';
        card.style.fontWeight = '600';
        card.style.fontSize = '1.1em';
        card.style.display = 'flex';
        card.style.alignItems = 'center';
        card.style.transition = 'all 0.12s';
        // style according to selected state
        const isSelected = selectedGroups.has(key);
        card.style.background = isSelected ? 'var(--brand)' : '#fff';
        card.style.color = isSelected ? '#fff' : '#222';
        card.style.boxShadow = isSelected ? '0 2px 8px rgba(0,0,0,0.08)' : '';

        const [flag, ...jurParts] = key.split(' ');
        const jurisdiction = jurParts.join(' ') || key;
        // try to show flag emoji (if present)
        const flagText = flag.match(/[\uD800-\uDBFF][\uDC00-\uDFFF]/) ? flag : '';
        card.innerHTML = `<span style="font-size:1.5em;margin-right:10px;">${flagText}</span> ${jurisdiction}`;

        card.onclick = () => {
          // Toggle selection
          if (selectedGroups.has(key)) selectedGroups.delete(key);
          else selectedGroups.add(key);

          // Persist dataset
          cardContainer.dataset.selectedGroups = JSON.stringify(Array.from(selectedGroups));
          // Update UI (cards and frameworks)
          renderCards();
          renderFrameworks();
        };

        cardContainer.appendChild(card);
      });
    }

    // Returns a map (key -> fw object + meta { groupKey })
    function computeVisibleFrameworks() {
      const visible = new Map();

      // 1) Add frameworks from currently selected groups
      selectedGroups.forEach(gk => {
        const arr = grouped[gk] || [];
        arr.forEach(fw => {
          visible.set(fw.key, Object.assign({}, fw, { groupKey: gk }));
        });
      });

      // 2) Ensure any checked frameworks (in frameworkSelectionOrder) are present
      (window.frameworkSelectionOrder || []).forEach(k => {
        if (!visible.has(k)) {
          // try to get fw from window.frameworks or grouped entries
          const fwFromWindow = window.frameworks && window.frameworks[k];
          if (fwFromWindow) {
            const gk = findGroupKeyForFramework(k);
            visible.set(k, Object.assign({ key: k }, fwFromWindow, { groupKey: gk }));
          } else {
            // fallback: try to search grouped
            for (const [gk, arr] of Object.entries(grouped)) {
              const found = arr.find(x => x.key === k);
              if (found) {
                visible.set(k, Object.assign({}, found, { groupKey: gk }));
                break;
              }
            }
          }
        }
      });

      return visible;
    }

    // Render frameworks for all selected groups + checked ones
    function renderFrameworks() {
      const visibleMap = computeVisibleFrameworks();
      container.innerHTML = '';

      if (visibleMap.size === 0) {
        container.innerHTML = '<div style="color:red;">No frameworks visible. Click a flag to add frameworks.</div>';
        updateFrameworkChain(); // keep chain consistent
        return;
      }

      // Build render order: first the checked frameworks (in selection order), then the rest (grouped)
      const order = [];
      (window.frameworkSelectionOrder || []).forEach(k => {
        if (visibleMap.has(k)) order.push(visibleMap.get(k));
        visibleMap.delete(k);
      });

      // Add remaining frameworks sorted by their group order and name
      const remaining = Array.from(visibleMap.values()).sort((a, b) => {
        const gAi = groupKeys.indexOf(a.groupKey);
        const gBi = groupKeys.indexOf(b.groupKey);
        if (gAi !== gBi) return (gAi === -1 ? 999 : gAi) - (gBi === -1 ? 999 : gBi);
        return (a.name || '').localeCompare(b.name || '');
      });

      const renderList = order.concat(remaining);

      renderList.forEach(fw => {
        const wrapper = document.createElement('div');
        wrapper.className = 'framework-checkbox';
        wrapper.style.marginBottom = '8px';

        const isChecked = (window.frameworkSelectionOrder || []).includes(fw.key);
        const promptIndicator = fw.generatedPromptLoaded ? '<span style="margin-left:6px;font-size:.65rem;color:var(--brand)">✓ prompt</span>' : '';
        const typeIndicator = fw.config?.framework_type ? `<span style="margin-left:6px;font-size:.65rem;color:var(--muted)">${fw.config.framework_type}</span>` : '';
        const groupBadge = fw.groupKey ? `<span style="margin-left:8px;font-size:.75rem;opacity:.85">${fw.groupKey}</span>` : '';
        wrapper.innerHTML = `
          <div style="display:flex; align-items:center;">
            <input type="checkbox" id="${fw.key}" data-framework="${fw.key}" ${isChecked ? 'checked' : ''} />
            <label for="${fw.key}" title="${fw.description}" style="margin-right:8px; margin-left:8px;">${fw.name}${promptIndicator}${typeIndicator}</label>
            ${groupBadge}
          </div>
          <div class="chain-mode-selector" style="display: ${isChecked ? 'block' : 'none'}; margin-left: 36px; margin-top:4px; font-size:0.85rem;">
            <label>Chaining mode: </label>
            <select id="${fw.key}_mode" data-framework="${fw.key}">
              <option value="none">No input from previous</option>
              <option value="last">Use last framework results</option>
              <option value="all">Use all previous results</option>
            </select>
          </div>
        `;
        container.appendChild(wrapper);

        // hook events
        const checkbox = wrapper.querySelector('input[type="checkbox"]');
        const modeSelect = wrapper.querySelector('select');
        const modeSelector = wrapper.querySelector('.chain-mode-selector');

        // set mode value if present
        if (window.frameworkChainModes && window.frameworkChainModes[fw.key]) {
          modeSelect.value = window.frameworkChainModes[fw.key];
        }

        // Visibility of mode selector depends on checked state
        checkbox.addEventListener('change', (e) => {
          const fwKey = fw.key;
          if (e.target.checked) {
            // show the mode selector for this framework now
            modeSelector.style.display = 'block';
            if (!window.frameworkSelectionOrder.includes(fwKey)) window.frameworkSelectionOrder.push(fwKey);
            // if framework has generatedPromptLoaded, and multiPrompt is empty, set it
            if (fw.generatedPromptLoaded) {
              const textarea = document.getElementById('multiPrompt');
              if (textarea && (!textarea.value.trim() || textarea.value === textarea.placeholder)) {
                textarea.value = fw.generatedPrompt;
              }
            }
          } else {
            // hide selector and remove from selection order
            modeSelector.style.display = 'none';
            window.frameworkSelectionOrder = (window.frameworkSelectionOrder || []).filter(k => k !== fwKey);
            // If user unchecked and this framework's group is not selected, it will be removed next render
          }
          // re-render so new visible set matches selected groups + checked frameworks
          renderFrameworks();
          updateFrameworkChain();
        });

        modeSelect.addEventListener('change', (e) => {
          const frameworkKey = e.target.dataset.framework;
          window.frameworkChainModes[frameworkKey] = e.target.value;
          updateFrameworkChain();
        });
      });

      // Update chain UI after rendering
      updateFrameworkChain();
    }

    // Mode description helper (kept from your original)
    function getModeDescription(mode) {
      switch(mode) {
        case 'none': return 'Independent analysis';
        case 'last': return 'Uses previous framework results';
        case 'all': return 'Uses all previous results';
        default: return 'Independent analysis';
      }
    }

    // Update chain UI (keeps old element IDs: chainOrder, frameworkChain, chainModes)
    function updateFrameworkChain() {
      const chainElement = document.getElementById('chainOrder');
      const chainContainer = document.getElementById('frameworkChain');
      const chainModesElement = document.getElementById('chainModes');

      const frameworkChain = Array.from(window.frameworkSelectionOrder || []);

      if (frameworkChain.length === 0) {
        if (chainContainer) chainContainer.style.display = 'none';
        if (chainElement) chainElement.innerHTML = '';
        if (chainModesElement) chainModesElement.innerHTML = '';
        return;
      }

      if (chainContainer) chainContainer.style.display = 'block';
      if (chainElement) {
        chainElement.innerHTML = frameworkChain.map(id => {
          const framework = window.frameworks[id] || { name: id };
          return `<span class="pill">${framework.name}</span>`;
        }).join(' → ');
      }

      if (chainModesElement) {
        let modesHtml = '<div style="margin-top: 8px;"><strong>Chaining modes:</strong><br>';
        frameworkChain.forEach((id, index) => {
          const framework = window.frameworks[id] || { name: id };
          const mode = (window.frameworkChainModes && window.frameworkChainModes[id]) || 'none';
          modesHtml += `${framework.name}: ${getModeDescription(mode)}`;
          if (index < frameworkChain.length - 1) modesHtml += '<br>';
        });
        modesHtml += '</div>';
        chainModesElement.innerHTML = modesHtml;
        }
      }

      // Initial render
      renderCards();
      renderFrameworks();

      // Expose updateFrameworkChain in case other code calls it
      window.updateFrameworkChain = updateFrameworkChain;
    }).catch(err => {
      console.error('Error building framework groups:', err);
    });
  }

  function setupEventListeners() {
    // Main action buttons
    const buildBtn = document.getElementById('multiBuildBtn');
    if (buildBtn) buildBtn.onclick = buildMultiPayloads;
  
    const sendBtn = document.getElementById('multiSendBtn');
    if (sendBtn) sendBtn.onclick = sendMultiPayloads;
  
    const exportBtn = document.getElementById('multiExportBtn');
    if (exportBtn) exportBtn.onclick = exportMultiAnalysis;
  
    const importBtn = document.getElementById('multiImportBtn');
    if (importBtn) importBtn.onclick = toggleImportSection;
  
    // Setup import functionality
    const importInput = document.getElementById('analysisImport');
    if (importInput) {
      importInput.onchange = handleAnalysisImport;
    }
    
    // Add handler for chain config import
    const chainImportInput = document.getElementById('chainConfigImport');
    if (chainImportInput) {
      chainImportInput.onchange = handleChainConfigImport;
    }

    // Setup universal input functionality
    document.getElementById('useTranscriptBtn').onclick = useCurrentTranscript;
    document.getElementById('useDocumentBtn').onclick = toggleDocumentInput;
    document.getElementById('useTextBtn').onclick = toggleTextInput;
    document.getElementById('processTextBtn').onclick = processTextInput;
    document.getElementById('documentUpload').onchange = handleDocumentUpload;

    // Toggle reasoning display
    const toggleBtn = document.getElementById('toggleReasoning');
    if (toggleBtn) {
      toggleBtn.onclick = function() {
        const reasoningOutput = document.getElementById('ai-reasoning-output');
        if (reasoningOutput.style.display === 'none') {
          reasoningOutput.style.display = 'block';
          this.textContent = 'Hide Reasoning';
        } else {
          reasoningOutput.style.display = 'none';
          this.textContent = 'Show Reasoning';
        }
      };
    }
    
    // Setup base context file handlers
    document.querySelectorAll('.context-file').forEach(input => {
      input.addEventListener('change', handleBaseContextUpload);
    });

    document.querySelectorAll('.context-slot .clear').forEach(button => {
      button.addEventListener('click', clearBaseContextSlot);
    });

    //PDF export handler
    const exportPdfBtn = document.getElementById('multiExportPDFBtn');
    if (exportPdfBtn) exportPdfBtn.onclick = exportPDFReportsOnly;

    // Transcript selection and viewing
    document.getElementById('viewTranscriptBtn').onclick = function() {
      const selector = document.getElementById('transcriptSelector');
      const selectedId = selector.value;
      const transcript = window.runsState.runs.find(run => run.id === selectedId);
      
      if (transcript && transcript.data && transcript.data.segments) {
        // Format and display the transcript segments
        const lines = transcript.data.segments.map(s => {
          const speakerLabel = typeof getSpeakerLabel === 'function' ? 
            getSpeakerLabel(s.speaker) : `Speaker ${s.speaker}`;
          return `[${(s.start||0).toFixed(2)}-${(s.end||0).toFixed(2)}] ${speakerLabel}: ${(s.text||'').trim()}`;
        }).join('\n');
        
        // Show in modal
        const modal = document.getElementById('transcriptDisplayModal');
        const content = document.getElementById('transcriptDisplayContent');
        content.textContent = lines;
        modal.style.display = 'block';
      } else {
        alert('Selected transcript is not available');
      }
    };
    
    // Close transcript modal
    document.getElementById('closeTranscriptModal').onclick = function() {
      const modal = document.getElementById('transcriptDisplayModal');
      modal.style.display = 'none';
    };
    
    const selector = document.getElementById('transcriptSelector');
    if (selector) {
      selector.onchange = async function() {
        await fetchAndSetBackendTranscript(this.value);
        await useCurrentTranscript();
        showToast('Transcript loaded: ' + this.value);
      };
    }
    const viewBtn = document.getElementById('viewTranscriptBtn');
    if (viewBtn) {
      viewBtn.onclick = async function() {
        const run = window.runsState?.runs?.find(x => x.id === window.runsState.activeId);
        if (!run || !run.data || !run.data.segments) {
          showToast('No transcript loaded');
          return;
        }
        const lines = run.data.segments.map(s => {
          const displaySpeaker = typeof getSpeakerLabel === 'function'
            ? getSpeakerLabel(s.speaker)
            : `Speaker ${s.speaker}`;
          return `[${(s.start ?? 0).toFixed(2)}-${(s.end ?? 0).toFixed(2)}] ${displaySpeaker}: ${(s.text || '').trim()}`;
        });
        document.getElementById('transcriptDisplayContent').textContent = lines.join('\n');
        document.getElementById('transcriptDisplayModal').style.display = 'block';
      };
    }
    const closeModal = document.getElementById('closeTranscriptModal');
    if (closeModal) {
      closeModal.onclick = function() {
        document.getElementById('transcriptDisplayModal').style.display = 'none';
      };
    }
  }

  function toggleImportSection() {
    const importSection = document.getElementById('importSection');
    if (importSection) {
      importSection.style.display = importSection.style.display === 'none' ? 'block' : 'none';
    }
  }

  function toggleDocumentInput() {
    const docSection = document.getElementById('documentInputSection');
    const textSection = document.getElementById('textInputSection');
    
    if (docSection) {
      docSection.style.display = docSection.style.display === 'none' ? 'block' : 'none';
    }
    if (textSection) {
      textSection.style.display = 'none';
    }
  }

  function toggleTextInput() {
    const docSection = document.getElementById('documentInputSection');
    const textSection = document.getElementById('textInputSection');
    
    if (textSection) {
      textSection.style.display = textSection.style.display === 'none' ? 'block' : 'none';
    }
    if (docSection) {
      docSection.style.display = 'none';
    }
  }

  async function handleBaseContextUpload(event) {
    const slot = parseInt(event.target.dataset.slot, 10);
    const file = event.target.files[0];
    
    if (!file) return;

    // Allowed extensions
    const allowedExtensions = ['.txt', '.md', '.json', '.js', '.html', '.css'];
    const fileName = file.name.toLowerCase();
    const isAllowed = allowedExtensions.some(ext => fileName.endsWith(ext));

    if (!isAllowed) {
      alert(`Unsupported file type. Allowed files: ${allowedExtensions.join(', ')}`);
      event.target.value = ''; // reset file input
      return;
    }

    try {
      const text = await file.text();
      window.baseContexts.slots[slot] = {
        name: file.name,
        content: text,
        uploadedAt: new Date().toISOString()
      };

      // Update UI
      const slotDiv = event.target.closest('.context-slot');
      slotDiv.classList.add('has-file');
      slotDiv.querySelector('.slot-header span').textContent =
        `${window.baseContexts.names[slot]} (${file.name})`;

      if (typeof showToast === 'function') {
        showToast(`Loaded base context: ${file.name}`);
      }

    } catch (error) {
      console.error('Error loading base context:', error);
      alert(`Error loading file: ${error.message}`);
    }
  }

  function clearBaseContextSlot(event) {
    const slot = parseInt(event.target.dataset.slot, 10);
    window.baseContexts.slots[slot] = null;

    const slotDiv = event.target.closest('.context-slot');
    slotDiv.classList.remove('has-file');
    slotDiv.querySelector('.slot-header span').textContent =
      window.baseContexts.names[slot];

    slotDiv.querySelector('.context-file').value = '';
  }

  async function useCurrentTranscript() {
    try {
      ensureRunsState();
  
      // Prefer using runsState and activeId
      let run = window.runsState?.runs?.find(x => x.id === window.runsState.activeId);
  
      // Fallback: Try to extract from DOM if not found
      if (!run || !run.data || !run.data.segments) {
        const transcriptElement = document.querySelector('.transcript-content') ||
                                 document.getElementById('transcript') ||
                                 document.querySelector('[data-transcript]');
        if (transcriptElement) {
          const transcriptText = transcriptElement.textContent || '';
          const lines = transcriptText.split('\n').filter(line => line.trim());
          const segments = lines.map((line, index) => {
            // Try to extract timestamps and speaker from the line
            const match = line.match(/\[(\d+\.\d+)-(\d+\.\d+)\]\s+([^:]+):(.*)/);
            if (match) {
              return {
                speaker: match[3].trim(),
                start: parseFloat(match[1]),
                end: parseFloat(match[2]),
                text: match[4].trim()
              };
            }
            // Fallback: treat as plain text
            return {
              speaker: 'Speaker',
              start: index * 10,
              end: (index + 1) * 10,
              text: line.trim()
            };
          });
          // Create synthetic runsState and currentInputData
          window.runsState = {
            runs: [{
              id: 'transcript',
              label: 'Current Transcript',
              data: { segments }
            }],
            activeId: 'transcript'
          };
          run = window.runsState.runs[0];
        }
      }
  
      if (!run || !run.data || !run.data.segments) {
        alert('Error: No input data available. Please use "Use Current Transcript" button or upload a document first.');
        return null;
      }
  
      // Use the same formatting as extractText for consistency
      currentInputData = {
        segments: run.data.segments,
        source: {
          type: 'transcript',
          name: run.label || run.id,
          processedAt: new Date().toISOString()
        }
      };
  
      updateInputSourceInfo('Transcript: ' + (run.label || run.id));
      if (typeof showToast === 'function') {
        showToast('Using current transcript as input');
      }
      return currentInputData;
    } catch (error) {
      console.error('Error using transcript:', error);
      alert('Error: ' + error.message);
      return null;
    }
  }

  async function fetchAndSetBackendTranscript(filename = null) {
    try {
      // Fetch the list of transcripts
      const resp = await fetch('http://localhost:8019/api/transcripts');
      if (!resp.ok) throw new Error('Failed to fetch transcript list');
      const transcripts = await resp.json();

      // Pick the first transcript or the one matching filename
      let transcriptObj;
      if (filename) {
        transcriptObj = transcripts.find(t => t.filename === filename);
      } else {
        transcriptObj = transcripts[0];
      }
      if (!transcriptObj) throw new Error('No transcript found in backend');

      // Convert backend format to segments
      const segments = (transcriptObj.content || []).map((seg, idx) => ({
        speaker: seg.speaker || seg.speaker_id || 'Speaker',
        start: seg.start || seg.start_time || idx * 10,
        end: seg.end || seg.end_time || (idx + 1) * 10,
        text: seg.text || seg.utterance || '',
      }));

      // Set runsState
      window.runsState = {
        runs: [{
          id: transcriptObj.filename,
          label: transcriptObj.filename,
          data: { segments }
        }],
        activeId: transcriptObj.filename
      };
      return true;
    } catch (err) {
      console.error('Error loading backend transcript:', err);
      return false;
    }
  }

  async function handleDocumentUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
      currentInputData = await UniversalInputPreprocessor.processInput(file, 'file');
      updateInputSourceInfo('Document: ' + file.name);
      if (typeof showToast === 'function') {
        showToast('Document processed successfully');
      }
    } catch (error) {
      console.error('Error processing document:', error);
      alert('Error processing document: ' + error.message);
    }
  }

  async function processTextInput() {
    const text = document.getElementById('pastedText').value;
    if (!text.trim()) {
      alert('Please paste some text first');
      return;
    }
    
    try {
      currentInputData = await UniversalInputPreprocessor.processInput(text, 'text', 'Pasted Text');
      updateInputSourceInfo('Text: Pasted Content');
      if (typeof showToast === 'function') {
        showToast('Text processed successfully');
      }
    } catch (error) {
      console.error('Error processing text:', error);
      alert('Error processing text: ' + error.message);
    }
  }

  function updateInputSourceInfo(sourceText) {
    const sourceElement = document.getElementById('currentSource');
    if (sourceElement) {
      sourceElement.textContent = sourceText;
    }
  }

async function handleChainConfigImport(event) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    const content = await file.text();
    const config = JSON.parse(content);

    console.log('Imported chain configuration:', config);

    if (!config.chain_configuration || !config.chain_configuration.order) {
      throw new Error('Invalid chain_analysis.json file. Missing `chain_configuration.order`.');
    }

    // Parse chain order and modes from the loaded config
    const chainOrder = config.chain_configuration?.order || [];
    const chainModes = config.chain_configuration?.modes_summary || {};

    // Normalize chainOrder items to framework keys (support strings or objects)
    const frameworkKeys = chainOrder.map(item => {
      if (typeof item === 'string') return item;
      if (item && (item.framework_key || item.key)) return item.framework_key || item.key;
      return null;
    }).filter(Boolean);

    // Now filter out undefined or invalid keys (only keep keys present in window.frameworks)
    const validFrameworkKeys = frameworkKeys.filter(key => key && window.frameworks && window.frameworks[key]);

    if (validFrameworkKeys.length !== frameworkKeys.length) {
      console.warn("Invalid framework keys:", frameworkKeys.filter(key => !window.frameworks || !window.frameworks[key]));
    }

    // Update the global state with validated keys and chain modes
    window.frameworkSelectionOrder = validFrameworkKeys;
    window.frameworkChainModes = chainModes || {};

    // Re-render the framework selection UI
    if (typeof setupFrameworkCheckboxes === 'function') {
      setupFrameworkCheckboxes();
    } else {
      console.error('setupFrameworkCheckboxes function not found.');
    }

    if (typeof showToast === 'function') {
      showToast(`Chain configuration loaded from ${file.name}.`);
    }

    // Reset the file input so the same file can be loaded again
    event.target.value = '';
  } catch (error) {
    console.error('Error importing chain configuration:', error);
    alert(`Error importing chain configuration: ${error.message}`);
  }
}

  async function handleAnalysisImport(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
      // Ensure JSZip is loaded
      await ensureJSZip();
      
      // Use JSZip to read the uploaded file
      const zip = await JSZip.loadAsync(file);
      
      // Extract the base name from the zip filename
      const baseName = file.name.replace(/\.zip$/, '').replace(/^legal_analysis_/, '');
      
      // Read the combined results file
      const combinedResultsFile = zip.file(new RegExp('.*_combined_results\\.json$'));
      
      if (combinedResultsFile.length === 0) {
        throw new Error('No combined results file found in the archive');
      }
      
      const combinedResultsContent = await combinedResultsFile[0].async('string');
      const combinedResults = JSON.parse(combinedResultsContent);
      
      // Read individual framework results
      const frameworkResults = {};
      const resultFiles = zip.file(new RegExp('.*_results\\.json$'));
      
      for (const file of resultFiles) {
        if (file.name.includes('combined')) continue; // Skip combined file
        
        const content = await file.async('string');
        const result = JSON.parse(content);
        
        // Extract framework key from filename
        const filename = file.name.split('/').pop();
        const frameworkKey = filename.replace(/_results\.json$/, '').replace(/^.*_/, '');
        
        frameworkResults[frameworkKey] = result;
      }
      
      // Store the imported analysis
      const analysisId = `imported_${Date.now()}`;
      window.importedAnalyses[analysisId] = {
        id: analysisId,
        name: baseName,
        combinedResults: combinedResults,
        frameworkResults: frameworkResults,
        importedAt: new Date().toISOString()
      };
      
      // Update the UI to show imported analyses
      updateImportedAnalysesUI();
      
      // Show success message
      if (typeof showToast === 'function') {
        showToast(`Successfully imported analysis: ${baseName}`);
      } else {
        alert(`Successfully imported analysis: ${baseName}`);
      }
    } catch (error) {
      console.error('Error importing analysis:', error);
      alert(`Error importing analysis: ${error.message}`);
    }
  }

  function updateImportedAnalysesUI() {
    const container = document.getElementById('importedAnalyses');
    const previousSection = document.getElementById('previousAnalysesSection');
    const previousCheckboxes = document.getElementById('previousAnalysesCheckboxes');
    
    if (Object.keys(window.importedAnalyses).length === 0) {
      if (container) {
        container.innerHTML = '<div style="color: var(--muted); font-size: 0.8rem;">No analyses imported yet</div>';
      }
      if (previousSection) {
        previousSection.style.display = 'none';
      }
      return;
    }
    
    // Show imported analyses list
    if (container) {
      container.innerHTML = '';
    }
    if (previousCheckboxes) {
      previousCheckboxes.innerHTML = '';
    }
    if (previousSection) {
      previousSection.style.display = 'block';
    }
    
    Object.values(window.importedAnalyses).forEach(analysis => {
      // Add to imported list
      if (container) {
        const analysisDiv = document.createElement('div');
        analysisDiv.className = 'imported-analysis-item';
        
        const frameworkCount = Object.keys(analysis.frameworkResults).length;
        analysisDiv.innerHTML = `
          <div style="font-weight: 600;">${analysis.name}</div>
          <div style="color: var(--muted);">${frameworkCount} frameworks • ${new Date(analysis.importedAt).toLocaleDateString()}</div>
          <button onclick="removeImportedAnalysis('${analysis.id}')" style="margin-top: 4px; font-size: 0.7rem;" class="btn small">Remove</button>
          <button onclick="toggleFrameworkSelection('${analysis.id}')" style="margin-top: 4px; font-size: 0.7rem;" class="btn small">Select Frameworks</button>
        `;
        container.appendChild(analysisDiv);
      }
      
      // Add to previous analyses checkboxes
      if (previousCheckboxes) {
        const checkboxDiv = document.createElement('div');
        checkboxDiv.className = 'framework-checkbox';
        
        const frameworkCount = Object.keys(analysis.frameworkResults).length;
        checkboxDiv.innerHTML = `
          <div style="display: flex; align-items: center;">
            <input type="checkbox" id="prev_${analysis.id}" data-analysis="${analysis.id}" />
            <label for="prev_${analysis.id}" style="margin-right: 8px;">${analysis.name} (${frameworkCount} frameworks)</label>
          </div>
          <div class="analysis-mode-selector" style="display: none; margin-left: 24px; margin-top: 4px; font-size: 0.8rem;">
            <label>Usage mode: </label>
            <select id="prev_${analysis.id}_mode" data-analysis="${analysis.id}">
              <option value="context">Use as context</option>
              <option value="comparison">Compare with current</option>
              <option value="baseline">Use as baseline</option>
            </select>
          </div>
        `;
      
        previousCheckboxes.appendChild(checkboxDiv);
        
        // Add event listeners
        const checkbox = checkboxDiv.querySelector('input');
        const modeSelector = checkboxDiv.querySelector('.analysis-mode-selector');
        
        checkbox.addEventListener('change', (e) => {
          if (e.target.checked) {
            modeSelector.style.display = 'block';
          } else {
            modeSelector.style.display = 'none';
          }
        });
      }
    });
  }

// Global function to remove imported analysis
window.removeImportedAnalysis = function(analysisId) {
  delete window.importedAnalyses[analysisId];
  updateImportedAnalysesUI();
};

// Add this function to toggle framework selection
window.toggleFrameworkSelection = function(analysisId) {
  const selector = document.getElementById(`frameworkSelector_${analysisId}`);
  if (selector) {
    selector.style.display = selector.style.display === 'none' ? 'block' : 'none';
  }
};


// Frameworks Groupped by Jurisdiction
const frameworksByJurisdiction = {};
Object.values(window.frameworks).forEach(fw => {
  const jurisdiction = fw.config?.jurisdiction || 'Other';
  if (!frameworksByJurisdiction[jurisdiction]) {
    frameworksByJurisdiction[jurisdiction] = [];
  }
  frameworksByJurisdiction[jurisdiction].push(fw);
});



// Modified buildMultiPayloads to include previous analyses
/**
 * Builds multiple analysis payloads for sequential AI processing using configured frameworks.
 * 
 * This function orchestrates the creation of analysis payloads by:
 * 1. Ensuring execution state is available (runsState)
 * 2. Loading input data from various sources (transcript, imported analysis, DOM)
 * 3. Processing and validating the input data
 * 4. Constructing sequential payloads with context chaining between frameworks
 * 5. Handling framework-specific configurations and analysis focus points
 * 
 * @example
 * // Returns object with payloads and results tracking
 * const result = buildMultiPayloads();
 * if (result) {
 *   const { payloads, allPreviousResults } = result;
 *   // Process payloads sequentially
 * }
 * 
 * @throws {Error} When no input data is available after exhaustive search
 * @returns {Object|null} Object containing payloads and results tracking, or null if no data
 * @property {Object} payloads - Framework-keyed analysis payloads for AI processing
 * @property {Object} allPreviousResults - Placeholder for tracking analysis results between frameworks
 */
function buildMultiPayloads() {
    // Ensure runsState is available before proceeding
    if (!window.runsState) {
      ensureRunsState();
    }
    
    /**
     * Attempt to initialize currentInputData from available sources if not present
     * Priority order: currentInputData -> transcript runs -> DOM transcript -> error
     */
    if (!currentInputData) {
      console.log('No currentInputData found, attempting to use current transcript or imported analysis...');
      try {
        // Find active run from execution state
        const run = window.runsState?.runs?.find(x => x.id === window.runsState.activeId);
        if (run && run.data && run.data.segments) {
          currentInputData = {
            segments: run.data.segments,
            source: {
              type: 'transcript',
              name: run.label || run.id,
              processedAt: new Date().toISOString()
            }
          };
          console.log('Successfully initialized currentInputData from transcript');
        }
      } catch (error) {
        console.error('Error initializing from transcript or imported analysis:', error);
      }
    }
    
    /**
     * Fallback: If runsState is still unavailable, attempt DOM transcript extraction
     * This serves as a last-resort data source before failing completely
     */
    if (!window.runsState || !window.runsState.runs) {
      console.error('Error: Execution state (runsState) not found.');
      
      // Search for transcript content in various DOM element selectors
      const transcriptElement = document.querySelector('.transcript-content') || 
                               document.getElementById('transcript') ||
                               document.querySelector('[data-transcript]');
      
      if (transcriptElement) {
        console.log('Found transcript in DOM, creating synthetic run');
        const transcriptText = transcriptElement.textContent || '';
        const lines = transcriptText.split('\n').filter(line => line.trim());
        
        /**
         * Parse transcript lines into structured segments
         * Attempts to extract timestamps and speaker labels with fallback formatting
         */
        const segments = lines.map((line, index) => {
          // Regex pattern: [start-end] Speaker: text
          const match = line.match(/\[(\d+\.\d+)-(\d+\.\d+)\]\s+([^:]+):(.*)/);
          if (match) {
            return {
              speaker: match[3].trim(),
              start: parseFloat(match[1]),
              end: parseFloat(match[2]),
              text: match[4].trim()
            };
          }
          // Fallback: create basic segments with line numbers as timestamps
          return {
            speaker: `Speaker`,
            start: index,
            end: index + 1,
            text: line.trim()
          };
        });
        
        // Create synthetic execution state from DOM transcript
        window.runsState = {
          runs: [{
            id: 'transcript',
            label: 'Current Transcript',
            data: { segments }
          }],
          activeId: 'transcript'
        };
        
        currentInputData = {
          segments: segments,
          source: {
            type: 'transcript',
            name: 'Current Transcript',
            processedAt: new Date().toISOString()
          }
        };
      } else {
        // Critical failure: No data sources available
        alert('Error: No input data available. Please use "Use Current Transcript" button or upload a document first.');
        return null;
      }
    }
    
    // Final validation of input data availability
    if (!currentInputData || !currentInputData.segments) {
      alert('Error: No input data available. Please use "Use Current Transcript" button or upload a document first.');
      return null;
    }
    
    /**
     * Validate active run selection and data availability
     * This ensures we have a valid execution context for analysis
     */
    const run = window.runsState.runs.find(x => x.id === window.runsState.activeId);
    if (!run && !currentInputData) {
      alert('Select an execution first.');
      return null;
    }
    
    /**
     * Input length management to prevent token limit issues
     * Large transcripts are truncated with user notification
     */
    if (currentInputData.segments && currentInputData.segments.length > 400) {
      console.warn(`Input truncated from ${currentInputData.segments.length} to 400 segments to avoid token limits.`);
      if (typeof showToast === 'function') {
        showToast(`⚠️ Input truncated to 400 segments`, 7000);
      }
    }

    /**
     * Process and format timeline data for AI consumption
     * - Limit to 400 segments maximum
     * - Normalize numerical precision
     * - Truncate text to prevent overflow
     * - Preserve source metadata
     */
    const segs = (currentInputData.segments || []).slice(0, 400);
    const timeline = segs.map((s, i) => ({
      i: i + 1,                    // Segment index (1-based)
      spk: s.speaker,              // Speaker identifier
      start: +(s.start || 0).toFixed(2),  // Normalized start time
      end: +(s.end || 0).toFixed(2),      // Normalized end time
      text: (s.text || '').trim().slice(0, 260),  // Truncated text content
      source: s.source || currentInputData.source  // Data provenance
    }));

    /**
     * Generate clean transcript format for AI processing
     * Format: [start-end] Speaker: text
     * This provides human-readable context alongside structured data
     */
    const cleanTranscript = timeline.map(t => {
      const speakerLabel = t.spk || 'Speaker';
      return `[${t.start}-${t.end}] ${speakerLabel}: ${t.text}`;
    }).join('\n');
    
    // Retrieve user-defined custom prompt for analysis customization
    const userCustomPrompt = (document.getElementById('multiPrompt').value || '').trim();

    /**
     * Initialize payload and result tracking structures
     * payloads: Framework-specific analysis requests
     * allPreviousResults: Cross-framework context sharing container
     */
    const payloads = {};
    const allPreviousResults = {};
    
    
    
    
    /**
     * Iterate through framework chain to build sequential analysis payloads
     * Each framework can leverage previous analyses based on chaining mode
     */
(window.frameworkSelectionOrder || []).forEach((key, index) => {
      const fw = window.frameworks[key];
      
      // Skip invalid framework configurations
      if (!fw) {
        console.warn(`Framework ${key} not found`);
        return;
      }
      
      /**
       * Framework prompt selection priority:
       * 1. Generated prompt (dynamic)
       * 2. Default prompt (static)
       * 3. User custom prompt (manual)
       */
      let frameworkPrompt = fw.generatedPrompt || fw.defaultPrompt || userCustomPrompt;
      
      /**
       * Extract analysis focus points from framework configuration
       * These guide the AI to specific aspects of the legal framework
       */
      let focusPoints = '';
      if (fw.config && fw.config.analysis_focus) {
        focusPoints = '\n\nFocus on these specific aspects:\n';
        for (const [aspect, keywords] of Object.entries(fw.config.analysis_focus)) {
          focusPoints += `- ${aspect}: "${keywords}"\n`;
        }
      }
      
      /**
       * Determine context chaining mode for this framework
       * Modes: 'none' (isolated), 'last' (previous only), 'all' (cumulative)
       */
      const mode = frameworkChainModes[key] || 'none';
      
      /**
       * Build previous analyses context for frameworks that support chaining
       * This enables sequential analysis building where each framework
       * can consider insights from previous analyses
       */
      let previousAnalysesContext = '';
      if (index > 0 && mode !== 'none') {
        if (mode === 'last') {
          // Single previous framework context
          const prevKey = frameworkChain[index - 1];
          previousAnalysesContext = `\n\nPREVIOUS ANALYSIS RESULTS (from ${window.frameworks[prevKey]?.name || prevKey}):\n${JSON.stringify(allPreviousResults[prevKey], null, 2)}`;
        } else if (mode === 'all') {
          // Cumulative context from all previous frameworks
          previousAnalysesContext = '\n\nPREVIOUS ANALYSES RESULTS:\n';
          for (let i = 0; i < index; i++) {
            const prevKey = frameworkChain[i];
            previousAnalysesContext += `\n--- ${window.frameworks[prevKey]?.name || prevKey} ---\n${JSON.stringify(allPreviousResults[prevKey], null, 2)}\n`;
          }
        }
        
        // Instruction for integrating previous analyses
        previousAnalysesContext += `\n\nINSTRUCTION: Consider these previous analysis results in your assessment.`;
      }

      /**
       * Input source metadata for data provenance tracking
       * Helps AI understand the origin and recency of the input data
       */
      const inputSourceInfo = `
INPUT SOURCE INFORMATION:
- Type: ${currentInputData.source.type}
- Name: ${currentInputData.source.name}
- Processed: ${currentInputData.source.processedAt || 'N/A'}
`;

      /**
       * Base context assembly from configured context slots
       * Provides foundational legal context that applies across all frameworks
       */
      let baseContextSection = '';
      window.baseContexts.slots.forEach((context, index) => {
        if (context) {
          baseContextSection += `\n--- BASE CONTEXT ${index + 1}: ${context.name} ---\n${context.content}\n`;
        }
      });

      /**
       * Final prompt construction with layered context:
       * 1. Base legal context
       * 2. Framework-specific instructions
       * 3. Analysis focus points
       * 4. Previous analyses context (if chaining enabled)
       */
      const promptWithContext = `${baseContextSection}\n\nFRAMEWORK INSTRUCTION:\n${frameworkPrompt}`;

      /**
       * Construct AI payload with structured analysis request
       * Includes system role definition, user context, and processing parameters
       */
      payloads[key] = {
        model: (document.getElementById('aiModel') && document.getElementById('aiModel').value) || 'deepseek-v4-pro',
        stream: true,
        messages: [
          {
            role: 'system',
            content: `You are a legal compliance analyst specialized in ${fw.name}. Always reference specific articles and sections of the legal framework in your analysis.`
          },
          {
            role: 'user',
            content: `INPUT SOURCE:\n${inputSourceInfo}\n\nCONTENT:\n${cleanTranscript}\n\nTIMELINE JSON:\n${JSON.stringify(timeline, null, 2)}\n\nINSTRUCTION:\n${promptWithContext}${focusPoints}${previousAnalysesContext}\n\nProvide a comprehensive analysis according to the framework guidelines.`
          }
        ],
        temperature: 0.15,  // Low temperature for consistent legal analysis
        frameworkMode: mode  // Chaining mode for result integration
      };
      
      // Initialize result placeholder for this framework in the chain
      allPreviousResults[key] = { status: 'pending' };
    });

    // Update UI with generated payloads for debugging and verification
    document.getElementById('multiPayloadsPre').textContent = JSON.stringify(payloads, null, 2);
    
    return { payloads, allPreviousResults };
  }

    // PDF generation utilities
  function ensurePDFLibraries() {
    return new Promise(async (resolve, reject) => {
      if (window.jspdf && window.html2canvas) {
        resolve();
        return;
      }

      try {
        // Load html2canvas
        if (!window.html2canvas) {
          await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
          });
        }

        // Load jsPDF
        if (!window.jspdf) {
          await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
          });
        }

        resolve();
      } catch (error) {
        reject(new Error('Failed to load PDF libraries: ' + error.message));
      }
    });
  }

  async function sendMultiPayloads() {
    const endpoint = getAiEndpoint();
    if (!endpoint) return alert('Define endpoint');

    const { payloads, allPreviousResults } = buildMultiPayloads();
    if (!payloads) return;

    const outputElement = document.getElementById('multiOutput');
    outputElement.innerHTML = '';
    
    // Show the AI reasoning container
    document.getElementById('aiReasoningContainer').style.display = 'block';
    document.getElementById('ai-reasoning-output').textContent = 'Starting analysis...';
    
    const results = {};
    let frameworksProcessed = 0;
    const totalFrameworks = (window.frameworkSelectionOrder || []).length;

    // Create a hidden element to store the final results for export
    const hiddenResults = document.createElement('div');
    hiddenResults.id = 'hiddenResultsJson';
    hiddenResults.style.display = 'none';
    outputElement.appendChild(hiddenResults);
    
    // Process frameworks sequentially in chain order
    for (const key of (window.frameworkSelectionOrder || [])) {
      try {
        frameworksProcessed++;
        const framework = window.frameworks[key];
        
        // Create a section for this framework
        const frameworkDiv = document.createElement('div');
        frameworkDiv.className = 'framework-section';
        frameworkDiv.innerHTML = `
          <div class="framework-title">${framework.name}</div>
          <div class="stream-header">
            <div><span class="stream-pulse"></span> Processing</div>
            <div class="stream-status">Framework ${frameworksProcessed}/${totalFrameworks}</div>
          </div>
          <div class="stream-content"></div>
        `;
        
        outputElement.appendChild(frameworkDiv);
        
        const contentElement = frameworkDiv.querySelector('.stream-content');
        const headerElement = frameworkDiv.querySelector('.stream-header');
        
        // Create a copy of the payload
        const payload = payloads[key];
        
        // Log the payload for debugging
        console.log(`Sending payload for ${framework.name}:`, payload);
        
        try {
          // Correctly format the request to match the API expectations
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          
          if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`API returned ${response.status}: ${errorText}`);
          }
          
          // Handle streaming response
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let accumulatedContent = '';
          let fullResponse = '';
          let isReasoningComplete = false;
          let finalAnalysis = '';
          let reasoningContent = '';
          
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            
            // Process the SSE format (data: ...)
            const lines = chunk.split('\n').filter(line => line.trim().startsWith('data:'));
            
            for (const line of lines) {
              const jsonStr = line.substring(5).trim();
              if (jsonStr === '[DONE]') continue;
              
              try {
                const data = JSON.parse(jsonStr);
                
                // Handle errors from the API
                if (data.error) {
                  throw new Error(`AI Error: ${data.error.message}`);
                }
                
                // Extract content from different API formats
                let content = '';
                if (data.choices && data.choices[0]) {
                  // OpenAI style API response
                  if (data.choices[0].delta) {
                    content = data.choices[0].delta.content || '';
                  } else if (data.choices[0].message) {
                    content = data.choices[0].message.content || '';
                  }
                } else if (data.response) {
                  // Anthropic or other API style
                  content = data.response;
                }
                
                if (content) {
                  fullResponse += content;
                  
                  // Update the AI reasoning output
                  reasoningContent += content;
                  document.getElementById('ai-reasoning-output').textContent = reasoningContent;
                  document.getElementById('ai-reasoning-output').scrollTop = document.getElementById('ai-reasoning-output').scrollHeight;
                  
                  // Try to detect when reasoning ends and analysis begins
                  if (!isReasoningComplete && (
                    content.includes("Now, let me parse") ||
                    content.includes("Based on this analysis") ||
                    content.includes("From the transcript") ||
                    content.includes("Looking at the evidence") ||
                    content.includes("Here's my final analysis") ||
                    content.includes("In conclusion")
                  )) {
                    isReasoningComplete = true;
                    
                    // Wrap the reasoning section
                    accumulatedContent = `<div class="reasoning-section">${accumulatedContent}</div>`;
                  }
                  
                  // Add to the appropriate section
                  if (isReasoningComplete) {
                    finalAnalysis += content;
                  } else {
                    accumulatedContent += content;
                  }
                  
                  // Update the display
                  let displayContent = accumulatedContent;
                  if (finalAnalysis) {
                    displayContent += `<div class="analysis-section">${finalAnalysis}</div>`;
                  }
                  
                  contentElement.innerHTML = displayContent;
                  
                  // Auto-scroll to keep the latest content visible
                  contentElement.scrollTop = contentElement.scrollHeight;
                  outputElement.scrollTop = outputElement.scrollHeight;
                }
              } catch (e) {
                console.warn('Could not parse stream chunk, continuing...', jsonStr);
              }
            }
          }
          
          // After streaming is complete, ensure all content is properly wrapped
          if (!isReasoningComplete && accumulatedContent) {
            // If we never detected the end of reasoning, wrap what we have
            accumulatedContent = `<div class="reasoning-section">${accumulatedContent}</div>`;
          }
          
          if (finalAnalysis) {
            finalAnalysis = `<div class="analysis-section">${finalAnalysis}</div>`;
          }
          
          contentElement.innerHTML = accumulatedContent + finalAnalysis;
          
          // Update the header to show completion
          headerElement.innerHTML = `
            <div><span class="stream-complete">✓</span> Analysis Complete</div>
            <div class="stream-status">Framework ${frameworksProcessed}/${totalFrameworks}</div>
          `;
          
          // Store result - we want the raw accumulated content for export
          results[key] = {
            framework: framework.name,
            analysis: fullResponse,
            mode: payload.frameworkMode
          };
          
          // Update the allPreviousResults for chaining
          allPreviousResults[key] = results[key];
          
        } catch (err) {
          console.error(`Error during analysis for ${framework.name}:`, err);
          headerElement.innerHTML = `
            <div><span class="stream-error">✗</span> Error</div>
            <div class="stream-status">Framework ${frameworksProcessed}/${totalFrameworks}</div>
          `;
          contentElement.innerHTML = `<div style="color:red;">Error: ${err.message}</div>`;
          
          // Store error result
          results[key] = {
            framework: framework.name,
            error: err.message,
            mode: payload.frameworkMode
          };
          
          // Update the allPreviousResults to indicate failure
          allPreviousResults[key] = results[key];
        }
      } catch (err) {
          console.error(`Unexpected error processing framework ${key}:`, err);
        }
      }
      
      // Store the final results in the hidden element for export
      hiddenResults.textContent = JSON.stringify(results, null, 2);
      
      // After all frameworks are processed, generate combined report
      if (totalFrameworks > 1) {
        try {
          await generateCombinedReport(results);
        } catch (error) {
          console.error('Failed to generate combined report:', error);
          // Optionally show error in UI
          document.getElementById('combinedReportSection').style.display = 'block';
          document.getElementById('combinedReport').textContent = 
            `Error generating combined report: ${error.message}`;
        }
      }
      
      // Add final summary after all frameworks are processed
      const summaryDiv = document.createElement('div');
      summaryDiv.className = 'framework-section';
      summaryDiv.innerHTML = `
        <div class="stream-header">
          <div><span class="stream-complete">✓</span> All Analyses Complete</div>
          <div class="stream-status">${totalFrameworks} frameworks processed</div>
        </div>
      `;
      outputElement.appendChild(summaryDiv);
      
      // Show toast when complete
      if (typeof showToast === 'function') {
        showToast(`Analysis complete for ${totalFrameworks} frameworks`);
      }
  }

  // ====== ENHANCEMENTS FOR BETTER BASE FILE INTEGRATION ======

  // Add this function to extract violations from the master violations file
  function extractViolationsFromBaseContexts() {
    const violations = {
      byJurisdiction: {},
      bySeverity: { high: [], moderate: [], low: [] },
      totalCount: 0,
      categories: {}
    };
    
    // Look for master violations in base contexts
    if (window.baseContexts && window.baseContexts.slots) {
      for (let i = 0; i < window.baseContexts.slots.length; i++) {
        const slot = window.baseContexts.slots[i];
        if (slot && slot.name && slot.name.toLowerCase().includes('violation')) {
          console.log('Found violations in slot', i, slot.name);
          return parseViolationsFromContent(slot.content);
        }
      }
    }
    
    return violations;
  }

  // Add this function to parse violations from markdown/content
  function parseViolationsFromContent(content) {
    const violations = {
      byJurisdiction: {},
      bySeverity: { high: [], moderate: [], low: [] },
      totalCount: 0,
      categories: {
        international: [],
        constitutional: [],
        criminal: [],
        consumer: [],
        procedural: [],
        human_rights: []
      }
    };
    
    if (!content) return violations;
    const lines = content.split('\n');
    let currentJurisdiction = null;
    
    lines.forEach(line => {
      line = line.trim();
      
      // Detect jurisdiction headers
      if (line.startsWith('## ') && !line.includes('Table of Contents')) {
        currentJurisdiction = line.replace('## ', '').trim();
        if (!violations.byJurisdiction[currentJurisdiction]) {
          violations.byJurisdiction[currentJurisdiction] = [];
        }
      }
      
      // Detect violation items (numbered or bulleted)
      if ((line.match(/^\d+\./) || line.startsWith('-')) && currentJurisdiction) {
        const cleanLine = line.replace(/^\d+\.\s*/, '').replace(/^-\s*/, '');
        const violation = {
          text: cleanLine,
          jurisdiction: currentJurisdiction,
          category: categorizeViolation(cleanLine, currentJurisdiction),
          full_citation: null,
          evidence_references: [],
          evidence_count: 0
        };
        
        // Attempt to add an initial full citation if available
        if (typeof getFullCitation === 'function') {
          violation.full_citation = getFullCitation(cleanLine, currentJurisdiction);
        }
        
        violations.byJurisdiction[currentJurisdiction].push(violation);
        violations.totalCount++;
        
        // Categorize by severity
        const severity = assessViolationSeverity(cleanLine);
        violations.bySeverity[severity].push(violation);
        
        // Add to category
        if (violation.category) {
          violations.categories[violation.category].push(violation);
        }
      }
    });
    
    return violations;
  }

  // Add this function to categorize violations
  function categorizeViolation(violationText, jurisdiction) {
    const text = (violationText || '').toLowerCase();
    const jur = (jurisdiction || '').toLowerCase();
    
    if (text.includes('montreal') || text.includes('tokyo') || text.includes('iata') || 
        text.includes('icao') || jur.includes('international')) {
      return 'international';
    }
    
    if (text.includes('constitution') || text.includes('fundamental') || 
        text.includes('due process') || jur.includes('constitution')) {
      return 'constitutional';
    }
    
    if (text.includes('penal') || text.includes('criminal') || text.includes('false testimony') || 
        text.includes('abuse of authority') || jur.includes('penal')) {
      return 'criminal';
    }
    
    if (text.includes('consumer') || text.includes('cdc') || text.includes('anac') || 
        text.includes('good faith') || text.includes('information')) {
      return 'consumer';
    }
    
    if (text.includes('procedural') || text.includes('documentation') || 
        text.includes('written notice') || text.includes('carta de desembarque')) {
      return 'procedural';
    }
    
    if (text.includes('human rights') || text.includes('uncat') || 
        text.includes('degrading') || text.includes('humiliation')) {
      return 'human_rights';
    }
    
    return null;
  }

  // Add this function to assess violation severity
  function assessViolationSeverity(violationText) {
    const text = (violationText || '').toLowerCase();
    
    // High severity indicators
    if (text.includes('criminal') || text.includes('penal') || 
        text.includes('constitution') || text.includes('fundamental') ||
        text.includes('false testimony') || text.includes('abuse of authority') ||
        text.includes('degrading treatment') || text.includes('humiliation')) {
      return 'high';
    }
    
    // Moderate severity indicators
    if (text.includes('consumer') || text.includes('violation') || 
        text.includes('breach') || text.includes('liability') ||
        text.includes('montreal') || text.includes('international')) {
      return 'moderate';
    }
    
    return 'low';
  }

// REPLACE the existing extractPassengerContext function with this enhanced version:
function extractPassengerContext() {
  const context = {
    personal: {
      name: "Leandro Disconzi",
      nationality: "Brazilian",
      family_situation: "Divorced, traveling to visit daughter",
      emotional_state: "Extremadamente cansado, estresado (extremely tired, stressed)"
    },
    professional: {
      background: "Aviation professional with knowledge of international aviation law",
      expertise: "Understanding of Montreal Convention, Tokyo Convention, IATA regulations"
    },
    incident_timeline: [
      "July 5, 2024 - Multiple incidents throughout day",
      "12:56: Initial confrontation with LATAM Pilot Ruiz (STG_1)",
      "13:30: Interaction with LATAM stewardess, forced removal threat (STG_5)", 
      "15:50: Extended confrontation with security officer Joaquin Barraza (STG_13)",
      "Total duration: 18+ hours of airport detention/delay"
    ],
    emotional_impact: [
      "Public humiliation and demeaning treatment by officials",
      "Psychological coercion and intimidation",
      "Forced physical removal from aircraft",
      "Systematic denial of due process rights",
      "Documented psychological stress requiring legal claim for moral damages"
    ],
    key_facts: [
      "Brazilian citizen subjected to coordinated abuse by Chilean authorities",
      "Multiple false accusations (physical aggression, entering aircraft by force)",
      "PDI confirmed accusations were 'desprovadas' (unfounded)",
      "Systematic obstruction of evidence access (CCTV denial)",
      "Strategic coordination between LATAM, DGAC, and PDI to avoid responsibility"
    ]
  };

  // Also attempt to extract from base contexts if available
  if (window.baseContexts && window.baseContexts.slots) {
    for (let i = 0; i < window.baseContexts.slots.length; i++) {
      const slot = window.baseContexts.slots[i];
      if (slot && slot.name) {
        const slotName = slot.name.toLowerCase();
        if (slotName.includes('narrative') || slotName.includes('passenger') || 
            slotName.includes('context') || slotName.includes('background')) {
          console.log('Found passenger context in slot:', slot.name);
          const parsed = parsePassengerContext(slot.content);
          // Merge with default context
          Object.assign(context, parsed);
        }
      }
    }
  }
  
  return context;
}

  // Add this function to parse passenger context
  function parsePassengerContext(content) {
    const context = {
      personal: {},
      professional: {},
      incident_timeline: [],
      emotional_impact: [],
      key_facts: []
    };
    
    if (!content) return context;
    const lines = content.split('\n');
    let currentSection = null;
    
    lines.forEach(line => {
      line = line.trim();
      
      // Detect sections
      if (line.startsWith('## ')) {
        const section = line.replace('## ', '').toLowerCase();
        if (section.includes('personal')) currentSection = 'personal';
        else if (section.includes('professional')) currentSection = 'professional';
        else if (section.includes('timeline') || section.includes('incident')) currentSection = 'timeline';
        else if (section.includes('emotional') || section.includes('impact')) currentSection = 'emotional';
        else currentSection = null;
      }
      
      // Parse content based on section
      if (currentSection && line && !line.startsWith('#') && !line.startsWith('##')) {
        if (currentSection === 'personal') {
          if (line.includes('divorce') || line.includes('daughter') || line.includes('family')) {
            context.personal.family_situation = line;
            context.key_facts.push(line);
          }
        } else if (currentSection === 'professional') {
          if (line.includes('aviation') || line.includes('experience') || line.includes('knowledge')) {
            context.professional.background = line;
            context.key_facts.push(line);
          }
        } else if (currentSection === 'timeline') {
          if (line.includes('hour') || line.includes('delay') || line.includes('duration')) {
            context.incident_timeline.push(line);
            context.key_facts.push(line);
          }
        } else if (currentSection === 'emotional') {
          if (line.includes('distress') || line.includes('humiliation') || line.includes('trauma')) {
            context.emotional_impact.push(line);
            context.key_facts.push(line);
          }
        }
      }
    });
    
    return context;
  }

  // ====== ENHANCED COMBINED REPORT GENERATION ======

  // Replace the existing generateCombinedReport function with this enhanced version
  async function generateCombinedReport(results) {
    const endpoint = getAiEndpoint();
    if (!endpoint) return;
    
    try {
      // Show loading state for combined report
      document.getElementById('combinedReportSection').style.display = 'block';
      document.getElementById('combinedReport').textContent = 'Generating enhanced combined analysis...';
      
      // Extract violations and passenger context from base files
      let violations = extractViolationsFromBaseContexts();
      const passengerContext = extractPassengerContext();

      // Enhance citations and link to transcript evidence
      if (typeof enhanceViolationCitations === 'function') {
        violations = enhanceViolationCitations(violations);
      }
      if (typeof linkViolationsToEvidence === 'function') {
        violations = linkViolationsToEvidence(violations);
      }
      const evidenceLinkedViolations = violations;

      // Prepare the enhanced combined analysis prompt
      const combinedPrompt = `
CRITICAL REQUIREMENTS FOR THIS SYNTHESIS:
1. The ENTIRE report must be in ENGLISH only
2. MUST integrate specific violations from the Master Violations file
3. MUST explicitly link passenger context to legal principles
4. MUST refine systemic risk conclusion to include full spectrum of legal risks
5. MUST include a brief methodology note about the chain analysis approach

ANALYTICAL METHODOLOGY:
This analysis was performed using a chain of 14 legal frameworks, where:
- Later frameworks incorporate findings from previous ones ("last" mode)
- Most frameworks use cumulative results from all previous ("all" mode)
- This creates a multi-layered, progressively informed legal assessment

BASE FILES INTEGRATION:

1. MASTER VIOLATIONS CATALOG (${violations.totalCount} violations):
${generateViolationsSummary(violations)}

2. PASSENGER CONTEXT KEY FACTS:
${generatePassengerContextSummary(passengerContext)}

ANALYSES TO SYNTHESIZE (14 frameworks):
${JSON.stringify(results, null, 2)}

SPECIFIC SYNTHESIS INSTRUCTIONS:

1. VIOLATION CATALOG SECTION:
   - Create a table or bulleted list of key violations by jurisdiction
   - Reference specific articles/sections (e.g., "Montreal Convention Art. 19/22", "Brazilian CDC Art. 6, III")
   - Include violations from: International treaties, Brazilian law, Chilean law, Human rights frameworks

2. CONTEXT-TO-LAW LINKAGE:
   - Explicitly connect passenger's family situation (divorce, visiting daughter) to "moral damages" under Montreal Convention
   - Link passenger's aviation expertise to the "procedural unfairness" analysis
   - Connect 18+ hour delay and humiliation to "degrading treatment" under UNCAT
   - Use these personal facts to humanize the legal arguments

3. REFINED SYSTEMIC RISK CONCLUSION:
   The systemic risk is NOT just procedural. It involves:
   - CRIMINAL RISK: Coordinated false testimony, abuse of authority (Chilean Penal Code)
   - CONSTITUTIONAL RISK: State violation of fundamental rights (Chilean Constitution)
   - MULTI-JURISDICTIONAL REGULATORY RISK: Concurrent violations in Chile (DGAC) and Brazil (ANAC/CDC)
   - HUMAN RIGHTS RISK: Potential degrading treatment (UNCAT)
   - PROCEDURAL REDRESS GAP: Strong enforcement powers but weak, fragmented redress mechanisms

4. ACTIONABLE NEXT STEPS:
   - Recommend producing a "Legal Case Synthesis Memo" that merges framework analysis with specific violations
   - Suggest submission targets: courts, regulators (ANAC, JAC), human rights bodies
   - Outline potential legal strategies based on the multi-jurisdictional findings

OUTPUT FORMAT:
Provide a comprehensive report with these sections:
1. EXECUTIVE SUMMARY (ENGLISH)
2. METHODOLOGY NOTE (brief explanation of chain analysis approach)
3. CROSS-FRAMEWORK ANALYSIS (synthesize patterns and contradictions)
4. VIOLATION CATALOG (jurisdiction-by-jurisdiction, with specific articles)
5. CONTEXTUAL ANALYSIS (explicit links between passenger facts and legal principles)
6. SYSTEMIC RISK ASSESSMENT (expanded to include criminal, constitutional, multi-jurisdictional risks)
7. INTEGRATED RECOMMENDATIONS (actionable next steps for litigation/complaints)
8. FINAL CONCLUSION & SEVERITY RATING
`;

      const payload = {
        model: (document.getElementById('aiModel') && document.getElementById('aiModel').value) || 'deepseek-v4-pro',
        stream: false,
        messages: [
          {
            role: 'system',
            content: 'You are a senior legal analyst specializing in synthesizing multi-framework analyses into actionable legal documents. You excel at connecting specific facts to legal principles and creating comprehensive, actionable reports.'
          },
          {
            role: 'user',
            content: combinedPrompt
          }
        ],
        temperature: 0.1
      };
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      
      const data = await response.json();
      const combinedAnalysis = data.choices?.[0]?.message?.content || data.content || 'Unable to generate combined report';
      
      // Display the enhanced combined report
      document.getElementById('combinedReport').textContent = combinedAnalysis;
      
      // Store the combined report in the results
      const hiddenResults = document.getElementById('hiddenResultsJson');
      if (hiddenResults) {
        try {
          let currentResults = {};
          if (hiddenResults.textContent && hiddenResults.textContent.trim() !== '') {
            currentResults = JSON.parse(hiddenResults.textContent);
          }
          
          // Add enhanced metadata
          currentResults.enhanced_combined = {
            analysis: combinedAnalysis,
            violations_summary: violations,
            passenger_context: passengerContext,
            generated_at: new Date().toISOString(),
            framework_count: Object.keys(results).length
          };
          
          // Update the hidden element
          hiddenResults.textContent = JSON.stringify(currentResults, null, 2);
        } catch (parseError) {
          console.error('Error parsing hidden results:', parseError);
          const newResults = { enhanced_combined: combinedAnalysis };
          hiddenResults.textContent = JSON.stringify(newResults, null, 2);
        }
      }
      
      // Show success message
      if (typeof showToast === 'function') {
        showToast('✓ Enhanced combined report generated with violations integration!');
      }
      
    } catch (error) {
      console.error('Error generating enhanced combined report:', error);
      document.getElementById('combinedReport').textContent = `Error generating enhanced combined report: ${error.message}`;
    }
  }

  // Add helper functions for generating summaries
  function generateViolationsSummary(violations) {
    let summary = `Total violations found: ${violations.totalCount}\n\n`;
    
    // By jurisdiction
    summary += 'BY JURISDICTION:\n';
    for (const [jurisdiction, items] of Object.entries(violations.byJurisdiction)) {
      summary += `- ${jurisdiction}: ${items.length} violations\n`;
      if (items.length <= 5) {
        items.forEach((item, idx) => {
          summary += `  ${idx + 1}. ${item.text}\n`;
        });
      }
    }
    
    // By severity
    summary += '\nBY SEVERITY:\n';
    summary += `- High: ${violations.bySeverity.high.length} violations\n`;
    summary += `- Moderate: ${violations.bySeverity.moderate.length} violations\n`;
    summary += `- Low: ${violations.bySeverity.low.length} violations\n`;
    
    // By category
    summary += '\nBY CATEGORY:\n';
    for (const [category, items] of Object.entries(violations.categories)) {
      if (items.length > 0) {
        summary += `- ${category.toUpperCase()}: ${items.length} violations\n`;
      }
    }
    
    return summary;
  }

  function generatePassengerContextSummary(context) {
    let summary = '';
    
    if (context.key_facts && context.key_facts.length > 0) {
      summary = 'KEY CONTEXTUAL FACTS:\n';
      context.key_facts.forEach((fact, idx) => {
        summary += `${idx + 1}. ${fact}\n`;
      });
    }
    
    if (context.personal.family_situation) {
      summary += `\nFAMILY SITUATION: ${context.personal.family_situation}\n`;
    }
    
    if (context.professional.background) {
      summary += `\nPROFESSIONAL BACKGROUND: ${context.professional.background}\n`;
    }
    
    if (context.incident_timeline.length > 0) {
      summary += '\nINCIDENT TIMELINE HIGHLIGHTS:\n';
      context.incident_timeline.slice(0, 3).forEach((timeline, idx) => {
        summary += `${idx + 1}. ${timeline}\n`;
      });
    }
    
    if (context.emotional_impact.length > 0) {
      summary += '\nEMOTIONAL IMPACT:\n';
      context.emotional_impact.slice(0, 3).forEach((impact, idx) => {
        summary += `${idx + 1}. ${impact}\n`;
      });
    }
    
    return summary || 'No specific passenger context found in base files.';
  }

  // ====== VIOLATION CITATION & EVIDENCE ENHANCEMENTS ======

  // Map violations to canonical citations and append full_citation
  function enhanceViolationCitations(violations) {
    if (!violations || !violations.byJurisdiction) return violations;

    const citationMap = {
      // Chilean Law
      'falso testimonio': 'Chilean Penal Code Art. 210',
      'prevaricación': 'Chilean Penal Code Art. 223',
      'calumnia': 'Chilean Penal Code Art. 412',
      'coacción': 'Chilean Penal Code Art. 141',
      'amenazas': 'Chilean Penal Code Art. 296',
      // Brazilian Law
      'consumer protection': 'Brazilian CDC Art. 6, III',
      'good faith violation': 'Brazilian CDC Art. 4, III',
      'abusive constraint': 'Brazilian CDC Art. 42',
      'service liability': 'Brazilian CDC Art. 14',
      // International Law
      'montreal convention': 'Montreal Convention 1999 Art. 19/22',
      'tokyo convention': 'Tokyo Convention 1963 Art. 9(1)',
      'uncat degrading': 'UNCAT Art. 16',
      'human rights': 'American Convention on Human Rights Art. 5'
    };

    for (const [jurisdiction, items] of Object.entries(violations.byJurisdiction)) {
      violations.byJurisdiction[jurisdiction] = items.map(item => {
        let enhancedText = item.text;

        for (const [keyword, citation] of Object.entries(citationMap)) {
          if (item.text.toLowerCase().includes(keyword.toLowerCase())) {
            // Append citation only if not already present
            if (!enhancedText.includes('[' + citation + ']')) {
              enhancedText = `${item.text} [${citation}]`;
            }
            item.full_citation = citation;
            break;
          }
        }

        return {
          ...item,
          text: enhancedText,
          full_citation: item.full_citation || getFullCitation(item.text, jurisdiction)
        };
      });
    }

    return violations;
  }

  function getFullCitation(violationText, jurisdiction) {
    const citations = {
      'Chilean Penal Code': 'Decreto Ley No. 1.000 de 1975',
      'Brazilian CDC': 'Código de Defesa do Consumidor (Lei No. 8.078/1990)',
      'Montreal Convention': 'Convention for the Unification of Certain Rules for International Carriage by Air (1999)',
      'Tokyo Convention': 'Convention on Offences and Certain Other Acts Committed on Board Aircraft (1963)',
      'UNCAT': 'United Nations Convention Against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment',
      'ANAC Resolution 400': 'RESOLUÇÃO ANAC Nº 400, DE 13 DE DEZEMBRO DE 2016'
    };

    // Try direct jurisdiction lookup
    if (citations[jurisdiction]) return citations[jurisdiction];

    // Otherwise do some fuzzy mapping
    const lower = (violationText || '').toLowerCase();
    if (lower.includes('chilean') || lower.includes('pdi') || lower.includes('dgac')) return citations['Chilean Penal Code'];
    if (lower.includes('brazil') || lower.includes('cdc') || lower.includes('anac')) return citations['Brazilian CDC'];
    if (lower.includes('montreal')) return citations['Montreal Convention'];
    if (lower.includes('tokyo')) return citations['Tokyo Convention'];
    if (lower.includes('uncat') || lower.includes('degrading')) return citations['UNCAT'];

    return jurisdiction || 'Unknown citation source';
  }

  // Link violations to transcript evidence and segments
  function linkViolationsToEvidence(violations) {
    if (!violations || !violations.byJurisdiction) return violations;

    const evidenceMap = {
      'forced removal': { segment: 'STG_1:12-15', timestamp: '12:56-13:05' },
      'threat of force': { segment: 'STG_1:18', timestamp: '13:08' },
      'no written documentation': { segment: 'STG_1:22', timestamp: '13:12' },
      'refusal of written explanation': { segment: 'STG_5:4-7', timestamp: '13:30-13:35' },
      'cctv evidence denial': { segment: 'STG_5:15', timestamp: '13:42' },
      'supervisor escalation blocked': { segment: 'STG_5:28', timestamp: '14:05' },
      'systematic coordination': { segment: 'STG_13:8-12', timestamp: '15:50-15:55' },
      'strategic evidence hiding': { segment: 'STG_13:22', timestamp: '16:10' },
      'false accusations disproven': { segment: 'STG_13:30', timestamp: '16:25' }
    };

    for (const [jurisdiction, items] of Object.entries(violations.byJurisdiction)) {
      violations.byJurisdiction[jurisdiction] = items.map(item => {
        const evidence = [];
        for (const [keyword, ev] of Object.entries(evidenceMap)) {
          if (item.text.toLowerCase().includes(keyword.toLowerCase())) {
            evidence.push({
              keyword,
              segment: ev.segment,
              timestamp: ev.timestamp,
              transcript_source: getTranscriptSource(ev.segment)
            });
          }
        }

        return {
          ...item,
          evidence_references: evidence,
          evidence_count: evidence.length
        };
      });
    }

    return violations;
  }

  function getTranscriptSource(segment) {
    if (segment.includes('STG_1')) return 'Initial confrontation with LATAM Pilot Ruiz (29 segments)';
    if (segment.includes('STG_5')) return 'Interaction with LATAM stewardess (35 segments)';
    if (segment.includes('STG_13')) return 'Extended confrontation with security officer (unknown segments)';
    return 'Multiple transcript sources';
  }

  // ====== ENHANCED PDF REPORT GENERATION ======

  // Add this function to generate enhanced PDF reports
  async function generateEnhancedPDFReport(frameworkKey, framework, analysisContent, violations, passengerContext) {
    await ensurePDFLibraries();
    
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    
    // Enhanced document properties
    doc.setProperties({
      title: `Enhanced Legal Analysis - ${framework.name}`,
      subject: `Analysis with violations integration for ${framework.name}`,
      author: 'Multi-Framework Legal Analysis System',
      keywords: 'legal, analysis, compliance, violations, framework',
      creator: 'Enhanced Legal Analysis Module'
    });

    let yPosition = 20;
    const pageHeight = doc.internal.pageSize.height;
    const margin = 20;
    const maxWidth = 170;

    // Title Page with enhanced information
    doc.setFontSize(20);
    doc.setFont('helvetica', 'bold');
    doc.text('ENHANCED LEGAL ANALYSIS REPORT', margin, yPosition);
    
    yPosition += 10;
    doc.setFontSize(16);
    doc.setFont('helvetica', 'normal');
    doc.text(framework.name, margin, yPosition);
    
    yPosition += 10;
    doc.setFontSize(12);
    doc.text(`Generated: ${new Date().toLocaleString()}`, margin, yPosition);
    
    yPosition += 8;
    doc.text(`Framework: ${framework.key}`, margin, yPosition);
    
    yPosition += 8;
    doc.text(`Jurisdiction: ${framework.jurisdiction || 'Multi-jurisdictional'}`, margin, yPosition);
    
    yPosition += 15;
    
    // Add violations summary if available
    if (violations && violations.totalCount > 0) {
      doc.setFont('helvetica', 'bold');
      doc.text('RELATED VIOLATIONS SUMMARY', margin, yPosition);
      yPosition += 8;
      doc.setFont('helvetica', 'normal');
      doc.text(`Total violations in case: ${violations.totalCount}`, margin, yPosition);
      
      // Add relevant violations by category
      const relevantViolations = getRelevantViolationsForFramework(frameworkKey, violations);
      if (relevantViolations.length > 0) {
        yPosition += 10;
        doc.setFont('helvetica', 'bold');
        doc.text('Key Violations in this Jurisdiction:', margin, yPosition);
        yPosition += 8;
        doc.setFont('helvetica', 'normal');
        
        relevantViolations.slice(0, 5).forEach((violation, idx) => {
          const violationText = `${idx + 1}. ${violation.text}`;
          const lines = doc.splitTextToSize(violationText, maxWidth);
          lines.forEach(line => {
            if (yPosition > pageHeight - 20) {
              doc.addPage();
              yPosition = 20;
            }
            doc.text(line, margin, yPosition);
            yPosition += 6;
          });
          yPosition += 2;
        });
      }
    }
    
    // Add passenger context if available
    if (passengerContext && passengerContext.key_facts.length > 0) {
      yPosition += 10;
      doc.setFont('helvetica', 'bold');
      doc.text('RELEVANT PASSENGER CONTEXT', margin, yPosition);
      yPosition += 8;
      doc.setFont('helvetica', 'normal');
      
      passengerContext.key_facts.slice(0, 3).forEach((fact, idx) => {
        const factText = `${idx + 1}. ${fact}`;
        const lines = doc.splitTextToSize(factText, maxWidth);
        lines.forEach(line => {
          if (yPosition > pageHeight - 20) {
            doc.addPage();
            yPosition = 20;
          }
          doc.text(line, margin, yPosition);
          yPosition += 6;
        });
        yPosition += 2;
      });
      
      // Add legal linkage note
      yPosition += 5;
      doc.setFont('helvetica', 'italic');
      doc.text('Note: These contextual facts should be explicitly linked to', margin, yPosition);
      yPosition += 6;
      doc.text('legal principles in the analysis (e.g., moral damages, discrimination).', margin, yPosition);
      doc.setFont('helvetica', 'normal');
    }
    
    yPosition += 15;
    
    // Main analysis content
    doc.setFont('helvetica', 'bold');
    doc.text('FRAMEWORK ANALYSIS', margin, yPosition);
    yPosition += 10;
    doc.setFont('helvetica', 'normal');
    
    // Add the analysis content
    const analysisLines = doc.splitTextToSize(analysisContent, maxWidth);
    for (const line of analysisLines) {
      if (yPosition > pageHeight - 20) {
        doc.addPage();
        yPosition = 20;
      }
      doc.text(line, margin, yPosition);
      yPosition += 6;
    }
    
    return doc;
  }

  // Helper function to get relevant violations for a framework
  function getRelevantViolationsForFramework(frameworkKey, violations) {
    const relevant = [];
    const framework = window.frameworks[frameworkKey];
    if (!framework || !framework.jurisdiction) return relevant;
    
    const frameworkJurisdiction = framework.jurisdiction.toLowerCase();
    
    for (const [jurisdiction, items] of Object.entries(violations.byJurisdiction)) {
      if (jurisdiction.toLowerCase().includes(frameworkJurisdiction) || 
          frameworkJurisdiction.includes(jurisdiction.toLowerCase())) {
        relevant.push(...items);
      }
    }
    
    return relevant;
  }

  // ====== ENHANCED EXPORT FUNCTION ======

  // Modify the exportMultiAnalysis function to use enhanced reports
  async function exportEnhancedAnalysis() {
    const hiddenResults = document.getElementById('hiddenResultsJson');
    const output = hiddenResults ? hiddenResults.textContent : document.getElementById('multiOutput').textContent;

    if (!output || output.trim() === '—') return alert('No output to export.');

    try {
      await ensureJSZip();
      await ensurePDFLibraries();
      
      const zip = new JSZip();
      
      // Get audio name (existing logic)
      let audioName = '';
      const selector = document.getElementById('transcriptSelector');
      if (selector && selector.value) {
        audioName = selector.value;
        const transcript = window.runsState?.runs?.find(run => run.id === selector.value);
        if (transcript && transcript.responsePayload && transcript.responsePayload.length > 0) {
          const payloadFilename = transcript.responsePayload[0].filename;
          if (payloadFilename && payloadFilename !== '_') {
            audioName = payloadFilename;
          }
        }
      }
      
      if (!audioName || audioName === '_' || audioName.trim() === '') {
        audioName = `enhanced_analysis_${Date.now()}`;
      }
      
      let cleanAudioId = audioName
        .replace(/_segment_\d+$/i, '')
        .replace(/\s*\(\d+\s+segs\)$/i, '')
        .replace(/\.(wav|mp3|m4a|flac|ogg)$/i, '')
        .replace(/\.(txt|json)$/i, '')
        .replace(/[^\w\d-_.]/g, '_')
        .replace(/_{2,}/g, '_')
        .replace(/^_+|_+$/g, '')
        .trim();
      
      if (!cleanAudioId || cleanAudioId === '_') {
        cleanAudioId = `enhanced_analysis_${Date.now()}`;
      }
      
      const baseName = cleanAudioId;
      
      // Extract violations and passenger context
      const violations = extractViolationsFromBaseContexts();
      const passengerContext = extractPassengerContext();
      
      // Parse results
      let allResults = {};
      try {
        allResults = JSON.parse(output);
      } catch (e) {
        console.error('Error parsing results:', e);
      }
      
      // Create enhanced folder structure
      const folders = {
        frameworks: zip.folder('frameworks'),
        payloads: zip.folder('payloads'),
        results: zip.folder('results'),
        transcripts: zip.folder('transcripts'),
        pdf_reports: zip.folder('pdf_reports'),
        violations: zip.folder('violations'),
        context: zip.folder('context'),
        synthesis: zip.folder('synthesis')
      };
      
      // Save violations data
      folders.violations.file('violations_summary.json', JSON.stringify(violations, null, 2));
      
      // Save passenger context
      folders.context.file('passenger_context.json', JSON.stringify(passengerContext, null, 2));
      
      // Generate enhanced documentation
      const enhancedDoc = {
        analysis_metadata: {
          timestamp: new Date().toISOString(),
          total_frameworks: (window.frameworkSelectionOrder || []).length,
          violations_count: violations.totalCount,
          passenger_context_available: passengerContext.key_facts.length > 0
        },
        chain_analysis: generateChainAnalysisDocumentation(
          window.frameworkSelectionOrder || [],
          window.frameworkChainModes || {},
          window.frameworks,
          JSON.parse(document.getElementById('multiPayloadsPre').textContent || '{}'),
          allResults
        ),
        violations_integration: {
          summary: `Integrated ${violations.totalCount} violations from base files`,
          by_jurisdiction: Object.keys(violations.byJurisdiction),
          severity_breakdown: {
            high: violations.bySeverity.high.length,
            moderate: violations.bySeverity.moderate.length,
            low: violations.bySeverity.low.length
          }
        },
        context_integration: {
          key_facts: passengerContext.key_facts,
          legal_linkages: generateLegalLinkages(passengerContext, violations)
        }
      };
      
      // Save enhanced documentation
      folders.synthesis.file('enhanced_analysis_documentation.json', JSON.stringify(enhancedDoc, null, 2));
      
      // Process each framework with enhanced reports
      for (const frameworkKey of (window.frameworkSelectionOrder || [])) {
        const framework = window.frameworks[frameworkKey];
        
        if (!framework) continue;
        
        const filePrefix = `${baseName}_${frameworkKey}`;
        
        // Save enhanced framework data
        const frameworkData = {
          name: framework.name,
          description: framework.description,
          jurisdiction: framework.jurisdiction,
          config: framework.config,
          relevant_violations: getRelevantViolationsForFramework(frameworkKey, violations)
        };
        folders.frameworks.file(`${filePrefix}_enhanced.json`, JSON.stringify(frameworkData, null, 2));
        
        // Generate and save enhanced PDF report
        if (allResults[frameworkKey] && allResults[frameworkKey].analysis) {
          try {
            const pdfDoc = await generateEnhancedPDFReport(
              frameworkKey, 
              framework, 
              allResults[frameworkKey].analysis,
              violations,
              passengerContext
            );
            
            const pdfBlob = pdfDoc.output('blob');
            folders.pdf_reports.file(`${filePrefix}_enhanced_report.pdf`, pdfBlob);
          } catch (pdfError) {
            console.error(`Error generating enhanced PDF for ${frameworkKey}:`, pdfError);
          }
        }
      }
      
      // Generate enhanced combined synthesis
      if (allResults.combined || Object.keys(allResults).length > 0) {
        try {
          const combinedPrompt = `
Generate a "Legal Case Synthesis Memo" that merges:
1. The multi-framework legal analysis
2. Specific enumerated violations (${violations.totalCount} total)
3. Passenger's personal and contextual facts

Create an actionable document suitable for submission to:
- Courts (civil litigation)
- Regulatory bodies (ANAC, JAC, DGAC)
- Human rights organizations

Focus on creating concrete, evidence-based arguments that link specific legal violations to the passenger's experience.
`;
          
          const payload = {
            model: (document.getElementById('aiModel') && document.getElementById('aiModel').value) || 'deepseek-v4-pro',
            stream: false,
            messages: [
              {
                role: 'system',
                content: 'You are a legal strategist creating actionable litigation/regulatory complaint documents.'
              },
              {
                role: 'user',
                content: combinedPrompt
              }
            ],
            temperature: 0.1
          };
          
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          
          if (response.ok) {
            const data = await response.json();
            const caseMemo = data.choices?.[0]?.message?.content || 'Unable to generate case memo';
            
            // Save case memo
            folders.synthesis.file('legal_case_synthesis_memo.md', caseMemo);
            
            // Generate PDF version
            const casePdfDoc = new jsPDF();
            casePdfDoc.setProperties({
              title: 'Legal Case Synthesis Memo',
              subject: 'Actionable legal document with violations integration',
              author: 'Enhanced Legal Analysis System'
            });
            
            let yPos = 20;
            const lines = casePdfDoc.splitTextToSize(caseMemo, 170);
            for (const line of lines) {
              if (yPos > 280) {
                casePdfDoc.addPage();
                yPos = 20;
              }
              casePdfDoc.text(line, 20, yPos);
              yPos += 6;
            }
            
            const casePdfBlob = casePdfDoc.output('blob');
            folders.pdf_reports.file(`${baseName}_legal_case_memo.pdf`, casePdfBlob);
          }
        } catch (error) {
          console.error('Error generating case memo:', error);
        }
      }
      
      // Generate the zip file
      const folderName = `enhanced_legal_analysis_${baseName}_${Date.now()}`;
      const content = await zip.generateAsync({ 
        type: "blob",
        compression: "DEFLATE",
        compressionOptions: {
          level: 6
        }
      });
      
      // Save the file
      saveAs(content, `${folderName}.zip`);
      
      if (typeof showToast === 'function') {
        showToast('✓ Enhanced analysis exported with violations integration!');
      }
      
    } catch (error) {
      console.error('Error in enhanced export:', error);
      alert(`Enhanced export error: ${error.message}`);
    }
  }

  // Helper function to generate legal linkages
  function generateLegalLinkages(passengerContext, violations) {
    const linkages = [];
    
    // Family situation linkages
    if (passengerContext.personal.family_situation) {
      linkages.push({
        fact: passengerContext.personal.family_situation,
        legal_principles: [
          'Moral damages under Montreal Convention Art. 22',
          'Emotional distress in consumer protection laws',
          'Family rights considerations in human rights frameworks'
        ],
        violations: violations.bySeverity.high.filter(v => 
          v.text.toLowerCase().includes('moral') || 
          v.text.toLowerCase().includes('damage')
        ).map(v => v.text)
      });
    }
    
    // Professional background linkages
    if (passengerContext.professional.background) {
      linkages.push({
        fact: passengerContext.professional.background,
        legal_principles: [
          'Reasonable passenger standard in negligence analysis',
          'Informed consent principles in procedural fairness',
          'Expert testimony considerations'
        ],
        violations: violations.categories.procedural
      });
    }
    
    // Timeline/duration linkages
    if (passengerContext.incident_timeline.length > 0) {
      linkages.push({
        fact: 'Extended duration of incident (18+ hours)',
        legal_principles: [
          'Delay liability under Montreal Convention Art. 19',
          'Proportionality in administrative actions',
          'Due process timing requirements'
        ],
        violations: violations.bySeverity.moderate.filter(v => 
          v.text.toLowerCase().includes('delay') || 
          v.text.toLowerCase().includes('time')
        ).map(v => v.text)
      });
    }
    
    // Emotional impact linkages
    if (passengerContext.emotional_impact.length > 0) {
      linkages.push({
        fact: 'Humiliation and emotional distress',
        legal_principles: [
          'Degrading treatment under UNCAT',
          'Human dignity protections in constitutional law',
          'Aggravated damages in tort law'
        ],
        violations: violations.categories.human_rights
      });
    }
    
    return linkages;
  }

  // ====== UI ENHANCEMENTS ======

  // Add enhanced export button to UI
  function addEnhancedExportButton() {
    const exportBtn = document.getElementById('multiExportBtn');
    if (!exportBtn || document.getElementById('enhancedExportBtn')) return;
    
    const enhancedBtn = document.getElementById('enhancedExportBtn');
    if (enhancedBtn) {
      enhancedBtn.onclick = exportEnhancedAnalysis;
    }
  }

  // Add violations summary display
  function addViolationsSummaryDisplay() {
    const contentDiv = host.querySelector('.content');
    if (!contentDiv || document.getElementById('violationsSummary')) return;
    
    const summaryDiv = document.createElement('div');
    summaryDiv.id = 'violationsSummary';
    summaryDiv.className = 'field';
    summaryDiv.innerHTML = `
      <label class="toggle-label">Violations Summary (from base files)<span class="toggle-indicator">▼</span></label>
      <div class="toggle-content" style="display: none;">
        <div id="violationsDisplay" style="background: #f8f9fa; border-radius: 4px; padding: 12px; font-size: 0.8rem;">
          <div style="text-align: center; color: var(--muted);">
            Click "Analyze Base Files" to load violations summary
          </div>
        </div>
        <button id="analyzeBaseFilesBtn" class="btn small" style="margin-top: 8px;">Analyze Base Files</button>
      </div>
    `;
    
    // Insert after the combined report section
    const combinedSection = contentDiv.querySelector('#combinedReportSection');
    if (combinedSection) {
      combinedSection.insertAdjacentElement('afterend', summaryDiv);
    }
    
    // Add event listener for analyze button
    document.getElementById('analyzeBaseFilesBtn').onclick = function() {
      const violations = extractViolationsFromBaseContexts();
      const passengerContext = extractPassengerContext();
      
      const display = document.getElementById('violationsDisplay');
      display.innerHTML = `
        <div style="margin-bottom: 12px;">
          <strong>Violations Found:</strong> ${violations.totalCount}
        </div>
        <div style="margin-bottom: 8px;">
          <strong>By Jurisdiction:</strong>
          ${Object.entries(violations.byJurisdiction).map(([jur, items]) => 
            `<div style="margin-left: 12px;">• ${jur}: ${items.length}</div>`
          ).join('')}
        </div>
        <div style="margin-bottom: 8px;">
          <strong>By Severity:</strong>
          <div style="margin-left: 12px;">• High: ${violations.bySeverity.high.length}</div>
          <div style="margin-left: 12px;">• Moderate: ${violations.bySeverity.moderate.length}</div>
          <div style="margin-left: 12px;">• Low: ${violations.bySeverity.low.length}</div>
        </div>
        <div style="margin-bottom: 8px;">
          <strong>Passenger Context:</strong>
          <div style="margin-left: 12px;">• Key Facts: ${passengerContext.key_facts.length}</div>
        </div>
        <div style="color: var(--brand); font-weight: 600; margin-top: 12px;">
          ✓ These violations and context will be integrated into enhanced reports
        </div>
      `;
      
      if (typeof showToast === 'function') {
        showToast(`Analyzed ${violations.totalCount} violations from base files`);
      }
    };
  }

  // Initialize enhanced features
  function initializeEnhancedFeatures() {
    addEnhancedExportButton();
    addViolationsSummaryDisplay();
  }

  // ====== ENHANCED CHAIN ANALYSIS DOCUMENTATION ======

  // Enhance the chain documentation with violations and context
  function generateEnhancedChainDocumentation(chainOrder, chainModes, frameworks, payloads, results) {
    const baseDoc = generateChainAnalysisDocumentation(chainOrder, chainModes, frameworks, payloads, results);
    
    // Extract additional data
    const violations = extractViolationsFromBaseContexts();
    const passengerContext = extractPassengerContext();
    
    // Enhance the documentation
    baseDoc.enhanced_metadata = {
      violations_integrated: violations.totalCount > 0,
      violations_count: violations.totalCount,
      passenger_context_available: passengerContext.key_facts.length > 0,
      base_files_used: ['MASTER-VIOLATIONS-FOR-PINOCCHIO.MD', 'passenger-context-structured.md'].filter(file => {
        // Check if these files are in base contexts
        return window.baseContexts.slots.some(slot => 
          slot && slot.name && (
            slot.name.toLowerCase().includes('violation') || 
            slot.name.toLowerCase().includes('narrative')
          )
        );
      })
    };
    
    baseDoc.legal_linkages_recommended = [
      "Passenger's family situation → Moral damages under Montreal Convention",
      "Aviation expertise → Procedural unfairness analysis",
      "18+ hour delay → Degrading treatment under UNCAT",
      "Multiple jurisdictions → Systemic risk assessment"
    ];
    
    baseDoc.actionable_outputs = [
      "Legal Case Synthesis Memo",
      "Jurisdiction-specific violation catalogs",
      "Regulatory complaint templates",
      "Human rights submission outlines"
    ];
    
    return baseDoc;
  }

  function formatJsonForDisplay(json) {
    return `<pre style="background:#f4f4f4; padding:8px; border-radius:4px; overflow:auto;">${JSON.stringify(json, null, 2)}</pre>`;
  }

  // Ensure runsState is available
  function ensureRunsState() {
    if (!window.runsState) {
      window.runsState = { runs: [], activeId: null };
    }
  }


async function exportMultiAnalysis() {
    const hiddenResults = document.getElementById('hiddenResultsJson');
    const output = hiddenResults ? hiddenResults.textContent : document.getElementById('multiOutput').textContent;
  
    if (!output || output.trim() === '—') return alert('No output to export.');
  
    try {
      // Ensure required libraries are loaded
      await ensureJSZip();
      await ensurePDFLibraries();
      
      const zip = new JSZip();
      
      // Enhanced audio name extraction with CORRECT priority
      let audioName = '';
      let audioUrl = '';
      
      // Priority 1: Use the transcript selector value (same as viewTranscriptBtn)
      const selector = document.getElementById('transcriptSelector');
      if (selector && selector.value) {
        audioName = selector.value;
        console.log('✓ Using transcriptSelector value:', audioName);
        
        // Try to find the transcript and get its audio URL
        const transcript = window.runsState?.runs?.find(run => run.id === selector.value);
        if (transcript && transcript.responsePayload && transcript.responsePayload.length > 0) {
          // Get the filename from responsePayload - this is the authoritative source
          const payloadFilename = transcript.responsePayload[0].filename;
          if (payloadFilename && payloadFilename !== '_') {
            audioName = payloadFilename;
            console.log('✓ Using responsePayload filename:', audioName);
          }
          audioUrl = transcript.responsePayload[0].audio || '';
          console.log('✓ Found audio URL from transcript:', audioUrl);
        }
      }
      
      // Priority 2: Try to get from window.runsState.activeId
      if (!audioName) {
        if (window.runsState && window.runsState.activeId) {
          const run = window.runsState.runs.find(x => x.id === window.runsState.activeId);
          if (run && run.responsePayload && run.responsePayload.length > 0) {
            // Get the filename from responsePayload
            const payloadFilename = run.responsePayload[0].filename;
            if (payloadFilename && payloadFilename !== '_') {
              audioName = payloadFilename;
              console.log('✓ Using responsePayload filename from activeId:', audioName);
            } else {
              audioName = window.runsState.activeId;
              console.log('✓ Using activeId as fallback:', audioName);
            }
            audioUrl = run.responsePayload[0].audio || '';
          } else {
            audioName = window.runsState.activeId;
            console.log('✓ Using activeId:', audioName);
          }
        }
      }
      
      // Priority 3: Try to get from runPreview element
      if (!audioName) {
        const runPreview = document.getElementById('runPreview');
        if (runPreview) {
          const previewText = runPreview.textContent.trim();
          const filenamePart = previewText.split('•')[0].trim();
          if (filenamePart && filenamePart.length > 0 && filenamePart !== '_') {
            audioName = filenamePart;
            console.log('✓ Using runPreview:', audioName);
          }
        }
      }
      
      // Priority 4: Try to get from currentInputData source
      if (!audioName) {
        if (currentInputData && currentInputData.source && currentInputData.source.name) {
          audioName = currentInputData.source.name;
          console.log('✓ Using currentInputData source:', audioName);
        }
      }
      
      // Final fallback: use timestamp
      if (!audioName || audioName === '_' || audioName.trim() === '') {
        audioName = `analysis_${Date.now()}`;
        console.warn('⚠ Using timestamp fallback:', audioName);
      }
      
      console.log('Raw audioName before cleaning:', audioName);
      
      // Clean the audio name - IMPORTANT: Remove segment suffix FIRST, then other processing
      let cleanAudioId = audioName
        .replace(/_segment_\d+$/i, '')               // FIRST: Remove segment suffix like "_segment_1", "_segment_5", etc.
        .replace(/\s*\(\d+\s+segs\)$/i, '')         // Remove segment count like "(25 segs)"
        .replace(/\.(wav|mp3|m4a|flac|ogg)$/i, '')  // Remove audio extensions
        .replace(/\.(txt|json)$/i, '')               // Remove document extensions
        .replace(/[^\w\d-_.]/g, '_')                 // Replace special chars with underscore
        .replace(/_{2,}/g, '_')                      // Replace multiple underscores with single
        .replace(/^_+|_+$/g, '')                     // Remove leading/trailing underscores
        .trim();
      
      // Ensure cleanAudioId is not empty after cleaning
      if (!cleanAudioId || cleanAudioId === '_') {
        cleanAudioId = `analysis_${Date.now()}`;
        console.warn('⚠ cleanAudioId was empty after cleaning, using:', cleanAudioId);
      }
      
      console.log('✓ Final cleanAudioId:', cleanAudioId);
      console.log('✓ Audio URL:', audioUrl || 'Not available');
      
      // Create a clean base name for files
      const baseName = cleanAudioId;
      
      // Create folder structure including media folder
      const folders = {
        frameworks: zip.folder('frameworks'),
        payloads: zip.folder('payloads'),
        results: zip.folder('results'),
        transcripts: zip.folder('transcripts'),
        pdf_reports: zip.folder('pdf_reports'),
        media: zip.folder('media')
      };
      
      // Download and add audio file to media folder if URL is available
      if (audioUrl) {
        try {
          console.log('Downloading audio from:', audioUrl);
          const audioResponse = await fetch(audioUrl);
          if (audioResponse.ok) {
            const audioBlob = await audioResponse.blob();
            const audioExtension = audioUrl.split('.').pop().split('?')[0] || 'mp3';
            folders.media.file(`${cleanAudioId}.${audioExtension}`, audioBlob);
            console.log('✓ Audio file added to export');
          } else {
            console.warn('Failed to download audio:', audioResponse.status);
          }
        } catch (audioError) {
          console.error('Error downloading audio:', audioError);
        }
      }
      
      // Get the current transcript using the same logic as viewTranscriptBtn
      const selectedId = selector?.value || window.runsState?.activeId;
      const transcript = window.runsState?.runs?.find(run => run.id === selectedId);
      
      // Prepare transcript content
      let transcriptContent = '';
      if (transcript && transcript.data && transcript.data.segments) {
        transcriptContent = transcript.data.segments.map(s => {
          const speakerLabel = typeof getSpeakerLabel === 'function' ? 
            getSpeakerLabel(s.speaker) : `Speaker ${s.speaker}`;
          return `[${(s.start||0).toFixed(2)}-${(s.end||0).toFixed(2)}] ${speakerLabel}: ${(s.text||'').trim()}`;
        }).join('\n');
      }
      
      // Get all payloads
      const allPayloads = JSON.parse(document.getElementById('multiPayloadsPre').textContent || '{}');
      
      // Parse results safely
      let allResults = {};
      try {
        allResults = JSON.parse(output);
      } catch (e) {
        console.error('Error parsing results:', e);
      }
      
      // Generate chain analysis documentation with audio information
      const chainDocumentation = generateChainAnalysisDocumentation(
        window.frameworkSelectionOrder || [],
        window.frameworkChainModes || {},
        window.frameworks,
        allPayloads,
        allResults
      );
      
      // Add audio metadata to chain documentation
      chainDocumentation.audio_metadata = {
        filename: audioName,
        clean_id: cleanAudioId,
        audio_url: audioUrl || 'Not available',
        included_in_export: !!audioUrl,
        format: audioUrl ? audioUrl.split('.').pop().split('?')[0] : 'unknown',
        transcript_id: selectedId || 'unknown'
      };
      
      // Add chain documentation to root of ZIP
      zip.file('chain_analysis.json', JSON.stringify(chainDocumentation, null, 2));
      
      // Prepare frameworks data for export
      const frameworksData = {};
      
      // Process each framework in the chain
      for (const frameworkKey of (window.frameworkSelectionOrder || [])) {
        const framework = window.frameworks[frameworkKey];
        
        if (!framework) continue;
        
        // Create consistent filename prefix
        const filePrefix = `${baseName}_${frameworkKey}`;
        
        // 1. Add framework definition to frameworks folder
        const frameworkData = {
          name: framework.name,
          description: framework.description,
          path: framework.path,
          config: framework.config,
          generatedPromptLoaded: framework.generatedPromptLoaded || false
        };
        frameworksData[frameworkKey] = frameworkData;
        folders.frameworks.file(`${filePrefix}_framework.json`, JSON.stringify(frameworkData, null, 2));
        
        // 2. Add payload to payloads folder
        if (allPayloads[frameworkKey]) {
          folders.payloads.file(`${filePrefix}_payload.json`, JSON.stringify(allPayloads[frameworkKey], null, 2));
        }
        
        // 3. Add results to results folder
        if (allResults[frameworkKey]) {
          folders.results.file(`${filePrefix}_result.json`, JSON.stringify(allResults[frameworkKey], null, 2));
        }
        
        // 4. Add transcript to transcripts folder
        if (transcriptContent) {
          folders.transcripts.file(`${filePrefix}_transcript.txt`, transcriptContent);
        }
        
        // 5. Generate and add PDF report for each framework
        if (allResults[frameworkKey] && allResults[frameworkKey].analysis) {
          try {
            const chainContext = {
              position: (window.frameworkSelectionOrder.indexOf(frameworkKey) + 1),
              total: window.frameworkSelectionOrder.length,
              mode: window.frameworkChainModes[frameworkKey] || 'none',
              mode_description: getChainModeDescription(window.frameworkChainModes[frameworkKey] || 'none')
            };
            
            const pdfDoc = await generatePDFReport(
              frameworkKey, 
              framework, 
              allResults[frameworkKey].analysis,
              chainContext
            );
            
            const pdfBlob = pdfDoc.output('blob');
            folders.pdf_reports.file(`${filePrefix}_report.pdf`, pdfBlob);
            
          } catch (pdfError) {
            console.error(`Error generating PDF for ${frameworkKey}:`, pdfError);
          }
        }
      }
      
      // Add the combined results to the results folder
      if (allResults.combined || Object.keys(allResults).length > 0) {
        folders.results.file(`${baseName}_combined_results.json`, JSON.stringify(allResults, null, 2));
      }
      
      // Generate combined PDF report if available
      if (allResults.combined) {
        try {
          const combinedFramework = {
            name: "Combined Multi-Framework Analysis",
            key: "combined",
            description: "Synthesized analysis across all frameworks"
          };
          
          const pdfDoc = await generatePDFReport(
            "combined",
            combinedFramework,
            allResults.combined
          );
          
          const pdfBlob = pdfDoc.output('blob');
          folders.pdf_reports.file(`${baseName}_combined_report.pdf`, pdfBlob);
        } catch (pdfError) {
          console.error('Error generating combined PDF:', pdfError);
        }
      }
      
      // Generate chain overview PDF
      try {
        const chainOverviewContent = generateChainOverviewContent(chainDocumentation);
        const chainPdfDoc = await generateChainOverviewPDF(chainOverviewContent, baseName);
        const chainPdfBlob = chainPdfDoc.output('blob');
        folders.pdf_reports.file(`${baseName}_chain_overview.pdf`, chainPdfBlob);
      } catch (error) {
        console.error('Error generating chain overview PDF:', error);
      }
      
      // Generate the zip file
      const folderName = `legal_analysis_${baseName}_${Date.now()}`;
      const content = await zip.generateAsync({ 
        type: "blob",
        compression: "DEFLATE",
        compressionOptions: {
          level: 6
        }
      });
      
      const frameworkCount = (window.frameworkSelectionOrder || []).length;
      
      // Save the file
      saveAs(content, `${folderName}.zip`);
      
      // Show success message
      const mediaMsg = audioUrl ? ' (includes audio file)' : '';
      if (typeof showToast === 'function') {
        showToast(`Export complete! ${frameworkCount} frameworks exported with PDF reports${mediaMsg}.`);
      } else {
        alert(`Export complete! ${frameworkCount} frameworks exported with PDF reports${mediaMsg}.`);
      }
      
      // Log the structure for debugging
      console.log(`Exported structure for ${folderName}:`);
      console.log(`├── frameworks/ (${frameworkCount} files)`);
      console.log(`├── payloads/ (${frameworkCount} files)`);
      console.log(`├── results/ (${frameworkCount + 1} files)`);
      console.log(`├── transcripts/ (${frameworkCount} files)`);
      console.log(`├── pdf_reports/ (${frameworkCount + 2} files)`);
      console.log(`├── media/ (${audioUrl ? '1 audio file' : '0 files'})`);
      console.log(`└── chain_analysis.json`);
      
      // Prepare export data structure for backend save
      const exportData = {
        audio_id: cleanAudioId,
        transcript: transcriptContent,
        frameworks: frameworksData,
        payloads: allPayloads,
        results: allResults,
        auto_process: true,
        chain_analysis: chainDocumentation,
        timestamp: new Date().toISOString(),
        audio_metadata: {
          filename: audioName,
          url: audioUrl,
          included: !!audioUrl,
          transcript_id: selectedId
        }
      };
      
      // Show saving status
      if (typeof showToast === 'function') {
        showToast('Saving analysis to server...', 5000);
      }
      
      // Send to backend to save
      try {
        console.log('Sending to backend with audio_id:', cleanAudioId);
        
        const response = await fetch('/api/violations/save-analysis-export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            audio_id: cleanAudioId,
            export_data: exportData
          })
        });
        
        if (response.ok) {
          const saveResult = await response.json();
          
          if (saveResult.success) {
            const message = `Analysis saved successfully!\n\nLocation: ${saveResult.paths.base_folder}\n\nAudio: ${cleanAudioId}\nTranscript file: ${cleanAudioId}_transcription___transcript.txt`;
            
            if (typeof showToast === 'function') {
              showToast('✓ Analysis saved to server!', 4000);
            }
            
            console.log('Analysis saved to:', saveResult.paths.base_folder);
            console.log('Audio ID:', cleanAudioId);
            console.log('Transcript file:', `${cleanAudioId}_transcription___transcript.txt`);
            console.log('Save timestamp:', saveResult.timestamp);
            
            alert(message);
          }
        } else {
          const errorText = await response.text();
          console.error('Server error:', errorText);
          throw new Error(`Server returned ${response.status}: ${errorText}`);
        }
      } catch (saveError) {
        console.error('Error saving to server:', saveError);
        if (typeof showToast === 'function') {
          showToast('⚠️ Export downloaded but server save failed', 5000);
        }
        // Continue even if server save fails - user still has the ZIP file
      }
      
    } catch (e) {
      console.error("Export error:", e);
      alert(`Export error: ${e.message}`);
    }
}

// Status polling function for post-processing
async function pollProcessingStatus(audioId) {
  const maxAttempts = 20;
  let attempts = 0;
  
  const checkStatus = async () => {
    try {
      const res = await fetch(`/api/violations/processing-status/${audioId}`);
      const data = await res.json();
      
      if (data.status === 'complete') {
        console.log('✅ Post-processing complete!', data);
        if (typeof showToast === 'function') {
          showToast('✅ Post-processing pipeline complete!', 4000);
        }
        
        // Display completion details
        if (data.results) {
          console.log('Processing results:', {
            violations_found: data.results.violations_count,
            enriched_count: data.results.enriched_count,
            files_created: data.results.files_created
          });
        }
        return true;
      } else if (data.status === 'error') {
        console.error('❌ Post-processing failed:', data.error_data);
        if (typeof showToast === 'function') {
          showToast('⚠️ Post-processing encountered errors', 5000);
        }
        return true;
      } else if (data.status === 'processing') {
        // Show progress if available
        if (data.current_step && typeof showToast === 'function') {
          showToast(`🔄 ${data.current_step}...`, 3000);
        }
      }
      
      // Still processing - continue polling
      attempts++;
      if (attempts < maxAttempts) {
        setTimeout(checkStatus, 15000); // Check every 15 seconds
      } else {
        console.log('⏱️ Stopped polling after max attempts');
        if (typeof showToast === 'function') {
          showToast('⏱️ Post-processing is taking longer than expected. Check logs for status.', 6000);
        }
      }
      
    } catch (err) {
      console.error('Error checking processing status:', err);
      attempts++;
      if (attempts < maxAttempts) {
        setTimeout(checkStatus, 15000);
      }
    }
  };
  
  // Start polling after initial delay
  console.log('🔄 Starting post-processing status monitoring...');
  setTimeout(checkStatus, 10000);
}

// Enhanced version of exportMultiAnalysis with post-processing
// This extends the existing function without modifying it
async function exportMultiAnalysisWithProcessing() {
  const hiddenResults = document.getElementById('hiddenResultsJson');
  const output = hiddenResults ? hiddenResults.textContent : document.getElementById('multiOutput').textContent;

  if (!output || output.trim() === '—') return alert('No output to export.');

  try {
    // First, execute the standard export to create the ZIP
    await ensureJSZip();
    await ensurePDFLibraries();
    
    const zip = new JSZip();
    
    // Use the same audio name extraction logic as the main function
    let audioName = '';
    let audioUrl = '';
    
    const selector = document.getElementById('transcriptSelector');
    if (selector && selector.value) {
      audioName = selector.value;
      const transcript = window.runsState?.runs?.find(run => run.id === selector.value);
      if (transcript && transcript.responsePayload && transcript.responsePayload.length > 0) {
        const payloadFilename = transcript.responsePayload[0].filename;
        if (payloadFilename && payloadFilename !== '_') {
          audioName = payloadFilename;
        }
        audioUrl = transcript.responsePayload[0].audio || '';
      }
    }
    
    if (!audioName) {
      if (window.runsState && window.runsState.activeId) {
        const run = window.runsState.runs.find(x => x.id === window.runsState.activeId);
        if (run && run.responsePayload && run.responsePayload.length > 0) {
          const payloadFilename = run.responsePayload[0].filename;
          if (payloadFilename && payloadFilename !== '_') {
            audioName = payloadFilename;
          } else {
            audioName = window.runsState.activeId;
          }
          audioUrl = run.responsePayload[0].audio || '';
        } else {
          audioName = window.runsState.activeId;
        }
      }
    }
    
    if (!audioName || audioName === '_' || audioName.trim() === '') {
      audioName = `analysis_${Date.now()}`;
    }
    
    let cleanAudioId = audioName
      .replace(/_segment_\d+$/i, '')
      .replace(/\s*\(\d+\s+segs\)$/i, '')
      .replace(/\.(wav|mp3|m4a|flac|ogg)$/i, '')
      .replace(/\.(txt|json)$/i, '')
      .replace(/[^\w\d-_.]/g, '_')
      .replace(/_{2,}/g, '_')
      .replace(/^_+|_+$/g, '')
      .trim();
    
    if (!cleanAudioId || cleanAudioId === '_') {
      cleanAudioId = `analysis_${Date.now()}`;
    }
    
    // Get transcript content
    const selectedId = selector?.value || window.runsState?.activeId;
    const transcript = window.runsState?.runs?.find(run => run.id === selectedId);
    
    let transcriptContent = '';
    if (transcript && transcript.data && transcript.data.segments) {
      transcriptContent = transcript.data.segments.map(s => {
        const speakerLabel = typeof getSpeakerLabel === 'function' ? 
          getSpeakerLabel(s.speaker) : `Speaker ${s.speaker}`;
        return `[${(s.start||0).toFixed(2)}-${(s.end||0).toFixed(2)}] ${speakerLabel}: ${(s.text||'').trim()}`;
      }).join('\n');
    }
    
    // Get payloads and results
    const allPayloads = JSON.parse(document.getElementById('multiPayloadsPre').textContent || '{}');
    let allResults = {};
    try {
      allResults = JSON.parse(output);
    } catch (e) {
      console.error('Error parsing results:', e);
    }
    
    // Generate chain documentation
    const chainDocumentation = generateChainAnalysisDocumentation(
      window.frameworkSelectionOrder || [],
      window.frameworkChainModes || {},
      window.frameworks,
      allPayloads,
      allResults
    );
    
    chainDocumentation.audio_metadata = {
      filename: audioName,
      clean_id: cleanAudioId,
      audio_url: audioUrl || 'Not available',
      included_in_export: !!audioUrl,
      format: audioUrl ? audioUrl.split('.').pop().split('?')[0] : 'unknown',
      transcript_id: selectedId || 'unknown'
    };
    
    // Prepare frameworks data
    const frameworksData = {};
    for (const frameworkKey of (window.frameworkSelectionOrder || [])) {
      const framework = window.frameworks[frameworkKey];
      if (!framework) continue;
      
      frameworksData[frameworkKey] = {
        name: framework.name,
        description: framework.description,
        path: framework.path,
        config: framework.config,
        generatedPromptLoaded: framework.generatedPromptLoaded || false
      };
    }
    
    // Prepare export data structure
    const exportData = {
      audio_id: cleanAudioId,
      transcript: transcriptContent,
      frameworks: frameworksData,
      payloads: allPayloads,
      results: allResults,
      chain_analysis: chainDocumentation,
      timestamp: new Date().toISOString(),
      audio_metadata: {
        filename: audioName,
        url: audioUrl,
        included: !!audioUrl,
        transcript_id: selectedId
      }
    };
    
    // Show saving status with post-processing info
    if (typeof showToast === 'function') {
      showToast('Saving analysis and starting post-processing pipeline...', 6000);
    }
    
    console.log('📤 Sending analysis with post-processing request...');
    console.log('Audio ID:', cleanAudioId);
    
    // Send to backend with post-processing enabled
    const response = await fetch('/api/violations/save-analysis-export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        audio_id: cleanAudioId,
        export_data: exportData,
        auto_process: true,  // Enable automatic post-processing
        enrich_start: 1,     // Start enrichment from violation 1
        enrich_end: 3        // Enrich first 3 violations
      })
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('Server error:', errorText);
      throw new Error(`Server returned ${response.status}: ${errorText}`);
    }
    
    const saveResult = await response.json();
    
    if (saveResult.success) {
      // Build success message with post-processing details
      let message = `✅ Analysis saved successfully!\n\n`;
      message += `📁 Location: ${saveResult.paths.base_folder}\n`;
      message += `📄 Transcript: ${cleanAudioId}_transcription___transcript.txt\n`;
      
      if (saveResult.post_processing) {
        message += `\n🔄 Post-Processing Pipeline Started:\n`;
        message += `   ✓ Violations scanner\n`;
        message += `   ✓ Master JSON builder\n`;
        message += `   ✓ Violations merger\n`;
        message += `   ✓ AI enrichment (violations ${saveResult.post_processing.enrichment_range})\n`;
        message += `\n📊 Status URL: ${saveResult.post_processing.check_status_url}`;
      }
      
      if (typeof showToast === 'function') {
        showToast('✓ Analysis saved! Post-processing started...', 5000);
      }
      
      // Log detailed information
      console.log('✅ Analysis saved successfully');
      console.log('📁 Base folder:', saveResult.paths.base_folder);
      console.log('📄 Files saved:', saveResult.files_saved);
      console.log('🔄 Post-processing:', saveResult.post_processing);
      
      // Show the message to user
      alert(message);
      
      // Start polling for processing status if enabled
      if (saveResult.post_processing && saveResult.post_processing.started) {
        console.log('🔄 Starting status monitoring...');
        pollProcessingStatus(cleanAudioId);
      }
      
    } else {
      throw new Error(saveResult.message || 'Failed to save analysis');
    }
    
  } catch (error) {
    console.error('❌ Export with processing error:', error);
    
    if (typeof showToast === 'function') {
      showToast('⚠️ Error during export/processing', 5000);
    }
    
    alert(`Export error: ${error.message}\n\nCheck console for details.`);
  }
}

// Add UI button to trigger the enhanced export
function addPostProcessingExportButton() {
  const exportBtn = document.getElementById('multiExportBtn');
  if (!exportBtn || document.getElementById('multiExportProcessBtn')) return;
  
  const processBtn = document.createElement('button');
  processBtn.id = 'multiExportProcessBtn';
  processBtn.className = 'btn small';
  processBtn.textContent = 'Export + Process';
  processBtn.title = 'Export and automatically run post-processing pipeline';
  processBtn.onclick = exportMultiAnalysisWithProcessing;
  
  // Insert after the regular export button
  exportBtn.parentNode.insertBefore(processBtn, exportBtn.nextSibling);
}

// Initialize the new button when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', addPostProcessingExportButton);
} else {
  addPostProcessingExportButton();
}

  // Function to load the generated_prompt.txt for a framework
  async function loadGeneratedPrompt(frameworkKey) {
    try {
      const framework = window.frameworks[frameworkKey];
      
      if (!framework || !framework.path) {
        console.warn(`Could not determine path for framework: ${frameworkKey}`);
        return false;
      }
      
      // Construct the path to the generated_prompt.txt file
      const promptPath = `${framework.path}/generated_prompt.txt`;
      
      console.log(`Attempting to load prompt from: ${promptPath}`);
      
      // Fetch the prompt file
      const response = await fetch(promptPath);
      
      if (!response.ok) {
        console.warn(`No generated prompt found at ${promptPath}`);
        return false;
      }
      
      const promptText = await response.text(); 
      
      // Store the prompt in the framework object
      if (window.frameworks[frameworkKey]) {
        window.frameworks[frameworkKey].generatedPrompt = promptText;
        window.frameworks[frameworkKey].generatedPromptLoaded = true;
        console.log(`✓ Loaded generated prompt for ${frameworkKey}`);
        return true;
      }
      
      return false;
    } catch (error) {
      console.error(`Error loading generated prompt for ${frameworkKey}:`, error);
      return false;
    }
  }

  // Function to ensure JSZip is loaded
  function ensureJSZip() {
    return new Promise((resolve, reject) => {
      if (window.JSZip) {
        resolve(window.JSZip);
        return;
      }
      
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
      script.onload = () => resolve(window.JSZip);
      script.onerror = (err) => reject(new Error('Failed to load JSZip'));
      document.head.appendChild(script);
    });
  }

  // Start the injection process
  injectWhenReady();
})();

// Universal Input Preprocessor for handling different input types
window.UniversalInputPreprocessor = {
  async processInput(input, type, name = 'Unknown') {
    try {
      if (type === 'file') {
        return await this.processFile(input, name);
      } else if (type === 'text') {
        return this.processText(input, name);
      } else {
        throw new Error(`Unsupported input type: ${type}`);
      }
    } catch (error) {
      console.error('Error in UniversalInputPreprocessor:', error);
      throw error;
    }
  },

  async processFile(file, name) {
    const fileType = file.type || '';
    const fileName = file.name || name;
    
    // Handle different file types
       if (fileType.includes('text') || fileName.endsWith('.txt') || fileName.endsWith('.html')) {
      return await this.readTextFile(file, fileName);
    } else if (fileName.endsWith('.md')) {
      return await this.readTextFile(file, fileName);
    } else if (fileName.endsWith('.pdf')) {
      await loadPDFJS();
      return await this.readPDFFile(file, fileName);
    } else if (fileName.endsWith('.msg') || fileName.endsWith('.eml')) {
      throw new Error('Email file processing not implemented yet. Please extract text content first.');
    } else {
      // Try to read as text anyway
      console.warn(`Unknown file type: ${fileType}, attempting to read as text`);
      return await this.readTextFile(file, fileName);
    }
  },

  async readTextFile(file, fileName) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      
      reader.onload = (e) => {
        const content = e.target.result;
        const segments = this.parseTextContent(content, fileName);
        
        resolve({
          segments: segments,
          source: {
            type: 'document',
            name: fileName,
            processedAt: new Date().toISOString(),
            fileType: file.type || 'text/plain'
          }
        });
      };
      
      reader.onerror = () => {
        reject(new Error('Failed to read file'));
      };
      
      reader.readAsText(file);
    });
  },

  processText(text, name) {
    const segments = this.parseTextContent(text, name);
    
    return {
      segments: segments,
      source: {
        type: 'text',
        name: name,
        processedAt: new Date().toISOString()
      }
    };
  },

  parseTextContent(content, sourceName) {
    // Split content into segments (lines or paragraphs)
    const lines = content.split('\n').filter(line => line.trim().length > 0);
    
    const segments = [];
    let currentTime = 0;
    const timeIncrement = 10; // 10 seconds per segment
    
    lines.forEach((line, index) => {
      // Try to extract speaker if it looks like a transcript
      const speakerMatch = line.match(/^([^:]+):\s*(.+)$/);
      
      if (speakerMatch) {
        segments.push({
          speaker: speakerMatch[1].trim(),
          start: currentTime,
          end: currentTime + timeIncrement,
          text: speakerMatch[2].trim(),
          source: sourceName
        });
      } else {
        // No speaker found, treat as continuous text
        segments.push({
          speaker: 'Document',
          start: currentTime,
          end: currentTime + timeIncrement,
          text: line.trim(),
          source: sourceName
        });
      }
      
      currentTime += timeIncrement;
    });
    
    // If no segments were created, create one big segment
    if (segments.length === 0) {
      segments.push({
        speaker: 'Document',
        start: 0,
        end: 60, // 1 minute
        text: content.trim(),
        source: sourceName
      });
    }
    
    return segments;
  }
};

// Add this to load PDF.js if needed
async function loadPDFJS() {
  if (window.pdfjsLib) return;
  
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
    script.onload = () => resolve();
    script.onerror = (err) => reject(err);
    document.head.appendChild(script);
  });
}

// Initialize baseContexts structure
window.baseContexts = window.baseContexts || {
  slots: [null, null, null],
  names: ['Master Report', 'Comprehensive Violations', 'Synthesized Narrative']
};

// Add FileSaver.js for export functionality
(function loadFileSaver() {
  if (window.saveAs) return;
  
  const script = document.createElement('script');
  script.src = 'https://cdnjs.cloudflare.com/ajax/libs/FileSaver.js/2.0.5/FileSaver.min.js';
  document.head.appendChild(script);
})();

// Add toast notification function if not exists
if (typeof showToast === 'undefined') {
  window.showToast = function(message, duration = 3000) {
    // Create toast element
    const toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: #333;
      color: white;
      padding: 12px 20px;
      border-radius: 4px;
      z-index: 10000;
      font-size: 0.9rem;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      opacity: 0;
      transition: opacity 0.3s;
    `;
    
    document.body.appendChild(toast);
    
    // Animate in
    setTimeout(() => toast.style.opacity = '1', 10);
    
    // Remove after duration
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, duration);
  };
}

// Add getSpeakerLabel function if not exists
if (typeof getSpeakerLabel === 'undefined') {
  window.getSpeakerLabel = function(speakerId) {
    return `Speaker ${speakerId}`;
  };
}

// Populate transcript selector options
async function populateTranscriptSelector() {
  const selector = document.getElementById('transcriptSelector');
  if (!selector) return;
  selector.innerHTML = '<option>Loading...</option>';
  try {
    const resp = await fetch('http://localhost:8019/api/transcripts');
    if (!resp.ok) throw new Error('Failed to fetch transcript list');
    const transcripts = await resp.json();
    selector.innerHTML = '';
    transcripts.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.filename;
      opt.textContent = t.filename + (t.content ? ` (${t.content.length} segs)` : '');
      selector.appendChild(opt);
    });
    // Set current selection if possible
    if (window.runsState && window.runsState.activeId) {
      selector.value = window.runsState.activeId;
    }
  } catch (e) {
    selector.innerHTML = '<option>Error loading transcripts</option>';
  }
}

// Add this function to generate chain analysis documentation
function generateChainAnalysisDocumentation(chainOrder, chainModes, frameworks, payloads, results) {
  // Normalize chainOrder to an array of items and keys.
  const items = Array.isArray(chainOrder) ? chainOrder : [];
  // keys: array of framework keys (strings)
  const keys = items.map(item => {
    if (typeof item === 'string') return item;
    if (item && (item.framework_key || item.key)) return item.framework_key || item.key;
    return String(item);
  });

  // Build canonical order objects (position, framework_key, framework_name, chaining_mode, mode_description)
  const orderObjects = items.map((item, index) => {
    const key = typeof item === 'string' ? item : (item && (item.framework_key || item.key)) || String(item);
    const itemMode = (item && (item.mode || item.chaining_mode)) || null;
    const chaining_mode = (chainModes && chainModes[key]) || itemMode || 'none';
    return {
      position: index + 1,
      framework_key: key,
      framework_name: (frameworks && frameworks[key] && frameworks[key].name) ? frameworks[key].name : key,
      chaining_mode: chaining_mode,
      mode_description: getChainModeDescription(chaining_mode)
    };
  });

  // Safely compute base contexts loaded
  const baseSlots = (window.baseContexts && Array.isArray(window.baseContexts.slots)) ? window.baseContexts.slots : [];
  const baseContextsLoaded = baseSlots.filter(s => s !== null && typeof s !== 'undefined').length;

  // Determine current input data safely (prefer global window.currentInputData or local currentInputData)
  const inputData = (typeof window !== 'undefined' && window.currentInputData) ? window.currentInputData : (typeof currentInputData !== 'undefined' ? currentInputData : null);

  const documentation = {
    analysis_metadata: {
      timestamp: new Date().toISOString(),
      total_frameworks: keys.length,
      chain_id: `chain_${Date.now()}`
    },
    chain_configuration: {
      order: orderObjects,
      modes_summary: Object.keys(chainModes || {}).reduce((summary, key) => {
        summary[key] = {
          mode: chainModes[key],
          description: getChainModeDescription(chainModes[key])
        };
        return summary;
      }, {})
    },
    framework_details: keys.map(key => {
      const fw = (frameworks && frameworks[key]) || {};
      return {
        key: key,
        name: fw.name || key,
        description: fw.description || '',
        jurisdiction: fw.jurisdiction || '',
        categories: fw.categories || [],
        has_generated_prompt: !!fw.generatedPromptLoaded,
        prompt_length: fw.generatedPrompt ? fw.generatedPrompt.length : 0
      };
    }),
    analysis_context: {
      input_source: inputData && inputData.source ? inputData.source : 'unknown',
      input_segments_count: inputData && Array.isArray(inputData.segments) ? inputData.segments.length : 0,
      base_contexts_loaded: baseContextsLoaded
    },
    payload_references: keys.map(key => {
      const payload = (payloads && payloads[key]) || {};
      return {
        framework: key,
        model: payload.model || null,
        temperature: payload.temperature || null,
        stream: payload.stream || false,
        message_count: Array.isArray(payload.messages) ? payload.messages.length : 0,
        framework_mode: payload.frameworkMode || (chainModes && chainModes[key]) || 'none'
      };
    }),
    results_summary: keys.map(key => {
      const result = (results && results[key]) || {};
      return {
        framework: key,
        status: result && result.error ? 'error' : 'success',
        error: result && result.error ? result.error : null,
        analysis_length: result && result.analysis ? (typeof result.analysis === 'string' ? result.analysis.length : (Array.isArray(result.analysis) ? result.analysis.length : 0)) : 0,
        has_reasoning: !!(result && result.analysis && (typeof result.analysis === 'string' ? result.analysis.length > 0 : Array.isArray(result.analysis) && result.analysis.length > 0))
      };
    })
  };

  return documentation;
}

function getChainModeDescription(mode) {
  const descriptions = {
    'none': 'Independent analysis without input from previous frameworks',
    'last': 'Uses results from the immediately preceding framework only',
    'all': 'Uses cumulative results from all previous frameworks in the chain'
  };
  return descriptions[mode] || 'Unknown mode';
}

// Enhanced PDF generation for all analysis components
async function generatePDFReport(frameworkKey, framework, analysisContent, chainDoc = null) {
  await ensurePDFLibraries();
  
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  
  // Set document properties
  doc.setProperties({
    title: `Legal Analysis - ${framework.name}`,
    subject: `Analysis using ${framework.name} framework`,
    author: 'Multi-Framework Legal Analysis System',
    keywords: 'legal, analysis, compliance, framework',
    creator: 'Legal Analysis Module'
  });

  let yPosition = 20;
  const pageHeight = doc.internal.pageSize.height;
  const margin = 20;
  const maxWidth = 170;

  // Title Page
  doc.setFontSize(20);
  doc.setFont('helvetica', 'bold');
  doc.text('LEGAL ANALYSIS REPORT', margin, yPosition);
  
  yPosition += 10;
  doc.setFontSize(16);
  doc.setFont('helvetica', 'normal');
  doc.text(framework.name, margin, yPosition);
  
  yPosition += 15;
  doc.setFontSize(12);
  doc.text(`Generated: ${new Date().toLocaleString()}`, margin, yPosition);
  
  yPosition += 8;
  doc.text(`Framework: ${framework.key}`, margin, yPosition);
  
  yPosition += 8;
  doc.text(`Jurisdiction: ${framework.jurisdiction || 'Not specified'}`, margin, yPosition);
  
  // Add chain information if available
  if (chainDoc) {
    yPosition += 15;
    doc.setFont('helvetica', 'bold');
    doc.text('CHAIN ANALYSIS CONTEXT', margin, yPosition);
    yPosition += 8;
    doc.setFont('helvetica', 'normal');
    const position = chainDoc.position || '-';
    const total = chainDoc.total || '-';
    const mode = chainDoc.mode || 'none';
    doc.text(`Position in chain: ${position}/${total}`, margin, yPosition);
    yPosition += 6;
    doc.text(`Chaining mode: ${mode}`, margin, yPosition);
    yPosition += 5;
  }
  
  // Framework Description
  if (framework.description) {
    doc.setFont('helvetica', 'bold');
    doc.text('Framework Description:', margin, yPosition);
    yPosition += 8;
    doc.setFont('helvetica', 'normal');
    doc.text(framework.description, margin, yPosition);
  }
    yPosition += 15;
  return doc;
}

function generateChainOverviewContent(chainDoc) {
  return {
    analysis_metadata: chainDoc.analysis_metadata,
    chain_order: chainDoc.chain_configuration.order,
    framework_details: chainDoc.framework_details,
    analysis_context: chainDoc.analysis_context
  };
}

async function generateChainOverviewPDF(chainContent, baseName) {
  await ensurePDFLibraries();

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  let yPosition = 20;
  const margin = 20;
  const maxWidth = 170;
  const pageHeight = doc.internal.pageSize.height;

  doc.setFontSize(18);
  doc.setFont('helvetica', 'bold');
  doc.text('Chain Analysis Overview', margin, yPosition);
  yPosition += 10;

  doc.setFontSize(11);
  doc.setFont('helvetica', 'normal');
  doc.text(`Export ID: ${baseName}`, margin, yPosition);
  yPosition += 7;
  doc.text(`Generated: ${new Date().toLocaleString()}`, margin, yPosition);
  yPosition += 10;

  const totalFrameworks = chainContent?.analysis_metadata?.total_frameworks || 0;
  doc.text(`Total frameworks: ${totalFrameworks}`, margin, yPosition);
  yPosition += 8;

  const order = chainContent?.chain_order || [];
  for (const item of order) {
    if (yPosition > pageHeight - 20) {
      doc.addPage();
      yPosition = 20;
    }

    const line = `${item.position}. ${item.framework_name} (${item.framework_key}) - ${item.chaining_mode}`;
    const lines = doc.splitTextToSize(line, maxWidth);
    for (const wrapped of lines) {
      doc.text(wrapped, margin, yPosition);
      yPosition += 6;
    }
  }

  return doc;
}

// Function to export only PDF reports (without the full ZIP)
async function exportPDFReportsOnly() {
  const hiddenResults = document.getElementById('hiddenResultsJson');
  const output = hiddenResults ? hiddenResults.textContent : document.getElementById('multiOutput').textContent;
  
  if (!output || output.trim() === '—') return alert('No analysis results to export as PDF.');
  
  try {
    await ensurePDFLibraries();
    
    const allResults = JSON.parse(output);
    const run = window.runsState.runs.find(x => x.id === window.runsState.activeId);
    
    // Get base name
    let baseName = 'legal_analysis';
    if (run) {
      baseName = (run.label || run.id).replace(/[^\w\d-_.]/g, '_');
    }
    
    // Generate PDFs for each framework
    for (const frameworkKey of (window.frameworkSelectionOrder || [])) {
      const framework = window.frameworks[frameworkKey];
      
      if (allResults[frameworkKey] && allResults[frameworkKey].analysis) {
        const pdfDoc = await generatePDFReport(frameworkKey, framework, allResults[frameworkKey].analysis);
        const pdfBlob = pdfDoc.output('blob');
        saveAs(pdfBlob, `${baseName}_${frameworkKey}_report.pdf`);
      }
    }
    


// Add this section to your UI (place it after the "Import Chain Configuration Section")
const chainConfigSection = `
<!-- Chain Configuration Management Section -->
<div class="field">
  <label class="toggle-label">Chain Configuration Management<span class="toggle-indicator">▼</span></label>
  <div class="toggle-content" style="display: none;">
    <div style="display: flex; gap: 8px; margin-bottom: 12px;">
      <button id="saveChainConfigBtn" class="btn small primary">Save Current Chain</button>
      <button id="loadChainConfigsBtn" class="btn small">Load Saved Chains</button>
      <button id="deleteChainConfigBtn" class="btn small danger" style="display:none;">Delete Selected</button>
    </div>
    
    <div id="chainConfigForm" style="display: none; background: #f8f9fa; padding: 12px; border-radius: 4px; margin-bottom: 12px;">
      <div class="field">
        <label>Configuration Name</label>
        <input type="text" id="chainConfigName" placeholder="Enter a descriptive name" style="width: 100%; padding: 6px; font-size: 0.9rem;" />
      </div>
      <div class="field">
        <label>Description</label>
        <textarea id="chainConfigDescription" placeholder="Describe this chain configuration..." style="width: 100%; min-height: 60px; padding: 6px; font-size: 0.9rem;"></textarea>
      </div>
      <div style="display: flex; gap: 8px;">
        <button id="confirmSaveChainBtn" class="btn small primary">Save</button>
        <button id="cancelSaveChainBtn" class="btn small">Cancel</button>
      </div>
    </div>
    
    <div id="savedChainsList" style="display: none;">
      <h4 style="margin-bottom: 8px;">Saved Chain Configurations</h4>
      <div id="chainsContainer" style="max-height: 300px; overflow-y: auto; border: 1px solid var(--border); border-radius: 4px; padding: 8px;"></div>
    </div>
  </div>
</div>
`;

// Inject the new section into the UI (add this to your injectWhenReady function)
function injectChainConfigSection() {
  const contentDiv = host.querySelector('.content');
  const importSection = contentDiv.querySelector('.field:nth-child(4)'); // After import section
  if (importSection) {
    importSection.insertAdjacentHTML('afterend', chainConfigSection);
  }
}

// Add these event listeners to your setupEventListeners function
function setupChainConfigEventListeners() {
  // Save chain configuration
  document.getElementById('saveChainConfigBtn').onclick = showSaveChainForm;
  document.getElementById('confirmSaveChainBtn').onclick = saveChainConfig;
  document.getElementById('cancelSaveChainBtn').onclick = hideSaveChainForm;
  
  // Load saved chains
  document.getElementById('loadChainConfigsBtn').onclick = loadSavedChainConfigs;
  document.getElementById('deleteChainConfigBtn').onclick = deleteSelectedChainConfig;
}

// Chain configuration management functions
function showSaveChainForm() {
  const form = document.getElementById('chainConfigForm');
  const savedList = document.getElementById('savedChainsList');
  
  form.style.display = 'block';
  savedList.style.display = 'none';
  document.getElementById('deleteChainConfigBtn').style.display = 'none';
  
  // Pre-fill with current timestamp as default name
  const timestamp = new Date().toLocaleString();
  document.getElementById('chainConfigName').value = `Chain Config ${timestamp}`;
  document.getElementById('chainConfigDescription').value = '';
}

function hideSaveChainForm() {
  document.getElementById('chainConfigForm').style.display = 'none';
}

async function saveChainConfig() {
  const name = document.getElementById('chainConfigName').value.trim();
  const description = document.getElementById('chainConfigDescription').value.trim();
  
  if (!name) {
    alert('Please enter a name for the chain configuration.');
    return;
  }
  
  if (!window.frameworkSelectionOrder || window.frameworkSelectionOrder.length === 0) {
    alert('No frameworks selected in the current chain.');
    return;
  }
  
  const chainConfig = {
    name: name,
    description: description,
    frameworks: window.frameworkSelectionOrder.map(key => ({
      key: key,
      name: window.frameworks[key]?.name || key,
      mode: window.frameworkChainModes[key] || 'none'
    })),
    timestamp: new Date().toISOString(),
    input_source: window.currentInputData?.source?.type || 'unknown'
  };
  
  try {
    const response = await fetch('/api/chain-configs/save', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(chainConfig)
    });
    
    if (!response.ok) {
      throw new Error(`Failed to save chain configuration: ${response.statusText}`);
    }
    
    const result = await response.json();
    
    if (result.success) {
      if (typeof showToast === 'function') {
        showToast(`Chain configurationf "${name}" saved successfully!`);
      }
      hideSaveChainForm();
      // Refresh the saved chains list
      loadAndApplyChainConfig();
      await loadSavedChainConfigs();
    } else {
      throw new Error(result.message || 'Failed to save chain configuration');
    }
  } catch (error) {
    console.error('Error saving chain configuration:', error);
    alert(`Error saving chain configuration: ${error.message}`);
  }
}

async function loadSavedChainConfigs() {
  try {
    const response = await fetch('/api/chain-configs/list');
    
    if (!response.ok) {
      throw new Error(`Failed to load chain configurations: ${response.statusText}`);
    }
    
    const chainConfigs = await response.json();
    
    const container = document.getElementById('chainsContainer');
    const savedList = document.getElementById('savedChainsList');
    const deleteBtn = document.getElementById('deleteChainConfigBtn');
    
    if (chainConfigs.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--muted); padding: 20px;">No saved chain configurations found.</div>';
    } else {
      container.innerHTML = chainConfigs.map((config, index) => `
        <div class="chain-config-item" style="border: 1px solid var(--border); border-radius: 4px; padding: 12px; margin-bottom: 8px; cursor: pointer; background: white;">
          <div style="display: flex; align-items: flex-start; gap: 12px;">
            <input type="radio" name="selectedChain" value="${config.id}" id="chain_${config.id}" style="margin-top: 2px;" />
            <div style="flex: 1;">
              <div style="font-weight: 600; margin-bottom: 4px;">${config.name}</div>
              ${config.description ? `<div style="font-size: 0.8rem; color: var(--muted); margin-bottom: 6px;">${config.description}</div>` : ''}
              <div style="font-size: 0.75rem; color: var(--muted); margin-bottom: 8px;">
                ${config.frameworks.length} frameworks • ${new Date(config.timestamp).toLocaleDateString()}
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                ${config.frameworks.map(fw => `
                  <span class="pill" style="font-size: 0.7rem; background: var(--brand); color: white; padding: 2px 6px; border-radius: 10px;">
                    ${fw.name}
                  </span>
                `).join('')}
              </div>
            </div>
          </div>
        </div>
      `).join('');
      
      // Add event listeners to radio buttons
      container.querySelectorAll('input[type="radio"]').forEach(radio => {
        radio.addEventListener('change', function() {
          deleteBtn.style.display = this.checked ? 'block' : 'none';
        });
      });
      
      // Add click event to entire item
      container.querySelectorAll('.chain-config-item').forEach(item => {
        item.addEventListener('click', function(e) {
          if (e.target.type !== 'radio') {
            const radio = this.querySelector('input[type="radio"]');
            radio.checked = true;
            radio.dispatchEvent(new Event('change'));
          }
        });
      });
    }
    
    savedList.style.display = 'block';
    document.getElementById('chainConfigForm').style.display = 'none';
    
  } catch (error) {
    console.error('Error loading chain configurations:', error);
    const container = document.getElementById('chainsContainer');
    container.innerHTML = `<div style="color: red; text-align: center; padding: 20px;">Error loading chain configurations: ${error.message}</div>`;
  }
}

async function deleteSelectedChainConfig() {
  const selectedRadio = document.querySelector('input[name="selectedChain"]:checked');
  
  if (!selectedRadio) {
    alert('Please select a chain configuration to delete.');
    return;
  }
  
  const configId = selectedRadio.value;
  const configName = selectedRadio.closest('.chain-config-item').querySelector('div[style*="font-weight: 600"]').textContent;
  
  if (!confirm(`Are you sure you want to delete the chain configuration "${configName}"?`)) {
    return;
  }
  
  try {
    const response = await fetch(`/api/chain-configs/delete/${configId}`, {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      throw new Error(`Failed to delete chain configuration: ${response.statusText}`);
    }
    
    const result = await response.json();
    
    if (result.success) {
      if (typeof showToast === 'function') {
        showToast(`Chain configuration "${configName}" deleted successfully!`);
      }
      await loadSavedChainConfigs();
    } else {
      throw new Error(result.message || 'Failed to delete chain configuration');
    }
  } catch (error) {
    console.error('Error deleting chain configuration:', error);
    alert(`Error deleting chain configuration: ${error.message}`);
  }
}

// Function to apply a saved chain configuration
function applyChainConfig(chainConfig) {
  if (!chainConfig || !chainConfig.frameworks) {
    console.error('Invalid chain configuration');
    return;
  }
  
  // Clear current selection
  window.frameworkSelectionOrder = [];
  window.frameworkChainModes = {};
  
  // Apply the saved configuration
  chainConfig.frameworks.forEach(fw => {
    window.frameworkSelectionOrder.push(fw.key);
    window.frameworkChainModes[fw.key] = fw.mode;
  });
  
  // Update the UI
  if (typeof setupFrameworkCheckboxes === 'function') {
    setupFrameworkCheckboxes();
  }
  
  if (typeof showToast === 'function') {
    showToast(`Applied chain configuration: ${chainConfig.name}`);
  }
}

// Add double-click to load functionality
function setupChainConfigDoubleClick() {
  document.addEventListener('click', function(e) {
    const chainItem = e.target.closest('.chain-config-item');
    if (chainItem && e.detail === 2) { // Double click
      const radio = chainItem.querySelector('input[type="radio"]');
      const configId = radio.value;
      
      // Load and apply the configuration
      loadAndApplyChainConfig(configId);
    }
  });
}

async function loadAndApplyChainConfig(configId) {
  try {
    const response = await fetch(`/api/chain-configs/get/${configId}`);
    
    if (!response.ok) {
      throw new Error(`Failed to load chain configuration: ${response.statusText}`);
    }
    
    const chainConfig = await response.json();
    applyChainConfig(chainConfig);
    
  } catch (error) {
    console.error('Error loading chain configuration:', error);
    alert(`Error loading chain configuration: ${error.message}`);
  }
}
    
    // Generate combined report if available
    if (allResults.combined) {
      const combinedFramework = {
        name: "Combined Multi-Framework Analysis",
        key: "combined"
      };
      
      const pdfDoc = await generatePDFReport("combined", combinedFramework, allResults.combined);
      const pdfBlob = pdfDoc.output('blob');
      saveAs(pdfBlob, `${baseName}_combined_report.pdf`);
    }
    
    if (typeof showToast === 'function') {
      showToast('PDF reports exported successfully!');
    }
    
  } catch (error) {
    console.error('Error exporting PDFs:', error);
    alert(`Error exporting PDFs: ${error.message}`);
  }
}

