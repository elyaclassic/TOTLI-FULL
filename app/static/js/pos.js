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
        var q = cart[index].quantity + delta;
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
                '<td class="align-middle"><div class="input-group input-group-sm" style="width:100px"><button type="button" class="btn btn-outline-secondary cart-minus" data-index="' + i + '">−</button><input type="number" class="form-control form-control-sm cart-qty text-center" data-index="' + i + '" value="' + item.quantity + '" step="0.01" min="0.01"><button type="button" class="btn btn-outline-secondary cart-plus" data-index="' + i + '">+</button></div></td>' +
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
            inp.addEventListener('change', function() {
                var i = parseInt(this.getAttribute('data-index'), 10);
                var q = parseFloat(this.value) || 0;
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

    function doPayment(payment) {
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
                    var ptLabel = pt === 'plastik' ? '<span class="badge bg-info">Plastik</span>' : pt === 'perechisleniye' ? '<span class="badge bg-warning text-dark">Bank</span>' : '<span class="badge bg-success">Naqd</span>';
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
})();
