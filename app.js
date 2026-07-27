/**
 * SubLearn — интерактивный плеер для изучения английского по субтитрам
 */

const STORAGE_KEY = 'sublearn-vocabulary';
const SKIP_ADS_KEY = 'sublearn-skip-ads';
const ONLINE_TRANSLATION_KEY = 'sublearn-online-translation';
const AUDIO_LANG_KEY = 'sublearn-audio-lang';
const QUALITY_LEVEL_KEY = 'sublearn-quality-level';
const LEARN_PANEL_H_KEY = 'sublearn-learn-panel-h';
const SUBS_SIZE_KEY = 'sublearn-subs-size';
const SUBS_POS_KEY = 'sublearn-subs-pos';
const PAGE_URL_KEY = 'sublearn-page-url';
const SEEK_STEP_KEY = 'sublearn-seek-step';
const NET_MODE_KEY = 'sublearn-net-mode';
const NET_PROXY_KEY = 'sublearn-net-proxy';
const LEARN_PANEL_H_DEFAULT = 200;
const LEARN_PANEL_H_MIN = 140;
const LEARN_PANEL_H_MAX_RATIO = 0.55;
const SUBS_SIZE_DEFAULT_PCT = 100;

function loadSeekStep() {
  try {
    const n = Number(localStorage.getItem(SEEK_STEP_KEY));
    if (n === 3 || n === 5 || n === 10) return n;
  } catch { /* ignore */ }
  return 10;
}

function saveSeekStep(sec) {
  const n = [3, 5, 10].includes(sec) ? sec : 10;
  state.seekStep = n;
  try {
    localStorage.setItem(SEEK_STEP_KEY, String(n));
  } catch { /* ignore */ }
}

const state = {
  mode: 'url', // 'url' | 'file'
  playbackMode: 'video', // 'video' | 'iframe'
  videoFile: null,
  subsFile: null,
  cues: [],
  currentCueIndex: -1,
  lastPopupWord: null,
  wordAnchorIndex: null,
  wordDrag: null,
  ignorePopupHideUntil: 0,
  preferredVoiceURI: null,
  translationCache: new Map(),
  vocabulary: [],
  resolved: null,
  selectedPlayer: null,
  hls: null,
  preferredAudioLang: loadPreferredAudioLang(),
  skipAds: loadSkipAdsPref(),
  onlineTranslation: loadOnlineTranslationPref(),
  subsScale: loadSubsScale(),
  seekStep: loadSeekStep(),
  subsEditMode: false,
  subsDrag: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const videoInput = $('#video-input');
const subsInput = $('#subs-input');
const subsInputUrl = $('#subs-input-url');
const videoName = $('#video-name');
const subsName = $('#subs-name');
const subsNameUrl = $('#subs-name-url');
const btnStart = $('#btn-start');
const btnStartUrl = $('#btn-start-url');
const btnResolve = $('#btn-resolve');
const pageUrl = $('#page-url');
const resolveStatus = $('#resolve-status');
const resolvedInfo = $('#resolved-info');
const resolvedTitle = $('#resolved-title');
const resolvedYlitron = $('#resolved-ylitron');
const resolvedYlitronId = $('#resolved-ylitron-id');
const resolvedYlitronPath = $('#resolved-ylitron-path');
const playerPicker = $('#player-picker');
const setupPanel = $('#setup-panel');
const playerSection = $('#player-section');
const playerTitle = $('#player-title');
const video = $('#video');
const embedFrame = $('#embed-frame');
const playerLoading = $('#player-loading');
const iframeNotice = $('#iframe-notice');
const playbackError = $('#playback-error');
const subtitleDisplay = $('#subtitle-display');
const subtitleTranslation = $('#subtitle-translation');
const subtitleMeta = $('#subtitle-meta');
const subtitleHint = $('#subtitle-hint');
const speedSelect = $('#speed-select');
const pauseOnWord = $('#pause-on-word');
const showRuInline = $('#show-ru-inline');
const wordPopup = $('#word-popup');
const popupWord = $('#popup-word');
const popupTranslation = $('#popup-translation');
const popupTranslationNote = $('#popup-translation-note');
const popupContext = $('#popup-context');
const vocabDrawer = $('#vocab-drawer');
const vocabList = $('#vocab-list');
const vocabEmpty = $('#vocab-empty');
const vocabCount = $('#vocab-count');
const manualTime = $('#manual-time');
const manualSync = $('#manual-sync');
const skipAdsSetup = $('#skip-ads');
const skipAdsLive = $('#skip-ads-live');
const skipAdsLiveWrap = $('#skip-ads-live-wrap');
const onlineTranslationSetup = $('#online-translation');
const aiStatusEl = $('#ai-status');
const audioTrackWrap = $('#audio-track-wrap');
const audioTrackSelect = $('#audio-track-select');
const qualityTrackWrap = $('#quality-track-wrap');
const qualityTrackSelect = $('#quality-track-select');
const subtitleTrackWrap = $('#subtitle-track-wrap');
const subtitleTrackSelect = $('#subtitle-track-select');
const subsSizeRange = $('#subs-size-range');
const subsSizeValue = $('#subs-size-value');
const btnSubsEdit = $('#btn-subs-edit');
const subtitlePanel = $('.subtitle-panel');
const playerChrome = $('#player-chrome');
const playerMenu = $('#player-menu');
const chromePlay = $('#chrome-play');
const chromeSeek = $('#chrome-seek');
const chromeTime = $('#chrome-time');
const chromeMute = $('#chrome-mute');
const chromeVolume = $('#chrome-volume');
const chromeMenuBtn = $('#chrome-menu-btn');
const videoShell = $('#video-shell');
const playerWrap = $('#player-wrap');
const seekStepSelect = $('#seek-step-select');

video.controls = false;

if (seekStepSelect) {
  seekStepSelect.value = String(state.seekStep);
  seekStepSelect.addEventListener('change', () => {
    saveSeekStep(Number(seekStepSelect.value));
  });
}

if (skipAdsSetup) skipAdsSetup.checked = state.skipAds;
if (skipAdsLive) skipAdsLive.checked = state.skipAds;
if (onlineTranslationSetup) onlineTranslationSetup.checked = state.onlineTranslation;

try {
  const savedPageUrl = localStorage.getItem(PAGE_URL_KEY);
  if (savedPageUrl && pageUrl) pageUrl.value = savedPageUrl;
} catch { /* ignore */ }

function savePageUrl(url) {
  try {
    if (url) localStorage.setItem(PAGE_URL_KEY, url);
  } catch { /* ignore */ }
}

pageUrl?.addEventListener('change', () => {
  const url = pageUrl.value.trim();
  if (url) savePageUrl(url);
});
pageUrl?.addEventListener('blur', () => {
  const url = pageUrl.value.trim();
  if (url) savePageUrl(url);
});

// --- Mode tabs ---

$$('.mode-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    state.mode = tab.dataset.mode;
    $$('.mode-tab').forEach((t) => t.classList.toggle('is-active', t === tab));
    $('#setup-url').classList.toggle('hidden', state.mode !== 'url');
    $('#setup-file').classList.toggle('hidden', state.mode !== 'file');
  });
});

// --- File mode ---

videoInput.addEventListener('change', (e) => {
  state.videoFile = e.target.files[0] || null;
  videoName.textContent = state.videoFile?.name || 'Не выбрано';
  updateStartButton();
});

subsInput.addEventListener('change', async (e) => {
  await loadSubsFile(e.target.files[0], subsName);
  updateStartButton();
});

subsInputUrl.addEventListener('change', async (e) => {
  await loadSubsFile(e.target.files[0], subsNameUrl);
  updateStartUrlButton();
});

btnStart.addEventListener('click', () => startFilePlayer());
btnStartUrl.addEventListener('click', () => startUrlPlayer());
btnResolve.addEventListener('click', resolvePageUrl);
pageUrl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') resolvePageUrl();
});

$('#btn-back-setup').addEventListener('click', backToSetup);
$('#btn-learn-fs')?.addEventListener('click', toggleLearnFullscreen);
$('#btn-exit-fs')?.addEventListener('click', exitLearnFullscreen);
document.addEventListener('fullscreenchange', syncLearnFullscreenUI);
document.addEventListener('webkitfullscreenchange', syncLearnFullscreenUI);
initLearnPanelResize();
$('#btn-replay-line').addEventListener('click', replayCurrentLine);
$('#btn-prev-cue').addEventListener('click', () => stepCue(-1));
$('#btn-next-cue').addEventListener('click', () => stepCue(1));
$('#btn-sync-time').addEventListener('click', syncByManualTime);

speedSelect.addEventListener('change', () => {
  if (state.playbackMode === 'video') {
    video.playbackRate = parseFloat(speedSelect.value);
  }
});

audioTrackSelect?.addEventListener('change', () => {
  const idx = Number(audioTrackSelect.value);
  if (Number.isNaN(idx)) return;

  const names = state.selectedPlayer?.audioTrackNames || [];
  if (names.length > 1 && idx < names.length) {
    const name = names[idx] || '';
    savePreferredAudioLang(/eng|original/i.test(name) ? 'en' : 'ru');
    applyAudioFromPreference();
    renderAudioTrackUI();
    return;
  }

  if (state.hls?.audioTracks?.length) {
    state.hls.audioTrack = idx;
    savePreferredAudioLang(state.hls.audioTracks[idx]?.lang);
    renderAudioTrackUI();
    return;
  }

  if (video.audioTracks?.length > 1 && idx < video.audioTracks.length) {
    for (let i = 0; i < video.audioTracks.length; i++) {
      video.audioTracks[i].enabled = i === idx;
    }
    savePreferredAudioLang(video.audioTracks[idx]?.language);
    renderAudioTrackUI();
  }
});

subtitleTrackSelect?.addEventListener('change', async () => {
  const idx = Number(subtitleTrackSelect.value);
  const track = state.selectedPlayer?.subtitleTracks?.[idx];
  if (track) await loadSubtitleTrack(track);
});

qualityTrackSelect?.addEventListener('change', () => {
  if (!state.hls) return;
  const val = Number(qualityTrackSelect.value);
  if (Number.isNaN(val)) return;
  state.hls.currentLevel = val;
  try {
    localStorage.setItem(QUALITY_LEVEL_KEY, String(val));
  } catch { /* ignore */ }
  renderQualityUI();
});

showRuInline.addEventListener('change', () => {
  if (state.currentCueIndex >= 0) renderCurrentCue();
});

function loadOnlineTranslationPref() {
  try {
    return localStorage.getItem(ONLINE_TRANSLATION_KEY) === '1';
  } catch {
    return false;
  }
}

