(function bootstrapApiClient(globalScope) {
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
    aiStatus: () => requestJson('/api/ai-status'),
    aiWarm: () => requestJson('/api/ai-warm', { method: 'POST' }),
    searchCatalog: ({ q, type = '', limit = 15 }) => {
      const params = new URLSearchParams({ q, limit: String(limit) });
      if (type) params.set('type', type);
      return requestJson(`/api/search?${params.toString()}`);
    },
    sourceAuthLogin: (payload) => requestJson('/api/source-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    sourceAuthClear: () => requestJson('/api/source-auth', { method: 'DELETE' }),
    resolvePage: (url) => requestJson(`/api/resolve?url=${encodeURIComponent(url)}`),
    loadSubtitles: (url) => requestText(`/api/subtitles?url=${encodeURIComponent(url)}`),
    explain: (payload) => requestJson('/api/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    translate: ({ text = '', word = '', sentence = '', engine = 'google' }) => {
      const params = new URLSearchParams();
      if (text) params.set('text', text);
      if (word) params.set('word', word);
      if (sentence) params.set('sentence', sentence);
      params.set('engine', engine);
      return requestJson(`/api/translate?${params.toString()}`);
    },
    vocabList: () => requestJson('/api/vocab'),
    vocabImport: (items) => requestJson('/api/vocab/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),
    vocabAdd: (payload) => requestJson('/api/vocab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    vocabDelete: (id) => requestJson(`/api/vocab?id=${encodeURIComponent(id)}`, { method: 'DELETE' }),
    vocabClear: () => requestJson('/api/vocab', { method: 'DELETE' }),
  };

  globalScope.SubLearnApi = api;
}(window));
