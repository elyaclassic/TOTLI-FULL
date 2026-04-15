import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/offline_db_service.dart';
import '../services/sync_service.dart';

enum MapMode { all, route, near }

class MapScreen extends StatefulWidget {
  const MapScreen({super.key});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final SessionService _session = SessionService();
  final MapController _mapController = MapController();

  List<Map<String, dynamic>> _partners = [];
  Position? _myPos;
  MapMode _mode = MapMode.all;
  bool _isLoading = true;

  int get _todayDbDay {
    final wd = DateTime.now().weekday; // 1=Mon..7=Sun
    return wd == 7 ? 0 : wd;
  }

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    await Future.wait([_loadPartners(), _loadMyPos()]);
    if (mounted) {
      setState(() => _isLoading = false);
      _fitToMarkers();
    }
  }

  Future<void> _loadPartners() async {
    final token = await _session.getToken();
    if (token == null) return;
    final syncService = SyncService();
    final offlineDb = OfflineDbService();

    if (syncService.isOnline) {
      final result = await ApiService.getPartners(token);
      if (result['success'] == true) {
        _partners = List<Map<String, dynamic>>.from(result['partners'] ?? []);
        offlineDb.cachePartners(_partners);
        return;
      }
    }
    _partners = await offlineDb.getCachedPartners();
  }

  Future<void> _loadMyPos() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 8),
      );
      _myPos = pos;
    } catch (_) {
      // GPS yo'q bo'lsa ham map ishlaydi
    }
  }

  List<Map<String, dynamic>> get _withLocation =>
      _partners.where((p) => p['lat'] != null && p['lng'] != null).toList();

  List<Map<String, dynamic>> get _todayPartners {
    final today = _todayDbDay;
    return _withLocation.where((p) => p['visit_day'] == today).toList();
  }

  double _distanceKm(double lat1, double lng1, double lat2, double lng2) {
    const R = 6371.0;
    const toRad = math.pi / 180;
    final dLat = (lat2 - lat1) * toRad;
    final dLng = (lng2 - lng1) * toRad;
    final a = math.sin(dLat / 2) * math.sin(dLat / 2) +
        math.cos(lat1 * toRad) * math.cos(lat2 * toRad) *
            math.sin(dLng / 2) * math.sin(dLng / 2);
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
  }

  String _fmtDist(double km) {
    if (km < 1) return '${(km * 1000).round()} m';
    if (km < 10) return '${km.toStringAsFixed(1)} km';
    return '${km.round()} km';
  }

  List<Map<String, dynamic>> _sortedByDistance(List<Map<String, dynamic>> list) {
    if (_myPos == null) return list;
    final mp = _myPos!;
    list.sort((a, b) {
      final da = _distanceKm(mp.latitude, mp.longitude, (a['lat'] as num).toDouble(), (a['lng'] as num).toDouble());
      final db = _distanceKm(mp.latitude, mp.longitude, (b['lat'] as num).toDouble(), (b['lng'] as num).toDouble());
      return da.compareTo(db);
    });
    return list;
  }

  List<Map<String, dynamic>> get _displayPartners {
    switch (_mode) {
      case MapMode.all:
        return _withLocation;
      case MapMode.route:
        return _sortedByDistance(List.from(_todayPartners));
      case MapMode.near:
        if (_myPos == null) return [];
        final sorted = _sortedByDistance(List.from(_withLocation));
        return sorted.take(20).toList();
    }
  }

  void _fitToMarkers() {
    final pts = _displayPartners
        .map((p) => LatLng((p['lat'] as num).toDouble(), (p['lng'] as num).toDouble()))
        .toList();
    if (_myPos != null) pts.add(LatLng(_myPos!.latitude, _myPos!.longitude));
    if (pts.isEmpty) return;
    if (pts.length == 1) {
      _mapController.move(pts.first, 15);
      return;
    }
    double minLat = pts.first.latitude, maxLat = pts.first.latitude;
    double minLng = pts.first.longitude, maxLng = pts.first.longitude;
    for (final p in pts) {
      if (p.latitude < minLat) minLat = p.latitude;
      if (p.latitude > maxLat) maxLat = p.latitude;
      if (p.longitude < minLng) minLng = p.longitude;
      if (p.longitude > maxLng) maxLng = p.longitude;
    }
    final bounds = LatLngBounds(LatLng(minLat, minLng), LatLng(maxLat, maxLng));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _mapController.fitCamera(
        CameraFit.bounds(bounds: bounds, padding: const EdgeInsets.all(50), maxZoom: 15),
      );
    });
  }

  void _changeMode(MapMode m) {
    setState(() => _mode = m);
    _fitToMarkers();
  }

  void _centerOnMe() {
    if (_myPos == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('GPS aniqlanmadi')),
      );
      return;
    }
    _mapController.move(LatLng(_myPos!.latitude, _myPos!.longitude), 16);
  }

  void _openNavSheet(double lat, double lng, String name) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2))),
              const SizedBox(height: 12),
              Text('Yo\'nalish: $name', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              _navTile(
                icon: Icons.map,
                label: 'Yandex Maps',
                color: Colors.red,
                onTap: () async {
                  Navigator.pop(ctx);
                  await launchUrl(
                    Uri.parse('https://yandex.com/maps/?rtext=~$lat,$lng&rtt=auto'),
                    mode: LaunchMode.externalApplication,
                  );
                },
              ),
              const SizedBox(height: 8),
              _navTile(
                icon: Icons.navigation,
                label: 'Google Maps',
                color: Colors.blue,
                onTap: () async {
                  Navigator.pop(ctx);
                  await launchUrl(
                    Uri.parse('https://www.google.com/maps/dir/?api=1&destination=$lat,$lng&travelmode=driving'),
                    mode: LaunchMode.externalApplication,
                  );
                },
              ),
              const SizedBox(height: 8),
              _navTile(
                icon: Icons.location_on,
                label: '2GIS',
                color: Colors.green,
                onTap: () async {
                  Navigator.pop(ctx);
                  await launchUrl(
                    Uri.parse('https://2gis.uz/geo/$lng,$lat'),
                    mode: LaunchMode.externalApplication,
                  );
                },
              ),
              const SizedBox(height: 12),
            ],
          ),
        ),
      ),
    );
  }

  Widget _navTile({required IconData icon, required String label, required Color color, required VoidCallback onTap}) {
    return Material(
      color: color.withOpacity(0.08),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Icon(icon, color: color, size: 24),
              const SizedBox(width: 14),
              Text(label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: color)),
              const Spacer(),
              Icon(Icons.chevron_right, color: color, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  void _showPartnerSheet(Map<String, dynamic> p) {
    final lat = (p['lat'] as num).toDouble();
    final lng = (p['lng'] as num).toDouble();
    final name = (p['name'] ?? '').toString();
    final phone = (p['phone'] ?? '').toString();
    final address = (p['address'] ?? '').toString();
    String? dist;
    if (_myPos != null) {
      dist = _fmtDist(_distanceKm(_myPos!.latitude, _myPos!.longitude, lat, lng));
    }
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2))),
              const SizedBox(height: 14),
              Text(name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              if (address.isNotEmpty) ...[
                const SizedBox(height: 4),
                Row(children: [
                  const Icon(Icons.place, size: 16, color: Colors.grey),
                  const SizedBox(width: 6),
                  Expanded(child: Text(address, style: TextStyle(color: Colors.grey[700]))),
                ]),
              ],
              if (phone.isNotEmpty) ...[
                const SizedBox(height: 4),
                Row(children: [
                  const Icon(Icons.phone, size: 16, color: Colors.grey),
                  const SizedBox(width: 6),
                  Text(phone, style: TextStyle(color: Colors.grey[700])),
                ]),
              ],
              if (dist != null) ...[
                const SizedBox(height: 4),
                Row(children: [
                  const Icon(Icons.straighten, size: 16, color: Color(0xFF017449)),
                  const SizedBox(width: 6),
                  Text('Mendan $dist', style: const TextStyle(color: Color(0xFF017449), fontWeight: FontWeight.w600)),
                ]),
              ],
              const SizedBox(height: 16),
              Row(children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _openNavSheet(lat, lng, name);
                    },
                    icon: const Icon(Icons.navigation, size: 18),
                    label: const Text('Yo\'nalish'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.orange,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
                if (phone.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    onPressed: () => launchUrl(Uri.parse('tel:$phone')),
                    icon: const Icon(Icons.call, size: 18),
                    label: const Text('Qo\'ng\'iroq'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ],
              ]),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final display = _displayPartners;
    final infoText = _infoText(display.length);
    final initCenter = _myPos != null
        ? LatLng(_myPos!.latitude, _myPos!.longitude)
        : const LatLng(41.311081, 69.240562); // Tashkent fallback

    return Scaffold(
      appBar: AppBar(
        title: const Text('Xarita', style: TextStyle(fontSize: 16)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.my_location),
            onPressed: _centerOnMe,
            tooltip: 'Mening o\'rnim',
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                Container(
                  color: Colors.white,
                  padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
                  child: Row(
                    children: [
                      _modeChip('Barchasi', Icons.place, MapMode.all),
                      const SizedBox(width: 6),
                      _modeChip('Marshrut', Icons.alt_route, MapMode.route),
                      const SizedBox(width: 6),
                      _modeChip('Yaqin', Icons.near_me, MapMode.near),
                    ],
                  ),
                ),
                Container(
                  width: double.infinity,
                  color: Colors.grey[100],
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Text(infoText, style: const TextStyle(fontSize: 12, color: Colors.black54)),
                ),
                Expanded(
                  child: Stack(
                    children: [
                      FlutterMap(
                        mapController: _mapController,
                        options: MapOptions(
                          initialCenter: initCenter,
                          initialZoom: 13,
                          maxZoom: 18,
                          minZoom: 4,
                        ),
                        children: [
                          TileLayer(
                            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                            userAgentPackageName: 'uz.totli.mobile',
                          ),
                          if (_mode == MapMode.route && display.length > 1)
                            PolylineLayer(
                              polylines: [
                                Polyline(
                                  points: [
                                    if (_myPos != null) LatLng(_myPos!.latitude, _myPos!.longitude),
                                    ...display.map((p) => LatLng((p['lat'] as num).toDouble(), (p['lng'] as num).toDouble())),
                                  ],
                                  strokeWidth: 4,
                                  color: Colors.orange.withOpacity(0.8),
                                  isDotted: true,
                                ),
                              ],
                            ),
                          MarkerLayer(
                            markers: [
                              ..._buildClientMarkers(display),
                              if (_myPos != null)
                                Marker(
                                  width: 28,
                                  height: 28,
                                  point: LatLng(_myPos!.latitude, _myPos!.longitude),
                                  child: Container(
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      color: Colors.blue.shade700,
                                      border: Border.all(color: Colors.white, width: 3),
                                      boxShadow: [BoxShadow(color: Colors.blue.withOpacity(0.5), blurRadius: 8, spreadRadius: 2)],
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ],
                      ),
                      if (_mode == MapMode.near && display.isNotEmpty)
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 0,
                          child: _buildNearList(display),
                        ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }

  String _infoText(int count) {
    switch (_mode) {
      case MapMode.all:
        return 'Barcha mijozlar: $count ta (GPS bor)';
      case MapMode.route:
        return 'Bugungi marshrut: $count ta mijoz';
      case MapMode.near:
        if (_myPos == null) return 'GPS yo\'q — yaqin mijozlar hisoblanmaydi';
        return 'Eng yaqin: $count ta';
    }
  }

  Widget _modeChip(String label, IconData icon, MapMode m) {
    final active = _mode == m;
    return Expanded(
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => _changeMode(m),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: active ? const Color(0xFF017449) : Colors.grey[100],
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 16, color: active ? Colors.white : Colors.black54),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: active ? Colors.white : Colors.black54,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<Marker> _buildClientMarkers(List<Map<String, dynamic>> list) {
    final markers = <Marker>[];
    for (var i = 0; i < list.length; i++) {
      final p = list[i];
      final lat = (p['lat'] as num).toDouble();
      final lng = (p['lng'] as num).toDouble();
      final numbered = _mode != MapMode.all;
      final color = _mode == MapMode.route ? Colors.orange : const Color(0xFF017449);
      markers.add(
        Marker(
          width: 36,
          height: 44,
          point: LatLng(lat, lng),
          alignment: Alignment.topCenter,
          child: GestureDetector(
            onTap: () => _showPartnerSheet(p),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Icon(Icons.location_on, size: 36, color: color, shadows: const [Shadow(color: Colors.black45, blurRadius: 3)]),
                if (numbered)
                  Positioned(
                    left: 9,
                    top: 4,
                    child: Container(
                      width: 18,
                      height: 18,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                        border: Border.all(color: color, width: 1.5),
                      ),
                      child: Text(
                        '${i + 1}',
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: color),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
    }
    return markers;
  }

  Widget _buildNearList(List<Map<String, dynamic>> list) {
    return Container(
      constraints: const BoxConstraints(maxHeight: 260),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 8, offset: Offset(0, -2))],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 40,
            height: 4,
            margin: const EdgeInsets.only(top: 8, bottom: 4),
            decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)),
          ),
          Flexible(
            child: ListView.builder(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              itemCount: list.length,
              itemBuilder: (ctx, i) {
                final p = list[i];
                final lat = (p['lat'] as num).toDouble();
                final lng = (p['lng'] as num).toDouble();
                final dist = _myPos == null
                    ? ''
                    : _fmtDist(_distanceKm(_myPos!.latitude, _myPos!.longitude, lat, lng));
                return ListTile(
                  dense: true,
                  leading: CircleAvatar(
                    radius: 14,
                    backgroundColor: const Color(0xFF017449).withOpacity(0.15),
                    child: Text('${i + 1}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF017449))),
                  ),
                  title: Text(p['name'] ?? '', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                  subtitle: Text(
                    (p['address'] ?? p['phone'] ?? '').toString(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11),
                  ),
                  trailing: Text(
                    dist,
                    style: const TextStyle(fontSize: 13, color: Color(0xFF017449), fontWeight: FontWeight.bold),
                  ),
                  onTap: () {
                    _mapController.move(LatLng(lat, lng), 17);
                    _showPartnerSheet(p);
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
