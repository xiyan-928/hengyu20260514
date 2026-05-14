from abc import ABC, abstractmethod
from pymodbus.client.sync import ModbusTcpClient
import logging

from .modbus_ephemeral import run_ephemeral
from modbus_logging import elapsed_ms, log_modbus_event, modbus_context, now_ms

logger = logging.getLogger(__name__)


class BaseSensorDriver(ABC):
    """传感器驱动：每次 read 在内部对 ip:port 建立短连接并完成读数。"""

    @abstractmethod
    def read(self, ip: str, port: int, params: dict) -> dict:
        """
        Read data from sensor (ephemeral Modbus connection per call).

        Args:
            ip: Modbus TCP 主机
            port: 端口
            params: 该传感器参数（unit、address 等）

        Returns:
            读到的键值字典（如 ddl / ph / pt100 等）
        """
        pass


class DefaultDDLDriver(BaseSensorDriver):
    """Default driver for DDL sensor"""

    def read(self, ip: str, port: int, params: dict) -> dict:
        unit = params.get("unit", 8)
        address = params.get("address", 3)
        context = modbus_context(
            source="sensor_driver",
            request_name="sensor_read",
            driver_name="DefaultDDL",
            sensor_name="DDL",
        )

        def _work(client: ModbusTcpClient) -> dict:
            started_ms = now_ms()
            response = client.read_holding_registers(address, 2, unit=unit)
            if response.isError():
                log_modbus_event(
                    operation="read_holding_registers",
                    ip=ip,
                    port=int(port),
                    unit=unit,
                    address=address,
                    count=2,
                    success=False,
                    error=str(response),
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=context,
                )
                logger.warning(f"DDL read error: {response}")
                return {}

            ddl = (response.registers[0] * 65536 + response.registers[1]) / 100
            log_modbus_event(
                operation="read_holding_registers",
                ip=ip,
                port=int(port),
                unit=unit,
                address=address,
                count=2,
                success=True,
                result={"registers": list(response.registers), "ddl": ddl},
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            return {"ddl": ddl}

        return run_ephemeral(ip, port, _work, context=context)


class DefaultPHDriver(BaseSensorDriver):
    """Default driver for PH sensor (includes Temperature)"""

    def read(self, ip: str, port: int, params: dict) -> dict:
        unit = params.get("unit", 9)
        address = params.get("address", 6)
        context = modbus_context(
            source="sensor_driver",
            request_name="sensor_read",
            driver_name="DefaultPH",
            sensor_name="PH",
        )

        def _work(client: ModbusTcpClient) -> dict:
            started_ms = now_ms()
            response = client.read_holding_registers(address, 2, unit=unit)
            if response.isError():
                log_modbus_event(
                    operation="read_holding_registers",
                    ip=ip,
                    port=int(port),
                    unit=unit,
                    address=address,
                    count=2,
                    success=False,
                    error=str(response),
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=context,
                )
                logger.warning(f"PH read error: {response}")
                return {}

            ph_temp = response.registers[0] / 10
            ph = response.registers[1] / 100
            log_modbus_event(
                operation="read_holding_registers",
                ip=ip,
                port=int(port),
                unit=unit,
                address=address,
                count=2,
                success=True,
                result={
                    "registers": list(response.registers),
                    "ph": ph,
                    "ph_temp": ph_temp,
                },
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            return {"ph": ph, "ph_temp": ph_temp}

        return run_ephemeral(ip, port, _work, context=context)


class DefaultPT100Driver(BaseSensorDriver):
    """Default driver for PT100 Temperature sensor"""

    def read(self, ip: str, port: int, params: dict) -> dict:
        unit = params.get("unit", 20)
        address = params.get("address", 0)
        context = modbus_context(
            source="sensor_driver",
            request_name="sensor_read",
            driver_name="DefaultPT100",
            sensor_name="PT100",
        )

        def _work(client: ModbusTcpClient) -> dict:
            started_ms = now_ms()
            response = client.read_input_registers(address, 2, unit=unit)
            if response.isError():
                log_modbus_event(
                    operation="read_input_registers",
                    ip=ip,
                    port=int(port),
                    unit=unit,
                    address=address,
                    count=2,
                    success=False,
                    error=str(response),
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=context,
                )
                logger.warning(f"PT100 read error: {response}")
                return {}

            pt100 = response.registers[0] / 100.0
            log_modbus_event(
                operation="read_input_registers",
                ip=ip,
                port=int(port),
                unit=unit,
                address=address,
                count=2,
                success=True,
                result={"registers": list(response.registers), "pt100": pt100},
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            return {"pt100": pt100}

        return run_ephemeral(ip, port, _work, context=context)


class PLCBasedPT100Driver(BaseSensorDriver):
    """PT100 via PLC holding registers (single register /10 °C)."""

    def read(self, ip: str, port: int, params: dict) -> dict:
        unit = params.get("unit", 20)
        address = params.get("address", 500)
        context = modbus_context(
            source="sensor_driver",
            request_name="sensor_read",
            driver_name="PLCBasedPT100",
            sensor_name="PT100",
        )

        def _work(client: ModbusTcpClient) -> dict:
            started_ms = now_ms()
            response = client.read_holding_registers(address, 2, unit=unit)
            if response.isError():
                log_modbus_event(
                    operation="read_holding_registers",
                    ip=ip,
                    port=int(port),
                    unit=unit,
                    address=address,
                    count=2,
                    success=False,
                    error=str(response),
                    elapsed_ms_value=elapsed_ms(started_ms),
                    context=context,
                )
                logger.warning(f"PT100 read error: {response}")
                return {}

            pt100 = response.registers[0] / 10.0
            log_modbus_event(
                operation="read_holding_registers",
                ip=ip,
                port=int(port),
                unit=unit,
                address=address,
                count=2,
                success=True,
                result={"registers": list(response.registers), "pt100": pt100},
                elapsed_ms_value=elapsed_ms(started_ms),
                context=context,
            )
            return {"pt100": pt100}

        return run_ephemeral(ip, port, _work, context=context)


class DriverFactory:
    """Factory to create driver instances"""

    _drivers = {
        "DefaultDDL": DefaultDDLDriver,
        "DefaultPH": DefaultPHDriver,
        "DefaultPT100": DefaultPT100Driver,
        "PLCBasedPT100": PLCBasedPT100Driver,
    }

    @classmethod
    def register(cls, name: str, driver_class):
        cls._drivers[name] = driver_class

    @classmethod
    def create(cls, name: str) -> BaseSensorDriver:
        driver_class = cls._drivers.get(name)
        if not driver_class:
            raise ValueError(f"Driver '{name}' not found")
        return driver_class()

    @classmethod
    def get_available_drivers(cls):
        return list(cls._drivers.keys())
