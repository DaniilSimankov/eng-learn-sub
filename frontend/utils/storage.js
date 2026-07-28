(function bootstrapStorageUtils(globalScope) {
  function safeGet(key, fallback = null) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch {
      return fallback;
    }
  }

  function safeSet(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  }

  function safeRemove(key) {
    try {
      localStorage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  }

  function safeGetJson(key, fallback = null) {
    const raw = safeGet(key, null);
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  function safeSetJson(key, value) {
    return safeSet(key, JSON.stringify(value));
  }

  globalScope.SubLearnStorage = {
    safeGet,
    safeSet,
    safeRemove,
    safeGetJson,
    safeSetJson,
  };
}(window));
