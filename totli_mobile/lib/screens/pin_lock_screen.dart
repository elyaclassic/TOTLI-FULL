import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/pin_service.dart';
import '../services/session_service.dart';
import 'login_screen.dart';
import 'dashboard_screen.dart';

/// PIN qulfdan ochish ekrani — ilova ochilganda har safar ko'rsatiladi.
class PinLockScreen extends StatefulWidget {
  const PinLockScreen({super.key});

  @override
  State<PinLockScreen> createState() => _PinLockScreenState();
}

class _PinLockScreenState extends State<PinLockScreen> {
  final TextEditingController _pin = TextEditingController();
  final FocusNode _focus = FocusNode();
  String? _error;
  String? _info;
  bool _checking = false;
  int _lockSeconds = 0;
  Timer? _lockTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _focus.requestFocus());
  }

  @override
  void dispose() {
    _lockTimer?.cancel();
    _pin.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _startLockCountdown(int seconds) {
    _lockSeconds = seconds;
    _lockTimer?.cancel();
    _lockTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return;
      setState(() {
        _lockSeconds--;
        if (_lockSeconds <= 0) {
          t.cancel();
          _info = null;
        }
      });
    });
  }

  Future<void> _verify() async {
    if (_lockSeconds > 0) return;
    final p = _pin.text.trim();
    if (p.length != 4) {
      setState(() => _error = 'PIN 4 raqam bo\'lishi kerak');
      return;
    }
    setState(() {
      _checking = true;
      _error = null;
    });
    final res = await PinService().verifyPin(p);
    if (!mounted) return;
    setState(() => _checking = false);

    switch (res.status) {
      case PinVerifyStatus.ok:
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const DashboardScreen()),
        );
        return;
      case PinVerifyStatus.wrong:
        setState(() {
          _error = 'PIN noto\'g\'ri. ${res.attemptsLeft} ta urinish qoldi.';
          _pin.clear();
        });
        _focus.requestFocus();
        return;
      case PinVerifyStatus.locked:
        _startLockCountdown(res.lockSecondsLeft ?? 60);
        setState(() {
          _info = 'Juda ko\'p noto\'g\'ri urinish. Biroz kuting.';
          _pin.clear();
        });
        return;
      case PinVerifyStatus.wiped:
        await SessionService().logout();
        if (!mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (_) => false,
        );
        return;
      case PinVerifyStatus.notSet:
        await SessionService().logout();
        if (!mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (_) => false,
        );
        return;
    }
  }

  Future<void> _forgotPin() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('PIN ni tiklash'),
        content: const Text(
            'PIN unutilgan bo\'lsa, qaytadan login qilish kerak (internet bilan). PIN saqlangan ma\'lumotlar tozalanadi. Davom etamizmi?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
            child: const Text('Ha, tiklash'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await PinService().clearPin();
    await SessionService().logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
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
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.lock, size: 72, color: Colors.white),
                    const SizedBox(height: 16),
                    const Text(
                      'PIN kiriting',
                      style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 28),
                    TextField(
                      controller: _pin,
                      focusNode: _focus,
                      keyboardType: TextInputType.number,
                      obscureText: true,
                      maxLength: 4,
                      enabled: _lockSeconds == 0,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white, fontSize: 28, letterSpacing: 16),
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      decoration: InputDecoration(
                        counterText: '',
                        labelText: 'PIN',
                        labelStyle: TextStyle(color: Colors.white.withOpacity(0.9)),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: Colors.white.withOpacity(0.5)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: const BorderSide(color: Color(0xFFFFB50D), width: 2),
                        ),
                      ),
                      onChanged: (v) {
                        if (v.length == 4) _verify();
                      },
                    ),
                    if (_lockSeconds > 0) ...[
                      const SizedBox(height: 16),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.orange.withOpacity(0.3),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          'Bloklangan. $_lockSeconds soniyadan keyin qayta urinib ko\'ring.',
                          style: const TextStyle(color: Colors.white),
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ] else if (_error != null) ...[
                      const SizedBox(height: 16),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red.withOpacity(0.3),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(_error!, style: const TextStyle(color: Colors.white)),
                      ),
                    ] else if (_info != null) ...[
                      const SizedBox(height: 16),
                      Text(_info!, style: const TextStyle(color: Colors.white70)),
                    ],
                    const SizedBox(height: 28),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: (_checking || _lockSeconds > 0) ? null : _verify,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFFFFB50D),
                          foregroundColor: Colors.black87,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        child: _checking
                            ? const SizedBox(height: 22, width: 22, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Text('OCHISH', style: TextStyle(fontWeight: FontWeight.bold)),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextButton(
                      onPressed: _forgotPin,
                      child: const Text('PIN ni unutdim', style: TextStyle(color: Colors.white70)),
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
}
