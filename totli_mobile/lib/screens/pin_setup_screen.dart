import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/pin_service.dart';
import 'dashboard_screen.dart';

/// PIN o'rnatish ekrani — 4 raqamli PIN ikki marta kiritish
class PinSetupScreen extends StatefulWidget {
  /// Birinchi marta o'rnatish (true — orqaga qaytib bo'lmaydi).
  /// PIN almashtirish (false — Settings'dan ochilganda).
  final bool firstTime;
  const PinSetupScreen({super.key, this.firstTime = true});

  @override
  State<PinSetupScreen> createState() => _PinSetupScreenState();
}

class _PinSetupScreenState extends State<PinSetupScreen> {
  final TextEditingController _pin1 = TextEditingController();
  final TextEditingController _pin2 = TextEditingController();
  final FocusNode _focus1 = FocusNode();
  final FocusNode _focus2 = FocusNode();
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _focus1.requestFocus());
  }

  @override
  void dispose() {
    _pin1.dispose();
    _pin2.dispose();
    _focus1.dispose();
    _focus2.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _error = null);
    final p1 = _pin1.text.trim();
    final p2 = _pin2.text.trim();
    if (p1.length != 4 || p2.length != 4) {
      setState(() => _error = 'PIN 4 raqam bo\'lishi kerak');
      return;
    }
    if (p1 != p2) {
      setState(() => _error = 'PIN lar mos kelmadi');
      return;
    }
    if (RegExp(r'^(\d)\1{3}$').hasMatch(p1)) {
      setState(() => _error = 'Bir xil 4 raqamdan iborat PIN qabul qilinmaydi');
      return;
    }
    setState(() => _saving = true);
    await PinService().setPin(p1);
    if (!mounted) return;
    setState(() => _saving = false);
    if (widget.firstTime) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const DashboardScreen()),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PIN saqlandi'), backgroundColor: Color(0xFF017449)),
      );
      Navigator.of(context).pop(true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !widget.firstTime,
      child: Scaffold(
        appBar: widget.firstTime
            ? null
            : AppBar(
                title: const Text('PIN o\'zgartirish'),
                backgroundColor: const Color(0xFF017449),
                foregroundColor: Colors.white,
              ),
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
                    const SizedBox(height: 12),
                    const Icon(Icons.lock_outline, size: 64, color: Colors.white),
                    const SizedBox(height: 16),
                    const Text(
                      'PIN kod o\'rnating',
                      style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      '4 raqamli PIN — har ilova ochilganda kiritiladi.\nIlova internetsiz ham ochiladi.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.white70, fontSize: 13),
                    ),
                    const SizedBox(height: 28),
                    _buildPinField('PIN', _pin1, _focus1, _focus2),
                    const SizedBox(height: 16),
                    _buildPinField('PIN ni qayta kiriting', _pin2, _focus2, null),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red.withOpacity(0.3),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(_error!, style: const TextStyle(color: Colors.white)),
                      ),
                    ],
                    const SizedBox(height: 28),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: _saving ? null : _save,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFFFFB50D),
                          foregroundColor: Colors.black87,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        child: _saving
                            ? const SizedBox(height: 22, width: 22, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Text('SAQLASH', style: TextStyle(fontWeight: FontWeight.bold)),
                      ),
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

  Widget _buildPinField(String label, TextEditingController c, FocusNode f, FocusNode? next) {
    return TextField(
      controller: c,
      focusNode: f,
      keyboardType: TextInputType.number,
      obscureText: true,
      maxLength: 4,
      textAlign: TextAlign.center,
      style: const TextStyle(color: Colors.white, fontSize: 24, letterSpacing: 16),
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.white.withOpacity(0.9)),
        counterText: '',
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
        if (v.length == 4 && next != null) next.requestFocus();
      },
    );
  }
}
