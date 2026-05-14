import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/spectrum_data.dart';
import '../providers/spectrum_provider.dart';
import '../services/api_service.dart';
import '../widgets/spectrum_chart.dart';

class SpectrumProjectDetailScreen extends StatefulWidget {
  const SpectrumProjectDetailScreen({super.key, required this.projectName});

  final String projectName;

  @override
  State<SpectrumProjectDetailScreen> createState() =>
      _SpectrumProjectDetailScreenState();
}

class _SpectrumProjectDetailScreenState extends State<SpectrumProjectDetailScreen> {
  final ApiService _api = ApiService();

  final List<TextEditingController> _dyeNameCtrls = [];
  final List<TextEditingController> _dyeRatioCtrls = [];
  final TextEditingController _fabricG = TextEditingController(text: '0');
  final TextEditingController _bathRatio = TextEditingController(text: '0');

  bool _loadingMeta = true;

  /// 各类别在本页内最近一次成功采集的光谱（仅内存展示，空则不显示图表）。
  final Map<String, SpectrumData?> _lastSpectrumByCategory = {};

  final TextEditingController _itCtrl = TextEditingController();
  final TextEditingController _avgCtrl = TextEditingController();
  bool _syncedInstrumentFields = false;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    await Future.wait([_loadMeta(), _loadSavedSpectra()]);
  }

  Future<void> _loadSavedSpectra() async {
    final r = await _api.getProjectSavedSpectra(widget.projectName);
    if (!mounted || !r.success || r.data == null) {
      return;
    }
    final raw = r.data!;
    setState(() {
      _lastSpectrumByCategory.clear();
      for (final cat in const ['dark', 'water', 'stock', 'residual']) {
        final e = raw[cat];
        if (e is! Map) {
          continue;
        }
        final wl = (e['wavelengths'] as List?)
                ?.map((x) => (x as num).toDouble())
                .toList() ??
            <double>[];
        final sp = (e['spectrum'] as List?)
                ?.map((x) => (x as num).round())
                .toList() ??
            <int>[];
        if (wl.isEmpty || sp.isEmpty) {
          continue;
        }
        final it = (e['integration_time'] as num?)?.toInt() ?? 10000;
        final avg = (e['scans_to_average'] as num?)?.toInt() ?? 3;
        _lastSpectrumByCategory[cat] = SpectrumData(
          wavelengths: wl,
          intensities: sp,
          timestamp: DateTime.now(),
          length: wl.length,
          integrationTime: it,
          scansToAverage: avg,
        );
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_syncedInstrumentFields) {
      _syncedInstrumentFields = true;
      final sp = context.read<SpectrumProvider>();
      _itCtrl.text = '${sp.integrationTime}';
      _avgCtrl.text = '${sp.scansToAverage}';
    }
  }

  @override
  void dispose() {
    _itCtrl.dispose();
    _avgCtrl.dispose();
    for (final c in _dyeNameCtrls) {
      c.dispose();
    }
    for (final c in _dyeRatioCtrls) {
      c.dispose();
    }
    _fabricG.dispose();
    _bathRatio.dispose();
    super.dispose();
  }

  Future<void> _loadMeta() async {
    final r = await _api.getProjectMeta(widget.projectName);
    if (!mounted) return;
    if (!r.success || r.data == null) {
      setState(() => _loadingMeta = false);
      return;
    }
    final dyes = (r.data!['dyes'] as List?) ?? [];
    for (final c in _dyeNameCtrls) {
      c.dispose();
    }
    for (final c in _dyeRatioCtrls) {
      c.dispose();
    }
    _dyeNameCtrls.clear();
    _dyeRatioCtrls.clear();
    for (final d in dyes) {
      if (d is Map) {
        _dyeNameCtrls.add(TextEditingController(text: '${d['name'] ?? ''}'));
        _dyeRatioCtrls
            .add(TextEditingController(text: '${d['ratio'] ?? 0}'));
      }
    }
    if (_dyeNameCtrls.isEmpty) {
      _dyeNameCtrls.add(TextEditingController());
      _dyeRatioCtrls.add(TextEditingController(text: '0'));
    }
    final fw = r.data!['fabric_weight_g'];
    final br = r.data!['bath_ratio'];
    _fabricG.text = fw != null ? '$fw' : '0';
    _bathRatio.text = br != null ? '$br' : '0';
    setState(() => _loadingMeta = false);
  }

  void _addDyeRow() {
    setState(() {
      _dyeNameCtrls.add(TextEditingController());
      _dyeRatioCtrls.add(TextEditingController(text: '0'));
    });
  }

  void _removeDyeRow(int i) {
    if (_dyeNameCtrls.length <= 1) return;
    setState(() {
      _dyeNameCtrls[i].dispose();
      _dyeRatioCtrls[i].dispose();
      _dyeNameCtrls.removeAt(i);
      _dyeRatioCtrls.removeAt(i);
    });
  }

  Future<void> _saveMeta() async {
    final dyes = <Map<String, dynamic>>[];
    for (var i = 0; i < _dyeNameCtrls.length; i++) {
      final ratio = double.tryParse(_dyeRatioCtrls[i].text) ?? 0;
      dyes.add({
        'name': _dyeNameCtrls[i].text.trim(),
        'ratio': ratio,
      });
    }
    final fw = double.tryParse(_fabricG.text) ?? 0;
    final br = double.tryParse(_bathRatio.text) ?? 0;
    final r = await _api.putProjectMeta(
      widget.projectName,
      dyes: dyes,
      fabricWeightG: fw,
      bathRatio: br,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(r.success ? '已保存 meta（xlsx）' : r.message)),
    );
  }

  Future<void> _runCategory({
    required String category,
    required bool lightOn,
    required String hint,
  }) async {
    final sp = context.read<SpectrumProvider>();
    if (!sp.isInitialized) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请先在「设置」中初始化 CDS350')),
      );
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('确认采集'),
        content: Text(hint),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('开始'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final w = ScaffoldMessenger.of(context);
    try {
      final wr = await _api.writeLightCoil(lightOn);
      if (!wr.success) {
        w.showSnackBar(SnackBar(content: Text('光源线圈失败: ${wr.message}')));
        return;
      }
      await Future<void>.delayed(const Duration(seconds: 2));
      await sp.applyConfiguration();
      final fr = await sp.fetchSpectrum(forceNew: true);
      if (!fr) {
        w.showSnackBar(SnackBar(content: Text(sp.status)));
        return;
      }
      final captured = sp.currentSpectrum;
      if (captured != null &&
          captured.wavelengths.isNotEmpty &&
          captured.intensities.isNotEmpty) {
        setState(() {
          _lastSpectrumByCategory[category] = captured;
        });
      }
      final sr = await _api.saveProjectSpectrum(widget.projectName, category);
      if (!mounted) return;
      w.showSnackBar(
        SnackBar(
          content: Text(
            sr.success
                ? '已保存: ${sr.data?['file_name'] ?? category}'
                : sr.message,
          ),
        ),
      );
    } catch (e) {
      w.showSnackBar(SnackBar(content: Text('异常: $e')));
    }
  }

  Widget _section({
    required String title,
    required String category,
    required bool lightOn,
    required String userHint,
    required String techHint,
  }) {
    final last = _lastSpectrumByCategory[category];
    final hasChart = last != null &&
        last.wavelengths.isNotEmpty &&
        last.intensities.isNotEmpty;

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(userHint, style: TextStyle(color: Colors.grey.shade800)),
            Text(techHint, style: TextStyle(color: Colors.grey.shade600, fontSize: 12)),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: () => _runCategory(
                category: category,
                lightOn: lightOn,
                hint: '$userHint\n$techHint',
              ),
              child: const Text('开始采集并保存 SPC'),
            ),
            if (hasChart) ...[
              const SizedBox(height: 16),
              Text(
                '本组最近一次采集',
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const SizedBox(height: 8),
              SizedBox(
                height: 220,
                child: SpectrumChart(
                  spectrumData: last,
                  height: 200,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sp = context.watch<SpectrumProvider>();
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.projectName),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '仪器参数（积分时间 μs、平均次数）',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _itCtrl,
                    decoration: const InputDecoration(
                      labelText: '积分时间 (μs)',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: _avgCtrl,
                    decoration: const InputDecoration(
                      labelText: '平均次数',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.check),
                  tooltip: '应用参数',
                  onPressed: () async {
                    final it = int.tryParse(_itCtrl.text);
                    final av = int.tryParse(_avgCtrl.text);
                    if (it != null) sp.setIntegrationTime(it);
                    if (av != null) sp.setScansToAverage(av);
                    await sp.applyConfiguration();
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('参数已下发')),
                      );
                    }
                  },
                ),
              ],
            ),
            const Divider(height: 32),
            const Text(
              '光谱组',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            _section(
              title: '暗光谱',
              category: 'dark',
              lightOn: false,
              userHint: '请确认关闭光源后探头就绪。',
              techHint: 'Modbus 关光源 → 等待 2s → 采集 → 保存 SPC。',
            ),
            _section(
              title: '清水光谱',
              category: 'water',
              lightOn: true,
              userHint: '请将探头放入清水中。',
              techHint: 'Modbus 开光源 → 等待 2s → 采集 → 保存 SPC。',
            ),
            _section(
              title: '打样原液光谱',
              category: 'stock',
              lightOn: true,
              userHint: '请将探头放入打样原液中。',
              techHint: 'Modbus 开光源 → 等待 2s → 采集 → 保存 SPC。',
            ),
            _section(
              title: '打样残液光谱',
              category: 'residual',
              lightOn: true,
              userHint: '请将探头放入打样残液中。',
              techHint: 'Modbus 开光源 → 等待 2s → 采集 → 保存 SPC。',
            ),
            const Divider(height: 32),
            const Text(
              'Meta 信息',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            if (_loadingMeta)
              const Center(child: CircularProgressIndicator())
            else ...[
              const Text('染料组合（保存为 染料信息.xlsx）'),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: const [
                    DataColumn(label: Text('染料名称')),
                    DataColumn(label: Text('比例')),
                    DataColumn(label: Text('')),
                  ],
                  rows: [
                    for (var i = 0; i < _dyeNameCtrls.length; i++)
                      DataRow(
                        cells: [
                          DataCell(
                            TextField(controller: _dyeNameCtrls[i]),
                          ),
                          DataCell(
                            TextField(
                              controller: _dyeRatioCtrls[i],
                              keyboardType:
                                  const TextInputType.numberWithOptions(decimal: true),
                            ),
                          ),
                          DataCell(
                            IconButton(
                              icon: const Icon(Icons.delete_outline),
                              onPressed: () => _removeDyeRow(i),
                            ),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
              TextButton.icon(
                onPressed: _addDyeRow,
                icon: const Icon(Icons.add),
                label: const Text('添加染料行'),
              ),
              const SizedBox(height: 16),
              const Text('浴比与布重（保存为 浴比布重.xlsx）'),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _fabricG,
                      decoration: const InputDecoration(
                        labelText: '布重 (g)',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: TextField(
                      controller: _bathRatio,
                      decoration: const InputDecoration(
                        labelText: '浴比(布重/染液)',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _saveMeta,
                icon: const Icon(Icons.save),
                label: const Text('保存 Meta 到 xlsx'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
