import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Lokal PIN qulf — 4-raqamli PIN ni xavfsiz saqlash va tekshirish.
/// Saqlash: flutter_secure_storage (Android Keystore / iOS Keychain).
/// Hash: SHA-256(salt + pin), salt har qurilmada bir marta yaratiladi.
class PinService {
  static const _kPinHash = 'pin_hash_v1';
  static const _kPinSalt = 'pin_salt_v1';
  static const _kFailCount = 'pin_fail_count_v1';
  static const _kLockUntil = 'pin_lock_until_v1';

  static const int maxFailBeforeLock = 5;
  static const int maxFailBeforeWipe = 10;
  static const int lockSeconds = 60;

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  /// PIN o'rnatilganmi?
  Future<bool> hasPin() async {
    final h = await _storage.read(key: _kPinHash);
    return h != null && h.isNotEmpty;
  }

  /// PIN o'rnatish (yoki almashtirish).
  Future<void> setPin(String pin) async {
    final salt = _newSalt();
    final hash = _hash(salt, pin);
    await _storage.write(key: _kPinSalt, value: salt);
    await _storage.write(key: _kPinHash, value: hash);
    await _storage.delete(key: _kFailCount);
    await _storage.delete(key: _kLockUntil);
  }

  /// PIN ni tekshirish. Natija: VerifyResult.
  Future<PinVerifyResult> verifyPin(String pin) async {
    // Lock muddati tekshirish
    final lockUntilStr = await _storage.read(key: _kLockUntil);
    if (lockUntilStr != null && lockUntilStr.isNotEmpty) {
      final lockUntil = DateTime.tryParse(lockUntilStr);
      if (lockUntil != null && DateTime.now().isBefore(lockUntil)) {
        final left = lockUntil.difference(DateTime.now()).inSeconds;
        return PinVerifyResult.locked(left);
      }
    }

    final salt = await _storage.read(key: _kPinSalt);
    final saved = await _storage.read(key: _kPinHash);
    if (salt == null || saved == null) {
      return PinVerifyResult.notSet();
    }
    final attempt = _hash(salt, pin);
    if (attempt == saved) {
      await _storage.delete(key: _kFailCount);
      await _storage.delete(key: _kLockUntil);
      return PinVerifyResult.ok();
    }
    // Xato urinish
    final cntStr = await _storage.read(key: _kFailCount);
    final cnt = (int.tryParse(cntStr ?? '0') ?? 0) + 1;
    await _storage.write(key: _kFailCount, value: cnt.toString());
    if (cnt >= maxFailBeforeWipe) {
      await clearPin();
      return PinVerifyResult.wiped();
    }
    if (cnt >= maxFailBeforeLock) {
      final until = DateTime.now().add(const Duration(seconds: lockSeconds));
      await _storage.write(key: _kLockUntil, value: until.toIso8601String());
      return PinVerifyResult.locked(lockSeconds);
    }
    return PinVerifyResult.wrong(maxFailBeforeWipe - cnt);
  }

  /// PIN va shu bilan bog'liq ma'lumotlarni o'chirish.
  Future<void> clearPin() async {
    await _storage.delete(key: _kPinHash);
    await _storage.delete(key: _kPinSalt);
    await _storage.delete(key: _kFailCount);
    await _storage.delete(key: _kLockUntil);
  }

  String _newSalt() {
    final r = Random.secure();
    final bytes = List<int>.generate(16, (_) => r.nextInt(256));
    return base64Url.encode(bytes);
  }

  String _hash(String salt, String pin) {
    final input = utf8.encode('$salt:$pin');
    return sha256.convert(input).toString();
  }
}

class PinVerifyResult {
  final PinVerifyStatus status;
  final int? lockSecondsLeft;
  final int? attemptsLeft;

  PinVerifyResult._(this.status, {this.lockSecondsLeft, this.attemptsLeft});

  factory PinVerifyResult.ok() => PinVerifyResult._(PinVerifyStatus.ok);
  factory PinVerifyResult.wrong(int left) =>
      PinVerifyResult._(PinVerifyStatus.wrong, attemptsLeft: left);
  factory PinVerifyResult.locked(int secondsLeft) =>
      PinVerifyResult._(PinVerifyStatus.locked, lockSecondsLeft: secondsLeft);
  factory PinVerifyResult.wiped() => PinVerifyResult._(PinVerifyStatus.wiped);
  factory PinVerifyResult.notSet() => PinVerifyResult._(PinVerifyStatus.notSet);
}

enum PinVerifyStatus { ok, wrong, locked, wiped, notSet }
