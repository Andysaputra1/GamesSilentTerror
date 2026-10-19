# Dipanggil lihat-link.bat: tampilkan status container, link tunnel terbaru, dan token tanpa menyalakan ulang apa pun,
# lalu kirim link itu ke backend (berguna bila Docker menyalakan ulang tunnel sendiri, mis. setelah laptop restart).

$folder = Split-Path $PSScriptRoot -Parent
Set-Location $folder
. (Join-Path $PSScriptRoot 'bersama.ps1')

docker compose ps -a
$link = Cari-Link
$token = Baca-Env 'LLM_TOKEN'

Write-Host ''
Write-Host "Token : $(if ($token) { $token } else { 'belum dibuat' })" -ForegroundColor Cyan
if ($link) {
    try { Set-Clipboard -Value $link } catch {}
    Write-Host "Link  : $link  (disalin ke clipboard)" -ForegroundColor Cyan
    Write-Host ''
    & (Join-Path $PSScriptRoot 'kirim-link.ps1') -Link $link
} else {
    Write-Host 'Link  : belum ada. Jalankan jalankan.bat dulu.' -ForegroundColor Yellow
}
