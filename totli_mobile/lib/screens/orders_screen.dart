import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  final SessionService _session = SessionService();
  List<Map<String, dynamic>> _orders = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadOrders();
  }

  Future<void> _loadOrders() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.getMyOrders(token);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (result['success'] == true) {
          _orders = List<Map<String, dynamic>>.from(result['orders'] ?? []);
        }
      });
    }
  }

  void _createOrder() async {
    final token = await _session.getToken();
    if (token == null) return;

    // Mahsulotlar va partnerlarni yuklash
    final productsResult = await ApiService.getProducts(token);
    final partnersResult = await ApiService.getPartners(token);
    if (!mounted) return;

    final products = List<Map<String, dynamic>>.from(productsResult['products'] ?? []);
    final partners = List<Map<String, dynamic>>.from(partnersResult['partners'] ?? []);

    if (products.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulotlar topilmadi')));
      return;
    }

    final result = await Navigator.push(context, MaterialPageRoute(
      builder: (_) => _CreateOrderPage(products: products, partners: partners, token: token),
    ));
    if (result == true) _loadOrders();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _orders.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.shopping_cart_outlined, size: 64, color: Colors.grey[400]),
                      const SizedBox(height: 16),
                      const Text('Buyurtmalar yo\'q', style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadOrders,
                  child: ListView.builder(
                    itemCount: _orders.length,
                    itemBuilder: (ctx, i) => _buildOrderTile(_orders[i]),
                  ),
                ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _createOrder,
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add),
        label: const Text('Yangi buyurtma'),
      ),
    );
  }

  String _formatMoney(double v) {
    if (v <= 0) return '0';
    final str = v.toInt().toString();
    final buf = StringBuffer();
    for (int i = 0; i < str.length; i++) {
      if (i > 0 && (str.length - i) % 3 == 0) buf.write(' ');
      buf.write(str[i]);
    }
    return buf.toString();
  }

  Widget _buildOrderTile(Map<String, dynamic> o) {
    final status = o['status'] ?? 'draft';
    final statusColor = status == 'completed' ? Colors.green : status == 'confirmed' ? Colors.blue : Colors.orange;
    final statusText = status == 'completed' ? 'Bajarilgan' : status == 'confirmed' ? 'Tasdiqlangan' : 'Qoralama';
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: statusColor.withOpacity(0.15),
          child: Icon(Icons.receipt_long, color: statusColor, size: 20),
        ),
        title: Text(o['number'] ?? '#${o['id']}', style: const TextStyle(fontWeight: FontWeight.w500)),
        subtitle: Text(o['partner_name'] ?? o['partner'] ?? '', style: const TextStyle(fontSize: 12)),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text('${_formatMoney((o['total'] ?? 0).toDouble())}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
            Text(statusText, style: TextStyle(fontSize: 10, color: statusColor)),
          ],
        ),
      ),
    );
  }
}

class _CreateOrderPage extends StatefulWidget {
  final List<Map<String, dynamic>> products;
  final List<Map<String, dynamic>> partners;
  final String token;
  const _CreateOrderPage({required this.products, required this.partners, required this.token});

  @override
  State<_CreateOrderPage> createState() => _CreateOrderPageState();
}

class _CreateOrderPageState extends State<_CreateOrderPage> {
  int? _selectedPartnerId;
  String _paymentType = 'naqd';
  final Map<int, double> _cart = {};
  bool _isSending = false;
  String _searchQuery = '';

  String _formatMoney(double v) {
    if (v <= 0) return '0';
    final str = v.toInt().toString();
    final buf = StringBuffer();
    for (int i = 0; i < str.length; i++) {
      if (i > 0 && (str.length - i) % 3 == 0) buf.write(' ');
      buf.write(str[i]);
    }
    return buf.toString();
  }

  List<Map<String, dynamic>> get _filteredProducts {
    if (_searchQuery.isEmpty) return widget.products;
    final q = _searchQuery.toLowerCase();
    return widget.products.where((p) => (p['name'] ?? '').toString().toLowerCase().contains(q)).toList();
  }

  double get _total {
    double t = 0;
    _cart.forEach((pid, qty) {
      final p = widget.products.firstWhere((x) => x['id'] == pid, orElse: () => {});
      t += (p['price'] ?? 0).toDouble() * qty;
    });
    return t;
  }

