import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:geolocator/geolocator.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';

/// Vizit davomida rasmlar olish ekrani.
/// Foydalanuvchi faqat kameradan rasm oladi (galereyaga kirish yo'q).
class VisitPhotoScreen extends StatefulWidget {
  final int visitId;
  final String partnerName;

  const VisitPhotoScreen({
    super.key,
    required this.visitId,
    required this.partnerName,
  });

  @override
  State<VisitPhotoScreen> createState() => _VisitPhotoScreenState();
}

class _VisitPhotoScreenState extends State<VisitPhotoScreen> {
  final ImagePicker _picker = ImagePicker();
  final SessionService _session = SessionService();

  final List<_LocalPhoto> _photos = [];
  bool _isUploading = false;

  static const Map<String, _PhotoTypeInfo> _types = {
    'shelf': _PhotoTypeInfo('Prilavka', Icons.storefront, Colors.orange),
    'warehouse': _PhotoTypeInfo('Qoldiq', Icons.inventory_2, Colors.blue),
    'storefront': _PhotoTypeInfo('Do\'kon fasadi', Icons.house, Colors.purple),
    'other': _PhotoTypeInfo('Boshqa', Icons.add_a_photo, Colors.grey),
  };

  Future<void> _takePhoto(String type) async {
    try {
      // image_picker ichki compress qiladi (maxWidth + imageQuality)
      final xfile = await _picker.pickImage(
        source: ImageSource.camera,
        imageQuality: 70,
        maxWidth: 1280,
        maxHeight: 1280,
        preferredCameraDevice: CameraDevice.rear,
      );
      if (xfile == null) return;

      final size = await File(xfile.path).length();

      if (!mounted) return;
      setState(() {
        _photos.add(_LocalPhoto(
          path: xfile.path,
          type: type,
          sizeBytes: size,
        ));
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Kamera xato: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _editNote(int index) async {
    final p = _photos[index];
    final controller = TextEditingController(text: p.notes);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_types[p.type]?.label ?? 'Izoh'),
        content: TextField(
          controller: controller,
          maxLines: 3,
          autofocus: true,
          decoration: const InputDecoration(
            hintText: 'Rasm izohi (ixtiyoriy)',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('OK'),
          ),
        ],
      ),
    );
    if (result != null && mounted) {
      setState(() => _photos[index].notes = result);
    }
  }

  void _removePhoto(int index) {
    setState(() => _photos.removeAt(index));
  }

  Future<void> _upload() async {
    if (_photos.isEmpty) {
      Navigator.pop(context, 0);
      return;
    }
    setState(() => _isUploading = true);

    final token = await _session.getToken();
    if (token == null) {
      setState(() => _isUploading = false);
      return;
    }

    Position? pos;
    try {
      pos = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 5),
      );
    } catch (_) {}

    int uploaded = 0;
    int failed = 0;
    for (final p in _photos) {
      final result = await ApiService.uploadVisitPhoto(
        token,
        visitId: widget.visitId,
        filePath: p.path,
        photoType: p.type,
        notes: p.notes,
        latitude: pos?.latitude,
        longitude: pos?.longitude,
      );
      if (result['success'] == true) {
        uploaded++;
      } else {
        failed++;
      }
    }

