/* TOTLI BI — 1C uslubidagi kalkulyator
   Foydalanish: <input ... data-calc>
   F4 yoki 🧮 tugma — modal ochiladi
   Klaviatura: 0-9, + - * / . ( ), Enter=qabul, Esc=bekor
   Modal HTML _input_calc_modal.html partial ichida (base.html include qiladi)
*/
(function () {
  'use strict';

  var SAFE_EXPR = /^[\d\s+\-*/().]+$/;
  var modalEl = null;
  var displayEl = null;
  var backdropEl = null;
  var targetInput = null;
  var isOpen = false;

  function ensureModal() {
    if (modalEl) return true;
    modalEl = document.getElementById('inputCalcModal');
    displayEl = document.getElementById('inputCalcDisplay');
    if (!modalEl || !displayEl) {
      console.error('[InputCalc] Modal element topilmadi — server restart kerak bo\'lishi mumkin (base.html yangilanmagan)');
      return false;
    }
    bindModalEvents();
    return true;
  }

  function bindModalEvents() {
    modalEl.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      if (btn.classList.contains('btn-close') || btn.getAttribute('data-bs-dismiss') === 'modal') {
        hideCalc();
        return;
      }
      if (btn.id === 'inputCalcAccept') { acceptResult(); return; }
      if (btn.dataset.num != null) appendChar(btn.dataset.num);
      else if (btn.dataset.op != null) appendChar(btn.dataset.op);
      else if (btn.dataset.act === 'C') displayEl.value = '';
      else if (btn.dataset.act === 'CE') displayEl.value = '';
      else if (btn.dataset.act === 'BACK') displayEl.value = displayEl.value.slice(0, -1);
      else if (btn.dataset.act === '(' || btn.dataset.act === ')') appendChar(btn.dataset.act);
      displayEl.focus();
    });

    displayEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); acceptResult(); }
      else if (e.key === 'Escape') { e.preventDefault(); hideCalc(); }
    });
  }

  function showCalc() {
    var parentModalShow = document.querySelector('.modal.show');
    var baseZ = parentModalShow ? (parseInt(getComputedStyle(parentModalShow).zIndex, 10) || 1055) : 1055;
    var calcZ = baseZ + 20;

    if (!backdropEl) {
      backdropEl = document.createElement('div');
      backdropEl.className = 'modal-backdrop fade show';
    }
    backdropEl.style.zIndex = String(calcZ - 5);
    document.body.appendChild(backdropEl);

    modalEl.style.display = 'block';
    modalEl.style.zIndex = String(calcZ);
    modalEl.removeAttribute('aria-hidden');
    modalEl.setAttribute('aria-modal', 'true');
    void modalEl.offsetWidth;
    modalEl.classList.add('show');
    isOpen = true;

    setTimeout(function () { displayEl.focus(); displayEl.select(); }, 50);
  }

  function hideCalc() {
    if (!isOpen) return;
    modalEl.classList.remove('show');
    modalEl.style.display = 'none';
    modalEl.setAttribute('aria-hidden', 'true');
    modalEl.removeAttribute('aria-modal');
    if (backdropEl && backdropEl.parentNode) backdropEl.parentNode.removeChild(backdropEl);
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

  function acceptResult() {
    var v = evaluate(displayEl.value);
    if (v === null) {
      displayEl.classList.add('is-invalid');
      setTimeout(function () { displayEl.classList.remove('is-invalid'); }, 600);
      return;
    }
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
    btn.addEventListener('click', function () { openCalc(input); });

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
