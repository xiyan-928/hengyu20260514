import threading
import time
import logging
from typing import Optional, Callable, Any

from pymodbus.client.sync import ModbusTcpClient
from Devices.device_settings import DeviceSettings
from Devices.hy_device import SensorDataManager
#from spectrum_manager import spectrum_manager
from spectrum_manager import spectrum_manager, SpectrumAcquisitionManager
from pymodbus.payload import BinaryPayloadBuilder, Endian

from auto_control_context import AutoControlContext
from auto_control_func import (
    get_alarm_message,
    get_autocontrol_message,
    run_on_alarm_off,
    run_on_alarm_on,
    run_on_autorun_batch_finish,
    run_on_get_ready_for_autorun,
    run_on_warmup,
    set_warmup_script_complete_callback,
)
from auto_control_script_engine import get_script_engine, load_auto_control_scripts_at_startup
from hy_logging import LOG_SIGNAL
from modbus_logging import elapsed_ms, log_modbus_event, modbus_context, now_ms

logger = logging.getLogger(__name__)

class AutoControlManager:
    """
    自动控制管理器
    监听本地Modbus寄存器，根据信号控制阀门和光谱采集
    """
    
    def __init__(self, get_cds350_device_func: Callable[[], Any]):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()  # 仅用于启动/停止线程
        self._state_lock = threading.Lock()  # 脚本化标志位与手动 API 同步
        self._get_cds350_device = get_cds350_device_func
        
        # 状态变量 - 简单类型，Python GIL 保证原子性
        self._timer_start: Optional[float] = None
        self._last_val: Optional[int] = None
        self._is_action_active = False
        self._last_log_time = 0.0  # 用于控制日志打印频率
        self._last_upload_time = 0.0 # 用于传感器上传
        
        self._is_alarming = False
        self._fan_speed = 0

        # 脚本化状态机标志（自动控制 enabled 时由状态机每轮更新）
        self._has_run_alarm_on = False
        self._has_run_alarm_off = False
        self._auto_run_ready = False
        self._start_spec_sample = False
        self._start_sensor_sample = False

        # 预热：服务启动时均为 False；warm_up_with_water 置 needs_warmup，warm_up_no_action 直接置 has_warmup
        self._has_warmup = False
        self._needs_warmup = False
        self._warmup_script_started = False

        # 日志：仅在与上次不同时输出（配合 hy.signal）
        self._prev_logged_control_signal: Optional[int] = None
        self._last_logged_flags: Optional[tuple] = None

        # 缓存配置
        self._settings = DeviceSettings.instance()
        set_warmup_script_complete_callback(self._on_warmup_script_complete)
            
    def get_status(self) -> dict:
        """获取当前状态"""
        config = self._settings.get_auto_control_settings()
        enabled = config.get('enabled', False)
        with self._state_lock:
            start_spec = self._start_spec_sample
            start_sensor = self._start_sensor_sample
            auto_ready = self._auto_run_ready
            has_alarm_on_edge = self._has_run_alarm_on
            has_alarm_off_edge = self._has_run_alarm_off
            has_warmup = self._has_warmup
            needs_warmup = self._needs_warmup
        last_val = self._last_val
        is_auto_run = last_val == 1 if last_val is not None else False
        return {
            "running": self._running and enabled,
            "signal_val": last_val,
            "timer_active": self._timer_start is not None,
            "timer_start": self._timer_start,
            "is_action_active": self._is_action_active,
            "is_alarming": self._is_alarming,
            "is_alarm_on": self._is_alarming,
            "is_auto_run": is_auto_run,
            "auto_run_ready": auto_ready,
            "has_run_alarm_on": has_alarm_on_edge,
            "has_run_alarm_off": has_alarm_off_edge,
            "start_spec_sample": start_spec,
            "start_sensor_sample": start_sensor,
            "fan_speed": self._fan_speed,
            "fan_read_ok": getattr(SensorDataManager.instance(), "fan_read_ok", False),
            "fan_last_error": getattr(SensorDataManager.instance(), "fan_last_error", None),
            "fan_last_read_ts": getattr(SensorDataManager.instance(), "fan_last_read_ts", None),
            "sensor_monitor_running": SensorDataManager.instance().is_running(),
            "has_warmup": has_warmup,
            "needs_warmup": needs_warmup,
        }

    def reset_warmup_flags(self) -> None:
        """FastAPI 等服务启动时将预热标志清零。"""
        with self._state_lock:
            self._has_warmup = False
            self._needs_warmup = False
            self._warmup_script_started = False

    def warm_up_with_water(self) -> None:
        """选择通水等方式预热：将 needs_warmup 置为 True。"""
        with self._state_lock:
            self._needs_warmup = True
            self._warmup_script_started = False

    def warm_up_no_action(self) -> None:
        """跳过通水等动作，直接视为已预热：将 has_warmup 置为 True。"""
        with self._state_lock:
            self._has_warmup = True

    def _on_warmup_script_complete(self) -> None:
        """script_define 中预热脚本执行完毕，等效于 warm_up_no_action。"""
        self.warm_up_no_action()

    #---------------------------------------
    def _on_ready_for_autorun_complete(self) -> None:
        """置换准备脚本（run_on_get_ready_for_autorun）全部步骤执行完毕后触发置换前参比光谱采集。"""
        device = self._get_cds350_device()
        if device is None:
            logger.warning("置换前参比光谱: CDS350 未初始化，跳过采集")
            return
        LOG_SIGNAL.info("置换准备脚本完成，触发置换前参比光谱采集")
        spectrum_manager.start_blank_acquisition(device, "blank_before")

    def _on_batch_finish_complete(self) -> None:
        """清洗脚本（run_on_autorun_batch_finish）全部步骤执行完毕后触发清洗后参比光谱采集。"""
        device = self._get_cds350_device()
        if device is None:
            logger.warning("清洗后参比光谱: CDS350 未初始化，跳过采集")
            return
        LOG_SIGNAL.info("清洗脚本完成，触发清洗后参比光谱采集")
        spectrum_manager.start_blank_acquisition(device, "blank_after")
    #---------------------------------------

    def _tick_script_engine(self, ctx: AutoControlContext) -> None:
        get_script_engine().tick(ctx)

    def _warmup_phase(self, ctx: AutoControlContext) -> None:
        """
        在自动控制信号查询前执行（紧接报警查询之后）：
        - has_warmup==True：将 needs_warmup 置 False，结束。
        - has_warmup==False 且 needs_warmup==True：本会话仅首次调用 run_on_warmup 启动脚本（由主循环 tick 推进）。
        """
        with self._state_lock:
            has_w = self._has_warmup
            needs_w = self._needs_warmup

        if has_w:
            with self._state_lock:
                self._needs_warmup = False
            return

        if needs_w:
            with self._state_lock:
                already = self._warmup_script_started
                if not already:
                    self._warmup_script_started = True
            if not already:
                run_on_warmup(ctx)

    def set_manual_sample_flags(
        self,
        start_spec: Optional[bool] = None,
        start_sensor: Optional[bool] = None,
    ) -> None:
        """
        仅在自动控制未启用（待机/手动）时生效，用于与 HTTP 手动操作同步标志位。
        自动控制 enabled 时调用将被忽略。
        """
        config = self._settings.get_auto_control_settings()
        if config.get("enabled", False):
            return
        should_stop_fan = start_sensor is False
        with self._state_lock:
            if start_spec is not None:
                self._start_spec_sample = start_spec
            if start_sensor is not None:
                self._start_sensor_sample = start_sensor
        if should_stop_fan:
            try:
                SensorDataManager.instance().set_fan_speed_to_zero(reason="manual_sensor_stop")
                self._fan_speed = SensorDataManager.instance().get_fan_speed()
            except Exception as e:
                logger.warning(f"手动关闭传感器采样后设置风扇为0失败: {e}")

    def start(self):
        """启动自动控制服务（启动后台线程，是否工作取决于配置的enabled）"""
        with self._lock:
            if self._running:
                logger.debug("Auto Control: start() called but already running")
                return
            
            # 即使 enabled=False 也启动线程，进入待机模式
            self._running = True
            self._thread = threading.Thread(target=self._run, name="AutoControlManager", daemon=True)
            self._thread.start()
            
            config = self._settings.get_auto_control_settings()
            enabled = config.get('enabled', False)
            logger.debug(
                f"自动控制服务已启动. 初始状态: {'工作中' if enabled else '待机中'}"
            )

    def stop(self):
        """停止自动控制服务（完全停止线程）"""
        with self._lock:
            logger.debug("Auto Control: Stopping service...")
            self._running = False
            
            # 停止传感器自动更新（如果是由自动控制启动的）
            if self._is_action_active:
                logger.debug("Auto Control: Stopping associated sensor updates...")
                SensorDataManager.instance().stop_auto_update()
                self._is_action_active = False
            
            # 额外保障：无论是否标记为active，确保SensorDataManager被清理，
            # 防止"ghost process"现象（如果用户手动停止了自动控制）
            # 注意：这可能会停止并非由自动控制启动的采集，但根据需求，自动控制主要负责采集流程
            # 如果有手动采集正在进行，这里停止也是合理的，因为"自动控制服务已停止"通常意味着系统进入空闲或人工接管
            # 但为了安全起见，我们只在确信是自动控制相关的场景下停止，或者强制停止
            # 考虑到用户反馈的bug，这里强制停止可能更稳妥，或者至少检查一下
            if SensorDataManager.instance().is_running():
                 logger.debug("Auto Control: Ensuring sensor update is stopped during shutdown")
                 SensorDataManager.instance().stop_auto_update()
            
            if self._thread:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.warning("Auto Control: Thread did not stop in time")
                self._thread = None
            
            # 重置状态
            self._timer_start = None
            self._last_val = None
            self._has_run_alarm_on = False
            self._has_run_alarm_off = False
            self._auto_run_ready = False
            with self._state_lock:
                self._start_spec_sample = False
                self._start_sensor_sample = False
                self._has_warmup = False
                self._needs_warmup = False
                self._warmup_script_started = False
            
            self._prev_logged_control_signal = None
            self._last_logged_flags = None
            logger.debug("自动控制服务已停止")

    def reload_settings(self):
        """Reload settings and update status"""
        config = self._settings.get_auto_control_settings()
        enabled = config.get('enabled', False)
        
        logger.debug(
            f"Auto Control: Reloading settings. Enabled={enabled}, Thread Running={self._running}"
        )
        
        # 如果线程未运行（例如刚初始化），则启动它
        if not self._running:
            logger.debug("Auto Control: Thread not running, starting service...")
            self.start()
        else:
            # 线程已在运行，只需打印状态变更
            logger.debug(
                f"Auto Control: Service status updated to {'Enabled' if enabled else 'Standby'}"
            )
            
            # 如果转为禁用，确保清理活动状态
            if not enabled:
                self._prev_logged_control_signal = None
                self._last_logged_flags = None
                if self._is_action_active:
                    logger.debug("Auto Control: Disabled while active, stopping sensors...")
                    SensorDataManager.instance().stop_auto_update()
                    self._is_action_active = False
                self._timer_start = None
                self._last_val = None
                self._has_run_alarm_on = False
                self._has_run_alarm_off = False
                self._auto_run_ready = False
                with self._state_lock:
                    self._start_spec_sample = False
                    self._start_sensor_sample = False

        try:
            load_auto_control_scripts_at_startup()
        except Exception as e:
            logger.error(f"Auto Control: 重载 script_define 失败: {e}")

    def _refresh_alarm_state(self, ctx: AutoControlContext) -> None:
        """根据 get_alarm_message 更新 _is_alarming，并在边沿打印与旧逻辑一致的日志。"""
        was = self._is_alarming
        self._is_alarming = bool(get_alarm_message(ctx))
        if was == self._is_alarming:
            return
        alarm_conf = self._settings.config.get("alarm", {})
        if not alarm_conf.get("enabled", False):
            return
        addr = alarm_conf.get("address", 0)
        if self._is_alarming:
            logger.warning(
                f"⚠️ 报警触发 (地址:{addr})！传感器采集进程已执行强制关闭阀门操作。"
            )
        else:
            LOG_SIGNAL.info(f"报警解除 (地址:{addr})，恢复正常控制")

    def _build_context(self, client: Optional[ModbusTcpClient], config: dict) -> AutoControlContext:
        coils_host, coils_port = self._settings.get_modbus_coils_endpoint()
        return AutoControlContext(
            settings=self._settings,
            modbus_client=client,
            modbus_host=str(config.get("modbus_host", "localhost")),
            modbus_port=int(config.get("modbus_port", 5020)),
            coils_modbus_host=coils_host,
            coils_modbus_port=coils_port,
            modbus_unit_id=int(config.get("unit_id", 1)),
            monitor_register=int(config.get("monitor_register", 1)),
            get_cds350_device=self._get_cds350_device,
        )

    def _apply_state_machine(self, ctx: AutoControlContext, val: int) -> None:
        """硬件控制状态机：报警边沿、自动就绪、采样标志（报警优先）。"""
        is_auto_run = val == 1
        is_alarm_on = self._is_alarming

        with self._state_lock:
            if is_alarm_on:
                if not self._has_run_alarm_on:
                    run_on_alarm_on(ctx)
                    self._has_run_alarm_on = True
                self._has_run_alarm_off = False
            else:
                if self._has_run_alarm_on and not self._has_run_alarm_off:
                    run_on_alarm_off(ctx)
                    self._has_run_alarm_off = True
                self._has_run_alarm_on = False

            if is_auto_run:
                if not self._auto_run_ready:
                    #-----------------run_on_get_ready_for_autorun(ctx)
                    run_on_get_ready_for_autorun(
                        ctx, on_complete=self._on_ready_for_autorun_complete
                    )
                    self._auto_run_ready = True
            else:
                if self._auto_run_ready:
                    #-----------------run_on_autorun_batch_finish(ctx)
                    run_on_autorun_batch_finish(
                        ctx, on_complete=self._on_batch_finish_complete
                    )
                self._auto_run_ready = False

            if not is_auto_run:
                self._start_spec_sample = False
                self._start_sensor_sample = False
            elif is_alarm_on:
                self._start_spec_sample = False
                self._start_sensor_sample = False
            elif (
                is_auto_run
                and self._auto_run_ready
                and self._is_action_active
            ):
                # 与 _process_signal 中计时结束、激活采集动作后再允许自动采样
                self._start_spec_sample = True
                self._start_sensor_sample = True
            else:
                self._start_spec_sample = False
                self._start_sensor_sample = False

        with self._state_lock:
            snap = (
                self._has_run_alarm_on,
                self._has_run_alarm_off,
                self._auto_run_ready,
                self._start_spec_sample,
                self._start_sensor_sample,
            )
        if self._last_logged_flags != snap:
            if self._last_logged_flags is not None:
                LOG_SIGNAL.info(
                    "自动控制标志位: "
                    f"alarm_on已执行={snap[0]}, alarm_off已执行={snap[1]}, 自动运行就绪={snap[2]}, "
                    f"允许光谱采样={snap[3]}, 允许传感器采样={snap[4]}"
                )
            self._last_logged_flags = snap

    def _data_acquisition_phase(self) -> None:
        """数据采集：光谱与传感器（报警时由调用方跳过）。"""
        with self._state_lock:
            do_spec = self._start_spec_sample
            do_sensor = self._start_sensor_sample
        if do_spec:
            self._trigger_spectrum_acquisition()
        if do_sensor:
            try:
                sdm = SensorDataManager.instance()
                ip = self._settings.get_ip()
                port = self._settings.get_port()
                sdm.update_sensor(ip, port)
            except Exception as e:
                logger.error(f"自动控制: 传感器单次采集失败: {e}")

    def _update_fan_from_sdm(self) -> None:
        """风扇显示用速度（逻辑仍在 SensorDataManager 内）。"""
        try:
            sdm = SensorDataManager.instance()
            self._fan_speed = sdm.get_fan_speed()
        except Exception as e:
            if int(time.time()) % 60 == 0:
                logger.error(f"风扇状态读取失败: {e}")

    def _run(self):
        """主循环：报警查询 → 预热（始终）→ 自动控制信号（仅 enabled）→ 状态机 → … → 脚本 tick（始终）"""
        logger.debug("进入自动控制主循环")

        client = None
        retry_interval = 5.0
        current_connection_key = None

        while self._running:
            try:
                config = self._settings.get_auto_control_settings()
                enabled = config.get("enabled", False)
                poll_interval = float(config.get("poll_interval", 5.0))

                host = config.get("modbus_host", "localhost")
                port = config.get("modbus_port", 5020)
                new_connection_key = (host, port)

                if client and (not enabled or current_connection_key != new_connection_key):
                    logger.debug(
                        f"Auto Control: Closing signal source connection {current_connection_key}"
                    )
                    client.close()
                    client = None

                current_connection_key = new_connection_key if enabled else None

                if enabled:
                    if client is None:
                        client = ModbusTcpClient(host, port=port, timeout=2.0)

                    if not client.connect():
                        logger.warning(
                            f"无法连接到控制信号源 {host}:{port}, {retry_interval}秒后重试"
                        )
                        ctx = self._build_context(None, config)
                        self._refresh_alarm_state(ctx)
                        self._warmup_phase(ctx)
                        self._apply_state_machine(ctx, 0)
                        self._tick_script_engine(ctx)
                        if not self._is_alarming:
                            self._process_signal(0)
                            self._data_acquisition_phase()
                        self._update_fan_from_sdm()
                        time.sleep(retry_interval)
                        continue

                ctx = self._build_context(client if enabled else None, config)
                self._refresh_alarm_state(ctx)
                self._warmup_phase(ctx)

                if enabled:
                    val = get_autocontrol_message(ctx)
                    if val != self._prev_logged_control_signal:
                        LOG_SIGNAL.info(
                            f"自动控制监视寄存器信号切换: {self._prev_logged_control_signal} → {val}"
                        )
                        self._prev_logged_control_signal = val
                    self._apply_state_machine(ctx, val)

                    if self._is_alarming:
                        if int(time.time()) % 30 == 0:
                            logger.debug(
                                "自动控制: 处于报警状态，忽略控制信号，保持阀门关闭"
                            )
                    else:
                        if val == 0 and self._last_val == 0 and int(time.time()) % 60 == 0:
                            pass
                        self._process_signal(val)
                        self._data_acquisition_phase()

                    self._update_fan_from_sdm()

                    if time.time() - self._last_upload_time >= 5.0:
                        self._upload_sensor_data(client)
                        self._last_upload_time = time.time()
                else:
                    self._update_fan_from_sdm()

                self._tick_script_engine(ctx)
                time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"自动控制循环异常: {e}")
                if client:
                    client.close()
                    client = None
                time.sleep(retry_interval)

        if client:
            client.close()

    def _process_signal(self, val: int):
        """处理控制信号"""
        
        # 获取设备连接信息
        dev_ip = self._settings.get_ip()
        dev_port = self._settings.get_port()
        close_on_zero = self._settings.get_manual_coil_signal_zero_points()
        open_on_run = self._settings.get_manual_coil_autorun_open_points()
        
        # 状态 0: 关闭相关点位（默认 script_define 全部基础点位）
        if val == 0:
            if self._last_val != 0:
                LOG_SIGNAL.info("控制流程: 信号为 0，关闭线圈点位")
                for pname in close_on_zero:
                    self._request_valve_switch(pname, 0, pname)
                
                self._timer_start = None
                self._last_val = 0
                # 清理阀门切换等待状态，避免下一次启动误判
                if hasattr(self, '_valve_switch_start_time'):
                    delattr(self, '_valve_switch_start_time')
                
                # 停止动作（光谱和传感器）
                if self._is_action_active:
                    LOG_SIGNAL.info("控制流程: 信号归零，停止采集动作")
                    self._is_action_active = False
                    # 注意：不再调用 stop_auto_update，而是保持 SensorDataManager 运行以执行关闭请求
                    # 并且为了保持监控，SDM应该一直运行
                    # SensorDataManager.instance().stop_auto_update() 
                    pass
                
        # 状态 1: 计时 -> 打开阀门 -> 启动光谱
        elif val == 1:
            now = time.time()

            # 如果仍有关闭请求未完成，先等待关闭完成再启动
            try:
                pending_requests = SensorDataManager.instance().get_valve_requests()
                if any(not state for state in pending_requests.values()):
                    if now - self._last_log_time >= 5.0:
                        logger.debug("自动控制: 等待阀门关闭完成后再启动")
                        self._last_log_time = now
                    return
            except Exception:
                pass
            
            # 如果光谱已经在采集（且不是我们刚触发的），则直接进入活动状态，跳过计时
            # 注意：如果是我们刚刚触发的，is_acquiring也会是True，所以需要结合_is_action_active判断
            # 如果 _is_action_active 已经是 True，说明已经是活动状态，无需跳过
            # 如果 _is_action_active 是 False，但光谱正在采集，说明可能是人工启动或之前的状态，我们直接接管
            if not self._is_action_active and spectrum_manager.is_acquiring():
                 LOG_SIGNAL.info("控制流程: 光谱已在采集，直接激活自动控制状态")
                 self._is_action_active = True
                 # 设置计时器为已超时状态，以便后续逻辑正常运行
                 config = self._settings.get_auto_control_settings()
                 timeout_seconds = config.get('wait_time', 300)
                 self._timer_start = now - timeout_seconds - 1.0 
                 self._last_val = 1
            
            if self._last_val != 1:
                LOG_SIGNAL.info("控制流程: 信号为 1，开始计时")
                self._timer_start = now
                self._last_val = 1
            
            if self._timer_start is None:
                 self._timer_start = now
                 
            elapsed = now - self._timer_start
            
            # 检查计时是否达到5分钟 (300秒)
            # 为了测试方便，可以从配置读取超时时间，默认为300
            config = self._settings.get_auto_control_settings()
            timeout_seconds = config.get('wait_time', 300)
            
            if elapsed >= timeout_seconds:
                # 标记动作激活
                if not self._is_action_active:
                    LOG_SIGNAL.info("控制流程: 计时结束，激活采集动作")
                    self._is_action_active = True
                    
                    # 先请求打开线圈点位（由 manual_coil.autorun_open_points 配置）
                    logger.debug("自动控制: 步骤1 - 请求打开线圈点位")
                    for pname in open_on_run:
                        self._request_valve_switch(pname, 1, pname)
                    
                    # 启动传感器数据采集（这会触发阀门请求的执行）
                    sdm = SensorDataManager.instance()
                    if not sdm.is_running():
                        logger.debug("自动控制: 步骤2 - 启动传感器自动更新（将执行阀门切换）")
                        sdm.start_auto_update(dev_ip, dev_port, interval_seconds=2.0, daemon=True)
                    
                    # 等待阀门切换完成（给一个周期的时间）
                    # 注意：这里不能用 time.sleep，因为会阻塞主循环
                    # 改为记录一个"阀门切换开始时间"，在后续周期中检查
                    self._valve_switch_start_time = time.time()
                    logger.debug("自动控制: 等待阀门切换完成...")
                
                # 检查阀门切换是否完成（等待至少一个更新周期）
                if hasattr(self, '_valve_switch_start_time'):
                    valve_switch_elapsed = time.time() - self._valve_switch_start_time
                    if valve_switch_elapsed < 3.0:
                        # 还在等待阀门切换；光谱由主循环数据采集阶段根据 start_spec_sample 触发
                        if int(valve_switch_elapsed * 10) % 10 == 0:  # 每秒打印一次
                            logger.debug(
                                f"自动控制: 等待阀门切换... ({valve_switch_elapsed:.1f}s/3.0s)"
                            )
                    else:
                        delattr(self, '_valve_switch_start_time')
                        LOG_SIGNAL.info("控制流程: 阀门切换完成（光谱由采集阶段触发）")
                else:
                    # 已经过了切换等待期，正常运行
                    # 每隔一段时间(比如60s)重新确认阀门打开
                    if (elapsed - timeout_seconds) % 60 < 5.1:
                        for pname in open_on_run:
                            self._request_valve_switch(pname, 1, pname)
            else:
                # 优化日志打印逻辑，确保每30秒打印一次，不依赖精确的整点命中
                if now - self._last_log_time >= 30.0:
                     logger.debug(
                         f"等待启动光谱检测... 已过去 {int(elapsed)}/{timeout_seconds} 秒"
                     )
                     self._last_log_time = now

    def _request_valve_switch(self, key, state, desc):
        """请求切换阀门状态（通过SensorDataManager异步执行）"""
        try:
            sdm = SensorDataManager.instance()
            
            # 确保 SensorDataManager 正在运行，否则启动它
            if not sdm.is_running():
                dev_ip = self._settings.get_ip()
                dev_port = self._settings.get_port()
                logger.debug("自动控制: SensorDataManager 未运行，启动中...")
                sdm.start_auto_update(dev_ip, dev_port, interval_seconds=2.0, daemon=True)
            
            sdm.set_valve_request(key, bool(state))
            LOG_SIGNAL.info(f"阀门/输出请求: {desc} → {'打开' if state else '关闭'}")
        except Exception as e:
            logger.error(f"请求控制 {desc} 失败: {e}")

    def _trigger_spectrum_acquisition(self):
        """触发光谱采集"""
        device = self._get_cds350_device()
        if not device:
            logger.warning("尝试启动光谱采集，但CDS350设备未初始化")
            return
            
        # 检查是否正在采集
        if spectrum_manager.is_acquiring():
            # 如果是连续采集，可能不需要做什么
            pass
        else:
            LOG_SIGNAL.info("自动控制: 启动光谱采集")
            # 在线程中启动采集，使用start_acquisition (它是非阻塞的，启动线程)
            success = spectrum_manager.start_acquisition(device)
            if success:
                logger.debug("自动控制: 光谱采集已触发")
            else:
                logger.warning("自动控制: 触发光谱采集失败 (可能已在进行中)")

    def _force_close_all_valves(self, dev_ip, dev_port):
        """强制关闭除出水口外的线圈点位（出水口见 manual_coil.outlet_point）"""
        # 这里的 dev_ip, dev_port 参数不再需要，但保留签名兼容性

        logger.warning("⚠️ 执行强制关闭线圈点位")
        outlet = self._settings.get_manual_coil_outlet_point()
        for pname in self._settings.list_script_define_point_names():
            if outlet and pname == outlet:
                continue
            self._request_valve_switch(pname, 0, f"{pname}(报警强制)")

    def _upload_sensor_data(self, client):
        """上传传感器数据到Modbus TCP服务器"""
        try:
            sdm = SensorDataManager.instance()
            # 顺序: ddl, ph, pt100_temp, ph_temp
            # 对应寄存器: 假设从100开始，每个float占2个寄存器，共8个寄存器
            # DDL: 100-101, PH: 102-103, PT100: 104-105, PH_TEMP: 106-107
            
            data_values = [
                sdm.get_ddl(),
                sdm.get_ph(),
                sdm.get_pt100(), # PT100 Temperature
                sdm.get_ph_temp()
            ]
            
            builder = BinaryPayloadBuilder(byteorder=Endian.Big, wordorder=Endian.Little)
            for val in data_values:
                builder.add_32bit_float(float(val))
            
            payload = builder.to_registers()
            
            # 默认上传地址 10，如有配置可读取
            config = self._settings.get_auto_control_settings()
            upload_addr = config.get('upload_register', 10)
            upload_unit = config.get('unit_id', 1) # 使用相同的unit_id
            
            # 如果client未连接，可能导致异常
            started_ms = now_ms()
            client.write_registers(upload_addr, payload, unit=upload_unit)
            log_modbus_event(
                operation="write_registers",
                ip=str(config.get("modbus_host", "localhost")),
                port=int(config.get("modbus_port", 5020)),
                unit=int(upload_unit),
                address=int(upload_addr),
                count=len(payload),
                data=list(payload),
                success=True,
                elapsed_ms_value=elapsed_ms(started_ms),
                context=modbus_context(
                    source="auto_control_manager",
                    request_name="upload_sensor_data",
                    upload_fields=["ddl", "ph", "pt100", "ph_temp"],
                ),
            )
            # logger.debug(f"传感器数据已上传至寄存器 {upload_addr}")
            
        except Exception as e:
            log_modbus_event(
                operation="write_registers",
                ip=str(config.get("modbus_host", "localhost")) if 'config' in locals() else None,
                port=int(config.get("modbus_port", 5020)) if 'config' in locals() else None,
                unit=int(upload_unit) if 'upload_unit' in locals() else None,
                address=int(upload_addr) if 'upload_addr' in locals() else None,
                count=len(payload) if 'payload' in locals() else None,
                data=list(payload) if 'payload' in locals() else None,
                success=False,
                error=str(e),
                elapsed_ms_value=elapsed_ms(started_ms) if 'started_ms' in locals() else None,
                context=modbus_context(
                    source="auto_control_manager",
                    request_name="upload_sensor_data",
                    upload_fields=["ddl", "ph", "pt100", "ph_temp"],
                ),
            )
            # 避免刷屏，偶尔记录
            if int(time.time()) % 60 == 0:
                logger.error(f"上传传感器数据失败: {e}")


