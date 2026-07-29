/**
 * llm_client.js — Multi-provider LLM caller
 *
 * Uses model-aware routing:
 *   DeepSeek V4 canonical models          → DeepSeek Anthropic-compatible API (/v1/messages)
 *   default                               → Anthropic-compatible API (/v1/messages)
 *
 * @param {string} systemPrompt
 * @param {string} userMessage
 * @param {Object} options - { apiKey, model, maxTokens }
 * @returns {Promise<string>} extracted text content
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldRetryStatus(status) {
  return status === 429 || status === 408 || status === 409 || status >= 500;
}

function computeBackoffMs(attempt, retryAfterHeader, baseMs = 700) {
  const retryAfter = Number.parseFloat(retryAfterHeader || '');
  if (Number.isFinite(retryAfter) && retryAfter > 0) {
    return Math.max(250, Math.round(retryAfter * 1000));
  }
  const cappedAttempt = Math.min(attempt, 6);
  return baseMs * Math.pow(2, cappedAttempt - 1);
}

async function fetchWithTimeout(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function shouldRetryError(error) {
  if (!error) return false;
  const name = String(error.name || '').toLowerCase();
  const msg = String(error.message || '').toLowerCase();
  return (
    name === 'aborterror' ||
    msg.includes('timed out') ||
    msg.includes('fetch failed') ||
    msg.includes('ecconnreset') ||
    msg.includes('etimedout') ||
    msg.includes('eai_again') ||
    msg.includes('socket hang up')
  );
}

function formatTransportError(provider, error, timeoutMs) {
  if (error && String(error.name || '').toLowerCase() === 'aborterror') {
    return new Error(`${provider} request timed out after ${timeoutMs}ms`);
  }
  const msg = error && error.message ? error.message : String(error);
  return new Error(`${provider} request failed: ${msg}`);
}

const DEEPSEEK_ANTHROPIC_BASE_URL =
  process.env.ANTHROPIC_BASE_URL || 'https://api.deepseek.com/anthropic';

const CANONICAL_DEEPSEEK_MODELS = new Set(['deepseek-v4-pro', 'deepseek-v4-flash']);

function resolveDeepSeekModelName(model) {
  const raw = String(model || '').trim();
  const normalized = raw.toLowerCase();
  if (!normalized) return 'deepseek-v4-pro';
  if (CANONICAL_DEEPSEEK_MODELS.has(normalized)) return normalized;
  if (normalized === 'v4-pro' || normalized === 'v4-flash' || normalized.startsWith('deepseek-')) {
    throw new Error(
      `Unsupported DeepSeek model "${model}". Use "deepseek-v4-pro" or "deepseek-v4-flash".`
    );
  }
  return raw;
}

function buildAnthropicMessagesUrl(baseUrl) {
  const root = String(baseUrl || '').replace(/\/+$/, '');
  if (!root) return 'https://api.deepseek.com/anthropic/v1/messages';
  if (root.endsWith('/v1/messages')) return root;
  if (root.endsWith('/v1')) return `${root}/messages`;
  return `${root}/v1/messages`;
}

async function callLLM(systemPrompt, userMessage, options = {}) {
  const {
    apiKey,
    model = 'deepseek-v4-pro',
    maxTokens = 2048,
    maxRetries = 2,
    retryBaseMs = 700,
    timeoutMs = Number(process.env.LLM_TIMEOUT_MS || 120000)
  } = options;

  if (!apiKey) throw new Error('API key required');

  const resolvedModel = resolveDeepSeekModelName(model);

  const attempts = Math.max(1, Number(maxRetries) + 1);

  for (let attempt = 1; attempt <= attempts; attempt++) {
    // DeepSeek V4 canonical models and other Anthropic-compatible models.
    let response;
    try {
      response = await fetchWithTimeout(buildAnthropicMessagesUrl(DEEPSEEK_ANTHROPIC_BASE_URL), {
        method:  'POST',
        headers: {
          'Content-Type':      'application/json',
          'x-api-key':         apiKey,
          'anthropic-version': '2023-06-01'
        },
        body: JSON.stringify({
          model: resolvedModel,
          max_tokens: maxTokens,
          system:     systemPrompt,
          messages:   [{ role: 'user', content: userMessage }]
        })
      }, timeoutMs);
    } catch (error) {
      if (attempt < attempts && shouldRetryError(error)) {
        const waitMs = computeBackoffMs(attempt, null, retryBaseMs);
        await sleep(waitMs);
        continue;
      }
      throw formatTransportError('Anthropic-compatible', error, timeoutMs);
    }

    if (!response.ok) {
      const errText = await response.text();
      const msg = `Anthropic-compatible API error ${response.status}: ${errText}`;

      if (attempt < attempts && shouldRetryStatus(response.status)) {
        const waitMs = computeBackoffMs(attempt, response.headers.get('retry-after'), retryBaseMs);
        await sleep(waitMs);
        continue;
      }
      throw new Error(msg);
    }

    const data = await response.json();
    return data.content?.map(b => b.text || '').join('') || '';
  }

  throw new Error('LLM request failed after retries');
}

module.exports = { callLLM };
