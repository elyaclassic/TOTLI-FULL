import 'package:shared_preferences/shared_preferences.dart';

class SessionService {
  static const _keyToken = 'session_token';
  static const _keyRole = 'session_role';
  static const _keyUserId = 'session_user_id';
  static const _keyFullName = 'session_full_name';
  static const _keyPhone = 'session_phone';
  static const _keyApiUrl = 'api_base_url';

  Future<void> saveSession({
    required String token,
    required String role,
    required int userId,
    String? fullName,
    String? phone,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyToken, token);
    await prefs.setString(_keyRole, role);
    await prefs.setInt(_keyUserId, userId);
    if (fullName != null) await prefs.setString(_keyFullName, fullName);
    if (phone != null) await prefs.setString(_keyPhone, phone);
  }

  Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyToken);
  }

  Future<String?> getRole() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyRole);
  }

  Future<int?> getUserId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_keyUserId);
  }

  Future<String?> getFullName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyFullName);
  }

  Future<String?> getPhone() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyPhone);
  }

  Future<String?> getApiUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyApiUrl);
  }

  Future<void> setApiUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyApiUrl, url);
  }

  Future<bool> isLoggedIn() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyToken);
    await prefs.remove(_keyRole);
    await prefs.remove(_keyUserId);
    await prefs.remove(_keyFullName);
    await prefs.remove(_keyPhone);
  }
}
