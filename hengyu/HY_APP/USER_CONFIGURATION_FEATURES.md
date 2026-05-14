# HY App - User Configuration Features

## Overview
The HY App has been successfully enhanced with user configuration features that allow customers to customize CDS350 parameters and choose custom data storage directories.

## New Features

### 1. CDS350 Parameter Configuration
- **Integration Time**: Users can now set custom integration time values (in microseconds)
  - Range: 1,000 to 1,000,000 μs
  - Default: 10,000 μs
- **Scans to Average**: Users can configure the number of scans to average
  - Range: 1 to 100 scans
  - Default: 3 scans

### 2. Custom Data Storage Directory
- **Default Behavior**: Data is saved to `Documents/HY_Data/` with monthly subdirectories (YYMM format)
- **Custom Directory**: Users can select a custom directory for data storage
- **Persistence**: The app remembers the user's directory choice between sessions
- **Automatic Creation**: Monthly subdirectories are automatically created in the selected path

### 3. Settings Management
- **Persistent Storage**: All user preferences are saved using SharedPreferences
- **Automatic Loading**: Settings are loaded when the app starts
- **Real-time Updates**: Changes to CDS350 parameters take effect immediately

## Technical Implementation

### Files Modified/Created:
1. **lib/services/settings_service.dart** (NEW)
   - Manages user preferences storage and retrieval
   - Handles integration time, scans to average, and custom directory settings

2. **lib/screens/settings_screen.dart** (NEW)
   - Provides user interface for configuration
   - Form validation for parameter ranges
   - Directory picker integration

3. **lib/services/file_service.dart** (UPDATED)
   - Enhanced to support custom directory selection
   - Maintains backward compatibility with default directories

4. **lib/providers/spectrum_provider.dart** (UPDATED)
   - Added initialization method to load user settings
   - Automatic persistence of parameter changes

5. **lib/screens/main_screen.dart** (UPDATED)
   - Added settings button in app bar
   - Initialize user settings on app startup

6. **pubspec.yaml** (UPDATED)
   - Added `file_picker: ^8.0.0+1` dependency for directory selection

### Key Features:
- **Cross-platform Compatibility**: Works on Windows, Android, and other platforms
- **Error Handling**: Comprehensive validation and error messages
- **User Experience**: Intuitive interface with clear feedback
- **Data Integrity**: Safe handling of directory paths and parameter validation

## Usage Instructions

### Accessing Settings:
1. Click the settings icon (⚙️) in the top-right corner of the main screen
2. The Settings screen will open with current configuration

### Configuring CDS350 Parameters:
1. In the "CDS350 Configuration" section:
   - Enter desired **Integration Time** (1,000 - 1,000,000 μs)
   - Enter desired **Scans to Average** (1 - 100)
2. Click "Save" to apply changes

### Setting Custom Data Directory:
1. In the "Data Storage" section:
   - Toggle "Use Custom Directory" switch ON
   - Click "Browse" to select your preferred directory
   - The selected path will be displayed in the text field
2. Click "Save" to apply changes

### Default Settings:
- Integration Time: 10,000 μs
- Scans to Average: 3
- Data Directory: Documents/HY_Data/ (Windows)

## Data Storage Structure
```
Selected Directory/
├── 2412/           # December 2024
│   ├── 2024-12-15-SPEC-143022.csv
│   ├── 2024-12-15-SENSOR.csv
│   └── ...
├── 2501/           # January 2025
│   └── ...
└── ...
```

## Validation Rules
- **Integration Time**: Must be between 1,000 and 1,000,000 microseconds
- **Scans to Average**: Must be between 1 and 100
- **Custom Directory**: Must be a valid, accessible directory path

## Benefits
1. **Flexibility**: Users can optimize CDS350 settings for their specific measurement needs
2. **Data Organization**: Custom directory selection allows integration with existing data management workflows
3. **Persistence**: Settings are remembered between app sessions
4. **User Experience**: Clear, intuitive interface with validation feedback

## Backend Compatibility
The enhanced frontend is fully compatible with the existing FastAPI backend:
- All API endpoints remain unchanged
- CDS350 configuration parameters are passed correctly to the backend
- Data collection and storage continue to work seamlessly

## Future Enhancements
Potential areas for future development:
- Preset configurations for common measurement scenarios
- Export/import of settings
- Advanced data organization options
- Real-time parameter adjustment during measurements
