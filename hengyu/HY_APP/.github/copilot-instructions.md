# Copilot Instructions for HY Data Acquisition System

This workspace contains a dual-stack application: a **Flutter frontend** (`HY_APP`) and a **Python FastAPI backend** (`HY_Online`).

## 🏗 Project Structure & Architecture

### HY_APP (Flutter)
- **State Management**: Uses `Provider` pattern. Root `MultiProvider` is defined in `lib/main.dart`.
- **Service Layer** (`lib/services/`): Handles external communication and IO.
  - `api_service.dart`: REST communication with `HY_Online`.
  - `isolate_service.dart` & `lib/workers/`: Manages `Isolate`-based background processing for heavy data tasks (Spectrum/Sensor data).
  - `spc_file_handler.dart`: Specialized handling for SPC file formats.
- **Providers** (`lib/providers/`): Business logic layer. `SensorProvider` and `SpectrumProvider` are central.
- **UI**: "White theme" convention. Screens in `lib/screens/`.

### HY_Online (Python)
- **Framework**: `FastAPI` (via `fastapi_offline`).
- **Hardware Abstraction**: `Devices/` directory contains hardware drivers.
  - `device_factory.py`: Factory pattern to switch between `mock` and `real` hardware based on `DEVICE_MODE`.
- **Entry Points**:
  - `start.py`: Starts server in **MOCK** mode (`DEVICE_MODE="mock"`).
  - `start_real.py`: Starts server in **REAL** mode.

## 🛠 Critical Workflows

### Running the System
1. **Backend**: Always start the backend first.
   - Mock Mode (Dev): `python HY_Online/start.py`
   - Real Mode (Prod): `python HY_Online/start_real.py`
   - Server runs on `http://0.0.0.0:8000`.
2. **Frontend**:
   - `cd HY_APP`
   - `flutter run`

### Data & File Conventions
- **Spectrum Data**: Saved as `YYYY-MM-DD-SPEC-ID.csv`.
- **Sensor Data**: Aggregated daily in `YYYY-MM-DD-SENSOR.csv`.
- **Directory Structure**: Organized by month (`YYMM`, e.g., `2507`).
- **SPC Files**: Handled via `spc_file_processor.py` (Backend) and `spc_file_handler.dart` (Frontend).

## 🧩 Coding Patterns & Guidelines

### Flutter
- **Concurrency**: Do NOT perform heavy data processing on the main thread. Use the existing `worker` infrastructure (`sensor_worker.dart`, `spectrum_worker.dart`).
- **API Calls**: Use `api_service.dart` for all backend interactions. Do not hardcode HTTP calls in widgets.
- **State Updates**: When updating `SpectrumProvider` or `SensorProvider`, ensure `notifyListeners()` is called appropriately to trigger UI updates.

### Python
- **Device Mode**: Always check `app_config` or `os.environ["DEVICE_MODE"]` before attempting hardware operations.
- **Path Handling**: `Devices/` is dynamically added to `sys.path` in `main.py`. Respect this import structure.
- **FastAPI**: Use `FastAPIOffline` instead of standard `FastAPI` to ensure compatibility in offline deployments.

## 🧪 Testing
- **Flutter**: `flutter test` for unit tests. Integration tests typically require the mock backend running.
- **Python**: `pytest` (if configured) or run `final_test.py` / `fix_main.py` for specific component verification.
