import pymodbus
import struct
from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder
import struct
import time

"""
对于 Modbus TCP，始终必须是 byteorder=Endian.Big, wordorder=Endian.Little,
因为由超过 2 个字节组成的值的字节顺序在协议(protocol)规范中明确指定 OPEN MODBUS/TCP SPECIFICATION(Appendix B. Data Encoding for non-word data) .
"""
builder = BinaryPayloadBuilder(byteorder=Endian.Big, wordorder=Endian.Big)

def test_upload_data():
    client = ModbusTcpClient('192.168.1.20', port=502)
    client.connect()
    builder = BinaryPayloadBuilder(byteorder=Endian.Big, wordorder=Endian.Little)
    # builder.add_32bit_float(0.07)
    # builder.add_32bit_float(0.7)
    # builder.add_32bit_float(7)
    # builder.add_32bit_float(70)
    # builder.add_32bit_float(700)
    # builder.add_32bit_float(7000)
    # builder.add_32bit_float(70000)
    for i in range(12):
        builder.add_32bit_float(i+1)
    payload = builder.build()
    response = client.write_registers(0, payload, unit=1, skip_encode=True) # 使能
    print (response)
    # response = client.write_register(0, 0, unit=1)
    # builder.add_32bit_float(300.0)
    # payload = builder.build()
    # response = client.write_registers(8, payload, unit=1, skip_encode=True)
    client.close()

def test_get_server_data():
    client = ModbusSerialClient(method='rtu', port='COM4', baudrate=9600, timeout=1.0)
    client.connect()
    # response = client.read_input_registers(address=0, count=14, unit=2)
    response = client.read_holding_registers(address=0, count=32, unit=1, skip_encode=True)
    for i in range(0, 32, 2):
        print (get_float_value(response.registers, i))
    client.close()

def single_test_get_server_data():
    client = ModbusSerialClient(method='rtu', port='COM4', baudrate=9600, timeout=1.0)
    client.connect()
    # response = client.read_input_registers(address=0, count=14, unit=2)
    response = client.read_holding_registers(address=4, count=2, unit=1, skip_encode=True)
    for i in range(0, 2, 2):
        print (get_float_value(response.registers, i))
    client.close()

def test_get_server_data2():
    client = ModbusTcpClient('192.168.1.20', port=502)
    client.connect()
    response = client.read_holding_registers(0, 24, unit=1, skip_encode=True) # 使能
    for i in range(0, 24, 2):
        print (get_float_value(response.registers, i))
    # response = client.write_register(0, 0, unit=1)
    # builder.add_32bit_float(300.0)
    # payload = builder.build()
    # response = client.write_registers(8, payload, unit=1, skip_encode=True)
    client.close()

def get_float_value(registers, start_index):
    """
    从 Modbus 返回的寄存器中获取浮点数
    """
    bytes_ddl = struct.pack('<HH', registers[start_index], registers[start_index+1])
    float_value = struct.unpack('<f', bytes_ddl)[0]
    return float_value

def test_valve():
    client = ModbusTcpClient('192.168.1.10', port=502)
    client.connect()
    # response = client.write_coils(0, [0,0,0,0], unit=1)
    # time.sleep(0.5)
    rt = client.read_coils(0, 4, unit=1)
    print (rt.bits)
    # client.write_coil(0, 0, unit=1)
    client.close()
    # response = client.write_register(0, 0, unit=1)
    # builder.add_32bit_float(300.0)
    # payload = builder.build()
    # response = client.write_registers(8, payload, unit=1, skip_encode=True)

# 转485后的查询命令：01 03 00 00 00 0E C4 0E 

if __name__ == '__main__':
    test_valve()
    # test_upload_data()
    # time.sleep(2)
    # test_get_server_data2()
