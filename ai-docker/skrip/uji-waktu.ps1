# Dipanggil uji-waktu.bat: ukur lama otak NPC di backend lewat simulasi panel (otak, NLU IndoBERT, dan NLG asli,
# tanpa room/database). Satu bot per metode (fuzzy, utility, behavior tree); setiap chat memanggil satu bot,
# lalu semua bot melangkah. Tiap langkah dicatat per tahap: NLU -> logika -> penjelasan -> NLG (LLM + validasi).
# Hasil: tabel di layar + CSV di communicationfolder\uji-waktu-<tanggal>\.
# Sengaja hanya karakter ASCII: PowerShell 5.1 membaca .ps1 tanpa BOM sebagai ANSI.

param([int] $Putaran = 3)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'bersama.ps1')

$metode = @('fuzzy', 'utility', 'bt')
# {0} = nama bot yang dipanggil; dirotasi supaya intent NLU bervariasi (tanya, tuduh, ajak vote, ...).
$pesan = @(
    '{0}, dari tadi kamu diam aja. Kamu curiga sama siapa?',
    'Aku curiga sama {0}, jawabannya muter-muter terus.',
    '{0}, semalam kamu ngapain? Jelasin dong.',
    '{0} kamu percaya sama aku nggak?',
    'Ayo vote {0} aja, dia paling aneh dari tadi.',
    '{0}, menurutmu siapa yang paling mencurigakan sekarang?'
)

function Statistik($nilai) {
    $urut = @($nilai | Sort-Object)
    if ($urut.Count -eq 0) { return '-' }
    $tengah = if ($urut.Count % 2) { $urut[[int][math]::Floor($urut.Count / 2)] } else { ($urut[$urut.Count / 2 - 1] + $urut[$urut.Count / 2]) / 2 }
    '{0:N0} / {1:N0} / {2:N0}' -f ($urut | Measure-Object -Average).Average, $tengah, $urut[-1]
}

$sesi = Masuk-Panel
$npc = (Panel GET '/api/panel/npc' -sesi $sesi).status
Write-Host "Backend $Backend | NLU: $($npc.nlu) | penulis berikut: $($npc.penulis) ($($npc.model_penulis)) | rantai: $($npc.urutan_penulis -join ' > ')"

$sim = Panel POST '/api/panel/simulasi' @{ nama = 'Penguji'; metode = $metode } $sesi 120
$bot = @($sim.pemain | Where-Object { -not $_.manusia })
Write-Host ("Simulasi {0}: {1}" -f $sim.id, (($bot | ForEach-Object { "$($_.nama)=$($_.metode)" }) -join ', '))
Write-Host ''

$baris = New-Object System.Collections.ArrayList
$jumlah = $Putaran * $bot.Count
for ($i = 0; $i -lt $jumlah; $i++) {
    $dipanggil = $bot[$i % $bot.Count].nama
    $teks = $pesan[$i % $pesan.Count] -f $dipanggil
    $jam = [Diagnostics.Stopwatch]::StartNew()
    try { $hasil = Panel POST "/api/panel/simulasi/$($sim.id)" @{ aksi = 'kirim'; teks = $teks; detik = 3 } $sesi 240 }
    catch { Write-Host "[x] Chat ke-$($i + 1) gagal: $(Pesan-Error $_)" -ForegroundColor Red; break }
    $dinding = $jam.ElapsedMilliseconds
    $manusia = $hasil.jejak | Where-Object { $_.manusia } | Select-Object -First 1
    Write-Host ("#{0} [{1:N0} ms, NLU pesan {2} ms -> {3}] {4}" -f ($i + 1), $dinding, $manusia.nlu.ms, $manusia.nlu.intent, $teks) -ForegroundColor Cyan
    foreach ($j in $hasil.jejak | Where-Object { $_.stage -like 'npc_brain*' }) {
        $w = $j.timings
        $nlg = $j.penjelasan.nlg
        $bicara = $nlg.status -eq 'terkirim'
        [void]$baris.Add([pscustomobject]@{
            chat_ke = $i + 1; pesan = $teks; dipanggil = $dipanggil; dinding_ms = $dinding
            nlu_pesan_ms = $manusia.nlu.ms; intent_pesan = $manusia.nlu.intent
            bot = $j.sender; metode = ($j.provider -replace '^otak:', '')
            nlu_ms = $w.nlu_ms; logika_ms = $w.logika_ms; penjelasan_ms = $w.penjelasan_ms
            nlg_ms = $w.nlg_ms; llm_ms = $w.llm_ms; validasi_ms = $w.validasi_ms; total_ms = $j.duration_ms
            bicara = $bicara; sumber = $nlg.sumber; penulis = $nlg.penulis
            percobaan_llm = (@($nlg.percobaan_llm) -join ' | '); keputusan = ($j.ringkas.keputusan -join '; ')
            kalimat = $(if ($bicara) { $nlg.teks } else { '' })
        })
        $ket = if ($bicara) { "$($nlg.sumber)/$($nlg.penulis): $($nlg.teks)" } else { "diam ($($nlg.status))" }
        Write-Host ("   {0,-5} {1,-7} nlu {2,6} | logika {3,6} | penjelasan {4,6} | nlg {5,7} (llm {6,7}) | total {7,7} ms  {8}" -f
            $j.sender, ($j.provider -replace '^otak:', ''), $w.nlu_ms, $w.logika_ms, $w.penjelasan_ms, $w.nlg_ms, $w.llm_ms, $j.duration_ms, $ket)
    }
}
try { Panel POST '/api/panel/logout' -sesi $sesi | Out-Null } catch {}

Write-Host ''
Write-Host 'Ringkasan per metode (rata-rata / median / maks, ms):' -ForegroundColor Green
$ringkas = foreach ($m in $metode) {
    $semua = @($baris | Where-Object { $_.metode -eq $m })
    $bicara = @($semua | Where-Object { $_.bicara })
    [pscustomobject]@{
        metode = $m; langkah = $semua.Count; bicara = $bicara.Count
        llm = @($bicara | Where-Object { $_.sumber -eq 'llm' }).Count
        nlu = Statistik ($semua | ForEach-Object { $_.nlu_ms })
        logika = Statistik ($semua | ForEach-Object { $_.logika_ms })
        nlg = Statistik ($bicara | ForEach-Object { $_.nlg_ms })
        'total (bicara)' = Statistik ($bicara | ForEach-Object { $_.total_ms })
        'total (diam)' = Statistik ($semua | Where-Object { -not $_.bicara } | ForEach-Object { $_.total_ms })
    }
}
$ringkas | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
Write-Host ("NLU pesan pemain: {0}" -f (Statistik ($baris | Group-Object chat_ke | ForEach-Object { $_.Group[0].nlu_pesan_ms })))

$folder = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) ("communicationfolder\uji-waktu-" + (Get-Date -Format 'yyyy-MM-dd'))
New-Item -ItemType Directory -Force $folder | Out-Null
$csv = Join-Path $folder ("uji-waktu-" + (Get-Date -Format 'HHmmss') + ".csv")
$baris | Export-Csv $csv -NoTypeInformation -Encoding UTF8
Write-Host "CSV: $csv"