  Future<void> _editQty(int pid, String productName, double currentQty) async {
    final controller = TextEditingController(text: currentQty > 0 ? currentQty.toStringAsFixed(currentQty == currentQty.roundToDouble() ? 0 : 1) : '');
    final result = await showDialog<double>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(productName, style: const TextStyle(fontSize: 15)),
        content: TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Miqdor', border: OutlineInputBorder()),
          onSubmitted: (v) => Navigator.pop(ctx, double.tryParse(v) ?? 0),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, 0.0), child: const Text('O\'chirish')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, double.tryParse(controller.text) ?? 0),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449)),
            child: const Text('OK', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
    if (result == null) return;
    setState(() {
      if (result <= 0) _cart.remove(pid); else _cart[pid] = result;
    });
  }

  Future<void> _submit() async {
    if (_selectedPartnerId == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mijozni tanlang')));
      return;
    }
    if (_cart.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulot qo\'shing')));
      return;
    }
    setState(() => _isSending = true);
    final items = _cart.entries.map((e) => {'product_id': e.key, 'qty': e.value}).toList();
    final result = await ApiService.createOrder(widget.token, {
      'partner_id': _selectedPartnerId,
      'payment_type': _paymentType,
      'items': items,
    });
    if (!mounted) return;
    setState(() => _isSending = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Buyurtma yaratildi: ${result['order_number'] ?? ''}'),
        backgroundColor: Colors.green,
      ));
      Navigator.pop(context, true);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(result['error'] ?? 'Xato'),
        backgroundColor: Colors.red,
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Yangi buyurtma'),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: Column(
        children: [
          // Mijoz va to'lov turi
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              children: [
                DropdownButtonFormField<int>(
                  value: _selectedPartnerId,
                  decoration: InputDecoration(
                    labelText: 'Mijoz',
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                    isDense: true,
                  ),
                  isExpanded: true,
                  items: widget.partners.map((p) => DropdownMenuItem<int>(
                    value: p['id'] as int,
                    child: Text(p['name'] ?? '', overflow: TextOverflow.ellipsis),
                  )).toList(),
                  onChanged: (v) => setState(() => _selectedPartnerId = v),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text('To\'lov: ', style: TextStyle(fontWeight: FontWeight.w500)),
                    ChoiceChip(label: const Text('Naqd'), selected: _paymentType == 'naqd', onSelected: (_) => setState(() => _paymentType = 'naqd')),
                    const SizedBox(width: 8),
                    ChoiceChip(label: const Text('Qarz'), selected: _paymentType == 'qarz', onSelected: (_) => setState(() => _paymentType = 'qarz')),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  decoration: InputDecoration(
                    hintText: 'Mahsulot qidirish...',
                    prefixIcon: const Icon(Icons.search),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  ),
                  onChanged: (v) => setState(() => _searchQuery = v),
                ),
              ],
            ),
          ),
          // Mahsulotlar
          Expanded(
            child: ListView.builder(
              itemCount: _filteredProducts.length,
              itemBuilder: (ctx, i) {
                final p = _filteredProducts[i];
                final pid = p['id'] as int;
                final qty = _cart[pid] ?? 0;
                final stock = (p['stock'] ?? 0).toDouble();
                return ListTile(
                  dense: true,
                  title: Text(p['name'] ?? '', style: const TextStyle(fontSize: 14)),
                  subtitle: Text(
                    '${((p['price'] ?? 0) / 1000).toStringAsFixed(0)}K | Qoldiq: ${stock.toStringAsFixed(0)} ${p['unit'] ?? ''}',
                    style: TextStyle(fontSize: 11, color: stock > 0 ? Colors.grey : Colors.red),
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (qty > 0) IconButton(icon: const Icon(Icons.remove_circle_outline, size: 22), onPressed: () => setState(() { if (qty <= 1) _cart.remove(pid); else _cart[pid] = qty - 1; })),
                      if (qty > 0) GestureDetector(
                        onTap: () => _editQty(pid, p['name'] ?? '', qty),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(border: Border.all(color: const Color(0xFF017449)), borderRadius: BorderRadius.circular(6)),
                          child: Text(qty == qty.roundToDouble() ? qty.toStringAsFixed(0) : qty.toStringAsFixed(1), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF017449))),
                        ),
                      ),
                      IconButton(icon: const Icon(Icons.add_circle, color: Color(0xFF017449), size: 22), onPressed: () => setState(() => _cart[pid] = qty + 1)),
                    ],
                  ),
                );
              },
            ),
          ),
          // Jami va yuborish
          if (_cart.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8, offset: const Offset(0, -2))],
              ),
              child: Row(
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${_cart.length} ta mahsulot', style: const TextStyle(fontSize: 12, color: Colors.grey)),
                      Text('${_formatMoney(_total)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const Spacer(),
                  ElevatedButton(
                    onPressed: _isSending ? null : _submit,
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449), foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12)),
                    child: _isSending ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Yuborish'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
