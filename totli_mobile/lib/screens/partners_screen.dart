import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';

class PartnersScreen extends StatefulWidget {
  const PartnersScreen({super.key});

  @override
  State<PartnersScreen> createState() => _PartnersScreenState();
}

class _PartnersScreenState extends State<PartnersScreen> {
  final SessionService _session = SessionService();
  final TextEditingController _searchController = TextEditingController();
  List<Map<String, dynamic>> _partners = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadPartners();
  }

  Future<void> _loadPartners({String? search}) async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.getPartners(token, search: search);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (result['success'] == true) {
          _partners = List<Map<String, dynamic>>.from(result['partners'] ?? []);
        }
      });
    }
  }

  void _onSearch() {
    _loadPartners(search: _searchController.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    hintText: 'Mijoz qidirish...',
                    prefixIcon: const Icon(Icons.search),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                    isDense: true,
                  ),
                  onSubmitted: (_) => _onSearch(),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.search, color: Color(0xFF017449)),
                onPressed: _onSearch,
              ),
            ],
          ),
        ),
        Expanded(
          child: _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _partners.isEmpty
                  ? const Center(child: Text('Mijozlar topilmadi'))
                  : RefreshIndicator(
                      onRefresh: () => _loadPartners(search: _searchController.text.trim()),
                      child: ListView.builder(
                        itemCount: _partners.length,
                        itemBuilder: (ctx, i) => _buildPartnerTile(_partners[i]),
                      ),
                    ),
        ),
      ],
    );
  }

  Widget _buildPartnerTile(Map<String, dynamic> p) {
    final balance = (p['balance'] ?? 0).toDouble();
    final hasDebt = balance < 0;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: hasDebt ? Colors.red.shade50 : Colors.green.shade50,
          child: Icon(Icons.store, color: hasDebt ? Colors.red : Colors.green, size: 20),
        ),
        title: Text(p['name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w500)),
        subtitle: Text(p['phone'] ?? p['address'] ?? '', style: const TextStyle(fontSize: 12)),
        trailing: balance != 0
            ? Text(
                '${balance > 0 ? "+" : ""}${(balance / 1000).toStringAsFixed(0)}K',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: hasDebt ? Colors.red : Colors.green,
                ),
              )
            : null,
        onTap: () => _showPartnerDetail(p),
      ),
    );
  }

  void _showPartnerDetail(Map<String, dynamic> p) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.85,
        expand: false,
        builder: (ctx, scroll) => SingleChildScrollView(
          controller: scroll,
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)))),
              const SizedBox(height: 16),
              Text(p['name'] ?? '', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              if (p['phone'] != null) ...[const SizedBox(height: 8), Row(children: [const Icon(Icons.phone, size: 16), const SizedBox(width: 8), Text(p['phone'])])],
              if (p['address'] != null) ...[const SizedBox(height: 4), Row(children: [const Icon(Icons.location_on, size: 16), const SizedBox(width: 8), Expanded(child: Text(p['address']))])],
              if (p['region'] != null) ...[const SizedBox(height: 4), Row(children: [const Icon(Icons.map, size: 16), const SizedBox(width: 8), Text(p['region'])])],
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.shopping_cart, size: 18),
                      label: const Text('Buyurtma'),
                      style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449), foregroundColor: Colors.white),
                      onPressed: () {
                        Navigator.pop(ctx);
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Buyurtma sahifasiga o\'ting')));
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.pin_drop, size: 18),
                      label: const Text('Vizit'),
                      onPressed: () {
                        Navigator.pop(ctx);
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit sahifasiga o\'ting')));
                      },
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
