# 设备配置页面加载卡死问题修复

## 问题描述

前端点击设备配置页面时卡死，等待一段时间后显示"加载配置失败"。

## 根本原因

1. **初始化时机问题**：`DeviceConfig.__init__` 在初始化时立即启动了 `SensorDataManager` 的自动更新线程
2. **Modbus 连接阻塞**：如果 Modbus 设备未连接或连接超时，会导致 `ModbusTaskQueue` 阻塞
3. **API 调用冲突**：前端加载设备配置页面时会调用 `/hy-device/valve-status` API，该 API 依赖 `SensorDataManager` 的缓存数据，但如果 `SensorDataManager` 正在阻塞，会导致请求超时

## 前端加载设备配置页面时的通信流程

1. `GET /api/settings/device` - 获取设备配置
2. `GET /api/settings/drivers` - 获取可用的驱动列表
3. `GET /hy-device/valve-status` - 获取阀门和光源状态（**这里卡住**）

## 解决方案

### 1. 延迟启动 SensorDataManager

**修改前**：
```python
class DeviceConfig:
    def __init__(self, mock_mode: bool = False):
        # ... 初始化代码 ...
        self.sdm = SensorDataManager()
        # 立即启动自动更新
        self.sdm.start_auto_update(self.ip_address, self.port, interval_seconds=5.0, daemon=True)
```

**修改后**：
```python
class DeviceConfig:
    def __init__(self, mock_mode: bool = False):
        # ... 初始化代码 ...
        self.sdm = SensorDataManager()
        # 不再自动启动，由需要的服务按需启动
        logger.info("SensorDataManager will be started on-demand")
```

### 2. 智能阀门状态查询

**修改前**：
```python
async def get_all_valve_statuses(self) -> Dict[str, bool]:
    # 总是使用 SensorDataManager 缓存
    return self.sdm.get_valve_statuses()
```

**修改后**：
```python
async def get_all_valve_statuses(self) -> Dict[str, bool]:
    # 如果 SensorDataManager 正在运行，使用缓存
    if self.sdm.is_running():
        return self.sdm.get_valve_statuses()
    else:
        # 独立查询阀门状态，避免冲突
        # 使用 ModbusTaskQueue 确保线程安全
        return self._query_valve_status_directly()
```

### 3. Mock 模式优化

**修改前**：
```python
def update_sensor(self, ip, port):
    def task():
        if is_mock:
            # Mock 逻辑
            ...
        else:
            # Real 逻辑
            ...
    # 总是通过 ModbusTaskQueue 执行
    ModbusTaskQueue.instance().execute(ip, port, task)
```

**修改后**：
```python
def update_sensor(self, ip, port):
    if is_mock:
        # Mock 模式：直接执行，不通过 ModbusTaskQueue
        # 生成模拟数据
        ...
    else:
        # Real 模式：通过 ModbusTaskQueue 执行
        def task():
            # Real 逻辑
            ...
        ModbusTaskQueue.instance().execute(ip, port, task)
```

### 4. AutoControlManager 按需启动

确保 `AutoControlManager` 在需要时启动 `SensorDataManager`：

```python
def _request_valve_switch(self, key, state, desc):
    sdm = SensorDataManager.instance()
    
    # 确保 SensorDataManager 正在运行
    if not sdm.is_running():
        logger.info("自动控制: SensorDataManager 未运行，启动中...")
        sdm.start_auto_update(dev_ip, dev_port, interval_seconds=2.0, daemon=True)
    
    sdm.set_valve_request(key, bool(state))
```

## 测试验证

### Mock 模式测试
1. 启动后端服务（Mock 模式）
2. 打开前端设备配置页面
3. 验证页面能够快速加载
4. 验证阀门状态显示正常

### Real 模式测试
1. 启动后端服务（Real 模式）
2. **设备未连接时**：
   - 打开设备配置页面
   - 应该能够加载配置，阀门状态显示为默认值（False）
3. **设备已连接时**：
   - 打开设备配置页面
   - 应该显示实际的阀门状态

### 自动控制测试
1. 启用自动控制
2. 验证 `SensorDataManager` 自动启动
3. 验证阀门控制请求正常执行
4. 验证风扇调速正常工作（查看日志输出）

## 关键改进点

1. **解耦初始化和运行**：`DeviceConfig` 初始化不再自动启动后台线程
2. **按需启动**：由实际需要的服务（如 `AutoControlManager`）按需启动 `SensorDataManager`
3. **智能查询**：根据 `SensorDataManager` 的运行状态，选择使用缓存或独立查询
4. **Mock 优化**：Mock 模式下避免使用 `ModbusTaskQueue`，直接生成数据
5. **超时保护**：独立查询时设置超时（3秒），避免长时间阻塞

## 相关文件

- `HY_Online/Devices/hy_device.py` - 核心修改
- `HY_Online/auto_control_manager.py` - 按需启动逻辑
- `HY_Online/main.py` - API 端点（无需修改）

