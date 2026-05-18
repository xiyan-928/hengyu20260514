import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:provider/provider.dart';
import '../providers/spectrum_provider.dart';
import '../services/settings_service.dart';
import '../services/file_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final SettingsService _settingsService = SettingsService();
  final _formKey = GlobalKey<FormState>();
  
  late TextEditingController _integrationTimeController;
  late TextEditingController _scansToAverageController;
  late TextEditingController _customDirectoryController;
  late TextEditingController _spectrumQueryIntervalController;
  
  bool _useCustomDirectory = false;
  SpectrumFileFormat _selectedFileFormat = SpectrumFileFormat.spc;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _integrationTimeController = TextEditingController();
    _scansToAverageController = TextEditingController();
    _customDirectoryController = TextEditingController();
    _spectrumQueryIntervalController = TextEditingController();
    _loadSettings();
  }

  @override
  void dispose() {
    _integrationTimeController.dispose();
    _scansToAverageController.dispose();
    _customDirectoryController.dispose();
    _spectrumQueryIntervalController.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    final integrationTime = await _settingsService.getIntegrationTime();
    final scansToAverage = await _settingsService.getScansToAverage();
    final spectrumQueryInterval = await _settingsService.getSpectrumQueryInterval();
    final useCustomDirectory = await _settingsService.getUseCustomDirectory();
    final customDirectory = await _settingsService.getCustomDirectory();
    final fileFormat = await _settingsService.getSpectrumFileFormat();

    setState(() {
      _integrationTimeController.text = integrationTime.toString();
      _scansToAverageController.text = scansToAverage.toString();
      _spectrumQueryIntervalController.text = spectrumQueryInterval.toString();
      _useCustomDirectory = useCustomDirectory;
      _customDirectoryController.text = customDirectory ?? '';
      _selectedFileFormat = fileFormat;
      _isLoading = false;
    });
  }

  Future<void> _saveSettings() async {
    if (!_formKey.currentState!.validate()) return;

    final integrationTime = int.parse(_integrationTimeController.text);
    final scansToAverage = int.parse(_scansToAverageController.text);
    final spectrumQueryInterval = int.parse(_spectrumQueryIntervalController.text);

    await _settingsService.setIntegrationTime(integrationTime);
    await _settingsService.setScansToAverage(scansToAverage);
    await _settingsService.setSpectrumQueryInterval(spectrumQueryInterval);
    await _settingsService.setUseCustomDirectory(_useCustomDirectory);
    await _settingsService.setSpectrumFileFormat(_selectedFileFormat);

    if (_useCustomDirectory && _customDirectoryController.text.isNotEmpty) {
      await _settingsService.setCustomDirectory(_customDirectoryController.text);
    }

    // Update the spectrum provider with new settings
    if (mounted) {
      final spectrumProvider = Provider.of<SpectrumProvider>(context, listen: false);
      spectrumProvider.integrationTime = integrationTime;
      spectrumProvider.scansToAverage = scansToAverage;
      spectrumProvider.collectionInterval = spectrumQueryInterval * 1000; // Convert to milliseconds
    }

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('设置已成功保存'),
        backgroundColor: Colors.green,
      ),
    );
  }

  Future<void> _selectDirectory() async {
    try {
      String? selectedDirectory = await FilePicker.platform.getDirectoryPath();
      
      if (selectedDirectory != null && selectedDirectory.isNotEmpty) {
        setState(() {
          _customDirectoryController.text = selectedDirectory;
        });
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('选择目录时出错: $e'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text('设置'),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black87,
        elevation: 1,
        actions: [
          TextButton.icon(
            onPressed: _saveSettings,
            icon: const Icon(Icons.save),
            label: const Text('保存'),
          ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // CDS350 Configuration Section
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '光谱仪设置',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 16),
                        
                        // Integration Time
                        TextFormField(
                          controller: _integrationTimeController,
                          decoration: const InputDecoration(
                            labelText: '积分时间 (μs)',
                            hintText: '输入积分时间（微秒）',
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                          inputFormatters: [
                            FilteringTextInputFormatter.digitsOnly,
                          ],
                          validator: (value) {
                            if (value == null || value.isEmpty) {
                              return '请输入积分时间';
                            }
                            final intValue = int.tryParse(value);
                            if (intValue == null || intValue <= 0) {
                              return '请输入有效的正整数';
                            }
                            if (intValue < 1000 || intValue > 1000000) {
                              return '积分时间应在 1000 到 1000000 μs 之间';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        
                        // Scans to Average
                        TextFormField(
                          controller: _scansToAverageController,
                          decoration: const InputDecoration(
                            labelText: '平均扫描次数',
                            hintText: '输入平均扫描次数',
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                          inputFormatters: [
                            FilteringTextInputFormatter.digitsOnly,
                          ],
                          validator: (value) {
                            if (value == null || value.isEmpty) {
                              return '请输入平均扫描次数';
                            }
                            final intValue = int.tryParse(value);
                            if (intValue == null || intValue <= 0) {
                              return '请输入有效的正整数';
                            }
                            if (intValue < 1 || intValue > 100) {
                              return '平均扫描次数应在 1 到 100 之间';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        
                        // Spectrum Query Interval
                        TextFormField(
                          controller: _spectrumQueryIntervalController,
                          decoration: const InputDecoration(
                            labelText: '光谱查询间隔 (s)',
                            hintText: '输入光谱查询间隔（单位：秒）',
                            helperText:
                                '仅影响本机 App 轮询；上报 SPC 间隔由 HY_Online device_config 配置',
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                          inputFormatters: [
                            FilteringTextInputFormatter.digitsOnly,
                          ],
                          validator: (value) {
                            if (value == null || value.isEmpty) {
                              return '请输入光谱查询间隔';
                            }
                            final intValue = int.tryParse(value);
                            if (intValue == null || intValue <= 0) {
                              return '请输入有效的正整数';
                            }
                            if (intValue < 1 || intValue > 300) {
                              return '查询间隔应该在1到300秒之间';
                            }
                            return null;
                          },
                        ),
                      ],
                    ),
                  ),
                ),
                
                const SizedBox(height: 16),
                
                // File Format Section
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '光谱文件格式',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 16),
                        
                        // File Format Selection
                        Column(
                          children: [
                            RadioListTile<SpectrumFileFormat>(
                              title: const Text('SPC 格式'),
                              subtitle: const Text('标准二进制格式（推荐）'),
                              value: SpectrumFileFormat.spc,
                              groupValue: _selectedFileFormat,
                              onChanged: (value) {
                                setState(() {
                                  _selectedFileFormat = value!;
                                });
                              },
                            ),
                            RadioListTile<SpectrumFileFormat>(
                              title: const Text('CSV 格式'),
                              subtitle: const Text('逗号分隔值（可读性好）'),
                              value: SpectrumFileFormat.csv,
                              groupValue: _selectedFileFormat,
                              onChanged: (value) {
                                setState(() {
                                  _selectedFileFormat = value!;
                                });
                              },
                            ),
                          ],
                        ),
                        
                        // Format Description
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Colors.blue[50],
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Row(
                            children: [
                              Icon(Icons.info_outline, color: Colors.blue[700]),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _selectedFileFormat == SpectrumFileFormat.spc
                                      ? 'SPC 格式是光谱数据的工业标准，兼容大多数分析软件。'
                                      : 'CSV 格式提供可读的文本文件，可用 Excel 打开。',
                                  style: TextStyle(
                                    color: Colors.blue[700],
                                    fontSize: 13,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                
                const SizedBox(height: 16),
                
                // Data Storage Section
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '数据存储',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 16),
                        
                        // Custom Directory Toggle
                        SwitchListTile(
                          title: const Text('使用自定义目录'),
                          subtitle: const Text('选择保存数据文件的自定义位置'),
                          value: _useCustomDirectory,
                          onChanged: (value) {
                            setState(() {
                              _useCustomDirectory = value;
                            });
                          },
                        ),
                        
                        // Custom Directory Selection
                        if (_useCustomDirectory) ...[
                          const SizedBox(height: 16),
                          Row(
                            children: [
                              Expanded(
                                child: TextFormField(
                                  controller: _customDirectoryController,
                                  decoration: const InputDecoration(
                                    labelText: '自定义目录路径',
                                    hintText: '选择目录',
                                    border: OutlineInputBorder(),
                                  ),
                                  readOnly: true,
                                  validator: _useCustomDirectory
                                      ? (value) {
                                          if (value == null || value.isEmpty) {
                                            return '请选择一个目录';
                                          }
                                          return null;
                                        }
                                      : null,
                                ),
                              ),
                              const SizedBox(width: 8),
                              ElevatedButton.icon(
                                onPressed: _selectDirectory,
                                icon: const Icon(Icons.folder_open),
                                label: const Text('浏览'),
                              ),
                            ],
                          ),
                        ],
                        
                        if (!_useCustomDirectory) ...[
                          const SizedBox(height: 16),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Colors.grey[100],
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: const Row(
                              children: [
                                Icon(Icons.info_outline, color: Colors.blue),
                                SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    '数据将保存到默认的 Documents/HY_Data 目录',
                                    style: TextStyle(color: Colors.black87),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                
                // Device Configuration Section
                // const SizedBox(height: 16),
                // Card(
                //   child: ListTile(
                //     leading: const Icon(Icons.settings_ethernet),
                //     title: const Text('Device Configuration'),
                //     subtitle: const Text('Configure IP, Port, and Sensor Drivers'),
                //     trailing: const Icon(Icons.arrow_forward_ios),
                //     onTap: () {
                //       Navigator.push(
                //         context,
                //         MaterialPageRoute(
                //           builder: (context) => const DeviceConfigScreen(),
                //         ),
                //       );
                //     },
                //   ),
                // ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
