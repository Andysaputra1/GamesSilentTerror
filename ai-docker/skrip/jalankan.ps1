# Dipanggil jalankan.bat. Menyalakan Ollama (Qwen3 4B) + gerbang token + Cloudflare quick tunnel,
# menunggu model siap, menguji link dari internet, lalu menampilkan link dan token untuk VM.
# Sengaja hanya karakter ASCII: PowerShell 5.1 membaca .ps1 tanpa BOM sebagai ANSI.

$ErrorActionPreference = 'Stop'
$folder = Split-Path $PSScriptRoot -Parent
Set-Location $folder
. (Join-Path $PSScriptRoot 'bersama.ps1')  # Baca-Env, Cari-Link

function Tulis($teks, $warna = 'Gray') { Write-Host $teks -ForegroundColor $warna }
function Gagal($teks) { Tulis "[x] $teks" Red; exit 1 }

# 1. Docker harus hidup.
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Gagal 'Docker belum jalan. Buka Docker Desktop, tunggu "Engine running", lalu jalankan lagi.' }

# 2. Token dibuat sekali dan disimpan di .env (tidak masuk Git).
if (-not (Test-Path .env)) {
    $acak = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($acak)
    $token = [BitConverter]::ToString($acak).Replace('-', '').ToLower()
    @(
        '# Dibuat otomatis oleh jalankan.bat. Jangan di-commit.',
        '# LLM_TOKEN dikirim ke backend (Konfigurasi AI panel) otomatis oleh jalankan.bat.',
        "LLM_TOKEN=$token",
        'LLM_MODELS=qwen3:4b-instruct qwen3:14b'
    ) | Set-Content .env -Encoding ascii
    Tulis '[+] Token baru dibuat di ai-docker\.env' Green
}
$token = Baca-Env 'LLM_TOKEN' ''
$modelSemua = Baca-Env 'LLM_MODELS' 'qwen3:4b-instruct qwen3:14b'
$model = ($modelSemua -split '\s+')[0]  # model pertama dipakai untuk tes chat
if (-not $token) { Gagal 'LLM_TOKEN di ai-docker\.env kosong. Hapus file .env lalu jalankan lagi.' }

# 3. GPU NVIDIA dipakai bila ada; kalau Docker tidak bisa memakainya, jatuh ke CPU.
$berkas = @('-f', 'docker-compose.yml')
$gpu = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    cmd /c "nvidia-smi >nul 2>&1"
    $gpu = ($LASTEXITCODE -eq 0)
}
if ($gpu) { $berkas += @('-f', 'docker-compose.gpu.yml') }
# Keluaran compose ditangkap supaya hanya error GPU yang memicu pindah ke CPU.
function Naikkan($berkas) {
    $keluar = cmd /c ("docker compose " + ($berkas -join ' ') + " up -d 2>&1")
    $kode = $LASTEXITCODE
    $keluar | ForEach-Object { Write-Host $_ }
    return @{ Kode = $kode; Teks = ($keluar -join "`n") }
}
Tulis ("[ ] Menyalakan container (" + $(if ($gpu) { 'GPU NVIDIA' } else { 'CPU' }) + ', model ' + $modelSemua + ')...')
$hasil = Naikkan $berkas
if ($hasil.Kode -ne 0 -and $gpu -and $hasil.Teks -match '(?i)nvidia|gpu|device driver|could not select device') {
    Tulis '[!] GPU tidak bisa dipakai Docker; mencoba CPU (lebih lambat).' Yellow
    $gpu = $false
    $berkas = @('-f', 'docker-compose.yml')
    $hasil = Naikkan $berkas
}
if ($hasil.Kode -ne 0) { Gagal 'docker compose up gagal. Lihat pesan di atas.' }

# 4. Tunggu model terunduh dan termuat (pertama kali sekitar 2,5 GB).
Tulis '[ ] Menyiapkan model (pertama kali mengunduh, bisa beberapa menit)...'
$idModel = (docker compose @berkas ps -a -q model | Select-Object -First 1)
if (-not $idModel) { Gagal 'Container model tidak ditemukan.' }
docker logs -f $idModel
$kode = (docker inspect -f '{{.State.ExitCode}}' $idModel).Trim()
if ($kode -ne '0') { Gagal "Model gagal disiapkan (kode $kode). Cek koneksi internet lalu jalankan lagi." }

# 5. Tunggu link tunnel.
Tulis '[ ] Menunggu link Cloudflare...'
$link = $null
for ($i = 0; $i -lt 45 -and -not $link; $i++) { $link = Cari-Link; if (-not $link) { Start-Sleep 2 } }
if (-not $link) { Gagal 'Link tunnel belum muncul. Lihat: docker logs silent_terror_tunnel' }

# 6. Uji dari internet: tanpa token harus ditolak, dengan token harus bisa menulis kalimat.
Tulis "[ ] Menguji $link ..."
$header = @{ Authorization = "Bearer $token" }
$siap = $false
for ($i = 0; $i -lt 30 -and -not $siap; $i++) {
    try {
        $tags = Invoke-RestMethod "$link/api/tags" -Headers $header -TimeoutSec 15
        $siap = $true
    } catch { Start-Sleep 3 }  # DNS link baru butuh beberapa detik
}
if (-not $siap) { Gagal "Link belum bisa diakses dari internet: $link" }
$daftar = ($tags.models | ForEach-Object { $_.name }) -join ', '

$tolak = $null
try { Invoke-WebRequest "$link/api/tags" -UseBasicParsing -TimeoutSec 15 | Out-Null; $tolak = 'TIDAK DITOLAK' }
catch { $tolak = [int]$_.Exception.Response.StatusCode }

$isi = @{
    model = $model; stream = $false; think = $false; options = @{ num_predict = 60 }
    messages = @(@{ role = 'user'; content = 'Tulis satu kalimat chat santai: kamu curiga sama Budi karena dia diam terus.' })
} | ConvertTo-Json -Depth 5
$mulai = Get-Date
try {
    $jawab = Invoke-RestMethod "$link/api/chat" -Method Post -Headers $header -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($isi)) -TimeoutSec 120
} catch { Gagal "Tes chat lewat link gagal: $($_.Exception.Message)" }
$detik = [math]::Round(((Get-Date) - $mulai).TotalSeconds, 1)

try { Set-Clipboard -Value $link } catch {}

Tulis ''
Tulis '================ LLM SIAP ================' Green
Tulis "Link     : $link  (sudah disalin ke clipboard)" Cyan
Tulis "Token    : $token" Cyan
Tulis "Model    : $daftar  ($(if ($gpu) { 'GPU' } else { 'CPU' }))"
Tulis "Tes chat : $detik detik -> $($jawab.message.content.Trim())"
Tulis "Tanpa token: $tolak $(if ($tolak -eq 401) { '(benar, ditolak)' } else { '(HARUSNYA 401!)' })"
Tulis ''
# Link + token langsung dikirim ke backend lewat API panel (login panel ditanya sekali di jendela ini).
& (Join-Path $PSScriptRoot 'kirim-link.ps1') -Link $link
Tulis ''
Tulis 'Link berganti setiap tunnel dinyalakan ulang; jalankan.bat atau lihat-link.bat mengirimnya lagi otomatis.' Yellow
Tulis 'Laptop harus tetap menyala selama game dimainkan. Matikan dengan hentikan.bat.'
