/* Cmd Palette (Global qidiruv — Ctrl+K)
 * DOM API bilan yaratiladi (XSS safe — textContent + createElement).
 */
(function () {
  'use strict';

  if (window.__cmdPaletteInit) return;
  window.__cmdPaletteInit = true;

  const DEBOUNCE_MS = 300;
  const MIN_LEN = 2;

  let backdrop, panel, input, results, activeIdx = -1, items = [], fetchSeq = 0, debounceTimer = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function buildDOM() {
    backdrop = el('div', 'cmdp-backdrop');
    panel = el('div', 'cmdp-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Global qidiruv');

    // Input row
    const inputWrap = el('div', 'cmdp-input-wrap');
    inputWrap.appendChild(el('span', 'cmdp-prompt', '>'));
    input = document.createElement('input');
    input.className = 'cmdp-input';
    input.type = 'text';
    input.placeholder = 'Mahsulot, mijoz, hujjat, agent qidirish...';
    input.autocomplete = 'off';
    input.spellcheck = false;
    inputWrap.appendChild(input);
    const escBtn = el('span', 'cmdp-esc', 'esc');
    escBtn.addEventListener('click', close);
    inputWrap.appendChild(escBtn);
    panel.appendChild(inputWrap);

    // Results
    results = el('div', 'cmdp-results');
    panel.appendChild(results);

    // Hint footer
    const hint = el('div', 'cmdp-hint');
    [
      ['↑↓', 'tanlash'],
      ['↵', 'ochish'],
      ['esc', 'yopish'],
    ].forEach(([k, label]) => {
      const span = el('span');
      const kbd = el('kbd', null, k);
      span.appendChild(kbd);
      span.appendChild(document.createTextNode(' ' + label));
      hint.appendChild(span);
    });
    panel.appendChild(hint);

    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });
    input.addEventListener('input', onInputChange);
    input.addEventListener('keydown', onInputKeydown);
  }

  function open() {
    if (!backdrop) buildDOM();
    backdrop.classList.add('cmdp-open');
    input.value = '';
    showHint();
    setTimeout(() => input.focus(), 50);
  }

  function close() {
    if (!backdrop) return;
    backdrop.classList.remove('cmdp-open');
    activeIdx = -1;
    items = [];
  }

  function isOpen() {
    return backdrop && backdrop.classList.contains('cmdp-open');
  }

  function clearResults() {
    while (results.firstChild) results.removeChild(results.firstChild);
  }

  function showHint() {
    clearResults();
    results.appendChild(el('div', 'cmdp-empty', '2 yoki ko\'proq harf yozing...'));
    items = [];
    activeIdx = -1;
  }

  function showEmpty() {
    clearResults();
    results.appendChild(el('div', 'cmdp-empty', 'Hech narsa topilmadi'));
    items = [];
    activeIdx = -1;
  }

  function render(data) {
    items = [];
    clearResults();
    if (!data.categories || data.categories.length === 0) {
      showEmpty();
      return;
    }
    data.categories.forEach(cat => {
      const catEl = el('div', 'cmdp-category');
      catEl.appendChild(el('div', 'cmdp-category-title', cat.name || ''));
      (cat.items || []).forEach(it => {
        const idx = items.length;
        items.push(it);
        const item = el('div', 'cmdp-item');
        item.dataset.idx = String(idx);

        const iconBox = el('div', 'cmdp-item-icon');
        const icon = document.createElement('i');
        icon.className = 'bi ' + (cat.icon || 'bi-circle');
        iconBox.appendChild(icon);
        item.appendChild(iconBox);

        const body = el('div', 'cmdp-item-body');
        body.appendChild(el('div', 'cmdp-item-label', it.label || ''));
        if (it.sub) body.appendChild(el('div', 'cmdp-item-sub', it.sub));
        item.appendChild(body);

        item.appendChild(el('span', 'cmdp-item-enter', '↵'));

        item.addEventListener('click', () => openItem(idx));
        item.addEventListener('mouseenter', () => {
          activeIdx = idx;
          updateActive(false);
        });

        catEl.appendChild(item);
      });
      results.appendChild(catEl);
    });
    activeIdx = 0;
    updateActive();
  }

  function updateActive(scroll) {
    if (scroll === undefined) scroll = true;
    const els = results.querySelectorAll('.cmdp-item');
    els.forEach((e, i) => e.classList.toggle('cmdp-active', i === activeIdx));
    if (scroll && els[activeIdx]) {
      els[activeIdx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function openItem(idx) {
    if (idx < 0 || idx >= items.length) return;
    const url = items[idx].url;
    if (url) {
      close();
      window.location.href = url;
    }
  }

  function onInputChange() {
    const q = input.value.trim();
    clearTimeout(debounceTimer);
    if (q.length < MIN_LEN) {
      showHint();
      return;
    }
    debounceTimer = setTimeout(() => doFetch(q), DEBOUNCE_MS);
  }

  function onInputKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (items.length === 0) return;
      activeIdx = (activeIdx + 1) % items.length;
      updateActive();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (items.length === 0) return;
      activeIdx = (activeIdx - 1 + items.length) % items.length;
      updateActive();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIdx >= 0) openItem(activeIdx);
    }
  }

  function doFetch(q) {
    const seq = ++fetchSeq;
    fetch('/api/search?q=' + encodeURIComponent(q), {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    })
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(data => {
        if (seq !== fetchSeq) return;
        render(data);
      })
      .catch(err => {
        if (seq !== fetchSeq) return;
        clearResults();
        results.appendChild(el('div', 'cmdp-empty', 'Xato: ' + (err.message || 'qidiruv ishlamadi')));
      });
  }

  document.addEventListener('keydown', (e) => {
    const isCmd = e.metaKey || e.ctrlKey;
    if (isCmd && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      if (isOpen()) close();
      else open();
    } else if (e.key === 'Escape' && isOpen()) {
      e.preventDefault();
      close();
    }
  });

  window.cmdPalette = { open: open, close: close };
})();
