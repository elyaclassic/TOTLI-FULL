(function() {
    var trigger = document.getElementById('posReceiptTrigger');
    if (trigger && trigger.getAttribute('data-receipt-number')) {
        var num = trigger.getAttribute('data-receipt-number');
        var receiptUrl = '/sales/pos/receipt?number=' + encodeURIComponent(num) + '&print=1';
        var w = window.open(receiptUrl, 'pos_receipt', 'width=320,height=520,scrollbars=yes');
        if (!w && typeof console !== 'undefined') console.warn('Chek oynasi bloklandi. Brauzerda popup ruxsat bering.');
    }

    /* To'liq ekran taklifi — sahifa ochilganda ko'rsatiladi */
    var fullscreenPrompt = document.getElementById('posFullscreenPrompt');
    var fullscreenBtn = document.getElementById('posFullscreenBtn');
    var fullscreenDismiss = document.getElementById('posFullscreenDismiss');
    var POS_FULLSCREEN_DISMISSED = 'pos_fullscreen_dismissed';
    function isFullscreen() {
        return !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);
    }
    function requestFullscreen() {
        var el = document.documentElement;
        var p = null;
        if (el.requestFullscreen) p = el.requestFullscreen();
        else if (el.webkitRequestFullscreen) p = el.webkitRequestFullscreen();
        else if (el.mozRequestFullScreen) p = el.mozRequestFullScreen();
        else if (el.msRequestFullscreen) p = el.msRequestFullscreen();
        if (fullscreenPrompt) fullscreenPrompt.style.display = 'none';
        if (p && typeof p.catch === 'function') {
            p.catch(function(err) {
                console.warn('To\'liq ekran so\'rovi rad etildi yoki muvaffaqiyatsiz:', err && err.name ? err.name : err);
            });
        }
    }
    function exitFullscreen() {
        if (document.exitFullscreen) document.exitFullscreen();
        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
        else if (document.mozCancelFullScreen) document.mozCancelFullScreen();
        else if (document.msExitFullscreen) document.msExitFullscreen();
    }
    /* To'liq ekran taklifi — har sahifa ochilganda ko'rsatiladi (sotuvchi doim eslatilsin) */
    if (fullscreenPrompt && !isFullscreen()) {
        setTimeout(function() {
            if (!isFullscreen() && fullscreenPrompt) fullscreenPrompt.style.display = 'flex';
        }, 400);
    }
    if (fullscreenBtn) fullscreenBtn.addEventListener('click', function() {
        requestFullscreen();
    });
    if (fullscreenDismiss) fullscreenDismiss.addEventListener('click', function() {
        fullscreenPrompt.style.display = 'none';
    });
    document.addEventListener('fullscreenchange', function() {
        if (!isFullscreen() && fullscreenPrompt) fullscreenPrompt.style.display = 'none';
    });
    document.addEventListener('webkitfullscreenchange', function() {
        if (!isFullscreen() && fullscreenPrompt) fullscreenPrompt.style.display = 'none';
    });


    /* Ochiq kunlar banneri — yopilmagan/to'liq emas Z-hisobotlar */
    var openDaysBanner = document.getElementById('posOpenDaysBanner');
    var openDaysList = document.getElementById('posOpenDaysList');
    var openDaysClose = document.getElementById('posOpenDaysClose');
    var OPEN_DAYS_DISMISS_KEY = 'pos_open_days_dismissed';

    function fmtNum(n) {
        try { return new Intl.NumberFormat('ru-RU').format(Math.round(Number(n) || 0)); }
        catch (e) { return String(n); }
    }

    function makeIcon(cls) {
        var i = document.createElement('i');
        i.className = cls;
        return i;
    }

    function makeBtn(it) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-warning';
        btn.appendChild(makeIcon('bi bi-lock'));
        btn.appendChild(document.createTextNode(' ' + it.date_display + " ni yopish"));
        btn.addEventListener('click', function() { closeOpenDay(it, btn); });
        return btn;
    }

    function renderOpenDays(items) {
        if (!openDaysList) return;
        while (openDaysList.firstChild) openDaysList.removeChild(openDaysList.firstChild);
        items.forEach(function(it) {
            var row = document.createElement('div');
            row.className = 'd-flex justify-content-between align-items-center gap-2 py-1 border-bottom';
            var info = document.createElement('div');
            var dateB = document.createElement('strong');
            dateB.textContent = it.date_display;
            info.appendChild(dateB);
            info.appendChild(document.createTextNode(' — '));
            if (it.status === 'no_z') {
                info.appendChild(document.createTextNode(
                    "Z-hisobot bosilmagan: " + (it.sales_count || 0) + " ta sotuv, " + fmtNum(it.sales_total) + " so'm"
                ));
            } else {
                var lz = it.last_z || {};
                var t = (lz.closed_at || '').slice(11, 19);
                info.appendChild(document.createTextNode("Z " + t + " da bosilgan, ammo keyin yana "));
                var strong = document.createElement('strong');
                strong.textContent = it.orphan_count + " ta sotuv (" + fmtNum(it.orphan_total) + " so'm)";
                info.appendChild(strong);
                info.appendChild(document.createTextNode(" qo'shilgan — Z to'liq emas"));
            }
            row.appendChild(info);
            row.appendChild(makeBtn(it));
            openDaysList.appendChild(row);
        });
    }

    function closeOpenDay(it, btn) {
        var msg;
        if (it.status === 'no_z') {
            msg = it.date_display + " uchun Z-hisobotni yopasizmi?\n\n" +
                  "  • Sotuvlar: " + (it.sales_count || 0) + " ta\n" +
                  "  • Summa: " + fmtNum(it.sales_total) + " so'm\n\n" +
                  "Snapshot fayl tarixga saqlanadi.";
        } else {
            msg = it.date_display + " uchun Z-hisobotni QAYTA yopasizmi?\n\n" +
                  "  • Jami: " + (it.sales_count || 0) + " ta sotuv, " + fmtNum(it.sales_total) + " so'm\n" +
                  "  • Eski Z'dan keyin yangi: " + it.orphan_count + " ta (" + fmtNum(it.orphan_total) + " so'm)\n\n" +
                  "Yangi Z to'liq kun bo'yicha jamlanadi. Eski Z fayl saqlanadi (dublikat sifatida).";
        }
        if (!confirm(msg)) return;
        btn.disabled = true;
        while (btn.firstChild) btn.removeChild(btn.firstChild);
        btn.appendChild(makeIcon('bi bi-hourglass-split'));
        btn.appendChild(document.createTextNode(' Saqlanmoqda...'));
        var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).getAttribute('content') || '';
        var headers = {'Content-Type': 'application/json', 'Accept': 'application/json'};
        if (csrf) headers['X-CSRF-Token'] = csrf;
        fetch('/sales/pos/z-report', {
            method: 'POST',
            credentials: 'same-origin',
            headers: headers,
            body: JSON.stringify({date: it.date})
        })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d && d.ok) {
                    btn.className = 'btn btn-sm btn-success';
                    while (btn.firstChild) btn.removeChild(btn.firstChild);
                    btn.appendChild(makeIcon('bi bi-check-circle'));
                    btn.appendChild(document.createTextNode(' Yopildi'));
                    setTimeout(loadOpenDays, 800);
                    // Z-hisobot chek shaklida avtomatik chop etish uchun ochish
                    if (d.snapshot_id) {
                        try { window.open('/reports/z-reports/' + encodeURIComponent(d.snapshot_id) + '?fmt=receipt', '_blank'); }
                        catch (e) { /* popup blocked */ }
                    }
                } else {
                    btn.disabled = false;
                    while (btn.firstChild) btn.removeChild(btn.firstChild);
                    btn.appendChild(makeIcon('bi bi-lock'));
                    btn.appendChild(document.createTextNode(' ' + it.date_display + " ni yopish"));
                    alert('Xato: ' + (d && d.error ? d.error : 'noma\'lum'));
                }
            })
            .catch(function() {
                btn.disabled = false;
                while (btn.firstChild) btn.removeChild(btn.firstChild);
                btn.appendChild(makeIcon('bi bi-lock'));
                btn.appendChild(document.createTextNode(' ' + it.date_display + " ni yopish"));
                alert('Tarmoq xatosi');
            });
    }

    function loadOpenDays() {
        if (!openDaysBanner) return;
        try {
            if (sessionStorage.getItem(OPEN_DAYS_DISMISS_KEY) === '1') return;
        } catch (e) { /* ignore */ }
        fetch('/sales/pos/z-report/open-days?days=5', {
            credentials: 'same-origin',
            headers: {'Accept': 'application/json'}
        })
            .then(function(r) { return r.json().catch(function() { return {ok: false}; }); })
            .then(function(d) {
                if (!d || !d.ok || !d.items || !d.items.length) {
                    openDaysBanner.classList.add('d-none');
                    return;
                }
                renderOpenDays(d.items);
                openDaysBanner.classList.remove('d-none');
            })
            .catch(function() { /* tarmoq xato — banner ko'rsatilmaydi */ });
    }

    if (openDaysClose) {
        openDaysClose.addEventListener('click', function() {
            openDaysBanner.classList.add('d-none');
            try { sessionStorage.setItem(OPEN_DAYS_DISMISS_KEY, '1'); } catch (e) { /* ignore */ }
        });
    }
    loadOpenDays();


    /* window._posCanEditPrice — template da o'rnatiladi */

    var form = document.getElementById('posForm');
    var cartHidden = document.getElementById('posCartHidden');
    var cartBody = document.getElementById('posCartBody');
    var cartEmpty = document.getElementById('posCartEmpty');
    var cartTotalEl = document.getElementById('posCartTotal');
    var btnSotuv = document.getElementById('posBtnSotuv');
    var btnClearCart = document.getElementById('posBtnClearCart');
    var paymentModal = document.getElementById('posPaymentModal');
    var posSearch = document.getElementById('posSearch');
    var posBarcode = document.getElementById('posBarcode');
    var cart = [];
    var POS_CART_KEY = 'pos_savat';
    var posStockByProduct = {};
    document.querySelectorAll('.pos-product-card-premium').forEach(function(c) {
        var id = c.getAttribute('data-product-id');
        var s = c.getAttribute('data-stock');
        if (id && s !== null && s !== '') { posStockByProduct[parseInt(id, 10)] = parseFloat(s) || 0; }
    });

    function saveCartToStorage() {
        try { sessionStorage.setItem(POS_CART_KEY, JSON.stringify(cart)); } catch (e) {}
    }
    function restoreCartFromStorage() {
        try {
            var raw = sessionStorage.getItem(POS_CART_KEY);
            if (!raw) return;
            var arr = JSON.parse(raw);
            if (Array.isArray(arr) && arr.length) {
                cart = arr;
                renderCart();
            }
            sessionStorage.removeItem(POS_CART_KEY);
        } catch (e) {}
    }

    function addToCart(productId, productName, price, quantity, maxStock) {
        quantity = parseFloat(quantity) || 1;
        if (quantity <= 0) return;
        price = parseFloat(price) || 0;
        productId = parseInt(productId, 10);
        maxStock = (maxStock !== undefined && maxStock !== null && maxStock !== '') ? parseFloat(maxStock) : null;
        var existing = cart.filter(function(x) { return x.productId === productId; })[0];
        var alreadyInCart = existing ? (existing.quantity || 0) : 0;
        if (maxStock !== null && !isNaN(maxStock) && (alreadyInCart + quantity) > maxStock) {
            quantity = Math.max(0, maxStock - alreadyInCart);
            if (quantity <= 0) return;
        }
        if (existing) {
            existing.quantity += quantity;
        } else {
            cart.push({ productId: productId, productName: productName, price: price, quantity: quantity });
        }
        renderCart();
    }

    function removeFromCart(index) {
        cart.splice(index, 1);
        renderCart();
    }

    function changeQty(index, delta) {
        if (!cart[index]) return;
        var pid = cart[index].productId;
        var maxQ = posStockByProduct[pid];
        var q = Math.round((cart[index].quantity + delta) * 100) / 100;
        if (delta < 0 && q < 1) {
            if (confirm('"' + (cart[index].productName || 'Mahsulot') + '" savatdan olib tashlansinmi?')) {
                removeFromCart(index);
            }
            return;
        }
        if (q < 0.01) q = 0.01;
        if (maxQ !== undefined && !isNaN(maxQ) && q > maxQ) q = maxQ;
        cart[index].quantity = q;
        renderCart();
    }

    function clearCart() {
        if (cart.length && confirm('Savatni tozalashni xohlaysizmi?')) {
            cart = [];
            renderCart();
        }
    }

    function renderCart() {
        cartBody.innerHTML = '';
        cartHidden.innerHTML = '';
        var total = 0;
        cart.forEach(function(item, i) {
            var qty = Number(item.quantity) || 0;
            var pr = Number(item.price) || 0;
            var sum = qty * pr;
            total += sum;
            var tr = document.createElement('tr');
            tr.innerHTML = '<td class="text-truncate align-middle" style="max-width:100px" title="' + (item.productName || '').replace(/"/g, '&quot;') + '">' + (item.productName || '') + '</td>' +
                '<td class="align-middle"><div class="input-group input-group-sm" style="width:100px"><button type="button" class="btn btn-outline-secondary cart-minus" data-index="' + i + '">−</button><input type="number" class="form-control form-control-sm cart-qty text-center" data-index="' + i + '" value="' + item.quantity + '" step="1" min="0.01"><button type="button" class="btn btn-outline-secondary cart-plus" data-index="' + i + '">+</button></div></td>' +
                '<td class="align-middle"><span class="cart-price-display" style="font-size:0.85rem;font-weight:600;color:#2c3e50;white-space:nowrap;">' + (pr || 0).toLocaleString('ru-RU') + '</span><input type="hidden" class="cart-price" data-index="' + i + '" value="' + item.price + '"></td>' +
                '<td class="cart-sum align-middle">' + (sum || 0).toLocaleString('ru-RU') + '</td>' +
                '<td class="align-middle"><button type="button" class="btn btn-sm btn-outline-danger cart-remove" data-index="' + i + '"><i class="bi bi-trash"></i></button></td>';
            cartBody.appendChild(tr);
            cartHidden.appendChild((function(){ var h=document.createElement('input'); h.type='hidden'; h.name='product_id'; h.value=item.productId; return h; })());
            cartHidden.appendChild((function(){ var h=document.createElement('input'); h.type='hidden'; h.name='quantity'; h.value=item.quantity; return h; })());
            cartHidden.appendChild((function(){ var h=document.createElement('input'); h.type='hidden'; h.name='price'; h.value=item.price; return h; })());
        });
        cartBody.querySelectorAll('.cart-remove').forEach(function(btn) {
            btn.addEventListener('click', function() { removeFromCart(parseInt(this.getAttribute('data-index'), 10)); });
        });
        cartBody.querySelectorAll('.cart-minus').forEach(function(btn) {
            btn.addEventListener('click', function() { changeQty(parseInt(this.getAttribute('data-index'), 10), -1); });
        });
        cartBody.querySelectorAll('.cart-plus').forEach(function(btn) {
            btn.addEventListener('click', function() { changeQty(parseInt(this.getAttribute('data-index'), 10), 1); });
        });
        cartBody.querySelectorAll('.cart-qty').forEach(function(inp) {
            inp.addEventListener('wheel', function(e) { e.preventDefault(); this.blur(); }, { passive: false });
            inp.addEventListener('change', function() {
                var i = parseInt(this.getAttribute('data-index'), 10);
                var q = Math.round((parseFloat(this.value) || 0) * 100) / 100;
                if (q <= 0) q = 1;
                var pid = cart[i] && cart[i].productId;
                var maxQ = pid !== undefined ? posStockByProduct[pid] : undefined;
                if (maxQ !== undefined && !isNaN(maxQ) && q > maxQ) q = maxQ;
                this.value = q;
                if (cart[i]) { cart[i].quantity = q; renderCart(); }
            });
        });
        cartBody.querySelectorAll('input.cart-price[type="number"]').forEach(function(inp) {
            inp.addEventListener('change', function() {
                var i = parseInt(this.getAttribute('data-index'), 10);
                var p = parseFloat(this.value) || 0;
                if (p < 0) p = 0;
                this.value = p;
                if (cart[i]) { cart[i].price = p; renderCart(); }
            });
        });
        var posDiscountInputEl = document.getElementById('posDiscountInput');
        var posDiscountTypeEl = document.getElementById('posDiscountType');
        function normalizeDiscountInput() {
            if (!posDiscountInputEl) return;
            var v = (posDiscountInputEl.value || '').trim();
            if (/^0\d+$/.test(v)) {
                posDiscountInputEl.value = parseFloat(v) || 0;
            } else if (/^0\d*\.\d*$/.test(v) === false && v !== '' && v !== '0') {
                var num = parseFloat(v);
                if (!isNaN(num) && num >= 0 && String(num) !== v) {
                    posDiscountInputEl.value = num;
                }
            }
        }
        if (posDiscountInputEl) {
            posDiscountInputEl.addEventListener('input', function() { normalizeDiscountInput(); renderCart(); });
            posDiscountInputEl.addEventListener('change', function() { normalizeDiscountInput(); renderCart(); });
        }
        cartEmpty.style.display = cart.length ? 'none' : 'block';
        saveCartToStorage();
        if (cartTotalEl) cartTotalEl.textContent = total.toLocaleString('ru-RU');
        var discountInput = document.getElementById('posDiscountInput');
        var discountTypeSelect = document.getElementById('posDiscountType');
        var discountRow = document.getElementById('posDiscountRow');
        var discountDisplay = document.getElementById('posDiscountDisplay');
        var totalFinalEl = document.getElementById('posCartTotalFinal');
        var discountPercentHidden = document.getElementById('posDiscountPercent');
        var discountAmountHidden = document.getElementById('posDiscountAmount');
        var discountVal = (discountInput && parseFloat(discountInput.value)) || 0;
        if (discountVal < 0) discountVal = 0;
        var discountType = (discountTypeSelect && discountTypeSelect.value) || 'amount';
        var discountSum = 0;
        if (discountType === 'percent') {
            discountSum = total * discountVal / 100;
            if (discountPercentHidden) discountPercentHidden.value = discountVal;
            if (discountAmountHidden) discountAmountHidden.value = 0;
        } else {
            discountSum = discountVal;
            if (discountPercentHidden) discountPercentHidden.value = 0;
            if (discountAmountHidden) discountAmountHidden.value = discountSum;
        }
        if (discountSum > total) discountSum = total;
        var totalFinal = total - discountSum;
        if (discountRow) discountRow.style.display = discountSum > 0 ? '' : 'none';
        if (discountDisplay) discountDisplay.textContent = discountSum.toLocaleString('ru-RU');
        if (totalFinalEl) totalFinalEl.textContent = totalFinal.toLocaleString('ru-RU');
        if (btnSotuv) btnSotuv.disabled = cart.length === 0;
        if (btnClearCart) btnClearCart.style.display = cart.length ? 'block' : 'none';
        var countBadge = document.getElementById('posCartCountBadge');
        if (countBadge) { countBadge.textContent = cart.length; countBadge.style.display = cart.length ? 'flex' : 'none'; }
        var hq = cartHidden.querySelectorAll('input[name="quantity"]');
        var hp = cartHidden.querySelectorAll('input[name="price"]');
        cart.forEach(function(item, i) {
            if (hq[i]) hq[i].value = item.quantity;
            if (hp[i]) hp[i].value = item.price;
        });
    }

    // Tovar kartochkalariga click + 3D tilt
    function initProductCards() {
        var grid = document.getElementById('posProductGrid');
        if (!grid) return;
        grid.addEventListener('click', function(e) {
            var card = e.target;
            while (card && card !== grid) {
                if (card.classList && card.classList.contains('pos-product-card-premium')) {
                    addToCart(card.getAttribute('data-product-id'), card.getAttribute('data-name'), card.getAttribute('data-price'), 1, card.getAttribute('data-stock'));
                    // Flash effekt
                    card.style.boxShadow = '0 0 0 3px rgba(13,107,75,0.5), 0 8px 24px rgba(13,107,75,0.2)';
                    setTimeout(function() { card.style.boxShadow = ''; }, 300);
                    return;
                }
                card = card.parentElement;
            }
        });
        // 3D tilt effekt — sichqoncha harakatida
        grid.addEventListener('mousemove', function(e) {
            var card = e.target;
            while (card && card !== grid) {
                if (card.classList && card.classList.contains('pos-product-card-premium')) {
                    var rect = card.getBoundingClientRect();
                    var x = (e.clientX - rect.left) / rect.width - 0.5;
                    var y = (e.clientY - rect.top) / rect.height - 0.5;
                    card.style.transform = 'translateY(-6px) rotateY(' + (x * 8) + 'deg) rotateX(' + (-y * 8) + 'deg)';
                    return;
                }
                card = card.parentElement;
            }
        });
        grid.addEventListener('mouseleave', function(e) {
            var cards = grid.querySelectorAll('.pos-product-card-premium');
            for (var i = 0; i < cards.length; i++) cards[i].style.transform = '';
        });
        grid.addEventListener('mouseout', function(e) {
            var card = e.target;
            while (card && card !== grid) {
                if (card.classList && card.classList.contains('pos-product-card-premium')) {
                    card.style.transform = '';
                    return;
                }
                card = card.parentElement;
            }
        });
    }
    initProductCards();

    var posWarehouseSelect = document.getElementById('posWarehouseSelect');
    if (posWarehouseSelect) {
        posWarehouseSelect.addEventListener('change', function() {
            var id = this.value;
            if (!id) return;
            saveCartToStorage();
            window.location.href = '/sales/pos?warehouse_id=' + encodeURIComponent(id);
        });
    }
    (function() {
        var partnerSelect = document.getElementById('posPartnerSelect');
        var dueWrap = document.getElementById('posPaymentDueDateWrap');
        var dueInput = document.getElementById('posPaymentDueDate');
        if (!partnerSelect || !dueWrap) return;
        var defaultId = String((dueWrap.getAttribute('data-default-partner-id') || '').trim());
        function toggleDueDate() {
            var sel = String((partnerSelect.value || '').trim());
            var isOtherPartner = sel && (defaultId ? sel !== defaultId : true);
            if (isOtherPartner) {
                dueWrap.style.display = '';
                if (dueInput) {
                    var d = new Date();
                    d.setDate(d.getDate() + 7);
                    dueInput.value = d.toISOString().slice(0, 10);
                }
            } else {
                dueWrap.style.display = 'none';
                if (dueInput) dueInput.value = '';
            }
        }
        partnerSelect.addEventListener('change', toggleDueDate);
        toggleDueDate();
    })();
    var posDiscountInputEl = document.getElementById('posDiscountInput');
    var posDiscountTypeEl = document.getElementById('posDiscountType');
    function normalizeDiscountInput() {
        if (!posDiscountInputEl) return;
        var v = (posDiscountInputEl.value || '').trim();
        if (/^0\d+$/.test(v)) {
            posDiscountInputEl.value = parseFloat(v) || 0;
        } else if (v !== '' && v !== '0') {
            var num = parseFloat(v);
            if (!isNaN(num) && num >= 0 && String(num) !== v && v.indexOf('.') === -1) {
                posDiscountInputEl.value = num;
            }
        }
    }
    if (posDiscountInputEl) {
        posDiscountInputEl.addEventListener('input', function() { normalizeDiscountInput(); renderCart(); });
        posDiscountInputEl.addEventListener('change', function() { normalizeDiscountInput(); renderCart(); });
    }
    if (posDiscountTypeEl) {
        posDiscountTypeEl.addEventListener('change', function() { renderCart(); });
    }

    function applyCategoryFilter(catValue) {
        catValue = (catValue || '').toString();
        document.querySelectorAll('.pos-cat-pill').forEach(function(p) {
            var pCat = (p.getAttribute('data-category') || '').toString();
            p.classList.toggle('active', pCat === catValue);
        });
        document.querySelectorAll('.pos-product-item').forEach(function(el) {
            var elCat = (el.getAttribute('data-category-id') || '').toString();
            var show = (catValue === '' && true) || (elCat === catValue);
            el.style.display = show ? '' : 'none';
        });
        var sel = document.getElementById('posCategoryFilter');
        if (sel) sel.value = catValue;
        if (posSearch) posSearch.dispatchEvent(new Event('input'));
    }
    document.querySelectorAll('.pos-cat-pill').forEach(function(pill) {
        pill.addEventListener('click', function() {
            var cat = (this.getAttribute('data-category') || '').toString();
            applyCategoryFilter(cat);
        });
    });
    var posCategoryFilterEl = document.getElementById('posCategoryFilter');
    if (posCategoryFilterEl) {
        posCategoryFilterEl.addEventListener('change', function() {
            applyCategoryFilter(this.value || '');
        });
    }

    if (posSearch) {
        posSearch.addEventListener('input', function() {
            var q = (this.value || '').trim().toLowerCase();
            var activePill = document.querySelector('.pos-cat-pill.active');
            var activeCat = activePill ? (activePill.getAttribute('data-category') || '') : '';
            document.querySelectorAll('.pos-product-item').forEach(function(el) {
                var name = (el.getAttribute('data-name') || '');
                var barcode = (el.getAttribute('data-barcode') || '');
                var catMatch = activeCat === '' || (el.getAttribute('data-category-id') || '').toString() === activeCat;
                var searchMatch = !q || name.indexOf(q) >= 0 || barcode.indexOf(q) >= 0;
                el.style.display = catMatch && searchMatch ? '' : 'none';
            });
        });
    }

    if (posBarcode) {
        posBarcode.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var code = (this.value || '').trim();
                if (!code) return;
                var card = null;
                var codeLower = code.toLowerCase();
                document.querySelectorAll('.pos-product-card-premium').forEach(function(c) {
                    var b = (c.getAttribute('data-barcode') || '').trim().toLowerCase();
                    if (b && b === codeLower) card = c;
                });
                if (card) {
                    addToCart(card.getAttribute('data-product-id'), card.getAttribute('data-name'), card.getAttribute('data-price'), 1, card.getAttribute('data-stock'));
                    this.value = '';
                }
            }
        });
        setTimeout(function() { if (posBarcode && !document.querySelector('#posPaymentModal.show')) posBarcode.focus(); }, 500);
    }

    if (btnClearCart) btnClearCart.addEventListener('click', clearCart);

    var paymentTypeInput = document.createElement('input');
    paymentTypeInput.type = 'hidden';
    paymentTypeInput.name = 'payment_type';
    paymentTypeInput.id = 'posPaymentTypeInput';
    if (form) form.appendChild(paymentTypeInput);

    var paymentSplitsInput = document.createElement('input');
    paymentSplitsInput.type = 'hidden';
    paymentSplitsInput.name = 'payment_splits';
    paymentSplitsInput.id = 'posPaymentSplitsInput';
    if (form) form.appendChild(paymentSplitsInput);

    if (btnSotuv) {
        btnSotuv.addEventListener('click', function() {
            if (cart.length === 0) return;
            var partnerSelect = document.getElementById('posPartnerSelect');
            var dueWrap = document.getElementById('posPaymentDueDateWrap');
            var defaultId = dueWrap ? String((dueWrap.getAttribute('data-default-partner-id') || '').trim()) : '';
            var sel = partnerSelect ? String((partnerSelect.value || '').trim()) : '';
            if (sel && defaultId && sel !== defaultId) {
                /* Boshqa kontragent — qarzga, to'lov turi modali kerak emas */
                doPayment('naqd');
                return;
            }
            var modal = bootstrap.Modal.getOrCreateInstance(paymentModal);
            modal.show();
        });
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'F2' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            if (cart.length > 0 && btnSotuv && !btnSotuv.disabled) btnSotuv.click();
        }
    });

    var posSubmitInFlight = false;
    function disableSubmitButtons() {
        if (btnSotuv) { btnSotuv.disabled = true; btnSotuv.style.opacity = '0.6'; btnSotuv.style.cursor = 'wait'; }
        var splitOk = document.getElementById('posSplitConfirm');
        if (splitOk) splitOk.disabled = true;
    }
    function doPayment(payment) {
        if (posSubmitInFlight) return;
        posSubmitInFlight = true;
        disableSubmitButtons();
        if (paymentTypeInput) paymentTypeInput.value = payment;
        if (paymentSplitsInput) paymentSplitsInput.value = '';
        try { sessionStorage.removeItem(POS_CART_KEY); } catch (e) {}
        form.submit();
    }

    function parseMoneyText(text) {
        if (!text) return 0;
        var s = String(text).replace(/\s+/g, '').replace(/,/g, '');
        s = s.replace(/[^\d.\-]/g, '');
        var v = parseFloat(s);
        return isNaN(v) ? 0 : v;
    }
    function getTotalFinal() {
        var el = document.getElementById('posCartTotalFinal');
        return parseMoneyText(el ? el.textContent : '0');
    }

    var splitPanel = document.getElementById('posSplitPanel');
    var splitTotalEl = document.getElementById('posSplitTotal');
    var splitSumEl = document.getElementById('posSplitSum');
    var splitRemainEl = document.getElementById('posSplitRemain');
    var splitConfirm = document.getElementById('posSplitConfirm');
    var splitInputs = [
        { key: 'naqd', el: document.getElementById('posSplitNaqd') },
        { key: 'plastik', el: document.getElementById('posSplitPlastik') },
        { key: 'click', el: document.getElementById('posSplitClick') },
        { key: 'terminal', el: document.getElementById('posSplitTerminal') },
    ];
    function normalizeAmtInput(inp) {
        if (!inp) return 0;
        var v = parseFloat(inp.value || '0');
        if (isNaN(v) || v < 0) v = 0;
        inp.value = v;
        return v;
    }
    function updateSplitSummary() {
        if (!splitTotalEl || !splitSumEl || !splitRemainEl) return;
        var total = getTotalFinal();
        var sum = 0;
        splitInputs.forEach(function(x) { sum += normalizeAmtInput(x.el); });
        var remain = total - sum;
        splitTotalEl.textContent = total.toLocaleString('ru-RU');
        splitSumEl.textContent = sum.toLocaleString('ru-RU');
        splitRemainEl.textContent = remain.toLocaleString('ru-RU');
        var ok = Math.abs(remain) < 0.01 && total > 0;
        if (splitConfirm) splitConfirm.disabled = !ok;
    }
    if (splitInputs) {
        splitInputs.forEach(function(x) {
            if (x.el) {
                x.el.addEventListener('input', updateSplitSummary);
                x.el.addEventListener('change', updateSplitSummary);
            }
        });
    }
    if (paymentModal) {
        paymentModal.addEventListener('show.bs.modal', function() {
            if (splitPanel) splitPanel.style.display = '';
            splitInputs.forEach(function(x) { if (x.el) x.el.value = '0'; });
            updateSplitSummary();
        });
    }
    if (splitConfirm) {
        splitConfirm.addEventListener('click', function() {
            if (posSubmitInFlight) return;
            var total = getTotalFinal();
            var parts = [];
            var sum = 0;
            splitInputs.forEach(function(x) {
                var amt = normalizeAmtInput(x.el);
                if (amt > 0) {
                    parts.push({ type: x.key, amount: amt });
                    sum += amt;
                }
            });
            if (!parts.length) { alert('Hech bolmaganda bitta summa kiriting.'); return; }
            if (Math.abs(total - sum) >= 0.01) { alert('Kiritilgan summalar jami bilan teng bolishi kerak.'); return; }
            posSubmitInFlight = true;
            disableSubmitButtons();
            if (paymentTypeInput) paymentTypeInput.value = 'split';
            if (paymentSplitsInput) paymentSplitsInput.value = JSON.stringify(parts);
            try { sessionStorage.removeItem(POS_CART_KEY); } catch (e) {}
            form.submit();
        });
    }

    /* Split inputlarda Enter bosilsa form yuborilmasin */
    splitInputs.forEach(function(x) {
        if (!x.el) return;
        x.el.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); }
        });
    });

    /* Qoldiq summani tez to'ldirish ( + tugma ) */
    document.querySelectorAll('.pos-split-fill').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var targetId = this.getAttribute('data-target');
            var inp = targetId ? document.getElementById(targetId) : null;
            if (!inp) return;
            var total = getTotalFinal();
            var sum = 0;
            splitInputs.forEach(function(x) { sum += normalizeAmtInput(x.el); });
            var remain = total - sum;
            if (remain < 0) remain = 0;
            inp.value = (normalizeAmtInput(inp) + remain);
            updateSplitSummary();
            try { inp.focus(); inp.select && inp.select(); } catch (e) {}
        });
    });

    document.querySelectorAll('.pos-payment-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var p = this.getAttribute('data-payment');
            if (p) doPayment(p);
        });
    });

    if (paymentModal) {
        paymentModal.addEventListener('keydown', function(e) {
            var t = e && e.target;
            var tag = t && t.tagName ? String(t.tagName).toLowerCase() : '';
            if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) {
                return; /* input ichida raqam yozganda hotkey ishlamasin */
            }
            if (e.key === '1') { e.preventDefault(); doPayment('naqd'); }
            if (e.key === '2') { e.preventDefault(); doPayment('plastik'); }
            if (e.key === '3') { e.preventDefault(); doPayment('click'); }
            if (e.key === '4') { e.preventDefault(); doPayment('terminal'); }
        });
    }

    /* 1024x768: qo'shimcha tugmalarni ochib-yopish */
    var moreActionsBtn = document.getElementById('posMoreActionsBtn');
    var extraActions = document.querySelector('.pos-extra-actions');
    if (moreActionsBtn && extraActions) {
        moreActionsBtn.addEventListener('click', function() {
            extraActions.classList.toggle('is-open');
        });
    }

    var todayModal = document.getElementById('posTodaySalesModal');
    var dailyDateFrom = document.getElementById('posDailyDateFrom');
    var dailyDateTo = document.getElementById('posDailyDateTo');
    var dailyOrdersBody = document.getElementById('posDailyOrdersBody');
    var dailyBtnShow = document.getElementById('posDailyBtnShow');

    function todayStr() {
        var d = new Date();
        var y = d.getFullYear(), m = ('0' + (d.getMonth() + 1)).slice(-2), day = ('0' + d.getDate()).slice(-2);
        return y + '-' + m + '-' + day;
    }
    var posDailyOrderType = 'sale';
    function loadDailyOrders() {
        if (!dailyOrdersBody) return;
        var from = (dailyDateFrom && dailyDateFrom.value) || todayStr();
        var to = (dailyDateTo && dailyDateTo.value) || todayStr();
        var type = posDailyOrderType || 'sale';
        dailyOrdersBody.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-muted">Yuklanmoqda...</td></tr>';
        var url = '/sales/pos/daily-orders?date_from=' + encodeURIComponent(from) + '&date_to=' + encodeURIComponent(to) + '&order_type=' + encodeURIComponent(type);
        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(orders) {
                var emptyMsg = type === 'return_sale' ? 'Tanlangan sanalarda qaytarishlar yo\'q.' : 'Tanlangan sanalarda sotuvlar yo\'q.';
                if (!orders || orders.length === 0) {
                    dailyOrdersBody.innerHTML = '<tr><td colspan="8" class="text-muted text-center py-4">' + emptyMsg + '</td></tr>';
                    return;
                }
                var html = '';
                orders.forEach(function(o, i) {
                    var totalStr = (o.total || 0).toLocaleString('ru-RU');
                    var linkUrl = (o.type === 'return_sale') ? '/sales/returns' : '/sales/edit/' + o.id;
                    var linkText = (o.type === 'return_sale') ? 'Ro\'yxat' : 'Ochish';
                    var pt = (o.payment_type || 'naqd').toLowerCase();
                    var ptLabel;
                    if (pt === 'plastik') ptLabel = '<span class="badge bg-info">Plastik</span>';
                    else if (pt === 'click') ptLabel = '<span class="badge" style="background:#0066ff;color:#fff;">Click</span>';
                    else if (pt === 'terminal') ptLabel = '<span class="badge bg-secondary">Terminal</span>';
                    else if (pt === 'split') ptLabel = '<span class="badge bg-dark">Aralash</span>';
                    else if (pt === 'perechisleniye' || pt === 'bank') ptLabel = '<span class="badge bg-warning text-dark">Bank</span>';
                    else ptLabel = '<span class="badge bg-success">Naqd</span>';
                    html += '<tr><td>' + (i + 1) + '</td><td>' + (o.number || '') + '</td><td>' + (o.created_at || '-') + '</td><td>' + (o.partner_name || '-') + '</td><td>' + (o.warehouse_name || '-') + '</td><td>' + ptLabel + '</td><td class="text-end fw-bold">' + totalStr + ' so\'m</td><td><a href="' + linkUrl + '" class="btn btn-sm btn-outline-primary" target="_blank">' + linkText + '</a></td></tr>';
                });
                dailyOrdersBody.innerHTML = html;
            })
            .catch(function() {
                dailyOrdersBody.innerHTML = '<tr><td colspan="8" class="text-danger text-center py-4">Yuklashda xato.</td></tr>';
            });
    }
    document.querySelectorAll('.pos-daily-tab').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.pos-daily-tab').forEach(function(b) { b.classList.remove('active'); });
            this.classList.add('active');
            posDailyOrderType = this.getAttribute('data-type') || 'sale';
            loadDailyOrders();
        });
    });
    if (todayModal) {
        todayModal.addEventListener('show.bs.modal', function() {
            var t = todayStr();
            if (dailyDateFrom) dailyDateFrom.value = t;
            if (dailyDateTo) dailyDateTo.value = t;
            loadDailyOrders();
        });
    }
    if (document.getElementById('posBtnKunlikSotuv') && todayModal) {
        document.getElementById('posBtnKunlikSotuv').addEventListener('click', function() {
            var t = todayStr();
            if (dailyDateFrom) dailyDateFrom.value = t;
            if (dailyDateTo) dailyDateTo.value = t;
            var modal = bootstrap.Modal.getOrCreateInstance(todayModal);
            modal.show();
        });
    }
    if (dailyBtnShow) dailyBtnShow.addEventListener('click', loadDailyOrders);

    /* X hisobot — smena yakuni */
    var xReportBtn = document.getElementById('posBtnXHisobot');
    var xReportModal = document.getElementById('posXReportModal');
    var xReportBody = document.getElementById('posXReportBody');
    var xReportDateInput = document.getElementById('posXReportDate');
    var xReportReloadBtn = document.getElementById('posXReportReload');
    function _xrFmt(n) { try { return Math.round(n).toLocaleString('ru-RU') + ' so\'m'; } catch(e) { return String(n); } }
    function _xrRow(label, value, bold) {
        var div = document.createElement('div');
        div.className = 'd-flex justify-content-between border-bottom py-2';
        var l = document.createElement('span'); l.textContent = label;
        var v = document.createElement('span'); v.textContent = value;
        if (bold) v.className = 'fw-bold';
        div.appendChild(l); div.appendChild(v);
        return div;
    }
    function _xrSection(title) {
        var h = document.createElement('div');
        h.className = 'mt-3 mb-2 fw-bold text-muted small';
        h.textContent = title;
        return h;
    }
    function _xrTd(text, cls) {
        var td = document.createElement('td');
        td.textContent = text;
        if (cls) td.className = cls;
        return td;
    }
    function loadXReport() {
        if (!xReportBody) return;
        xReportBody.textContent = '';
        var loading = document.createElement('div');
        loading.className = 'text-center py-5 text-muted';
        loading.textContent = 'Yuklanmoqda...';
        xReportBody.appendChild(loading);
        var dateParam = (xReportDateInput && xReportDateInput.value) ? ('?date=' + encodeURIComponent(xReportDateInput.value)) : '';
        fetch('/sales/pos/x-report' + dateParam, {credentials: 'same-origin'})
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (!d || d.error) {
                    xReportBody.textContent = '';
                    var err = document.createElement('div');
                    err.className = 'alert alert-danger';
                    err.textContent = (d && d.error) || 'Xato';
                    xReportBody.appendChild(err);
                    return;
                }
                xReportBody.textContent = '';
                if (xReportDateInput && d.date_iso && !xReportDateInput.value) xReportDateInput.value = d.date_iso;
                var ptLabel = {
                    naqd: 'Naqd', plastik: 'Plastik', click: 'Click',
                    terminal: 'Terminal', split: 'Aralash',
                    perechisleniye: 'Bank', bank: 'Bank',
                    qarz: 'Qarzga'
                };
                var hdr = document.createElement('div');
                hdr.className = 'mb-3 pb-2 border-bottom';
                var t1 = document.createElement('div');
                t1.className = 'fw-bold';
                t1.textContent = d.user + ' — ' + d.warehouse;
                var t2 = document.createElement('small');
                t2.className = 'text-muted';
                t2.textContent = 'Sana: ' + d.date;
                hdr.appendChild(t1); hdr.appendChild(t2);
                xReportBody.appendChild(hdr);

                xReportBody.appendChild(_xrRow('Sotuvlar soni:', d.sales_count));
                xReportBody.appendChild(_xrRow('Sotuvlar summasi:', _xrFmt(d.sales_total), true));

                // OLDINGI KUNLARDAN HALI KELMAGAN PUL — sotuvchi shu pulni bugun olib kelishi kerak
                if (d.pending_prev_days && d.pending_prev_days.length) {
                    var pendSec = _xrSection('⚠ OLDINGI KUNLARDAN HALI KELMAGAN PUL:');
                    pendSec.style.color = '#b45309';
                    xReportBody.appendChild(pendSec);
                    var totalPending = 0;
                    d.pending_prev_days.forEach(function(p) {
                        var sign = (p.diff_sales_total >= 0) ? '+' : '';
                        var row = _xrRow(
                            p.date_display + ' (' + p.first_z_id + '):',
                            sign + p.diff_sales_count + ' ta · ' + sign + _xrFmt(p.diff_sales_total),
                            true
                        );
                        row.style.background = '#fef3c7';
                        row.style.color = '#92400e';
                        xReportBody.appendChild(row);
                        totalPending += (p.diff_sales_total || 0);
                    });
                    if (d.pending_prev_days.length > 1) {
                        var sumRow = _xrRow('Jami kelmagan:', _xrFmt(totalPending), true);
                        sumRow.style.background = '#fde68a';
                        sumRow.style.color = '#78350f';
                        xReportBody.appendChild(sumRow);
                    }
                }
                // Oldingi Z bo'lsa — birinchi yopilish vs hozirgi farqi
                if (d.last_z && (d.diff_sales_count || d.diff_sales_total)) {
                    var lz = d.last_z;
                    var prevTime = (lz.closed_at || '').slice(11, 19);
                    var prevDate = (lz.closed_at || '').slice(0, 10);
                    var sec = _xrSection('BIRINCHI Z-HISOBOT (' + prevDate + ' ' + prevTime + '):');
                    xReportBody.appendChild(sec);
                    var prevRow = _xrRow(
                        'Birinchi yopilish (' + lz.z_id + '):',
                        lz.sales_count + ' ta · ' + _xrFmt(lz.sales_total)
                    );
                    prevRow.style.color = '#6b7280';
                    xReportBody.appendChild(prevRow);
                    var sign = (d.diff_sales_total >= 0) ? '+' : '';
                    var diffRow = _xrRow(
                        'Keyin qo\'shildi (majburiy yopilish):',
                        sign + (d.diff_sales_count || 0) + ' ta · ' + sign + _xrFmt(d.diff_sales_total || 0),
                        true
                    );
                    diffRow.style.background = '#fffbeb';
                    diffRow.style.color = '#92400e';
                    xReportBody.appendChild(diffRow);
                    if (lz.total_closes && lz.total_closes > 2) {
                        var info = document.createElement('div');
                        info.className = 'small text-muted mt-1';
                        info.textContent = '(' + lz.total_closes + ' marta yopilgan)';
                        xReportBody.appendChild(info);
                    }
                }
                if (d.returns_count > 0) {
                    xReportBody.appendChild(_xrRow('Qaytarishlar soni:', d.returns_count));
                    xReportBody.appendChild(_xrRow('Qaytarishlar summasi:', '−' + _xrFmt(d.returns_total)));
                    var net = _xrRow('NET (sotuv − qaytarish):', _xrFmt(d.net_total), true);
                    net.style.background = '#f0f9f4';
                    xReportBody.appendChild(net);
                }
                if (d.cancelled_count > 0) {
                    var c = _xrRow('Bekor qilingan:', d.cancelled_count + ' ta — ' + _xrFmt(d.cancelled_total));
                    c.style.color = '#b44';
                    xReportBody.appendChild(c);
                }

                if (d.payment_breakdown && d.payment_breakdown.length) {
                    xReportBody.appendChild(_xrSection('TO\'LOV TURI BO\'YICHA:'));
                    d.payment_breakdown.forEach(function(p) {
                        var name = ptLabel[p.type] || p.type;
                        xReportBody.appendChild(_xrRow(name + ' (' + p.count + ' ta):', _xrFmt(p.sum)));
                    });
                }

                var hasExpense = (d.expense_to_partner && d.expense_to_partner.count > 0)
                              || (d.expense_other && d.expense_other.count > 0);
                if (hasExpense || typeof d.qoldiq !== 'undefined') {
                    xReportBody.appendChild(_xrSection('HARAJATLAR (NAQD KASSADAN):'));
                    if (d.expense_to_partner && d.expense_to_partner.count > 0) {
                        xReportBody.appendChild(_xrRow(
                            'Kontragentga to\'lov (' + d.expense_to_partner.count + ' ta):',
                            '−' + _xrFmt(d.expense_to_partner.sum)
                        ));
                    }
                    if (d.expense_other && d.expense_other.count > 0) {
                        xReportBody.appendChild(_xrRow(
                            'Boshqa harajatlar (' + d.expense_other.count + ' ta):',
                            '−' + _xrFmt(d.expense_other.sum)
                        ));
                    }
                    if (d.inkasatsiya_naqd_today && d.inkasatsiya_naqd_today.count > 0) {
                        xReportBody.appendChild(_xrRow(
                            'Inkasatsiya naqd (' + d.inkasatsiya_naqd_today.count + ' ta):',
                            '−' + _xrFmt(d.inkasatsiya_naqd_today.sum)
                        ));
                    }
                    if (typeof d.qoldiq !== 'undefined') {
                        var qRow = _xrRow('NAQD QOLDIQ (kassada bo\'lishi kerak):', _xrFmt(d.qoldiq), true);
                        qRow.style.background = '#e3f2fd';
                        qRow.style.fontSize = '1.05em';
                        xReportBody.appendChild(qRow);
                    }
                    if (d.expense_non_cash && d.expense_non_cash.length) {
                        d.expense_non_cash.forEach(function(e) {
                            var name = (ptLabel[e.type] || e.type);
                            var r = _xrRow(name + ' kassadan harajat (' + e.count + ' ta):', '−' + _xrFmt(e.sum));
                            r.style.color = '#666';
                            xReportBody.appendChild(r);
                        });
                    }
                }

                if (d.cash_balances && d.cash_balances.length) {
                    xReportBody.appendChild(_xrSection('KASSA BALANSI (joriy):'));
                    d.cash_balances.forEach(function(c) {
                        xReportBody.appendChild(_xrRow(c.name + ':', _xrFmt(c.balance)));
                    });
                }

                if (d.inkasatsiya_today && d.inkasatsiya_today.count > 0) {
                    xReportBody.appendChild(_xrSection('INKASATSIYA (bugun topshirilgan):'));
                    xReportBody.appendChild(_xrRow(
                        'O\'tkazmalar (' + d.inkasatsiya_today.count + ' ta):',
                        _xrFmt(d.inkasatsiya_today.sum)
                    ));
                }

                if (d.by_user && d.by_user.length) {
                    xReportBody.appendChild(_xrSection('SOTUVCHILAR BO\'YICHA:'));
                    var tbl = document.createElement('table');
                    tbl.className = 'table table-sm mb-0';
                    var thead = document.createElement('thead');
                    var thr = document.createElement('tr');
                    ['Sotuvchi','Soni','Sotuv','Qaytarish','NET'].forEach(function(h, i) {
                        var th = document.createElement('th');
                        th.textContent = h;
                        if (i > 0) th.className = 'text-end';
                        thr.appendChild(th);
                    });
                    thead.appendChild(thr);
                    tbl.appendChild(thead);
                    var tb = document.createElement('tbody');
                    d.by_user.forEach(function(u) {
                        var tr = document.createElement('tr');
                        tr.appendChild(_xrTd(u.user || '-'));
                        tr.appendChild(_xrTd(String(u.count), 'text-end'));
                        tr.appendChild(_xrTd(_xrFmt(u.sum), 'text-end'));
                        tr.appendChild(_xrTd(u.returns ? '−' + _xrFmt(u.returns) : '0', 'text-end'));
                        tr.appendChild(_xrTd(_xrFmt(u.net), 'text-end fw-bold'));
                        tb.appendChild(tr);
                    });
                    tbl.appendChild(tb);
                    xReportBody.appendChild(tbl);
                }
            })
            .catch(function() {
                xReportBody.textContent = '';
                var err = document.createElement('div');
                err.className = 'alert alert-danger';
                err.textContent = 'Tarmoq xatosi';
                xReportBody.appendChild(err);
            });
    }
    if (xReportBtn && xReportModal) {
        xReportBtn.addEventListener('click', function() {
            var modal = bootstrap.Modal.getOrCreateInstance(xReportModal);
            modal.show();
            if (xReportDateInput && !xReportDateInput.value) {
                var t = new Date();
                xReportDateInput.value = t.getFullYear() + '-' + String(t.getMonth()+1).padStart(2,'0') + '-' + String(t.getDate()).padStart(2,'0');
            }
            loadXReport();
        });
    }
    if (xReportReloadBtn) xReportReloadBtn.addEventListener('click', loadXReport);
    if (xReportDateInput) xReportDateInput.addEventListener('change', loadXReport);
    var xReportPrintBtn = document.getElementById('posXReportPrintBtn');
    if (xReportPrintBtn) {
        xReportPrintBtn.addEventListener('click', function() {
            var d = document.getElementById('posXReportDate');
            var dateParam = (d && d.value) ? ('?date=' + encodeURIComponent(d.value)) : '';
            window.open('/sales/pos/x-report/receipt' + dateParam, '_blank');
        });
    }
    var xReportZBtn = document.getElementById('posXReportZBtn');
    if (xReportZBtn) {
        function fmtNum(n) {
            try { return new Intl.NumberFormat('ru-RU').format(Math.round(Number(n) || 0)); }
            catch (e) { return String(n); }
        }
        function submitZReport(dateParam) {
            xReportZBtn.disabled = true;
            var csrfTokenZ = (document.querySelector('meta[name="csrf-token"]') || {}).getAttribute('content') || '';
            var zHeaders = {'Content-Type': 'application/json', 'Accept': 'application/json'};
            if (csrfTokenZ) zHeaders['X-CSRF-Token'] = csrfTokenZ;
            fetch('/sales/pos/z-report', {
                method: 'POST',
                credentials: 'same-origin',
                headers: zHeaders,
                body: JSON.stringify({date: dateParam})
            })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    xReportZBtn.disabled = false;
                    if (d && d.ok) {
                        if (d.snapshot_id) {
                            try { window.open('/reports/z-reports/' + encodeURIComponent(d.snapshot_id) + '?fmt=receipt', '_blank'); }
                            catch (e) { /* popup blocked */ }
                        } else {
                            alert('Z-hisobot saqlandi, lekin snapshot_id qaytmadi.');
                        }
                    } else {
                        alert('Xato: ' + (d && d.error ? d.error : 'noma\'lum'));
                    }
                })
                .catch(function() {
                    xReportZBtn.disabled = false;
                    alert('Tarmoq xatosi');
                });
        }
        xReportZBtn.addEventListener('click', function() {
            var dateParam = (xReportDateInput && xReportDateInput.value) ? xReportDateInput.value : '';
            xReportZBtn.disabled = true;
            var checkUrl = '/sales/pos/z-report/check' + (dateParam ? ('?date=' + encodeURIComponent(dateParam)) : '');
            fetch(checkUrl, { credentials: 'same-origin', headers: {'Accept': 'application/json'} })
                .then(function(r) { return r.json().catch(function() { return {ok: false}; }); })
                .then(function(c) {
                    xReportZBtn.disabled = false;
                    if (c && c.ok && c.exists && c.last) {
                        var t = (c.last.closed_at || '').slice(0, 19).replace('T', ' ');
                        var msg = 'DIQQAT: Ushbu sana uchun smena allaqachon yopilgan!\n\n' +
                                  '  • Vaqt: ' + t + '\n' +
                                  '  • Sotuv: ' + fmtNum(c.last.sales_total) + " so'm (" + (c.last.sales_count || 0) + ' ta)\n' +
                                  '  • Z-ID: ' + (c.last.z_id || '—') + '\n\n' +
                                  'Yana bir marta yopsangiz, dublikat yozuv yaratiladi (jami hisobga kirmaydi, lekin tarixda qoladi).\n\n' +
                                  'Davom etasizmi?';
                        if (!confirm(msg)) return;
                    } else {
                        if (!confirm('Smenani yopasizmi? Z-hisobot tarixga saqlanadi va keyin o\'zgartirib bo\'lmaydi.')) return;
                    }
                    submitZReport(dateParam);
                })
                .catch(function() {
                    xReportZBtn.disabled = false;
                    if (!confirm('Smenani yopasizmi? Z-hisobot tarixga saqlanadi va keyin o\'zgartirib bo\'lmaydi.')) return;
                    submitZReport(dateParam);
                });
        });
    }

    /* Inkasatsiya — kutilayotgan o'tkazmalar */
    if (document.getElementById('posBtnKassaniTasdiqlash')) {
        document.getElementById('posBtnKassaniTasdiqlash').addEventListener('click', function() {
            var modal = new bootstrap.Modal(document.getElementById('posInkasatsiyaModal'));
            loadInkasatsiya();
            modal.show();
        });
    }
    function loadInkasatsiya() {
        var tbody = document.getElementById('posInkasatsiyaBody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-muted">Yuklanmoqda...</td></tr>';
        fetch('/cash/transfers/my-pending', { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.length) {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted"><i class="bi bi-check-circle d-block mb-2" style="font-size:2rem;opacity:0.3;"></i>Kutilayotgan inkasatsiya yo\'q</td></tr>';
                    return;
                }
                tbody.innerHTML = '';
                data.forEach(function(t) {
                    var tr = document.createElement('tr');
                    var escapedNum = (t.number || '').replace(/'/g, "\\'");
                    var escapedFrom = (t.from_cash || '').replace(/'/g, "\\'");
                    var escapedTo = (t.to_cash || '').replace(/'/g, "\\'");
                    var isReceiver = (t.role === 'receiver');
                    var isDone = (t.role === 'done');
                    var isPending = (t.status === 'pending');
                    var canAct = !isDone && (isReceiver ? !isPending : true);
                    var statusBadge;
                    if (isDone) {
                        statusBadge = '<span class="badge bg-success">Tasdiqlangan</span>';
                    } else if (!canAct) {
                        statusBadge = '<span class="badge bg-info text-dark">Sender tasdiqlashi kerak</span>';
                    } else if (isReceiver) {
                        statusBadge = '<span class="badge bg-warning text-dark">Yolda — qabul kutilmoqda</span>';
                    } else {
                        statusBadge = '<span class="badge bg-secondary">Yuborish kerak</span>';
                    }
                    var btnText = isReceiver ? 'Qabul qilish' : 'Yuborish';
                    var btnColor = isReceiver ? '#1565c0' : '#0d6b4b';
                    var btnIcon = isReceiver ? 'bi-box-arrow-in-down' : 'bi-send';
                    var action = isReceiver ? 'receiveInkasatsiya' : 'confirmInkasatsiya';
                    var btnDisabledAttr = canAct ? '' : ' disabled style="opacity:0.5;cursor:not-allowed;"';
                    var inkPart = t.inkasator ? '<div class="small"><i class="bi bi-person"></i> ' + t.inkasator + '</div>' : '';
                    var sentPart = t.sent_at ? '<div class="small text-muted">Yuborildi: ' + t.sent_at + (t.sent_by ? ' ('+t.sent_by+')' : '') + '</div>' : '';
                    var apprPart = t.approved_at ? '<div class="small text-success">Tasdiq: ' + t.approved_at + (t.approved_by ? ' ('+t.approved_by+')' : '') + '</div>' : '';
                    var infoHtml = inkPart + sentPart + apprPart;
                    tr.innerHTML = '<td><strong>' + t.number + '</strong><br><small class="text-muted">' + t.date + '</small><br>' + statusBadge + '</td>' +
                        '<td>' + t.from_cash + ' <i class="bi bi-arrow-right text-muted"></i> ' + t.to_cash + '</td>' +
                        '<td class="text-end fw-bold" style="color:' + btnColor + ';">' + (t.amount || 0).toLocaleString('ru-RU') + '</td>' +
                        '<td class="text-muted" style="font-size:0.8rem;">' + infoHtml + '</td>' +
                        (isDone
                            ? '<td class="text-center"><i class="bi bi-check2-circle text-success" style="font-size:1.4rem;"></i></td>'
                            : '<td><button class="btn btn-sm"' + btnDisabledAttr + ' style="background:' + btnColor + ';color:#fff;border-radius:10px;font-weight:600;font-size:0.8rem;" onclick="if(!this.disabled){' + action + '(' + t.id + ', this, ' + (t.amount||0) + ', \'' + escapedFrom + '\', \'' + escapedTo + '\', \'' + escapedNum + '\')}"><i class="bi ' + btnIcon + ' me-1"></i>' + btnText + '</button></td>');
                    tbody.appendChild(tr);
                });
            })
            .catch(function() {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-danger">Yuklashda xato</td></tr>';
            });
    }
    window.confirmInkasatsiya = function(id, btn, amount, fromCash, toCash, number) {
        var inkasatorSelect = document.getElementById('posInkasatorSelect');
        var inkasatorId = inkasatorSelect ? inkasatorSelect.value : '';
        var inkasatorName = inkasatorSelect && inkasatorSelect.selectedOptions[0] ? inkasatorSelect.selectedOptions[0].text : '';
        if (!inkasatorId) {
            alert('Inkasatorni tanlang!');
            if (inkasatorSelect) inkasatorSelect.focus();
            return;
        }
        if (!confirm('Pulni ' + inkasatorName + ' ga berdingizmi? Kassadan mablag ayriladi.')) return;
        btn.disabled = true;
        btn.innerHTML = '<i class="bi bi-hourglass-split"></i>';
        var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content ||
            (document.querySelector('input[name="csrf_token"]') || {}).value || '';
        var fd = new FormData();
        fd.append('csrf_token', csrfToken);
        fd.append('inkasator_id', inkasatorId);
        fetch('/cash/transfers/' + id + '/sotuvchi-confirm', { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function(r) {
                if (r.ok || r.status === 303) {
                    loadInkasatsiya();
                    // Chek ochish
                    var receiptUrl = '/cash/transfers/' + id + '/receipt';
                    window.open(receiptUrl, 'inkasatsiya_receipt', 'width=400,height=500,scrollbars=yes');
                } else {
                    alert('Xatolik yuz berdi');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Tasdiqlash';
                }
            })
            .catch(function() {
                alert('Tarmoq xatosi');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Tasdiqlash';
            });
    };
    /* Yangi yuborish (sotuvchi boshlaydi) */
    var posBtnNew = document.getElementById('posBtnNewTransfer');
    var posNewBox = document.getElementById('posNewTransferBox');
    if (posBtnNew && posNewBox) {
        posBtnNew.addEventListener('click', function() {
            posNewBox.style.display = (posNewBox.style.display === 'none') ? 'block' : 'none';
        });
        var cancelBtn = document.getElementById('posNewTrCancel');
        if (cancelBtn) cancelBtn.addEventListener('click', function() { posNewBox.style.display = 'none'; });
        var submitBtn = document.getElementById('posNewTrSubmit');
        if (submitBtn) {
            submitBtn.addEventListener('click', function() {
                var toCash = document.getElementById('posNewTrTo').value;
                var amount = parseFloat(document.getElementById('posNewTrAmount').value || 0);
                var ink = document.getElementById('posNewTrInk').value;
                var note = (document.getElementById('posNewTrNote').value || '').trim();
                if (!toCash) { alert('Qabul qiluvchi kassa tanlang'); return; }
                if (!amount || amount <= 0) { alert("Summa 0 dan katta bo'lishi kerak"); return; }
                if (!confirm(amount.toLocaleString('ru-RU') + " so'm yuborildimi?")) return;
                submitBtn.disabled = true;
                submitBtn.textContent = 'Yuborilmoqda...';
                var csrfToken = (document.querySelector('meta[name=\"csrf-token\"]') || {}).content ||
                    (document.querySelector('input[name=\"csrf_token\"]') || {}).value || '';
                var fd = new FormData();
                fd.append('csrf_token', csrfToken);
                fd.append('to_cash_id', toCash);
                fd.append('amount', amount);
                if (ink) fd.append('inkasator_id', ink);
                if (note) fd.append('note', note);
                fetch('/cash/transfers/sotuvchi-send', { method: 'POST', body: fd, credentials: 'same-origin' })
                    .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, data: j }; }); })
                    .then(function(res) {
                        submitBtn.disabled = false;
                        submitBtn.textContent = 'Yuborish';
                        if (res.ok && res.data.ok) {
                            alert('Yuborildi: ' + res.data.number);
                            document.getElementById('posNewTrAmount').value = '';
                            document.getElementById('posNewTrNote').value = '';
                            posNewBox.style.display = 'none';
                            loadInkasatsiya();
                        } else {
                            alert('Xato: ' + (res.data.error || 'nomalum'));
                        }
                    })
                    .catch(function() {
                        submitBtn.disabled = false;
                        submitBtn.textContent = 'Yuborish';
                        alert('Tarmoq xatosi');
                    });
            });
        }
    }

    /* Receiver: in_transit -> completed (qabul qilish) */
    window.receiveInkasatsiya = function(id, btn, amount, fromCash, toCash, number) {
        if (!confirm('Pulni qabul qildingizmi? ' + (amount||0).toLocaleString('ru-RU') + " so'm " + toCash + ' ga kiradi.')) return;
        btn.disabled = true;
        btn.innerHTML = '<i class="bi bi-hourglass-split"></i>';
        var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content ||
            (document.querySelector('input[name="csrf_token"]') || {}).value || '';
        var fd = new FormData();
        fd.append('csrf_token', csrfToken);
        fetch('/cash/transfers/' + id + '/admin-confirm', { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function(r) {
                if (r.ok || r.status === 303) {
                    loadInkasatsiya();
                } else {
                    alert('Xatolik (qabul qilish faqat admin/manager uchun — o\'z ombor huquqingiz bor bo\'lsa ham)');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-box-arrow-in-down me-1"></i>Qabul qilish';
                }
            })
            .catch(function() {
                alert('Tarmoq xatosi');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-box-arrow-in-down me-1"></i>Qabul qilish';
            });
    };
    /* Omborni tasdiqlash — ombordan omborga o'tkazish ro'yxati */
    if (document.getElementById('posBtnOmborniTasdiqlash')) {
        document.getElementById('posBtnOmborniTasdiqlash').addEventListener('click', function() {
            window.location.href = '/warehouse/transfers';
        });
    }

    /* Chekni saqlash — savatdagi tovarlarni vaqtinchalik saqlab qo'yish */
    if (document.getElementById('posBtnChekniSaqlash')) {
        document.getElementById('posBtnChekniSaqlash').addEventListener('click', function() {
            if (!cart || cart.length === 0) {
                alert('Savat bo\'sh. Avval mahsulot qo\'shing.');
                return;
            }
            var name = (prompt('Chek nomi (ixtiyoriy):', '') || '').trim() || null;
            var payload = { items: cart };
            if (name) payload.name = name;
            var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).getAttribute('content') || '';
            var headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
            if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
            fetch('/sales/pos/draft/save', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data && data.ok) {
                    alert('Chek saqlandi.');
                } else {
                    alert(data && data.error ? data.error : 'Saqlashda xato.');
                }
            })
            .catch(function() { alert('Tarmoq xatosi.'); });
        });
    }

    /* Chekni yuklash — saqlangan cheklar ro'yxatidan tanlash */
    var loadDraftModal = document.getElementById('posLoadDraftModal');
    var draftsListBody = document.getElementById('posDraftsListBody');
    var draftsEmpty = document.getElementById('posDraftsEmpty');
    function loadDraftsList() {
        if (!draftsListBody) return;
        draftsListBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-muted">Yuklanmoqda...</td></tr>';
        if (draftsEmpty) draftsEmpty.style.display = 'none';
        fetch('/sales/pos/drafts')
            .then(function(r) { return r.json(); })
            .then(function(list) {
                if (!list || list.length === 0) {
                    draftsListBody.innerHTML = '';
                    if (draftsEmpty) draftsEmpty.style.display = 'block';
                    return;
                }
                var html = '';
                list.forEach(function(d) {
                    var totalStr = (d.total || 0).toLocaleString('ru-RU');
                    html += '<tr class="pos-draft-row" data-draft-id="' + d.id + '">';
                    html += '<td>' + (d.created_at || '-') + '</td>';
                    html += '<td>' + (d.name || '-') + '</td>';
                    html += '<td>' + (d.item_count || 0) + ' ta</td>';
                    html += '<td class="text-end fw-bold">' + totalStr + ' so\'m</td>';
                    html += '<td><button type="button" class="btn btn-sm btn-success pos-draft-load-btn" data-draft-id="' + d.id + '"><i class="bi bi-download me-1"></i>Yuklash</button></td></tr>';
                });
                draftsListBody.innerHTML = html;
                draftsListBody.querySelectorAll('.pos-draft-load-btn').forEach(function(btn) {
                    btn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        var id = parseInt(this.getAttribute('data-draft-id'), 10);
                        if (!id) return;
                        fetch('/sales/pos/draft/' + id)
                            .then(function(r) { return r.json(); })
                            .then(function(res) {
                                if (res && res.ok && Array.isArray(res.items) && res.items.length) {
                                    cart = res.items.map(function(x) {
                                        return {
                                            productId: parseInt(x.productId, 10) || x.product_id,
                                            productName: x.productName || x.product_name || '',
                                            price: parseFloat(x.price) || 0,
                                            quantity: parseFloat(x.quantity) || 1,
                                        };
                                    });
                                    cart.forEach(function(item) {
                                        var maxQ = posStockByProduct[item.productId];
                                        if (maxQ !== undefined && !isNaN(maxQ) && item.quantity > maxQ) item.quantity = maxQ;
                                    });
                                    renderCart();
                                    var modal = bootstrap.Modal.getOrCreateInstance(loadDraftModal);
                                    modal.hide();
                                } else {
                                    alert('Chek ma\'lumotlari topilmadi.');
                                }
                            })
                            .catch(function() { alert('Yuklashda xato.'); });
                    });
                });
            })
            .catch(function() {
                draftsListBody.innerHTML = '<tr><td colspan="5" class="text-danger text-center py-4">Yuklashda xato.</td></tr>';
            });
    }
    if (document.getElementById('posBtnChekniYuklash') && loadDraftModal) {
        document.getElementById('posBtnChekniYuklash').addEventListener('click', function() {
            loadDraftsList();
            var modal = bootstrap.Modal.getOrCreateInstance(loadDraftModal);
            modal.show();
        });
    }
    if (loadDraftModal) {
        loadDraftModal.addEventListener('show.bs.modal', loadDraftsList);
    }

    restoreCartFromStorage();


    /* Xodim mahsulot xaridi modal — savatdagi mahsulotlarni xodimga yozish */
    var empProdBtn = document.getElementById('posBtnEmployeeProduct');
    var empProdModal = document.getElementById('posEmployeeProductModal');
    if (empProdBtn && empProdModal) {
        var empSelect = document.getElementById('posEmpProdSelect');
        var empProdEmpty = document.getElementById('posEmpProdEmpty');
        var empProdContent = document.getElementById('posEmpProdContent');
        var empProdItemsBody = document.getElementById('posEmpProdItems');
        var empProdTotal = document.getElementById('posEmpProdTotal');
        var empProdQuotaBox = document.getElementById('posEmpProdQuotaBox');
        var empProdQuotaFree = document.getElementById('posEmpProdQuotaFree');
        var empProdQuotaUsed = document.getElementById('posEmpProdQuotaUsed');
        var empProdQuotaRemain = document.getElementById('posEmpProdQuotaRemain');
        var empProdBreakdown = document.getElementById('posEmpProdBreakdown');
        var empProdFromQuota = document.getElementById('posEmpProdFromQuota');
        var empProdFromSalary = document.getElementById('posEmpProdFromSalary');
        var empProdSubmit = document.getElementById('posEmpProdSubmit');
        var empProdQuotaRemainNum = 0;
        var empProdTotalNum = 0;
        var empsLoaded = false;

        function empFmt(n) {
            try { return new Intl.NumberFormat('ru-RU').format(Math.round(Number(n) || 0)); }
            catch (e) { return String(n); }
        }

        function loadEmployees() {
            if (empsLoaded) return Promise.resolve();
            return fetch('/sales/pos/employees-active', { credentials: 'same-origin', headers: {'Accept': 'application/json'} })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (!d || !d.ok || !d.items) return;
                    while (empSelect.firstChild) empSelect.removeChild(empSelect.firstChild);
                    var ph = document.createElement('option');
                    ph.value = '';
                    ph.textContent = '— Xodim tanlang —';
                    empSelect.appendChild(ph);
                    var byDept = {};
                    d.items.forEach(function(e) {
                        var dept = e.department || "Bo'lim ko'rsatilmagan";
                        if (!byDept[dept]) byDept[dept] = [];
                        byDept[dept].push(e);
                    });
                    Object.keys(byDept).sort().forEach(function(dept) {
                        var g = document.createElement('optgroup');
                        g.label = dept;
                        byDept[dept].forEach(function(e) {
                            var opt = document.createElement('option');
                            opt.value = e.id;
                            opt.textContent = e.name + (e.position ? ' — ' + e.position : '');
                            g.appendChild(opt);
                        });
                        empSelect.appendChild(g);
                    });
                    empsLoaded = true;
                });
        }

        function renderItems() {
            while (empProdItemsBody.firstChild) empProdItemsBody.removeChild(empProdItemsBody.firstChild);
            empProdTotalNum = 0;
            if (!cart.length) {
                empProdEmpty.classList.remove('d-none');
                empProdContent.classList.add('d-none');
                empProdSubmit.disabled = true;
                return;
            }
            empProdEmpty.classList.add('d-none');
            empProdContent.classList.remove('d-none');
            cart.forEach(function(it) {
                var tr = document.createElement('tr');
                var c1 = document.createElement('td'); c1.textContent = it.productName || ('#' + it.productId);
                var c2 = document.createElement('td'); c2.className = 'text-end'; c2.textContent = it.quantity;
                var c3 = document.createElement('td'); c3.className = 'text-end'; c3.textContent = empFmt(it.price);
                var line = (it.price || 0) * (it.quantity || 0);
                var c4 = document.createElement('td'); c4.className = 'text-end fw-bold'; c4.textContent = empFmt(line) + " so'm";
                tr.appendChild(c1); tr.appendChild(c2); tr.appendChild(c3); tr.appendChild(c4);
                empProdItemsBody.appendChild(tr);
                empProdTotalNum += line;
            });
            empProdTotal.textContent = empFmt(empProdTotalNum) + " so'm";
            updateBreakdown();
        }

        function updateBreakdown() {
            if (!empSelect.value || !cart.length) {
                empProdBreakdown.classList.add('d-none');
                empProdSubmit.disabled = true;
                return;
            }
            var fromQuota = Math.min(empProdTotalNum, empProdQuotaRemainNum);
            var fromSalary = Math.max(0, empProdTotalNum - empProdQuotaRemainNum);
            empProdFromQuota.textContent = empFmt(fromQuota) + " so'm";
            empProdFromSalary.textContent = empFmt(fromSalary) + " so'm";
            empProdBreakdown.classList.remove('d-none');
            empProdSubmit.disabled = false;
        }

        function loadQuota(empId) {
            empProdQuotaBox.classList.add('d-none');
            empProdQuotaRemainNum = 0;
            if (!empId) {
                updateBreakdown();
                return;
            }
            fetch('/sales/pos/employee-quota?employee_id=' + encodeURIComponent(empId), { credentials: 'same-origin', headers: {'Accept': 'application/json'} })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (!d || !d.ok) return;
                    empProdQuotaFree.textContent = empFmt(d.free_quota) + " so'm";
                    empProdQuotaUsed.textContent = empFmt(d.used_this_month) + " so'm";
                    empProdQuotaRemain.textContent = empFmt(d.free_remaining) + " so'm";
                    empProdQuotaRemainNum = Number(d.free_remaining) || 0;
                    empProdQuotaBox.classList.remove('d-none');
                    updateBreakdown();
                });
        }

        empProdBtn.addEventListener('click', function() {
            loadEmployees();
            empSelect.value = '';
            empProdQuotaBox.classList.add('d-none');
            empProdBreakdown.classList.add('d-none');
            empProdSubmit.disabled = true;
            renderItems();
            var m = bootstrap.Modal.getOrCreateInstance(empProdModal);
            m.show();
        });

        empSelect.addEventListener('change', function() {
            loadQuota(empSelect.value);
        });

        empProdSubmit.addEventListener('click', function() {
            var empId = empSelect.value;
            if (!empId || !cart.length) return;
            var whId = (document.getElementById('posWarehouseId') || {}).value || '';
            if (!whId) {
                alert("Ombor aniqlanmadi. Sahifani yangilang.");
                return;
            }
            var empName = empSelect.options[empSelect.selectedIndex].textContent;
            var msg = empName + " uchun yozasizmi?\n\n" +
                      "  • Jami: " + empFmt(empProdTotalNum) + " so'm (" + cart.length + " ta tovar)\n" +
                      "  • Bepul kvotadan: " + empFmt(Math.min(empProdTotalNum, empProdQuotaRemainNum)) + " so'm\n" +
                      "  • Oylikdan ushlanadi: " + empFmt(Math.max(0, empProdTotalNum - empProdQuotaRemainNum)) + " so'm\n\n" +
                      "Stock kamayadi, kassaga pul kirim qilinmaydi.";
            if (!confirm(msg)) return;
            empProdSubmit.disabled = true;
            var origText = empProdSubmit.textContent;
            while (empProdSubmit.firstChild) empProdSubmit.removeChild(empProdSubmit.firstChild);
            var sp = document.createElement('span');
            sp.className = 'spinner-border spinner-border-sm me-1';
            empProdSubmit.appendChild(sp);
            empProdSubmit.appendChild(document.createTextNode(' Saqlanmoqda...'));

            var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).getAttribute('content') || '';
            var headers = {'Content-Type': 'application/json', 'Accept': 'application/json'};
            if (csrf) headers['X-CSRF-Token'] = csrf;
            var payload = {
                employee_id: parseInt(empId, 10),
                warehouse_id: parseInt(whId, 10),
                items: cart.map(function(c) {
                    return {product_id: c.productId, quantity: c.quantity, price: c.price};
                }),
            };
            fetch('/sales/pos/employee-product', {
                method: 'POST',
                credentials: 'same-origin',
                headers: headers,
                body: JSON.stringify(payload),
            })
                .then(function(r) { return r.json().catch(function() { return {ok: false}; }); })
                .then(function(d) {
                    if (d && d.ok) {
                        cart = [];
                        saveCartToStorage();
                        var m = bootstrap.Modal.getInstance(empProdModal);
                        if (m) m.hide();
                        window.location.href = '/sales/pos?success=1&number=' +
                            encodeURIComponent("Xodim: " + (d.employee_name || '') + " — " + empFmt(d.total) + " so'm");
                    } else {
                        empProdSubmit.disabled = false;
                        while (empProdSubmit.firstChild) empProdSubmit.removeChild(empProdSubmit.firstChild);
                        empProdSubmit.appendChild(document.createTextNode(origText));
                        alert("Xato: " + (d && d.error ? d.error : "noma'lum"));
                    }
                })
                .catch(function() {
                    empProdSubmit.disabled = false;
                    while (empProdSubmit.firstChild) empProdSubmit.removeChild(empProdSubmit.firstChild);
                    empProdSubmit.appendChild(document.createTextNode(origText));
                    alert("Tarmoq xatosi");
                });
        });
    }


    /* Mening operatsiyalarim modal — sotuvchining kunlik to'lov/harajatlari */
    var myOpsBtn = document.getElementById('posBtnMyOperations');
    var myOpsModal = document.getElementById('posMyOperationsModal');
    if (myOpsBtn && myOpsModal) {
        var myOpsDateInput = document.getElementById('posMyOpsDate');
        var myOpsTabPayments = document.getElementById('posMyOpsTabPayments');
        var myOpsTabExpenses = document.getElementById('posMyOpsTabExpenses');
        var myOpsPayCount = document.getElementById('posMyOpsPayCount');
        var myOpsExpCount = document.getElementById('posMyOpsExpCount');
        var myOpsTableBody = document.getElementById('posMyOpsTableBody');
        var myOpsTotal = document.getElementById('posMyOpsTotal');
        var myOpsColParty = document.getElementById('posMyOpsColParty');
        var myOpsActiveTab = 'payments';
        var myOpsData = { payments: [], expenses: [], totals: {} };

        function myOpsFmt(n) {
            try { return new Intl.NumberFormat('ru-RU').format(Math.round(Number(n) || 0)); }
            catch (e) { return String(n); }
        }
        function myOpsEmptyRow(text) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.colSpan = 6;
            td.className = 'text-center text-muted py-4';
            td.textContent = text;
            tr.appendChild(td);
            return tr;
        }
        function myOpsRow(rec) {
            var tr = document.createElement('tr');
            var cells = [
                {text: rec.time || '—', cls: 'text-muted small'},
                {text: rec.number || '—', cls: 'small font-monospace'},
                {text: myOpsActiveTab === 'payments' ? (rec.partner_name || '—') : (rec.description.split(' — ')[0] || '—')},
                {text: rec.description || '', cls: 'small text-muted'},
                {text: (rec.cash_name || '—') + (rec.payment_type && rec.payment_type !== 'naqd' ? ' (' + rec.payment_type + ')' : ''), cls: 'small'},
                {text: myOpsFmt(rec.amount) + " so'm", cls: 'text-end fw-bold ' + (myOpsActiveTab === 'payments' ? 'text-primary' : 'text-warning')},
            ];
            cells.forEach(function(c) {
                var td = document.createElement('td');
                if (c.cls) td.className = c.cls;
                td.textContent = c.text;
                tr.appendChild(td);
            });
            return tr;
        }
        function myOpsRender() {
            while (myOpsTableBody.firstChild) myOpsTableBody.removeChild(myOpsTableBody.firstChild);
            var list = myOpsActiveTab === 'payments' ? myOpsData.payments : myOpsData.expenses;
            var totalSum = myOpsActiveTab === 'payments' ? (myOpsData.totals.payments_sum || 0) : (myOpsData.totals.expenses_sum || 0);
            if (myOpsColParty) myOpsColParty.textContent = myOpsActiveTab === 'payments' ? 'Kontragent' : 'Harajat turi';
            if (!list.length) {
                myOpsTableBody.appendChild(myOpsEmptyRow(myOpsActiveTab === 'payments' ? "Tanlangan sanada to'lov qilmadingiz" : "Tanlangan sanada harajat qilmadingiz"));
            } else {
                list.forEach(function(rec) { myOpsTableBody.appendChild(myOpsRow(rec)); });
            }
            myOpsTotal.textContent = myOpsFmt(totalSum) + " so'm";
        }
        function myOpsLoad() {
            var d = myOpsDateInput.value;
            while (myOpsTableBody.firstChild) myOpsTableBody.removeChild(myOpsTableBody.firstChild);
            myOpsTableBody.appendChild(myOpsEmptyRow('Yuklanmoqda...'));
            myOpsPayCount.textContent = '0';
            myOpsExpCount.textContent = '0';
            myOpsTotal.textContent = "0 so'm";
            var url = '/sales/pos/my-operations' + (d ? ('?date=' + encodeURIComponent(d)) : '');
            fetch(url, { credentials: 'same-origin', headers: {'Accept': 'application/json'} })
                .then(function(r) { return r.json().catch(function() { return {ok: false}; }); })
                .then(function(data) {
                    if (!data || !data.ok) {
                        while (myOpsTableBody.firstChild) myOpsTableBody.removeChild(myOpsTableBody.firstChild);
                        myOpsTableBody.appendChild(myOpsEmptyRow('Xato: ' + (data && data.error ? data.error : "noma'lum")));
                        return;
                    }
                    myOpsData = data;
                    myOpsPayCount.textContent = (data.totals.payments_count || 0);
                    myOpsExpCount.textContent = (data.totals.expenses_count || 0);
                    myOpsRender();
                })
                .catch(function() {
                    while (myOpsTableBody.firstChild) myOpsTableBody.removeChild(myOpsTableBody.firstChild);
                    myOpsTableBody.appendChild(myOpsEmptyRow('Tarmoq xatosi'));
                });
        }
        function myOpsSetTab(tab) {
            myOpsActiveTab = tab;
            [myOpsTabPayments, myOpsTabExpenses].forEach(function(b) { b.classList.remove('active'); });
            if (tab === 'payments') myOpsTabPayments.classList.add('active');
            else myOpsTabExpenses.classList.add('active');
            myOpsRender();
        }
        myOpsBtn.addEventListener('click', function() {
            if (!myOpsDateInput.value) {
                var t = new Date();
                myOpsDateInput.value = t.getFullYear() + '-' + String(t.getMonth()+1).padStart(2,'0') + '-' + String(t.getDate()).padStart(2,'0');
            }
            myOpsSetTab('payments');
            var m = bootstrap.Modal.getOrCreateInstance(myOpsModal);
            m.show();
            myOpsLoad();
        });
        myOpsDateInput.addEventListener('change', myOpsLoad);
        myOpsTabPayments.addEventListener('click', function() { myOpsSetTab('payments'); });
        myOpsTabExpenses.addEventListener('click', function() { myOpsSetTab('expenses'); });
    }
})();