function saveOnlineTranslationPref(value) {
  state.onlineTranslation = value;
  try {
    localStorage.setItem(ONLINE_TRANSLATION_KEY, value ? '1' : '0');
  } catch { /* ignore */ }
  if (onlineTranslationSetup) onlineTranslationSetup.checked = value;
}

function bindOnlineTranslationToggle(el) {
  if (!el) return;
  el.addEventListener('change', () => saveOnlineTranslationPref(el.checked));
}

bindOnlineTranslationToggle(onlineTranslationSetup);
refreshAiStatus();
setInterval(refreshAiStatus, 15000);

const netModeSelect = $('#net-mode');
const netProxyInput = $('#net-proxy');
const netProxyWrap = $('#net-proxy-wrap');
const netStatusEl = $('#net-status');
const btnNetCheck = $('#btn-net-check');

function loadNetModePref() {
  try {
    const m = localStorage.getItem(NET_MODE_KEY);
    return m === 'split' ? 'split' : 'direct';
  } catch {
    return 'direct';
  }
}

function loadNetProxyPref() {
  try {
    return localStorage.getItem(NET_PROXY_KEY) || 'http://host.docker.internal:7890';
  } catch {
    return 'http://host.docker.internal:7890';
  }
}

function syncNetProxyVisibility() {
  const split = netModeSelect?.value === 'split';
  netProxyWrap?.classList.toggle('hidden', !split);
}

async function pushNetConfigToServer() {
  const mode = netModeSelect?.value === 'split' ? 'split' : 'direct';
  const proxy = (netProxyInput?.value || '').trim();
  try {
    localStorage.setItem(NET_MODE_KEY, mode);
    localStorage.setItem(NET_PROXY_KEY, proxy);
  } catch { /* ignore */ }
  const res = await fetch('/api/net-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, proxy }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Не удалось сохранить сеть');
  return data;
}

function setNetStatus(text, kind = '') {
  if (!netStatusEl) return;
  netStatusEl.textContent = text;
  netStatusEl.classList.remove('is-ok', 'is-err');
  if (kind) netStatusEl.classList.add(kind);
}

async function checkNetStatus() {
  setNetStatus('Проверяю…');
  try {
    await pushNetConfigToServer();
    const res = await fetch('/api/net-status');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Ошибка проверки');
    const dIp = data.direct?.ip || '—';
    const pIp = data.proxyProbe?.ip;
    const pErr = data.proxyProbe?.error;
    if (data.mode === 'split') {
      if (!data.proxy) {
        setNetStatus('Сплит: укажите прокси', 'is-err');
        return;
      }
      if (pErr) {
        setNetStatus(`Прямой ${dIp} · прокси ошибка: ${pErr}`, 'is-err');
        return;
      }
      setNetStatus(`Прямой ${dIp} · через прокси ${pIp || '—'}`, 'is-ok');
    } else {
      setNetStatus(`Прямой IP: ${dIp}`, data.direct?.ok ? 'is-ok' : 'is-err');
    }
  } catch (err) {
    setNetStatus(err?.message || 'Ошибка сети', 'is-err');
  }
}

if (netModeSelect) {
  netModeSelect.value = loadNetModePref();
  if (netProxyInput) netProxyInput.value = loadNetProxyPref();
  syncNetProxyVisibility();
  netModeSelect.addEventListener('change', () => {
    syncNetProxyVisibility();
    pushNetConfigToServer().catch((err) => setNetStatus(err.message, 'is-err'));
  });
  netProxyInput?.addEventListener('change', () => {
    pushNetConfigToServer().catch((err) => setNetStatus(err.message, 'is-err'));
  });
  btnNetCheck?.addEventListener('click', checkNetStatus);
  pushNetConfigToServer().catch(() => {});
}

async function refreshAiStatus() {
  if (!aiStatusEl) return;
  try {
    const res = await fetch('/api/ai-status');
    const data = await res.json();
    aiStatusEl.classList.remove('is-ok', 'is-warn', 'is-err');
    if (!data.ok) {
      aiStatusEl.textContent = 'Ollama выкл';
      aiStatusEl.classList.add('is-err');
      aiStatusEl.title = data.error || 'Запустите ./start.sh';
      return;
    }
    if (!data.ready) {
      aiStatusEl.textContent = 'модель…';
      aiStatusEl.classList.add('is-warn');
      aiStatusEl.title = data.error || `Скачивается ${data.model}`;
      return;
    }
    aiStatusEl.textContent = data.model || 'ok';
    aiStatusEl.classList.add('is-ok');
    aiStatusEl.title = `Локальная модель готова: ${data.model}`;
  } catch {
    aiStatusEl.textContent = 'нет связи';
    aiStatusEl.classList.remove('is-ok', 'is-warn');
    aiStatusEl.classList.add('is-err');
    aiStatusEl.title = 'Сервер SubLearn недоступен';
  }
}

function loadPreferredAudioLang() {
  try {
    return localStorage.getItem(AUDIO_LANG_KEY) || 'en';
  } catch {
    return 'en';
  }
}

function savePreferredAudioLang(lang) {
  const code = (lang || 'en').toLowerCase().slice(0, 2);
  state.preferredAudioLang = code;
  try {
    localStorage.setItem(AUDIO_LANG_KEY, code);
  } catch { /* ignore */ }
}

function formatAudioTrackLabel(track, index = 0) {
  const lang = (track.lang || track.language || '').toLowerCase();
  const name = track.name || '';
  if (lang.startsWith('en') || /eng/i.test(name)) return 'English (оригинал)';
  if (lang.startsWith('ru') || /rus/i.test(name)) return 'Русский (дубляж)';
  return name || lang || `Дорожка ${index + 1}`;
}

function labelForHlsTrack(track, hlsIndex) {
  const names = state.selectedPlayer?.audioTrackNames || [];
  const lang = (track.lang || '').toLowerCase();
  const trackName = track.name || '';

  if (names.length) {
    if (lang.startsWith('en') || /eng/i.test(trackName)) {
      const match = names.find((n) => /eng|original/i.test(n));
      if (match) return match;
    }
    if (lang.startsWith('ru') || /rus/i.test(trackName)) {
      const match = names.find((n) => !/eng|original/i.test(n));
      if (match) return match;
    }
  }
  return formatAudioTrackLabel(track, hlsIndex);
}

function getDisplayAudioTracks() {
  if (!state.hls?.audioTracks?.length) return [];
  const seen = new Set();
  const result = [];
  state.hls.audioTracks.forEach((track, index) => {
    const lang = (track.lang || '').toLowerCase();
    const key = lang.startsWith('en') ? 'en' : lang.startsWith('ru') ? 'ru' : `${lang}:${track.name || index}`;
    if (seen.has(key)) return;
    seen.add(key);
    result.push({ track, index });
  });
  return result;
}

function findPreferredAudioTrackIndex(tracks) {
  if (!tracks?.length) return -1;
  const pref = state.preferredAudioLang || 'en';
  const byLang = tracks.findIndex((t) => (t.lang || t.language || '').toLowerCase().startsWith(pref));
  if (byLang >= 0) return byLang;
  if (pref === 'en') {
    const byName = tracks.findIndex((t) => /eng/i.test(t.name || ''));
    if (byName >= 0) return byName;
  }
  if (pref === 'ru') {
    const byName = tracks.findIndex((t) => /rus/i.test(t.name || ''));
    if (byName >= 0) return byName;
  }
  const def = tracks.findIndex((t) => t.default);
  return def >= 0 ? def : 0;
}

