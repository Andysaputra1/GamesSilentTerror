'use strict';
// Ambil elemen panel berdasarkan ID.
const $ = (id) => document.getElementById(id);
// Riwayat chat: versi request (jawaban filter lama diabaikan) dan id pesan terakhir yang sudah tampil.
let versiRiwayat = 0,
  idRiwayatTerakhir = 0;
// Manajemen user: id akun terakhir yang sudah tampil, versi request, akun di editor, dan status simpan.
let idAkunTerakhir = 0,
  versiAkun = 0,
  akunTerpilih = null,
  sedangMenyimpanAkun = false;
let keyAvailability = { default: false, custom: false };
let token = '',
  menu = 'ai',
  traceBefore = null,
  traces = [],
  selectedTrace = '',
  busy = false,
  generation = 0;
// Tampilkan pesan status sebagai teks agar isi dinamis tidak dianggap HTML.
const notice = (pesan) => {
  $('notice').textContent = pesan;
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => {
    $('notice').textContent = '';
  }, 8000);
};
// Kirim request panel dan hapus sesi lokal jika server menyatakan token tidak valid.
async function request(alamat, isi, metode = 'GET') {
  const generasiAwal = generation;
  const respons = await fetch(alamat, {
    method: metode,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: isi ? JSON.stringify(isi) : undefined,
    // Uji AI dan cek rantai penulis menunggu provider; simulasi menunggu otak + LLM beberapa bot.
    signal: AbortSignal.timeout(
      /\/simulasi/.test(alamat) ? 180000 : /\/cek-penulis$/.test(alamat) ? 60000 : 15000,
    ),
  });
  if (generasiAwal !== generation) throw new Error('Sesi telah berubah. Respons lama diabaikan.');
  if (respons.status === 204) return {};
  const hasil = await respons.json().catch(() => ({}));
  if (!respons.ok) {
    if (respons.status === 401 && token) clearSession();
    throw new Error(
      typeof hasil.detail === 'string'
        ? hasil.detail
        : 'Permintaan gagal. Periksa isian dan coba lagi.',
    );
  }
  return hasil;
}
// Buang token, rahasia form, dan data panel; abaikan respons dari sesi sebelumnya.
function clearSession() {
  $('create-user-form').reset();
  versiAkun++;
  $('user-rows').replaceChildren();
  tutupEditorAkun();
  $('api-key').value = '';
  generation++;
  token = '';
  $('workspace').hidden = true;
  $('login-view').hidden = false;
  $('logout').hidden = true;
  $('history-rows').replaceChildren();
  $('traces').replaceChildren();
  $('trace-detail').textContent = '';
  $('events').textContent = '';
  resetChecker();
  sim = null;
  simTraces = [];
  simSelected = '';
  simProgres = null;
  flowNode = '';
  renderedFlowDetail = '';
  kodeCache.clear();
  $('sim-chat').replaceChildren();
  $('sim-detail').textContent = '';
  $('sim-status').hidden = true;
  $('npc-status').replaceChildren();
  $('survey-rows').replaceChildren();
  $('survey-method-rows').replaceChildren();
  $('survey-stats').replaceChildren();
  $('survey-charts').replaceChildren();
  $('survey-respondent-rows').replaceChildren();
  $('survey-order-status').textContent = '';
  urutanSurvei = [];
  urutanSurveiTersimpan = [];
  barisSurvei.clear();
  kosongkanFormSurvei();
  versiRiwayat++;
  traces = [];
}

// Buat elemen dengan isi teks biasa, sehingga data dari server tidak pernah menjadi HTML.
function node(tag, text, className = '') {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  element.className = className;
  return element;
}
function duration(value) {
  if (typeof value !== 'number') return 'Belum tercatat';
  return value >= 1000 ? `${(value / 1000).toFixed(2)} dtk` : `${value.toFixed(1)} ms`;
}
// Lama cek aturan satu kalimat; jejak sebelum 4 Nov 2026 menyimpannya sebagai validasi_ms.
function waktuAturan(t) {
  return t.aturan_ms ?? t.validasi_ms;
}
function renderReport(container, trace) {
  container.replaceChildren();
  container.classList.remove('empty-state');
  const metrics = node('div', undefined, 'metric-grid');
  const success = trace.active ?? ['complete', 'delivered', 'npc_complete'].includes(trace.stage);
  for (const [label, value] of [
    ['Status', trace.active === undefined ? trace.stage : success ? 'AI merespons' : 'AI gagal'],
    ['Total proses', duration(trace.duration_ms)],
    ['Waktu LLM', duration(trace.timings?.llm_ms)],
    ['Provider', trace.provider || 'Belum dipanggil'],
    ['Model', trace.model || '—'],
    [
      'HTTP / validasi',
      `${trace.response?.status_code ?? '—'}${trace.valid_decision === undefined ? '' : trace.valid_decision ? ' · valid' : ' · tidak valid'}`,
    ],
  ]) {
    const metric = node('div', undefined, 'metric');
    metric.append(
      node('small', label),
      node('strong', value, label === 'Status' ? (success ? 'status-good' : 'status-pending') : ''),
    );
    metrics.append(metric);
  }
  container.append(metrics);
  if (trace.message_status)
    container.append(node('p', trace.message_status, success ? 'status-good' : 'status-bad'));
  const steps = node('div', undefined, 'steps');
  for (const [key, value] of Object.entries(trace.timings || {}))
    steps.append(node('span', `${key.replace('_ms', '')}: ${duration(value)}`, 'step'));
  container.append(
    steps,
    node('h4', 'INPUT PEMAIN', 'report-title'),
    node('pre', trace.message || '—'),
  );
  container.append(
    node('h4', 'OUTPUT / KEPUTUSAN', 'report-title'),
    node(
      'pre',
      typeof trace.output === 'string'
        ? trace.output
        : trace.output
          ? JSON.stringify(trace.output, null, 2)
          : trace.response?.body?.output || 'Belum ada output. Lihat status atau error di bawah.',
      'output',
    ),
  );
  const sections = [
    [
      'Request LLM · endpoint & parameter',
      trace.request || 'Tidak tercatat pada trace ini. Trace lama tidak direkonstruksi.',
    ],
    ['Response LLM · status, output & usage', trace.response || 'Tidak tercatat pada trace ini.'],
    ['Prompt yang dikirim', trace.prompt || 'Belum mengirim prompt.'],
    [
      'Konteks skenario / NPC',
      trace.context || 'Lihat prompt untuk konteks NPC pada trace pertandingan.',
    ],
    ['Seluruh trace JSON', trace],
  ];
  for (const [title, value] of sections) {
    const detail = node('details');
    detail.append(
      node('summary', title),
      node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)),
    );
    container.append(detail);
  }
  if (trace.note) container.append(node('p', trace.note, 'hint'));
}
// Tampilkan kolom konfigurasi yang sesuai dengan provider pilihan form.
function providerView() {
  $('local-settings').hidden = $('provider').value !== 'docker';
  $('api-settings').hidden = $('provider').value !== 'api';
}
// Jelaskan ketersediaan sumber API key tanpa menampilkan nilai rahasianya.
function keySourceView() {
  const source = $('key-source').value;
  $('custom-key-settings').hidden = source !== 'custom';
  $('source-status').textContent =
    source === 'default'
      ? keyAvailability.default
        ? 'Key default server tersedia. Nilainya tidak ditampilkan.'
        : 'Key default belum tersedia di server (openrouter_default).'
      : keyAvailability.custom
        ? 'Key sendiri sudah tersimpan. Kosongkan kolom untuk tetap memakainya.'
        : 'Isi API key OpenRouter milikmu di bawah.';
}
// Sinkronkan form dan ringkasan dengan konfigurasi yang tersimpan di server.
function showConfig(data) {
  const source =
    data.provider === 'docker'
      ? 'LLM lokal (Ollama)'
      : data.key_source === 'custom'
        ? 'OpenRouter - API key sendiri'
        : 'OpenRouter - API default server';
  $('active-config').textContent =
    `Saat ini menggunakan: ${source}. Model: ${data.model}.` +
    (data.provider === 'docker'
      ? ` Tujuan: ${data.endpoint}`
      : data.api_configured
        ? ' Key tersedia; uji koneksinya di menu Otak NPC.'
        : ' Key belum tersedia; AI belum siap digunakan.');
  $('config-draft').textContent = 'Konfigurasi ini berlaku untuk pesan AI berikutnya.';
  $('provider').value = data.provider;
  $('key-source').value = data.key_source;
  keyAvailability = {
    default: data.default_configured,
    custom: data.custom_configured,
  };
  keySourceView();
  $('endpoint').value = data.endpoint.startsWith('https://') ? data.endpoint : '';
  $('local-model').replaceChildren(
    ...(data.local_models ?? [data.local_model]).map((model) => {
      const option = node('option', model);
      option.value = model;
      return option;
    }),
  );
  $('local-model').value = data.local_model;
  $('tunnel-token').value = '';
  $('clear-token').checked = false;
  $('clear-token-row').hidden = data.token_source !== 'panel';
  $('token-status').textContent =
    {
      panel: 'Token tersimpan di panel (terenkripsi). Kosongkan untuk tetap memakainya.',
      env: 'Memakai OLLAMA_TUNNEL_TOKEN dari .env server. Isi di sini untuk menggantinya.',
    }[data.token_source] ??
    'Belum ada token. Tunnel ai-docker menolak permintaan tanpa token (401).';
  $('key-status').textContent = data.api_configured
    ? 'API key tersedia di server.'
    : 'Sumber key yang disimpan belum tersedia. Pilih sumber lalu simpan.';
  providerView();
}
// Ambil konfigurasi tersimpan lalu tampilkan pada form panel.
async function loadConfig() {
  showConfig(await request('/api/panel/config'));
}
// Tandai perubahan form yang belum diterapkan pada request AI berikutnya.
function markConfigDraft() {
  $('config-draft').textContent =
    'Ada perubahan formulir yang belum disimpan. Game masih memakai konfigurasi di atas.';
}
$('config-form').addEventListener('input', markConfigDraft);
$('config-form').addEventListener('change', markConfigDraft);
// Ambil seluruh halaman ruangan dan pertahankan pilihan filter pengguna.
async function muatDaftarRuangan() {
  const daftarRuangan = [];
  let idTerakhir = 0;
  for (;;) {
    const halaman = await request(`/api/panel/rooms?after_id=${idTerakhir}`);
    daftarRuangan.push(...halaman.rooms);
    if (!halaman.has_more) break;
    idTerakhir = halaman.next_after_id;
  }
  // API berhalaman urut id naik; pilihan ditampilkan dari ruangan terbaru.
  daftarRuangan.sort((a, b) => b.id - a.id);
  for (const idPilihan of ['checker-room', 'history-room']) {
    const pilihan = $(idPilihan),
      nilaiSekarang = pilihan.value;
    pilihan.replaceChildren(
      new Option(idPilihan === 'history-room' ? 'Semua ruangan' : 'Pilih ruangan', ''),
    );
    for (const ruangan of daftarRuangan)
      pilihan.add(
        new Option(
          `${ruangan.room_code} | ${tanggal(ruangan.created_at)} | ${ruangan.message_count} pesan${ruangan.live ? ' | aktif' : ''}`,
          ruangan.room_code,
        ),
      );
    pilihan.value = nilaiSekarang;
  }
  return daftarRuangan;
}
// CHECKER ROOM: ringkasan room, linimasa jejak per bot, dan kartu penjelasan keputusan otak.
// Semua isi dari server ditulis lewat textContent/Option, tidak pernah sebagai HTML.
let checkerRoom = null,
  traceFilter = '', // '' semua jejak | 'bot' semua keputusan bot | 'bot:NAMA'
  detailTab = 'proses',
  renderedDetail = ''; // jejak yang sedang tampil: tidak dirender ulang tiap auto-refresh
const traceDetails = new Map(); // id → jejak lengkap (dengan penjelasan), dimuat saat dibuka
// DATA LIVE Checker (polling /proses tiap detik): langkah bot yang sedang berjalan, chat manusia yang belum selesai,
// kondisi tiap bot, dan antrean thread. Waktu berjalan berdetak di browser dari data terakhir (liveDiterima).
let liveBot = [],
  liveChat = new Map(), // id jejak → jejak chat manusia yang belum selesai (dengan berjalan_ms)
  liveKondisi = new Map(), // nama bot → kondisi
  liveAntrean = null,
  liveDiterima = 0,
  liveBusy = false,
  livePilihan = null, // item live yang dipilih: {b, hilang, segar} sampai jejaknya ditemukan
  perluSegar = false, // langkah/chat live selesai: daftar jejak perlu dimuat ulang
  segarKe = 0; // berapa kali daftar jejak sudah dimuat (penanda urutan untuk livePilihan)
