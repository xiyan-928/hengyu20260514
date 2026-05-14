import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/spectrum_provider.dart';
import '../services/api_service.dart';

class SpectrumSettingsScreen extends StatefulWidget {
  const SpectrumSettingsScreen({super.key});

  @override
  State<SpectrumSettingsScreen> createState() => _SpectrumSettingsScreenState();
}

class _SpectrumSettingsScreenState extends State<SpectrumSettingsScreen> {
  final ApiService _api = ApiService();

  Map<String, dynamic>? _modes;
  String _projectRoot = '';

  final TextEditingController _host = TextEditingController();
  final TextEditingController _port = TextEditingController();
  final TextEditingController _unit = TextEditingController();
  final TextEditingController _addr = TextEditingController();
  String _lightMode = 'mock';

  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    _unit.dispose();
    _addr.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    final m = await _api.getDeviceModes();
    final r = await _api.getProjectRoot();
    final lc = await _api.getLightSourceConfig();
    if (!mounted) return;
    if (m.success && m.data != null) {
      _modes = m.data;
    }
    if (r.success && r.data != null) {
      _projectRoot = r.data!;
    }
    if (lc.success && lc.data != null) {
      final ls = lc.data!;
      _host.text = '${ls['host'] ?? '127.0.0.1'}';
      _port.text = '${ls['port'] ?? 502}';
      _unit.text = '${ls['unit'] ?? 1}';
      _addr.text = '${ls['address'] ?? 0}';
      _lightMode = '${ls['mode'] ?? 'mock'}'.toLowerCase();
      if (_lightMode != 'mock' && _lightMode != 'real') {
        _lightMode = 'mock';
      }
    }
    setState(() => _loading = false);
  }

  Future<void> _pickRoot() async {
    final path = await FilePicker.platform.getDirectoryPath();
    if (path == null) return;
    final r = await _api.setProjectRoot(path);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(r.success ? '已设置: $path' : r.message)),
    );
    if (r.success) setState(() => _projectRoot = r.data ?? path);
  }

  /// 光源表单：加大行高与边距，避免标签与文字挤叠。
  InputDecoration _lightInputDecoration(String label) {
    return InputDecoration(
      labelText: label,
      isDense: false,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 18),
      border: const OutlineInputBorder(),
    );
  }

  Future<void> _saveLight() async {
    final r = await _api.updateLightSourceConfig({
      'mode': _lightMode,
      'host': _host.text.trim(),
      'port': int.tryParse(_port.text) ?? 502,
      'unit': int.tryParse(_unit.text) ?? 1,
      'address': int.tryParse(_addr.text) ?? 0,
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(r.success ? '光源配置已保存' : r.message)),
    );
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final sp = context.watch<SpectrumProvider>();

    return Padding(
      padding: const EdgeInsets.all(24),
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                const Text(
                  '设置',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 16),
                if (_modes != null) ...[
                  Card(
                    child: ListTile(
                      title: const Text('设备模式'),
                      subtitle: Text(
                        '光谱仪: ${(_modes!['cds350Mock'] == true) ? "模拟" : "真实"}  ·  '
                        '光源: ${(_modes!['lightSourceMock'] == true) ? "模拟" : "真实"}',
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('项目根目录（所有项目子文件夹）'),
                        const SizedBox(height: 8),
                        Text(
                          _projectRoot.isEmpty ? '未设置' : _projectRoot,
                          style: TextStyle(color: Colors.grey.shade800),
                        ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: _pickRoot,
                          icon: const Icon(Icons.folder_open),
                          label: const Text('选择目录'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('光源 Modbus（线圈）'),
                        const SizedBox(height: 12),
                        DropdownButtonFormField<String>(
                          value: _lightMode,
                          isExpanded: true,
                          decoration: _lightInputDecoration('模式'),
                          items: const [
                            DropdownMenuItem(value: 'mock', child: Text('模拟')),
                            DropdownMenuItem(value: 'real', child: Text('真实')),
                          ],
                          onChanged: (v) {
                            if (v != null) setState(() => _lightMode = v);
                          },
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _host,
                          decoration: _lightInputDecoration('IP'),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _port,
                          decoration: _lightInputDecoration('端口'),
                          keyboardType: TextInputType.number,
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _unit,
                          decoration: _lightInputDecoration('Unit'),
                          keyboardType: TextInputType.number,
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _addr,
                          decoration: _lightInputDecoration('线圈地址'),
                          keyboardType: TextInputType.number,
                        ),
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: _saveLight,
                          child: const Text('保存光源配置'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('CDS350 光谱仪'),
                        const SizedBox(height: 8),
                        Text('状态: ${sp.status}  已初始化: ${sp.isInitialized}'),
                        const SizedBox(height: 8),
                        FilledButton(
                          onPressed: () async {
                            final ok = await sp.initializeDevice();
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    ok ? '已初始化' : sp.status,
                                  ),
                                ),
                              );
                            }
                          },
                          child: const Text('初始化 CDS350'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                TextButton.icon(
                  onPressed: _refresh,
                  icon: const Icon(Icons.refresh),
                  label: const Text('刷新状态'),
                ),
              ],
            ),
    );
  }
}
