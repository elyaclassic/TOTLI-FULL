// Driver Dashboard JavaScript

// Check if logged in
if (!Session.isLoggedIn()) {
    window.location.href = '/static/pwa/login.html';
}

// Agent bo'lsa agent dashboard ga yo'naltirish
const _user = Session.getUser();
if (_user && (_user.user_type || _user.role) === 'agent') {
    window.location.href = '/static/pwa/dashboard.html';
}

const user = Session.getUser();
const token = Session.getToken();

// Ensure we have driver data
if (!user || (!user.full_name && !user.driver)) {
    console.warn('Driver ma\'lumotlari topilmadi, session tekshirilsin');
}

const driverName = user?.full_name || user?.driver?.full_name || 'Haydovchi';

// Update sidebar
document.getElementById('sidebarDriverName').textContent = driverName;

// Main tab
function setMainTab(tab) {
    document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.main-tab:nth-child(${tab === 'visits' ? 1 : tab === 'completed' ? 2 : 3})`).classList.add('active');

    document.getElementById('visitsTabContent').style.display = tab === 'visits' ? 'block' : 'none';
    document.getElementById('completedTabContent').style.display = tab === 'completed' ? 'block' : 'none';
    document.getElementById('totalsTabContent').style.display = tab === 'totals' ? 'block' : 'none';
}

// Page navigation
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) {
        page.classList.add('active');
        if (pageId === 'tradePointsPage') loadTradePoints();
        if (pageId === 'debtorsPage') loadDebtors();
        if (pageId === 'paymentHistoryPage') loadPaymentHistory();
        if (pageId === 'orderHistoryPage') loadOrderHistory();
    }
}

function openSidebar() {
    document.getElementById('sidebar').classList.add('active');
    document.getElementById('sidebarOverlay').classList.add('active');
}

function closeSidebar() {
    document.getElementById('sidebar').classList.remove('active');
    document.getElementById('sidebarOverlay').classList.remove('active');
}

function logout() {
    if (confirm('Chiqishni xohlaysizmi?')) {
        Session.logout();
    }
}

async function doSync() {
    try {
        const btn = document.querySelector('.fab-sync i');
        if (btn) btn.classList.add('spin');
        await loadDriverData();
        if (btn) btn.classList.remove('spin');
    } catch (e) {
        console.error('Sinxronlash xatosi:', e);
    }
}

async function loadDriverData() {
    const token = Session.getToken();
    if (!token) return;

    try {
        const [partnersRes, visitsRes] = await Promise.all([
            fetch(`/api/driver/partners?token=${encodeURIComponent(token)}`).catch(() => ({ ok: false })),
            fetch(`/api/driver/visits?token=${encodeURIComponent(token)}`).catch(() => ({ ok: false }))
        ]);

        const partnersData = partnersRes.ok ? await partnersRes.json() : { partners: [] };
        const visitsData = visitsRes.ok ? await visitsRes.json() : { visits: [], completed: 0 };

        const partners = partnersData.partners || partnersData.data || [];
        const visits = visitsData.visits || visitsData.data || [];
        const completed = visitsData.completed || 0;

        document.getElementById('visitsCount').textContent = visits.length;
        document.getElementById('completedCount').textContent = completed;
        document.getElementById('totalDeliveries').textContent = completed;
        document.getElementById('totalAmount').textContent = formatSum(visitsData.totalAmount || 0);
    } catch (e) {
        console.error('Ma\'lumot yuklash xatosi:', e);
    }
}

async function loadTradePoints() {
    const token = Session.getToken();
    const listEl = document.getElementById('tradePointsList');
    const balanceEl = document.getElementById('totalBalance');

    try {
        const res = await fetch(`/api/driver/partners?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        const partners = data.partners || data.data || [];

        let totalBalance = 0;
        let html = '';
        partners.forEach(p => {
            const balance = p.balance || 0;
            totalBalance += balance;
            const balanceClass = balance >= 0 ? 'amount-positive' : 'amount-negative';
            const balanceText = balance >= 0 ? `Oldindan to'lov: ${formatSum(balance)}` : `Qarz: ${formatSum(balance)}`;
            html += `
                <div class="trade-point-item">
                    <div class="trade-point-icon"><i class="bi bi-building"></i></div>
                    <div class="trade-point-info">
                        <div class="trade-point-name">${escapeHtml(p.name || '')}</div>
                        <div class="trade-point-detail">${escapeHtml(p.address || p.region || '')}</div>
                        <div class="trade-point-detail ${balanceClass}">${balanceText}</div>
                    </div>
                    <div class="${balanceClass}">${formatSum(balance)}</div>
                </div>
            `;
        });

        listEl.innerHTML = html || '<p class="text-muted text-center py-4">Savdo nuqtalari yo\'q</p>';
        balanceEl.textContent = formatSum(totalBalance);
        balanceEl.className = totalBalance >= 0 ? 'amount-positive' : 'amount-negative';
    } catch (e) {
        listEl.innerHTML = '<p class="text-muted text-center py-4">Ma\'lumot yuklanmadi</p>';
        balanceEl.textContent = '0 сум';
    }
}

