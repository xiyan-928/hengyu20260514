import ctypes

libwrapper = ctypes.CDLL('/usr/local/lib/libwrapper.so', mode=ctypes.RTLD_GLOBAL)

# Define the function prototypes
libwrapper.Init.argtypes = [ctypes.c_int]
libwrapper.Init.restype = ctypes.c_int

libwrapper.Open.argtypes = [ctypes.c_int]
libwrapper.Open.restype = ctypes.c_int

libwrapper.GetSerialNumber.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char)]
libwrapper.GetSerialNumber.restype = ctypes.c_int

libwrapper.SetIntegrationTime.argtypes = [ctypes.c_int, ctypes.c_double]
libwrapper.SetIntegrationTime.restype = ctypes.c_int

libwrapper.SetAverageTime.argtypes = [ctypes.c_int, ctypes.c_int]
libwrapper.SetAverageTime.restype = ctypes.c_int

libwrapper.GetWavelengthsNumber.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
libwrapper.GetWavelengthsNumber.restype = ctypes.c_int

libwrapper.GetWavelengths.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
libwrapper.GetWavelengths.restype = ctypes.c_int

libwrapper.GetScopes.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ushort)]
libwrapper.GetScopes.restype = ctypes.c_int

libwrapper.ReadBytes.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
libwrapper.ReadBytes.restype = ctypes.c_int

# Define a Python class to wrap the functions
class Wrapper:
    def __init__(self):
        pass

    def init(self, commType):
        return libwrapper.Init(commType)

    def open(self, index):
        return libwrapper.Open(index)

    def get_serial_number(self, index):
        serial_number = ctypes.create_string_buffer(8)
        ret = libwrapper.GetSerialNumber(index, serial_number)
        return ret, serial_number.value.decode()

    def set_integration_time(self, index, integration_time_ms):
        return libwrapper.SetIntegrationTime(index, integration_time_ms)

    def set_average_time(self, index, average_time):
        return libwrapper.SetAverageTime(index, average_time)

    def get_wavelengths_number(self, index):
        number = ctypes.c_int()
        ret = libwrapper.GetWavelengthsNumber(index, ctypes.byref(number))
        return ret, number.value

    def get_wavelengths(self, index):
        wls = (ctypes.c_float * 2048)()
        ret = libwrapper.GetWavelengths(index, wls)
        return ret, [wls[i] for i in range(2048)]

    def get_scopes(self, index):
        scopes = (ctypes.c_ushort * 2048)()
        ret = libwrapper.GetScopes(index, scopes)
        return ret, [scopes[i] for i in range(2048)]

    def read_bytes(self, index, size):
        buf = ctypes.create_string_buffer(size)
        ret = libwrapper.ReadBytes(index, buf, size)
        return ret, buf.value

# Create an instance of the Wrapper class
wrapper = Wrapper()

# Test
# when connected just one spectrometer, set the device index as 0
index = 0

# Open the device (assuming index 0)
ret = wrapper.init(index)
if ret < 0:
    print("Error opening device")
else:
    print("Connected device number is:", ret)

ret = wrapper.open(index)
if ret < 0:
    print("Error opening device")
else:
    print("Open successful")    

# Get the serial number
ret, serial_number = wrapper.get_serial_number(index)
if ret < 0:
    print("Error getting serial number")
else:
    print("Serial number:", serial_number)


# Set integration time to 100ms
ret = wrapper.set_integration_time(index, 100)    
if ret < 0:
    print("Error setting integration time")
else:
    print("Set integration time successful")    

# Set average times to 5
ret = wrapper.set_average_time(index, 5)    
if ret < 0:
    print("Error setting average time")
else:
    print("Set average time successful")      

# Get wavelengths
ret, wavelengths = wrapper.get_wavelengths(index)
if ret < 0:
    print("Error getting wavelengths")
else:
    print("Get wavelengths successful")    

# Get scopes
ret, scopes = wrapper.get_scopes(0)
if ret < 0:
    print("Error getting scopes")
else:
    print("Get scopes successful")  

# Print scopes from 500-505 table index
print("Wavelength and Scopes from 500-505 pixel range:")
for i in range(500, 505):
    print("{:.2f}: {}".format(wavelengths[i], scopes[i]))    