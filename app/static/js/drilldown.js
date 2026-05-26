/* Drill-down modal — KPI cards click qilinsa ochiladi.
 * Universal: data-drilldown="sales|production|debt|stock" atribut bo'yicha
 * /api/dashboard/v2/drilldown?kind=... fetch qiladi va modal ko'rsatadi.
 * XSS safe — DOM API + textContent.
 */
(function () {
  'use strict';

  if (window.__drilldownInit) return;
  window.__drilldownInit = true;

  let backdrop, panel, title, summary, body, footerLink, fetchSeq = 0;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function buildDOM() {
    backdrop = el('div', 'dd-backdrop');
    panel = el('div', 'dd-panel');
    panel.setAttribute('role', 'dialog');

    // Header
    const header = el('div', 'dd-header');
    const titleWrap = el('div', 'dd-title-wrap');
    title = el('div', 'dd-title', '');
    summary = el('div', 'dd-summary', '');
    titleWrap.appendChild(title);
    titleWrap.appendChild(summary);
    header.appendChild(titleWrap);
    const closeBtn = el('button', 'dd-close', 'esc');
    closeBtn.addEventListener('click', close);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Body
    body = el('div', 'dd-body');
    panel.appendChild(body);

    // Footer
    const footer = el('div', 'dd-footer');
    footerLink = el('a', 'dd-link', '');
    footer.appendChild(footerLink);
    const hint = el('div', 'dd-hint');
    const kbd = el('kbd', null, 'esc');
    hint.appendChild(kbd);
    hint.appendChild(document.createTextNode(' yopish'));
    footer.appendChild(hint);
    panel.appendChild(footer);

    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });
  }

  function open(kind) {
    if (!backdrop) buildDOM();
    backdrop.classList.add('dd-open');
    showLoading();
    fetchData(kind);
  }

  function close() {
    if (!backdrop) return;
    backdrop.classList.remove('dd-open');
  }

  function isOpen() {
    return backdrop && backdrop.classList.contains('dd-open');
  }

  function clearBody() {
    while (body.firstChild) body.removeChild(body.firstChild);
  }

  function showLoading() {
    title.textContent = 'Yuklanmoqda';
    summary.textContent = '';
    footerLink.textContent = '';
    footerLink.removeAttribute('href');
    clearBody();
    body.appendChild(el('div', 'dd-loading', 'Yuklanmoqda'));
  }

  function renderData(data) {
    title.textContent = data.title || 'Detail';
    summary.textContent = data.summary || '';

    if (data.link && data.link.url) {
      footerLink.textContent = data.link.label || 'Batafsil →';
      footerLink.href = data.link.url;
    } else {
      footerLink.textContent = '';
      footerLink.removeAttribute('href');
    }

    clearBody();

    if (!data.rows || data.rows.length === 0) {
      body.appendChild(el('div', 'dd-empty', 'Hech narsa yo\'q'));
      return;
    }

    const table = document.createElement('table');
    table.className = 'dd-table';

    const thead = document.createElement('thead');
    const trHead = document.createElement('tr');
    (data.headers || []).forEach(h => {
      const th = el('th', null, h);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    data.rows.forEach(row => {
      const tr = document.createElement('tr');
      row.forEach(cell => {
        const td = el('td', null, cell === null || cell === undefined ? '' : String(cell));
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    body.appendChild(table);
  }

  function showError(msg) {
    clearBody();
    body.appendChild(el('div', 'dd-empty', 'Xato: ' + (msg || 'yuklab bo\'lmadi')));
  }

  function fetchData(kind) {
    const seq = ++fetchSeq;
    fetch('/api/dashboard/v2/drilldown?kind=' + encodeURIComponent(kind), {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    })
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(data => {
        if (seq !== fetchSeq) return;
        renderData(data);
      })
      .catch(err => {
        if (seq !== fetchSeq) return;
        showError(err.message || 'fetch xato');
      });
  }

  // Global keydown - Esc bilan yopish
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen()) {
      e.preventDefault();
      close();
    }
  });

  // KPI card'larga click handler — DOM tayyor bo'lganda
  function bindClicks() {
    document.querySelectorAll('[data-drilldown]').forEach(card => {
      if (card.__ddBound) return;
      card.__ddBound = true;
      card.addEventListener('click', (e) => {
        const kind = card.getAttribute('data-drilldown');
        if (kind) open(kind);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindClicks);
  } else {
    bindClicks();
  }

  window.dashboardDrilldown = { open: open, close: close };
})();
