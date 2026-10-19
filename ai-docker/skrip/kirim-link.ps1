# Kirim link tunnel + token LLM ke backend lewat API panel, jadi Konfigurasi AI tidak perlu diisi manual.
# Dipanggil jalankan.ps1 dan lihat-link.ps1. Jalur "LLM sendiri lewat link" dijadikan prioritas pertama di rantai
# penulis kalimat bot (jalur lain tetap jadi cadangan). Kode keluar 0 = terkirim, 1 = gagal (link tetap bisa diisi manual).
# Sengaja hanya karakter ASCII: PowerShell 5.1 membaca .ps1 tanpa BOM sebagai ANSI.

param([Parameter(Mandatory = $true)] [string] $Link)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'bersama.ps1')

try {
    Write-Host "[ ] Mengirim link ke backend $Backend ..."
    $sesi = Masuk-Panel
    $config = Panel GET '/api/panel/config' -sesi $sesi
    # Provider Konfigurasi AI dipertahankan; rantai penulis bot memakai link ini apa pun providernya.
    $isi = @{ provider = $config.provider; endpoint = $Link; tunnel_token = (Baca-Env 'LLM_TOKEN') }
    for ($i = 0; ; $i++) {
        try { Panel PUT '/api/panel/config' $isi $sesi | Out-Null; break }
        catch {
            # 422 = DNS VM belum mengenal link baru; tunggu sebentar.
            if ((Kode-Http $_) -ne 422 -or $i -ge 5) { throw "Simpan link ditolak: $(Pesan-Error $_)" }
            Start-Sleep 5
        }
    }

    $npc = (Panel GET '/api/panel/npc' -sesi $sesi).status
    $urutan = @('tautan') + @($npc.urutan_penulis | Where-Object { $_ -ne 'tautan' })
    if ((@($npc.urutan_penulis) -join ',') -ne ($urutan -join ',')) {
        $ubah = @{ metode = $npc.metode; penulis = $npc.penulis_diminta; validasi = $npc.validasi; urutan_penulis = $urutan }
        $npc = (Panel PUT '/api/panel/npc' $ubah $sesi).status
    }

    # Simpan link memicu cek rantai penulis di latar (termasuk satu kalimat tes lewat link); tunggu hasilnya.
    for ($i = 0; $i -lt 45 -and $npc.sedang_cek_penulis; $i++) {
        Start-Sleep 2
        $npc = (Panel GET '/api/panel/npc' -sesi $sesi).status
    }
    $tautan = $npc.rantai_penulis | Where-Object { $_.jalur -eq 'tautan' }
    try { Panel POST '/api/panel/logout' -sesi $sesi | Out-Null } catch {}

    Write-Host "[+] Link tersimpan di backend. Rantai penulis: $($npc.urutan_penulis -join ' > ')" -ForegroundColor Green
    $durasi = if ($tautan.hasil_cek.durasi_ms) { ", cek $($tautan.hasil_cek.durasi_ms) ms" } else { '' }
    Write-Host "    Jalur link: $($tautan.keadaan) - $($tautan.status) (model $($tautan.model)$durasi)"
    if ($npc.penulis_diminta -eq 'templat') {
        Write-Host '[!] Otak NPC sedang mode "Templat saja": LLM tidak dipakai sampai penulis diubah ke otomatis di panel.' -ForegroundColor Yellow
    }
    exit 0
} catch {
    Write-Host "[x] Link tidak terkirim ke backend: $(Pesan-Error $_)" -ForegroundColor Red
    Write-Host '    Isi manual: Panel > Konfigurasi AI, tempel link (sudah di clipboard), Simpan.' -ForegroundColor Yellow
    exit 1
}
