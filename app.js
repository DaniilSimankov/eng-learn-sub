/**
 * SubLearn — интерактивный плеер для изучения английского по субтитрам
 */

const STORAGE_KEY = 'sublearn-vocabulary';
const SKIP_ADS_KEY = 'sublearn-skip-ads';
const ONLINE_TRANSLATION_KEY = 'sublearn-online-translation';
const AUDIO_LANG_KEY = 'sublearn-audio-lang';
const QUALITY_LEVEL_KEY = 'sublearn-quality-level';
const LEARN_PANEL_H_KEY = 'sublearn-learn-panel-h';
const LEARN_PANEL_H_DEFAULT = 200;
const LEARN_PANEL_H_MIN = 140;
const LEARN_PANEL_H_MAX_RATIO = 0.55;

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
  translationCache: new Map(),
  vocabulary: loadVocabulary(),
  resolved: null,
  selectedPlayer: null,
  hls: null,
  preferredAudioLang: loadPreferredAudioLang(),
  skipAds: loadSkipAdsPref(),
  onlineTranslation: loadOnlineTranslationPref(),
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

if (skipAdsSetup) skipAdsSetup.checked = state.skipAds;
if (skipAdsLive) skipAdsLive.checked = state.skipAds;
if (onlineTranslationSetup) onlineTranslationSetup.checked = state.onlineTranslation;

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
  if (level.height) {
    const mbps = level.bitrate ? ` · ${Math.round(level.bitrate / 1000)} kbps` : '';
    return `${level.height}p${mbps}`;
  }
  if (level.width && level.height) return `${level.width}×${level.height}`;
  if (level.bitrate) return `${Math.round(level.bitrate / 1000)} kbps`;
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
  if (e.target.classList.contains('word')) return;
  translateCurrentLine();
});

$('#popup-close').addEventListener('click', hidePopup);
$('#popup-save').addEventListener('click', saveFromPopup);
$('#popup-speak').addEventListener('click', speakPopupWord);
document.addEventListener('click', (e) => {
  if (!wordPopup.contains(e.target) && !e.target.classList.contains('word')) {
    hidePopup();
  }
});

document.addEventListener('keydown', (e) => {
  if (!playerSection.classList.contains('hidden') && state.playbackMode === 'iframe') {
    if (e.key === 'ArrowLeft') { e.preventDefault(); stepCue(-1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); stepCue(1); }
  }
});

$('#btn-vocab').addEventListener('click', () => vocabDrawer.classList.remove('hidden'));
$('#vocab-close').addEventListener('click', () => vocabDrawer.classList.add('hidden'));
$('#vocab-backdrop').addEventListener('click', () => vocabDrawer.classList.add('hidden'));
$('#vocab-clear').addEventListener('click', clearVocabulary);
$('#vocab-export').addEventListener('click', exportVocabulary);

video.addEventListener('timeupdate', onTimeUpdate);
video.addEventListener('seeked', onTimeUpdate);

renderVocabulary();
updateStartButton();
updateStartUrlButton();

// --- URL resolve ---

async function resolvePageUrl() {
  const url = pageUrl.value.trim();
  if (!url) {
    setStatus('Вставьте ссылку на страницу серии', true);
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
  labelEl.textContent = file?.name || (labelEl === subsNameUrl ? 'Не выбрано — можно добавить позже' : 'Не выбрано');
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
  video.src = URL.createObjectURL(state.videoFile);
  video.classList.remove('hidden');
  embedFrame.classList.add('hidden');
  iframeNotice.classList.add('hidden');
  playerTitle.textContent = state.videoFile.name;
  resetSubtitleState();
  video.playbackRate = parseFloat(speedSelect.value);
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
      video.classList.remove('hidden');
      embedFrame.classList.add('hidden');
      iframeNotice.classList.add('hidden');
      setIframeControls(false);
      renderAudioTrackUI();
      syncAudioTracksUI();
      syncQualityUI();

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
  if (on) applyLearnPanelHeight(loadLearnPanelHeight());
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
  if (showRuInline && !showRuInline.checked) {
    showRuInline.checked = true;
    showRuInline.dispatchEvent(new Event('change'));
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
    translateText(cue.text).then((ru) => {
      if (state.cues[state.currentCueIndex]?.text === cue.text) {
        subtitleTranslation.textContent = ru;
        subtitleTranslation.classList.remove('hidden');
      }
    });
  } else {
    subtitleTranslation.classList.add('hidden');
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
    el.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      state.wordDrag = { start: idx, end: idx, sentence };
      if (e.shiftKey && state.wordAnchorIndex != null) {
        applyWordRange(state.wordAnchorIndex, idx);
      } else {
        state.wordAnchorIndex = idx;
        applyWordRange(idx, idx);
      }
    });

    el.addEventListener('mouseenter', () => {
      if (!state.wordDrag) return;
      state.wordDrag.end = idx;
      applyWordRange(state.wordDrag.start, idx);
    });

    el.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  });
}