const liveBox = node('div', undefined, 'chat-live-list'); // item "sedang diproses" di ujung chat room
// Game hanya memakai Fuzzy (dan LLM sebagai pembanding). Utility AI dan Behavior Tree sudah diarsipkan;
// label, arti parameter, dan tampilan penalarannya tetap ada agar jejak lama di database bisa dibuka.
const METODE_LABEL = {
  fuzzy: 'Fuzzy Mamdani',
  utility: 'Utility AI (jejak lama)',
  bt: 'Behavior Tree (jejak lama)',
};
// Singkatan metode, sama dengan label nama bot di game.
const METODE_SINGKAT = { fuzzy: 'FL', utility: 'UA', bt: 'BT', llm: 'LLM' };
const METODE_CARA = {
  fuzzy:
    'Setiap nilai 0–1 difuzzifikasi menjadi rendah/sedang/tinggi. Aturan JIKA–MAKA menyala dengan kekuatan min(derajat input), keluaran digabung (max) lalu didefuzzifikasi centroid menjadi 0–100 dan dibandingkan ambang. Bela diri dan jawab dikirim tanpa nilai; Hostage dan Guard memakai nilai 0–1 tanpa sistem fuzzy.',
  utility:
    'Setiap pilihan diberi pertimbangan 0–1 lewat kurva. Utilitas = bobot × Π(n + (1 − n)(1 − 1/k)n) (kompensasi IAUS, k = jumlah pertimbangan). Pilihan terbesar dipakai bila melewati ambang atau utilitas diam.',
  bt: 'Pohon dibaca dari atas. Selector mencoba cabang berurutan dan berhenti di cabang pertama yang berhasil; Sequence berhenti di syarat pertama yang gagal. Aksi pada cabang yang berhasil menjadi keputusan.',
};
const ROLE_LABEL = { hitman: 'Hitman', spy: 'Spy', stalker: 'Stalker', civilian: 'Civilian' };
const FASE_LABEL = {
  preparing: 'Persiapan',
  day: 'Siang',
  night: 'Malam',
  tribunal: 'Tribunal',
  finished: 'Selesai',
};
const STATUS_ROOM = {
  live: ['Live', 'status-good'],
  selesai: ['Selesai', 'status-pending'],
  lobby: ['Lobby', 'status-muted'],
  arsip: ['Arsip', 'status-muted'],
};
const SUMBER_NLG = {
  llm: 'LLM (lolos pemeriksaan)',
  templat: 'Templat (lolos pemeriksaan)',
  templat_cadangan: 'Templat cadangan (tidak ada varian yang lolos)',
};
// Arti parameter: dipakai legenda dan keterangan judul kolom tabel.
const PARAMETER = {
  kecurigaan: 'Seberapa kuat pemain dianggap Hitman (0–1), hasil akhir metode.',
  tekanan:
    'Tuduhan dan vote ke pemain ini dari yang masih bisa bersuara, dibagi jumlah mereka (hidup, tidak disandera); meluruh per ronde.',
  dukungan: 'Pembelaan dari yang masih bisa bersuara, termasuk klaim bersih dari pengaku Stalker.',
  plin_plan: 'Berganti sikap ke target yang sama, atau vote tidak sesuai ucapannya.',
  alihkan_tuduhan:
    'Balasan pertama sesudah dituduh: menuduh orang lain 1, membela diri sekaligus menuduh 0,5, hanya membela 0; dirata-ratakan per balasan.',
  penuduh_dibungkam:
    'Pernah dituduh pemain yang kemudian disandera (diumumkan) atau diduga di-Gag (jejak aksi Hitman).',
  ikut_salah_eksekusi:
    'Ikut mendorong eksekusi warga: vote, ikut menuduh, atau penuduh pertama, dikali kepastian korban warga (1 bila game berlanjut di room satu Hitman atau jumlah Hitman yang diumumkan tetap; selain itu 1 − k/(N − 1)). Tidak dihitung bila korban diketahui Hitman.',
  memihak_hitman:
    'Pernah membela pemain yang kini terbukti Hitman; rendah bila hanya mengulang klaim bersih pengaku Stalker lain.',
  jejak_kedua:
    'Nilai terbesar dari ikut_salah_eksekusi dan memihak_hitman, input kedua sistem jejak.',
  menuduh_orang_baik: 'Menuduh atau vote pemain yang pasti orang baik menurut bot.',
  klaim_role_bermasalah:
    'Klaim role bermasalah: pasti bohong 1; klaim terbukti salah atau disebut Hitman oleh pengaku tunggal 0,8; bentrok 0,6.',
  p_sandera: 'Korban Hostage yang diumumkan server (1) atau bukan (0); korban pasti bukan Hitman.',
  diam: 'Belum bicara di ronde ini (0–1 menurut waktu yang lewat).',
  sentimen_sosial: 'Fuzzy: kecurigaan dari tekanan dan dukungan (0–1).',
  perilaku_mencurigakan: 'Fuzzy: kecurigaan dari plin plan dan alihkan tuduhan (0–1).',
  jejak: 'Fuzzy: jejak aksi Hitman dari penuduh dibungkam dan jejak kedua (0–1).',
  kejanggalan: 'Fuzzy: kejanggalan dari menuduh orang baik dan klaim role bermasalah (0–1).',
  ucapan: 'Fuzzy: gabungan bukti lunak, sentimen sosial dan perilaku mencurigakan (0–1).',
  bukti_keras: 'Fuzzy: gabungan bukti keras, jejak dan kejanggalan (0–1).',
  warga_terdesak: 'Makin sedikit warga bebas, makin mendesak (0–1).',
  waktu_berjalan: 'Bagian fase yang sudah berjalan (0–1).',
  chat_membingungkan:
    'Porsi chat ronde ini yang tidak jelas; minimal 0,8 bila ada klaim role yang bentrok.',
  chat_sepi: 'Makin sedikit chat ronde ini, makin tinggi (0 bila sudah ramai).',
  ruangan_hening: 'Tidak ada chat di fase ini selama sekitar 20% durasi fase (minimal 15 detik).',
  bot_dituduh_baru:
    'Penuduh baru sesudah chat terakhir bot, ditambah pemilih Tribunal ke bot; pemicu bela diri.',
  penanya: 'Pengirim chat neutral terbaru yang menyebut bot dan belum dibalas; pemicu jawab.',
  sudah_disuarakan:
    'Jumlah pemain lain yang sudah menuduh atau membela tiap pemain di fase ini (anti-gema).',
  klaim_bentrok: 'Pengaku role yang bentrok, dan bot belum tahu siapa yang bohong.',
  keunggulan: 'Selisih kecurigaan tersangka teratas dari tersangka kedua (0–1).',
  keyakinan: 'Fuzzy vote: keyakinan pada kandidat teratas (0–1).',
  kesiapan: 'Fuzzy vote: kesiapan mengunci vote (0–100) dari keyakinan dan warga terdesak.',
  prioritas:
    'Nilai tiap kandidat: keluaran fuzzy 0–100 untuk chat, Gag, dan Peek; nilai 0–1 tanpa fuzzy untuk Hostage dan Guard. Bela diri dan jawab tanpa nilai.',
  utilitas: 'Skor Utility AI 0–1. Nilai pertimbangan sudah melalui kurva.',
  poin: 'Behavior Tree: jumlah poin bendera merah yang aktif; kecurigaan = poin / 5.',
  bendera: 'Behavior Tree: bendera merah aktif bila nilai bukti ≥ ambangnya.',
  ancaman: 'Hitman: seberapa berbahaya pemain (menuduh, berpengaruh, mengaku role penting).',
  ancaman_langsung: 'Hitman: ancaman dari menuduh tim dan pengaruh (0–1).',
  ancaman_peran: 'Hitman: ancaman dari mengaku role penting dan kredibilitas (0–1).',
  menuduh_tim:
    'Hitman: tuduhan pemain ini ke Hitman ini (chat 0,5, vote 1) dan ke rekan (separuhnya), meluruh per ronde.',
  pengaruh: 'Seberapa sering tuduhan pemain ini diikuti pemain lain pada ronde yang sama (0–1).',
  mengaku_role_penting: 'Hitman: mengaku Stalker 1 (0,7 bila bentrok), mengaku Spy 0,5.',
  kecurigaan_publik:
    'Kecurigaan pemain ini menurut pengamat netral, tanpa pengetahuan pribadi (0–1).',
  kredibilitas: 'Hitman: 1 − kecurigaan publik.',
  dukungan_suara: 'Hitman: porsi suara Tribunal yang mengarah ke pemain ini.',
  ancaman_sekarang:
    'Hitman: tuduhan ronde ini, ditambah 0,5 × mengaku role penting bila pemain ini bicara di fase ini; bahan Gag.',
  kambing_hitam: 'Hitman: seberapa mudah pemain dijadikan tersangka oleh warga.',
  jejak_tuduhan:
    'Hitman: seberapa jelas pemain ini menuduh Syndicate, makin sedikit orang yang dituduhnya makin tinggi. Nilai Hostage = ancaman × (1 − 0,5 × jejak_tuduhan).',
  terancam: 'Spy: seberapa mungkin pemain diincar Hitman malam ini; menjadi nilai Guard.',
  menuduh_tersangka:
    'Spy: jumlah kecurigaan orang yang dituduh atau di-vote pemain ini, meluruh per ronde.',
  mengaku_stalker: 'Spy: pemain ini mengaku Stalker 0,9 (0,5 bila bentrok, 0 bila pasti bohong).',
  kepercayaan: 'Input bela orang: seberapa bisa dipercaya (1 = pasti bersih).',
  tidak_dijaga:
    'Jejak lama: kepastian target tidak dijaga Spy malam itu (1 pasti, 0,5 tidak tahu). Sekarang tidak dipakai.',
  menuduh_saya:
    'Jejak lama: tuduhan pemain ini ke Hitman ini saja (chat 0,5, vote 0,8). Sekarang menuduh tim, yang juga menghitung tuduhan ke rekan.',
};
// Nama lama tetap dikenali karena jejak lama di checker_traces masih memakainya.
for (const [lama, baru] of Object.entries({
  inkonsistensi: 'plin_plan',
  pengalihan: 'alihkan_tuduhan',
  dituduh_korban: 'penuduh_dibungkam',
  dorong_salah_eksekusi: 'ikut_salah_eksekusi',
  serang_bersih: 'menuduh_orang_baik',
  klaim: 'klaim_role_bermasalah',
  urgensi: 'warga_terdesak',
  porsi_fase: 'waktu_berjalan',
  sosial: 'sentimen_sosial',
  perilaku: 'perilaku_mencurigakan',
  pribadi: 'kejanggalan',
  klaim_peran: 'mengaku_role_penting',
  klaim_stalker: 'mengaku_stalker',
  ketidakjelasan: 'chat_membingungkan',
  sedikit_info: 'chat_sepi',
  hening: 'ruangan_hening',
})) {
  PARAMETER[lama] = `Nama lama ${baru.replaceAll('_', ' ')}. ${PARAMETER[baru]}`;
}
// Nilai → teks ringkas: angka dibulatkan, boolean ya/tidak, kosong menjadi —.
function teks(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number')
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
  if (typeof value === 'boolean') return value ? 'ya' : 'tidak';
  if (Array.isArray(value)) return value.length ? value.map(teks).join(', ') : '—';
  if (typeof value === 'object')
    return (
      Object.entries(value)
        .map(([k, v]) => `${k}: ${teks(v)}`)
        .join(' · ') || '—'
    );
  return String(value);
}
function roleClass(role) {
  return role === 'hitman' ? 'status-bad' : role === 'civilian' ? 'status-muted' : 'status-pending';
}
function chip(text, className) {
  return node('span', text, `chip ${className}`);
}
// Tabel {kolom, baris}; judul kolom diberi keterangan arti parameter bila ada.
function dataTable(data) {
  const wrap = node('div', undefined, 'table-scroll decision-table');
  const table = document.createElement('table');
  const head = document.createElement('tr');
  for (const kolom of data.kolom || []) {
    const th = node('th', String(kolom).replaceAll('_', ' '));
    if (PARAMETER[kolom]) th.title = PARAMETER[kolom];
    head.append(th);
  }
  table.createTHead().append(head);
  const body = table.createTBody();
  for (const baris of data.baris || []) {
    const tr = body.insertRow();
    for (const nilai of baris) tr.insertCell().textContent = teks(nilai);
  }
  wrap.append(table);
  return wrap;
}
function keyValues(pairs) {
  const dl = node('dl', undefined, 'status-list decision-kv');
  for (const [label, value] of pairs) {
    const dt = node('dt', String(label).replaceAll('_', ' '));
    if (PARAMETER[label]) dt.title = PARAMETER[label];
    dl.append(dt, node('dd', teks(value)));
  }
  return dl;
}
function listOf(items, className = 'decision-list') {
  const ul = node('ul', undefined, className);
  for (const item of items) ul.append(node('li', item));
  return ul;
}
// Legenda statis: cara membaca tiap metode dan arti parameter.
function renderLegend() {
  $('checker-legend').append(
    node('h4', 'Metode', 'report-title'),
    keyValues(Object.entries(METODE_LABEL).map(([id, label]) => [label, METODE_CARA[id]])),
    node('h4', 'Parameter', 'report-title'),
    keyValues(Object.entries(PARAMETER)),
  );
}
renderLegend();
// Nama bot pemilik jejak: dari ringkasan penjelasan, provider otak:<metode>, item live, atau jejak error langkah bot.
function traceBot(trace) {
  if (trace.live) return trace.sender;
  return (
    trace.ringkas?.bot?.nama ||
    (trace.provider?.startsWith('otak:') || trace.stage === 'npc_brain_error' ? trace.sender : null)
  );
}
function visibleTraces() {
  if (!traceFilter) return traces;
  if (traceFilter === 'bot') return traces.filter(traceBot);
  return traces.filter((t) => traceBot(t) === traceFilter.slice(4));
}
function waktu(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta' });
}
// Waktu server (UTC tanpa zona) menjadi tanggal dan jam WIB.
function tanggal(iso) {
  if (!iso) return 'tanpa tanggal';
  const date = new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  return Number.isNaN(date.getTime())
    ? 'tanpa tanggal'
    : date.toLocaleString('id-ID', {
        timeZone: 'Asia/Jakarta',
        dateStyle: 'medium',
        timeStyle: 'short',
      });
}
// ISTILAH untuk orang awam. Istilah teknisnya tetap ada di tooltip (title) dan tab Teknis.
const STAGE_LABEL = {
  npc_brain: 'langkah bot',
  npc_brain_rejected: 'ditolak engine',
  npc_brain_error: 'error',
  received: 'diterima server',
  delivered: 'terkirim',
  complete: 'selesai',
  discarded_state_changed: 'dibuang: fase sudah berubah',
  persistence_error: 'gagal disimpan ke database',
};
const AKSI_LABEL = {
  vote: 'vote',
  gag: 'Gag (bungkam)',
  hostage: 'Hostage (sandera)',
  guard: 'Guard (jaga)',
  peek: 'Peek (intip)',
  wait: 'diam',
  tunggu: 'diam',
  abstain: 'abstain',
  tidak_bisa: 'tidak bisa',
};
const INTENT_LABEL = { offend: 'menuduh', defend: 'membela', neutral: 'netral' };
const TEKS_DITUNDA = 'chat ditunda (lantai bicara penuh/rencana basi)';
const HASIL_LANGKAH = {
  bertindak: 'bertindak',
  diam: 'diam',
  ditunda: 'chat ditunda',
  ditolak: 'ditolak engine',
  basi: 'keputusan dibuang karena fase berganti',
  error: 'error',
};
// Tanda keadaan, sama di alur, kolom kondisi, antrean, dan legenda: aktif, selesai, menunggu, error, tidak bisa
// bertindak, dan tidak dilalui (redup).
const TANDA = { sedang: '●', selesai: '✓', menunggu: '…', gagal: '✗', tidakbisa: '⊘', lewat: '–' };
// Tahap live langkah bot (dilaporkan bot_controller lewat lapor): [kotak alur yang menyala, keterangan].
// Antre menyala di kotak yang sedang ditunggu (NLU atau LLM); lamanya masuk kotak Antre + mengetik.
const TAHAP_LIVE = {
  antre: ['nlu', 'antre thread otak'],
  nlu: ['nlu', 'NLU membaca chat'],
  logika: ['fuzzy', 'Fuzzy menimbang'],
  penjelasan: ['penjelasan', 'menyusun penjelasan'],
  engine: ['engine', 'vote/aksi ke engine'],
  tim: ['engine', 'menulis chat tim'],
  antre_nlg: ['llm', 'antre thread penulis'],
  nlg: ['llm', 'menyiapkan prompt'],
  llm: ['llm', 'menunggu LLM'],
  aturan: ['aturan', 'cek aturan'],
  giliran: ['llm', 'memeriksa giliran bicara'],
  ketik: ['sisa', 'jeda mengetik'],
  simpan: ['output', 'menyimpan chat'],
  jejak: ['output', 'mencatat jejak'],
};
// Teks tahap live untuk kolom Kondisi sekarang.
const KONDISI_TAHAP = {
  antre: 'antre (menunggu thread otak)',
  nlu: 'berpikir: NLU',
  logika: 'berpikir: Fuzzy',
  penjelasan: 'berpikir: penjelasan panel',
  engine: 'vote/aksi ke engine',
  tim: 'chat tim',
  giliran: 'memeriksa giliran bicara',
  antre_nlg: 'menulis kalimat: antre thread penulis',
  nlg: 'menulis kalimat: prompt',
  llm: 'menulis kalimat: LLM',
  aturan: 'cek aturan',
  ketik: 'mengetik',
  simpan: 'menyimpan chat',
  jejak: 'mencatat jejak',
};
// Tahap brain_turn tempat langkah bot gagal (error_tahap jejak npc_brain_error).
const TAHAP_GAGAL = {
  lihat: 'melihat snapshot permainan',
  berpikir: 'berpikir (thread otak)',
  vote_aksi: 'mengirim vote/aksi ke engine',
  chat_tim: 'menulis chat tim',
  tulis: 'menulis kalimat',
  kirim: 'menyimpan/mengirim chat',
  jejak: 'mencatat jejak',
};
// Keputusan ringkas dari server ("chat bela_diri → ECHO", "gag → Kimberly") dalam bahasa awam.
function teksKeputusan(k) {
  const [kata, ...sisa] = String(k).split(' ');
  return [AKSI_LABEL[kata] || kata, ...sisa].join(' ').replaceAll('_', ' ');
}
// Keputusan terakhir bot di tabel ringkasan room: jejak terbarunya (error ditulis sebagai error).
function lastDecision(nama) {
  const trace = traces.find((t) => traceBot(t) === nama);
  if (!trace) return '—';
  if (trace.stage === 'npc_brain_error') return `error: ${trace.error || 'tidak diketahui'}`;
  return trace.ringkas?.keputusan?.length
    ? trace.ringkas.keputusan.map(teksKeputusan).join(' · ')
    : trace.message;
}
// WAKTU LIVE: lama berjalan = nilai dari polling terakhir + waktu sejak data itu diterima (jeda, ms). Kunci:
// bot|id|tahap atau total, chat|id|ms tahap yang sudah selesai, turun|nama (hitung mundur), antre|nomor|bagian.
function waktuLive(kunci, jeda) {
  const [jenis, id, bagian] = kunci.split('|');
  if (jenis === 'bot') {
    const b = liveBot.find((x) => x.id === id);
    return b ? (bagian === 'total' ? b.total_ms : b.tahap_ms) + jeda : null;
  }
  if (jenis === 'chat') {
    const c = liveChat.get(id);
    return typeof c?.berjalan_ms === 'number'
      ? Math.max(0, c.berjalan_ms - Number(bagian || 0)) + jeda
      : null;
  }
  if (jenis === 'turun') {
    const k = liveKondisi.get(id);
    return typeof k?.berikutnya_detik === 'number'
      ? Math.max(0, k.berikutnya_detik * 1000 - jeda)
      : null;
  }
  if (jenis === 'antre') {
    const t = Object.values(liveAntrean || {})
      .flatMap((a) => a.tugas || [])
      .find((x) => String(x.nomor) === id);
    if (!t) return null;
    return (bagian === 'berjalan' ? t.berjalan_ms : t.menunggu_ms) + jeda;
  }
  return null;
}
// Teks satu waktu live. Hitung mundur langkah berikutnya di bawah 0,5 dtk ditulis "sebentar lagi", karena jam bot
// memeriksa jadwal tiap 0,5 dtk.
function teksWaktuLive(kunci, ms) {
  if (ms === null) return '—';
  if (kunci.startsWith('turun|')) return ms < 500 ? 'sebentar lagi' : `±${duration(ms)}`;
  return duration(ms);
}
// Teks waktu yang ikut berdetak: awalan + lama + akhiran; detakLive memperbaruinya dari data polling terakhir.
function waktuBerdetak(kunci, awalan = '', akhiran = '', className = 'waktu-live') {
  const el = node('span', undefined, className);
  Object.assign(el.dataset, { live: kunci, awalan, akhiran });
  const ms = waktuLive(kunci, performance.now() - liveDiterima);
  el.textContent = `${awalan}${teksWaktuLive(kunci, ms)}${akhiran}`;
  return el;
}
// Detak 250 ms: hanya teks waktu yang berubah, elemen lain tidak dirender ulang.
function detakLive() {
  const jeda = performance.now() - liveDiterima;
  for (const el of $('menu-checker').querySelectorAll('[data-live]')) {
    const kunci = el.dataset.live,
      ms = waktuLive(kunci, jeda);
    if (ms !== null)
      el.textContent = `${el.dataset.awalan}${teksWaktuLive(kunci, ms)}${el.dataset.akhiran}`;
  }
}
// KONDISI SEKARANG tiap bot (kolom ringkasan room), dari data live server: tahap langkah yang sedang berjalan
// (checker_service), atau alasan bot tidak melangkah (NPCService.kondisi_bot: status dan hak di engine, otak sibuk,
// jadwal langkah, lantai bicara, hasil langkah terakhir).
// Alur: 1 sedang melangkah: tahap + lama -> 2 tidak bisa bertindak, belum siap, atau sibuk di luar alur live
//       (menutup langkah / baru dijadwalkan) -> 3 alasan menunggu + jadwal -> 4 hasil langkah terakhir dan error
function dataKondisi(nama) {
  const b = liveBot.find((x) => x.nama === nama),
    k = liveKondisi.get(nama);
  const error = k?.terakhir?.hasil === 'error' ? k.terakhir.error || 'tidak diketahui' : null;
  if (b)
    return {
      keadaan: 'sedang',
      teks: `${KONDISI_TAHAP[b.tahap] || b.tahap} · `,
      live: `bot|${b.id}|tahap`,
      kedua: `langkah ${b.langkah} · total `,
      liveKedua: `bot|${b.id}|total`,
      error,
    };
  if (!k)
    return {
      keadaan: 'lewat',
      teks: '—',
      tip: 'Kondisi live hanya ada untuk room yang sedang berjalan di server.',
    };
  if (k.status === 'dieksekusi')
    return { keadaan: 'tidakbisa', teks: 'tidak bisa bertindak: dieksekusi', error };
  if (!k.otak)
    return { keadaan: 'tidakbisa', teks: 'otak belum siap: engine memakai aksi cadangan', error };
  if (k.menutup)
    return {
      keadaan: 'sedang',
      teks: 'menutup langkah: kirim chat dan arsip jejak',
      kedua: `langkah ${k.langkah} · jejaknya sudah tampil`,
      tip: 'Siaran chat dan penyimpanan jejak ke database berjalan sesudah jejak dibuat (di luar total proses).',
      error,
    };
  if (k.sibuk)
    return {
      keadaan: 'menunggu',
      teks: 'langkah baru dijadwalkan, sebentar lagi mulai',
      tip: 'Penjadwal sudah menandai bot sibuk (otak.sibuk), tetapi langkahnya belum melapor tahap pertama.',
      error,
    };
  const hak = k.hak || {};
  let keadaan = 'menunggu',
    teksUtama = 'menunggu giliran';
  if (k.status === 'disandera')
    [keadaan, teksUtama] = ['tidakbisa', 'tidak bisa bertindak: disandera'];
  else if (k.status === 'dibungkam')
    [keadaan, teksUtama] = [
      'tidakbisa',
      hak.vote || hak.aksi || hak.chat_tim
        ? 'tidak bisa chat: dibungkam (Gag)'
        : 'tidak bisa bertindak: dibungkam (Gag)',
    ];
  else if (k.terakhir?.hasil === 'ditunda')
    teksUtama = `${TEKS_DITUNDA}, lantai ${k.lantai?.terisi ?? '?'}/${k.lantai?.maks ?? '?'}`;
  else if (k.hak && !hak.chat && !hak.vote && !hak.aksi && !hak.chat_tim)
    [keadaan, teksUtama] = [
      'lewat',
      hak.sudah_vote
        ? 'sudah vote; fase ini tidak ada tindakan lain'
        : hak.sudah_aksi
          ? 'aksi malam sudah dikirim; tidak ada tindakan lain'
          : 'fase ini tidak ada tindakan',
    ];
  const jadwal =
    typeof k.berikutnya_detik === 'number'
      ? { kedua: 'langkah berikutnya ', liveKedua: `turun|${nama}` }
      : {
          kedua:
            k.fase === 'preparing'
              ? 'persiapan: otak sedang dimuat'
              : k.fase === 'finished'
                ? 'permainan selesai'
                : 'langkah berikutnya di fase sesudahnya',
        };
  const akhir =
    k.terakhir && k.terakhir.hasil !== 'error'
      ? `✓ langkah ${k.terakhir.langkah}: ${HASIL_LANGKAH[k.terakhir.hasil] || k.terakhir.hasil}`
      : '';
  return { keadaan, teks: teksUtama, ...jadwal, akhir, error };
}
// Sel kondisi satu bot: teks utama bertanda keadaan, baris kedua (jadwal atau total), hasil langkah terakhir, dan chip
// error. dataset.kunci = isi tanpa waktu berdetak, dipakai perbaruiKondisi.
function kondisiSel(nama) {
  const d = dataKondisi(nama);
  const box = node('div', undefined, 'kondisi');
  box.dataset.kunci = JSON.stringify([
    d.keadaan,
    d.teks,
    d.kedua,
    d.akhir,
    d.error,
    d.live,
    d.liveKedua,
  ]);
  if (d.tip) box.title = d.tip;
  const utama = node('span', undefined, `kondisi-utama keadaan-${d.keadaan}`);
  if (TANDA[d.keadaan]) utama.append(node('span', TANDA[d.keadaan], 'alur-tanda'));
  utama.append(d.live ? waktuBerdetak(d.live, d.teks) : node('span', d.teks));
  box.append(utama);
  if (d.kedua)
    box.append(
      d.liveKedua
        ? waktuBerdetak(d.liveKedua, d.kedua, '', 'kondisi-kedua')
        : node('small', d.kedua, 'kondisi-kedua'),
    );
  if (d.akhir) box.append(node('small', d.akhir, 'kondisi-kedua keadaan-selesai'));
  if (d.error) box.append(chip(`error: ${d.error}`, 'status-bad'));
  return box;
}
// Polling: hanya sel kondisi yang isinya berubah yang diganti (waktu berdetak sendiri), jadi tabel tidak berkedip.
function perbaruiKondisi() {
  for (const td of document.querySelectorAll('#room-summary [data-kondisi]')) {
    const baru = kondisiSel(td.dataset.kondisi);
    if (td.firstElementChild?.dataset.kunci !== baru.dataset.kunci) td.replaceChildren(baru);
  }
}
// Ringkasan room: status pertandingan, komposisi role, dan tabel bot. Kolom kondisi live tepat di sebelah nama supaya
// tetap terlihat di HP (tabel lebar digulir); klik nama untuk memfilter.
function renderRoomSummary() {
  const box = $('room-summary'),
    room = checkerRoom;
  box.replaceChildren();
  box.hidden = !room;
  if (!room) return;
  const [label, kelas] = STATUS_ROOM[room.status] || [room.status, 'status-muted'];
  const head = node('div', undefined, 'room-head');
  const posisi = [
    room.ronde && `Ronde ${room.ronde}`,
    FASE_LABEL[room.fase] || room.fase,
    room.pemenang && `Pemenang: ${room.pemenang === 'hitman' ? 'Hitman' : 'Warga'}`,
  ].filter(Boolean);
  head.append(chip(label, kelas), node('strong', `Room ${room.kode}`));
  if (posisi.length) head.append(node('span', posisi.join(' · '), 'room-meta'));
  box.append(head);
  if (room.komposisi) {
    const counts = node('div', undefined, 'room-composition');
    for (const [role, jumlah] of Object.entries(room.komposisi))
      counts.append(node('span', `${ROLE_LABEL[role] || role} × ${jumlah}`, 'room-count'));
    if (typeof room.manusia === 'number')
      counts.append(node('span', `${room.manusia} manusia`, 'room-count'));
    box.append(counts);
  }
  if (!room.bot?.length) {
    box.append(node('p', 'Belum ada data bot untuk room ini.', 'hint'));
    return;
  }
  const live = room.status === 'live';
  const table = dataTable({
    kolom: [
      'bot',
      ...(live ? ['kondisi sekarang'] : []),
      'role',
      'status',
      'keputusan terakhir',
      'persona',
      'metode',
    ],
    baris: room.bot.map((b) => [
      b.nama,
      ...(live ? [''] : []),
      ROLE_LABEL[b.role] || b.role,
      b.status,
      lastDecision(b.nama),
      b.persona,
      METODE_LABEL[b.metode] || b.metode,
    ]),
  });
  if (live)
    table.querySelectorAll('th')[1].title =
      'Live tiap detik: tahap langkah yang sedang berjalan beserta lamanya, atau alasan bot sedang tidak melangkah.';
  // Nama bot menjadi tombol filter linimasa; status selain aktif tampil abu-abu (tidak bisa bertindak penuh).
  table.querySelectorAll('tbody tr').forEach((tr, index) => {
    const bot = room.bot[index];
    const button = node('button', bot.nama, 'room-bot');
    button.type = 'button';
    button.title = `Tampilkan jejak ${bot.nama} saja`;
    button.onclick = () => {
      traceFilter = `bot:${bot.nama}`;
      selectedTrace = '';
      renderTraces();
    };
    tr.cells[0].replaceChildren(button);
    if (bot.status && bot.status !== 'aktif')
      tr.cells[live ? 3 : 2].classList.add('keadaan-tidakbisa');
    if (live) {
      tr.cells[1].dataset.kondisi = bot.nama;
      tr.cells[1].replaceChildren(kondisiSel(bot.nama));
    }
  });
  box.append(table);
}
// Pilihan filter: semua jejak, semua keputusan bot, lalu tiap bot di room ini.
function renderFilter() {
  const select = $('checker-filter');
  const names = [
    ...new Set([...(checkerRoom?.bot || []).map((b) => b.nama), ...traces.map(traceBot)]),
  ]
    .filter(Boolean)
    .sort();
  select.replaceChildren(
    new Option('Semua jejak', ''),
    new Option('Semua keputusan bot', 'bot'),
    ...names.map((nama) => new Option(`Bot ${nama}`, `bot:${nama}`)),
  );
  if (![...select.options].some((option) => option.value === traceFilter)) traceFilter = '';
  select.value = traceFilter;
}
// CHAT ROOM: jejak ditampilkan seperti chat di game (lama di atas). Chat manusia dan bot menjadi gelembung;
// langkah bot tanpa chat (vote, aksi, diam) menjadi baris kecil; error berbingkai merah; langkah yang sedang
// diproses (belum punya jejak) berbingkai terang di ujung bawah. Klik satu item untuk melihat prosesnya.
const isSistem = (t) => t.stage === 'sistem';
const isHuman = (t) =>
  Boolean(
    t.manusia ||
    (!t.provider && !t.ringkas && !isSistem(t) && t.stage !== 'npc_brain_error' && !t.live),
  );