function updateAudioTrackUI(currentIndex = null) {
  if (!audioTrackWrap || !audioTrackSelect) return;

  if (state.hls?.audioTracks?.length) {
    const displayTracks = getDisplayAudioTracks();
    const current = currentIndex ?? state.hls.audioTrack ?? 0;
    if (displayTracks.length <= 1) {
      audioTrackWrap.classList.add('hidden');
      audioTrackSelect.innerHTML = '';
      return;
    }
    audioTrackWrap.classList.remove('hidden');
    audioTrackSelect.innerHTML = displayTracks
      .map(({ track, index }) => {
        const label = labelForHlsTrack(track, index);
        return `<option value="${index}" ${index === current ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      })
      .join('');
    return;
  }

  if (video.audioTracks?.length > 1) {
    const tracks = Array.from(video.audioTracks);
    const current = tracks.findIndex((t) => t.enabled);
    audioTrackWrap.classList.remove('hidden');
    audioTrackSelect.innerHTML = tracks
      .map((track, i) => {
        const label = formatAudioTrackLabel({ lang: track.language, name: track.label }, i);
        return `<option value="${i}" ${i === (current >= 0 ? current : 0) ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      })
      .join('');
    return;
  }

  audioTrackWrap.classList.add('hidden');
  audioTrackSelect.innerHTML = '';
}

function applyPreferredAudioTrack() {
  if (state.hls?.audioTracks?.length) {
    const display = getDisplayAudioTracks();
    const pref = state.preferredAudioLang || 'en';
    let idx = display.find(({ track }) => (track.lang || '').toLowerCase().startsWith(pref))?.index;
    if (idx == null && pref === 'en') {
      idx = display.find(({ track }) => /eng/i.test(track.name || ''))?.index;
    }
    if (idx == null && pref === 'ru') {
      idx = display.find(({ track }) => /rus/i.test(track.name || ''))?.index;
    }
    if (idx == null) idx = display[0]?.index ?? 0;
    if (state.hls.audioTrack !== idx) state.hls.audioTrack = idx;
    updateAudioTrackUI(idx);
    return;
  }

  if (video.audioTracks?.length > 1) {
    const tracks = Array.from(video.audioTracks);
    const idx = findPreferredAudioTrackIndex(
      tracks.map((t, i) => ({ lang: t.language, name: t.label, default: t.enabled && i === 0 }))
    );
    if (idx >= 0) {
      for (let i = 0; i < video.audioTracks.length; i++) {
        video.audioTracks[i].enabled = i === idx;
      }
    }
    updateAudioTrackUI(idx);
  }
}

function hideAudioTrackUI() {
  audioTrackWrap?.classList.add('hidden');
  if (audioTrackSelect) audioTrackSelect.innerHTML = '';
}

function findHlsAudioIndex(preferEnglish) {
  if (!state.hls?.audioTracks?.length) return -1;
  const tracks = state.hls.audioTracks;
  let idx = tracks.findIndex((t) => {
    const lang = (t.lang || '').toLowerCase();
    const name = (t.name || '').toLowerCase();
    return preferEnglish
      ? lang.startsWith('en') || name.includes('eng')
      : lang.startsWith('ru') || name.includes('rus') || name.includes('amedia');
  });
  if (idx >= 0) return idx;
  return preferEnglish ? Math.min(1, tracks.length - 1) : 0;
}

function applyAudioFromPreference() {
  const names = state.selectedPlayer?.audioTrackNames || [];
  const preferEnglish = (state.preferredAudioLang || 'en') === 'en';

  if (state.hls?.audioTracks?.length) {
    const idx = findHlsAudioIndex(preferEnglish);
    if (idx >= 0 && state.hls.audioTrack !== idx) {
      state.hls.audioTrack = idx;
    }
    return;
  }

  if (video.audioTracks?.length > 1) {
    const idx = findHlsAudioIndex(preferEnglish);
    if (idx >= 0) {
      for (let i = 0; i < video.audioTracks.length; i++) {
        video.audioTracks[i].enabled = i === idx;
      }
    }
  }
}

function renderAudioTrackUI() {
  const names = state.selectedPlayer?.audioTrackNames || [];
  if (!audioTrackWrap || !audioTrackSelect) return;

  if (names.length > 1) {
    const pref = state.preferredAudioLang || 'en';
    let selectedIdx = names.findIndex((name) => (
      pref === 'en' ? /eng|original/i.test(name) : !/eng|original/i.test(name)
    ));
    if (selectedIdx < 0) selectedIdx = pref === 'en' ? names.length - 1 : 0;

    audioTrackWrap.classList.remove('hidden');
    audioTrackSelect.innerHTML = names
      .map((name, i) => `<option value="${i}" ${i === selectedIdx ? 'selected' : ''}>${escapeHtml(name)}</option>`)
      .join('');
    return;
  }

  const displayTracks = getDisplayAudioTracks();
  if (displayTracks.length > 1) {
    const current = state.hls?.audioTrack ?? 0;
    audioTrackWrap.classList.remove('hidden');
    audioTrackSelect.innerHTML = displayTracks
      .map(({ track, index }) => {
        const label = labelForHlsTrack(track, index);
        return `<option value="${index}" ${index === current ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      })
      .join('');
    return;
  }

  hideAudioTrackUI();
}

function syncAudioTracksUI() {
  applyAudioFromPreference();
  renderAudioTrackUI();
}

function formatQualityLabel(level) {
  if (level.height) return `${level.height}p`;
  if (level.width && level.height) return `${level.width}×${level.height}`;
  return 'Поток';
}

function getDisplayQualityLevels() {
  if (!state.hls?.levels?.length) return [];
  const byHeight = new Map();
  state.hls.levels.forEach((level, index) => {
    const key = level.height || level.bitrate || index;
    const prev = byHeight.get(key);
    if (!prev || (level.bitrate || 0) > (prev.level.bitrate || 0)) {
      byHeight.set(key, { level, index });
    }
  });
  return Array.from(byHeight.values()).sort(
    (a, b) => (b.level.height || b.level.bitrate || 0) - (a.level.height || a.level.bitrate || 0)
  );
}

function hideQualityUI() {
  qualityTrackWrap?.classList.add('hidden');
  if (qualityTrackSelect) qualityTrackSelect.innerHTML = '';
}

function loadQualityPref() {
  try {
    const val = localStorage.getItem(QUALITY_LEVEL_KEY);
    if (val === null || val === '-1') return -1;
    const num = Number(val);
    return Number.isNaN(num) ? -1 : num;
  } catch {
    return -1;
  }
}

function applyQualityPreference() {
  if (!state.hls?.levels?.length) return;
  const pref = loadQualityPref();
  if (pref < 0) {
    state.hls.currentLevel = -1;
    return;
  }
  const available = getDisplayQualityLevels().some(({ index }) => index === pref);
  state.hls.currentLevel = available ? pref : -1;
}

function renderQualityUI() {
  if (!qualityTrackWrap || !qualityTrackSelect) return;
  const levels = getDisplayQualityLevels();
  if (levels.length <= 1) {
    hideQualityUI();
    return;
  }

  const current = state.hls?.currentLevel ?? -1;
  qualityTrackWrap.classList.remove('hidden');
  qualityTrackSelect.innerHTML = [
    `<option value="-1" ${current === -1 ? 'selected' : ''}>Авто</option>`,
    ...levels.map(({ level, index }) => {
      const label = formatQualityLabel(level);
      return `<option value="${index}" ${index === current ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    }),
  ].join('');
}

function syncQualityUI() {
  applyQualityPreference();
  renderQualityUI();
}

function hideSubtitleTrackUI() {
  subtitleTrackWrap?.classList.add('hidden');
  if (subtitleTrackSelect) subtitleTrackSelect.innerHTML = '';
}

function updateSubtitleTrackUI(tracks) {
  if (!subtitleTrackWrap || !subtitleTrackSelect || !tracks?.length) {
    hideSubtitleTrackUI();
    return;
  }
  subtitleTrackWrap.classList.remove('hidden');
  const defaultIdx = Math.max(0, tracks.findIndex((t) => /eng/i.test(t.name || '')));
  subtitleTrackSelect.innerHTML = tracks
    .map((track, i) => {
      const label = track.name || `Субтитры ${i + 1}`;
      return `<option value="${i}" ${i === defaultIdx ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    })
    .join('');
}

function pickDefaultSubtitleTrack(tracks) {
  if (!tracks?.length) return null;
  return tracks.find((t) => /eng/i.test(t.name || '')) || tracks[0];
}

async function loadSubtitleTrack(track) {
  if (!track?.url) return;
  await loadAutoSubtitles(track.url);
  subsNameUrl.textContent = `${track.name || 'Субтитры'} (${state.cues.length} реплик)`;
  if (state.playbackMode === 'video' && state.cues.length) {
    state.currentCueIndex = -1;
    resetSubtitleState();
  }
}

async function setupSubtitleTracks() {
  const tracks = state.selectedPlayer?.subtitleTracks || [];
  if (!tracks.length || state.subsFile) return;
  updateSubtitleTrackUI(tracks);
  await loadSubtitleTrack(pickDefaultSubtitleTrack(tracks));
}

function loadSkipAdsPref() {
  try {
    return localStorage.getItem(SKIP_ADS_KEY) !== '0';
  } catch {
    return true;
  }
}

function saveSkipAdsPref(value) {
  state.skipAds = value;
  try {
    localStorage.setItem(SKIP_ADS_KEY, value ? '1' : '0');
  } catch { /* ignore */ }
  if (skipAdsSetup) skipAdsSetup.checked = value;
  if (skipAdsLive) skipAdsLive.checked = value;
}

function buildEmbedSrc(iframeUrl) {
  // Прямой iframe: прокси /api/embed ломает JS-плееры (ylitron и др.)
  return iframeUrl;
}

function bindSkipAdsToggle(el) {
  if (!el) return;
  el.addEventListener('change', () => {
    saveSkipAdsPref(el.checked);
    if (state.playbackMode === 'iframe' && state.selectedPlayer?.iframeUrl) {
      embedFrame.src = buildEmbedSrc(state.selectedPlayer.iframeUrl);
    }
  });
}

bindSkipAdsToggle(skipAdsSetup);
bindSkipAdsToggle(skipAdsLive);

subtitleDisplay.addEventListener('click', (e) => {
  // Фон строки больше не переводит реплику — только чекбокс «Перевод строки»
  e.stopPropagation();
});

$('#popup-close').addEventListener('click', hidePopup);
$('#popup-save').addEventListener('click', saveFromPopup);
$('#popup-speak').addEventListener('click', speakPopupWord);
document.addEventListener('click', (e) => {
  if (Date.now() < state.ignorePopupHideUntil) return;
  if (wordPopup.classList.contains('hidden')) return;
  if (wordPopup.contains(e.target)) return;
  if (e.target.closest?.('.word')) return;
  if (subtitleDisplay.contains(e.target)) return;
  hidePopup();
});

document.addEventListener('keydown', (e) => {
  if (playerSection.classList.contains('hidden')) return;

  const tag = (e.target?.tagName || '').toLowerCase();
  const inputType = (e.target?.type || '').toLowerCase();
  // range/checkbox не считаем «печатанием» — пробел должен ставить на паузу
  const typing = tag === 'textarea'
    || tag === 'select'
    || e.target?.isContentEditable
    || (tag === 'input' && !['range', 'checkbox', 'radio', 'button'].includes(inputType));

  if ((e.code === 'Space' || e.key === ' ') && !typing) {
    e.preventDefault();
    e.stopPropagation();
    if (state.playbackMode === 'video') {
      toggleVideoPlayback();
      bumpChromeVisible();
    }
    return;
  }

  if (e.key === 'Escape' && playerMenu && !playerMenu.classList.contains('hidden')) {
    closePlayerMenu();
    return;
  }

  if (typing) return;

  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    if (state.playbackMode === 'video') {
      seekVideoBy((e.key === 'ArrowRight' ? 1 : -1) * state.seekStep);
    } else if (state.playbackMode === 'iframe') {
      stepCue(e.key === 'ArrowRight' ? 1 : -1);
    }
  }
}, true);

function seekVideoBy(deltaSec) {
  if (state.playbackMode !== 'video') return;
  const dur = Number.isFinite(video.duration) ? video.duration : Infinity;
  const next = Math.min(Math.max(0, video.currentTime + deltaSec), dur);
  video.currentTime = next;
  syncChromeSeek();
  bumpChromeVisible();
}

$('#btn-vocab').addEventListener('click', () => vocabDrawer.classList.remove('hidden'));
$('#vocab-close').addEventListener('click', () => vocabDrawer.classList.add('hidden'));
$('#vocab-backdrop').addEventListener('click', () => vocabDrawer.classList.add('hidden'));
$('#vocab-clear').addEventListener('click', clearVocabulary);
$('#vocab-export').addEventListener('click', exportVocabulary);

if (subsSizeRange) {
  const pct = Math.round(state.subsScale * 100);
  subsSizeRange.value = String(pct);
  if (subsSizeValue) subsSizeValue.textContent = `${pct}%`;
  applySubsScale(state.subsScale);
  const onSizeInput = () => {
    const percent = Number(subsSizeRange.value) || SUBS_SIZE_DEFAULT_PCT;
    if (subsSizeValue) subsSizeValue.textContent = `${percent}%`;
    const scale = percent / 100;
    applySubsScale(scale);
    saveSubsScale(scale);
  };
  subsSizeRange.addEventListener('input', onSizeInput);
  subsSizeRange.addEventListener('change', onSizeInput);
}

btnSubsEdit?.addEventListener('click', () => {
  state.subsEditMode = !state.subsEditMode;
  playerSection.classList.toggle('is-subs-edit', state.subsEditMode);
  btnSubsEdit.classList.toggle('is-active', state.subsEditMode);
  btnSubsEdit.textContent = state.subsEditMode ? '✓ Готово' : '↕ Позиция';
  if (!state.subsEditMode) subtitlePanel?.classList.remove('is-dragging');
});

initSubsPanelDrag();

// --- Custom player chrome ---

const CHROME_IDLE_MS = 2500;
let chromeIdleTimer = null;
let chromeSeeking = false;

function formatChromeTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function syncChromePlayIcon() {
  if (!chromePlay) return;
  chromePlay.textContent = video.paused ? '▶' : '⏸';
  chromePlay.title = video.paused ? 'Play' : 'Pause';
}

function syncChromeMuteIcon() {
  if (!chromeMute) return;
  const muted = video.muted || video.volume === 0;
  chromeMute.textContent = muted ? '🔇' : '🔊';
}

function syncChromeSeek() {
  if (!chromeSeek || chromeSeeking) return;
  const dur = video.duration;
  if (!Number.isFinite(dur) || dur <= 0) {
    chromeSeek.value = '0';
    if (chromeTime) chromeTime.textContent = `${formatChromeTime(video.currentTime)} / —`;
    return;
  }
  chromeSeek.value = String(Math.round((video.currentTime / dur) * 1000));
  if (chromeTime) {
    chromeTime.textContent = `${formatChromeTime(video.currentTime)} / ${formatChromeTime(dur)}`;
  }
}

function syncChromeUI() {
  syncChromePlayIcon();
  syncChromeMuteIcon();
  syncChromeSeek();
  if (chromeVolume) chromeVolume.value = String(video.muted ? 0 : video.volume);
}

function bumpChromeVisible() {
  if (!playerChrome) return;
  playerChrome.classList.add('is-chrome-visible');
  playerChrome.classList.remove('is-chrome-idle');
  clearTimeout(chromeIdleTimer);
  if (playerChrome.classList.contains('is-menu-open')) return;
  if (state.playbackMode === 'video' && video.paused) return;
  chromeIdleTimer = setTimeout(() => {
    if (playerChrome.classList.contains('is-menu-open')) return;
    if (state.playbackMode === 'video' && video.paused) return;
    playerChrome.classList.add('is-chrome-idle');
    playerChrome.classList.remove('is-chrome-visible');
  }, CHROME_IDLE_MS);
}

function openPlayerMenu() {
  if (!playerMenu || !playerChrome) return;
  playerMenu.classList.remove('hidden');
  playerChrome.classList.add('is-menu-open');
  playerSection.classList.add('is-menu-open');
  chromeMenuBtn?.setAttribute('aria-expanded', 'true');
  bumpChromeVisible();
}

function closePlayerMenu() {
  if (!playerMenu || !playerChrome) return;
  playerMenu.classList.add('hidden');
  playerChrome.classList.remove('is-menu-open');
  playerSection.classList.remove('is-menu-open');
  chromeMenuBtn?.setAttribute('aria-expanded', 'false');
  bumpChromeVisible();
}

function togglePlayerMenu() {
  if (!playerMenu) return;
  if (playerMenu.classList.contains('hidden')) openPlayerMenu();
  else closePlayerMenu();
}

function toggleVideoPlayback() {
  if (state.playbackMode !== 'video') return;
  if (video.paused) video.play().catch(() => {});
  else video.pause();
}

function initPlayerChrome() {
  if (!playerChrome) return;

  chromePlay?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleVideoPlayback();
    bumpChromeVisible();
  });

  chromeSeek?.addEventListener('pointerdown', () => {
    chromeSeeking = true;
    bumpChromeVisible();
  });
  chromeSeek?.addEventListener('input', () => {
    const dur = video.duration;
    if (!Number.isFinite(dur) || dur <= 0) return;
    const t = (Number(chromeSeek.value) / 1000) * dur;
    if (chromeTime) {
      chromeTime.textContent = `${formatChromeTime(t)} / ${formatChromeTime(dur)}`;
    }
  });
  const commitSeek = () => {
    const dur = video.duration;
    if (Number.isFinite(dur) && dur > 0) {
      video.currentTime = (Number(chromeSeek.value) / 1000) * dur;
    }
    chromeSeeking = false;
    syncChromeSeek();
    bumpChromeVisible();
  };
  chromeSeek?.addEventListener('change', commitSeek);
  chromeSeek?.addEventListener('pointerup', commitSeek);

  chromeMute?.addEventListener('click', (e) => {
    e.stopPropagation();
    video.muted = !video.muted;
    if (!video.muted && video.volume === 0) video.volume = 0.5;
    syncChromeUI();
    bumpChromeVisible();
  });

  chromeVolume?.addEventListener('input', () => {
    const v = Number(chromeVolume.value);
    video.volume = v;
    video.muted = v === 0;
    syncChromeMuteIcon();
    bumpChromeVisible();
  });

  chromeMenuBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePlayerMenu();
  });

  playerMenu?.addEventListener('click', (e) => e.stopPropagation());

  document.addEventListener('click', (e) => {
    if (!playerMenu || playerMenu.classList.contains('hidden')) return;
    if (playerMenu.contains(e.target)) return;
    if (chromeMenuBtn?.contains(e.target)) return;
    closePlayerMenu();
  });

  playerWrap?.addEventListener('mousemove', bumpChromeVisible);
  playerWrap?.addEventListener('pointerdown', bumpChromeVisible);
  playerChrome.addEventListener('mouseenter', bumpChromeVisible);

  videoShell?.addEventListener('click', (e) => {
    if (e.target.closest?.('.player-chrome')) return;
    if (e.target.closest?.('.word')) return;
    if (state.playbackMode !== 'video') return;
    toggleVideoPlayback();
    bumpChromeVisible();
  });

  video.addEventListener('play', () => {
    syncChromePlayIcon();
    bumpChromeVisible();
  });
  video.addEventListener('pause', () => {
    syncChromePlayIcon();
    bumpChromeVisible();
  });
  video.addEventListener('volumechange', () => {
    syncChromeMuteIcon();
    if (chromeVolume && !chromeSeeking) {
      chromeVolume.value = String(video.muted ? 0 : video.volume);
    }
  });
  video.addEventListener('loadedmetadata', syncChromeUI);
  video.addEventListener('durationchange', syncChromeUI);
  video.addEventListener('timeupdate', () => {
    syncChromeSeek();
  });

  syncChromeUI();
  bumpChromeVisible();
}

initPlayerChrome();

video.addEventListener('timeupdate', onTimeUpdate);
video.addEventListener('seeked', onTimeUpdate);

initVocabulary();
updateStartButton();
updateStartUrlButton();
applySubsPosition(loadSubsPosition());

// --- URL resolve ---

async function resolvePageUrl() {
  const url = pageUrl.value.trim();
  if (!url) {
    setStatus('Вставьте ссылку на страницу серии', true);
    return;
  }
  savePageUrl(url);

  try {
    await pushNetConfigToServer();
  } catch (err) {
    setStatus(err?.message || 'Ошибка настроек сети', true);
    return;
  }

  setStatus('Ищу Ylitron ID на странице NewDeaf…');
  btnResolve.disabled = true;

  try {
    const res = await fetch(`/api/resolve?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Ошибка загрузки');

    state.resolved = data;
    const sorted = [...data.players].sort((a, b) => {
      if (a.available === false && b.available !== false) return 1;
      if (a.available !== false && b.available === false) return -1;
      if (a.streamUrl && !b.streamUrl) return -1;
      if (!a.streamUrl && b.streamUrl) return 1;
      return a.index - b.index;
    });
    state.selectedPlayer =
      sorted.find((p) => p.available !== false && p.streamUrl)
      || sorted.find((p) => p.available !== false)
      || null;

    resolvedTitle.textContent = data.title;

    if (data.ylitronId) {
      resolvedYlitron.classList.remove('hidden');
      resolvedYlitronId.textContent = data.ylitronId;
      resolvedYlitronPath.textContent = data.ylitronPath
        ? `(ylitron.pro${data.ylitronPath})`
        : '';
    } else {
      resolvedYlitron.classList.add('hidden');
      resolvedYlitronId.textContent = '';
      resolvedYlitronPath.textContent = '';
    }

    playerPicker.innerHTML = sorted
      .map((p) => {
        const active = p === state.selectedPlayer ? 'is-active' : '';
        const disabled = p.available === false ? 'is-disabled' : '';
        const name = p.label || (data.ylitronId ? `Ylitron ${data.ylitronId}` : `Плеер ${p.index}`);
        let badge = '<small> · только iframe</small>';
        if (p.available === false) badge = '<small> · недоступен</small>';
        else if (p.streamUrl && p.subtitleUrl) badge = '<small> · поток + субтитры ✓</small>';
        else if (p.streamUrl) badge = '<small> · прямой поток ✓</small>';
        return `
        <button type="button" class="player-pick ${active} ${disabled}" data-index="${p.index}" ${disabled ? 'disabled' : ''}>
          ${name}${badge}
        </button>`;
      })
      .join('');

    playerPicker.querySelectorAll('.player-pick:not(.is-disabled)').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.index);
        state.selectedPlayer = data.players.find((p) => p.index === idx);
        playerPicker.querySelectorAll('.player-pick').forEach((b) => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        if (!playerSection.classList.contains('hidden')) {
          startUrlPlayer();
        }
      });
    });

    resolvedInfo.classList.remove('hidden');
    if (data.ylitronId) {
      const ok = state.selectedPlayer?.streamUrl;
      setStatus(
        ok
          ? `Используем Ylitron ID ${data.ylitronId} — поток берём напрямую с ylitron`
          : `Найден Ylitron ID ${data.ylitronId}, но поток пока не открылся — попробуйте ещё раз`,
        !ok,
        !!ok
      );
    } else {
      const streamPlayer = data.players.find((p) => p.available !== false && p.streamUrl);
      setStatus(
        streamPlayer
          ? `Ylitron не найден. Плеер ${streamPlayer.index} — прямой поток`
          : 'Ylitron на странице не найден, прямой поток тоже нет.',
        !streamPlayer,
        !!streamPlayer
      );
    }
    updateStartUrlButton();
  } catch (err) {
    state.resolved = null;
    resolvedInfo.classList.add('hidden');
    resolvedYlitron.classList.add('hidden');
    setStatus(err.message, true);
  } finally {
    btnResolve.disabled = false;
  }
}

