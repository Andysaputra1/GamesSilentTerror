@echo off
rem Matikan LLM dan tunnel. Model tetap tersimpan di volume silent_terror_ai_model (tidak diunduh ulang).
cd /d "%~dp0"
docker compose down
echo.
echo LLM dan tunnel dimatikan. Bot di VM akan memakai jalur berikutnya / templat sampai dinyalakan lagi.
pause