function nluTeks(nlu) {
  if (!nlu) return '—';
  const target = (nlu.target || []).map(
    (t) => `${t.pemain} (${t.relasi}${t.prob == null ? '' : ` ${teks(t.prob)}`})`,
  );
  return `${nlu.intent} ${teks(nlu.confidence)}${target.length ? ` · target ${target.join(', ')}` : ''}`;
}
// Bacaan IndoBERT satu chat dalam bahasa awam (intent teknis tetap di detail).
function ringkasNlu(nlu) {
  if (!nlu) return null;
  const sasaran = (nlu.target || [])
    .map((t) => `${t.pemain} (${INTENT_LABEL[t.relasi] || t.relasi})`)
    .join(', ');
  return `dibaca IndoBERT: ${INTENT_LABEL[nlu.intent] || nlu.intent} (yakin ${teks(nlu.confidence)})${sasaran ? ` → ${sasaran}` : ''}`;
}
// Sel riwayat chat: chat sebelumnya yang ikut dibaca IndoBERT sebagai konteks (maks 12, tersimpan sejak pencatat
// NLU menyimpan konteks). Target baru berbentuk {pemain, relasi}, yang lama berupa teks. Isi chat dipasang sebagai
// teks, bukan HTML.
function konteksSel(nlu) {
  const td = node('td');
  const konteks = nlu?.konteks || [];
  if (!konteks.length) {
    td.textContent = nlu ? 'Tidak ada chat sebelumnya.' : '—';
    return td;
  }
  const rincian = node('details', undefined, 'nlu-konteks');
  rincian.append(node('summary', `${konteks.length} chat sebelumnya`));
  const daftar = node('ol');
  for (const c of konteks) {
    const target = (c.target || [])
      .map((t) => (typeof t === 'string' ? t : `${t.pemain}: ${t.relasi}`))
      .join(', ');
    daftar.append(
      node('li', `${c.pengirim}: ${c.teks} — ${c.intent || '-'}${target ? ` · ${target}` : ''}`),
    );
  }
  rincian.append(daftar);
  td.append(rincian);
  return td;
}
// Alur chat manusia (chat_service): persistence_ms, broadcast_ms, nlu_ms (antre thread otak + IndoBERT + simpan
// bacaan; nlu.ms = IndoBERT saja), duration_ms seluruhnya. Selama chat masih diproses (data live), tahap pertama yang
// belum punya waktu adalah yang sedang berjalan; lamanya ± lama berjalan dikurangi tahap yang sudah selesai.
// Alur: 1 tahap yang sedang berjalan -> 2 kotak simpan, kirim, NLU -> 3 diterima = total − tahap terukur -> 4 output
function alurManusia(trace) {
  const live = liveChat.has(trace.id),
    j = liveChat.get(trace.id) || trace;
  const t = j.timings || {},
    n = j.nlu;
  const gagal = ['discarded_state_changed', 'persistence_error'].includes(j.stage);
  const selesai = typeof j.duration_ms === 'number';
  const urutan = [t.persistence_ms, t.broadcast_ms, t.nlu_ms];
  const iSedang = live && !gagal ? urutan.findIndex((v) => typeof v !== 'number') : -1;
  const kurang = urutan.slice(0, Math.max(0, iSedang)).reduce((a, v) => a + v, 0);
  const tahap = (i, nilai, label, tidak) =>
    typeof nilai === 'number'
      ? { keadaan: 'selesai', waktu: duration(nilai) }
      : i === iSedang
        ? { keadaan: 'sedang', waktu: `sedang ${label} · ±`, live: `chat|${trace.id}|${kurang}` }
        : live && !gagal
          ? { keadaan: 'belum', waktu: 'belum' }
          : { keadaan: 'lewat', waktu: gagal ? 'tidak dilalui' : tidak };
  const nlu = tahap(
    2,
    t.nlu_ms,
    'antre/IndoBERT',
    j.match_id == null ? 'lobby: tidak dibaca' : 'tidak tercatat',
  );
  if (typeof t.nlu_ms === 'number' && !n)
    Object.assign(nlu, { keadaan: 'lewat', waktu: 'otak belum siap' });
  if (n)
    nlu.catatan = [
      typeof n.ms === 'number' && `IndoBERT ${duration(n.ms)}`,
      typeof n.ms === 'number' &&
        typeof t.nlu_ms === 'number' &&
        t.nlu_ms - n.ms > 0.05 &&
        `antre + simpan bacaan ${duration(t.nlu_ms - n.ms)}`,
      `${INTENT_LABEL[n.intent] || n.intent}${n.target?.length ? ` → ${n.target.map((x) => x.pemain).join(', ')}` : ''}`,
    ];
  const simpan = tahap(0, t.persistence_ms, 'menyimpan', 'tidak tercatat');
  if (gagal)
    Object.assign(simpan, {
      keadaan: 'gagal',
      catatan: [`${STAGE_LABEL[j.stage]}${j.error ? `: ${j.error}` : ''}`],
    });
  const terukur = urutan.reduce((a, v) => a + (typeof v === 'number' ? v : 0), 0);
  return [
    {
      judul: 'Diterima',
      isi: 'cek pesan + izin chat',
      keadaan: 'selesai',
      waktu: selesai ? duration(Math.max(0, j.duration_ms - terukur)) : 'sudah diterima',
      tip: 'Total dikurangi tahap terukur: validasi pesan, cek izin chat (fase, Gag, Hostage), dan catatan aktivitas.',
    },
    { judul: 'Simpan DB', isi: 'MySQL + chat pertandingan', tip: 'persistence_ms', ...simpan },
    {
      judul: 'Kirim ke pemain',
      isi: 'siaran ke semua di room',
      tip: 'broadcast_ms',
      ...tahap(1, t.broadcast_ms, 'mengirim', 'tidak tercatat'),
    },
    {
      judul: 'NLU IndoBERT',
      isi: 'antre thread otak + IndoBERT',
      tip: 'nlu_ms: antre thread otak + IndoBERT membaca maksud (intent) dan sasaran (target) + simpan bacaan.',
      ...nlu,
    },
    {
      judul: 'Output',
      isi: gagal ? STAGE_LABEL[j.stage] : n ? 'terkirim dan terbaca' : 'terkirim',
      keadaan: selesai ? (gagal ? 'gagal' : 'selesai') : live ? 'belum' : n ? 'selesai' : 'lewat',
      waktu: selesai ? `total ${duration(j.duration_ms)}` : live ? 'belum' : 'total tidak tercatat',
      tip: 'duration_ms: dari pesan masuk sampai selesai dibaca IndoBERT.',
    },
  ];
}
// Penjelasan singkat error langkah bot: batas waktu dijelaskan dalam bahasa awam, error lain memakai pesannya.
function penjelasanError(trace) {
  if (trace.error === 'TimeoutError') {
    const batas = trace.batas_detik ?? '?';
    if (trace.error_tahap === 'berpikir')
      return `langkah bot melewati batas ${batas} detik (termasuk antre di thread otak/IndoBERT)`;
    if (trace.error_tahap === 'tulis')
      return `templat cadangan melewati batas ${batas} detik sesudah LLM melewati batasnya`;
    if (trace.error_tahap === 'chat_tim')
      return `chat tim (templat cadangan) melewati batas ${batas} detik`;
    return `${TAHAP_GAGAL[trace.error_tahap] || 'langkah bot'} melewati batas waktu`;
  }
  if (trace.error_pesan) return trace.error_pesan;
  return trace.error_pesan === '' ? 'tanpa pesan' : 'pesan tidak tercatat (jejak lama)';
}
// Role bot dari ringkasan room (jejak error dan item live tidak membawa role).
function roleBot(nama) {
  return (checkerRoom?.bot || []).find((x) => x.nama === nama)?.role;
}
// Item chat untuk langkah bot yang sedang diproses (belum punya jejak): tahap sekarang dan lamanya berdetak.
function itemLive(trace, selected, onSelect) {
  const b = trace.live,
    role = roleBot(b.nama);
  const el = node(
    'button',
    undefined,
    `trace chat-item chat-step chat-live${selected ? ' selected' : ''}`,
  );
  el.type = 'button';
  const head = node('span', undefined, 'trace-head');
  head.append(
    node('strong', b.nama),
    chip(trace.selesai ? 'selesai' : 'sedang diproses', 'status-pending'),
  );
  if (role) head.append(chip(ROLE_LABEL[role] || role, roleClass(role)));
  const [, label] = TAHAP_LIVE[b.tahap] || [null, b.tahap];
  const info = node('small', undefined, 'chat-info');
  info.append(
    trace.selesai
      ? node('span', 'langkah selesai, jejaknya sedang dimuat')
      : waktuBerdetak(`bot|${b.id}|tahap`, `${TANDA.sedang} sedang ${label} · `),
  );
  const meta = node('small', undefined, 'chat-meta');
  meta.append(
    trace.selesai
      ? node('span', `langkah ${b.langkah}`)
      : waktuBerdetak(`bot|${b.id}|total`, `langkah ${b.langkah} · berjalan `),
  );
  el.append(head, info, meta);
  el.onclick = () => onSelect(trace.id);
  return el;
}
function chatItem(trace, selected, onSelect) {
  if (isSistem(trace)) return node('p', trace.message, 'chat-system');
  if (trace.live) return itemLive(trace, selected, onSelect);
  const r = trace.ringkas,
    bot = r?.bot,
    error = trace.stage === 'npc_brain_error',
    human = isHuman(trace),
    bubble = human || r?.nlg === 'terkirim';
  const kind = error
    ? 'chat-step chat-error'
    : human
      ? 'chat-human'
      : bubble
        ? 'chat-bot'
        : 'chat-step';
  const b = node('button', undefined, `trace chat-item ${kind}${selected ? ' selected' : ''}`);
  b.type = 'button';
  if (trace.stage) b.title = `Tahap teknis: ${trace.stage}`;
  const head = node('span', undefined, 'trace-head');
  head.append(node('strong', bot?.nama || trace.sender));
  const role = bot?.role || (error ? roleBot(trace.sender) : null);
  if (human) head.append(chip('manusia', 'status-muted'));
  if (error) head.append(chip('error', 'status-bad'));
  if (bot?.metode && bot.metode !== 'fuzzy')
    head.append(chip(METODE_SINGKAT[bot.metode] || bot.metode, 'status-good'));
  if (role) head.append(chip(ROLE_LABEL[role] || role, roleClass(role)));
  if (r?.ditolak) head.append(chip('ditolak engine', 'status-bad'));
  if (human && liveChat.has(trace.id)) head.append(chip('sedang diproses', 'status-pending'));
  b.append(head);
  if (bubble) b.append(node('span', trace.message, 'chat-text'));
  const info = [];
  if (error) info.push(`Error: ${trace.error || 'tidak diketahui'} — ${penjelasanError(trace)}`);
  else if (human) {
    const sedang = liveChat.has(trace.id) && alurManusia(trace).find((k) => k.keadaan === 'sedang');
    info.push(
      ringkasNlu(trace.nlu) ||
        (sedang
          ? `${TANDA.sedang} sedang diproses: ${sedang.judul}`
          : liveChat.has(trace.id)
            ? 'sedang diproses server'
            : 'belum dibaca IndoBERT'),
    );
  }
  if (r?.nlg === 'ditunda')
    info.push(`${TEKS_DITUNDA}${r.usulan ? `: akan ditulis “${r.usulan}”` : ''}`);
  if (r) {
    // Chat sudah tampil sebagai gelembung; sisanya vote/aksi rahasia langkah yang sama.
    const lain = (r.keputusan || [])
      .filter((k) => !bubble || !k.startsWith('chat '))
      .map(teksKeputusan);
    if (lain.length) info.push(lain.join(' · '));
    else if (!bubble) info.push('diam: tidak chat, vote, atau beraksi');
  } else if (!human && !error)
    info.push(`${trace.message} · ${STAGE_LABEL[trace.stage] || trace.stage}`);
  const meta = [
    bot?.ronde && `R${bot.ronde} ${FASE_LABEL[bot.fase] || bot.fase || ''}`.trim(),
    waktu(trace.created_at),
    typeof trace.duration_ms === 'number' &&
      `${error ? 'gagal sesudah' : 'proses'} ${duration(trace.duration_ms)}`,
    error && trace.error_tahap && `saat ${TAHAP_GAGAL[trace.error_tahap] || trace.error_tahap}`,
  ].filter(Boolean);
  for (const line of info)
    b.append(node('small', line, error ? 'chat-info chat-info-error' : 'chat-info'));
  const baris = node('small', meta.join(' · '), 'chat-meta');
  // Chat manusia yang masih diproses: lama berjalannya ikut berdetak.
  if (human && liveChat.has(trace.id))
    baris.append(waktuBerdetak(`chat|${trace.id}|0`, ' · berjalan '));
  b.append(baris);
  b.onclick = () => onSelect(trace.id);
  return b;
}
// Render ulang chat; tetap menempel di bawah bila sebelumnya sudah di bawah (seperti chat game). ekor: elemen tetap
// di ujung bawah (item live Checker), dipasang ulang tanpa dibuat ulang.
function renderChat(box, list, selectedId, onSelect, ekor = []) {
  const bawah = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...list.map((t) => chatItem(t, t.id === selectedId, onSelect)), ...ekor);
  if (bawah) box.scrollTop = box.scrollHeight;
}
// Langkah live dan jejaknya sama bila bot, pertandingan, dan nomor langkahnya sama.
function cocokLive(trace, b) {
  return (
    traceBot(trace) === b.nama &&
    trace.match_id === b.match_id &&
    (trace.ringkas?.bot?.langkah ?? trace.langkah) === b.langkah
  );
}
// Item live yang tampil (sesuai filter): langkah bot yang sedang berjalan dan belum punya jejak, ditambah item
// terpilih yang baru selesai sampai jejaknya dimuat.
function liveTerlihat() {
  const daftar = liveBot.map((b) => ({ id: `live:${b.id}`, live: b, sender: b.nama }));
  if (livePilihan?.hilang)
    daftar.push({
      id: `live:${livePilihan.b.id}`,
      live: livePilihan.b,
      sender: livePilihan.b.nama,
      selesai: true,
    });
  return daftar.filter(
    (l) =>
      !traces.some((t) => cocokLive(t, l.live)) &&
      (!traceFilter || traceFilter === 'bot' || traceFilter === `bot:${l.sender}`),
  );
}
// Item live terpilih yang sudah selesai pindah ke jejak langkah yang sama. Langkah diam tidak punya jejak: sesudah
// daftar dimuat ulang, pilihan kembali ke item terbaru dengan pemberitahuan.
function selesaikanPilihanLive() {
  if (!livePilihan) return;
  if (selectedTrace !== `live:${livePilihan.b.id}`) {
    livePilihan = null;
    return;
  }
  const b = livePilihan.b,
    jejak = traces.find((t) => cocokLive(t, b));
  if (jejak) {
    selectedTrace = jejak.id;
    livePilihan = null;
  } else if (livePilihan.hilang && segarKe > livePilihan.segar) {
    notice(
      `Langkah ${b.nama} ke-${b.langkah} selesai tanpa jejak: langkah diam (tanpa chat, vote, atau aksi) tidak dicatat.`,
    );
    selectedTrace = '';
    livePilihan = null;
  }
}
// Isi ujung bawah chat room dengan item live; tetap menempel di bawah bila sebelumnya di bawah.
function isiLiveBox() {
  const box = $('traces'),
    bawah = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  liveBox.replaceChildren(
    ...liveTerlihat().map((l) => chatItem(l, l.id === selectedTrace, selectTrace)),
  );
  if (bawah) box.scrollTop = box.scrollHeight;
}
function selectTrace(id) {
  selectedTrace = id;
  if (!(livePilihan && `live:${livePilihan.b.id}` === id)) {
    const live = id.startsWith('live:') ? liveTerlihat().find((l) => l.id === id) : null;
    livePilihan = live ? { b: live.live, hilang: false, segar: segarKe } : null;
  }
  renderTraces();
}
// Render chat room (sesuai filter) dan detail item terpilih; default item terbaru.
function renderTraces() {
  renderFilter();
  selesaikanPilihanLive();
  const box = $('traces');
  const list = visibleTraces(),
    live = liveTerlihat();
  if (!list.length && !live.length) {
    liveBox.replaceChildren();
    box.textContent = traces.length
      ? 'Tidak ada jejak untuk filter ini.'
      : 'Belum ada jejak AI di room ini.';
    $('trace-detail').textContent = 'Belum ada data.';
    renderedDetail = '';
    return;
  }
  const active =
    live.find((l) => l.id === selectedTrace) ||
    list.find((t) => t.id === selectedTrace) ||
    list[0] ||
    live[0];
  selectedTrace = active.id;
  renderChat(box, [...list].reverse(), active.id, selectTrace, [liveBox]);
  isiLiveBox();
  showDetail(active).catch((error) => notice(error.message));
}
// Penjelasan langkah sebelumnya dari bot yang sama (untuk kolom perubahan), bila sudah dimuat.
function sebelumnya(trace, urut, ambil) {
  const nama = traceBot(trace),
    i = urut.findIndex((t) => t.id === trace.id);
  for (let j = i - 1; j >= 0; j--) if (traceBot(urut[j]) === nama) return ambil(urut[j]);
  return null;
}
// ALUR PROSES di atas detail tiap item: kotak tahap berpanah, lama tiap tahap di bawah kotaknya. Keadaan kotak:
// selesai ✓, sedang (berdenyut, waktunya berdetak), belum (redup), lewat (redup: tidak dilalui), gagal ✗.
// k = {judul, isi, keadaan, waktu, live?, catatan?, tip?, sisa?}
function kotakAlur(k) {
  const li = node('li', undefined, `alur-tahap keadaan-${k.keadaan}${k.sisa ? ' alur-sisa' : ''}`);
  if (k.tip) li.title = k.tip;
  const kotak = node('div', undefined, 'alur-kotak');
  const judul = node('strong', undefined, 'alur-judul');
  if (TANDA[k.keadaan]) judul.append(node('span', TANDA[k.keadaan], 'alur-tanda'));
  judul.append(node('span', k.judul));
  kotak.append(judul);
  if (k.isi) kotak.append(node('small', k.isi, 'alur-isi'));
  li.append(
    kotak,
    k.live ? waktuBerdetak(k.live, k.waktu, '', 'alur-waktu') : node('span', k.waktu, 'alur-waktu'),
  );
  for (const c of k.catatan || []) if (c) li.append(node('small', c, 'alur-catatan'));
  return li;
}
// Kotak "Alur proses": judul, deret kotak tahap, dan keterangan. dataset.kunci = isi tanpa waktu berdetak (pasangAlur).
function alurProses(daftar, keterangan) {
  const box = node('section', undefined, 'alur');
  box.setAttribute('aria-label', 'Alur proses');
  const ol = node('ol', undefined, 'alur-baris');
  for (const k of daftar) ol.append(kotakAlur(k));
  box.append(node('h4', 'Alur proses', 'alur-kepala'), ol);
  if (keterangan) box.append(node('p', keterangan, 'hint alur-keterangan'));
  box.dataset.kunci = JSON.stringify(
    daftar.map((k) => [k.keadaan, k.judul, k.isi, k.waktu, k.live, k.catatan]),
  );
  return box;
}
// Polling: alur yang tampil diganti hanya bila isinya berubah (waktu yang berdetak tidak ikut dihitung).
function pasangAlur(container, alur) {
  const lama = container.querySelector('.alur');
  if (lama && lama.dataset.kunci !== alur.dataset.kunci) lama.replaceWith(alur);
}
// Kotak alur langkah bot: judul dan keterangan singkat, urut sesuai brain_turn.
const KOTAK_BOT = {
  input: ['Input', 'snapshot permainan'],
  nlu: ['NLU', 'IndoBERT + sinkron ingatan'],
  fuzzy: ['Fuzzy', 'menimbang bukti, memutuskan'],
  penjelasan: ['Penjelasan', 'disusun untuk panel'],
  engine: ['Engine', 'vote / aksi rahasia'],
  llm: ['LLM', 'penulis kalimat'],
  aturan: ['Cek aturan', 'aturan, prompt, templat'],
  sisa: ['Antre + mengetik', 'sisa di luar tahap terukur'],
  output: ['Output', 'hasil langkah'],
};
// Tahap live yang lamanya masuk tiap kotak.
const BAGIAN_LIVE = {
  input: [],
  nlu: ['nlu'],
  fuzzy: ['logika'],
  penjelasan: ['penjelasan'],
  engine: ['engine', 'tim'],
  llm: ['nlg', 'llm'],
  aturan: ['aturan'],
  sisa: ['antre', 'giliran', 'antre_nlg', 'ketik', 'simpan', 'jejak'],
  output: [],
};
const KET_LIVE =
  'Kotak terang = tahap yang sedang berjalan; waktunya berdetak. Antre thread otak dan antre thread penulis menyala di kotak yang sedang ditunggu (NLU atau LLM); lamanya dihitung ke kotak Antre + mengetik.';
const KET_BOT =
  'Waktu di bawah kotak dijumlah = total. Antre + mengetik = total dikurangi tahap yang diukur sendiri, dirinci menjadi antre thread otak (1 thread untuk semua room, juga dipakai IndoBERT membaca chat), antre thread penulis, jeda mengetik, simpan chat, dan lainnya (snapshot, giliran bicara, menyusun jejak, menunggu event loop).';
const KET_MANUSIA =
  'Waktu di bawah kotak = lama tiap tahap di server. NLU = antre thread otak (dipakai bersama langkah semua bot) + IndoBERT + simpan bacaan.';