function setStatus(text, isError = false, isOk = false) {
  resolveStatus.textContent = text;
  resolveStatus.classList.toggle('is-error', isError);
  resolveStatus.classList.toggle('is-ok', isOk);
}

async function loadSubsFile(file, labelEl) {
  state.subsFile = file || null;
  labelEl.textContent = file?.name || (labelEl === subsNameUrl ? 'Не выбрано — позже' : 'Не выбрано');
  if (file) {
    const text = await file.text();
    state.cues = parseSubtitles(text, file.name);
  } else {
    state.cues = [];
  }
}

function updateStartButton() {
  btnStart.disabled = !(state.videoFile && state.cues.length);
}

function updateStartUrlButton() {
  btnStartUrl.disabled = !state.selectedPlayer;
}

// --- Start players ---

function startFilePlayer() {
  if (!state.videoFile || !state.cues.length) return;
  state.playbackMode = 'video';
  setupPlayerUI();
  video.controls = false;
  video.src = URL.createObjectURL(state.videoFile);
  video.classList.remove('hidden');
  embedFrame.classList.add('hidden');
  iframeNotice.classList.add('hidden');
  setIframeControls(false);
  playerTitle.textContent = state.videoFile.name;
  resetSubtitleState();
  video.playbackRate = parseFloat(speedSelect.value);
  syncChromeUI();
  bumpChromeVisible();
}

