@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet. Run INSTALL.bat first.
  pause
  exit /b 1
)

echo Starting Smart Glasses GUI in Pi discovery / WiFi stream mode.
echo Start the Pi stream service first, then click Find Glasses.
".venv\Scripts\python.exe" dual_cam_gui_safe.py --camera-backend mjpeg