const KET_ERROR = 'Kotak merah ✗ = tahap tempat langkah gagal; kotak sesudahnya tidak dilalui.';
// Alur langkah bot dari tahap live (langkah yang sedang berjalan) atau dari tahap gagal (jejak error).
// aktif = kotak yang menyala; lama = ms tiap tahap live yang sudah lewat;
// akhir = {live: kunci waktu} | {gagal: true, ms} | {selesai: true}.
// Alur: 1 kotak sebelum aktif: selesai/tidak dilalui -> 2 kotak aktif: sedang/gagal -> 3 kotak sesudahnya: belum
//       -> 4 catatan antre di kotak yang ditunggu
function alurLangkah(aktif, label, lama, akhir) {
  const ids = Object.keys(KOTAK_BOT),
    iAktif = Math.max(0, ids.indexOf(aktif));
  const jumlah = (id) => BAGIAN_LIVE[id].reduce((s, t) => s + (lama[t] || 0), 0);
  const pernah = (id) => BAGIAN_LIVE[id].some((t) => t in lama);
  return ids.map((id, i) => {
    const [judul, isi] = KOTAK_BOT[id];
    // Antre yang sudah lewat dicatat di kotak yang ditunggunya (bukan bila antre itu sendiri tahap yang menyala).
    const catatan = [
      id === 'nlu' && typeof lama.antre === 'number' && `antre thread otak ${duration(lama.antre)}`,
      id === 'llm' &&
        typeof lama.antre_nlg === 'number' &&
        `antre thread penulis ${duration(lama.antre_nlg)}`,
    ].filter((c) => c && !c.startsWith(label));
    const k = { judul, isi, sisa: id === 'sisa', catatan };
    if (i === iAktif) {
      if (akhir.gagal)
        return {
          ...k,
          keadaan: 'gagal',
          waktu: `gagal saat ${label}${typeof akhir.ms === 'number' ? ` · ${duration(akhir.ms)}` : ''}`,
        };
      if (akhir.selesai) return { ...k, keadaan: 'selesai', waktu: `terakhir: ${label}` };
      return { ...k, keadaan: 'sedang', waktu: `sedang ${label} · `, live: akhir.live };
    }
    if (i > iAktif)
      return akhir.gagal
        ? { ...k, catatan: [], keadaan: 'lewat', waktu: 'tidak dilalui' }
        : { ...k, catatan: [], keadaan: 'belum', waktu: 'belum' };
    if (id === 'input') return { ...k, keadaan: 'selesai', waktu: 'snapshot diambil' };
    if (!pernah(id)) return { ...k, keadaan: 'lewat', waktu: 'tidak dilalui' };
    return { ...k, keadaan: 'selesai', waktu: duration(jumlah(id)) };
  });
}
// Alur langkah yang sedang berjalan: kotak tahap live menyala; item terpilih yang baru selesai berhenti di tahap
// terakhirnya sampai jejaknya dimuat.
function alurLive(l) {
  const [aktif, label] = TAHAP_LIVE[l.live.tahap] || ['input', l.live.tahap];
  return alurLangkah(
    aktif,
    label,
    l.live.lama || {},
    l.selesai ? { selesai: true } : { live: `bot|${l.live.id}|tahap` },
  );
}
// Alur jejak error: kotak tahap gagal ditandai ✗. Tahap live (mis. masih antre thread otak) lebih tepat daripada
// tahap brain_turn untuk berpikir dan menulis; jejak lama tanpa keduanya tidak punya alur.
function alurError(trace) {
  const KOTAK_GAGAL = {
    lihat: 'input',
    berpikir: 'fuzzy',
    vote_aksi: 'engine',
    chat_tim: 'engine',
    tulis: 'llm',
    kirim: 'output',
    jejak: 'output',
  };
  const lama = trace.tahap_ms || {};
  const tepat =
    ['berpikir', 'tulis', 'chat_tim'].includes(trace.error_tahap) && TAHAP_LIVE[trace.tahap_live];
  const [aktif, label] = tepat || [
    KOTAK_GAGAL[trace.error_tahap] || 'input',
    TAHAP_GAGAL[trace.error_tahap] || 'tahap tidak tercatat',
  ];
  return alurLangkah(aktif, label, lama, {
    gagal: true,
    ms: tepat ? lama[trace.tahap_live] : undefined,
  });
}
// Kolom output jejak (JSON teks: action, target, chat tim); jejak rusak atau lama menjadi objek kosong.
function keluaranJejak(trace) {
  try {
    return JSON.parse(trace.output || '{}') || {};
  } catch {
    return {};
  }
}
// Alur langkah bot yang sudah selesai. Arti angka (timings, ms) mengikuti bot_controller: nlu_ms, logika_ms, dan
// penjelasan_ms dari BrainRuntime.langkah; nlg_ms, llm_ms, dan aturan_ms dari waktu_jejak; antre, engine, chat tim,
// mengetik, dan simpan dari LangkahBerjalan (checker_service); duration_ms = brain_turn sampai jejak dibuat.
// Alur: 1 kotak tahap terukur -> 2 LLM dan cek aturan menurut status kalimat -> 3 sisa = total − tahap terukur
//       -> 4 output
function alurBot(trace) {
  const t = trace.timings || {},
    p = trace.penjelasan || {},
    r = trace.ringkas || {};
  const nlg = p.nlg || {},
    e = p.engine,
    keluaran = keluaranJejak(trace);
  const status = nlg.status || r.nlg;
  const terkirim = status === 'terkirim';
  const percobaan = (nlg.percobaan_llm || []).map(String);
  const lewatBatas = percobaan.some((s) => s.includes('melewati batas'));
  const llmDipakai = terkirim && ((t.llm_ms || 0) > 0 || percobaan.length > 0);
  const aksi = e?.action ?? keluaran.action,
    target = e?.target ?? keluaran.target;
  const metode = (p.bot || r.bot || {}).metode;
  const ms = (x) => (typeof x === 'number' ? duration(x) : 'tidak tercatat');
  const tanpaKalimat =
    {
      ditunda: TEKS_DITUNDA,
      'tidak ada chat': 'tidak ada chat',
      'tidak terkirim': 'kalimat tidak terkirim',
    }[status] || 'tidak dilalui';
  // Sisa hanya dihitung bila semua tahap yang lama bisa diukur ada angkanya; chat tim (bisa detik-an, LLM) wajib punya
  // tim_ms, karena tanpa itu sisa tidak lagi berarti antre + mengetik.
  const terukur = [
    t.nlu_ms,
    t.logika_ms,
    t.penjelasan_ms,
    ...(terkirim ? [t.nlg_ms] : []),
    ...(keluaran.chat_tim ? [t.tim_ms] : []),
  ];
  const sisa =
    typeof trace.duration_ms === 'number' && terukur.every((x) => typeof x === 'number')
      ? Math.max(0, trace.duration_ms - terukur.reduce((a, b) => a + b, 0) - (t.engine_ms || 0))
      : null;
  const rincian = [
    ['antre thread otak', t.antre_otak_ms],
    ['antre thread penulis', t.antre_nlg_ms],
    ['jeda mengetik', t.ketik_ms],
    ['simpan chat', t.simpan_ms],
  ].filter(([, v]) => typeof v === 'number');
  const catatanSisa = rincian.map(([n, v]) => `${n} ${duration(v)}`);
  if (sisa !== null && rincian.length)
    catatanSisa.push(
      `lainnya ${duration(Math.max(0, sisa - rincian.reduce((a, [, v]) => a + v, 0)))}`,
    );
  if (sisa !== null && typeof t.engine_ms !== 'number')
    catatanSisa.push('termasuk vote/aksi ke engine (jejak lama)');
  if (lewatBatas) catatanSisa.push('termasuk menunggu LLM sampai batas');
  if (status === 'tidak terkirim') catatanSisa.push('termasuk menulis kalimat yang tidak terkirim');
  const llm = !terkirim
    ? { keadaan: 'lewat', waktu: tanpaKalimat }
    : lewatBatas
      ? { keadaan: 'gagal', waktu: 'melewati batas', catatan: ['kalimat dari templat cadangan'] }
      : llmDipakai
        ? {
            keadaan: 'selesai',
            waktu: ms(t.llm_ms),
            catatan: [
              nlg.sumber && nlg.sumber !== 'llm' && 'ditolak aturan → templat',
              percobaan.length > 1 && `${percobaan.length} percobaan`,
            ],
          }
        : { keadaan: 'lewat', waktu: 'tidak dipakai', catatan: ['kalimat dari templat'] };
  return [
    {
      judul: 'Input',
      isi: 'snapshot permainan',
      keadaan: 'selesai',
      waktu: 'seketika',
      tip: 'Bot mengambil keadaan permainan miliknya (tanpa role pemain lain); lamanya masuk "lainnya".',
    },
    {
      judul: 'NLU',
      isi: KOTAK_BOT.nlu[1],
      keadaan: 'selesai',
      waktu: ms(t.nlu_ms),
      catatan: [
        p.nlu_dibaca &&
          (p.nlu_dibaca.length ? `${p.nlu_dibaca.length} chat baru dibaca` : 'tanpa chat baru'),
      ],
      tip: 'nlu_ms: ingatan mencatat snapshot dan IndoBERT membaca chat baru (mendekati 0 bila diambil dari memo).',
    },
    {
      judul: metode && metode !== 'fuzzy' ? METODE_LABEL[metode] || metode : 'Fuzzy',
      isi: KOTAK_BOT.fuzzy[1],
      keadaan: 'selesai',
      waktu: ms(t.logika_ms),
      tip: 'logika_ms: fuzzy_controller.putuskan memilih chat, vote, dan aksi.',
    },
    {
      judul: 'Penjelasan',
      isi: KOTAK_BOT.penjelasan[1],
      keadaan: 'selesai',
      waktu: ms(t.penjelasan_ms),
      tip: 'penjelasan_ms: hanya untuk panel admin; tidak memengaruhi keputusan.',
    },
    {
      judul: 'Engine',
      isi:
        aksi && aksi !== 'wait'
          ? `${AKSI_LABEL[aksi] || aksi}${target ? ` → ${target}` : ''}`
          : 'tidak ada vote/aksi',
      keadaan: e?.ditolak ? 'gagal' : 'selesai',
      waktu: typeof t.engine_ms === 'number' ? duration(t.engine_ms) : 'tidak diukur',
      catatan: [
        e?.ditolak && `ditolak engine: ${e.ditolak}`,
        keluaran.chat_tim &&
          `chat tim ${keluaran.chat_tim.status}${typeof t.tim_ms === 'number' ? ` · ${duration(t.tim_ms)}` : ''}`,
      ],
      tip: 'engine_ms: vote atau aksi rahasia diterapkan ke game (jejak lama: masuk Antre + mengetik).',
    },
    {
      judul: 'LLM',
      isi: llmDipakai || lewatBatas ? nlg.penulis || 'penulis LLM' : KOTAK_BOT.llm[1],
      tip: 'llm_ms: total lama panggilan LLM untuk kalimat ini, termasuk percobaan ulang.',
      ...llm,
    },
    {
      judul: 'Cek aturan',
      isi: KOTAK_BOT.aturan[1],
      keadaan: terkirim ? 'selesai' : 'lewat',
      waktu: terkirim ? ms(waktuAturan(t)) : tanpaKalimat,
      catatan: [terkirim && nlg.pelanggaran?.length && `pelanggaran: ${teks(nlg.pelanggaran)}`],
      tip: 'aturan_ms = lama menulis kalimat − lama LLM: menyusun prompt, memeriksa aturan, dan templat.',
    },
    {
      judul: 'Antre + mengetik',
      isi: KOTAK_BOT.sisa[1],
      sisa: true,
      keadaan: sisa === null ? 'lewat' : 'selesai',
      waktu: sisa === null ? 'data tidak cukup' : duration(sisa),
      catatan: catatanSisa,
      tip: 'Total dikurangi NLU, Fuzzy, penjelasan, engine, chat tim, dan menulis kalimat. "Data tidak cukup" bila salah satunya tidak tercatat.',
    },
    {
      judul: 'Output',
      isi: terkirim
        ? 'chat terkirim'
        : status === 'ditunda'
          ? 'chat ditunda'
          : r.keputusan?.length
            ? r.keputusan.map(teksKeputusan).join(' · ')
            : 'diam',
      keadaan: 'selesai',
      waktu:
        typeof trace.duration_ms === 'number'
          ? `total ${duration(trace.duration_ms)}`
          : 'tidak tercatat',
      catatan: [
        trace.stage === 'npc_brain_rejected' && 'vote/aksi ditolak engine (lihat kotak Engine)',
      ],
      tip: 'duration_ms: dari langkah dimulai sampai jejak dibuat (siaran chat dan arsip database tidak ikut).',
    },
  ];
}
// Detail langkah bot yang sedang berjalan: alur live (tahap sekarang berdenyut, waktunya berdetak).
function renderLiveDetail(container, l) {
  const b = l.live,
    role = roleBot(b.nama);
  container.replaceChildren();
  container.classList.remove('empty-state');
  const head = node('div', undefined, 'decision-head');
  head.append(
    node('strong', b.nama),
    chip(l.selesai ? 'selesai' : 'sedang diproses', 'status-pending'),
  );
  if (role) head.append(chip(ROLE_LABEL[role] || role, roleClass(role)));
  head.append(
    l.selesai
      ? node('span', `langkah ${b.langkah}`, 'room-meta')
      : waktuBerdetak(`bot|${b.id}|total`, `langkah ${b.langkah} · berjalan `, '', 'room-meta'),
  );
  container.append(
    head,
    alurProses(alurLive(l), KET_LIVE),
    node(
      'p',
      l.selesai
        ? 'Langkah selesai; jejaknya sedang dimuat. Langkah diam (tanpa chat, vote, atau aksi) tidak dicatat.'
        : 'Langkah ini belum punya jejak. Rincian keputusan muncul setelah langkah selesai; langkah diam (tanpa chat, vote, atau aksi) tidak dicatat.',
      'hint',
    ),
  );
}
// Detail jejak error langkah bot: alur dengan tahap gagal ✗, lalu kotak error (jenis, pesan, tahap, waktu, bot).
function renderError(container, trace) {
  container.replaceChildren();
  container.classList.remove('empty-state');
  const role = roleBot(trace.sender);
  const head = node('div', undefined, 'decision-head');
  head.append(node('strong', trace.sender), chip('error', 'status-bad'));
  if (role) head.append(chip(ROLE_LABEL[role] || role, roleClass(role)));
  head.append(
    node(
      'span',
      [trace.langkah && `langkah ${trace.langkah}`, waktu(trace.created_at)]
        .filter(Boolean)
        .join(' · '),
      'room-meta',
    ),
  );
  container.append(head);
  if (trace.error_tahap || trace.tahap_live)
    container.append(alurProses(alurError(trace), KET_ERROR));
  const kotak = node('section', undefined, 'kotak-error');
  kotak.setAttribute('aria-label', 'Error langkah bot');
  kotak.append(
    node('strong', `Error: ${trace.error || 'tidak diketahui'} — ${penjelasanError(trace)}`),
    keyValues(
      [
        ['Jenis', trace.error || 'tidak tercatat'],
        [
          'Pesan',
          trace.error_pesan ||
            (trace.error_pesan !== ''
              ? 'tidak tercatat (jejak lama)'
              : trace.error === 'TimeoutError'
                ? 'tanpa pesan (TimeoutError memang tidak berpesan)'
                : 'tanpa pesan'),
        ],
        [
          'Tahap gagal',
          TAHAP_GAGAL[trace.error_tahap]
            ? `${TAHAP_GAGAL[trace.error_tahap]}${trace.tahap_live ? ` · tahap live: ${KONDISI_TAHAP[trace.tahap_live] || trace.tahap_live}` : ''}`
            : 'tidak tercatat (jejak lama)',
        ],
        [
          'Waktu',
          [
            tanggal(trace.created_at),
            typeof trace.duration_ms === 'number' && `gagal sesudah ${duration(trace.duration_ms)}`,
          ]
            .filter(Boolean)
            .join(' · '),
        ],
        ['Batas waktu', trace.batas_detik ? `${trace.batas_detik} detik` : null],
        [
          'Bot',
          `${trace.sender}${role ? ` (${ROLE_LABEL[role] || role})` : ''}${trace.langkah ? `, langkah ${trace.langkah}` : ''}`,
        ],
      ].filter(([, v]) => v !== null),
    ),
  );
  const teknis = node('details'),
    box = node('div', undefined, 'report');
  renderReport(box, trace);
  teknis.append(node('summary', 'Teknis: seluruh jejak'), box);
  container.append(kotak, teknis);
}
// Polling live: alur item terpilih diganti bila tahapnya berubah, tanpa merender ulang detail (tab dan rincian yang
// sedang terbuka tetap).
function perbaruiAlurTerpilih() {
  const container = $('trace-detail');
  const live = liveTerlihat().find((l) => l.id === selectedTrace);
  if (live) {
    pasangAlur(container, alurProses(alurLive(live), KET_LIVE));
    return;
  }
  const trace = traces.find((t) => t.id === selectedTrace);
  if (trace && isHuman(trace) && liveChat.has(trace.id))
    pasangAlur(container, alurProses(alurManusia(trace), KET_MANUSIA));
}
// Jejak otak bot dimuat lengkap sekali (cache); chat manusia dan error memakai kartunya sendiri; jejak lain laporan
// lama. Item live dirender sekali per item; tahapnya diperbarui perbaruiAlurTerpilih.
async function showDetail(trace) {
  const container = $('trace-detail');
  const key = trace.live
    ? `live|${trace.id}|${trace.selesai ? 1 : 0}`
    : `${trace.id}|${trace.stage}|${trace.duration_ms}|${traces.length}|${liveChat.has(trace.id)}`;
  if (renderedDetail === key) {
    perbaruiAlurTerpilih();
    return;
  }
  renderedDetail = key;
  if (trace.live) {
    renderLiveDetail(container, trace);
    return;
  }
  if (trace.stage === 'npc_brain_error') {
    renderError(container, trace);
    return;
  }
  const urut = [...visibleTraces()].reverse();
  const lama = () => sebelumnya(trace, urut, (t) => traceDetails.get(t.id)?.penjelasan);
  if (isHuman(trace)) {
    renderHuman(container, trace, urut, selectTrace);
    return;
  }
  if (!trace.ringkas) {
    renderReport(container, trace);
    return;
  }
  if (traceDetails.has(trace.id)) {
    renderDecision(container, traceDetails.get(trace.id), lama());
    return;
  }
  container.classList.remove('empty-state');
  container.textContent = 'Memuat penjelasan keputusan…';
  const code = $('checker-room').value,
    epoch = generation;
  try {
    const data = await request(
      `/api/panel/checker/${encodeURIComponent(code)}/jejak/${encodeURIComponent(trace.id)}`,
    );
    if (epoch !== generation || !token || code !== $('checker-room').value) return;
    if (traceDetails.size >= 200) traceDetails.delete(traceDetails.keys().next().value);
    traceDetails.set(trace.id, data);
    if (selectedTrace === trace.id) renderDecision(container, data, lama());
  } catch (error) {
    if (selectedTrace === trace.id) {
      renderedDetail = '';
      container.textContent = error.message;
    }
  }
}
// Langkah bernomor dengan lama prosesnya: [judul, ms atau null, ...isi (teks/elemen)].
function processSteps(steps) {
  const ol = node('ol', undefined, 'process-steps');
  for (const [judul, ms, ...isi] of steps) {
    const li = node('li');
    const head = node('div', undefined, 'process-head');
    head.append(node('strong', judul));
    if (ms !== null) head.append(node('span', duration(ms), 'process-time'));
    li.append(head);
    for (const x of isi) if (x) li.append(typeof x === 'string' ? node('p', x, 'hint') : x);
    ol.append(li);
  }
  return ol;
}
// Chat manusia: alur proses di atas, isi chat, bacaan NLU IndoBERT (intent, target), dan reaksi bot sesudahnya.
function renderHuman(container, trace, urut, onSelect) {
  container.replaceChildren();
  container.classList.remove('empty-state');
  const live = liveChat.has(trace.id),
    n = (liveChat.get(trace.id) || trace).nlu;
  const head = node('div', undefined, 'decision-head');
  head.append(node('strong', trace.sender), chip('manusia', 'status-muted'));
  if (live) head.append(chip('sedang diproses', 'status-pending'));
  head.append(node('span', waktu(trace.created_at), 'room-meta'));
  container.append(
    head,
    alurProses(alurManusia(trace), KET_MANUSIA),
    node('h4', 'Isi chat', 'report-title'),
    node('pre', trace.message || '', 'output'),
  );
  if (n) {
    container.append(
      node('h4', 'Bacaan NLU IndoBERT', 'report-title'),
      keyValues([
        [
          'Maksud (intent)',
          `${INTENT_LABEL[n.intent] || n.intent} · ${n.intent} (keyakinan ${teks(n.confidence)})`,
        ],
        ['Model', n.sumber],
      ]),
      dataTable({
        kolom: ['pemain', 'relasi', 'probabilitas'],
        baris: (n.target || []).map((x) => [x.pemain, x.relasi, x.prob]),
      }),
      node(
        'p',
        'Intent: offend = menuduh/menyerang, defend = membela, neutral = netral. Target: pemain yang dituju beserta relasinya. Bot membaca chat ini dengan hasil yang sama (memo NLU) di langkah berikutnya.',
        'hint',
      ),
    );
  } else
    container.append(
      node(
        'p',
        live
          ? 'IndoBERT belum selesai membaca chat ini.'
          : 'Belum dibaca IndoBERT: otak NPC belum siap saat pesan masuk, room masih lobby, atau pesan dari versi lama.',
        'hint',
      ),
    );
  const i = urut.findIndex((x) => x.id === trace.id),
    reaksi = [];
  for (const x of urut.slice(i + 1)) {
    if (isHuman(x)) break;
    if (x.ringkas) reaksi.push(x);
  }
  if (reaksi.length) {
    const ul = node('ul', undefined, 'decision-list');
    for (const x of reaksi) {
      const bot = x.ringkas.bot || {},
        keputusan = x.ringkas.keputusan?.length
          ? x.ringkas.keputusan.map(teksKeputusan).join(' · ')
          : 'diam';
      const b = node(
        'button',
        `${bot.nama} (${METODE_SINGKAT[bot.metode] || bot.metode || '?'}): ${keputusan} · ${duration(x.duration_ms)}`,
        'room-bot',
      );
      b.type = 'button';
      b.onclick = () => onSelect(x.id);
      const li = node('li');
      li.append(b);
      ul.append(li);
    }
    container.append(
      node('h4', 'Reaksi bot sesudah pesan ini (klik untuk melihat prosesnya)', 'report-title'),
      ul,
    );
  }
  const teknis = node('details'),
    box = node('div', undefined, 'report');
  renderReport(box, trace);
  teknis.append(node('summary', 'Teknis: seluruh jejak'), box);
  container.append(teknis);
}
// Kartu keputusan: alur proses di atas, lalu tab Rincian proses · Keputusan · Bahan bukti · Penalaran · Kalimat (NLG)
// · Teknis. Tab tanpa isi disembunyikan. lama: penjelasan langkah sebelumnya bot yang sama (kolom perubahan).
function renderDecision(container, trace, lama = null) {
  const p = trace.penjelasan;
  container.replaceChildren();
  container.classList.remove('empty-state');
  if (!p) {
    renderReport(container, trace);
    return;
  }
  const bot = p.bot || {};
  const head = node('div', undefined, 'decision-head');
  head.append(node('strong', bot.nama || trace.sender));
  if (bot.role) head.append(chip(ROLE_LABEL[bot.role] || bot.role, roleClass(bot.role)));
  if (bot.metode) head.append(chip(METODE_LABEL[bot.metode] || bot.metode, 'status-good'));
  if (trace.stage === 'npc_brain_rejected') head.append(chip('ditolak engine', 'status-bad'));
  const meta = [
    bot.persona && `persona ${bot.persona}`,
    bot.ronde && `ronde ${bot.ronde}`,
    FASE_LABEL[bot.fase] || bot.fase,
    bot.langkah && `langkah ${bot.langkah}`,
    waktu(trace.created_at),
  ].filter(Boolean);
  head.append(node('span', meta.join(' · '), 'room-meta'));
  container.append(head, alurProses(alurBot(trace), KET_BOT));
  if (p.catatan?.length) container.append(node('p', p.catatan.join(' '), 'hint status-pending'));
  const ada = {
    parameter: p.tersangka || p.khusus_peran || p.konteks || p.pengetahuan,
    penalaran: Object.keys(p.penalaran || {}).length,
    nlg: p.nlg,
  };
  const tabs = [
    ['proses', 'Rincian proses', () => prosesTab(trace, p, lama)],
    ['keputusan', 'Keputusan', () => decisionTab(p)],
    ['parameter', 'Bahan bukti', () => parameterTab(p)],
    ['penalaran', `Penalaran ${METODE_LABEL[bot.metode] || ''}`.trim(), () => reasoningTab(p)],
    ['nlg', 'Kalimat (NLG)', () => nlgTab(p)],
    [
      'teknis',
      'Teknis',
      () => {
        const box = node('div', undefined, 'report');
        renderReport(box, trace);
        return box;
      },
    ],
  ].filter(([id]) => !(id in ada) || ada[id]);
  const bar = node('div', undefined, 'decision-tabs');
  bar.setAttribute('role', 'tablist');
  const panel = node('div', undefined, 'decision-panel');
  panel.setAttribute('role', 'tabpanel');
  const show = (id) => {
    detailTab = id;
    for (const b of bar.children) b.setAttribute('aria-selected', String(b.dataset.tab === id));
    panel.replaceChildren((tabs.find((tab) => tab[0] === id) || tabs[0])[2]());
  };
  for (const [id, label] of tabs) {
    const b = node('button', label, 'decision-tab');
    b.type = 'button';
    b.dataset.tab = id;
    b.setAttribute('role', 'tab');
    b.onclick = () => show(id);
    bar.append(b);
  }
  container.append(bar, panel);
  show(tabs.some((tab) => tab[0] === detailTab) ? detailTab : 'proses');
}
const DIAM = ['tunggu', 'abstain', 'tidak_bisa']; // keputusan tanpa aksi
function planText(r, chat = false) {
  if (!r?.aksi) return '—';
  if (chat && !r.kirim) return `diam — ${r.alasan?.[0] || ''}`;
  if (DIAM.includes(r.aksi)) return `${r.aksi.replace('_', ' ')} — ${r.alasan?.[0] || ''}`;
  const klaim = r.role_diakui ? `, mengaku ${r.role_diakui}` : '';
  const intent = chat && r.intent ? ` (${r.intent}${klaim})` : '';
  const skor = typeof r.skor === 'number' ? ` · skor ${teks(r.skor)}` : '';
  const jenis = chat && r.jenis ? ` · ${r.jenis.replaceAll('_', ' ')}` : '';
  const tanda = r.pindah ? ' · pindah suara' : r.paksa ? ' · vote paksa' : '';
  return `${r.aksi}${jenis}${r.target ? ` → ${r.target}` : ''}${intent}${tanda}${skor}`;
}
function engineText(e) {
  if (!e) return '—';
  const aksi =
    e.action === 'wait' ? 'tidak ada vote/aksi' : `${e.action}${e.target ? ` → ${e.target}` : ''}`;
  return e.ditolak ? `${aksi} (ditolak engine: ${e.ditolak})` : aksi;
}
// Kecurigaan per pemain dari tabel tersangka penjelasan ({pemain: nilai}).
function petaKecurigaan(tabel) {
  const kolom = tabel?.kolom || [],
    iP = kolom.indexOf('pemain'),
    iK = kolom.indexOf('kecurigaan');
  if (iP < 0 || iK < 0) return null;
  return Object.fromEntries((tabel.baris || []).map((b) => [b[iP], b[iK]]));
}
// Data sementara langkah ini dan perubahannya dari langkah sebelumnya bot yang sama.
function dataSementara(p, lama) {
  const kini = petaKecurigaan(p.tersangka);
  if (!kini) return null;
  const dulu = petaKecurigaan(lama?.tersangka) || {};
  const box = node('div');
  box.append(
    node(
      'h4',
      `Data sementara: ${p.tersangka.judul || 'tersangka'} (kecurigaan 0–1)`,
      'report-title',
    ),
    dataTable({
      kolom: ['pemain', 'kecurigaan', 'langkah sebelumnya', 'perubahan'],
      baris: Object.entries(kini).map(([pemain, nilai]) => {
        const awal = dulu[pemain];
        const beda = typeof nilai === 'number' && typeof awal === 'number' ? nilai - awal : null;
        return [
          pemain,
          nilai,
          awal ?? '—',
          beda === null ? '—' : `${beda > 0 ? '+' : ''}${teks(Number(beda.toFixed(3)))}`,
        ];
      }),
    }),
  );
  if (!lama)
    box.append(
      node('p', 'Perubahan tampil bila langkah sebelumnya bot ini sudah dibuka/tercatat.', 'hint'),
    );
  return box;
}
// Tab Proses: urutan kerja satu langkah bot dengan lama tiap tahap, hasil antara, dan perubahannya.
function prosesTab(trace, p, lama) {
  const box = node('div');
  const t = trace.timings || {},
    k = p.keputusan || {},
    bot = p.bot || {},
    nlg = p.nlg || {};
  const dibaca = (p.nlu_dibaca || []).map(
    (c) =>
      `${c.pengirim}: “${c.teks}” → intent ${c.intent} (${teks(c.confidence)})` +
      (c.target?.length ? ` · target ${c.target.join(', ')}` : ''),
  );
  const penalaran = Object.values(p.penalaran || {})
    .filter((blok) => blok?.hasil)
    .map((blok) => `${blok.judul}: ${blok.hasil}`);
  const kalimat =
    nlg.status === 'terkirim'
      ? keyValues([
          ['Kalimat', nlg.teks],
          ['Sumber', SUMBER_NLG[nlg.sumber] || nlg.sumber],
          ['Penulis LLM', nlg.penulis || 'tidak ada (templat)'],
          ['Lama panggilan LLM', duration(t.llm_ms)],
          ['Aturan + templat', duration(waktuAturan(t))],
          ['Status percobaan LLM', nlg.percobaan_llm],
        ])
      : nlgBelum(nlg);
  box.append(
    node(
      'p',
      `Total ${duration(trace.duration_ms)} dari membaca keadaan permainan sampai keputusan diterapkan dan kalimat terkirim.`,
      'hint',
    ),
    processSteps([
      [
        '1. NLU IndoBERT: membaca chat baru',
        t.nlu_ms ?? null,
        dibaca.length ? listOf(dibaca) : 'Tidak ada chat baru sejak langkah sebelumnya.',
        'Mendekati 0 ms berarti hasilnya diambil dari memo (chat sudah dibaca sebelumnya).',
      ],
      [
        `2. Logika ${METODE_LABEL[bot.metode] || bot.metode || ''}: menimbang bukti`,
        t.logika_ms ?? null,
        penalaran.length ? listOf(penalaran) : 'Tidak ada ringkasan penalaran.',
        'Rincian hitungan (bila tercatat) ada di tab Bahan bukti dan Penalaran.',
      ],
      [
        '3. Keputusan',
        null,
        keyValues([
          ['Chat', planText(k.chat, true)],
          ['Vote', planText(k.vote)],
          ['Aksi rahasia', planText(k.aksi)],
        ]),
      ],
      ['4. NLG: rencana chat menjadi kalimat', t.nlg_ms ?? null, kalimat],
      ['5. Diterapkan ke engine', null, engineText(p.engine)],
      [
        'Penjelasan untuk panel disusun',
        t.penjelasan_ms ?? null,
        'Hanya untuk panel admin; tidak memengaruhi keputusan.',
      ],
    ]),
  );
  const data = dataSementara(p, lama);
  if (data) box.append(data);
  return box;
}
function decisionTab(p) {
  const box = node('div');
  const k = p.keputusan || {};
  box.append(
    keyValues([
      ['Chat', planText(k.chat, true)],
      ['Vote', planText(k.vote)],
      ['Aksi rahasia', planText(k.aksi)],
      ['Diterapkan ke engine', engineText(p.engine)],
      ['Kalimat', p.nlg?.status === 'terkirim' ? p.nlg.teks : p.nlg?.status],
    ]),
  );
  const ringkasan = Object.values(p.penalaran || {})
    .filter((blok) => blok?.hasil)
    .map((blok) => `${blok.judul}: ${blok.hasil}`);
  if (ringkasan.length)
    box.append(node('h4', 'Ringkasan penalaran', 'report-title'), listOf(ringkasan));
  for (const [label, r] of [
    ['Alasan chat', k.chat],
    ['Alasan vote', k.vote],
    ['Alasan aksi rahasia', k.aksi],
  ])
    // Alasan tunggu/abstain/tidak bisa sudah tertulis di baris keputusan.
    if (r?.alasan?.length && r.kirim !== false && !DIAM.includes(r.aksi))
      box.append(node('h4', label, 'report-title'), listOf(r.alasan));
  return box;
}
function parameterTab(p) {
  const box = node('div');
  if (p.tersangka) {
    box.append(
      node('h4', p.tersangka.judul || 'Tersangka', 'report-title'),
      dataTable(p.tersangka),
    );
    // Siapa menuduh/membela tersangka teratas; pemain tanpa interaksi tidak ditampilkan.
    const rincian = (p.tersangka.rincian || [])
      .filter((r) => r.penuduh?.length || r.pembela?.length || r.diserang?.length)
      .map(
        (r) =>
          `${r.pemain}: dituduh ${teks(r.penuduh)} · dibela ${teks(r.pembela)}` +
          (r.diserang?.length ? ` · menyerang ${teks(r.diserang)}` : ''),
      );
    if (rincian.length) box.append(listOf(rincian));
  }
  if (p.khusus_peran)
    box.append(node('h4', p.khusus_peran.judul, 'report-title'), dataTable(p.khusus_peran));
  if (p.konteks)
    box.append(
      node('h4', 'Konteks permainan', 'report-title'),
      keyValues(Object.entries(p.konteks)),
    );
  if (p.pengetahuan)
    box.append(
      node('h4', 'Pengetahuan pasti milik bot', 'report-title'),
      keyValues(Object.entries(p.pengetahuan)),
    );
  return box;
}
// Satu sistem fuzzy: derajat keanggotaan input, aturan yang menyala, dan keluaran centroid.
function fuzzySystem(s) {
  const box = node('div', undefined, 'fuzzy-system');
  box.append(node('strong', `Sistem "${s.nama}"`));
  if (s.arti) box.append(node('p', s.arti, 'hint'));
  for (const masukan of s.input || []) {
    const row = node('div', undefined, 'fuzzy-input');
    row.append(node('span', `${masukan.nama} = ${teks(masukan.nilai)}`, 'fuzzy-name'));
    for (const [tingkat, derajat] of Object.entries(masukan.derajat || {})) {
      const meter = document.createElement('meter');
      meter.setAttribute('min', '0');
      meter.setAttribute('max', '1');
      meter.setAttribute('value', String(derajat ?? 0));
      const degree = node('span', undefined, 'fuzzy-degree');
      degree.append(node('span', `${tingkat} ${teks(derajat)}`), meter);
      row.append(degree);
    }
    box.append(row);
  }
  if (s.aturan?.length)
    box.append(dataTable({ kolom: ['jika', 'maka', 'kekuatan'], baris: s.aturan }));
  box.append(
    node('p', `Keluaran defuzzifikasi (centroid, 0–100): ${teks(s.keluaran)}`, 'decision-result'),
  );
  if (s.catatan) box.append(node('p', s.catatan, 'hint'));
  return box;
}
// Jalur Behavior Tree pada jejak lama: syarat/aksi yang dievaluasi berurutan dengan status berhasil/gagal.
function btPath(blok) {
  const box = node('div', undefined, 'bt-path');
  box.append(
    node(
      'small',
      `Jalur evaluasi · status akar ${blok.status_akar || '—'}${blok.cabang ? ` · aksi terpilih: ${blok.cabang}` : ''}`,
    ),
  );
  const ol = node('ol');
  for (const [nama, jenis, status] of blok.jalur.baris || []) {
    const li = node('li', undefined, `bt-${String(status).toLowerCase()}`);
    const ikon = status === 'SUKSES' ? '✓' : status === 'GAGAL' ? '✗' : '…';
    li.append(
      node('span', ikon, 'bt-icon'),
      node('span', `${jenis === 'aksi' ? 'Aksi' : 'Syarat'}: ${nama}`),
    );
    ol.append(li);
  }
  box.append(ol);
  return box;
}
function reasoningTab(p) {
  const box = node('div');
  box.append(node('p', METODE_CARA[p.bot?.metode] || '', 'hint'));
  for (const key of ['kecurigaan', 'chat', 'vote', 'aksi']) {
    const blok = p.penalaran?.[key];
    if (!blok) continue;
    const section = node('section', undefined, 'decision-block');
    section.append(
      node('h4', blok.judul, 'report-title'),
      node('p', blok.hasil, 'decision-result'),
    );
    for (const [data, keterangan] of [
      [blok.hierarki, 'Hierarki sistem fuzzy (nilai 0–1)'],
      [blok.komponen, 'Komponen noisy-OR'],
      [blok.bendera, 'Bendera merah'],
      [blok.kandidat, 'Kandidat yang dinilai (terbaik di atas)'],
    ])
      if (data) section.append(node('small', keterangan), dataTable(data));
    for (const sistem of blok.sistem || []) section.append(fuzzySystem(sistem));
    if (blok.jalur) section.append(btPath(blok));
    if (blok.ambang?.length)
      section.append(
        node('small', 'Ambang'),
        dataTable({ kolom: ['konstanta', 'nilai', 'arti'], baris: blok.ambang }),
      );
    if (blok.catatan) section.append(node('p', blok.catatan, 'hint'));
    box.append(section);
  }
  return box;
}
// NLG yang tidak menghasilkan kalimat (ditunda, tidak terkirim, tidak ada chat): status, alasan, dan
// rencana yang sudah/akan diserahkan ke penulis.
function nlgBelum(n) {
  const m = n.masukan;
  return keyValues([
    ['Status', n.status || 'Tidak ada data NLG'],
    ['Keterangan', n.keterangan],
    ...(m
      ? [
          ['Rencana ke NLG', `${m.aksi}${m.target ? ` → ${m.target}` : ''} (${m.intent})`],
          ['Kalimat templat', m.cadangan],
        ]
      : []),
  ]);
}
// Masukan NLG: rencana yang diserahkan otak ke penulis kalimat dan prompt LLM-nya (juga saat ditunda).
function masukanNlg(m) {
  const box = node('div');
  if (!m) return box;
  box.append(
    node('h4', 'Masukan ke NLG', 'report-title'),
    keyValues(
      [
        ['Aksi chat', `${m.aksi}${m.target ? ` → ${m.target}` : ''}`],
        ['Jenis', m.jenis],
        ['Intent', m.intent],
        ['Mengaku role', m.role_diakui],
        ['Bukti klaim', m.bukti_klaim],
        ['Alasan yang boleh dipakai', m.bukti],
        ['Menjawab', m.penanya],
        ['Kalimat templat (cadangan)', m.cadangan],
      ].filter(([, v]) => v !== undefined && v !== null),
    ),
    node('h4', 'Prompt ke LLM penulis', 'report-title'),
    m.prompt
      ? node('pre', m.prompt, 'output')
      : node('p', 'Penulis LLM tidak aktif: kalimat ditulis dari templat.', 'hint'),
  );
  return box;
}
function nlgTab(p) {
  const n = p.nlg,
    box = node('div');
  if (!n) {
    box.append(node('p', 'Jejak ini tidak memuat data NLG.', 'hint'));
    return box;
  }
  if (n.status !== 'terkirim') {
    box.append(nlgBelum(n), masukanNlg(n.masukan));
    return box;
  }
  box.append(
    node('pre', n.teks || '', 'output'),
    keyValues([
      ['Sumber kalimat', SUMBER_NLG[n.sumber] || n.sumber],
      ['Penulis LLM', n.penulis || 'tidak ada (templat)'],
      ['Persona', n.persona],
      ['Lolos aturan', n.lolos_aturan],
      // Jejak sebelum 4 Nov 2026 masih memuat hasil pembacaan ulang IndoBERT; jejak baru tidak.
      ...('lolos_nlu' in n
        ? [
            ['Lolos validasi IndoBERT', n.lolos_nlu ?? 'tidak divalidasi'],
            [
              'Intent terbaca',
              n.nlu ? `${n.nlu.intent_prediksi} (${teks(n.nlu.confidence)})` : null,
            ],
            [
              'Target terbaca',
              n.nlu?.target_prediksi?.map(([nama, relasi]) => `${nama}: ${relasi}`),
            ],
          ]
        : []),
      ['Pelanggaran aturan', n.pelanggaran],
      ['Percobaan LLM', n.percobaan_llm],
      ['Varian templat dicoba', n.percobaan_templat],
      ['Waktu tulis (dtk)', n.detik],
    ]),
    masukanNlg(n.masukan),
  );
  return box;
}
// ANTREAN THREAD (kotak paling bawah): pekerjaan yang menunggu atau sedang dikerjakan di thread otak dan thread penulis
// semua room, dari registri EksekutorTercatat di server.
const ANTREAN_JUDUL = {
  otak: ['Thread otak', 'langkah berpikir bot dan IndoBERT membaca chat'],
  penulis: ['Thread penulis', 'menulis kalimat bot (LLM atau templat)'],
};
// Satu kotak pekerjaan: urutan, status, room (bila beda room), siapa mengerjakan apa, dan lamanya (berdetak).
function kotakAntrean(t, room) {
  const dikerjakan = t.status === 'dikerjakan';
  const li = node('li', undefined, `antrean-tugas keadaan-${dikerjakan ? 'sedang' : 'menunggu'}`);
  const head = node('div', undefined, 'antrean-head');
  head.append(
    node('span', `#${t.urutan}`, 'antrean-urutan'),
    node('span', `${TANDA[dikerjakan ? 'sedang' : 'menunggu']} ${t.status}`, 'antrean-status'),
  );
  if (t.room && t.room !== room) head.append(chip(`room ${t.room}`, 'status-muted'));
  const siapa = t.siapa || 'tanpa nama';
  li.append(
    head,
    node(
      'p',
      t.teks ? `${t.kerja} “${t.teks}” dari ${siapa}` : `${siapa} ${t.kerja}`,
      'antrean-kerja',
    ),
    dikerjakan
      ? waktuBerdetak(
          `antre|${t.nomor}|berjalan`,
          'dikerjakan ',
          ` · sesudah antre ${duration(t.menunggu_ms)}`,
          'antrean-waktu',
        )
      : waktuBerdetak(`antre|${t.nomor}|menunggu`, 'sudah menunggu ', '', 'antrean-waktu'),
  );
  return li;
}
// Render ulang hanya bila isi antrean berubah (masuk, mulai, keluar); lamanya berdetak sendiri.
function renderAntrean() {
  const box = $('checker-antrean');
  if (!liveAntrean) {
    if (box.dataset.kunci !== '') {
      box.dataset.kunci = '';
      box.textContent = 'Belum ada data antrean.';
    }
    return;
  }
  const room = $('checker-room').value;
  const kunci = JSON.stringify(
    Object.entries(liveAntrean).map(([nama, a]) => [
      nama,
      a.thread,
      (a.tugas || []).map((t) => [t.nomor, t.urutan, t.status, t.room === room]),
    ]),
  );
  if (box.dataset.kunci === kunci) return;
  box.dataset.kunci = kunci;
  box.replaceChildren(
    ...Object.entries(liveAntrean).map(([nama, a]) => {
      const [judul, isi] = ANTREAN_JUDUL[nama] || [nama, ''];
      const tugas = a.tugas || [];
      const menunggu = tugas.filter((t) => t.status !== 'dikerjakan').length;
      // Satu baris memanjang per thread: keterangan di kiri, kotak pekerjaan berderet sesuai urutan di kanan.
      const baris = node('section', undefined, 'antrean-baris'),
        info = node('div', undefined, 'antrean-info');
      info.append(
        node('h4', `${judul} · ${a.thread} thread`, 'antrean-judul'),
        node(
          'p',
          `${isi}. ${tugas.length - menunggu} dikerjakan, ${menunggu} menunggu.`,
          'hint antrean-ringkas',
        ),
      );
      baris.append(info);
      if (!tugas.length) baris.append(node('p', 'Tidak ada antrean.', 'antrean-kosong'));
      else {
        const daftar = node('ol', undefined, 'antrean-daftar');
        for (const t of tugas) daftar.append(kotakAntrean(t, room));
        baris.append(daftar);
      }
      return baris;
    }),
  );
}
// Buang data live (ganti room atau logout).
function kosongkanLive() {
  liveBot = [];
  liveChat = new Map();
  liveKondisi = new Map();
  liveAntrean = null;
  livePilihan = null;
  perluSegar = false;
  liveBox.replaceChildren();
  renderAntrean();
}
// Tanda tangan item live yang tampil: id berubah → daftar chat dirender ulang; tahap berubah → item live saja.
function kunciLive() {
  const live = liveTerlihat();
  return {
    ids: live.map((l) => l.id).join(','),
    tahap: live.map((l) => `${l.live.tahap}${l.selesai ? '!' : ''}`).join(','),
  };
}
// Terima hasil polling live dan render seperlunya supaya tidak berkedip: item live baru/hilang → daftar chat dirender
// ulang (detail tetap), tahap berubah → item live dan alur terpilih saja, kondisi bot dan antrean → yang berubah saja.
// Langkah yang selesai dengan jejak (bukan diam atau basi menurut hasil langkah terakhirnya), chat yang selesai, atau
// item terpilih yang selesai memicu muat ulang daftar jejak supaya jejak akhirnya langsung tampil.
// Alur: 1 simpan data -> 2 item live terpilih yang selesai ditandai -> 3 perlu muat ulang? -> 4 render bagian yang
//       berubah -> 5 muat ulang daftar jejak
function terimaLive(data) {
  const kunciLama = kunciLive(),
    botLama = liveBot,
    chatLama = [...liveChat.keys()],
    pilihanAda = Boolean(livePilihan && !livePilihan.hilang);
  liveBot = data.bot || [];
  liveChat = new Map((data.chat || []).map((c) => [c.id, c]));
  liveKondisi = new Map((data.kondisi || []).map((k) => [k.nama, k]));
  liveAntrean = data.antrean || null;
  liveDiterima = performance.now();
  if (livePilihan && !livePilihan.hilang) {
    const kini = liveBot.find((b) => b.id === livePilihan.b.id);
    if (kini) livePilihan.b = kini;
    else Object.assign(livePilihan, { hilang: true, segar: segarKe });
  }
  const berjejak = (b) => {
    const t = liveKondisi.get(b.nama)?.terakhir;
    return !(t && t.langkah === b.langkah && ['diam', 'basi'].includes(t.hasil));
  };
  if (
    botLama.some((b) => !liveBot.some((x) => x.id === b.id) && berjejak(b)) ||
    (pilihanAda && livePilihan.hilang) ||
    chatLama.some((id) => !liveChat.has(id)) ||
    [...liveChat.keys()].some((id) => !traces.some((t) => t.id === id))
  )
    perluSegar = true;
  const kunciBaru = kunciLive();
  if (kunciBaru.ids !== kunciLama.ids) renderTraces();
  else {
    if (kunciBaru.tahap !== kunciLama.tahap) isiLiveBox();
    perbaruiAlurTerpilih();
  }
  perbaruiKondisi();
  renderAntrean();
  if (perluSegar && !busy) checker().catch((error) => notice(error.message));
}
// Polling live tiap detik untuk room terpilih (tanpa database selain cek sesi).
async function muatLive() {
  const code = $('checker-room').value;
  if (!code || liveBusy) return;
  liveBusy = true;
  const epoch = generation;
  try {
    const data = await request(`/api/panel/checker/${encodeURIComponent(code)}/proses`);
    if (epoch === generation && token && code === $('checker-room').value) terimaLive(data);
  } catch {
    // Data live hanya tampilan; satu polling yang gagal tidak menghentikan Checker.
  } finally {
    liveBusy = false;
  }
}
// Muat jejak terbaru/lama; tolak respons basi setelah logout atau pergantian ruangan. Sesudah halaman pertama dimuat,
// data live langsung diambil supaya langkah yang sedang berjalan tidak menunggu polling berikutnya.
async function checker(older = false) {
  if (busy) return;
  const code = $('checker-room').value;
  if (!code) {
    traces = [];
    checkerRoom = null;
    kosongkanLive();
    renderRoomSummary();
    renderTraces();
    $('events').textContent = 'Pilih room.';
    $('older-traces').hidden = true;
    return;
  }
  busy = true;
  const epoch = generation;
  try {
    const data = await request(
      `/api/panel/checker/${encodeURIComponent(code)}${older && traceBefore ? `?before=${encodeURIComponent(traceBefore)}` : ''}`,
    );
    if (epoch !== generation || !token || code !== $('checker-room').value) return;
    traces = older
      ? [...traces, ...data.traces.filter((t) => !traces.some((old) => old.id === t.id))]
      : data.traces;
    traceBefore = data.next_before;
    $('older-traces').hidden = !data.has_more;
    if (!older) {
      $('events').textContent = JSON.stringify(data.events, null, 2);
      checkerRoom = data.room || null;
      segarKe++;
      perluSegar = false;
    }
    renderRoomSummary();
    renderTraces();
    if (!older) await muatLive();
  } finally {
    busy = false;
  }
}
// Pergantian room atau sesi: buang filter, cache penjelasan, data live, dan tampilan detail lama.
function resetChecker() {
  checkerRoom = null;
  traceFilter = '';
  selectedTrace = '';
  renderedDetail = '';
  traceDetails.clear();
  kosongkanLive();
  $('room-summary').replaceChildren();
  $('room-summary').hidden = true;
}
// FLOWCHART PROSES AI (menu Simulasi): seluruh jalur AI dari chat pemain sampai output bot.
// tahap = nama tahap yang dilaporkan server saat simulasi berjalan, untuk menandai posisi tiap bot.
// metode = kotak cabang metode (dipakai bot dengan metode itu). Teks dibuat singkat dan mudah dipahami.
const ALUR_AI = {
  input: {
    judul: 'Chat pemain masuk',
    kode: 'Simulasi.kirim · chat.send_chat · Match.can_chat',
    tujuan: 'Menerima kalimat pemain pada fase yang boleh chat.',
    proses:
      'Server memeriksa izin chat (siang/Tribunal, tidak dibungkam), lalu pesan masuk ke chat pertandingan.',
    keluaran: 'Pesan {pengirim, teks} di daftar chat room.',
    alasan: 'Bot membaca chat dari daftar yang sama dengan yang dilihat pemain.',
  },
  nlu_pesan: {
    tahap: ['nlu_pesan'],
    judul: 'NLU IndoBERT membaca chat',
    kode: 'nlu.baca_chat → anotasi_chat',
    tujuan: 'Memahami chat: maksudnya apa dan ditujukan ke siapa.',
    proses:
      'Chat dibaca dua model IndoBERT berurutan (intent lalu target) dengan konteks chat sebelumnya.',
    keluaran: 'intent + keyakinan, dan daftar target beserta relasinya.',
    alasan: 'Logika bot bekerja dengan angka, bukan kalimat; NLU menerjemahkan chat menjadi data.',
  },
  nlu_intent: {
    judul: 'Model 1: intent',
    kode: 'NLUIndoBERT.intent · varian_nama_intent',
    tujuan: 'Menebak maksud kalimat.',
    proses:
      'Nama pemain diganti nama yang dikenal model (3 varian), IndoBERT menghitung probabilitas tiap kelas, lalu dirata-rata.',
    keluaran: 'offend (menyerang) / defend (membela) / neutral + keyakinan 0–1.',
    alasan:
      'Model dilatih dengan nama tertentu; mengganti nama membuat hasil stabil untuk nama apa pun.',
  },
  nlu_target: {
    judul: 'Model 2: target',
    kode: 'NLUIndoBERT.target · buat_teks_pasangan',
    tujuan: 'Menebak siapa yang dituju kalimat.',
    proses:
      'Untuk tiap pemain dibuat pasangan (kalimat + 12 chat terakhir + kandidat); IndoBERT memberi relasi offend/defend/tidak_ada. Bila semua tidak_ada, ambang memilih minimal satu target.',
    keluaran: 'Daftar {pemain, relasi, probabilitas}.',
    alasan:
      '"Aku curiga dia" baru bermakna bila tahu "dia" siapa; konteks chat sebelumnya membantu.',
  },
  nlu_memo: {
    judul: 'Memo NLU bersama',
    kode: 'NLUBersama._ingat',
    tujuan: 'Satu chat dibaca sekali untuk semua bot.',
    proses:
      'Hasil disimpan dengan kunci teks + daftar pemain + konteks; bot lain mengambil hasil yang sama.',
    keluaran: 'Bacaan sama untuk semua bot (mendekati 0 ms bila sudah ada).',
    alasan:
      'IndoBERT di CPU butuh sekitar 0,5–1,5 detik per chat; tanpa memo setiap bot mengulang hitungan.',
  },
  sinkron: {
    tahap: ['nlu'],
    judul: 'Ingatan bot diperbarui',
    kode: 'Ingatan.sinkron_snapshot → nlu.baca_chat_baru',
    tujuan: 'Menyamakan memori bot dengan keadaan permainan yang ia lihat.',
    proses:
      'Snapshot privat bot dibaca: chat baru, vote, eksekusi, pemain keluar, korban Hostage yang diumumkan, hasil Peek, Gag, pilihan malam rekan, fase, dan waktu. Chat tim hanya masuk view, tidak pernah menjadi bukti. Sesudah itu NLU membaca chat yang baru masuk ingatan, berurutan.',
    keluaran: 'view: ronde, fase, pemain hidup, izin chat/vote/aksi milik bot.',
    alasan: 'Bot hanya tahu yang boleh dilihat role-nya; role lawan tidak pernah bocor.',
  },
  bukti: {
    judul: 'Menghitung bukti tiap pemain',
    kode: 'hitung_bukti · pengetahuan_peran · fitur_hitman / fitur_lindung',
    tujuan: 'Mengubah riwayat permainan menjadi angka 0–1 per pemain.',
    proses:
      'Dari chat ber-NLU dan vote dihitung tekanan, dukungan, plin plan, alihkan tuduhan, klaim role bermasalah, diam, dll. Hitman juga menilai ancaman; Spy menilai siapa yang perlu di-Guard.',
    keluaran: 'Tabel bukti (lihat tab Bahan bukti).',
    alasan:
      'Penalaran menerima angka, bukan teks chat, jadi nilainya bisa diperiksa di tab Bahan bukti.',
  },
  fl: {
    metode: 'fuzzy',
    judul: 'FL · Fuzzy Mamdani',
    kode: 'fuzzy_controller.putuskan',
    tujuan: 'Menalar dengan aturan bahasa manusia (rendah/sedang/tinggi).',
    proses:
      'Bukti → sistem fuzzy bertingkat → kecurigaan. Chat yang dinilai, vote, Gag, dan Peek diberi prioritas 0–100. Bela diri dan jawab dikirim tanpa nilai; Hostage dan Guard memakai nilai 0–1 tanpa fuzzy.',
    keluaran: 'Kecurigaan per pemain dan nilai tiap pilihan.',
    alasan: 'Bukti sosial tidak pasti; fuzzy menangani "agak curiga" dengan halus.',
  },
  fl_1: {
    metode: 'fuzzy',
    judul: 'Fuzzifikasi',
    kode: 'keanggotaan(x)',
    tujuan: 'Angka 0–1 menjadi derajat rendah/sedang/tinggi.',
    proses: 'Fungsi keanggotaan memberi derajat tiap himpunan.',
    keluaran: 'Mis. tekanan 0,62 → sedang 0,4 dan tinggi 0,6.',
    alasan: 'Aturan ditulis dengan kata, bukan ambang tajam.',
  },
  fl_2: {
    metode: 'fuzzy',
    judul: 'Aturan JIKA–MAKA',
    kode: 'aturan_aktif(nama, a, b)',
    tujuan: 'Menyalakan aturan yang cocok.',
    proses:
      'Kekuatan aturan = min(derajat input). Contoh: JIKA tekanan tinggi DAN dukungan rendah MAKA curiga tinggi.',
    keluaran: 'Daftar aturan yang menyala dan kekuatannya.',
    alasan: 'Logikanya mudah dibaca dan dijelaskan.',
  },
  fl_3: {
    metode: 'fuzzy',
    judul: 'Agregasi + defuzzifikasi',
    kode: 'fuzzy/mesin.hitung · fuzzy/kecurigaan.py · nilai_kecurigaan (pohon)',
    tujuan: 'Menggabungkan aturan menjadi satu angka.',
    proses:
      'Keluaran aturan digabung (max), lalu centroid → 0–100. Bertingkat: sentimen_sosial, perilaku_mencurigakan, jejak, kejanggalan, ucapan, bukti_keras → kecurigaan.',
    keluaran: 'Kecurigaan 0–1 dan prioritas 0–100.',
    alasan: 'Centroid membuat nilai berubah halus saat bukti berubah.',
  },
  fl_4: {
    metode: 'fuzzy',
    judul: 'Bandingkan ambang',
    kode: 'keputusan_chat · keputusan_vote · keputusan_aksi',
    tujuan: 'Memutuskan bertindak atau menunggu.',
    proses:
      'Prioritas terbaik dibandingkan AMBANG_CHAT dan VOTE_LANGSUNG/AMBANG_VOTE. Bela diri dan jawab tidak melewati ambang, dan gali tersangka menjadi cadangan saat semua chat di bawah ambang. Saat waktu tambahan seri, suara yang sudah ada dinilai ulang sekali (keputusan_pindah_vote). Gag selalu terpakai: ancaman tinggi langsung, nilai ≥ AMBANG_GAG sebelum 60% siang, dan wajib sesudahnya. Hostage, Guard, dan Peek selalu memakai target terbaik.',
    keluaran: 'Rencana chat, vote, dan aksi rahasia.',
    alasan: 'Bot tidak menuduh tanpa bukti yang cukup.',
  },
  keputusan: {
    judul: 'Keputusan langkah ini',
    kode: 'rencana_chat · pertahanan_suara · format_npc · siapkan_nlg · siapkan_nlg_tim',
    tujuan: 'Menyatukan hasil metode menjadi satu keputusan.',
    proses:
      'Rencana chat (aksi, jenis, intent, target), vote, dan aksi rahasia digabung. Saat warga kritis, abstain diganti vote ke tersangka teratas yang layak. Malam hari, bot dengan rekan manusia juga menyiapkan paket chat tim.',
    keluaran:
      'npc_decision {action, target}, rencana kalimat untuk NLG, dan paket chat tim bila ada.',
    alasan:
      'Format keputusan terpisah dari penalaran, jadi engine dan NLG tidak perlu tahu metodenya.',
  },
  penjelasan: {
    tahap: ['penjelasan'],
    judul: 'Penjelasan untuk panel',
    kode: 'penjelasan.jelaskan',
    tujuan: 'Mencatat alasan keputusan untuk admin.',
    proses: 'Parameter, penalaran, dan keputusan diringkas (maks 12 KB).',
    keluaran: 'Isi tab Bahan bukti, Penalaran, dan Keputusan.',
    alasan: 'Keputusan bot bisa diperiksa; tidak memengaruhi keputusan.',
  },
  engine: {
    tahap: ['engine'],
    judul: 'Vote/aksi ke engine',
    kode: 'Match.vote · Match.act',
    tujuan: 'Menjalankan vote atau aksi rahasia sesuai aturan game.',
    proses:
      'Engine memeriksa legalitas (fase, cooldown, rekan Syndicate); yang tidak sah ditolak dan dicatat.',
    keluaran: 'Vote/aksi tercatat, atau alasan penolakan.',
    alasan: 'Bot tunduk pada aturan yang sama dengan pemain.',
  },
  nlg_prompt: {
    tahap: ['nlg'],
    judul: 'NLG: susun prompt',
    kode: 'nlg.buat_prompt',
    tujuan: 'Rencana chat menjadi instruksi untuk LLM.',
    proses:
      'Prompt berisi maksud, target, persona, chat terbaru, dan larangan (tidak membocorkan role, dll.).',
    keluaran: 'Pesan sistem dan pesan untuk LLM.',
    alasan: 'LLM hanya menulis kalimat; isi keputusan tetap dari metode.',
  },
  nlg_llm: {
    tahap: ['llm'],
    judul: 'LLM menulis kalimat',
    kode: 'PenulisBerantai.tulis (OpenRouter → link Ollama)',
    tujuan: 'Kalimat bahasa Indonesia yang natural.',
    proses:
      'Jalur dicoba sesuai prioritas di panel; jalur gagal/lambat diistirahatkan. Batas 20 detik per kalimat.',
    keluaran: 'Kalimat mentah dari model.',
    alasan: 'Lebih variatif dan manusiawi daripada templat.',
  },
  nlg_cek: {
    tahap: ['aturan'],
    judul: 'Cek aturan',
    kode: 'bersihkan · periksa_aturan · nilai_kalimat',
    tujuan: 'Menjaga kalimat tetap aman sebelum dikirim.',
    proses:
      'Kalimat dibersihkan dan dicek (target disebut, tidak membocorkan role, tidak mengaku AI). Gagal atau terlalu mirip → ulang LLM (maks 2 kali) atau templat.',
    keluaran: 'Kalimat yang lolos, atau alasan penolakan.',
    alasan:
      'LLM bisa melenceng; aturan menjaga bot tidak membocorkan peran atau mengikuti injeksi dari chat.',
  },
  nlg_templat: {
    judul: 'Cadangan templat',
    kode: 'kalimat_templat · kalimat_cadangan',
    tujuan: 'Selalu ada kalimat walau LLM gagal.',
    proses: 'Varian templat sesuai persona diisi nama target, lalu dinilai seperti kalimat LLM.',
    keluaran: 'Kalimat templat yang lolos.',
    alasan: 'Game tidak boleh menunggu LLM yang mati atau lambat.',
  },
  kirim: {
    tahap: ['kirim'],
    judul: 'Chat terkirim',
    kode: 'Match.add_message · catat_chat · baca_chat',
    tujuan: 'Menampilkan kalimat bot ke semua pemain.',
    proses:
      'Kalimat masuk chat room, ingatan bot mencatat aksinya, dan NLU membaca kalimat bot untuk konteks berikutnya.',
    keluaran: 'Gelembung chat bot.',
    alasan: 'Bot lain dan pemain membaca chat ini di langkah berikutnya.',
  },
  simpan: {
    judul: 'Parameter disimpan',
    kode: 'Ingatan · checker_traces · chat_messages.nlu',
    tujuan: 'Menyimpan hasil langkah untuk langkah berikutnya dan untuk panel.',
    proses:
      'Ingatan bot (chat, vote, aksi rahasia) dipakai langkah berikutnya. Di room asli jejak checker dan bacaan NLU masuk database; simulasi tidak menyimpan ke database.',
    keluaran: 'Ingatan dan jejak langkah ini.',
    alasan: 'Bot menimbang kejadian sebelumnya; admin bisa memeriksa ulang.',
  },
  output: {
    tahap: ['selesai'],
    judul: 'Output',
    kode: 'jejak checker (isi_jejak)',
    tujuan: 'Hasil akhir satu langkah bot.',
    proses: 'Chat (bila ada), vote, atau aksi rahasia, beserta lama prosesnya.',
    keluaran: 'Item di chat room; klik item itu untuk melihat prosesnya.',
    alasan: 'Satu langkah bot selesai; bot berikutnya mulai.',
  },
};
// Tata letak: baris berurutan (panah ke bawah), item dalam satu baris dihubungkan panah ke kanan.
const BARIS_ALUR = [
  ['input'],
  ['nlu_pesan'],
  ['nlu_intent', 'nlu_target', 'nlu_memo'],
  ['sinkron'],
  ['bukti'],
  'cabang',
  ['keputusan', 'penjelasan'],
  ['engine'],
  ['nlg_prompt', 'nlg_llm', 'nlg_cek', 'nlg_templat'],
  ['kirim', 'simpan'],
  ['output'],
];
const CABANG_ALUR = {
  fuzzy: ['fl', 'fl_1', 'fl_2', 'fl_3', 'fl_4'],
};
let simProgres = null, // {nama: {tahap, detik}} selama simulasi berjalan
  flowNode = '';