function showPlaybackError(message) {
  playbackError.textContent = message;
  playbackError.classList.remove('hidden');
  iframeNotice.classList.add('hidden');
  video.classList.add('hidden');
  embedFrame.classList.add('hidden');
  hideSubtitleTrackUI();
  hideAudioTrackUI();
  hideQualityUI();
}

function hidePlaybackError() {
  playbackError.classList.add('hidden');
}

function showPlayerLoading(text = 'Загрузка плеера…') {
  if (playerLoading) {
    playerLoading.textContent = text;
    playerLoading.classList.remove('hidden');
  }
}

function hidePlayerLoading() {
  playerLoading?.classList.add('hidden');
}

function cleanupVideo() {
  destroyHls();
  video.pause();
  const src = video.currentSrc || video.src;
  if (src?.startsWith('blob:')) {
    URL.revokeObjectURL(src);
  }
  video.removeAttribute('src');
  video.load();
}

let iframeLoadTimer = null;

function clearIframeLoadTimer() {
  if (iframeLoadTimer) {
    clearTimeout(iframeLoadTimer);
    iframeLoadTimer = null;
  }
}

function loadIframePlayer(iframeUrl) {
  clearIframeLoadTimer();
  embedFrame.removeAttribute('src');
  showPlayerLoading('Загрузка встроенного плеера…');

  const onLoad = () => {
    clearIframeLoadTimer();
    hidePlayerLoading();
    hidePlaybackError();
    embedFrame.removeEventListener('load', onLoad);
    embedFrame.removeEventListener('error', onError);
  };

  const onError = () => {
    clearIframeLoadTimer();
    hidePlayerLoading();
    showPlaybackError(
      'Плеер 1 не загрузился. Рекомендуем Плеер 3 — прямой поток без рекламы и с субтитрами.'
    );
    embedFrame.removeEventListener('load', onLoad);
    embedFrame.removeEventListener('error', onError);
  };

  embedFrame.addEventListener('load', onLoad);
  embedFrame.addEventListener('error', onError);
  iframeLoadTimer = setTimeout(() => {
    iframeLoadTimer = null;
    hidePlayerLoading();
    showPlaybackError(
      'Плеер долго загружается. Попробуйте Плеер 3 или нажмите «Загрузить» для обновления ссылок.'
    );
  }, 25000);

  embedFrame.src = buildEmbedSrc(iframeUrl);
}

async function startUrlPlayer() {
  if (!state.selectedPlayer) return;
  if (state.selectedPlayer.available === false) {
    setStatus('Этот плеер недоступен (404). Выберите Плеер 3 или нажмите «Загрузить» снова.', true);
    return;
  }

  hidePlaybackError();
  clearIframeLoadTimer();
  embedFrame.removeAttribute('src');
  cleanupVideo();
  setupPlayerUI();
  const yId = state.resolved?.ylitronId;
  const baseTitle = state.resolved?.title || 'Просмотр';
  playerTitle.textContent = yId ? `${baseTitle} · Ylitron ${yId}` : baseTitle;

  const { iframeUrl, streamUrl, subtitleUrl, available } = state.selectedPlayer;

  if (!streamUrl) {
    state.cues = [];
    subsNameUrl.textContent = 'Не выбрано — загрузите .srt для Плеера 1';
  }

  if (streamUrl) {
    showPlayerLoading('Подключение к потоку…');
    if (await tryPlayStream(streamUrl)) {
      hidePlayerLoading();
      state.playbackMode = 'video';
      video.controls = false;
      video.classList.remove('hidden');
      embedFrame.classList.add('hidden');
      iframeNotice.classList.add('hidden');
      setIframeControls(false);
      renderAudioTrackUI();
      syncAudioTracksUI();
      syncQualityUI();
      syncChromeUI();
      bumpChromeVisible();

      if (state.subsFile && state.cues.length) {
        subsNameUrl.textContent = `${state.subsFile.name} (${state.cues.length} реплик)`;
      } else if (subtitleUrl) {
        await loadAutoSubtitles(subtitleUrl);
      } else if (state.selectedPlayer?.subtitleTracks?.length) {
        await setupSubtitleTracks();
      }

      const hasEnglishSubs = state.cues.length && (subtitleUrl || /eng/i.test(subsNameUrl.textContent));
      const hasAnySubs = state.cues.length > 0;
      subtitleHint.textContent = hasEnglishSubs
        ? 'Прямой поток + субтитры. Клик по слову — перевод.'
        : hasAnySubs
          ? 'Субтитры плеера (не EN). Для обучения загрузите .srt на английском на главном экране.'
          : 'Загрузите .srt/.vtt на английском для интерактивных субтитров.';
    } else {
      hidePlayerLoading();
      hideSubtitleTrackUI();
      showPlaybackError(
        'Поток не загрузился (ссылки быстро протухают). Нажмите «← Назад» → «Загрузить» снова и сразу откройте Плеер 3.'
      );
      setIframeControls(false);
      resetSubtitleState();
      return;
    }
  } else if (available !== false) {
    state.playbackMode = 'iframe';
    video.classList.add('hidden');
    embedFrame.classList.remove('hidden');
    iframeNotice.classList.remove('hidden');
    skipAdsLiveWrap?.classList.add('hidden');
    setIframeControls(true);
    subtitleHint.textContent = 'Плеер 1 — встроенный iframe. Загрузите .srt/.vtt и листайте реплики ← →.';
    loadIframePlayer(iframeUrl);
    bumpChromeVisible();
  } else {
    hidePlayerLoading();
    showPlaybackError('Плеер недоступен. Обновите ссылку кнопкой «Загрузить».');
    return;
  }

  resetSubtitleState();
  if (state.cues.length) {
    state.currentCueIndex = state.playbackMode === 'iframe' ? 0 : -1;
    if (state.playbackMode === 'iframe') renderCurrentCue();
  }
}

async function loadAutoSubtitles(subtitleUrl) {
  try {
    const res = await fetch(`/api/subtitles?url=${encodeURIComponent(subtitleUrl)}`);
    if (!res.ok) return;
    const text = await res.text();
    state.cues = parseSubtitles(text, 'auto.vtt');
  } catch {
    /* ignore */
  }
}

function streamProxyUrl(originalUrl) {
  return `/api/stream?url=${encodeURIComponent(originalUrl)}`;
}

function setupPlayerUI() {
  setupPanel.classList.add('hidden');
  playerSection.classList.remove('hidden');
}

function setIframeControls(show) {
  playerSection.classList.toggle('is-iframe-mode', show);
  $$('.control--iframe-only').forEach((el) => el.classList.toggle('hidden', !show));
  $$('.control--video-only').forEach((el) => {
    if (el.id === 'audio-track-wrap' || el.id === 'subtitle-track-wrap' || el.id === 'quality-track-wrap') return;
    el.classList.toggle('hidden', show);
  });
  manualSync.classList.toggle('hidden', !show);
  if (!show) skipAdsLiveWrap?.classList.add('hidden');
  if (show) {
    hideAudioTrackUI();
    hideSubtitleTrackUI();
    hideQualityUI();
  }
  closePlayerMenu();
  bumpChromeVisible();
}

async function tryPlayStream(url) {
  destroyHls();
  const src = streamProxyUrl(url);

  const waitForPlayable = (hlsInstance) => new Promise((resolve) => {
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      video.removeEventListener('canplay', onCanPlay);
      video.removeEventListener('error', onError);
      if (hlsInstance) {
        hlsInstance.off(Hls.Events.FRAG_BUFFERED, onFragBuffered);
        hlsInstance.off(Hls.Events.ERROR, onHlsError);
      }
      resolve(ok);
    };
    const onCanPlay = () => finish(true);
    const onError = () => finish(false);
    const onFragBuffered = () => finish(true);
    const onHlsError = (_, data) => {
      if (data.fatal) finish(false);
    };
    video.addEventListener('canplay', onCanPlay, { once: true });
    video.addEventListener('error', onError, { once: true });
    if (hlsInstance) {
      hlsInstance.on(Hls.Events.FRAG_BUFFERED, onFragBuffered);
      hlsInstance.on(Hls.Events.ERROR, onHlsError);
    }
    setTimeout(() => finish(false), 30000);
  });

  if (url.includes('.m3u8')) {
    if (window.Hls?.isSupported()) {
      state.hls = new Hls({
        enableWorker: true,
        maxBufferLength: 30,
        manifestLoadingTimeOut: 15000,
        manifestLoadingMaxRetry: 2,
        levelLoadingTimeOut: 15000,
        fragLoadingTimeOut: 20000,
      });
      const playable = waitForPlayable(state.hls);
      state.hls.loadSource(src);
      state.hls.attachMedia(video);
      state.hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, () => syncAudioTracksUI());
      state.hls.on(Hls.Events.AUDIO_TRACK_SWITCHED, () => renderAudioTrackUI());
      state.hls.on(Hls.Events.LEVELS_UPDATED, () => syncQualityUI());
      state.hls.on(Hls.Events.LEVEL_SWITCHED, () => renderQualityUI());
      state.hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      const ok = await playable;
      if (ok) {
        syncAudioTracksUI();
        syncQualityUI();
      }
      return ok;
    }
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = src;
      video.addEventListener('loadedmetadata', () => applyPreferredAudioTrack(), { once: true });
      return waitForPlayable(null);
    }
  }

  if (url.includes('.mp4') || url.includes('.m3u8')) {
    video.src = src;
    return waitForPlayable(null);
  }
  return false;
}

function destroyHls() {
  if (state.hls) {
    state.hls.destroy();
    state.hls = null;
  }
  hideAudioTrackUI();
  hideQualityUI();
}

