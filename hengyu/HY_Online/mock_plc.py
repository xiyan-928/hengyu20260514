import logging
import threading
import time
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext

# 配置日志
logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.INFO)

def run_server():
    # 初始化数据存储
    # unit_id=1
    # holding registers (hr) 初始值为0
    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [1]*100),
        co=ModbusSequentialDataBlock(0, [1]*100),
        hr=ModbusSequentialDataBlock(0, [1]*100),
        ir=ModbusSequentialDataBlock(0, [1]*100))
    
    context = ModbusServerContext(slaves=store, single=True)
    
    # 启动用户输入监听线程
    def input_listener():
        address = 1
        print("输入 0 或 1 来控制寄存器值 (输入 q 退出控制):")
        while True:
            try:
                user_input = input()
                if user_input.lower() == 'q':
                    break
                
                if user_input in ['0', '1']:
                    value = int(user_input)
                    print(f"手动控制: 更新寄存器 {address} 值为 {value}")
                    # fx=3 表示 Holding Register
                    store.setValues(3, address, [value])
                else:
                    print("无效输入，请输入 0 或 1")
            except EOFError:
                print("非交互模式，停止输入监听")
                break
            except Exception as e:
                print(f"输入处理错误: {e}")

    t = threading.Thread(target=input_listener)
    t.daemon = True
    t.start()

    print("启动模拟PLC Modbus TCP服务器...")
    print("地址: localhost:5020")
    print("Unit ID: 1")
    print("Monitor Register: 1 (对应 hr[1])")
    print("提示: 使用 Modbus Poll 或类似工具连接修改寄存器值来测试自动控制")
    
    # 启动服务器
    StartTcpServer(context, address=("localhost", 5020))

if __name__ == "__main__":
    run_server()