function metodePemain(nama) {
  return sim?.pemain.find((p) => p.nama === nama)?.metode;
}
// Node tempat pemain berada untuk satu tahap live; tahap logika menandai kepala cabang metodenya.
function nodeTahap(nama, tahap) {
  if (tahap === 'logika') return { fuzzy: 'fl' }[metodePemain(nama)];
  return Object.keys(ALUR_AI).find((id) => ALUR_AI[id].tahap?.includes(tahap));
}
// Lama tiap node untuk item chat terpilih (ms), dari timings jejak.
function waktuNode(trace) {
  if (!trace) return {};
  if (isHuman(trace)) return { nlu_pesan: trace.nlu?.ms };
  const t = trace.timings || {},
    kepala = { fuzzy: 'fl' }[trace.ringkas?.bot?.metode];
  return {
    sinkron: t.nlu_ms,
    ...(kepala ? { [kepala]: t.logika_ms } : {}),
    penjelasan: t.penjelasan_ms,
    nlg_llm: t.llm_ms,
    nlg_cek: waktuAturan(t),
    output: trace.duration_ms,
  };
}
function flowBox(id, posisi, waktuMs, terpakai) {
  const n = ALUR_AI[id];
  const kelas = ['flow-node'];
  if (posisi[id]?.length) kelas.push('flow-aktif');
  if (terpakai && !terpakai.has(id)) kelas.push('flow-redup');
  if (flowNode === id) kelas.push('selected');
  const b = node('button', undefined, kelas.join(' '));
  b.type = 'button';
  b.append(node('strong', n.judul), node('small', n.kode.split(' · ')[0], 'flow-kode'));
  if (typeof waktuMs[id] === 'number')
    b.append(node('span', duration(waktuMs[id]), 'process-time'));
  if (posisi[id]?.length) {
    const bots = node('span', undefined, 'flow-bots');
    for (const nama of posisi[id]) bots.append(chip(nama, 'status-good'));
    b.append(bots);
  }
  b.onclick = () => {
    flowNode = id;
    renderFlow();
  };
  return b;
}
// Node yang dilalui item terpilih (untuk meredupkan cabang/tahap yang tidak dipakai).
function jalurTerpakai(trace) {
  if (!trace || isSistem(trace)) return null;
  if (isHuman(trace))
    return new Set(['input', 'nlu_pesan', 'nlu_intent', 'nlu_target', 'nlu_memo']);
  const r = trace.ringkas || {},
    metode = r.bot?.metode;
  const ids = ['sinkron', 'bukti', ...(CABANG_ALUR[metode] || []), 'keputusan', 'penjelasan'];
  ids.push('engine', 'simpan', 'output');
  if (r.nlg === 'terkirim') {
    ids.push('nlg_prompt', 'nlg_cek', 'kirim');
    if ((trace.timings?.llm_ms || 0) > 0) ids.push('nlg_llm');
    if (traceSumber(trace) !== 'llm') ids.push('nlg_templat');
  }
  return new Set(ids);
}
function traceSumber(trace) {
  try {
    return JSON.parse(trace.output || '{}').nlg?.sumber;
  } catch {
    return null;
  }
}
function renderFlow() {
  const box = $('sim-flow');
  const trace = simTraces.find((t) => t.id === simSelected);
  const posisi = {},
    antre = [],
    sedang = [];
  for (const [nama, p] of Object.entries(simProgres || {})) {
    if (p.tahap === 'menunggu') {
      antre.push(nama);
      continue;
    }
    const id = nodeTahap(nama, p.tahap);
    if (id) (posisi[id] ||= []).push(`${nama} ${teks(p.detik)}s`);
    if (id && p.tahap !== 'selesai')
      sedang.push(`${nama} di "${ALUR_AI[id].judul}" (${teks(p.detik)} dtk)`);
  }
  const waktuMs = simProgres ? {} : waktuNode(trace);
  const terpakai = simProgres ? null : jalurTerpakai(trace);
  const isi = [];
  isi.push(
    node(
      'p',
      simProgres
        ? [
            'Sedang berjalan.',
            sedang.length && `Posisi: ${sedang.join(' · ')}.`,
            antre.length && `Menunggu giliran: ${antre.join(', ')}.`,
          ]
            .filter(Boolean)
            .join(' ')
        : trace && !isSistem(trace)
          ? `Waktu di kotak = langkah ${trace.ringkas?.bot?.nama || trace.sender} yang dipilih di chat; kotak redup tidak dilalui langkah itu.`
          : 'Pilih item chat untuk melihat lama tiap tahap. Saat bot berpikir, posisinya tampil di sini.',
      'hint',
    ),
  );
  BARIS_ALUR.forEach((baris, i) => {
    if (i) isi.push(node('span', '↓', 'flow-arrow'));
    if (baris === 'cabang') {
      const cabang = node('div', undefined, 'flow-branch');
      for (const ids of Object.values(CABANG_ALUR)) {
        const lajur = node('div', undefined, 'flow-lane');
        ids.forEach((id, j) => {
          if (j) lajur.append(node('span', '↓', 'flow-arrow'));
          lajur.append(flowBox(id, posisi, waktuMs, terpakai));
        });
        cabang.append(lajur);
      }
      isi.push(cabang);
      return;
    }
    const row = node('div', undefined, 'flow-row');
    baris.forEach((id, j) => {
      if (j) row.append(node('span', '→', 'flow-arrow'));
      row.append(flowBox(id, posisi, waktuMs, terpakai));
    });
    isi.push(row);
  });
  box.replaceChildren(...isi);
  renderFlowDetail(trace);
}
// Data node pada item chat terpilih: hasil antara yang benar-benar terjadi di langkah itu.
function dataNode(id, trace) {
  if (!trace || isSistem(trace)) return null;
  if (isHuman(trace)) return id.startsWith('nlu') ? `Bacaan: ${nluTeks(trace.nlu)}` : null;
  const p = trace.penjelasan || {},
    t = trace.timings || {},
    nlg = p.nlg || {},
    k = p.keputusan || {};
  const penalaran = Object.values(p.penalaran || {})
    .filter((blok) => blok?.hasil)
    .map((blok) => `${blok.judul}: ${blok.hasil}`);
  if (id === 'sinkron')
    return listOf(
      (p.nlu_dibaca || [])
        .map((c) => `${c.pengirim}: “${c.teks}” → ${c.intent}`)
        .concat(p.nlu_dibaca?.length ? [] : ['Tidak ada chat baru.']),
    );
  if (id === 'bukti') return p.tersangka ? dataTable(p.tersangka) : null;
  if (ALUR_AI[id].metode) return penalaran.length ? listOf(penalaran) : null;
  if (id === 'keputusan')
    return keyValues([
      ['Chat', planText(k.chat, true)],
      ['Vote', planText(k.vote)],
      ['Aksi rahasia', planText(k.aksi)],
    ]);
  if (id === 'engine') return engineText(p.engine);
  if (id.startsWith('nlg'))
    return nlg.status === 'terkirim'
      ? keyValues([
          ['Kalimat', nlg.teks],
          ['Sumber', SUMBER_NLG[nlg.sumber] || nlg.sumber],
          ['LLM', duration(t.llm_ms)],
          ['Cek aturan', duration(waktuAturan(t))],
          ['Pelanggaran', nlg.pelanggaran],
        ])
      : nlgBelum(nlg);
  if (id === 'kirim') return trace.nlu ? `Kalimat bot dibaca NLU: ${nluTeks(trace.nlu)}` : null;
  if (id === 'output')
    return `${trace.ringkas?.keputusan?.join(' · ') || 'diam'} · total ${duration(trace.duration_ms)}`;
  return null;
}
// KODE ASLI tiap kotak: dimuat sekali dari server (sumber modul yang sedang berjalan) lalu disimpan di cache.
const kodeCache = new Map();
let renderedFlowDetail = ''; // kotak + item chat yang sedang tampil: polling tidak merender ulang kode
function teksParameter(p) {
  return p.bawaan === null ? p.nama : `${p.nama}=${p.bawaan}`;
}
function kodeView(item) {
  const box = node('section', undefined, 'kode-fungsi');
  const param = item.parameter.map(teksParameter).join(', ');
  const head = node('div', undefined, 'kode-head');
  head.append(
    node('strong', item.konstanta ? `${item.nama} (konstanta)` : `${item.nama}(${param})`),
    node('small', `${item.berkas} · baris ${item.mulai}–${item.akhir}`),
  );
  const keluar = item.baris.filter((b) => b.jenis === 'output').map((b) => b.teks.trim());
  const ringkas = [
    [
      'Output (return)',
      keluar.length
        ? keluar.join(' | ')
        : item.konstanta
          ? 'nilai konstanta di bawah'
          : 'tanpa return: mengubah data atau objek yang diberikan',
    ],
  ];
  if (!item.konstanta)
    ringkas.unshift(['Parameter', item.parameter.length ? param : 'tanpa parameter']);
  box.append(head, keyValues(ringkas));
  const isi = node('div', undefined, 'kode-isi');
  for (const b of item.baris) {
    const row = node('div', undefined, `kode-baris${b.jenis ? ` kode-${b.jenis}` : ''}`);
    row.append(node('span', String(b.no), 'kode-no'), node('code', b.teks || ' '));
    isi.append(row);
    if (b.catatan) isi.append(node('div', `↑ ${b.catatan}`, 'kode-tanda'));
  }
  box.append(isi);
  return box;
}
async function tampilkanKode(container, id) {
  container.append(
    node('h4', 'Kode asli', 'report-title'),
    node(
      'p',
      'Dibaca langsung dari kode server yang sedang berjalan. Biru = parameter (baris def), hijau = output (return), kuning = baris inti dengan catatan, abu = komentar.',
      'hint',
    ),
  );
  if (!kodeCache.has(id)) {
    const status = node('p', 'Memuat kode…', 'hint');
    container.append(status);
    try {
      const data = await request(`/api/panel/kode/${encodeURIComponent(id)}`);
      kodeCache.set(id, data.kode || []);
    } catch (error) {
      status.textContent = `Kode gagal dimuat: ${error.message}`;
      return;
    }
    status.remove();
  }
  if (flowNode !== id || !container.isConnected) return; // kotak lain sudah dipilih
  for (const item of kodeCache.get(id)) container.append(kodeView(item));
}
function renderFlowDetail(trace) {
  const box = $('flow-detail'),
    n = ALUR_AI[flowNode];
  const key = `${flowNode}|${trace?.id || ''}`;
  if (renderedFlowDetail === key) return;
  renderedFlowDetail = key;
  if (!n) {
    box.classList.add('empty-state');
    box.textContent =
      'Klik satu kotak untuk melihat tujuan, proses, kode asli, output, dan alasannya.';
    return;
  }
  box.classList.remove('empty-state');
  box.replaceChildren(
    node('h4', n.judul, 'report-title'),
    keyValues([
      ['Tujuan', n.tujuan],
      ['Proses', n.proses],
      ['Output yang diharapkan', n.keluaran],
      ['Alasan dibuat begini', n.alasan],
    ]),
  );
  const data = dataNode(flowNode, trace);
  if (data) {
    box.append(node('h4', 'Pada item chat yang dipilih', 'report-title'));
    box.append(typeof data === 'string' ? node('p', data) : data);
  }
  tampilkanKode(box, flowNode).catch((error) => notice(error.message));
}
// SIMULASI: pertandingan tiruan (admin + bot Fuzzy) memakai engine, otak, NLU, dan NLG asli di server.
// Item chat dan detailnya memakai tampilan yang sama dengan checker room.
let sim = null,
  simTraces = [],
  simSelected = '',
  simBusy = false;
