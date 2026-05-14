import numpy as np
from Devices.get_spc import write_spc

x = np.linspace(200, 800, 1024)
y = np.random.rand(1024)
print(write_spc(x, y))