function resetSubtitleState() {
  if (state.cues.length) {
    subtitleDisplay.innerHTML = state.playbackMode === 'iframe'
      ? '<span class="placeholder">Листайте реплики или синхронизируйте по времени…</span>'
      : '<span class="placeholder">Субтитры появятся при воспроизведении…</span>';
  } else {
    subtitleDisplay.innerHTML = '<span class="placeholder">Загрузите .srt на английском для интерактивных субтитров</span>';
  }
  subtitleTranslation.classList.add('hidden');
  state.currentCueIndex = -1;
  subtitleMeta.textContent = '';
}

function backToSetup() {
  closePlayerMenu();
  exitLearnFullscreen();
  video.pause();
  clearIframeLoadTimer();
  cleanupVideo();
  embedFrame.removeAttribute('src');
  hidePlayerLoading();
  hidePlaybackError();
  setupPanel.classList.remove('hidden');
  playerSection.classList.add('hidden');
  hidePopup();
}

function isLearnFullscreen() {
  return document.fullscreenElement === playerSection
    || document.webkitFullscreenElement === playerSection;
}

function loadLearnPanelHeight() {
  try {
    const raw = localStorage.getItem(LEARN_PANEL_H_KEY);
    const n = Number(raw);
    if (!Number.isFinite(n)) return LEARN_PANEL_H_DEFAULT;
    return Math.round(Math.min(Math.max(n, LEARN_PANEL_H_MIN), 900));
  } catch {
    return LEARN_PANEL_H_DEFAULT;
  }
}

function saveLearnPanelHeight(px) {
  try {
    localStorage.setItem(LEARN_PANEL_H_KEY, String(Math.round(px)));
  } catch { /* ignore */ }
}

function clampLearnPanelHeight(px) {
  const max = Math.max(
    LEARN_PANEL_H_MIN,
    Math.floor(window.innerHeight * LEARN_PANEL_H_MAX_RATIO)
  );
  return Math.round(Math.min(Math.max(px, LEARN_PANEL_H_MIN), max));
}

function applyLearnPanelHeight(px) {
  const h = clampLearnPanelHeight(px);
  playerSection.style.setProperty('--learn-panel-h', `${h}px`);
  return h;
}

function syncLearnFullscreenUI() {
  const on = isLearnFullscreen();
  playerSection.classList.toggle('is-learn-fs', on);
  $('#btn-exit-fs')?.classList.toggle('hidden', !on);
  btnSubsEdit?.classList.toggle('hidden', !on);
  if (!on) {
    state.subsEditMode = false;
    playerSection.classList.remove('is-subs-edit');
    if (btnSubsEdit) {
      btnSubsEdit.classList.remove('is-active');
      btnSubsEdit.textContent = '↕ Позиция';
    }
  } else {
    applyLearnPanelHeight(loadLearnPanelHeight());
    applySubsPosition(loadSubsPosition());
    applySubsScale(state.subsScale);
  }
  bumpChromeVisible();
}

function initLearnPanelResize() {
  const handle = $('#learn-resize-handle');
  if (!handle) return;

  let dragging = false;
  let startY = 0;
  let startH = 0;

  const onMove = (clientY) => {
    if (!dragging || !isLearnFullscreen()) return;
    const delta = startY - clientY;
    applyLearnPanelHeight(startH + delta);
  };

  const stop = () => {
    if (!dragging) return;
    dragging = false;
    playerSection.classList.remove('is-resizing');
    const current = getComputedStyle(playerSection).getPropertyValue('--learn-panel-h');
    const px = Number.parseFloat(current);
    if (Number.isFinite(px)) saveLearnPanelHeight(px);
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', stop);
    window.removeEventListener('pointercancel', stop);
  };

  const onPointerMove = (e) => onMove(e.clientY);

  handle.addEventListener('pointerdown', (e) => {
    if (!isLearnFullscreen()) return;
    e.preventDefault();
    dragging = true;
    startY = e.clientY;
    startH = loadLearnPanelHeight();
    const live = Number.parseFloat(
      getComputedStyle(playerSection).getPropertyValue('--learn-panel-h')
    );
    if (Number.isFinite(live)) startH = live;
    playerSection.classList.add('is-resizing');
    handle.setPointerCapture?.(e.pointerId);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
  });

  handle.addEventListener('dblclick', () => {
    if (!isLearnFullscreen()) return;
    const h = applyLearnPanelHeight(LEARN_PANEL_H_DEFAULT);
    saveLearnPanelHeight(h);
  });
}

async function toggleLearnFullscreen() {
  if (isLearnFullscreen()) {
    await exitLearnFullscreen();
    return;
  }
  try {
    if (playerSection.requestFullscreen) {
      await playerSection.requestFullscreen();
    } else if (playerSection.webkitRequestFullscreen) {
      await playerSection.webkitRequestFullscreen();
    }
  } catch {
    /* ignore */
  }
  syncLearnFullscreenUI();
}

async function exitLearnFullscreen() {
  if (!isLearnFullscreen()) {
    syncLearnFullscreenUI();
    return;
  }
  try {
    if (document.exitFullscreen) await document.exitFullscreen();
    else if (document.webkitExitFullscreen) await document.webkitExitFullscreen();
  } catch {
    /* ignore */
  }
  syncLearnFullscreenUI();
}

// --- Subtitle parsing (unchanged) ---

function parseSubtitles(text, filename) {
  if (filename.toLowerCase().endsWith('.vtt')) return parseVtt(text);
  return parseSrt(text);
}

function parseSrt(text) {
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  const blocks = normalized.split(/\n\n+/);
  const cues = [];

  for (const block of blocks) {
    const lines = block.split('\n').filter(Boolean);
    if (lines.length < 2) continue;

    let timeLineIdx = 0;
    if (/^\d+$/.test(lines[0].trim())) timeLineIdx = 1;
    const timeMatch = lines[timeLineIdx]?.match(
      /(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})/
    );
    if (!timeMatch) continue;

    const rawText = lines.slice(timeLineIdx + 1).join(' ').replace(/<[^>]+>/g, '').trim();
    if (!rawText) continue;

    cues.push({ start: parseTime(timeMatch[1]), end: parseTime(timeMatch[2]), text: rawText });
  }

  return cues.sort((a, b) => a.start - b.start);
}

function parseVtt(text) {
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const blocks = normalized.split(/\n\n+/);
  const cues = [];

  for (const block of blocks) {
    if (block.startsWith('WEBVTT')) continue;
    const lines = block.split('\n').filter(Boolean);
    if (!lines.length) continue;

    let timeLineIdx = 0;
    if (!lines[0].includes('-->')) timeLineIdx = 1;
    const timeMatch = lines[timeLineIdx]?.match(
      /(\d{1,2}:?\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:?\d{2}:\d{2}[,.]\d{3})/
    );
    if (!timeMatch) continue;

    const rawText = lines.slice(timeLineIdx + 1).join(' ').replace(/<[^>]+>/g, '').trim();
    if (!rawText) continue;

    cues.push({ start: parseTime(timeMatch[1]), end: parseTime(timeMatch[2]), text: rawText });
  }

  return cues.sort((a, b) => a.start - b.start);
}

function parseTime(str) {
  const clean = str.replace(',', '.');
  const parts = clean.split(':').map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return parts[0] * 60 + parts[1];
}

function parseManualTimeInput(str) {
  const trimmed = str.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(':').map(Number);
  if (parts.some(Number.isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0];
}

// --- Playback sync ---

function onTimeUpdate() {
  if (state.playbackMode !== 'video' || !state.cues.length) return;
  const t = video.currentTime;
  const idx = state.cues.findIndex((c) => t >= c.start && t <= c.end);
  if (idx !== state.currentCueIndex) {
    state.currentCueIndex = idx;
    renderCurrentCue();
  }
}

function syncByManualTime() {
  const seconds = parseManualTimeInput(manualTime.value);
  if (seconds == null || !state.cues.length) return;
  const idx = state.cues.findIndex((c) => seconds >= c.start && seconds <= c.end);
  state.currentCueIndex = idx >= 0 ? idx : findNearestCue(seconds);
  renderCurrentCue();
}

function findNearestCue(seconds) {
  let best = 0;
  let bestDist = Infinity;
  state.cues.forEach((c, i) => {
    const dist = Math.min(Math.abs(seconds - c.start), Math.abs(seconds - c.end));
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  });
  return best;
}

function stepCue(delta) {
  if (!state.cues.length) return;
  if (state.currentCueIndex < 0) state.currentCueIndex = 0;
  else state.currentCueIndex = Math.max(0, Math.min(state.cues.length - 1, state.currentCueIndex + delta));
  renderCurrentCue();
}

function renderCurrentCue() {
  if (state.currentCueIndex < 0 || !state.cues.length) {
    if (!state.cues.length) {
      subtitleDisplay.innerHTML = '<span class="placeholder">Нет субтитров — загрузите .srt</span>';
    } else {
      subtitleDisplay.innerHTML = '<span class="placeholder">…</span>';
    }
    subtitleTranslation.classList.add('hidden');
    subtitleMeta.textContent = '';
    return;
  }

  const cue = state.cues[state.currentCueIndex];
  subtitleDisplay.innerHTML = tokenizeToHtml(cue.text);
  bindWordClicks(cue.text);
  subtitleMeta.textContent = `#${state.currentCueIndex + 1} / ${state.cues.length} · ${formatTime(cue.start)} → ${formatTime(cue.end)}`;

  if (showRuInline.checked) {
    subtitleTranslation.textContent = '…';
    subtitleTranslation.classList.remove('hidden');
    translateText(cue.text).then((ru) => {
      if (state.cues[state.currentCueIndex]?.text === cue.text && showRuInline.checked) {
        subtitleTranslation.textContent = ru;
        subtitleTranslation.classList.remove('hidden');
      }
    });
  } else {
    subtitleTranslation.classList.add('hidden');
    subtitleTranslation.textContent = '';
  }
}

function tokenizeToHtml(text) {
  return text
    .split(/(\s+|[^\w']+|'\w+)/)
    .filter(Boolean)
    .map((part) => {
      if (/^\s+$/.test(part)) return part;
      if (/^[\w']+$/.test(part) && /[a-zA-Z]/.test(part)) {
        return `<span class="word" data-word="${escapeAttr(part)}">${escapeHtml(part)}</span>`;
      }
      return escapeHtml(part);
    })
    .join('');
}

function getCueWordEls() {
  return Array.from(subtitleDisplay.querySelectorAll('.word'));
}

function clearWordSelection() {
  getCueWordEls().forEach((w) => {
    w.classList.remove('is-active', 'is-selected');
  });
}

function applyWordRange(from, to) {
  const words = getCueWordEls();
  const a = Math.max(0, Math.min(from, to));
  const b = Math.min(words.length - 1, Math.max(from, to));
  words.forEach((w, i) => {
    const on = i >= a && i <= b;
    w.classList.toggle('is-active', on);
    w.classList.toggle('is-selected', on);
  });
  return words.slice(a, b + 1).map((w) => w.dataset.word).join(' ');
}

function bindWordClicks(sentence) {
  const words = getCueWordEls();
  state.wordAnchorIndex = null;
  state.wordDrag = null;

  words.forEach((el, idx) => {
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || state.subsEditMode) return;
      e.preventDefault();
      e.stopPropagation();
      try { el.setPointerCapture?.(e.pointerId); } catch { /* ignore */ }
      state.wordDrag = { start: idx, end: idx, sentence, pointerId: e.pointerId };
      if (e.shiftKey && state.wordAnchorIndex != null) {
        applyWordRange(state.wordAnchorIndex, idx);
        state.wordDrag.start = state.wordAnchorIndex;
        state.wordDrag.end = idx;
      } else {
        state.wordAnchorIndex = idx;
        applyWordRange(idx, idx);
      }
    });

    el.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
  });
}

