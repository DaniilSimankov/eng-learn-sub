(function bootstrapSubLearnConfig(globalScope) {
  globalScope.SUBLEARN_API_BASE = globalScope.SUBLEARN_API_BASE || '';

  globalScope.SubLearnApiUrl = function subLearnApiUrl(path) {
    const base = String(globalScope.SUBLEARN_API_BASE || '').replace(/\/$/, '');
    const normalized = path.startsWith('/') ? path : `/${path}`;
    return `${base}${normalized}`;
  };
}(window));
