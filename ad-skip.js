/**
 * SubLearn — автопропуск рекламы во встроенных плеерах.
 * Инжектируется через /api/embed в проксированную страницу плеера.
 */
(function () {
  'use strict';

  var SKIP_TEXT = /skip|пропуст|пропуск|close|закрыть|continue|продолж|перейти|skip ad|dismiss|отмен|×|✕/i;
  var AD_HINT = /ad|advert|preroll|commercial|promo|реклам|banner|overlay|midroll|pre-roll|vast/i;

  var AD_SELECTORS = [
    '[class*="ad-"]', '[class*="advert"]', '[id*="ad-"]', '[id*="Advert"]',
    '[class*="preroll"]', '[class*="pre-roll"]', '[class*="commercial"]',
    '.video-ad', '.ad-container', '.adoverlay', '.ad-overlay',
    '[data-ad]', '[data-advertisement]', '.yandex-ad', '.adbadge',
    'iframe[src*="doubleclick"]', 'iframe[src*="googlesyndication"]',
    'iframe[src*="ad."]', 'iframe[src*="ads."]',
  ].join(',');

  var SKIP_SELECTORS = 'button, a, [role="button"], .btn, [aria-label]';
  var clicked = new WeakSet();
  var scheduled = false;

  function isVisible(el) {
    if (!el || el.nodeType !== 1) return false;
    var st = window.getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
  }

  function clickSkipButtons() {
    var nodes = document.querySelectorAll(SKIP_SELECTORS);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (clicked.has(el) || !isVisible(el)) continue;
      var text = (el.textContent || el.getAttribute('aria-label') || '').trim();
      if (!text || text.length > 48) continue;
      if (SKIP_TEXT.test(text)) {
        try {
          el.click();
          clicked.add(el);
        } catch (e) { /* ignore */ }
      }
    }
  }

  function hideAdBlocks() {
    try {
      document.querySelectorAll(AD_SELECTORS).forEach(function (el) {
        var id = (el.className || '') + (el.id || '');
        if (AD_HINT.test(id) || el.matches('iframe[src*="doubleclick"], iframe[src*="googlesyndication"]')) {
          el.style.setProperty('display', 'none', 'important');
          el.style.setProperty('pointer-events', 'none', 'important');
        }
      });
    } catch (e) { /* ignore */ }
  }

  function speedUpAdVideos() {
    document.querySelectorAll('video').forEach(function (v) {
      var box = v.closest('[class*="ad"], [id*="ad"], [class*="preroll"], [class*="commercial"]');
      if (!box) {
        var parent = v.parentElement;
        for (var i = 0; i < 5 && parent; i++, parent = parent.parentElement) {
          var blob = (parent.className || '') + (parent.id || '');
          if (AD_HINT.test(blob)) { box = parent; break; }
        }
      }
      if (box && v.duration && !isNaN(v.duration) && v.duration > 0 && v.duration < 180) {
        try {
          v.playbackRate = 16;
          v.muted = true;
          v.play().catch(function () {});
        } catch (e) { /* ignore */ }
      }
    });
  }

  function tick() {
    clickSkipButtons();
    hideAdBlocks();
    speedUpAdVideos();
  }

  function scheduleTick() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(function () {
      scheduled = false;
      tick();
    }, 250);
  }

  tick();
  setInterval(tick, 1200);
  if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(scheduleTick).observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }
})();
