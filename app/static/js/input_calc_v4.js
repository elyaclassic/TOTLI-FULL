/* TOTLI BI — Kalkulyator widget (v4 — Bootstrap'sdan butunlay mustaqil)
   Foydalanish: <input ... data-calc>
   F4 yoki 🧮 tugma — popup ochiladi (parent modal saqlanadi)
   Klaviatura: 0-9, + - * / . ( ), Enter=qabul, Esc=bekor, = hisoblash
*/
(function () {
  'use strict';

  console.log('[InputCalc v4.1] loaded');

  var SAFE_EXPR = /^[\d\s+\-*/().]+$/;
  var modalEl = null;
  var backdropEl = null;
  var displayEl = null;
  var targetInput = null;
  var isOpen = false;

  function ensureModal() {
    if (modalEl) return true;
    modalEl = document.getElementById('inputCalcModal');
    backdropEl = document.getElementById('inputCalcBackdrop');
    displayEl = document.getElementById('inputCalcDisplay');
    if (!modalEl || !backdropEl || !displayEl) {
      console.error('[InputCalc v4.1] DOM elementlar topilmadi — base.html yangilanmagan');
      return false;
    }
    bindEvents();
    return true;
  }

  function bindEvents() {
    modalEl.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      e.stopPropagation();
      handleButton(btn);
      displayEl.focus();
    });

    backdropEl.addEventListener('click', function () { hideCalc(); });

    // Bootstrap _enforceFocus bypass: capture phase + stopPropagation
    // Bootstrap document.focusin listener'ini kalkulyator focus event'iga yetkazmaymiz
    document.addEventListener('focusin', function (e) {
      if (isOpen && modalEl.contains(e.target)) {
        e.stopImmediatePropagation();
      }
    }, true);

    // Klaviatura — modal ichidagi har qanday tugma (display'da bo'lmasa ham)
    modalEl.addEventListener('keydown', handleKey);
    displayEl.addEventListener('keydown', handleKey);
  }

  function handleKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); acceptResult(); return; }
    if (e.key === 'Escape') { e.preventDefault(); hideCalc(); return; }
    if (e.key === '=') { e.preventDefault(); computeInPlace(); return; }
    // Boshqa tugmalar (raqamlar, operatorlar) — default text input xulqi ishlaydi
    // chunki displayEl type=text
  }

  function handleButton(btn) {
    if (btn.hasAttribute('data-calc-close')) { hideCalc(); return; }
    if (btn.id === 'inputCalcAccept') { acceptResult(); return; }
    if (btn.dataset.num != null) appendChar(btn.dataset.num);
    else if (btn.dataset.op != null) appendChar(btn.dataset.op);
    else if (btn.dataset.act === 'C') displayEl.value = '';
    else if (btn.dataset.act === 'CE') displayEl.value = '';
    else if (btn.dataset.act === 'BACK') displayEl.value = displayEl.value.slice(0, -1);
    else if (btn.dataset.act === '(' || btn.dataset.act === ')') appendChar(btn.dataset.act);
    else if (btn.dataset.act === 'EQ') computeInPlace();
  }

  function showCalc() {
    console.log('[InputCalc v4.1] showCalc()');
    backdropEl.classList.add('is-open');
    modalEl.classList.add('is-open');
    isOpen = true;
    setTimeout(function () { displayEl.focus(); displayEl.select(); }, 50);
  }

  function hideCalc() {
    if (!isOpen) return;
    modalEl.classList.remove('is-open');
    backdropEl.classList.remove('is-open');
    isOpen = false;
    setTimeout(function () { targetInput && targetInput.focus(); }, 50);
  }

  function appendChar(ch) {
    displayEl.value = (displayEl.value || '') + ch;
  }

  function evaluate(expr) {
    var s = String(expr).replace(/\s+/g, '').replace(/,/g, '.');
    if (!s) return null;
    if (!SAFE_EXPR.test(s)) return null;
    try {
      var v = Function('"use strict"; return (' + s + ')')();
      if (typeof v !== 'number' || !isFinite(v)) return null;
      return v;
    } catch (e) {
      return null;
    }
  }

  function flashInvalid() {
    displayEl.classList.add('is-invalid');
    setTimeout(function () { displayEl.classList.remove('is-invalid'); }, 600);
  }

  // = tugmasi: hisoblab natijani display'ga yozadi, modal yopilmaydi
  function computeInPlace() {
    var v = evaluate(displayEl.value);
    if (v === null) { flashInvalid(); return; }
    displayEl.value = String(Math.round(v * 100) / 100);
    displayEl.focus();
  }

  // Qabul qilish / Enter: natijani input'ga yuboradi va yopadi
  function acceptResult() {
    var v = evaluate(displayEl.value);
    if (v === null) { flashInvalid(); return; }
    var rounded = Math.round(v * 100) / 100;
    if (targetInput) {
      targetInput.value = rounded;
      targetInput.dispatchEvent(new Event('input', { bubbles: true }));
      targetInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    hideCalc();
  }

  function openCalc(input) {
    if (!ensureModal()) return;
    targetInput = input;
    displayEl.value = input.value || '';
    showCalc();
  }

  function attach(input) {
    if (input.dataset.calcBound) return;
    input.dataset.calcBound = '1';

    input.addEventListener('keydown', function (e) {
      if (e.key === 'F4') { e.preventDefault(); openCalc(input); }
    });

    var wrap = document.createElement('span');
    wrap.className = 'input-calc-wrap';
    wrap.style.cssText = 'position:relative;display:block;';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-outline-secondary input-calc-trigger';
    btn.title = 'Kalkulyator (F4)';
    btn.setAttribute('aria-label', 'Kalkulyator');
    var icon = document.createElement('i');
    icon.className = 'bi bi-calculator';
    btn.appendChild(icon);
    btn.style.cssText = 'position:absolute;right:8px;top:50%;transform:translateY(-50%);z-index:5;padding:.2rem .5rem;line-height:1;';
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      openCalc(input);
    });

    if (input.type === 'number') {
      input.style.appearance = 'textfield';
      input.style.MozAppearance = 'textfield';
    }
    input.style.paddingRight = '44px';
    wrap.appendChild(btn);
  }

  function scan(root) {
    (root || document).querySelectorAll('input[data-calc]').forEach(attach);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(); });
  } else {
    scan();
  }

  window.InputCalc = { open: openCalc, attach: attach, scan: scan };
})();