    if (!mounted) return;
    setState(() => _isUploading = false);
    if (failed == 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$uploaded ta rasm yuklandi'), backgroundColor: Colors.green),
      );
      Navigator.pop(context, uploaded);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Yuklandi: $uploaded, xato: $failed'),
          backgroundColor: failed > uploaded ? Colors.red : Colors.orange,
        ),
      );
      if (uploaded > 0) {
        Navigator.pop(context, uploaded);
      }
    }
  }

  Future<bool> _confirmExit() async {
    if (_photos.isEmpty) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rasmlar saqlanmagan'),
        content: const Text('Olingan rasmlar yuklanmagan. Chiqib ketasizmi?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Qolish')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Chiqish', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    return ok == true;
  }

  String _fmtSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} KB';
    return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _photos.isEmpty,
      onPopInvoked: (didPop) async {
        if (!didPop) {
          final ok = await _confirmExit();
          if (ok && mounted) Navigator.pop(context, 0);
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(widget.partnerName, style: const TextStyle(fontSize: 15)),
          backgroundColor: const Color(0xFF017449),
          foregroundColor: Colors.white,
        ),
        body: Column(
          children: [
            Container(
              color: Colors.orange.shade50,
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Icon(Icons.camera_alt, color: Colors.orange.shade700),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'Vizit rasmlarini oling. Prilavka, qoldiq va do\'kon fasadini suratga tushiring.',
                      style: TextStyle(fontSize: 12),
                    ),
                  ),
                ],
              ),
            ),
            // Rasm turi tugmalari
            Padding(
              padding: const EdgeInsets.all(12),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _types.entries.map((e) {
                  final count = _photos.where((p) => p.type == e.key).length;
                  return ElevatedButton.icon(
                    onPressed: _isUploading ? null : () => _takePhoto(e.key),
                    icon: Icon(e.value.icon, size: 18),
                    label: Text('${e.value.label}${count > 0 ? " ($count)" : ""}'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: e.value.color.withOpacity(count > 0 ? 0.85 : 1.0),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    ),
                  );
                }).toList(),
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: _photos.isEmpty
                  ? const Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.photo_camera, size: 64, color: Colors.grey),
                          SizedBox(height: 12),
                          Text('Hali rasm olinmagan', style: TextStyle(color: Colors.grey)),
                        ],
                      ),
                    )
                  : GridView.builder(
                      padding: const EdgeInsets.all(12),
                      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: 2,
                        crossAxisSpacing: 8,
                        mainAxisSpacing: 8,
                        childAspectRatio: 0.85,
                      ),
                      itemCount: _photos.length,
                      itemBuilder: (ctx, i) => _buildPhotoCard(i),
                    ),
            ),
            if (_photos.isNotEmpty)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.white,
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 6, offset: const Offset(0, -2))],
                ),
                child: SafeArea(
                  top: false,
                  child: Row(children: [
                    Expanded(
                      child: Text(
                        '${_photos.length} ta rasm',
                        style: const TextStyle(fontSize: 14, color: Colors.black54),
                      ),
                    ),
                    ElevatedButton.icon(
                      onPressed: _isUploading ? null : _upload,
                      icon: _isUploading
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          : const Icon(Icons.cloud_upload, size: 18),
                      label: Text(_isUploading ? 'Yuklanmoqda...' : 'Yuklash'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF017449),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
                      ),
                    ),
                  ]),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildPhotoCard(int i) {
    final p = _photos[i];
    final info = _types[p.type]!;
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: Image.file(File(p.path), fit: BoxFit.cover),
          ),
          Positioned(
            top: 4,
            left: 4,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              decoration: BoxDecoration(color: info.color, borderRadius: BorderRadius.circular(10)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(info.icon, size: 11, color: Colors.white),
                const SizedBox(width: 3),
                Text(info.label, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w600)),
              ]),
            ),
          ),
          Positioned(
            top: 4,
            right: 4,
            child: InkWell(
              onTap: () => _removePhoto(i),
              child: Container(
                padding: const EdgeInsets.all(3),
                decoration: const BoxDecoration(color: Colors.black54, shape: BoxShape.circle),
                child: const Icon(Icons.close, size: 14, color: Colors.white),
              ),
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: InkWell(
              onTap: () => _editNote(i),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                color: Colors.black54,
                child: Row(children: [
                  Expanded(
                    child: Text(
                      p.notes.isEmpty ? 'Izoh qo\'shish...' : p.notes,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: p.notes.isEmpty ? Colors.white70 : Colors.white,
                        fontSize: 11,
                        fontStyle: p.notes.isEmpty ? FontStyle.italic : FontStyle.normal,
                      ),
                    ),
                  ),
                  Text(
                    _fmtSize(p.sizeBytes),
                    style: const TextStyle(color: Colors.white60, fontSize: 9),
                  ),
                ]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _LocalPhoto {
  final String path;
  final String type;
  String notes;
  final int sizeBytes;
  _LocalPhoto({required this.path, required this.type, this.notes = '', required this.sizeBytes});
}

class _PhotoTypeInfo {
  final String label;
  final IconData icon;
  final Color color;
  const _PhotoTypeInfo(this.label, this.icon, this.color);
}
