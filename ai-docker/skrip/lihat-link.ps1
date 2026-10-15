# Dipanggil lihat-link.bat: tampilkan status container, link tunnel terbaru, dan token tanpa menyalakan ulang apa pun.

$folder = Split-Path $PSScriptRoot -Parent
Set-Location $folder

docker compose ps -a
$log = (cmd /c "docker logs silent_terror_tunnel 2>&1") -join "`n"
$semua = [regex]::Matches($log, 'https://[a-z0-9-]+\.trycloudflare\.com')
$token = if (Test-Path .env) { ((Get-Content .env | Where-Object { $_ -match '^LLM_TOKEN=' }) -replace '^LLM_TOKEN=', '') } else { '' }

Write-Host ''
if ($semua.Count -gt 0) {
    $link = $semua[$semua.Count - 1].Value
    try { Set-Clipboard -Value $link } catch {}
    Write-Host "Link  : $link  (disalin ke clipboard)" -ForegroundColor Cyan
} else {
    Write-Host 'Link  : belum ada. Jalankan jalankan.bat dulu.' -ForegroundColor Yellow
}
Write-Host "Token : $(if ($token) { $token } else { 'belum dibuat' })" -ForegroundColor Cyan
