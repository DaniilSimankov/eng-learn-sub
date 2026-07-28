(function bootstrapApiClient(globalScope) {
  const apiUrl = (path) => (
    typeof globalScope.SubLearnApiUrl === 'function'
      ? globalScope.SubLearnApiUrl(path)
      : path
  );

  async function requestJson(url, options = {}) {
    let res;
    try {
      res = await fetch(url, options);
    } catch (err) {
      const msg = err?.message || 'Ошибка сети';
      throw new Error(msg);
    }
    let data = {};
    try {
      data = await res.json();
    } catch {
      if (!res.ok) throw new Error(`Ошибка сервера (${res.status})`);
      return {};
    }
    if (!res.ok) throw new Error(data.error || `Ошибка сервера (${res.status})`);
    return data;
  }

  async function requestText(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error(`Ошибка сервера (${res.status})`);
    return res.text();
  }

  const api = {
    aiStatus: () => requestJson(apiUrl('/api/ai-status')),
    aiWarm: () => requestJson(apiUrl('/api/ai-warm'), { method: 'POST' }),
    searchCatalog: ({ q, type = '', limit = 15 }) => {
      const params = new URLSearchParams({ q, limit: String(limit) });
      if (type) params.set('type', type);
      return requestJson(apiUrl(`/api/search?${params.toString()}`));
    },
    sourceAuthLogin: (payload) => requestJson(apiUrl('/api/source-auth'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    sourceAuthClear: () => requestJson(apiUrl('/api/source-auth'), { method: 'DELETE' }),
    resolvePage: (url) => requestJson(apiUrl(`/api/resolve?url=${encodeURIComponent(url)}`)),
    loadSubtitles: (url) => requestText(apiUrl(`/api/subtitles?url=${encodeURIComponent(url)}`)),
    explain: (payload) => requestJson(apiUrl('/api/explain'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    translate: ({ text = '', word = '', sentence = '', engine = 'google', tier = 'auto' }) => {
      const params = new URLSearchParams();
      if (text) params.set('text', text);
      if (word) params.set('word', word);
      if (sentence) params.set('sentence', sentence);
      params.set('engine', engine);
      if (tier && tier !== 'auto') params.set('tier', tier);
      return requestJson(apiUrl(`/api/translate?${params.toString()}`));
    },
    vocabList: () => requestJson(apiUrl('/api/vocab')),
    vocabImport: (items) => requestJson(apiUrl('/api/vocab/import'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),
    vocabAdd: (payload) => requestJson(apiUrl('/api/vocab'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    vocabDelete: (id) => requestJson(apiUrl(`/api/vocab?id=${encodeURIComponent(id)}`), { method: 'DELETE' }),
    vocabClear: () => requestJson(apiUrl('/api/vocab'), { method: 'DELETE' }),
  };

  globalScope.SubLearnApi = api;
}(window));
