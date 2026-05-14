# Modbus Client 管理策略

## 设计原则

1. **双平面**：线圈侧（`coils`、离散量报警等）与寄存器侧（`holding` / `input register`、风扇 holding 等）使用**不同的 IP:端口** 时，由**两个独立 worker** 并行通信，互不排队阻塞。
2. **平面内串行**：同一 `(ip, port, plane)` 仅一个工作线程 + FIFO 队列，任务顺序执行；同一 TCP 连接上不并发 pymodbus 调用。
3. **持久连接**：每个 worker 内维护长生命周期 `ModbusTcpClient`，失败时关闭并在下一任务重建，避免每次任务握手。

配置项（[device_settings.py](Devices/device_settings.py)）：

- `modbus_coils`: `{ "host", "port" }`，缺省回退到顶层 `ip` / `port`
- `modbus_holding`: `{ "host", "port" }`（寄存器网关，含传感器与风扇等），缺省回退到顶层 `ip` / `port`

## ModbusTaskQueue API

- `execute_coils(host, port, task, timeout=None)` — `task(client: ModbusTcpClient) -> result`
- `execute_registers(host, port, task, timeout=None)` — 同上
- `get_status_snapshot()` — 各 worker 的 `plane`、`ip`、`port`、`queue_size`、`connected`

## 正确使用方式

### 1. SensorDataManager.update_sensor()（真实模式）

- 线圈任务与寄存器任务通过 `ThreadPoolExecutor` **并行**提交。
- 阀请求、读线圈状态、报警与急停写入仅在线圈平面执行。
- 传感器驱动读、风扇控制仅在寄存器平面执行。

### 2. switch_valve()

- 仅使用 `get_modbus_coils_endpoint()` + `execute_coils`，与寄存器轮询**不同队列**，阀操作可尽快下发。

### 3. get_all_valve_statuses()（SDM 未运行时）

- 使用线圈平面 `execute_coils` 读线圈。

### 4. reset_devices()

- 重置线圈写入使用 `execute_coils`。

### 5. DeviceConfig.test_connection()

- 分别在线圈平面与寄存器平面各做一次连通性检查，**均成功**才返回 True。

### 6. 外部 PLC（自动控制信号源）

- [auto_control_manager.py](auto_control_manager.py) 对 `modbus_host:modbus_port` 仍使用**独立**长连接，与现场设备双平面无关；勿与设备 `modbus_coils` / `modbus_holding` 混为同一端口（除非刻意为之）。

## 使用规范

### 规则 1：按平面选队列

```python
# 阀、线圈、离散量报警 → 线圈端点
coil_ip, coil_port = DeviceSettings.instance().get_modbus_coils_endpoint()
ModbusTaskQueue.instance().execute_coils(coil_ip, coil_port, lambda c: c.write_coil(addr, True, unit=1))

# 传感器、风扇 holding → 寄存器端点
reg_ip, reg_port = DeviceSettings.instance().get_modbus_holding_endpoint()
ModbusTaskQueue.instance().execute_registers(reg_ip, reg_port, lambda c: driver.read(c, params))
```

### 规则 2：Task 签名为 (client) -> result

Worker 负责 `_ensure_client()`；不要在 task 内 `close()` 传入的 client（由 worker 在异常时重建）。

### 规则 3：合理超时

`execute_*(..., timeout=25.0)` 应大于单轮读写预期；重置等长等待仍在 asyncio 层睡眠，不占满队列。

## 调试

- HTTP：`GET /hy-device/connection-pool` → `DeviceConfig.get_connection_pool_status()` → `get_status_snapshot()`。
- 日志：线程名形如 `Modbus-coils-192.168.1.10:502`。

## 总结

| 操作           | 端点配置              | 队列方法            |
|----------------|-----------------------|---------------------|
| 阀线圈读/写    | `modbus_coils`        | `execute_coils`     |
| 传感器/风扇等  | `modbus_holding`      | `execute_registers` |
| PLC 控制信号   | `auto_control.*`      | 独立 client（ACM）  |