function renderSimStatus() {
  const box = $('sim-status');
  box.hidden = !sim;
  if (!sim) {
    box.replaceChildren();
    return;
  }
  const head = node('div', undefined, 'room-head');
  head.append(
    chip(sim.pemenang ? 'Selesai' : 'Simulasi', sim.pemenang ? 'status-pending' : 'status-good'),
    node('strong', `Ronde ${sim.ronde} · ${FASE_LABEL[sim.fase] || sim.fase}`),
    node(
      'span',
      sim.pemenang
        ? `Pemenang: ${sim.pemenang === 'hitman' ? 'Hitman' : 'Warga'}`
        : `detik ke-${teks(sim.detik)} dari ${sim.durasi ?? '—'} detik fase`,
      'room-meta',
    ),
  );
  box.replaceChildren(
    head,
    dataTable({
      kolom: ['pemain', 'role', 'metode', 'persona', 'status'],
      baris: sim.pemain.map((p) => [
        p.manusia ? `${p.nama} (kamu)` : p.nama,
        ROLE_LABEL[p.role] || p.role,
        p.manusia ? 'manusia' : METODE_LABEL[p.metode] || p.metode,
        p.persona,
        p.status,
      ]),
    }),
  );
}
function renderSim() {
  renderSimStatus();
  renderChat($('sim-chat'), simTraces, simSelected, selectSim);
  renderFlow();
  $('sim-send').disabled = simBusy || !sim?.bisa_chat;
  $('sim-message').disabled = !sim?.bisa_chat;
  $('sim-message').placeholder = !sim
    ? 'Mulai simulasi dulu'
    : sim.bisa_chat
      ? 'Tulis chat seperti di game…'
      : 'Chat terkunci pada fase ini';
  $('sim-run').disabled = $('sim-phase').disabled = simBusy || !sim || Boolean(sim.pemenang);
  $('sim-start').disabled = simBusy;
}
function selectSim(id) {
  simSelected = id;
  renderSim();
  showSimDetail();
}
function showSimDetail() {
  const box = $('sim-detail'),
    trace = simTraces.find((t) => t.id === simSelected);
  if (!trace || isSistem(trace)) {
    box.classList.add('empty-state');
    box.textContent = 'Klik chat atau langkah bot untuk melihat prosesnya.';
  } else if (isHuman(trace)) renderHuman(box, trace, simTraces, selectSim);
  else if (trace.penjelasan)
    renderDecision(
      box,
      trace,
      sebelumnya(trace, simTraces, (t) => t.penjelasan),
    );
  else renderReport(box, trace);
}
// Satu permintaan simulasi; waktu berjalan ditampilkan karena LLM bisa butuh beberapa detik per bot.
// pantau: tahap tiap bot diambil berkala dan ditandai di flowchart selama permintaan berjalan.
async function simRequest(path, body, label, pantau = false) {
  if (simBusy) return null;
  simBusy = true;
  renderSim();
  const epoch = generation,
    started = performance.now(),
    id = sim?.id;
  const timer = setInterval(() => {
    $('sim-progress').textContent =
      `${label} ${((performance.now() - started) / 1000).toFixed(1)} dtk`;
  }, 100);
  let polling = false;
  const poll = setInterval(async () => {
    if (!pantau || !id || polling) return;
    polling = true;
    try {
      const data = await request(`/api/panel/simulasi/${encodeURIComponent(id)}/progres`);
      if (simBusy && epoch === generation) {
        simProgres = data.progres;
        renderFlow();
      }
    } catch {
      // Progres hanya tampilan; kegagalan polling tidak menghentikan simulasi.
    } finally {
      polling = false;
    }
  }, 400);
  try {
    const data = await request(path, body, 'POST');
    return epoch === generation && token ? data : null;
  } finally {
    clearInterval(timer);
    clearInterval(poll);
    simProgres = null;
    $('sim-progress').textContent = '';
    simBusy = false;
    renderSim();
  }
}
// Tambahkan jejak baru ke chat dan buka item pilihan (default: item terakhir).
function terimaSim(data, pilih) {
  if (!data) return;
  const { jejak, ...ringkas } = data;
  sim = ringkas;
  simTraces.push(...jejak);
  simSelected = (pilih(jejak) || jejak[jejak.length - 1] || {}).id || simSelected;
  renderSim();
  showSimDetail();
}
async function simAksi(aksi, label, isi = '') {
  if (!sim) return;
  const data = await simRequest(
    `/api/panel/simulasi/${encodeURIComponent(sim.id)}`,
    { aksi, teks: isi, detik: Number($('sim-step').value) || 0 },
    label,
    true,
  );
  terimaSim(data, (jejak) => jejak.find(isHuman));
}
// Validasi urutan tanggal dan susun parameter untuk riwayat serta ekspor CSV.
function susunFilterRiwayat() {
  const tanggalAwal = $('date-from').value,
    tanggalAkhir = $('date-to').value;
  if (tanggalAwal && tanggalAkhir && tanggalAwal > tanggalAkhir)
    throw new Error('Tanggal awal harus sebelum atau sama dengan tanggal akhir.');
  const filter = new URLSearchParams();
  if (tanggalAwal) filter.set('date_from', tanggalAwal);
  if (tanggalAkhir) filter.set('date_to', tanggalAkhir);
  if ($('history-room').value) filter.set('room_code', $('history-room').value);
  filter.set('sender_kind', $('history-sender').value);
  filter.set('urut', $('history-order').value);
  return filter;
}
// Muat halaman riwayat dan abaikan respons dari sesi atau filter yang sudah berubah.
async function muatRiwayat(dariAwal = true) {
  const filter = susunFilterRiwayat(),
    generasiAwal = generation;
  if (dariAwal) {
    versiRiwayat++;
    idRiwayatTerakhir = 0;
    $('history-rows').replaceChildren();
  }
  const versiRequest = versiRiwayat;
  // idRiwayatTerakhir = id terakhir halaman sebelumnya; urut "baru" melanjutkan ke pesan yang lebih lama.
  if (filter.get('urut') === 'baru') {
    if (idRiwayatTerakhir) filter.set('before_id', String(idRiwayatTerakhir));
  } else filter.set('after_id', String(idRiwayatTerakhir));
  const halaman = await request(`/api/panel/history?${filter}`);
  if (generasiAwal !== generation || !token || versiRequest !== versiRiwayat) return;
  for (const pesan of halaman.messages) {
    const baris = document.createElement('tr');
    const waktuKirim = new Date(
      pesan.created_at.endsWith('Z') ? pesan.created_at : pesan.created_at + 'Z',
    );
    for (const isiSel of [
      `#${pesan.id}\n${waktuKirim.toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' })}`,
      `${pesan.room_code || '-'}\nRonde ${pesan.round_number ?? '-'} | ${pesan.phase || 'legacy'}`,
      `${pesan.sender_name}\n${pesan.sender_kind}`,
      pesan.message,
    ]) {
      const sel = document.createElement('td');
      sel.textContent = isiSel;
      baris.append(sel);
    }
    baris.append(node('td', nluTeks(pesan.nlu)), konteksSel(pesan.nlu));
    $('history-rows').append(baris);
  }
  idRiwayatTerakhir = halaman.next_after_id;
  $('more-history').hidden = !halaman.has_more;
  $('history-empty').hidden = $('history-rows').children.length > 0;
}
// Unduh CSV panel lewat request bertoken, lalu simpan sebagai berkas di browser.
async function unduhCsv(alamat, namaBerkas, pesanGagal) {
  const respons = await fetch(alamat, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!respons.ok) {
    if (respons.status === 401) clearSession();
    throw new Error(pesanGagal);
  }
  const alamatBerkas = URL.createObjectURL(await respons.blob()),
    tautan = document.createElement('a');
  tautan.href = alamatBerkas;
  tautan.download = namaBerkas;
  document.body.append(tautan);
  tautan.click();
  tautan.remove();
  setTimeout(() => URL.revokeObjectURL(alamatBerkas), 60000);
}
// Bungkus event async agar submit tidak me-reload halaman dan error tampil di panel.
function handle(tugas) {
  return async (event) => {
    if (event) event.preventDefault();
    try {
      await tugas(event);
    } catch (error) {
      notice(error.message);
    }
  };
}
$('login-form').onsubmit = handle(async () => {
  $('login-button').disabled = true;
  try {
    const sesi = await request(
      '/api/panel/login',
      { username: $('username').value, password: $('password').value },
      'POST',
    );
    token = sesi.access_token;
    await loadConfig();
    await muatDaftarRuangan();
    $('login-view').hidden = true;
    $('workspace').hidden = false;
    $('logout').hidden = false;
    await bukaMenu('ai');
    notice('Login administrator berhasil.');
  } catch (error) {
    if (token) await request('/api/panel/logout', null, 'POST').catch(() => {});
    clearSession();
    throw error;
  } finally {
    $('password').value = '';
    $('login-button').disabled = false;
  }
});
// Ganti menu aktif lalu muat data yang dibutuhkan halaman tujuan.
async function bukaMenu(namaMenu) {
  menu = namaMenu;
  for (const tombol of document.querySelectorAll('[data-menu]')) {
    if (tombol.dataset.menu === namaMenu) tombol.setAttribute('aria-current', 'page');
    else tombol.removeAttribute('aria-current');
  }
  for (const id of ['ai', 'checker', 'history', 'users', 'npc', 'survey', 'simulasi', 'dokumen'])
    $('menu-' + id).hidden = id !== namaMenu;
  if (namaMenu === 'checker' || namaMenu === 'history') await muatDaftarRuangan();
  if (namaMenu === 'checker') await checker();
  if (namaMenu === 'history') await muatRiwayat();
  if (namaMenu === 'users') await muatDaftarAkun();
  if (namaMenu === 'npc') await loadNpc();
  if (namaMenu === 'survey') await muatSurvei();
  if (namaMenu === 'simulasi') renderSim();
}

// OTAK NPC: isi pilihan dari server agar panel tidak perlu tahu daftar penulis.
function fillSelect(select, options, value) {
  select.replaceChildren(
    ...Object.entries(options).map(([key, label]) => {
      const option = node('option', label);
      option.value = key;
      return option;
    }),
  );
  select.value = value;
}
// RANTAI PENULIS: urutan dan jalur aktif diubah di panel, dikirim saat Simpan; status dari server.
// npcDirty: ada editan form yang belum disimpan; refresh otomatis dan hasil cek tidak menimpanya.
let npcChain = [],
  npcPaths = {},
  npcChainStatus = {},
  npcDirty = false;
const WRITER_STATE = {
  dipakai: ['Dipakai', 'status-good'],
  siap: ['Siap', 'status-good'],
  istirahat: ['Istirahat', 'status-pending'],
  ditolak: ['Ditolak', 'status-bad'],
  tidak_ada: ['Belum diatur', 'status-muted'],
  nonaktif: ['Nonaktif', 'status-muted'],
};
function writerLabel(path) {
  return npcPaths[path]?.label ?? path;
}
function moveWriter(index, step) {
  const target = index + step;
  if (target < 0 || target >= npcChain.length) return;
  [npcChain[index], npcChain[target]] = [npcChain[target], npcChain[index]];
  npcDirty = true;
  renderChain();
}
// Satu baris per jalur: aktif/nonaktif, nama, asal key/link, status cek terakhir, dan tombol prioritas.
function renderChain() {
  let priority = 0;
  $('npc-chain').replaceChildren(
    ...npcChain.map((item, index) => {
      const info = npcPaths[item.jalur] ?? {};
      const last = npcChainStatus[item.jalur] ?? {};
      const row = node('li', undefined, item.dipakai ? 'chain-item' : 'chain-item off');
      const toggle = document.createElement('input');
      toggle.type = 'checkbox';
      toggle.checked = item.dipakai;
      toggle.setAttribute('aria-label', `Pakai ${writerLabel(item.jalur)}`);
      toggle.onchange = () => {
        item.dipakai = toggle.checked;
        npcDirty = true;
        renderChain();
      };
      const text = node('div', undefined, 'chain-text');
      const order = item.dipakai ? `${++priority}. ` : '';
      // Link LLM: host yang benar-benar dipakai dan asalnya (panel atau .env bawaan server).
      const address = last.alamat ? `${last.alamat.host} (${last.alamat.sumber})` : '';
      text.append(
        node('strong', order + writerLabel(item.jalur)),
        node('small', [last.model, address, info.sumber].filter(Boolean).join(' · ')),
      );
      const move = node('div', undefined, 'chain-move');
      for (const [step, symbol, verb] of [
        [-1, '▲', 'Naikkan'],
        [1, '▼', 'Turunkan'],
      ]) {
        const button = node('button', symbol, 'secondary');
        button.type = 'button';
        button.disabled = index + step < 0 || index + step >= npcChain.length;
        button.setAttribute('aria-label', `${verb} prioritas ${writerLabel(item.jalur)}`);
        button.onclick = () => moveWriter(index, step);
        move.append(button);
      }
      const [stateLabel, stateClass] = WRITER_STATE[last.keadaan] ?? [
        'Belum dicek',
        'status-pending',
      ];
      const state = node('div', undefined, 'chain-state');
      const check = last.hasil_cek;
      const unverified =
        !check && ['dipakai', 'siap'].includes(last.keadaan) && last.status === 'belum dicek';
      state.append(
        node(
          'span',
          unverified ? 'Belum dicek' : stateLabel,
          `chip ${unverified ? 'status-pending' : stateClass}`,
        ),
      );
      if (check) {
        const checking = check.keadaan === 'memeriksa';
        const success = check.keadaan === 'berhasil';
        state.append(
          node(
            'span',
            checking ? 'Sedang dicek…' : success ? 'Hit berhasil' : 'Hit gagal',
            `chip ${checking ? 'status-pending' : success ? 'status-good' : 'status-bad'}`,
          ),
        );
        if (!checking) {
          state.append(
            node(
              'small',
              `Cek terakhir: ${new Date(check.waktu * 1000).toLocaleString('id-ID')} · ${(check.durasi_ms / 1000).toFixed(2)} detik`,
            ),
          );
          if (!success && check.detail) state.append(node('small', check.detail));
        }
      }
      if (last.status) state.append(node('small', last.status));
      if (last.panggilan || last.token_masuk)
        state.append(
          node(
            'small',
            `${last.panggilan} panggilan · token ${last.token_masuk}/${last.token_keluar} sejak cek terakhir`,
          ),
        );
      row.append(toggle, text, move, state);
      return row;
    }),
  );
  $('npc-chain-box').classList.toggle('muted', $('npc-writer').value === 'templat');
}
// Cek jalur berjalan di latar setelah simpan/startup: muat ulang sekali agar hasilnya terlihat.
function scheduleNpcRefresh(status) {
  clearTimeout(scheduleNpcRefresh.timer);
  if (!status.sedang_cek_penulis) return;
  scheduleNpcRefresh.timer = setTimeout(() => {
    if (token && menu === 'npc') loadNpc({ form: false }).catch(() => {});
  }, 3000);
}
// Tampilkan status pemuatan otak, sumber NLU, dan penulis kalimat yang benar-benar aktif.
// form=false (refresh otomatis, hasil cek) hanya memperbarui status; isi form dan urutan rantai lokal tetap.
// Pilihan model link: bawaan Konfigurasi AI, lalu model yang ditemukan di link saat tes terakhir.
function fillLinkModels(status, selected) {
  const available = status.model_tautan_tersedia ?? [];
  const options = [['', `Bawaan (${status.model_tautan_bawaan || 'Konfigurasi AI'})`]];
  for (const model of available) options.push([model, model]);
  if (selected && !available.includes(selected))
    options.push([selected, `${selected} (belum terlihat di link)`]);
  $('npc-link-model').replaceChildren(
    ...options.map(([value, label]) => {
      const option = node('option', label);
      option.value = value;
      return option;
    }),
  );
  $('npc-link-model').value = selected;
}
function showNpc(data, { form = true } = {}) {
  const status = data.status;
  $('check-writers').disabled = !!status.sedang_cek_penulis;
  $('check-writers').textContent = status.sedang_cek_penulis
    ? 'Sedang menguji prioritas…'
    : 'Tes koneksi semua prioritas';
  npcPaths = data.pilihan.jalur_penulis ?? {};
  const chain = status.rantai_penulis ?? [];
  npcChainStatus = Object.fromEntries(chain.map((row) => [row.jalur, row]));
  if (form || !npcChain.length) {
    fillSelect($('npc-writer'), data.pilihan.penulis, status.penulis_diminta);
    npcChain = chain.map((row) => ({
      jalur: row.jalur,
      dipakai: (status.urutan_penulis ?? []).includes(row.jalur),
    }));
    $('npc-openrouter-model').value = status.model_openrouter ?? '';
    npcDirty = false;
  }
  // Daftar model link ikut diperbarui setelah tes koneksi; pilihan yang belum disimpan dipertahankan.
  fillLinkModels(status, npcDirty ? $('npc-link-model').value : (status.model_tautan ?? ''));
  renderChain();
  const nlu = {
    indobert: 'IndoBERT (intent + target)',
  };
  const writer = status.penulis_aktif
    ? writerLabel(status.penulis) + (status.model_penulis ? ` (${status.model_penulis})` : '')
    : 'Templat bervariasi (tanpa LLM)';
  const rows = [
    ['Status', status.siap ? 'Siap' : status.gagal ? 'Gagal dimuat' : 'Memuat…'],
    ['Keterangan', status.detail],
    ['NLU', nlu[status.nlu] ?? '—'],
    ['Penulis kalimat sekarang', writer],
    ['Cek rantai penulis', status.sedang_cek_penulis ? 'Sedang dicek…' : 'Selesai'],
    ['Pertandingan dengan otak aktif', String(status.pertandingan_aktif)],
  ];
  $('npc-status').replaceChildren(
    ...rows.flatMap(([label, value]) => [node('dt', label), node('dd', value || '—')]),
  );
  scheduleNpcRefresh(status);
}
async function loadNpc(options) {
  const epoch = generation;
  const data = await request('/api/panel/npc');
  if (!token || epoch !== generation) return;
  showNpc(data, options);
}

