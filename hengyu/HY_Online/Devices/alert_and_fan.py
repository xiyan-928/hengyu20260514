import random
import logging
from typing import Optional, Tuple

from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from .modbus_ephemeral import run_ephemeral
from modbus_logging import elapsed_ms, log_modbus_event, mock_modbus_context, modbus_context, now_ms

logger = logging.getLogger(__name__)

# Global variable to store mock fan speed
_mock_fan_speed = 0


def read_alert_message(
    ip: Optional[str],
    port: Optional[int],
    d_pos: int,
    mock_mode: bool = False,
    unit: int = 1,
) -> bool:
    """报警输入：短连接 read_discrete_inputs 读取 IO 模块输入点。"""
    if mock_mode:
        result = random.random() < 0.05
        log_modbus_event(
            operation="read_discrete_inputs",
            ip=ip,
            port=port,
            unit=unit,
            address=d_pos,
            count=1,
            success=True,
            result={"alarm": result},
            context=mock_modbus_context(
                source="mock_alert_and_fan",
                request_name="read_alert_message",
            ),
        )
        return result

    assert ip is not None and port is not None
    context = modbus_context(
        source="alert_and_fan",
        request_name="read_alert_message",
    )

    def _work(client: ModbusTcpClient) -> bool:
        started_ms = now_ms()
        rr = client.read_discrete_inputs(d_pos, 1, unit=unit)
        if rr.isError():
            log_modbus_event(
                operation="read_discrete_inputs",
                ip=ip,
                port=int(port),
                unit=unit,
                address=d_pos,
                count=1,
                success=False,
                error=str(rr),
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            logger.warning(f"read_discrete_inputs 报警失败 address={d_pos} unit={unit}: {rr}")
            return False
        result = bool(rr.bits[0])
        log_modbus_event(
            operation="read_discrete_inputs",
            ip=ip,
            port=int(port),
            unit=unit,
            address=d_pos,
            count=1,
            success=True,
            result={"bits": list(rr.bits), "alarm": result},
            elapsed_ms_value=elapsed_ms(started_ms),
            context=context,
        )
        return result

    return run_ephemeral(ip, int(port), _work, context=context)


def get_current_speed(
    ip: Optional[str],
    port: Optional[int],
    fan_unit: int = 7,
    mock_mode: bool = False,
) -> int:
    speed, _, _ = get_current_speed_with_status(
        ip=ip,
        port=port,
        fan_unit=fan_unit,
        mock_mode=mock_mode,
    )
    return speed


def get_current_speed_with_status(
    ip: Optional[str],
    port: Optional[int],
    fan_unit: int = 7,
    mock_mode: bool = False,
) -> Tuple[int, bool, Optional[str]]:
    if mock_mode:
        global _mock_fan_speed
        log_modbus_event(
            operation="read_holding_registers",
            ip=ip,
            port=port,
            unit=fan_unit,
            address=3,
            count=1,
            success=True,
            result={"fan_speed": _mock_fan_speed},
            context=mock_modbus_context(
                source="mock_alert_and_fan",
                request_name="get_current_speed",
            ),
        )
        return _mock_fan_speed, True, None

    assert ip is not None and port is not None
    context = modbus_context(
        source="alert_and_fan",
        request_name="get_current_speed",
    )

    def _work(client: ModbusTcpClient) -> Tuple[int, bool, Optional[str]]:
        started_ms = now_ms()
        v = client.read_holding_registers(3, 1, unit=fan_unit)
        if v.isError():
            error = str(v)
            log_modbus_event(
                operation="read_holding_registers",
                ip=ip,
                port=int(port),
                unit=fan_unit,
                address=3,
                count=1,
                success=False,
                error=error,
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            logger.warning(f"read_holding_registers 风扇速度失败 unit={fan_unit}: {error}")
            return 0, False, error
        speed = v.registers[0]
        log_modbus_event(
            operation="read_holding_registers",
            ip=ip,
            port=int(port),
            unit=fan_unit,
            address=3,
            count=1,
            success=True,
            result={"registers": list(v.registers), "fan_speed": speed},
            elapsed_ms_value=elapsed_ms(started_ms),
            context=context,
        )
        return speed, True, None

    return run_ephemeral(ip, int(port), _work, context=context)


def get_new_fan_speed(
    current_temp,
    current_speed,
    start_temp=30.0,
    stop_temp=20.0,
    k_factor=5,
    min_speed=50,
    max_speed=100,
) -> int:
    """
    Calculate new fan speed based on hysteresis logic and linear control.

    Logic Rules:
    1. Temp < stop_temp: Stop (Speed = 0)
    2. Temp > start_temp: Start (Speed = min_speed + k * (temp - start_temp))
    3. stop_temp <= Temp <= start_temp (Hysteresis Zone):
       - If currently running (speed > 0), maintain at least min_speed or current speed
       - If currently stopped (speed == 0), stay stopped
    """

    if current_temp < stop_temp:
        return 0

    if current_temp > start_temp:
        temp_diff = current_temp - start_temp
        calculated_speed = min_speed + int(k_factor * temp_diff)
        logger.debug(
            f"Minspeed: {min_speed}, Maxspeed: {max_speed}, Calculatedspeed: {calculated_speed}, "
            f"K: {k_factor}, Tempdiff: {temp_diff}, Currenttemp: {current_temp}, Starttemp: {start_temp}"
        )

        return max(min_speed, min(max_speed, calculated_speed))

    if current_speed > 0:
        return max(min_speed, min(max_speed, current_speed))
    return 0


def set_new_fan_speed(
    ip: Optional[str],
    port: Optional[int],
    new_speed: int,
    fan_unit: int = 7,
    mock_mode: bool = False,
):
    if mock_mode:
        global _mock_fan_speed
        _mock_fan_speed = new_speed
        log_modbus_event(
            operation="write_register",
            ip=ip,
            port=port,
            unit=fan_unit,
            address=3,
            count=1,
            data=[new_speed],
            success=True,
            context=mock_modbus_context(
                source="mock_alert_and_fan",
                request_name="set_new_fan_speed",
            ),
        )
        return True

    assert ip is not None and port is not None
    context = modbus_context(
        source="alert_and_fan",
        request_name="set_new_fan_speed",
    )

    def _work(client: ModbusTcpClient) -> bool:
        started_ms = now_ms()
        response = client.write_register(3, new_speed, unit=fan_unit)
        if response.isError():
            log_modbus_event(
                operation="write_register",
                ip=ip,
                port=int(port),
                unit=fan_unit,
                address=3,
                count=1,
                data=[new_speed],
                success=False,
                error=str(response),
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            raise ModbusException(f"Failed to set fan speed: {response}")
        log_modbus_event(
            operation="write_register",
            ip=ip,
            port=int(port),
            unit=fan_unit,
            address=3,
            count=1,
            data=[new_speed],
            success=True,
            elapsed_ms_value=elapsed_ms(started_ms),
            context=context,
        )
        return True

    return run_ephemeral(ip, int(port), _work, context=context)