async function loadDebtors() {
    const token = Session.getToken();
    const listEl = document.getElementById('debtorsList');
    const totalEl = document.getElementById('totalDebt');

    try {
        const res = await fetch(`/api/driver/debtors?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        const debtors = data.debtors || data.data || [];
        const totalDebt = data.totalDebt || 0;

        let html = '';
        debtors.forEach(d => {
            const balance = d.balance || 0;
            const debt = d.debt || d.order_debt || 0;
            const unallocated = d.unallocated || 0;
            html += `
                <div class="trade-point-item">
                    <div class="trade-point-icon"><i class="bi bi-building"></i></div>
                    <div class="trade-point-info">
                        <div class="trade-point-name">${escapeHtml(d.name || '')}</div>
                        <div class="trade-point-detail amount-negative">Balans: ${formatSum(balance)}</div>
                        <div class="trade-point-detail amount-negative">Buyurtma qarzi: ${formatSum(debt)}</div>
                        <div class="trade-point-detail">Taqsimlanmagan: ${formatSum(unallocated)}</div>
                    </div>
                    <i class="bi bi-chevron-right text-muted"></i>
                </div>
            `;
        });

        listEl.innerHTML = html || '<p class="text-muted text-center py-4">Qarzdorlar yo\'q</p>';
        totalEl.textContent = formatSum(totalDebt);
    } catch (e) {
        listEl.innerHTML = '<p class="text-muted text-center py-4">Ma\'lumot yuklanmadi</p>';
        totalEl.textContent = '0';
    }
}

async function loadPaymentHistory() {
    const token = Session.getToken();
    const listEl = document.getElementById('paymentHistoryList');
    const totalEl = document.getElementById('paymentTotal');

    try {
        const res = await fetch(`/api/driver/payments?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        const payments = data.payments || data.data || [];
        const total = data.total || 0;

        let html = '';
        payments.forEach(p => {
            html += `
                <div class="trade-point-item">
                    <div class="trade-point-icon"><i class="bi bi-building"></i></div>
                    <div class="trade-point-info">
                        <div class="trade-point-name">${escapeHtml(p.partner_name || p.name || '')}</div>
                        <div class="trade-point-detail">${escapeHtml(p.address || '')}</div>
                    </div>
                    <div class="amount-positive">${formatSum(p.amount || 0)}</div>
                </div>
            `;
        });

        listEl.innerHTML = html || '<p class="text-muted text-center py-4">To\'lovlar yo\'q</p>';
        totalEl.textContent = formatSum(total);
    } catch (e) {
        listEl.innerHTML = '<p class="text-muted text-center py-4">Ma\'lumot yuklanmadi</p>';
        totalEl.textContent = '0 сум';
    }
}

async function loadOrderHistory() {
    const token = Session.getToken();
    const listEl = document.getElementById('orderHistoryList');

    try {
        const res = await fetch(`/api/driver/orders?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        const orders = data.orders || data.data || [];

        let html = '';
        orders.forEach(o => {
            html += `
                <div class="trade-point-item">
                    <div class="trade-point-icon"><i class="bi bi-cart"></i></div>
                    <div class="trade-point-info">
                        <div class="trade-point-name">${escapeHtml(o.number || '')}</div>
                        <div class="trade-point-detail">${escapeHtml(o.partner_name || '')} — ${formatSum(o.total || 0)}</div>
                    </div>
                    <i class="bi bi-chevron-right text-muted"></i>
                </div>
            `;
        });

        listEl.innerHTML = html || '<p class="text-muted text-center py-4">Buyurtmalar yo\'q</p>';
    } catch (e) {
        listEl.innerHTML = '<p class="text-muted text-center py-4">Ma\'lumot yuklanmadi</p>';
    }
}

function formatSum(val) {
    const n = typeof val === 'number' ? val : parseFloat(val) || 0;
    return new Intl.NumberFormat('uz-UZ').format(Math.round(n)) + ' сум';
}

function escapeHtml(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

// Auto GPS tracking
async function sendLocation() {
    try {
        const pos = await new Promise((resolve, reject) => {
            if (!navigator.geolocation) reject(new Error('GPS yo\'q'));
            navigator.geolocation.getCurrentPosition(resolve, reject);
        });
        const formData = new FormData();
        formData.append('latitude', pos.coords.latitude);
        formData.append('longitude', pos.coords.longitude);
        formData.append('accuracy', pos.coords.accuracy || 0);
        formData.append('battery', 100);
        formData.append('token', token);
        await fetch('/api/driver/location', { method: 'POST', body: formData });
    } catch (e) {
        console.warn('GPS yuborish:', e.message);
    }
}

setInterval(sendLocation, 5 * 60 * 1000);

// Init
loadDriverData();