let wordDragListenersBound = false;
function ensureWordDragListeners() {
  if (wordDragListenersBound) return;
  wordDragListenersBound = true;

  document.addEventListener('pointermove', (e) => {
    if (!state.wordDrag) return;
    const words = getCueWordEls();
    if (!words.length) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const wordEl = el?.closest?.('.word');
    if (!wordEl || !subtitleDisplay.contains(wordEl)) return;
    const idx = words.indexOf(wordEl);
    if (idx < 0 || idx === state.wordDrag.end) return;
    state.wordDrag.end = idx;
    applyWordRange(state.wordDrag.start, idx);
  });

  document.addEventListener('pointerup', onWordPointerEnd);
  document.addEventListener('pointercancel', onWordPointerEnd);
}

async function onWordPointerEnd(e) {
  if (!state.wordDrag) return;
  if (e?.pointerId != null && state.wordDrag.pointerId != null
      && e.pointerId !== state.wordDrag.pointerId) return;

  const { sentence, start, end } = state.wordDrag;
  state.wordDrag = null;
  const from = Math.min(start, end);
  const to = Math.max(start, end);
  state.wordAnchorIndex = from;
  const phrase = applyWordRange(from, to);
  if (!phrase) return;
  state.ignorePopupHideUntil = Date.now() + 400;
  await finishWordSelection(phrase, sentence, from, to);
}

ensureWordDragListeners();

async function finishWordSelection(phrase, sentence, from, to) {
  const words = getCueWordEls();
  if (!phrase || !words.length) return;

  const first = words[from] || words[0];
  const last = words[to] || first;
  const rect = first.getBoundingClientRect();
  const rect2 = last.getBoundingClientRect();
  const union = {
    left: Math.min(rect.left, rect2.left),
    right: Math.max(rect.right, rect2.right),
    top: Math.min(rect.top, rect2.top),
    bottom: Math.max(rect.bottom, rect2.bottom),
    get width() { return this.right - this.left; },
    get height() { return this.bottom - this.top; },
  };

  const contextSentence = buildTranslationContext(phrase, sentence);
  state.lastPopupWord = { word: phrase, sentence: contextSentence };
  if (pauseOnWord.checked && state.playbackMode === 'video') video.pause();

  if (document.activeElement && subtitleDisplay.contains(document.activeElement)) {
    document.activeElement.blur();
  } else if (document.activeElement === subtitleDisplay) {
    subtitleDisplay.blur();
  }

  showPopup(phrase, contextSentence, union);

  const translation = await translateWord(phrase, contextSentence);
  if (state.lastPopupWord?.word === phrase) {
    setPopupTranslation(translation);
  }
}

function showPopup(word, sentence, rect) {
  popupWord.textContent = word;
  popupTranslation.textContent = 'Перевод…';
  popupTranslation.classList.add('loading');
  if (popupTranslationNote) {
    popupTranslationNote.textContent = '';
    popupTranslationNote.classList.add('hidden');
  }
  popupContext.textContent = sentence;
  wordPopup.classList.remove('hidden');

  const popupRect = wordPopup.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = rect.left + rect.width / 2 - popupRect.width / 2;
  let top = rect.top - popupRect.height - 10;
  if (top < 8) top = Math.min(rect.bottom + 10, vh - popupRect.height - 8);
  left = Math.max(8, Math.min(left, vw - popupRect.width - 8));
  wordPopup.style.left = `${left}px`;
  wordPopup.style.top = `${top}px`;
}

function setPopupTranslation(raw) {
  const { main, note } = splitTranslationNote(raw);
  popupTranslation.textContent = main || raw;
  popupTranslation.classList.remove('loading');
  if (popupTranslationNote) {
    if (note) {
      popupTranslationNote.textContent = note;
      popupTranslationNote.classList.remove('hidden');
    } else {
      popupTranslationNote.textContent = '';
      popupTranslationNote.classList.add('hidden');
    }
  }
}

function splitTranslationNote(raw) {
  const text = String(raw || '').trim();
  if (!text) return { main: '', note: '' };
  const match = text.match(/^(.*?)(?:\n+\s*|\s+)(Примечание\s*[:：].*)$/is);
  if (match) {
    return { main: match[1].trim(), note: match[2].trim() };
  }
  const idx = text.search(/\bПримечание\s*[:：]/i);
  if (idx > 0) {
    return { main: text.slice(0, idx).trim(), note: text.slice(idx).trim() };
  }
  return { main: text, note: '' };
}

function buildTranslationContext(phrase, sentence) {
  // В модель — только текущая реплика (для выбора значения слова).
  // Соседние реплики путали маленькую модель: она переводила их вместо слова.
  const idx = state.currentCueIndex;
  const current = (sentence || state.cues[idx]?.text || '').trim();
  return current || phrase || '';
}

function hidePopup() {
  wordPopup.classList.add('hidden');
  if (popupTranslationNote) {
    popupTranslationNote.textContent = '';
    popupTranslationNote.classList.add('hidden');
  }
  clearWordSelection();
}

function replayCurrentLine() {
  if (state.currentCueIndex < 0 || state.playbackMode !== 'video') return;
  video.currentTime = state.cues[state.currentCueIndex].start;
  video.play();
}

async function fetchTranslation(text, { word = null, sentence = null } = {}) {
  const params = new URLSearchParams();
  if (text) params.set('text', text);
  if (word) params.set('word', word);
  if (sentence) params.set('sentence', sentence);
  const res = await fetch(`/api/translate?${params.toString()}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Ошибка перевода');
  return data.translation;
}

async function translateText(text) {
  if (!state.onlineTranslation) {
    return 'AI-перевод выключен — включите в настройках выше';
  }
  const key = `en-ru:v3:${text}`;
  if (state.translationCache.has(key)) return state.translationCache.get(key);
  try {
    const result = await fetchTranslation(text);
    state.translationCache.set(key, result);
    return result;
  } catch (err) {
    return err?.message || 'Ошибка перевода';
  }
}

async function translateWord(word, sentence = '') {
  const clean = word.replace(/^['"]|['"]$/g, '');
  if (!state.onlineTranslation) {
    return clean;
  }
  const ctx = sentence || state.lastPopupWord?.sentence || '';
  const key = `word:v5:${clean.toLowerCase()}:${ctx}`;
  if (state.translationCache.has(key)) return state.translationCache.get(key);
  try {
    const result = await fetchTranslation(clean, { word: clean, sentence: ctx });
    state.translationCache.set(key, result);
    return result;
  } catch (err) {
    return err?.message || '…';
  }
}

function pickEnglishVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  if (!voices.length) return null;

  if (state.preferredVoiceURI) {
    const saved = voices.find((v) => v.voiceURI === state.preferredVoiceURI);
    if (saved) return saved;
  }

  const en = voices.filter((v) => /^en([-_]|$)/i.test(v.lang || ''));
  const pool = en.length ? en : voices;

  const preferred = [
    /google us english/i,
    /google uk english female/i,
    /google uk english/i,
    /microsoft aria/i,
    /microsoft jenny/i,
    /microsoft guy/i,
    /microsoft ryan/i,
    /samantha/i,
    /karen/i,
    /daniel/i,
    /moira/i,
    /enhanced/i,
    /premium/i,
    /neural/i,
  ];

  for (const re of preferred) {
    const hit = pool.find((v) => re.test(v.name));
    if (hit) {
      state.preferredVoiceURI = hit.voiceURI;
      return hit;
    }
  }

  const us = pool.find((v) => /^en-US/i.test(v.lang));
  const pick = us || pool[0] || null;
  if (pick) state.preferredVoiceURI = pick.voiceURI;
  return pick;
}

if (typeof speechSynthesis !== 'undefined') {
  const refreshVoices = () => {
    state.preferredVoiceURI = null;
    pickEnglishVoice();
  };
  speechSynthesis.addEventListener?.('voiceschanged', refreshVoices);
  speechSynthesis.onvoiceschanged = refreshVoices;
  pickEnglishVoice();
}

function speakPopupWord() {
  if (!state.lastPopupWord || typeof speechSynthesis === 'undefined') return;
  const text = state.lastPopupWord.word;
  if (!text) return;

  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  const voice = pickEnglishVoice();
  if (voice) {
    utter.voice = voice;
    utter.lang = voice.lang || 'en-US';
  } else {
    utter.lang = 'en-US';
  }
  utter.rate = 0.92;
  utter.pitch = 1;
  speechSynthesis.speak(utter);
}

function loadLocalVocabularyBackup() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

async function fetchVocabulary() {
  const res = await fetch('/api/vocab');
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Не удалось загрузить словарь');
  return Array.isArray(data.items) ? data.items : [];
}

async function migrateLocalVocabularyIfNeeded() {
  const localItems = loadLocalVocabularyBackup();
  if (!localItems.length) return;
  try {
    const res = await fetch('/api/vocab/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: localItems }),
    });
    if (!res.ok) return;
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* сервер ещё не готов — оставим localStorage */
  }
}

async function refreshVocabulary() {
  try {
    state.vocabulary = await fetchVocabulary();
  } catch {
    state.vocabulary = loadLocalVocabularyBackup();
  }
  renderVocabulary();
}

async function initVocabulary() {
  await migrateLocalVocabularyIfNeeded();
  await refreshVocabulary();
}

async function saveFromPopup() {
  if (!state.lastPopupWord || !state.onlineTranslation) return;
  const { word, sentence } = state.lastPopupWord;
  const ru = popupTranslation.textContent;
  if (ru === 'Перевод…' || ru === '…') return;
  const note = popupTranslationNote?.textContent?.trim();
  const stored = note ? `${ru}\n${note}` : ru;

  try {
    const res = await fetch('/api/vocab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word,
        translation: stored,
        context: sentence || '',
        savedAt: Date.now(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Не удалось сохранить');
    await refreshVocabulary();
  } catch (err) {
    // fallback: локально, если API недоступен
    const exists = state.vocabulary.some(
      (v) => v.word.toLowerCase() === word.toLowerCase() && v.context === sentence
    );
    if (!exists) {
      state.vocabulary.unshift({
        word,
        translation: stored,
        context: sentence,
        savedAt: Date.now(),
      });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.vocabulary));
      renderVocabulary();
    }
    console.warn(err);
  }
  hidePopup();
}

function renderVocabulary() {
  vocabCount.textContent = state.vocabulary.length;
  vocabList.innerHTML = '';
  if (!state.vocabulary.length) {
    vocabEmpty.classList.remove('hidden');
    return;
  }
  vocabEmpty.classList.add('hidden');
  state.vocabulary.forEach((item) => {
    const li = document.createElement('li');
    const { main, note } = splitTranslationNote(item.translation || '');
    li.innerHTML = `
      <div>
        <div class="en">${escapeHtml(item.word)}</div>
        <div class="ru">${escapeHtml(main || item.translation || '')}</div>
        ${note ? `<div class="ctx">${escapeHtml(note)}</div>` : ''}
        ${item.context ? `<div class="ctx">${escapeHtml(item.context)}</div>` : ''}
      </div>
      <button type="button" aria-label="Удалить" data-id="${item.id ?? ''}">×</button>`;
    li.querySelector('button').addEventListener('click', () => {
      deleteVocabularyItem(item);
    });
    vocabList.appendChild(li);
  });
}

async function deleteVocabularyItem(item) {
  if (item?.id != null) {
    try {
      const res = await fetch(`/api/vocab?id=${encodeURIComponent(item.id)}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Ошибка удаления');
      }
      await refreshVocabulary();
      return;
    } catch (err) {
      console.warn(err);
    }
  }
  state.vocabulary = state.vocabulary.filter((v) => v !== item);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.vocabulary));
  renderVocabulary();
}

