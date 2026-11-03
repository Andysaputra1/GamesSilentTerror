@echo off
rem Ukur lama otak NPC (NLU, fuzzy, NLG lewat LLM) di backend lewat simulasi panel.
rem Game hanya memakai Fuzzy; Utility AI dan Behavior Tree diarsipkan di ..\arsip_bt_utility_2026-11-03 (di luar repo).
rem Hasil lama (waktu dan keseimbangan) diukur dengan metode campuran, jadi belum berlaku untuk Fuzzy saja.
rem Butuh login panel yang sudah disimpan jalankan.bat. Hasil CSV di communicationfolder\uji-waktu-TANGGAL.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrip\uji-waktu.ps1" %*
echo.
pause