// SURVEI: pertanyaan, jenis, skala, dan arti skala sepenuhnya diatur dari panel.
const LABEL_JENIS_PERTANYAAN = {
  stars: 'Bintang',
  scale: 'Skala angka',
  choice: 'Pilihan ganda',
  text: 'Teks bebas',
};
// Pilihan yang membuka isian bebas di form pemain (sama dengan PILIHAN_LAINNYA di backend).
const PILIHAN_LAINNYA = 'Lainnya';
// Urutan tabel Survei: id yang tampil, urutan terakhir yang diterima server, dan baris tabel per
// id. Simpan urutan berjalan satu per satu; perubahan selama menyimpan dikirim sesudahnya.
let urutanSurvei = [],
  urutanSurveiTersimpan = [],
  simpanUrutanBerjalan = false,
  simpanUrutanLagi = false;
const barisSurvei = new Map();

// Pasang baris tabel Survei sesuai urutanSurvei lalu perbarui nomor dan tombol ▲▼. Memindah baris
// di DOM membuang fokus keyboard, jadi fokus dikembalikan ke tombol yang tadi dipakai.
// Alur: 1 ingat fokus -> 2 pasang baris -> 3 perbarui nomor dan tombol -> 4 kembalikan fokus
function tampilkanUrutanSurvei() {
  // 1 ingat fokus
  const fokus = document.activeElement;
  const barisFokus = fokus?.closest?.('#survey-rows tr');
  // 2 pasang baris berurutan
  $('survey-rows').replaceChildren(...urutanSurvei.map((id) => barisSurvei.get(id)));
  // 3 perbarui nomor dan tombol; tombol di ujung tabel nonaktif
  urutanSurvei.forEach((id, indeks) => {
    const baris = barisSurvei.get(id);
    baris.querySelector('.urutan-nomor').textContent = String(indeks + 1);
    baris.querySelector('.urutan-naik').disabled = indeks === 0;
    baris.querySelector('.urutan-turun').disabled = indeks === urutanSurvei.length - 1;
  });
  // 4 kembalikan fokus; tombol yang kini nonaktif (baris di ujung) diganti tombol arah sebaliknya
  if (barisFokus?.isConnected && document.activeElement !== fokus)
    (fokus.disabled ? barisFokus.querySelector('.urutan-tombol:not(:disabled)') : fokus)?.focus();
}
// Pindahkan satu pertanyaan ke indeks baru, tampilkan langsung, lalu kirim seluruh urutan (termasuk
// yang nonaktif). Bila simpan sebelumnya masih berjalan, urutan terbaru dikirim sesudahnya.
// Alur: 1 susun -> 2 tampilkan -> 3 kirim -> 4.1.1 Tersimpan
//                                         \> 4.2.1 gagal: pulihkan urutan -> 4.2.2 tampilkan error
async function pindahkanPertanyaanSurvei(id, indeksBaru) {
  // 1 susun urutan baru; tujuan di luar tabel atau sama dengan tempat lama tidak mengubah apa pun
  const indeksLama = urutanSurvei.indexOf(id);
  if (indeksLama < 0 || indeksBaru < 0 || indeksBaru >= urutanSurvei.length) return;
  if (indeksBaru === indeksLama) return;
  urutanSurvei = urutanSurvei.filter((lain) => lain !== id);
  urutanSurvei.splice(indeksBaru, 0, id);
  // 2 tampilkan
  tampilkanUrutanSurvei();
  // 3 kirim ke server; perulangan mengirim lagi bila urutan berubah selama menunggu jawaban
  if (simpanUrutanBerjalan) {
    simpanUrutanLagi = true;
    return;
  }
  const generasiAwal = generation;
  const status = $('survey-order-status');
  simpanUrutanBerjalan = true;
  status.textContent = 'Menyimpan…';
  status.className = 'status-pending';
  try {
    do {
      simpanUrutanLagi = false;
      const ids = [...urutanSurvei];
      await request('/api/panel/survey/questions/order', { ids }, 'PUT');
      urutanSurveiTersimpan = ids;
    } while (simpanUrutanLagi);
    // 4.1.1 Tersimpan
    status.textContent = 'Tersimpan';
    status.className = 'status-good';
  } catch (error) {
    // 4.2.1 gagal: pulihkan urutan tersimpan; kegagalan dari sesi yang sudah keluar diabaikan
    if (generasiAwal !== generation) return;
    urutanSurvei = [...urutanSurveiTersimpan];
    tampilkanUrutanSurvei();
    // 4.2.2 tampilkan error
    status.textContent = `Urutan gagal disimpan dan dikembalikan: ${error.message}`;
    status.className = 'status-bad';
    notice(status.textContent);
  } finally {
    simpanUrutanBerjalan = false;
    simpanUrutanLagi = false;
  }
}
// Jawaban yang benar-benar diisi: angka, atau teks yang tidak kosong (pertanyaan opsional boleh dilewati).
function jawabanTerisi(jawaban) {
  return jawaban.value_number != null || (jawaban.value_text ?? '') !== '';
}
// Teks satu jawaban untuk admin: angka beserta skala dan arti ujungnya, atau isian teksnya.
function teksJawabanSurvei(jawaban) {
  if (jawaban.value_number == null) return jawaban.value_text || '— (tidak diisi)';
  const arti =
    jawaban.value_number === jawaban.scale_min
      ? jawaban.label_min
      : jawaban.value_number === jawaban.scale_max
        ? jawaban.label_max
        : null;
  return `${jawaban.value_number} dari ${jawaban.scale_max ?? '?'}${arti ? ` (${arti})` : ''}`;
}
// Kelompok batang diagram satu pertanyaan: setiap nilai skala, atau setiap pilihan ganda. Isian
// "Lainnya: …" masuk ke Lainnya; jawaban di luar daftar (pilihan lama) mendapat batang sendiri.
// Alur: 1 kelompok kosong sesuai skala atau pilihan -> 2 hitung tiap jawaban -> 3 daftar kelompok
function kelompokDiagramSurvei(pertanyaan, daftarJawaban) {
  const kelompok = new Map();
  if (pertanyaan.kind === 'choice') {
    for (const pilihan of pertanyaan.options) kelompok.set(pilihan, { label: pilihan, n: 0 });
  } else {
    for (let nilai = pertanyaan.scale_min; nilai <= pertanyaan.scale_max; nilai++) {
      const arti =
        nilai === pertanyaan.scale_min
          ? pertanyaan.label_min
          : nilai === pertanyaan.scale_max
            ? pertanyaan.label_max
            : null;
      kelompok.set(String(nilai), { label: arti ? `${nilai} · ${arti}` : String(nilai), n: 0 });
    }
  }
  for (const jawaban of daftarJawaban) {
    let kunci = pertanyaan.kind === 'choice' ? jawaban.value_text : String(jawaban.value_number);
    if (pertanyaan.kind === 'choice' && kunci.startsWith(`${PILIHAN_LAINNYA}:`))
      kunci = PILIHAN_LAINNYA;
    if (!kelompok.has(kunci)) kelompok.set(kunci, { label: kunci, n: 0 });
    kelompok.get(kunci).n++;
  }
  return [...kelompok.values()];
}
// Daftar isian teks yang dilipat (teks bebas, atau isian Lainnya): "nama: isian" per baris.
function lipatanIsianSurvei(judul, daftarJawaban) {
  const lipatan = node('details', undefined, 'survey-isian');
  const daftar = node('ul');
  for (const jawaban of daftarJawaban)
    daftar.append(node('li', `${jawaban.nama}: ${jawaban.value_text}`));
  lipatan.append(node('summary', `${judul} (${daftarJawaban.length})`), daftar);
  return lipatan;
}
// Diagram batang mendatar satu pertanyaan: satu batang per nilai atau pilihan, panjangnya persentase
// dari jawaban pertanyaan itu. Pertanyaan teks bebas menampilkan jumlah dan daftar isiannya.
// Alur: 1 jawaban terisi untuk pertanyaan ini -> 2 judul, jumlah, rata-rata -> 3 batang per kelompok
//       atau daftar isian teks -> 4 daftar isian Lainnya
function diagramSurvei(nomor, pertanyaan, daftarKiriman) {
  // 1 jawaban terisi (angka untuk skala, teks untuk pilihan dan teks bebas), beserta nama pengisinya
  const berskala = pertanyaan.kind === 'stars' || pertanyaan.kind === 'scale';
  const terisi = daftarKiriman.flatMap((kiriman) =>
    kiriman.answers
      .filter(
        (jawaban) =>
          jawaban.question_id === pertanyaan.id &&
          (berskala ? jawaban.value_number != null : (jawaban.value_text ?? '') !== ''),
      )
      .map((jawaban) => ({ ...jawaban, nama: kiriman.display_name ?? kiriman.username })),
  );

  // 2 judul dengan jumlah jawaban, rata-rata untuk skala, dan tanda nonaktif
  let ringkas = `${terisi.length} jawaban`;
  if (berskala && terisi.length) {
    const rataRata = terisi.reduce((jumlah, j) => jumlah + j.value_number, 0) / terisi.length;
    ringkas += ` · rata-rata ${rataRata.toFixed(2)}`;
  }
  if (!pertanyaan.active) ringkas += ' · nonaktif';
  const kotak = node('figure', undefined, 'survey-chart');
  const judul = node('figcaption');
  judul.append(node('strong', `${nomor}. ${pertanyaan.prompt}`), node('span', ringkas, 'hint'));
  kotak.append(judul);
  if (!terisi.length) {
    kotak.append(node('p', 'Belum ada jawaban.', 'hint'));
    return kotak;
  }

  // 3 teks bebas: daftar isian; skala dan pilihan: satu batang per kelompok
  if (pertanyaan.kind === 'text') {
    kotak.append(lipatanIsianSurvei('Lihat isian', terisi));
    return kotak;
  }
  for (const { label, n } of kelompokDiagramSurvei(pertanyaan, terisi)) {
    const persen = (n / terisi.length) * 100;
    const baris = node('div', undefined, 'survey-bar');
    baris.title = `${label}: ${n} dari ${terisi.length} jawaban (${persen.toFixed(0)}%)`;
    const jalur = node('span', undefined, 'survey-bar-track');
    const isi = node('span', undefined, 'survey-bar-fill');
    isi.style.width = `${persen}%`;
    jalur.append(isi);
    baris.append(
      node('span', label, 'survey-bar-label'),
      jalur,
      node('span', `${n} · ${persen.toFixed(0)}%`, 'survey-bar-value'),
    );
    kotak.append(baris);
  }

  // 4 isian bebas dari pilihan Lainnya
  const isianLainnya = terisi.filter(
    (jawaban) => pertanyaan.kind === 'choice' && jawaban.value_text.startsWith(`${PILIHAN_LAINNYA}:`),
  ); // pilihan dan teks bebas selalu punya value_text (disaring di langkah 1)
  if (isianLainnya.length) kotak.append(lipatanIsianSurvei('Isian Lainnya', isianLainnya));
  return kotak;
}
// Daftar bot satu pertandingan dari kolom bots ("NAMA:metode:persona | …") untuk dibaca admin.
function teksBotSurvei(bots) {
  return bots
    .split(' | ')
    .map((bot) => {
      const [nama, metode, persona] = bot.split(':');
      return persona ? `${nama} (${metode}, ${persona})` : bot;
    })
    .join(', ');
}
// Satu kiriman di daftar pengisi: baris ringkas dan baris rincian tersembunyi berisi semua isiannya.
// Klik nama membuka atau menutup rinciannya.
// Alur: 1 baris ringkas (waktu, nama tampilan, room, role, hasil, jumlah jawaban) -> 2 baris rincian: pertanyaan
//       dan jawaban, bot, username dan nomor pertandingan -> 3 tombol nama membuka/menutup rincian
function barisPengisiSurvei(kiriman) {
  // 1 baris ringkas
  const tombolNama = node('button', kiriman.display_name ?? kiriman.username, 'tombol-nama');
  tombolNama.type = 'button';
  tombolNama.setAttribute('aria-expanded', 'false');
  const selNama = node('td');
  selNama.append(tombolNama);
  const kubu = { hitman: 'Hitman', civilians: 'Warga' }[kiriman.team] ?? '—';
  const hasil = { won: 'menang', lost: 'kalah' }[kiriman.outcome] ?? '—';
  const baris = document.createElement('tr');
  baris.append(
    node('td', tanggal(kiriman.created_at)),
    selNama,
    node('td', kiriman.room_code),
    node('td', kiriman.role ?? '—'),
    node('td', `${kubu} · ${hasil}`),
    node('td', `${kiriman.answers.filter(jawabanTerisi).length} dari ${kiriman.answers.length}`),
  );

  // 2 baris rincian
  const rincian = document.createElement('tr');
  rincian.className = 'survey-detail';
  rincian.hidden = true;
  const selRincian = node('td');
  selRincian.colSpan = 6;
  const daftarJawaban = node('dl', undefined, 'survey-answers');
  for (const jawaban of kiriman.answers)
    daftarJawaban.append(
      node('dt', jawaban.prompt ?? jawaban.code),
      node('dd', teksJawabanSurvei(jawaban)),
    );
  selRincian.append(daftarJawaban);
  if (kiriman.bots)
    selRincian.append(node('p', `Bot di pertandingan ini: ${teksBotSurvei(kiriman.bots)}`, 'hint'));
  selRincian.append(
    node('p', `Akun ${kiriman.username} · pertandingan ${kiriman.match_id}`, 'hint'),
  );
  rincian.append(selRincian);

  // 3 buka/tutup rincian
  tombolNama.onclick = () => {
    rincian.hidden = !rincian.hidden;
    tombolNama.setAttribute('aria-expanded', String(!rincian.hidden));
  };
  return [baris, rincian];
}
// Bagian pengisi di menu Survei: kotak jumlah, diagram per pertanyaan, dan daftar pengisi.
// Alur: 1 kotak jumlah kiriman, orang, pertandingan -> 2 diagram untuk pertanyaan aktif dan pertanyaan
//       nonaktif yang punya jawaban -> 3 daftar pengisi (atau baris kosong)
function tampilkanPengisiSurvei(daftarPertanyaan, dataPengisi) {
  // 1 kotak jumlah
  const daftarKiriman = dataPengisi.respondents ?? [];
  $('survey-stats').replaceChildren(
    ...[
      ['Kiriman survei', dataPengisi.total_submissions],
      ['Orang yang mengisi', dataPengisi.total_people],
      ['Pertandingan', dataPengisi.total_matches],
    ].map(([judul, angka]) => {
      const kotak = node('div', undefined, 'metric');
      kotak.append(node('small', judul), node('strong', String(angka ?? 0)));
      return kotak;
    }),
  );

  // 2 diagram
  const punyaJawaban = new Set(
    daftarKiriman.flatMap((kiriman) => kiriman.answers.map((jawaban) => jawaban.question_id)),
  );
  const pertanyaanDiagram = daftarPertanyaan.filter(
    (pertanyaan) => pertanyaan.active || punyaJawaban.has(pertanyaan.id),
  );
  $('survey-charts').replaceChildren(
    ...pertanyaanDiagram.map((pertanyaan, indeks) =>
      diagramSurvei(indeks + 1, pertanyaan, daftarKiriman),
    ),
  );

  // 3 daftar pengisi
  if (!daftarKiriman.length) {
    const kosong = document.createElement('tr');
    const sel = node('td', 'Belum ada yang mengisi survei.', 'hint');
    sel.colSpan = 6;
    kosong.append(sel);
    $('survey-respondent-rows').replaceChildren(kosong);
    return;
  }
  $('survey-respondent-rows').replaceChildren(...daftarKiriman.flatMap(barisPengisiSurvei));
}
// Muat ringkasan dan pengisi survei, lalu tampilkan tabel pertanyaan (urutan server), rata-rata per
// metode, dan bagian pengisi (jumlah, diagram, daftar nama).
// Alur: 1 ambil ringkasan dan pengisi -> 2 kelompokkan nilai -> 3 bangun baris -> 4 tampilkan
//       -> 5 tabel metode -> 6 bagian pengisi
async function muatSurvei() {
  // 1 ambil ringkasan dan pengisi; jawaban untuk sesi lama diabaikan
  const generasiAwal = generation;
  const [ringkasan, pengisi] = await Promise.all([
    request('/api/panel/survey/summary'),
    request('/api/panel/survey/respondents'),
  ]);
  if (!token || generasiAwal !== generation) return;

  // 2 kelompokkan sebaran nilai dan jumlah jawaban teks per pertanyaan
  const sebaranNilai = {};
  for (const baris of ringkasan.distribution) (sebaranNilai[baris.question_id] ??= []).push(baris);
  const jumlahJawabanTeks = Object.fromEntries(
    ringkasan.text_answers.map((baris) => [baris.question_id, baris.n]),
  );

  // 3 bangun baris tiap pertanyaan; disimpan per id supaya bisa disusun ulang tanpa dibangun lagi
  barisSurvei.clear();
  for (const pertanyaan of ringkasan.questions) {
    const nilaiPertanyaan = sebaranNilai[pertanyaan.id] ?? [];
    const totalJawaban = nilaiPertanyaan.reduce((jumlah, baris) => jumlah + baris.n, 0);
    const rataRata = totalJawaban
      ? nilaiPertanyaan.reduce((jumlah, baris) => jumlah + baris.n * baris.value_number, 0) /
        totalJawaban
      : null;
    const hasilJawaban =
      pertanyaan.kind === 'text' || pertanyaan.kind === 'choice'
        ? `${jumlahJawabanTeks[pertanyaan.id] ?? 0} jawaban`
        : totalJawaban
          ? `${totalJawaban} jawaban · rata-rata ${rataRata.toFixed(2)}`
          : 'Belum ada';
    const artiSkala =
      pertanyaan.label_min || pertanyaan.label_max
        ? `${pertanyaan.scale_min} = ${pertanyaan.label_min ?? '—'} · ${pertanyaan.scale_max} = ${pertanyaan.label_max ?? '—'}`
        : '—';
    let jenisDanSkala = LABEL_JENIS_PERTANYAAN.text;
    if (pertanyaan.kind === 'stars' || pertanyaan.kind === 'scale')
      jenisDanSkala = `${LABEL_JENIS_PERTANYAAN[pertanyaan.kind]} ${pertanyaan.scale_min}–${pertanyaan.scale_max}`;
    else if (pertanyaan.kind === 'choice')
      jenisDanSkala = `${LABEL_JENIS_PERTANYAAN.choice}: ${pertanyaan.options
        .map((pilihan) => (pilihan === PILIHAN_LAINNYA ? `${pilihan} (isian bebas)` : pilihan))
        .join(' / ')}`;

    // Sel urutan: pegangan seret (mouse), nomor tampil, dan tombol ▲▼ untuk HP dan keyboard.
    const selUrutan = node('td', undefined, 'urutan-survei');
    const pegangan = node('span', '⋮⋮', 'pegangan-seret');
    pegangan.draggable = true;
    pegangan.title = 'Seret untuk memindah urutan';
    pegangan.setAttribute('aria-hidden', 'true');
    selUrutan.append(pegangan, node('span', '', 'urutan-nomor'));
    for (const [langkah, simbol, kerja, kelas] of [
      [-1, '▲', 'Naikkan', 'urutan-naik'],
      [1, '▼', 'Turunkan', 'urutan-turun'],
    ]) {
      const tombolUrutan = node('button', simbol, `secondary urutan-tombol ${kelas}`);
      tombolUrutan.type = 'button';
      tombolUrutan.title = `${kerja} (Alt+${langkah < 0 ? '↑' : '↓'})`;
      tombolUrutan.setAttribute('aria-label', `${kerja} urutan: ${pertanyaan.prompt}`);
      tombolUrutan.onclick = () =>
        pindahkanPertanyaanSurvei(pertanyaan.id, urutanSurvei.indexOf(pertanyaan.id) + langkah);
      selUrutan.append(tombolUrutan);
    }

    const tombolEdit = node('button', 'Edit', 'secondary');
    tombolEdit.type = 'button';
    // Isi form dari data pertanyaan untuk diedit; posisi tidak ikut, edit tidak menggeser urutan.
    tombolEdit.onclick = () => {
      $('survey-id').value = String(pertanyaan.id);
      $('survey-code').value = pertanyaan.code;
      $('survey-prompt').value = pertanyaan.prompt;
      $('survey-kind').value = pertanyaan.kind;
      $('survey-min').value = String(pertanyaan.scale_min);
      $('survey-max').value = String(pertanyaan.scale_max);
      $('survey-label-min').value = pertanyaan.label_min ?? '';
      $('survey-label-max').value = pertanyaan.label_max ?? '';
      $('survey-options').value = pertanyaan.options.join('\n');
      $('survey-required').checked = pertanyaan.required;
      $('survey-active').checked = pertanyaan.active;
      $('survey-editor-title').textContent = 'Edit pertanyaan: ' + pertanyaan.code;
      $('survey-editor-box').open = true;
    };
    const tombolStatus = node(
      'button',
      pertanyaan.active ? 'Nonaktifkan' : 'Aktifkan',
      'secondary',
    );
    tombolStatus.type = 'button';
    tombolStatus.onclick = handle(() =>
      simpanPertanyaanSurvei({ ...pertanyaan, active: !pertanyaan.active }, pertanyaan.id),
    );
    const tombolHapus = node('button', 'Hapus', 'danger');
    tombolHapus.type = 'button';
    tombolHapus.onclick = handle(async () => {
      if (!window.confirm(`Hapus pertanyaan "${pertanyaan.prompt}" secara permanen?`)) return;
      await request(`/api/panel/survey/questions/${pertanyaan.id}`, undefined, 'DELETE');
      if ($('survey-id').value === String(pertanyaan.id)) kosongkanFormSurvei();
      notice('Pertanyaan survei dihapus.');
      await muatSurvei();
    });
    const selAksi = node('td');
    selAksi.append(tombolEdit, ' ', tombolStatus, ' ', tombolHapus);

    const barisTabel = document.createElement('tr');
    barisTabel.dataset.id = String(pertanyaan.id);
    barisTabel.append(
      selUrutan,
      node('td', pertanyaan.prompt + (pertanyaan.required ? '' : ' (opsional)')),
      node('td', jenisDanSkala),
      node('td', artiSkala),
      node('td', pertanyaan.active ? 'Aktif' : 'Nonaktif'),
      node('td', hasilJawaban),
      selAksi,
    );
    barisSurvei.set(pertanyaan.id, barisTabel);
  }

  // 4 tampilkan urutan dari server (ORDER BY position, id), sekaligus urutan tersimpan terakhir
  urutanSurvei = ringkasan.questions.map((pertanyaan) => pertanyaan.id);
  urutanSurveiTersimpan = [...urutanSurvei];
  tampilkanUrutanSurvei();

  // 5 tabel rata-rata per metode
  const teksPertanyaan = Object.fromEntries(
    ringkasan.questions.map((pertanyaan) => [pertanyaan.id, pertanyaan.prompt]),
  );
  $('survey-method-rows').replaceChildren(
    ...ringkasan.per_method.map((baris) => {
      const barisTabel = document.createElement('tr');
      barisTabel.append(
        node('td', teksPertanyaan[baris.question_id] ?? String(baris.question_id)),
        node('td', baris.method),
        node('td', String(baris.n)),
        node('td', baris.rata == null ? '—' : baris.rata.toFixed(2)),
      );
      return barisTabel;
    }),
  );

  // 6 bagian pengisi: jumlah, diagram, daftar nama
  tampilkanPengisiSurvei(ringkasan.questions, pengisi);
}
function kosongkanFormSurvei() {
  $('survey-form').reset();
  $('survey-id').value = '';
  $('survey-editor-title').textContent = '+ Tambah pertanyaan';
  $('survey-editor-box').open = false;
}
async function simpanPertanyaanSurvei(pertanyaan, idPertanyaan) {
  if (idPertanyaan) await request(`/api/panel/survey/questions/${idPertanyaan}`, pertanyaan, 'PUT');
  else await request('/api/panel/survey/questions', pertanyaan, 'POST');
  notice('Pertanyaan survei tersimpan. Pemain melihat versi terbaru di pertandingan berikutnya.');
  kosongkanFormSurvei();
  await muatSurvei();
}

