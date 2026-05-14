# HY Data Acquisition App

A Flutter mobile application for real-time data acquisition from CDS350 spectrometer and HY Modbus sensors.

## Features

- **Real-time Spectrum Collection**: Continuous data acquisition from CDS350 spectrometer
- **Multi-sensor Support**: Simultaneous data collection from multiple HY Modbus sensors (pH, Temperature, Dissolved Oxygen, etc.)
- **Multi-threaded Architecture**: Independent data collection threads for spectrum and sensor data
- **Automated CSV Export**: 
  - Spectrum data: Individual files (`YYYY-MM-DD-SPEC-ID.csv`)
  - Sensor data: Daily aggregated files (`YYYY-MM-DD-SENSOR.csv`)
  - Organized in monthly directories (`YYMM` format)
- **Real-time Visualization**: Interactive spectrum charts and sensor data displays
- **White Theme UI**: Clean, professional interface design
- **Device Management**: Easy connection and configuration of devices

## Installation

### Prerequisites
- Flutter SDK (3.8.1 or later)
- Running FastAPI server for device communication

### Setup
1. Install dependencies: `flutter pub get`
2. Generate code: `flutter packages pub run build_runner build`
3. Run: `flutter run`

## Usage

1. **Initialize Devices**: App automatically initializes on startup
2. **Start Collection**: Use control panel to start/stop data acquisition
3. **Monitor Data**: View real-time spectrum and sensor readings
4. **Export Data**: Files are automatically saved during collection
5. **Exit Safely**: Use the power button to stop all collection and close devices
