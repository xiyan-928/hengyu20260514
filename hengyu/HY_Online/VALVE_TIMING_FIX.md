# 阀门切换时序问题修复

## 问题描述

自动控制启动时，光谱采集的启动时间早于阀门实际切换完成的时间，导致：
1. 阀门还未完全打开就开始采集
2. 采集到的数据可能不准确
3. 前端设置的等待时间与实际不符

## 根本原因

### 原有流程（有问题）

```
T0: 计时结束 (wait_time 到达)
    ↓
T0+0ms: 标记 _is_action_active = True
T0+0ms: 启动 SensorDataManager
T0+0ms: 调用 _request_valve_switch() (只是设置标志)
T0+0ms: 调用 _trigger_spectrum_acquisition() ❌ 太早了！
    ↓
T0+2000ms: SensorDataManager 第一次更新周期
           → 执行阀门切换请求
           → 写入 Modbus 寄存器
    ↓
T0+2000-3000ms: 物理阀门开始动作
    ↓
T0+3000-5000ms: 阀门实际打开完成
```

**问题**：光谱采集在 T0+0ms 就启动了，但阀门要到 T0+3000-5000ms 才真正打开！

## 解决方案

### 新流程（修复后）

```
T0: 计时结束 (wait_time 到达)
    ↓
T0+0ms: 步骤1 - 设置阀门请求标志
        _request_valve_switch("VALVE_IN", 1)
        _request_valve_switch("VALVE_OUT", 1)
        _request_valve_switch("LIGHT", 1)
    ↓
T0+0ms: 步骤2 - 启动 SensorDataManager
        (这会触发阀门请求的执行)
        记录 _valve_switch_start_time = T0
    ↓
T0+2000ms: SensorDataManager 第一次更新
           → 执行阀门切换
           → 读取传感器
    ↓
T0+3000ms: 检查 valve_switch_elapsed = 3.0s
           → 阀门切换完成 ✅
           → 步骤3 - 启动光谱采集
    ↓
T0+3000ms+: 光谱采集开始（阀门已经打开）
```

## 代码修改

### 修改前
```python
if not self._is_action_active:
    self._is_action_active = True
    sdm.start_auto_update(...)

# 立即请求阀门
self._request_valve_switch(...)

# 立即启动光谱 ❌
self._trigger_spectrum_acquisition()
```

### 修改后
```python
if not self._is_action_active:
    self._is_action_active = True
    
    # 1. 先设置阀门请求
    self._request_valve_switch("VALVE_IN", 1, "进水阀")
    self._request_valve_switch("VALVE_OUT", 1, "出水阀")
    self._request_valve_switch("LIGHT", 1, "光源")
    
    # 2. 启动传感器更新（触发阀门切换）
    sdm.start_auto_update(...)
    
    # 3. 记录切换开始时间
    self._valve_switch_start_time = time.time()

# 检查是否需要等待阀门切换
if hasattr(self, '_valve_switch_start_time'):
    valve_switch_elapsed = time.time() - self._valve_switch_start_time
    if valve_switch_elapsed < 3.0:
        # 还在等待，不启动光谱
        logger.info(f"等待阀门切换... ({valve_switch_elapsed:.1f}s/3.0s)")
    else:
        # 等待完成，启动光谱
        delattr(self, '_valve_switch_start_time')
        self._trigger_spectrum_acquisition() ✅
```

## 关键改进

### 1. 分阶段执行
- **阶段1**：设置阀门请求 + 启动 SensorDataManager
- **阶段2**：等待 3 秒（阀门切换时间）
- **阶段3**：启动光谱采集

### 2. 非阻塞等待
使用 `_valve_switch_start_time` 标记，而不是 `time.sleep()`：
- ✅ 不阻塞主循环
- ✅ 可以继续处理其他逻辑
- ✅ 可以响应控制信号变化

### 3. 状态追踪
```python
if hasattr(self, '_valve_switch_start_time'):
    # 正在等待阀门切换
else:
    # 阀门已切换，正常运行
```

## 时间参数

### 等待时间：3 秒
基于以下考虑：
1. SensorDataManager 更新间隔：2 秒
2. Modbus 通信延迟：~100-500ms
3. 物理阀门动作时间：~500-1000ms
4. 安全余量：~500ms

**总计**：2s (更新周期) + 1s (通信+动作) = 3s

### 可配置化（未来）
如果需要，可以将等待时间改为可配置：
```python
valve_switch_delay = config.get('valve_switch_delay', 3.0)
if valve_switch_elapsed < valve_switch_delay:
    ...
```

## 测试验证

### 测试步骤
1. 启动自动控制
2. 设置 `wait_time` 为较短时间（如 10 秒）
3. 观察日志输出：
   ```
   自动控制: 步骤1 - 请求打开阀门
   自动控制: 步骤2 - 启动传感器自动更新
   自动控制: 等待阀门切换... (0.0s/3.0s)
   自动控制: 等待阀门切换... (1.0s/3.0s)
   自动控制: 等待阀门切换... (2.0s/3.0s)
   自动控制: 步骤3 - 阀门切换完成，启动光谱采集
   自动控制: 光谱采集已触发
   ```

### 验证点
- ✅ 阀门请求在光谱启动前发出
- ✅ 有 3 秒的等待时间
- ✅ 光谱在阀门切换后启动
- ✅ 不阻塞主循环

## 相关文件
- `HY_Online/auto_control_manager.py` - 主要修改
- `HY_Online/Devices/hy_device.py` - SensorDataManager 逻辑