// Muat daftar akun tanpa rahasia; versi request mencegah hasil filter lama menimpa pencarian baru.
async function muatDaftarAkun(dariAwal = true) {
  const generasiAwal = generation;
  if (dariAwal) {
    versiAkun++;
    idAkunTerakhir = 0;
    $('user-rows').replaceChildren();
  }
  const versiRequest = versiAkun;
  const filter = new URLSearchParams({
    after_id: String(idAkunTerakhir),
    search: $('user-search').value.trim(),
  });
  const halaman = await request('/api/panel/users?' + filter);
  if (!token || generasiAwal !== generation || versiRequest !== versiAkun) return;
  for (const akun of halaman.users) {
    const barisTabel = document.createElement('tr');
    for (const [label, nilai] of [
      ['Username', akun.username],
      ['Nama tampilan', akun.display_name],
      ['Login', akun.login_method === 'google' ? 'Google' : 'Password'],
    ]) {
      const sel = document.createElement('td');
      sel.dataset.label = label;
      if (label === 'Login') sel.append(node('span', nilai, 'login-method'));
      else sel.textContent = nilai;
      barisTabel.append(sel);
    }
    const buatTombolAksi = (teksTombol, kelasCss, tindakan) => {
      const tombol = node('button', teksTombol, kelasCss);
      tombol.onclick = () => bukaEditorAkun(akun, tindakan);
      return tombol;
    };
    const selAksi = document.createElement('td');
    selAksi.dataset.label = 'Aksi';
    const kelompokAksi = node('div', undefined, 'user-actions');
    kelompokAksi.append(
      buatTombolAksi('Edit user', 'secondary', 'profile'),
      akun.login_method !== 'google'
        ? buatTombolAksi('Ubah password', 'secondary', 'password')
        : node('small', 'Password dikelola Google. ', 'google-password-note'),
      buatTombolAksi('Hapus akun', 'danger', 'delete'),
    );
    selAksi.append(kelompokAksi);
    barisTabel.append(selAksi);
    $('user-rows').append(barisTabel);
  }
  idAkunTerakhir = halaman.next_after_id;
  $('more-users').hidden = !halaman.has_more;
  $('users-empty').hidden = $('user-rows').children.length > 0;
}

// Bersihkan password/draft konfirmasi setiap editor ditutup atau sesi panel berakhir.
function tutupEditorAkun() {
  akunTerpilih = null;
  if ($('user-editor').open) $('user-editor').close();
  $('user-editor').hidden = true;
  $('user-password-form').reset();
  $('user-profile-form').reset();
  $('user-delete-form').reset();
}

// Target disimpan sebagai ID; nama target ditampilkan sebelum admin mengonfirmasi tindakan.
function bukaEditorAkun(akun, tindakan) {
  if (sedangMenyimpanAkun) return;
  tutupEditorAkun();
  akunTerpilih = akun;
  $('user-editor').hidden = false;
  $('user-editor-title').textContent =
    { profile: 'Edit user: ', password: 'Ubah password: ', delete: 'Hapus akun: ' }[tindakan] +
    akun.username;
  $('user-profile-form').hidden = tindakan !== 'profile';
  $('edit-user-username').value = akun.username;
  $('edit-user-display-name').value = akun.display_name;
  $('user-password-form').hidden = tindakan !== 'password';
  $('user-delete-form').hidden = tindakan !== 'delete';
  $('user-editor').showModal();
  $(
    {
      profile: 'edit-user-username',
      password: 'user-new-password',
      delete: 'user-delete-confirmation',
    }[tindakan],
  ).focus();
}

// Cegah klik ganda dan pergantian target selama mutasi akun sedang berlangsung.
async function simpanPerubahanAkun(tindakan) {
  if (!akunTerpilih || sedangMenyimpanAkun) return;
  const akun = akunTerpilih;
  const generasiAwal = generation;
  const tombolEditor = [
    'save-user-profile',
    'save-user-password',
    'delete-user',
    'cancel-user-edit',
  ];

  // INPUT: isi request menurut tindakan; form yang tidak valid ditolak sebelum dikirim
  let isiRequest;
  if (tindakan === 'profile') {
    isiRequest = {
      username: $('edit-user-username').value.trim(),
      display_name: $('edit-user-display-name').value.trim(),
    };
  } else if (tindakan === 'password') {
    if (akun.login_method === 'google') throw new Error('Password akun Google dikelola di Google.');
    if ($('user-new-password').value !== $('user-password-confirmation').value)
      throw new Error('Konfirmasi password tidak cocok.');
    isiRequest = {
      password: $('user-new-password').value,
      password_confirmation: $('user-password-confirmation').value,
    };
  } else {
    if ($('user-delete-confirmation').value !== akun.username)
      throw new Error('Ketik username target dengan tepat untuk menghapus akun.');
    isiRequest = { confirm_username: $('user-delete-confirmation').value };
  }

  // PROSES: kunci editor selama request berjalan; password selalu dibersihkan sesudahnya
  sedangMenyimpanAkun = true;
  for (const id of tombolEditor) $(id).disabled = true;
  try {
    await request(`/api/panel/users/${akun.id}/${tindakan}`, isiRequest, 'POST');
    if (!token || generasiAwal !== generation) return;

    // OUTPUT: editor ditutup, hasil diumumkan, dan daftar akun dimuat ulang
    tutupEditorAkun();
    notice(
      {
        profile: 'Data user disimpan. Jika username berubah, user perlu login ulang.',
        password: 'Password diganti. Semua sesi user dicabut; user perlu login ulang.',
        delete: 'Akun dihapus. Riwayat chat dan analisis tetap tersimpan.',
      }[tindakan],
    );
    await muatDaftarAkun();
  } finally {
    $('user-new-password').value = '';
    $('user-password-confirmation').value = '';
    sedangMenyimpanAkun = false;
    for (const id of tombolEditor) $(id).disabled = false;
  }
}

$('user-search-form').onsubmit = handle(() => muatDaftarAkun());
$('more-users').onclick = handle(async () => {
  $('more-users').disabled = true;
  try {
    await muatDaftarAkun(false);
  } finally {
    $('more-users').disabled = false;
  }
});
$('cancel-user-edit').onclick = tutupEditorAkun;
$('user-editor').addEventListener('cancel', (event) => {
  event.preventDefault();
  if (!sedangMenyimpanAkun) tutupEditorAkun();
});
$('user-profile-form').onsubmit = handle(() => simpanPerubahanAkun('profile'));
$('user-password-form').onsubmit = handle(() => simpanPerubahanAkun('password'));
$('user-delete-form').onsubmit = handle(() => simpanPerubahanAkun('delete'));

// Buat akun tanpa login sebagai pemain; rahasia form selalu dibersihkan setelah request.
$('create-user-form').onsubmit = handle(async () => {
  if ($('create-user-button').disabled) return;
  if ($('create-password').value !== $('create-password-confirmation').value)
    throw new Error('Konfirmasi password tidak cocok.');
  const generasiAwal = generation;
  $('create-user-button').disabled = true;
  try {
    await request(
      '/api/panel/users',
      {
        username: $('create-username').value.trim(),
        display_name: $('create-display-name').value.trim(),
        password: $('create-password').value,
        password_confirmation: $('create-password-confirmation').value,
      },
      'POST',
    );
    if (!token || generasiAwal !== generation) return;
    $('create-user-form').reset();
    $('user-search').value = '';
    notice(
      'User berhasil ditambahkan. Pemain dapat login menggunakan username dan password tersebut.',
    );
    await muatDaftarAkun();
  } finally {
    $('create-password').value = '';
    $('create-password-confirmation').value = '';
    $('create-user-button').disabled = false;
  }
});
for (const tombol of document.querySelectorAll('[data-menu]'))
  tombol.onclick = handle(() => bukaMenu(tombol.dataset.menu));
$('provider').onchange = providerView;
$('key-source').onchange = () => {
  $('api-key').value = '';
  keySourceView();
};
$('config-form').onsubmit = handle(async () => {
  $('save-config').disabled = true;
  try {
    const data = await request(
      '/api/panel/config',
      {
        provider: $('provider').value,
        endpoint: $('provider').value === 'docker' ? $('endpoint').value : '',
        key_source: $('key-source').value,
        api_key:
          $('provider').value === 'api' && $('key-source').value === 'custom'
            ? $('api-key').value.trim() || null
            : null,
        tunnel_token:
          $('provider').value === 'docker' ? $('tunnel-token').value.trim() || null : null,
        clear_tunnel_token: $('provider').value === 'docker' && $('clear-token').checked,
        model: $('provider').value === 'docker' ? $('local-model').value : null,
      },
      'PUT',
    );
    $('api-key').value = '';
    showConfig(data);
    notice('Konfigurasi tersimpan. Sumber AI yang sedang digunakan terlihat di bawah formulir.');
  } finally {
    $('save-config').disabled = false;
  }
});
$('refresh-checker').onclick = handle(async () => {
  await muatDaftarRuangan();
  await checker();
});
$('checker-room').onchange = handle(() => {
  resetChecker();
  return checker();
});
$('checker-filter').onchange = () => {
  traceFilter = $('checker-filter').value;
  selectedTrace = '';
  renderTraces();
};
$('older-traces').onclick = handle(async () => {
  $('auto-checker').checked = false;
  await checker(true);
});
$('sim-setup').onsubmit = handle(async () => {
  const data = await simRequest(
    '/api/panel/simulasi',
    {
      nama: $('sim-name').value.trim() || 'Pemain',
      jumlah_bot: Number($('sim-count').value) - 1, // semua pemain selain kamu
    },
    'Menyiapkan pertandingan…',
  );
  if (!data) return;
  simTraces = [];
  simSelected = '';
  terimaSim(data, () => null);
  notice('Simulasi dimulai. Kirim chat untuk melihat cara bot membaca dan membalasnya.');
});
$('sim-form').onsubmit = handle(async () => {
  const isi = $('sim-message').value.trim();
  if (!isi || !sim?.bisa_chat || simBusy) return;
  // Chat langsung tampil selama bot berpikir; diganti jejak asli dari server setelah selesai.
  const sementara = {
    id: 'sementara',
    sender: sim.pemain.find((p) => p.manusia)?.nama || 'Kamu',
    message: isi,
    manusia: true,
    stage: 'mengirim',
  };
  simTraces.push(sementara);
  try {
    await simAksi('kirim', 'Bot membaca chat dan berpikir…', isi);
    $('sim-message').value = '';
  } finally {
    simTraces = simTraces.filter((t) => t !== sementara);
    renderSim();
  }
});
$('sim-run').onclick = handle(() => simAksi('jalan', 'Bot melangkah…'));
$('sim-phase').onclick = handle(() => simAksi('fase', 'Menyelesaikan fase…'));
$('history-filter').onsubmit = handle(() => muatRiwayat());
$('more-history').onclick = handle(async () => {
  $('more-history').disabled = true;
  try {
    await muatRiwayat(false);
  } finally {
    $('more-history').disabled = false;
  }
});
$('download').onclick = handle(async () => {
  $('download').disabled = true;
  try {
    await unduhCsv(
      `/api/panel/history.csv?${susunFilterRiwayat()}`,
      'riwayat-chat.csv',
      'Download gagal. Periksa login dan koneksi database.',
    );
    notice('CSV sesuai filter tanggal, ruangan, dan pengirim berhasil diunduh.');
  } finally {
    $('download').disabled = false;
  }
});
$('npc-form').onsubmit = handle(async () => {
  $('save-npc').disabled = true;
  try {
    const data = await request(
      '/api/panel/npc',
      {
        penulis: $('npc-writer').value,
        urutan_penulis: npcChain.filter((item) => item.dipakai).map((item) => item.jalur),
        model_openrouter: $('npc-openrouter-model').value.trim(),
        model_tautan: $('npc-link-model').value,
      },
      'PUT',
    );
    showNpc(data);
    notice(
      'Otak NPC tersimpan. Metode berlaku untuk pertandingan berikutnya; rantai penulis langsung.',
    );
  } finally {
    $('save-npc').disabled = false;
  }
});
// Refresh manual memuat ulang form dari server (editan yang belum disimpan dibuang).
$('refresh-npc').onclick = handle(() => loadNpc());
for (const id of ['npc-writer', 'npc-openrouter-model', 'npc-link-model'])
  for (const type of ['input', 'change'])
    $(id).addEventListener(type, () => {
      npcDirty = true;
      if (id === 'npc-writer') renderChain();
    });
// Hit semua jalur aktif dengan konfigurasi tersimpan; hasil dimuat lewat polling.
// Cek memakai konfigurasi tersimpan, jadi editan harus disimpan dulu.
$('check-writers').onclick = handle(async () => {
  if (npcDirty) {
    notice('Simpan perubahan dulu: cek ulang memakai konfigurasi yang tersimpan.');
    return;
  }
  $('check-writers').disabled = true;
  try {
    showNpc(await request('/api/panel/npc/cek-penulis', {}, 'POST'), { form: false });
    notice('Pengecekan dimulai. Status tiap prioritas diperbarui otomatis.');
  } catch (error) {
    $('check-writers').disabled = false;
    throw error;
  }
});
$('survey-form').onsubmit = handle(async () => {
  $('save-survey').disabled = true;
  try {
    await simpanPertanyaanSurvei(
      {
        code: $('survey-code').value.trim().toLowerCase(),
        prompt: $('survey-prompt').value.trim(),
        kind: $('survey-kind').value,
        scale_min: Number($('survey-min').value),
        scale_max: Number($('survey-max').value),
        label_min: $('survey-label-min').value.trim() || null,
        label_max: $('survey-label-max').value.trim() || null,
        options: $('survey-options')
          .value.split('\n')
          .map((pilihan) => pilihan.trim())
          .filter(Boolean),
        required: $('survey-required').checked,
        active: $('survey-active').checked,
      },
      Number($('survey-id').value) || null,
    );
  } finally {
    $('save-survey').disabled = false;
  }
});
$('cancel-survey').onclick = kosongkanFormSurvei;
// Seret pegangan ⋮⋮ untuk memindah pertanyaan survei; garis hijau di atas atau bawah baris menandai
// tempat jatuh. Pendengar dipasang sekali di <tbody>, jadi berlaku juga untuk baris baru.
// Alur: 1 dragstart catat baris -> 2 dragover tandai tempat -> 3 drop pindahkan -> 4 dragend bersih
let idSurveiDiseret = null,
  tempatJatuhSurvei = null;
// Hapus garis penanda tempat jatuh dari tabel Survei.
function hapusPenandaJatuh() {
  for (const baris of $('survey-rows').querySelectorAll('.jatuh-sebelum, .jatuh-sesudah'))
    baris.classList.remove('jatuh-sebelum', 'jatuh-sesudah');
  tempatJatuhSurvei = null;
}
$('survey-rows').addEventListener('dragstart', (event) => {
  // 1 catat baris; seret yang tidak berawal dari pegangan (mis. teks terpilih) dibiarkan
  const baris = event.target.closest?.('.pegangan-seret')?.closest('tr[data-id]');
  if (!baris) return;
  idSurveiDiseret = Number(baris.dataset.id);
  baris.classList.add('sedang-diseret');
  if (event.dataTransfer) {
    // Firefox baru mulai menyeret bila ada data; gambar seret memakai seluruh baris, bukan ikonnya.
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', baris.dataset.id);
    const kotak = baris.getBoundingClientRect();
    event.dataTransfer.setDragImage(baris, event.clientX - kotak.left, event.clientY - kotak.top);
  }
});
$('survey-rows').addEventListener('dragover', (event) => {
  // 2 tandai tempat jatuh: separuh atas baris = sebelum, separuh bawah = sesudah
  const baris = event.target.closest?.('tr[data-id]');
  if (idSurveiDiseret === null || !baris) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
  const id = Number(baris.dataset.id);
  const kotak = baris.getBoundingClientRect();
  const sesudah = event.clientY > kotak.top + kotak.height / 2;
  if (tempatJatuhSurvei?.id === id && tempatJatuhSurvei.sesudah === sesudah) return;
  hapusPenandaJatuh();
  // Di atas baris yang sedang diseret: urutan tidak berubah, jadi tidak ada penanda.
  if (id === idSurveiDiseret) return;
  baris.classList.add(sesudah ? 'jatuh-sesudah' : 'jatuh-sebelum');
  tempatJatuhSurvei = { id, sesudah };
});
$('survey-rows').addEventListener('dragleave', (event) => {
  if (!$('survey-rows').contains(event.relatedTarget)) hapusPenandaJatuh();
});
$('survey-rows').addEventListener('drop', (event) => {
  // 3 pindahkan; indeks tujuan dihitung dari urutan tanpa baris yang diseret
  if (idSurveiDiseret === null) return;
  event.preventDefault();
  const id = idSurveiDiseret;
  const tempat = tempatJatuhSurvei;
  hapusPenandaJatuh();
  if (!tempat) return;
  const tanpaYangDiseret = urutanSurvei.filter((lain) => lain !== id);
  pindahkanPertanyaanSurvei(id, tanpaYangDiseret.indexOf(tempat.id) + (tempat.sesudah ? 1 : 0));
});
$('survey-rows').addEventListener('dragend', () => {
  // 4 bersihkan, juga saat seret dibatalkan (Esc atau dilepas di luar tabel)
  idSurveiDiseret = null;
  hapusPenandaJatuh();
  for (const baris of $('survey-rows').querySelectorAll('.sedang-diseret'))
    baris.classList.remove('sedang-diseret');
});
// Alt+↑/↓ saat fokus di dalam baris (tombol ▲▼, Edit, dan lainnya) memindah pertanyaan itu.
$('survey-rows').addEventListener('keydown', (event) => {
  if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
  const baris = event.target.closest?.('tr[data-id]');
  if (!baris) return;
  event.preventDefault();
  const id = Number(baris.dataset.id);
  pindahkanPertanyaanSurvei(id, urutanSurvei.indexOf(id) + (event.key === 'ArrowUp' ? -1 : 1));
});
$('survey-clean').onclick = handle(async () => {
  if ($('survey-clean-confirm').value.trim() !== 'BERSIHKAN')
    throw new Error('Ketik BERSIHKAN dengan tepat untuk menghapus semua jawaban survei.');
  const hasil = await request('/api/panel/survey/responses', undefined, 'DELETE');
  $('survey-clean-confirm').value = '';
  $('survey-clean-box').open = false;
  notice(`${hasil.deleted} jawaban survei dihapus.`);
  await muatSurvei();
});
$('download-survey').onclick = handle(async () => {
  $('download-survey').disabled = true;
  try {
    await unduhCsv(
      '/api/panel/survey/responses.csv',
      'survei-silent-terror.csv',
      'Download gagal. Periksa login dan migrasi V7.',
    );
    notice('Jawaban survei berhasil diunduh.');
  } finally {
    $('download-survey').disabled = false;
  }
});
$('logout').onclick = handle(async () => {
  $('logout').disabled = true;
  try {
    await request('/api/panel/logout', null, 'POST');
    clearSession();
    notice('Kamu sudah keluar dari panel.');
  } finally {
    $('logout').disabled = false;
  }
});
setInterval(() => {
  if (token && menu === 'checker' && $('auto-checker').checked && !document.hidden)
    checker().catch((error) => notice(error.message));
}, 5000);
// Data live Checker tiap detik (langkah berjalan, kondisi bot, antrean) dan detak waktu berjalan tiap 250 ms.
setInterval(() => {
  if (token && menu === 'checker' && $('auto-checker').checked && !document.hidden) muatLive();
}, 1000);
setInterval(() => {
  if (menu === 'checker' && !document.hidden) detakLive();
}, 250);

// PILIHAN KUSTOM: dropdown bawaan browser diganti tombol + daftar bergaya panel. <select> asli tetap ada dan
// disembunyikan, jadi nilai form, event change, dan kode lain yang membaca/menyetel .value tidak berubah.
// Daftar dibangun ulang saat opsi, nilai, atau status nonaktif berubah; keyboard: panah, Enter/Spasi, Esc, Tab.
const PILIH_PROTO = Object.getOwnPropertyDescriptors(HTMLSelectElement.prototype);
function pasangPilihanKustom(select) {
  if (select.dataset.kustom) return;
  select.dataset.kustom = '1';
  const wadah = node('div', undefined, 'pilih');
  const tombol = node('button', undefined, 'pilih-tombol');
  const daftar = node('ul', undefined, 'pilih-daftar');
  tombol.type = 'button';
  tombol.setAttribute('aria-haspopup', 'listbox');
  tombol.setAttribute('aria-expanded', 'false');
  daftar.setAttribute('role', 'listbox');
  daftar.hidden = true;
  const label = select.closest('label');
  // Judul untuk pembaca layar: teks langsung di dalam <label>, tanpa elemen anaknya.
  const judul = label
    ? [...label.childNodes]
        .filter((simpul) => simpul.nodeType === 3)
        .map((simpul) => simpul.textContent)
        .join(' ')
        .trim()
    : '';
  if (judul) daftar.setAttribute('aria-label', judul);
  select.replaceWith(wadah);
  wadah.append(select, tombol, daftar);
  select.classList.add('pilih-asli');
  select.tabIndex = -1;
  select.setAttribute('aria-hidden', 'true');
  select.addEventListener('focus', () => tombol.focus());

  const sinkron = () => {
    const pilihan = select.options[select.selectedIndex];
    tombol.textContent = pilihan ? pilihan.text : '—';
    tombol.setAttribute('aria-label', `${judul ? `${judul}: ` : ''}${tombol.textContent}`);
    tombol.disabled = select.disabled;
    daftar.replaceChildren(
      ...[...select.options].map((opsi) => {
        const itemOpsi = node('li', opsi.text, 'pilih-opsi');
        itemOpsi.setAttribute('role', 'option');
        itemOpsi.setAttribute('aria-selected', String(opsi.selected));
        if (opsi.disabled) itemOpsi.setAttribute('aria-disabled', 'true');
        itemOpsi.tabIndex = -1;
        itemOpsi.dataset.value = opsi.value;
        return itemOpsi;
      }),
    );
  };
  const tutup = (fokus = true) => {
    if (daftar.hidden) return;
    daftar.hidden = true;
    tombol.setAttribute('aria-expanded', 'false');
    if (fokus) tombol.focus();
  };
  const buka = () => {
    if (select.disabled) return;
    for (const lain of document.querySelectorAll('.pilih-daftar:not([hidden])')) lain.hidden = true;
    daftar.hidden = false;
    tombol.setAttribute('aria-expanded', 'true');
    (daftar.querySelector('[aria-selected="true"]') || daftar.firstElementChild)?.focus();
  };
  const pilih = (itemOpsi) => {
    if (!itemOpsi || itemOpsi.getAttribute('aria-disabled')) return;
    const berubah = select.value !== itemOpsi.dataset.value;
    select.value = itemOpsi.dataset.value;
    tutup();
    if (berubah) {
      select.dispatchEvent(new Event('input', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  };
  tombol.onclick = () => (daftar.hidden ? buka() : tutup());
  tombol.onkeydown = (event) => {
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      buka();
    }
  };
  daftar.onclick = (event) => pilih(event.target.closest('.pilih-opsi'));
  daftar.onkeydown = (event) => {
    const semuaOpsi = [...daftar.children];
    const posisi = semuaOpsi.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const langkah = event.key === 'ArrowDown' ? 1 : -1;
      semuaOpsi[Math.max(0, Math.min(semuaOpsi.length - 1, posisi + langkah))]?.focus();
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      pilih(semuaOpsi[posisi]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      tutup();
    } else if (event.key === 'Tab') {
      tutup(false);
    }
  };
  wadah.addEventListener('focusout', (event) => {
    if (!wadah.contains(event.relatedTarget)) tutup(false);
  });
  // Nilai yang disetel lewat kode (select.value = …) juga memperbarui tombol.
  for (const nama of ['value', 'selectedIndex']) {
    Object.defineProperty(select, nama, {
      configurable: true,
      get: () => PILIH_PROTO[nama].get.call(select),
      set: (nilai) => {
        PILIH_PROTO[nama].set.call(select, nilai);
        sinkron();
      },
    });
  }
  select.addEventListener('change', sinkron);
  new MutationObserver(sinkron).observe(select, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['disabled'],
  });
  sinkron();
}
document.querySelectorAll('select').forEach(pasangPilihanKustom);
// <select> yang dibuat belakangan ikut diganti.
new MutationObserver((daftarPerubahan) => {
  for (const perubahan of daftarPerubahan)
    for (const simpul of perubahan.addedNodes)
      if (simpul.nodeType === 1)
        (simpul.matches('select') ? [simpul] : simpul.querySelectorAll('select')).forEach(
          pasangPilihanKustom,
        );
}).observe(document.body, { childList: true, subtree: true });
document.addEventListener('click', (event) => {
  for (const daftar of document.querySelectorAll('.pilih-daftar:not([hidden])'))
    if (!daftar.parentElement.contains(event.target)) {
      daftar.hidden = true;
      daftar.previousElementSibling.setAttribute('aria-expanded', 'false');
    }
});
