import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/device_config.dart';
import '../services/api_service.dart';
import '../providers/sensor_provider.dart';
import '../providers/spectrum_provider.dart';

class DeviceConfigScreen extends StatefulWidget {
  const DeviceConfigScreen({super.key});

  @override
  State<DeviceConfigScreen> createState() => _DeviceConfigScreenState();
}

class _DeviceConfigScreenState extends State<DeviceConfigScreen> {
  final ApiService _apiService = ApiService();
  bool _isLoading = true;
  DeviceConfig? _config;
  List<String> _availableDrivers = [];
  
  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _portController = TextEditingController();

  // 双平面 Modbus 网关（后端 modbus_coils / modbus_holding）
  final TextEditingController _coilHostController = TextEditingController();
  final TextEditingController _coilPortController = TextEditingController();
  final TextEditingController _holdingHostController = TextEditingController();
  final TextEditingController _holdingPortController = TextEditingController();
  
  // Auto Control Controllers
  final TextEditingController _autoModbusHostController = TextEditingController();
  final TextEditingController _autoModbusPortController = TextEditingController();
  final TextEditingController _autoUnitIdController = TextEditingController();
  final TextEditingController _autoRegisterController = TextEditingController();
  final TextEditingController _autoWaitTimeController = TextEditingController();
  bool _autoControlEnabled = false;
  
  // Alarm Controllers
  final TextEditingController _alarmAddressController = TextEditingController();
  bool _alarmEnabled = false;

  // Fan Controllers
  final TextEditingController _fanUnitController = TextEditingController();
  final TextEditingController _fanTargetTempController = TextEditingController(); // Deprecated
  final TextEditingController _fanStartTempController = TextEditingController();
  final TextEditingController _fanStopTempController = TextEditingController();
  final TextEditingController _fanMinSpeedController = TextEditingController();
  final TextEditingController _fanMaxSpeedController = TextEditingController();
  final TextEditingController _fanKFactorController = TextEditingController();
  bool _fanEnabled = false;

  // Map to store controllers for sensor params
  final Map<String, Map<String, TextEditingController>> _sensorParamControllers = {};

  List<String> _scriptDefineOptions = ['define/script_define.xlsx'];
  String _selectedScriptDefinePath = 'define/script_define.xlsx';

  @override
  void initState() {
    super.initState();
    _loadData();
  }
  
