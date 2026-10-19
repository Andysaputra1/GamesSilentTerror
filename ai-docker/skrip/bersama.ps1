# Dipakai skrip lain di folder ini (dot-source): baca/tulis ai-docker\.env, cari link tunnel, login ke API panel.
# Password panel disimpan terenkripsi DPAPI (hanya bisa dibuka akun Windows ini), tidak pernah teks polos.
# Sengaja hanya karakter ASCII: PowerShell 5.1 membaca .ps1 tanpa BOM sebagai ANSI.

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$EnvBerkas = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'

# Link tunnel di log sejak container tunnel terakhir dinyalakan. Log nyala sebelumnya ikut tersimpan dan
# memuat link lama yang sudah mati, jadi tanpa --since link lama bisa terambil sebelum link baru tercetak.
# Tunnel yang mati tidak punya link.
function Cari-Link {
    $jalan, $mulai = (cmd /c "docker inspect -f ""{{.State.Running}} {{.State.StartedAt}}"" silent_terror_tunnel 2>nul") -split ' '
    if ($jalan -ne 'true') { return $null }
    $log = (cmd /c "docker logs --since $mulai silent_terror_tunnel 2>&1") -join "`n"
    $semua = [regex]::Matches($log, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($semua.Count -gt 0) { return $semua[$semua.Count - 1].Value }
    return $null
}

# Nilai dari .env (format KUNCI=nilai).
function Baca-Env($kunci, $bawaan = '') {
    if (-not (Test-Path $EnvBerkas)) { return $bawaan }
    $baris = Get-Content $EnvBerkas | Where-Object { $_ -match "^$kunci=" } | Select-Object -Last 1
    if ($baris) { $nilai = ($baris -replace "^$kunci=", '').Trim(); if ($nilai) { return $nilai } }
    return $bawaan
}

# Ganti (atau hapus bila $nilai kosong) satu baris KUNCI=nilai di .env.
function Simpan-Env($kunci, $nilai) {
    $baris = @(Get-Content $EnvBerkas | Where-Object { $_ -notmatch "^$kunci=" })
    if ($nilai) { $baris += "$kunci=$nilai" }
    $baris | Set-Content $EnvBerkas -Encoding ascii
}

$Backend = (Baca-Env 'BACKEND_URL' 'https://backendthesis.andylabs.site').TrimEnd('/')

# Panggil API panel; $isi (hashtable) dikirim sebagai JSON UTF-8.
function Panel($metode, $jalur, $isi = $null, $sesi = $null, $batas = 60) {
    $p = @{ Uri = "$Backend$jalur"; Method = $metode; TimeoutSec = $batas; ContentType = 'application/json; charset=utf-8' }
    if ($sesi) { $p.Headers = @{ Authorization = "Bearer $sesi" } }
    if ($null -ne $isi) { $p.Body = [Text.Encoding]::UTF8.GetBytes(($isi | ConvertTo-Json -Depth 6 -Compress)) }
    Invoke-RestMethod @p
}

# Pesan error dari backend ({"detail": ...}) atau dari koneksi.
function Pesan-Error($galat) {
    $detail = $galat.ErrorDetails.Message
    if ($detail) { try { return ($detail | ConvertFrom-Json).detail } catch { return $detail } }
    return $galat.Exception.Message
}

function Kode-Http($galat) {
    if ($galat.Exception.Response) { return [int]$galat.Exception.Response.StatusCode }
    return 0
}

# Login panel. Username/password ditanya sekali (jendela .bat) lalu disimpan; ditanya ulang bila salah.
function Masuk-Panel {
    $bisaTanya = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
    for ($coba = 0; $coba -lt 3; $coba++) {
        $user = Baca-Env 'PANEL_USERNAME'
        $rahasia = Baca-Env 'PANEL_PASSWORD_DPAPI'
        if (-not $user -or -not $rahasia) {
            if (-not $bisaTanya) { throw 'Login panel belum disimpan. Jalankan jalankan.bat sekali lalu isi username/password panel.' }
            Write-Host "Login panel $Backend (sekali saja, password disimpan terenkripsi di ai-docker\.env)" -ForegroundColor Yellow
            $user = (Read-Host 'Username panel').Trim()
            $aman = Read-Host 'Password panel' -AsSecureString
            if (-not $user -or $aman.Length -eq 0) { throw 'Username/password panel kosong.' }
            Simpan-Env 'PANEL_USERNAME' $user
            Simpan-Env 'PANEL_PASSWORD_DPAPI' (ConvertFrom-SecureString $aman)
            continue
        }
        $password = (New-Object PSCredential 'x', (ConvertTo-SecureString $rahasia)).GetNetworkCredential().Password
        try { return (Panel POST '/api/panel/login' @{ username = $user; password = $password }).access_token }
        catch {
            if ((Kode-Http $_) -ne 401) { throw "Login panel gagal: $(Pesan-Error $_)" }
            Write-Host '[!] Username/password panel salah, isi ulang.' -ForegroundColor Yellow
            Simpan-Env 'PANEL_PASSWORD_DPAPI' ''
        }
    }
    throw 'Login panel gagal.'
}
