@echo off
rem Ukur lama otak NPC (NLU, behavior tree / fuzzy / utility AI, NLG lewat LLM) di backend lewat simulasi panel.
rem Butuh login panel yang sudah disimpan jalankan.bat. Hasil CSV di communicationfolder\uji-waktu-TANGGAL.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrip\uji-waktu.ps1" %*
echo.
pause