async function finishWordSelection(sentence) {
  const words = getCueWordEls();
  const selected = words.filter((w) => w.classList.contains('is-selected'));
  if (!selected.length) return;

  const phrase = selected.map((w) => w.dataset.word).join(' ');
  const first = selected[0];
  const last = selected[selected.length - 1];
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

  state.lastPopupWord = { word: phrase, sentence };
  if (pauseOnWord.checked && state.playbackMode === 'video') video.pause();

  showPopup(phrase, sentence, union);

  const translation = await translateWord(phrase, sentence);
  if (state.lastPopupWord?.word === phrase) {
    popupTranslation.textContent = translation;
    popupTranslation.classList.remove('loading');
  }
}

function showPopup(word, sentence, rect) {
  popupWord.textContent = word;
  popupTranslation.textContent = 'Перевод…';
  popupTranslation.classList.add('loading');
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

document.addEventListener('mouseup', async () => {
  if (!state.wordDrag) return;
  const { sentence } = state.wordDrag;
  const start = state.wordDrag.start;
  const end = state.wordDrag.end;
  state.wordDrag = null;
  state.wordAnchorIndex = Math.min(start, end);
  await finishWordSelection(sentence);
});

function hidePopup() {
  wordPopup.classList.add('hidden');
  clearWordSelection();
}

async function translateCurrentLine() {
  if (state.currentCueIndex < 0) return;
  const cue = state.cues[state.currentCueIndex];
  subtitleTranslation.textContent = 'Перевод…';
  subtitleTranslation.classList.remove('hidden');
  subtitleTranslation.textContent = await translateText(cue.text);
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
  const key = `en-ru:${text}`;
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
  const key = `word:${clean.toLowerCase()}:${ctx}`;
  if (state.translationCache.has(key)) return state.translationCache.get(key);
  try {
    const result = await fetchTranslation(clean, { word: clean, sentence: ctx });
    state.translationCache.set(key, result);
    return result;
  } catch (err) {
    return err?.message || '…';
  }
}

function speakPopupWord() {
  if (!state.lastPopupWord) return;
  const utter = new SpeechSynthesisUtterance(state.lastPopupWord.word);
  utter.lang = 'en-US';
  speechSynthesis.speak(utter);
}

function loadVocabulary() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveVocabulary() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.vocabulary));
  renderVocabulary();
}

function saveFromPopup() {
  if (!state.lastPopupWord || !state.onlineTranslation) return;
  const { word, sentence } = state.lastPopupWord;
  const ru = popupTranslation.textContent;
  if (ru === 'Перевод…' || ru === '…') return;

  const exists = state.vocabulary.some(
    (v) => v.word.toLowerCase() === word.toLowerCase() && v.context === sentence
  );
  if (!exists) {
    state.vocabulary.unshift({ word, translation: ru, context: sentence, savedAt: Date.now() });
    saveVocabulary();
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
  state.vocabulary.forEach((item, i) => {
    const li = document.createElement('li');
    li.innerHTML = `
      <div>
        <div class="en">${escapeHtml(item.word)}</div>
        <div class="ru">${escapeHtml(item.translation)}</div>
        ${item.context ? `<div class="ctx">${escapeHtml(item.context)}</div>` : ''}
      </div>
      <button type="button" aria-label="Удалить" data-idx="${i}">×</button>`;
    li.querySelector('button').addEventListener('click', () => {
      state.vocabulary.splice(i, 1);
      saveVocabulary();
    });
    vocabList.appendChild(li);
  });
}

function clearVocabulary() {
  if (!confirm('Очистить весь словарь?')) return;
  state.vocabulary = [];
  saveVocabulary();
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

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
  return str.replace(/"/g, '&quot;');
}
