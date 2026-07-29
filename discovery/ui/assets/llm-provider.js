(function () {
  const STORAGE_KEY = "discovery.llm.config.v1";
  const STYLE_ID = "discovery-llm-widget-style";
  const WIDGET_ID = "discovery-llm-widget";

  const PROVIDERS = {
    anthropic: {
      id: "anthropic",
      label: "Anthropic-Compatible API",
      vendor: "DeepSeek",
      endpoint: "https://api.deepseek.com/anthropic/v1/messages",
      models: [
        { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
        { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" }
      ],
      buildRequest({ config, systemPrompt, messages, maxTokens }) {
        return {
          url: this.endpoint,
          headers: {
            "content-type": "application/json",
            "x-api-key": config.apiKey,
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true"
          },
          body: {
            model: config.model,
            max_tokens: maxTokens,
            system: systemPrompt,
            messages: messages.map((message) => ({
              role: message.role === "assistant" ? "assistant" : "user",
              content: String(message.content || "")
            }))
          }
        };
      },
      readText(data) {
        if (!Array.isArray(data.content)) return "";
        return data.content.map((block) => block.text || "").join("").trim();
      },
      readError(data, statusText) {
        return data?.error?.message || data?.message || statusText || "Anthropic-compatible request failed";
      }
    },
    deepseek: {
      id: "deepseek",
      label: "DeepSeek API",
      vendor: "DeepSeek",
      endpoint: "https://api.deepseek.com/v1/chat/completions",
      models: [
        { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
        { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" }
      ],
      buildRequest({ config, systemPrompt, messages, maxTokens, temperature }) {
        return {
          url: this.endpoint,
          headers: {
            "content-type": "application/json",
            authorization: `Bearer ${config.apiKey}`
          },
          body: {
            model: config.model,
            max_tokens: maxTokens,
            temperature,
            messages: [
              { role: "system", content: systemPrompt },
              ...messages.map((message) => ({
                role: message.role === "assistant" ? "assistant" : "user",
                content: String(message.content || "")
              }))
            ]
          }
        };
      },
      readText(data) {
        return data?.choices?.[0]?.message?.content?.trim?.() || "";
      },
      readError(data, statusText) {
        return data?.error?.message || data?.message || statusText || "DeepSeek request failed";
      }
    }
  };

  let widget = null;
  const listeners = new Set();

  function getStoredConfig() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function normalizeConfig(config) {
    const stored = config || {};
    const providerId = PROVIDERS[stored.provider] ? stored.provider : "anthropic";
    const provider = PROVIDERS[providerId];
    const model = provider.models.some((item) => item.value === stored.model)
      ? stored.model
      : provider.models[0].value;

    return {
      provider: providerId,
      model,
      apiKey: typeof stored.apiKey === "string" ? stored.apiKey : ""
    };
  }

  function getConfig() {
    return normalizeConfig(getStoredConfig());
  }

  function notify(config) {
    listeners.forEach((listener) => {
      try {
        listener(config);
      } catch {
      }
    });
  }

  function saveConfig(nextConfig) {
    const normalized = normalizeConfig(nextConfig);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    syncWidget(normalized, "Configura\u00e7\u00e3o salva");
    notify(normalized);
    return normalized;
  }

  function subscribe(listener) {
    listeners.add(listener);
    return function unsubscribe() {
      listeners.delete(listener);
    };
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.tb-llm-toggle{position:fixed;top:72px;right:24px;z-index:320;width:42px;height:42px;border-radius:999px;border:1px solid rgba(196,98,45,.32);background:rgba(25,25,23,.92);backdrop-filter:blur(16px);color:#ede8df;display:flex;align-items:center;justify-content:center;font:600 12px/1 Inter,sans-serif;letter-spacing:.08em;cursor:pointer;box-shadow:0 10px 32px rgba(0,0,0,.28);transition:transform .18s ease,border-color .18s ease,background .18s ease}
.tb-llm-toggle:hover{transform:translateY(-1px);border-color:rgba(196,98,45,.7);background:rgba(38,37,34,.96)}
.tb-llm-toggle span{color:#c4622d}
.tb-llm-panel{position:fixed;top:124px;right:24px;z-index:320;width:min(340px,calc(100vw - 32px));padding:16px;border-radius:14px;border:1px solid rgba(196,98,45,.24);background:rgba(25,25,23,.97);backdrop-filter:blur(18px);box-shadow:0 18px 54px rgba(0,0,0,.38);color:#ede8df;display:none}
.tb-llm-panel.open{display:block}
.tb-llm-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}
.tb-llm-title{font:600 14px/1.3 Lora,Georgia,serif}
.tb-llm-subtitle{margin-top:4px;color:#9a9a96;font:400 11px/1.5 Inter,sans-serif}
.tb-llm-close{border:none;background:transparent;color:#9a9a96;cursor:pointer;font-size:14px;padding:2px 4px}
.tb-llm-grid{display:grid;gap:12px}
.tb-llm-field{display:grid;gap:6px}
.tb-llm-label{font:600 11px/1 Inter,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:#9a9a96}
.tb-llm-input,.tb-llm-select{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #2a2a28;background:#171715;color:#ede8df;font:400 13px/1.4 Inter,sans-serif}
.tb-llm-input:focus,.tb-llm-select:focus{outline:none;border-color:rgba(196,98,45,.55)}
.tb-llm-meta{padding:10px 12px;border-radius:8px;border:1px solid #2a2a28;background:#1f1f1d}
.tb-llm-meta strong{display:block;font:600 11px/1 Inter,sans-serif;color:#ede8df;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.tb-llm-endpoint{word-break:break-all;color:#c4622d;font:500 11px/1.5 JetBrains Mono,monospace}
.tb-llm-status{min-height:18px;color:#9a9a96;font:400 11px/1.4 Inter,sans-serif}
.tb-llm-status.ok{color:#6bcf96}
.tb-llm-status.warn{color:#d4b84e}
.tb-llm-actions{display:flex;gap:8px;justify-content:flex-end}
.tb-llm-btn{padding:9px 12px;border-radius:8px;border:1px solid #363634;background:transparent;color:#ede8df;cursor:pointer;font:500 12px/1 Inter,sans-serif}
.tb-llm-btn:hover{border-color:rgba(196,98,45,.7)}
.tb-llm-btn-primary{background:#c4622d;border-color:#c4622d;color:#191917}
.tb-llm-hint{color:#9a9a96;font:400 11px/1.5 Inter,sans-serif}
@media (max-width: 640px){
  .tb-llm-toggle{top:auto;bottom:18px;right:16px}
  .tb-llm-panel{top:auto;bottom:72px;right:16px}
}
`;
    document.head.appendChild(style);
  }

  function buildWidget(options) {
    if (widget) return widget;
    injectStyles();

    const root = document.createElement("div");
    root.id = WIDGET_ID;
    root.innerHTML = `
      <button class="tb-llm-toggle" type="button" title="Configurar IA"><span>AA</span></button>
      <div class="tb-llm-panel" aria-hidden="true">
        <div class="tb-llm-head">
          <div>
            <div class="tb-llm-title"></div>
            <div class="tb-llm-subtitle"></div>
          </div>
          <button class="tb-llm-close" type="button">&#10005;</button>
        </div>
        <div class="tb-llm-grid">
          <label class="tb-llm-field">
            <span class="tb-llm-label">Provider</span>
            <select class="tb-llm-select" data-role="provider" name="llmProvider"></select>
          </label>
          <label class="tb-llm-field">
            <span class="tb-llm-label">Modelo</span>
            <select class="tb-llm-select" data-role="model" name="llmModel"></select>
          </label>
          <label class="tb-llm-field">
            <span class="tb-llm-label">API Key</span>
            <input class="tb-llm-input" data-role="apiKey" name="llmApiKey" type="password" placeholder="Cole sua chave aqui" autocomplete="off">
          </label>
          <div class="tb-llm-meta">
            <strong>Endpoint</strong>
            <div class="tb-llm-endpoint" data-role="endpoint"></div>
          </div>
          <div class="tb-llm-hint">A chave fica salva apenas neste navegador via localStorage.</div>
          <div class="tb-llm-status" data-role="status"></div>
          <div class="tb-llm-actions">
            <button class="tb-llm-btn" type="button" data-role="close">Fechar</button>
            <button class="tb-llm-btn tb-llm-btn-primary" type="button" data-role="save">Salvar</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(root);

    widget = {
      root,
      toggle: root.querySelector(".tb-llm-toggle"),
      panel: root.querySelector(".tb-llm-panel"),
      title: root.querySelector(".tb-llm-title"),
      subtitle: root.querySelector(".tb-llm-subtitle"),
      provider: root.querySelector('[data-role="provider"]'),
      model: root.querySelector('[data-role="model"]'),
      apiKey: root.querySelector('[data-role="apiKey"]'),
      endpoint: root.querySelector('[data-role="endpoint"]'),
      status: root.querySelector('[data-role="status"]')
    };

    widget.title.textContent = options?.title || "Configura\u00e7\u00e3o de IA";
    widget.subtitle.textContent = options?.subtitle || "DeepSeek Anthropic-compatible and DeepSeek API integration for Discovery.";

    widget.provider.innerHTML = Object.values(PROVIDERS)
      .map((provider) => `<option value="${provider.id}">${provider.label}</option>`)
      .join("");

    widget.toggle.addEventListener("click", togglePanel);
    root.querySelector(".tb-llm-close").addEventListener("click", closeConfig);
    root.querySelector('[data-role="close"]').addEventListener("click", closeConfig);

    widget.provider.addEventListener("change", () => {
      const config = normalizeConfig({
        provider: widget.provider.value,
        model: widget.model.value,
        apiKey: widget.apiKey.value
      });
      syncWidget(config, "Provider alterado. Clique em salvar.");
    });

    root.querySelector('[data-role="save"]').addEventListener("click", () => {
      saveConfig({
        provider: widget.provider.value,
        model: widget.model.value,
        apiKey: widget.apiKey.value.trim()
      });
    });

    document.addEventListener("click", (event) => {
      if (!widget) return;
      if (!widget.root.contains(event.target) && widget.panel.classList.contains("open")) {
        closeConfig();
      }
    });

    syncWidget(getConfig());
    return widget;
  }

  function renderModels(providerId, selectedModel) {
    const provider = PROVIDERS[providerId] || PROVIDERS.anthropic;
    widget.model.innerHTML = provider.models
      .map((model) => `<option value="${model.value}">${model.label}</option>`)
      .join("");
    widget.model.value = provider.models.some((model) => model.value === selectedModel)
      ? selectedModel
      : provider.models[0].value;
  }

  function syncWidget(config, statusText) {
    if (!widget) return;
    const normalized = normalizeConfig(config);
    renderModels(normalized.provider, normalized.model);
    widget.provider.value = normalized.provider;
    widget.model.value = normalized.model;
    widget.apiKey.value = normalized.apiKey;
    widget.endpoint.textContent = PROVIDERS[normalized.provider].endpoint;
    const missingKey = !normalized.apiKey;
    widget.status.textContent = statusText || (missingKey ? "Adicione uma API key para habilitar o chat." : "Configura\u00e7\u00e3o pronta para uso.");
    widget.status.className = `tb-llm-status ${missingKey ? "warn" : "ok"}`;
  }

  function openConfig() {
    if (!widget) buildWidget();
    widget.panel.classList.add("open");
    widget.panel.setAttribute("aria-hidden", "false");
    syncWidget(getConfig());
    widget.apiKey.focus();
  }

  function closeConfig() {
    if (!widget) return;
    widget.panel.classList.remove("open");
    widget.panel.setAttribute("aria-hidden", "true");
  }

  function togglePanel() {
    if (!widget) buildWidget();
    if (widget.panel.classList.contains("open")) {
      closeConfig();
    } else {
      openConfig();
    }
  }

  function mountConfigWidget(options) {
    buildWidget(options || {});
    return api;
  }

  async function sendChat(options) {
    const config = getConfig();
    const provider = PROVIDERS[config.provider];

    if (!config.apiKey) {
      throw new Error("Configure a API key antes de usar o chat.");
    }

    const request = provider.buildRequest({
      config,
      systemPrompt: String(options.systemPrompt || ""),
      messages: Array.isArray(options.messages) ? options.messages : [],
      maxTokens: Number(options.maxTokens || 1000),
      temperature: typeof options.temperature === "number" ? options.temperature : 0.2
    });

    const response = await fetch(request.url, {
      method: "POST",
      headers: request.headers,
      body: JSON.stringify(request.body)
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(provider.readError(data, response.statusText));
    }

    const text = provider.readText(data);
    if (!text) {
      throw new Error("O provider retornou uma resposta vazia.");
    }

    return {
      text,
      provider: provider.id,
      model: config.model,
      data
    };
  }

  const api = {
    providers: PROVIDERS,
    getConfig,
    saveConfig,
    subscribe,
    mountConfigWidget,
    openConfig,
    closeConfig,
    hasApiKey() {
      return Boolean(getConfig().apiKey);
    },
    sendChat
  };

  window.DiscoveryLLM = api;
})();