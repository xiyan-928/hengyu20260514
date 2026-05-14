# 电导率电极调试
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder

import struct
import os
"""
对于 Modbus TCP，始终必须是 byteorder=Endian.Big, wordorder=Endian.Little,
因为由超过 2 个字节组成的值的字节顺序在协议(protocol)规范中明确指定 OPEN MODBUS/TCP SPECIFICATION(Appendix B. Data Encoding for non-word data) .
"""

import csv
import json
import time, datetime

def read_ph_value():
    client = ModbusTcpClient('192.168.1.15', port=502)
    client.connect()
    response = client.read_holding_registers(0x2003, 1, unit=10)
    print (response.registers)
    client.close()
    
def get_temp_list():
    client = ModbusTcpClient('192.168.1.15', port=502, timeout=1.0)
    client.connect()
    suc = False
    while not suc:
        try:
            response = client.read_input_registers(address=0, count=2, unit=20)
            # print (response.registers)
            nv1 = response.registers[0]/100
            nv2 = response.registers[1]/100
            # temp_list=  list(map(transform_ua, response.registers))
            # print (temp_list)
            client.close()
            suc = True
        except:
            time.sleep(0.1)
            suc = False
        # client.close()
    client.close()
    return nv1, nv2

def read_ddl():
    client = ModbusTcpClient('192.168.1.15', port=502)
    client.connect()
    response = client.read_holding_registers(address=15, count=4, unit=5)
    # print (response.registers)
    a1, a2 = response.registers
    v = (a1*65536 + a2 ) / 1000
    # bytes_ddl = struct.pack('<HH', response.registers[0], response.registers[1])
    # float_value = struct.unpack('<f', bytes_ddl)[0]
    client.close()
    return v

if __name__ == "__main__":
    # 20： 12.80
    # 90： 79.53
    # Interval config
    # n = get_pt100()
    # print (get_temp_list())
    # print (n)
    print (read_ddl())
    # read_ph_value()
    # j_file = "./modbus_config.json"
    # if not os.path.exists("./modbus_config.json"):
    #     j_dict = {
    #        "interval": 5000,
    #     }
    #     with open(j_file, 'w') as f:
    #         json.dump(j_dict, f)
    # with open(j_file, 'r') as f:
    #     j_dict = json.load(f)
    # time_interval = j_dict["interval"]
    # #
    # while True:
    #     # pt100_temp = get_pt100()
    #     ddl = read_ddl()
    #     current_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    #     file_date = datetime.datetime.now().strftime('%Y-%m-%d')
    #     with open("./modbus-%s.csv" % file_date, 'a', newline='') as csvfile:
    #         csvwriter = csv.writer(csvfile)
    #         csvwriter.writerow([current_date, pt100_temp, ddl])
    #         print (current_date, pt100_temp, ddl)
    #     time.sleep(time_interval/1000)
        