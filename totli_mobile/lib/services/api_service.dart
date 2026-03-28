import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  static String _baseUrl = 'http://10.0.2.2:8080';

  static void setBaseUrl(String url) {
    _baseUrl = url.replaceAll(RegExp(r'/$'), '');
  }

  static String get baseUrl => _baseUrl;

  static Map<String, String> _headers(String? token) => {
    'Content-Type': 'application/x-www-form-urlencoded',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  static Map<String, String> _jsonHeaders(String? token) => {
    'Content-Type': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  static Future<Map<String, dynamic>> _get(String path, String? token) async {
    try {
      final sep = path.contains('?') ? '&' : '?';
      final url = '$_baseUrl$path${token != null ? "${sep}token=${Uri.encodeComponent(token)}" : ""}';
      final r = await http.get(Uri.parse(url)).timeout(const Duration(seconds: 15));
      return jsonDecode(r.body) as Map<String, dynamic>;
    } catch (e) {
      return {'success': false, 'error': 'Ulanish xatosi: $e'};
    }
  }

  static Future<Map<String, dynamic>> _post(String path, Map<String, String> body, {String? token}) async {
    try {
      if (token != null) body['token'] = token;
      final r = await http.post(
        Uri.parse('$_baseUrl$path'),
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.entries.map((e) => '${Uri.encodeComponent(e.key)}=${Uri.encodeComponent(e.value)}').join('&'),
      ).timeout(const Duration(seconds: 15));
      return jsonDecode(r.body) as Map<String, dynamic>;
    } catch (e) {
      return {'success': false, 'error': 'Ulanish xatosi: $e'};
    }
  }

  static Future<Map<String, dynamic>> _postJson(String path, Map<String, dynamic> body, {String? token}) async {
    try {
      if (token != null) body['token'] = token;
      final r = await http.post(
        Uri.parse('$_baseUrl$path'),
        headers: _jsonHeaders(null),
        body: jsonEncode(body),
      ).timeout(const Duration(seconds: 15));
      return jsonDecode(r.body) as Map<String, dynamic>;
    } catch (e) {
      return {'success': false, 'error': 'Ulanish xatosi: $e'};
    }
  }

  // ===== AUTH =====
  static Future<Map<String, dynamic>> login(String username, String password) async {
    return _post('/api/login', {'username': username, 'password': password});
  }

  // ===== LOCATION =====
  static Future<Map<String, dynamic>> sendLocation({
    required String userType,
    required String token,
    required double latitude,
    required double longitude,
    double? accuracy,
    int? battery,
  }) async {
    return _post('/api/$userType/location', {
      'latitude': latitude.toString(),
      'longitude': longitude.toString(),
      'accuracy': (accuracy ?? 0).toString(),
      'battery': (battery ?? 100).toString(),
    }, token: token);
  }

  // ===== AGENT: PARTNERS =====
  static Future<Map<String, dynamic>> getPartners(String token, {String? search}) async {
    final q = search != null && search.isNotEmpty ? '&search=${Uri.encodeComponent(search)}' : '';
    return _get('/api/agent/my-partners?token=${Uri.encodeComponent(token)}$q', null);
  }

  static Future<Map<String, dynamic>> getPartnerDebts(String token, int partnerId) async {
    return _get('/api/agent/partner/$partnerId/debts', token);
  }

  static Future<Map<String, dynamic>> addPartner(String token, Map<String, String> data) async {
    return _post('/api/agent/partner/add', data, token: token);
  }

  // ===== AGENT: ORDERS =====
  static Future<Map<String, dynamic>> getMyOrders(String token) async {
    return _get('/api/agent/my-orders', token);
  }

  static Future<Map<String, dynamic>> createOrder(String token, Map<String, dynamic> orderData) async {
    return _postJson('/api/agent/order/create', orderData, token: token);
  }

  static Future<Map<String, dynamic>> getProducts(String token) async {
    return _get('/api/agent/products', token);
  }

  // ===== AGENT: VISITS =====
  static Future<Map<String, dynamic>> getVisits(String token) async {
    return _get('/api/agent/visits', token);
  }

  static Future<Map<String, dynamic>> checkIn(String token, {
    required int partnerId,
    required double latitude,
    required double longitude,
    String? notes,
  }) async {
    return _post('/api/agent/visit/checkin', {
      'partner_id': partnerId.toString(),
      'latitude': latitude.toString(),
      'longitude': longitude.toString(),
      if (notes != null) 'notes': notes,
    }, token: token);
  }

  static Future<Map<String, dynamic>> checkOut(String token, {
    required int visitId,
    String? notes,
  }) async {
    return _post('/api/agent/visit/checkout', {
      'visit_id': visitId.toString(),
      if (notes != null) 'notes': notes,
    }, token: token);
  }

  // ===== AGENT: PARTNER DETAIL & DEBTS =====
  static Future<Map<String, dynamic>> getPartnerDetail(String token, int partnerId) async {
    return _get('/api/agent/partner/$partnerId', token);
  }

  static Future<Map<String, dynamic>> getPartnerCompletedOrders(String token, int partnerId) async {
    return _get('/api/agent/partner/$partnerId/completed-orders', token);
  }

  static Future<Map<String, dynamic>> createReturn(String token, Map<String, dynamic> data) async {
    return _postJson('/api/agent/return/create', data, token: token);
  }

  // ===== AGENT: STATS =====
  static Future<Map<String, dynamic>> getAgentStats(String token) async {
    return _get('/api/agent/stats', token);
  }

  // ===== DRIVER: DELIVERIES =====
  static Future<Map<String, dynamic>> getDeliveries(String token) async {
    return _get('/api/driver/deliveries', token);
  }

  static Future<Map<String, dynamic>> updateDeliveryStatus(String token, int deliveryId, String status, {
    double? latitude, double? longitude, String? notes,
  }) async {
    return _post('/api/driver/delivery/$deliveryId/status', {
      'status': status,
      if (latitude != null) 'latitude': latitude.toString(),
      if (longitude != null) 'longitude': longitude.toString(),
      if (notes != null) 'notes': notes,
    }, token: token);
  }

  // ===== DRIVER: STATS =====
  static Future<Map<String, dynamic>> getDriverStats(String token) async {
    return _get('/api/driver/stats', token);
  }

  // ===== APP UPDATE =====
  static Future<Map<String, dynamic>> checkAppVersion() async {
    try {
      final r = await http.get(Uri.parse('$_baseUrl/api/app/version')).timeout(const Duration(seconds: 10));
      if (r.statusCode == 200) return jsonDecode(r.body) as Map<String, dynamic>;
    } catch (_) {}
    return {};
  }

  // ===== PWA CONFIG =====
  static Future<String?> fetchApiBaseUrl() async {
    try {
      final r = await http.get(Uri.parse('$_baseUrl/api/pwa/config'));
      if (r.statusCode == 200) {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        return data['apiBaseUrl']?.toString()?.trim();
      }
    } catch (_) {}
    return null;
  }
}