async function clearVocabulary() {
  if (!confirm('Очистить весь словарь?')) return;
  try {
    const res = await fetch('/api/vocab', { method: 'DELETE' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Ошибка очистки');
    }
    localStorage.removeItem(STORAGE_KEY);
    await refreshVocabulary();
  } catch (err) {
    state.vocabulary = [];
    localStorage.removeItem(STORAGE_KEY);
    renderVocabulary();
    console.warn(err);
  }
}

function exportVocabulary() {
  const blob = new Blob([JSON.stringify(state.vocabulary, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `sublearn-vocab-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec % 1) * 1000);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function loadSubsScale() {
  try {
    const raw = localStorage.getItem(SUBS_SIZE_KEY);
    const n = Number(raw);
    if (!Number.isFinite(n)) return SUBS_SIZE_DEFAULT_PCT / 100;
    // Поддержка старых пресетов (0.85–1.45) и процентов (50–200)
    if (n >= 50 && n <= 200) return n / 100;
    if (n >= 0.5 && n <= 2.5) return n;
  } catch { /* ignore */ }
  return SUBS_SIZE_DEFAULT_PCT / 100;
}

function saveSubsScale(scale) {
  state.subsScale = scale;
  try {
    localStorage.setItem(SUBS_SIZE_KEY, String(Math.round(scale * 100)));
  } catch { /* ignore */ }
}

function applySubsScale(scale) {
  state.subsScale = scale;
  playerSection?.style.setProperty('--subs-scale', String(scale));
  document.documentElement.style.setProperty('--subs-scale', String(scale));
}

function loadSubsPosition() {
  try {
    const raw = localStorage.getItem(SUBS_POS_KEY);
    if (!raw) return null;
    const pos = JSON.parse(raw);
    if (typeof pos?.x === 'number' && typeof pos?.y === 'number') return pos;
  } catch { /* ignore */ }
  return null;
}

function saveSubsPosition(pos) {
  try {
    if (!pos) localStorage.removeItem(SUBS_POS_KEY);
    else localStorage.setItem(SUBS_POS_KEY, JSON.stringify(pos));
  } catch { /* ignore */ }
}

const SUBS_SNAP_THRESHOLD = 2.4; // % — мягкий магнит как в PowerPoint

function getSubsPositionBounds() {
  if (!subtitlePanel || !playerSection) {
    return { minX: 8, maxX: 92, minY: 8, maxY: 88 };
  }
  const section = playerSection.getBoundingClientRect();
  const panel = subtitlePanel.getBoundingClientRect();
  if (!section.width || !section.height) {
    return { minX: 8, maxX: 92, minY: 8, maxY: 88 };
  }
  // Центр панели в %; край экрана = halfSize, без «невидимой стены» на 92%
  const pad = 1.2;
  const halfW = Math.max(4, (panel.width / section.width) * 50);
  const halfH = Math.max(3, (panel.height / section.height) * 50);
  return {
    minX: Math.min(48, halfW + pad),
    maxX: Math.max(52, 100 - halfW - pad),
    minY: Math.min(48, halfH + pad),
    maxY: Math.max(52, 100 - halfH - pad),
  };
}

function snapSubsAxis(value, magnets, threshold = SUBS_SNAP_THRESHOLD) {
  let best = value;
  let guide = null;
  let bestDist = threshold;
  for (const m of magnets) {
    const d = Math.abs(value - m);
    if (d <= bestDist) {
      bestDist = d;
      best = m;
      guide = m;
    }
  }
  return { value: best, guide };
}

function snapSubsPosition(x, y, bounds) {
  const magnetsX = [bounds.minX, 50, bounds.maxX];
  const magnetsY = [bounds.minY, 50, bounds.maxY];
  const sx = snapSubsAxis(x, magnetsX);
  const sy = snapSubsAxis(y, magnetsY);
  return {
    x: sx.value,
    y: sy.value,
    guideX: sx.guide,
    guideY: sy.guide,
  };
}

function ensureSnapGuides() {
  let root = playerSection.querySelector('.snap-guides');
  if (root) return root;
  root = document.createElement('div');
  root.className = 'snap-guides';
  root.innerHTML = `
    <div class="snap-guide snap-guide--v" data-guide="v" hidden></div>
    <div class="snap-guide snap-guide--h" data-guide="h" hidden></div>
  `;
  playerSection.appendChild(root);
  return root;
}

function updateSnapGuides(guideX, guideY) {
  const root = ensureSnapGuides();
  const v = root.querySelector('[data-guide="v"]');
  const h = root.querySelector('[data-guide="h"]');
  if (v) {
    if (guideX == null) v.hidden = true;
    else {
      v.hidden = false;
      v.style.left = `${guideX}%`;
    }
  }
  if (h) {
    if (guideY == null) h.hidden = true;
    else {
      h.hidden = false;
      h.style.top = `${guideY}%`;
    }
  }
}

function hideSnapGuides() {
  const root = playerSection?.querySelector('.snap-guides');
  if (!root) return;
  root.querySelectorAll('.snap-guide').forEach((el) => { el.hidden = true; });
}

function applySubsPosition(pos, { snap = false } = {}) {
  if (!subtitlePanel) return null;
  if (!pos) {
    subtitlePanel.classList.remove('is-custom-pos');
    subtitlePanel.style.left = '';
    subtitlePanel.style.top = '';
    hideSnapGuides();
    return null;
  }
  const bounds = getSubsPositionBounds();
  let x = Number(pos.x);
  let y = Number(pos.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;

  x = Math.min(bounds.maxX, Math.max(bounds.minX, x));
  y = Math.min(bounds.maxY, Math.max(bounds.minY, y));

  let guideX = null;
  let guideY = null;
  if (snap) {
    const snapped = snapSubsPosition(x, y, bounds);
    x = snapped.x;
    y = snapped.y;
    guideX = snapped.guideX;
    guideY = snapped.guideY;
    updateSnapGuides(guideX, guideY);
  } else {
    hideSnapGuides();
  }

  subtitlePanel.classList.add('is-custom-pos');
  subtitlePanel.style.left = `${x}%`;
  subtitlePanel.style.top = `${y}%`;
  return { x, y };
}

function initSubsPanelDrag() {
  if (!subtitlePanel) return;

  subtitlePanel.addEventListener('pointerdown', (e) => {
    if (!state.subsEditMode || !isLearnFullscreen()) return;
    if (e.target.closest('.word')) return;
    e.preventDefault();
    const rect = playerSection.getBoundingClientRect();
    const panelRect = subtitlePanel.getBoundingClientRect();
    state.subsDrag = {
      offsetX: e.clientX - panelRect.left - panelRect.width / 2,
      offsetY: e.clientY - panelRect.top - panelRect.height / 2,
      sectionLeft: rect.left,
      sectionTop: rect.top,
      sectionW: rect.width,
      sectionH: rect.height,
    };
    subtitlePanel.classList.add('is-dragging');
    playerSection.classList.add('is-snapping');
    subtitlePanel.setPointerCapture?.(e.pointerId);
  });

  subtitlePanel.addEventListener('pointermove', (e) => {
    if (!state.subsDrag) return;
    const { offsetX, offsetY, sectionLeft, sectionTop, sectionW, sectionH } = state.subsDrag;
    if (!sectionW || !sectionH) return;
    const x = ((e.clientX - offsetX - sectionLeft) / sectionW) * 100;
    const y = ((e.clientY - offsetY - sectionTop) / sectionH) * 100;
    applySubsPosition({ x, y }, { snap: true });
  });

  const endDrag = () => {
    if (!state.subsDrag) return;
    state.subsDrag = null;
    subtitlePanel.classList.remove('is-dragging');
    playerSection.classList.remove('is-snapping');
    hideSnapGuides();
    if (subtitlePanel.classList.contains('is-custom-pos')) {
      const x = Number.parseFloat(subtitlePanel.style.left);
      const y = Number.parseFloat(subtitlePanel.style.top);
      if (Number.isFinite(x) && Number.isFinite(y)) saveSubsPosition({ x, y });
    }
  };

  subtitlePanel.addEventListener('pointerup', endDrag);
  subtitlePanel.addEventListener('pointercancel', endDrag);

  subtitlePanel.addEventListener('dblclick', () => {
    if (!state.subsEditMode || !isLearnFullscreen()) return;
    applySubsPosition(null);
    saveSubsPosition(null);
  });
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
  return str.replace(/"/g, '&quot;');
}
