@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet. Run INSTALL.bat first.
  pause
  exit /b 1
)

if not exist "out" mkdir out

echo Starting Smart Glasses GUI in local USB camera / ESP32 serial mode.
echo Tip: Close Arduino Serial Monitor/Plotter if ESP32 won't connect.
".venv\Scripts\python.exe" dual_cam_gui_safe.py --camera-backend opencv
