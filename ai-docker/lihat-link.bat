@echo off
rem Tampilkan link tunnel terbaru dan token tanpa menyalakan ulang apa pun.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrip\lihat-link.ps1"
echo.
pause
