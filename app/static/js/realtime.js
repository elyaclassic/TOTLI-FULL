/* Realtime WebSocket client — /dashboard/v2 KPI live update.
 * - Auto-reconnect 5s interval
 * - Ping 30s
 * - Event handlers: sale_created, production_completed, cash_transfer_created
 * - DOM update: KPI value + delta animation (pulse green/cyan)
 */
(function () {
  'use strict';

  if (window.__realtimeInit) return;
  window.__realtimeInit = true;

  // Faqat /dashboard/v2 da ishlaydi
  if (!document.body.classList.contains('d2-active') && !window.location.pathname.startsWith('/dashboard/v2')) {
    return;
  }

  const RECONNECT_MS = 5000;
  const PING_MS = 30000;

  let ws = null;
  let pingTimer = null;
  let reconnectTimer = null;
  let isClosing = false;

  function wsUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + window.location.host + '/ws/dashboard/v2';
  }

  function connect() {
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      console.warn('[realtime] WS create fail:', e);
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      console.log('[realtime] connected');
      // Status indicator pulse green
      pulseIndicator('online');
      startPing();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleEvent(data);
      } catch (e) {
        // Plain text (e.g. pong)
        if (event.data === 'pong') return;
      }
    };

    ws.onclose = () => {
      console.log('[realtime] closed');
      stopPing();
      pulseIndicator('offline');
      if (!isClosing) scheduleReconnect();
    };

    ws.onerror = (e) => {
      console.warn('[realtime] error:', e);
    };
  }

  function startPing() {
    stopPing();
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send('ping'); } catch (e) { /* ignore */ }
      }
    }, PING_MS);
  }

  function stopPing() {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_MS);
  }

  function handleEvent(data) {
    const type = data.type;
    const p = data.payload || {};
    if (type === 'sale_created') {
      bumpKpi('sales', p.amount, p.count_delta || 1);
    } else if (type === 'production_completed') {
      bumpKpi('production', null, null, p.kg);
    } else if (type === 'cash_transfer_created') {
      bumpKpi('cash', p.amount);
    }
  }

  // KPI raqamlarini yangilash (animatsiya bilan)
  function bumpKpi(kind, amount, countDelta, kg) {
    // Bu funksiya soddalashtirilgan — to'liq raqam update qilmaydi,
    // faqat "pulse" effect ko'rsatadi va flash banner chiqaradi
    // (sahifa qayta yuklamasdan to'liq raqam update qilish uchun
    // backend'dan yangi snapshot olish kerak — keyingi iter).
    pulseKpiCard(kind);
    showToast(kind, amount, countDelta, kg);
  }

  function pulseKpiCard(kind) {
    const map = {
      'sales': '[data-drilldown="sales"]',
      'production': '[data-drilldown="production"]',
      'cash': '[data-drilldown="cash"]',
    };
    const sel = map[kind];
    if (!sel) return;
    const el = document.querySelector(sel);
    if (!el) return;
    el.classList.remove('rt-pulse');
    void el.offsetWidth; // reflow
    el.classList.add('rt-pulse');
  }

  function showToast(kind, amount, countDelta, kg) {
    const c = ensureToastContainer();
    const t = document.createElement('div');
    t.className = 'rt-toast';
    const map = {
      'sales': { icon: 'bi-cart-check', label: 'Yangi sotuv', color: '#00FF88' },
      'production': { icon: 'bi-gear', label: 'Yangi production', color: '#00D9FF' },
      'cash': { icon: 'bi-cash-coin', label: 'Yangi inkasatsiya', color: '#FFB020' },
    };
    const cfg = map[kind] || { icon: 'bi-bell', label: 'Yangilik', color: '#9CA3AF' };

    const icon = document.createElement('i');
    icon.className = 'bi ' + cfg.icon;
    icon.style.color = cfg.color;
    t.appendChild(icon);

    const labelEl = document.createElement('span');
    labelEl.className = 'rt-toast-label';
    labelEl.textContent = cfg.label;
    t.appendChild(labelEl);

    if (amount) {
      const amt = document.createElement('span');
      amt.className = 'rt-toast-amt';
      amt.textContent = formatShort(amount) + ' so\'m';
      t.appendChild(amt);
    } else if (kg) {
      const amt = document.createElement('span');
      amt.className = 'rt-toast-amt';
      amt.textContent = formatKg(kg);
      t.appendChild(amt);
    }

    c.appendChild(t);
    setTimeout(() => t.classList.add('rt-toast-show'), 10);
    setTimeout(() => {
      t.classList.remove('rt-toast-show');
      setTimeout(() => t.remove(), 300);
    }, 4000);
  }

  function ensureToastContainer() {
    let c = document.getElementById('rt-toasts');
    if (!c) {
      c = document.createElement('div');
      c.id = 'rt-toasts';
      c.className = 'rt-toasts';
      document.body.appendChild(c);
    }
    return c;
  }

  function pulseIndicator(state) {
    // Cockpit bar'dagi pulse dot — yashildan ko'kga (online) yoki bo'r (offline)
    const dot = document.querySelector('.d2-pulse-dot');
    if (dot) {
      dot.classList.toggle('rt-offline', state === 'offline');
    }
  }

  function formatShort(n) {
    n = Number(n) || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
    return String(Math.round(n));
  }

  function formatKg(n) {
    n = Number(n) || 0;
    if (n >= 1000) return (n / 1000).toFixed(2) + 't';
    return n.toFixed(1) + 'kg';
  }

  // Sahifa ochilganda darhol ulan
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connect);
  } else {
    connect();
  }

  // Yopilganda WS uzish
  window.addEventListener('beforeunload', () => {
    isClosing = true;
    if (ws) try { ws.close(); } catch (e) { /* ignore */ }
  });

  window.realtime = { connect: connect, close: () => { isClosing = true; if (ws) ws.close(); } };
})();
