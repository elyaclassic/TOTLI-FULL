import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/location_service.dart';
import '../services/sync_service.dart';
import 'dashboard_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _serverController = TextEditingController(text: 'http://10.0.2.2:8080');
  bool _isLoading = false;
  bool _obscurePassword = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadSavedServer();
  }

  Future<void> _loadSavedServer() async {
    final session = SessionService();
    final url = await session.getApiUrl();
    if (url != null && url.isNotEmpty) {
      _serverController.text = url;
      ApiService.setBaseUrl(url);
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _serverController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (_isLoading) return;
    setState(() {
      _errorMessage = null;
      _isLoading = true;
    });

    final serverUrl = _serverController.text.trim();
    if (serverUrl.isEmpty) {
      setState(() {
        _errorMessage = 'Server manzilini kiriting';
        _isLoading = false;
      });
      return;
    }

    ApiService.setBaseUrl(serverUrl);
    await SessionService().setApiUrl(serverUrl);

    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty || password.isEmpty) {
      setState(() {
        _errorMessage = 'Login va parolni kiriting';
        _isLoading = false;
      });
      return;
    }

    final result = await ApiService.login(username, password);

    if (!mounted) return;
    setState(() => _isLoading = false);

    if (result['success'] == true) {
      final role = result['role']?.toString() ?? '';
      final token = result['token']?.toString() ?? '';
      final redirect = result['redirect']?.toString() ?? '';

      // Faqat agent va driver uchun mobil ilova
      if (redirect == 'pwa' && (role == 'agent' || role == 'driver')) {
        final session = SessionService();
        int userId = 0;
        String? fullName, phone;

        if (role == 'agent') {
          final agent = result['agent'] as Map<String, dynamic>?;
          userId = agent?['id'] ?? 0;
          fullName = agent?['full_name']?.toString();
          phone = agent?['phone']?.toString();
        } else {
          final driver = result['driver'] as Map<String, dynamic>?;
          userId = driver?['id'] ?? 0;
          fullName = driver?['full_name']?.toString();
          phone = driver?['phone']?.toString();
        }

        await session.saveSession(
          token: token,
          role: role,
          userId: userId,
          fullName: fullName,
          phone: phone,
        );

        // GPS ruxsat so'rash va tracking boshlash
        final locService = LocationService();
        final hasPerm = await locService.checkPermission();
        if (hasPerm) {
          locService.startPeriodicTracking();
        }

        // Offline cache — partners va products ni yuklash
        try {
          final syncService = SyncService();
          await syncService.init();
          await syncService.refreshCache();
        } catch (_) {}

        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const DashboardScreen()),
        );
      } else {
        setState(() {
          _errorMessage =
              'Bu ilova faqat Agent yoki Haydovchi uchun. Boshqa foydalanuvchilar veb-sahifadan kirishlari kerak.';
        });
      }
    } else {
      setState(() {
        _errorMessage = result['error']?.toString() ?? 'Xato yuz berdi';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF017449), Color(0xFF015A38)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                  const SizedBox(height: 32),
                  Center(
                    child: ClipOval(
                      child: Image.asset(
                        'assets/images/logo.png',
                        height: 180,
                        width: 180,
                        fit: BoxFit.cover,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Agent / Haydovchi kirish',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.white.withOpacity(0.8),
                    ),
                  ),
                  const SizedBox(height: 48),
                  _buildTextField(
                    controller: _serverController,
                    label: 'Server manzili',
                    hint: 'http://192.168.1.100:8080',
                    keyboardType: TextInputType.url,
                  ),
                  const SizedBox(height: 16),
                  _buildTextField(
                    controller: _usernameController,
                    label: 'Telefon raqam yoki login',
                    hint: '+998901234567',
                    keyboardType: TextInputType.text,
                  ),
                  const SizedBox(height: 16),
                  _buildTextField(
                    controller: _passwordController,
                    label: 'Parol',
                    hint: 'Parol',
                    obscureText: _obscurePassword,
                    suffixIcon: IconButton(
                      icon: Icon(
                        _obscurePassword ? Icons.visibility_off : Icons.visibility,
                        color: Colors.white.withOpacity(0.7),
                      ),
                      onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                    ),
                  ),
                  if (_errorMessage != null) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.withOpacity(0.3),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        _errorMessage!,
                        style: const TextStyle(color: Colors.white),
                      ),
                    ),
                  ],
                  const SizedBox(height: 32),
                  ElevatedButton(
                    onPressed: _isLoading ? null : _login,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFFFB50D),
                      foregroundColor: Colors.black87,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: _isLoading
                        ? const SizedBox(
                            height: 24,
                            width: 24,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('KIRISH', style: TextStyle(fontWeight: FontWeight.bold)),
                  ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    required String hint,
    bool obscureText = false,
    TextInputType? keyboardType,
    Widget? suffixIcon,
  }) {
    return TextFormField(
      controller: controller,
      obscureText: obscureText,
      keyboardType: keyboardType,
      style: const TextStyle(color: Colors.white),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: TextStyle(color: Colors.white.withOpacity(0.9)),
        hintStyle: TextStyle(color: Colors.white.withOpacity(0.5)),
        suffixIcon: suffixIcon,
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.white.withOpacity(0.5)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFFFB50D), width: 2),
        ),
      ),
    );
  }
}