  @override
  void dispose() {
    _ipController.dispose();
    _portController.dispose();
    _coilHostController.dispose();
    _coilPortController.dispose();
    _holdingHostController.dispose();
    _holdingPortController.dispose();
    _autoModbusHostController.dispose();
    _autoModbusPortController.dispose();
    _autoUnitIdController.dispose();
    _autoRegisterController.dispose();
    _autoWaitTimeController.dispose();
    
    _alarmAddressController.dispose();
    _fanUnitController.dispose();
    _fanTargetTempController.dispose();
    _fanStartTempController.dispose();
    _fanStopTempController.dispose();
    _fanMinSpeedController.dispose();
    _fanMaxSpeedController.dispose();
    _fanKFactorController.dispose();

    for (var sensorMap in _sensorParamControllers.values) {
      for (var controller in sensorMap.values) {
        controller.dispose();
      }
    }
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    try {
      final driversResponse = await _apiService.getAvailableDrivers();
      final configResponse = await _apiService.getDeviceSettings();

      var scriptOptions = <String>['define/script_define.xlsx'];
      final filesResp = await _apiService.getScriptDefineFiles();
      if (filesResp.success &&
          filesResp.data != null &&
          filesResp.data!.isNotEmpty) {
        scriptOptions = List<String>.from(filesResp.data!);
      }

      if (mounted) {
        setState(() {
          if (driversResponse.success) {
            _availableDrivers = driversResponse.data ?? [];
          }
          
          if (configResponse.success && configResponse.data != null) {
            _config = configResponse.data;
            _ipController.text = _config!.ip;
            _portController.text = _config!.port.toString();

            _coilHostController.text = _config!.modbusCoils.host ?? '';
            _coilPortController.text =
                _config!.modbusCoils.port?.toString() ?? '';
            _holdingHostController.text = _config!.modbusHolding.host ?? '';
            _holdingPortController.text =
                _config!.modbusHolding.port?.toString() ?? '';
            
            // Initialize param controllers
            _config!.sensors.forEach((sensorName, sensorConfig) {
              _sensorParamControllers[sensorName] = {};
              sensorConfig.params.forEach((key, value) {
                _sensorParamControllers[sensorName]![key] = 
                    TextEditingController(text: value.toString());
              });
            });

            // Initialize auto control controllers
            _autoModbusHostController.text = _config!.autoControl.modbusHost;
            _autoModbusPortController.text = _config!.autoControl.modbusPort.toString();
            _autoUnitIdController.text = _config!.autoControl.unitId.toString();
            _autoRegisterController.text = _config!.autoControl.monitorRegister.toString();
            _autoWaitTimeController.text = _config!.autoControl.waitTime.toString();
            _autoControlEnabled = _config!.autoControl.enabled;
            _selectedScriptDefinePath = _config!.autoControl.scriptDefinePath;
            _scriptDefineOptions = scriptOptions.contains(_selectedScriptDefinePath)
                ? scriptOptions
                : [...scriptOptions, _selectedScriptDefinePath];
            
            // Initialize alarm controllers
            _alarmAddressController.text = _config!.alarm.address.toString();
            _alarmEnabled = _config!.alarm.enabled;

            // Initialize fan controllers
            _fanUnitController.text = _config!.fan.unit.toString();
            _fanTargetTempController.text = _config!.fan.targetTemp.toString();
            _fanStartTempController.text = _config!.fan.startTemp.toString();
            _fanStopTempController.text = _config!.fan.stopTemp.toString();
            _fanMinSpeedController.text = _config!.fan.minSpeed.toString();
            _fanMaxSpeedController.text = _config!.fan.maxSpeed.toString();
            _fanKFactorController.text = _config!.fan.kFactor.toString();
            _fanEnabled = _config!.fan.enabled;
          }
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error loading data: $e')),
        );
      }
    }
  }

  Future<void> _saveConfig() async {
    if (_config == null) return;
    
    print('🔍 [Frontend] _saveConfig called. AutoControl Enabled: $_autoControlEnabled');
    
    setState(() => _isLoading = true);
    
    try {
      // Update config from controllers
      final newSensors = <String, SensorConfig>{};
      
      _config!.sensors.forEach((sensorName, sensorConfig) {
        final newParams = <String, dynamic>{};
        
        // Copy existing params first to keep keys
        newParams.addAll(sensorConfig.params);
        
        // Update from controllers
        if (_sensorParamControllers.containsKey(sensorName)) {
          _sensorParamControllers[sensorName]!.forEach((key, controller) {
            // Try to parse as int/double if possible, otherwise string
            final text = controller.text;
            if (int.tryParse(text) != null) {
              newParams[key] = int.parse(text);
            } else if (double.tryParse(text) != null) {
              newParams[key] = double.parse(text);
            } else {
              newParams[key] = text;
            }
          });
        }
        
        newSensors[sensorName] = sensorConfig.copyWith(params: newParams);
      });
      
      final newAutoControl = _config!.autoControl.copyWith(
        enabled: _autoControlEnabled,
        modbusHost: _autoModbusHostController.text,
        modbusPort: int.tryParse(_autoModbusPortController.text),
        unitId: int.tryParse(_autoUnitIdController.text),
        monitorRegister: int.tryParse(_autoRegisterController.text),
        waitTime: int.tryParse(_autoWaitTimeController.text),
        scriptDefinePath: _selectedScriptDefinePath,
      );
      
      final newAlarm = _config!.alarm.copyWith(
        enabled: _alarmEnabled,
        address: int.tryParse(_alarmAddressController.text),
      );

      final newFan = _config!.fan.copyWith(
        enabled: _fanEnabled,
        unit: int.tryParse(_fanUnitController.text),
        targetTemp: double.tryParse(_fanTargetTempController.text),
        startTemp: double.tryParse(_fanStartTempController.text),
        stopTemp: double.tryParse(_fanStopTempController.text),
        minSpeed: int.tryParse(_fanMinSpeedController.text),
        maxSpeed: int.tryParse(_fanMaxSpeedController.text),
        kFactor: int.tryParse(_fanKFactorController.text),
      );

      final coilHost = _coilHostController.text.trim();
      final holdHost = _holdingHostController.text.trim();
      final newModbusCoils = ModbusBusConfig(
        host: coilHost.isEmpty ? null : coilHost,
        port: int.tryParse(_coilPortController.text.trim()),
      );
      final newModbusHolding = ModbusBusConfig(
        host: holdHost.isEmpty ? null : holdHost,
        port: int.tryParse(_holdingPortController.text.trim()),
      );

      final newConfig = _config!.copyWith(
        ip: _ipController.text,
        port: int.tryParse(_portController.text) ?? 502,
        sensors: newSensors,
        relays: _config!.relays,
        modbusCoils: newModbusCoils,
        modbusHolding: newModbusHolding,
        autoControl: newAutoControl,
        alarm: newAlarm,
        fan: newFan,
      );
      
      final response = await _apiService.updateDeviceSettings(newConfig);
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(response.message),
            backgroundColor: response.success ? Colors.green : Colors.red,
          ),
        );
        if (response.success) {
          // Update sensor provider with new auto control config
          context.read<SensorProvider>().setAutoControlEnabled(_autoControlEnabled);
          // Update spectrum provider with new auto control config
          context.read<SpectrumProvider>().setAutoControlEnabled(_autoControlEnabled);
          
          // Reload to ensure sync
          _loadData();
        } else {
          setState(() => _isLoading = false);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error saving config: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('设备配置'),
        actions: [
          IconButton(
            icon: const Icon(Icons.save),
            onPressed: _isLoading ? null : _saveConfig,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _config == null
              ? const Center(child: Text('加载配置失败'))
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildConnectionSection(),
                      const SizedBox(height: 24),
                      _buildModbusBusSection(),
                      const SizedBox(height: 24),
                      _buildAutoControlSection(),
                      const SizedBox(height: 24),
                      _buildAlarmSection(),
                      const SizedBox(height: 24),
                      _buildFanSection(),
                      const SizedBox(height: 24),
                      const Text(
                        '传感器',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 16),
                      ..._config!.sensors.entries.map((entry) => _buildSensorCard(entry.key, entry.value)),
                    ],
                  ),
                ),
    );
  }

  Widget _buildConnectionSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '主设备连接',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _ipController,
                    decoration: const InputDecoration(
                      labelText: 'IP 地址',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  flex: 1,
                  child: TextField(
                    controller: _portController,
                    decoration: const InputDecoration(
                      labelText: '端口',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildModbusBusSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Modbus 双平面网关',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '线圈侧（阀、报警离散量等）与寄存器侧（传感器、风扇等）可配置不同 IP/端口；留空则使用上方主设备地址。',
              style: TextStyle(
                fontSize: 13,
                color: Colors.grey.shade700,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              '线圈网关 (modbus_coils)',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _coilHostController,
                    decoration: const InputDecoration(
                      labelText: '线圈侧 IP（可选）',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  flex: 1,
                  child: TextField(
                    controller: _coilPortController,
                    decoration: const InputDecoration(
                      labelText: '端口（可选）',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            const Text(
              '寄存器网关 (modbus_holding)',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _holdingHostController,
                    decoration: const InputDecoration(
                      labelText: '寄存器侧 IP（可选）',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  flex: 1,
                  child: TextField(
                    controller: _holdingPortController,
                    decoration: const InputDecoration(
                      labelText: '端口（可选）',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
  
  Widget _buildAutoControlSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  '自动控制 (Modbus TCP)',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Switch(
                  value: _autoControlEnabled,
                  onChanged: (value) {
                    setState(() {
                      _autoControlEnabled = value;
                    });
                  },
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _autoModbusHostController,
                    decoration: const InputDecoration(
                      labelText: 'Modbus 服务器 IP',
                      border: OutlineInputBorder(),
                    ),
                    enabled: _autoControlEnabled,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  flex: 1,
                  child: TextField(
                    controller: _autoModbusPortController,
                    decoration: const InputDecoration(
                      labelText: '端口',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _autoControlEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _autoUnitIdController,
                    decoration: const InputDecoration(
                      labelText: '单元 ID (unit_add)',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _autoControlEnabled,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _autoRegisterController,
                    decoration: const InputDecoration(
                      labelText: '寄存器地址',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _autoControlEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _autoWaitTimeController,
                    decoration: const InputDecoration(
                      labelText: '等待时间 (秒)',
                      border: OutlineInputBorder(),
                      helperText: '信号为1后启动前的等待时间',
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _autoControlEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              value: _scriptDefineOptions.contains(_selectedScriptDefinePath)
                  ? _selectedScriptDefinePath
                  : _scriptDefineOptions.first,
              decoration: const InputDecoration(
                labelText: 'script_define（xlsx）',
                border: OutlineInputBorder(),
                helperText: '保存后服务器将重新加载脚本定义',
              ),
              items: _scriptDefineOptions
                  .map(
                    (p) => DropdownMenuItem<String>(
                      value: p,
                      child: Text(p, overflow: TextOverflow.ellipsis),
                    ),
                  )
                  .toList(),
              onChanged: (v) {
                if (v != null) {
                  setState(() => _selectedScriptDefinePath = v);
                }
              },
            ),
          ],
        ),
      ),
    );
  }
  
  Widget _buildAlarmSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  '温度报警',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Switch(
                  value: _alarmEnabled,
                  onChanged: (value) {
                    setState(() {
                      _alarmEnabled = value;
                    });
                  },
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '触发报警时将强制关闭所有阀门',
              style: TextStyle(
                fontSize: 12,
                color: Colors.grey.shade600,
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _alarmAddressController,
              decoration: const InputDecoration(
                labelText: '报警点位地址',
                border: OutlineInputBorder(),
                helperText: 'Modbus离散输入地址',
              ),
              keyboardType: TextInputType.number,
              enabled: _alarmEnabled,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFanSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  '风扇调温',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Switch(
                  value: _fanEnabled,
                  onChanged: (value) {
                    setState(() {
                      _fanEnabled = value;
                    });
                  },
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '根据PT100温度自动调节风扇转速',
              style: TextStyle(
                fontSize: 12,
                color: Colors.grey.shade600,
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _fanUnitController,
                    decoration: const InputDecoration(
                      labelText: '风扇单元号',
                      border: OutlineInputBorder(),
                      helperText: 'Modbus单元ID',
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _fanEnabled,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _fanTargetTempController,
                    decoration: const InputDecoration(
                      labelText: '目标温度 (°C)',
                      border: OutlineInputBorder(),
                      helperText: '期望维持的温度',
                    ),
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    enabled: _fanEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _fanStartTempController,
                    decoration: const InputDecoration(
                      labelText: '启动温度 (°C)',
                      border: OutlineInputBorder(),
                      helperText: '超过此温度开始运转',
                    ),
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    enabled: _fanEnabled,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _fanStopTempController,
                    decoration: const InputDecoration(
                      labelText: '停止温度 (°C)',
                      border: OutlineInputBorder(),
                      helperText: '低于此温度停止运转',
                    ),
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    enabled: _fanEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _fanMinSpeedController,
                    decoration: const InputDecoration(
                      labelText: '最小转速',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _fanEnabled,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _fanMaxSpeedController,
                    decoration: const InputDecoration(
                      labelText: '最大转速',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.number,
                    enabled: _fanEnabled,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _fanKFactorController,
              decoration: const InputDecoration(
                labelText: '控制增益 (K因子)',
                border: OutlineInputBorder(),
                helperText: '每1°C温差对应的转速变化',
              ),
              keyboardType: TextInputType.number,
              enabled: _fanEnabled,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSensorCard(String sensorName, SensorConfig sensorConfig) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  sensorName,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Switch(
                  value: sensorConfig.enabled,
                  onChanged: (value) {
                    setState(() {
                      final newSensors = Map<String, SensorConfig>.from(_config!.sensors);
                      newSensors[sensorName] = sensorConfig.copyWith(enabled: value);
                      _config = _config!.copyWith(sensors: newSensors);
                    });
                  },
                ),
              ],
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              value: _availableDrivers.contains(sensorConfig.driver) 
                  ? sensorConfig.driver 
                  : null,
              decoration: const InputDecoration(
                labelText: '驱动',
                border: OutlineInputBorder(),
              ),
              items: _availableDrivers.map((driver) {
                return DropdownMenuItem(
                  value: driver,
                  child: Text(driver),
                );
              }).toList(),
              onChanged: (value) {
                if (value != null) {
                  setState(() {
                    final newSensors = Map<String, SensorConfig>.from(_config!.sensors);
                    newSensors[sensorName] = sensorConfig.copyWith(driver: value);
                    _config = _config!.copyWith(sensors: newSensors);
                  });
                }
              },
            ),
            if (sensorConfig.params.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Text(
                '参数',
                style: TextStyle(fontWeight: FontWeight.w500),
              ),
              const SizedBox(height: 8),
              ...sensorConfig.params.keys.map((key) {
                // Ensure controller exists
                if (_sensorParamControllers[sensorName] == null) {
                  _sensorParamControllers[sensorName] = {};
                }
                if (_sensorParamControllers[sensorName]![key] == null) {
                  _sensorParamControllers[sensorName]![key] = 
                      TextEditingController(text: sensorConfig.params[key].toString());
                }
                
                return Padding(
                  padding: const EdgeInsets.only(bottom: 8.0),
                  child: TextField(
                    controller: _sensorParamControllers[sensorName]![key],
                    decoration: InputDecoration(
                      labelText: key,
                      border: const OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                );
              }),
            ],
          ],
        ),
      ),
    );
  }
}
