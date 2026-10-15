@echo off
rem Nyalakan LLM (Qwen3 4B) + tunnel untuk VM. Klik dua kali, atau jalankan dari terminal.
title Silent Terror - LLM Docker
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrip\jalankan.ps1"
set "KODE=%ERRORLEVEL%"
echo.
pause
exit /b %KODE%
