import 'package:flutter/material.dart';

import '../services/api_service.dart';
import 'spectrum_project_detail_screen.dart';

class SpectrumProjectsHomeScreen extends StatefulWidget {
  const SpectrumProjectsHomeScreen({super.key});

  @override
  State<SpectrumProjectsHomeScreen> createState() =>
      _SpectrumProjectsHomeScreenState();
}

class _SpectrumProjectsHomeScreenState extends State<SpectrumProjectsHomeScreen> {
  final ApiService _api = ApiService();
  final TextEditingController _filter = TextEditingController();
  List<String> _projects = [];
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _filter.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final r = await _api.listSpectrumProjects();
    if (!mounted) return;
    if (!r.success || r.data == null) {
      setState(() {
        _loading = false;
        _error = r.message;
        _projects = [];
      });
      return;
    }
    setState(() {
      _loading = false;
      _projects = r.data!;
    });
  }

  List<String> get _filtered {
    final q = _filter.text.trim().toLowerCase();
    if (q.isEmpty) return _projects;
    return _projects.where((p) => p.toLowerCase().contains(q)).toList();
  }

  Future<void> _createProject() async {
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建项目'),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(
            labelText: '项目名称',
            hintText: '仅支持文件夹名，勿含 / \\ ..',
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('创建'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final name = ctrl.text.trim();
    if (name.isEmpty) return;
    final r = await _api.createSpectrumProject(name);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(r.success ? '已创建 $name' : r.message),
      ),
    );
    if (r.success) await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '光谱项目',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: _load,
                tooltip: '刷新',
              ),
              FilledButton.icon(
                onPressed: _createProject,
                icon: const Icon(Icons.add),
                label: const Text('新建项目'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _filter,
            decoration: const InputDecoration(
              labelText: '检索项目',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),
          if (_loading)
            const Center(child: CircularProgressIndicator())
          else if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            )
          else
            Expanded(
              child: ListView.builder(
                itemCount: _filtered.length,
                itemBuilder: (context, i) {
                  final name = _filtered[i];
                  return Card(
                    child: ListTile(
                      title: Text(name),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () {
                        Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => SpectrumProjectDetailScreen(
                              projectName: name,
                            ),
                          ),
                        );
                      },
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
