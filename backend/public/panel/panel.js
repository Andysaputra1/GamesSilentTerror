'use strict';
// Ambil elemen panel berdasarkan ID.
const $ = (id) => document.getElementById(id);
let historyVersion = 0;
let usersAfter = 0,
  usersVersion = 0,
  selectedUser = null,
  userSaving = false;
let keyAvailability = { default: false, custom: false };
let token = '',
  menu = 'ai',
  historyAfter = 0,
  traceBefore = null,
  traces = [],
  selectedTrace = '',
  busy = false,
  generation = 0;
// Tampilkan pesan status sebagai teks agar isi dinamis tidak dianggap HTML.
const notice = (text) => {
  $('notice').textContent = text;
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => {
    $('notice').textContent = '';
  }, 8000);
};
// Kirim request panel dan hapus sesi lokal jika server menyatakan token tidak valid.
async function request(path, body, method = 'GET') {
  const epoch = generation;
  const response = await fetch(path, {
    method,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    // Uji AI dan cek rantai penulis menunggu provider; simulasi menunggu otak + LLM beberapa bot.
    signal: AbortSignal.timeout(
      /\/simulasi/.test(path) ? 180000 : /\/(test-ai|cek-penulis)$/.test(path) ? 60000 : 15000,
    ),
  });
  if (epoch !== generation) throw new Error('Sesi telah berubah. Respons lama diabaikan.');
  if (response.status === 204) return {};
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && token) clearSession();
    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : 'Permintaan gagal. Periksa isian dan coba lagi.',
    );
  }
  return data;
}
// Buang token, rahasia form, dan data panel; abaikan respons dari sesi sebelumnya.
function clearSession() {
  $('create-user-form').reset();
  usersVersion++;
  $('user-rows').replaceChildren();
  closeUserEditor();
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
  $('probe-result').replaceChildren();
  $('ai-status').textContent = 'Belum diperiksa.';
  $('probe-progress').textContent = '';
  $('npc-status').replaceChildren();
  $('survey-rows').replaceChildren();
  $('survey-method-rows').replaceChildren();
  resetSurveyForm();
  historyVersion++;
  traces = [];
}

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
  $('probe-result').replaceChildren();
  $('probe-result').classList.add('empty-state');
  $('probe-result').textContent = 'Jalankan pengujian untuk memeriksa konfigurasi ini.';
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
        ? ' Key tersedia; koneksi belum diperiksa.'
        : ' Key belum tersedia; AI belum siap digunakan.');
  $('config-draft').textContent = 'Konfigurasi ini berlaku untuk pesan AI berikutnya.';
  $('ai-status').textContent = 'Belum diperiksa untuk konfigurasi ini.';
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
async function loadRooms() {
  const rooms = [];
  let after = 0;
  for (;;) {
    const data = await request(`/api/panel/rooms?after_id=${after}`);
    rooms.push(...data.rooms);
    if (!data.has_more) break;
    after = data.next_after_id;
  }
  // API berhalaman urut id naik; pilihan ditampilkan dari ruangan terbaru.
  rooms.sort((a, b) => b.id - a.id);
  for (const id of ['checker-room', 'history-room']) {
    const select = $(id),
      current = select.value;
    select.replaceChildren(
      new Option(id === 'history-room' ? 'Semua ruangan' : 'Pilih ruangan', ''),
    );
    for (const room of rooms)
      select.add(
        new Option(
          `${room.room_code} | ${tanggal(room.created_at)} | ${room.message_count} pesan${room.live ? ' | aktif' : ''}`,
          room.room_code,
        ),
      );
    select.value = current;
  }
  return rooms;
}
// CHECKER ROOM: ringkasan room, linimasa jejak per bot, dan kartu penjelasan keputusan otak.
// Semua isi dari server ditulis lewat textContent/Option, tidak pernah sebagai HTML.
let checkerRoom = null,
  traceFilter = '', // '' semua jejak | 'bot' semua keputusan bot | 'bot:NAMA'
  detailTab = 'proses',
  renderedDetail = ''; // jejak yang sedang tampil: tidak dirender ulang tiap auto-refresh
const traceDetails = new Map(); // id → jejak lengkap (dengan penjelasan), dimuat saat dibuka
const METODE_LABEL = {
  fuzzy: 'Fuzzy Mamdani',
  utility: 'Utility AI (IAUS)',
  bt: 'Behavior Tree',
  llm: 'LLM (mode lama)',
};
// Singkatan metode, sama dengan label nama bot di game.
const METODE_SINGKAT = { fuzzy: 'FL', utility: 'UA', bt: 'BT', llm: 'LLM' };
const METODE_CARA = {
  fuzzy:
    'Setiap nilai 0–1 difuzzifikasi menjadi rendah/sedang/tinggi. Aturan JIKA–MAKA menyala dengan kekuatan min(derajat input), keluaran digabung (max) lalu didefuzzifikasi centroid menjadi 0–100 dan dibandingkan ambang.',
  utility:
    'Setiap pilihan diberi pertimbangan 0–1 lewat kurva. Utilitas = bobot × Π(n + (1 − n)(1 − 1/k)n) (kompensasi IAUS, k = jumlah pertimbangan). Pilihan terbesar dipakai bila melewati ambang atau utilitas diam.',
  bt: 'Pohon dibaca dari atas. Selector mencoba cabang berurutan dan berhenti di cabang pertama yang berhasil; Sequence berhenti di syarat pertama yang gagal. Aksi pada cabang yang berhasil menjadi keputusan.',
  llm: 'Satu prompt LLM memutuskan aksi dan pesan sekaligus; tidak ada penalaran metode.',
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
  llm: 'LLM (lolos aturan dan IndoBERT)',
  templat: 'Templat (lolos aturan dan IndoBERT)',
  templat_cadangan: 'Templat cadangan (tidak ada varian yang lolos IndoBERT)',
};
// Arti parameter: dipakai legenda dan keterangan judul kolom tabel.
const PARAMETER = {
  kecurigaan: 'Seberapa kuat pemain dianggap Hitman (0–1), hasil akhir metode.',
  tekanan:
    'Tuduhan dan vote pemain lain ke pemain ini, dibagi jumlah pemain lain yang hidup; meluruh per ronde.',
  dukungan: 'Pembelaan pemain lain, termasuk klaim bersih dari pengaku Stalker.',
  inkonsistensi: 'Berganti sikap ke target yang sama, atau vote tidak sesuai ucapannya.',
  pengalihan: 'Setelah dituduh, malah menuduh orang lain alih-alih membela diri.',
  dituduh_korban: 'Pernah dituduh pemain yang kemudian di-Gag atau disandera (jejak aksi Hitman).',
  dorong_salah_eksekusi:
    'Ikut mendorong eksekusi warga: vote, ikut menuduh, atau penuduh pertama, dikali kepastian korban warga (1 bila game berlanjut di room satu Hitman atau jumlah Hitman yang diumumkan tetap; selain itu 1 − k/(N − 1)). Tidak dihitung bila korban diketahui Hitman.',
  serang_bersih: 'Menuduh atau vote pemain yang pasti bersih menurut bot.',
  klaim: 'Klaim role bermasalah: bentrok, dibantah, atau hasil Peek palsu.',
  p_sandera:
    'Dugaan pemain sedang disandera (tidak aktif sejak malam); tinggi berarti bukan Hitman.',
  diam: 'Belum bicara di ronde ini (0–1 menurut waktu yang lewat).',
  urgensi: 'Makin sedikit warga bebas, makin mendesak (0–1).',
  porsi_fase: 'Bagian fase yang sudah berjalan (0–1).',
  keunggulan: 'Selisih kecurigaan tersangka teratas dari tersangka kedua (0–1).',
  keyakinan: 'Fuzzy vote: keyakinan pada kandidat teratas (0–1).',
  kesiapan: 'Fuzzy vote: kesiapan mengunci vote (0–100) dari keyakinan dan urgensi.',
  prioritas: 'Keluaran fuzzy 0–100 untuk tindakan chat atau aksi rahasia.',
  utilitas: 'Skor Utility AI 0–1. Nilai pertimbangan sudah melalui kurva.',
  poin: 'Behavior Tree: jumlah poin bendera merah yang aktif; kecurigaan = poin / 5.',
  bendera: 'Behavior Tree: bendera merah aktif bila nilai bukti ≥ ambangnya.',
  ancaman: 'Hitman: seberapa berbahaya pemain (menuduh, berpengaruh, mengaku role penting).',
  kambing_hitam: 'Hitman: seberapa mudah pemain dijadikan tersangka oleh warga.',
  terancam: 'Spy: seberapa mungkin pemain diincar Hitman malam ini.',
  kepercayaan: 'Seberapa bisa dipercaya (1 = pasti bersih).',
};
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
function traceBot(trace) {
  return trace.ringkas?.bot?.nama || (trace.provider?.startsWith('otak:') ? trace.sender : null);
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
function lastDecision(nama) {
  const trace = traces.find((t) => traceBot(t) === nama);
  if (!trace) return '—';
  return trace.ringkas?.keputusan?.length ? trace.ringkas.keputusan.join(' · ') : trace.message;
}
// Ringkasan room: status pertandingan, komposisi role, dan tabel bot (klik nama untuk memfilter).
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
  const table = dataTable({
    kolom: ['bot', 'role', 'metode', 'persona', 'status', 'keputusan terakhir'],
    baris: room.bot.map((b) => [
      b.nama,
      ROLE_LABEL[b.role] || b.role,
      METODE_LABEL[b.metode] || b.metode,
      b.persona,
      b.status,
      lastDecision(b.nama),
    ]),
  });
  // Nama bot menjadi tombol filter linimasa.
  table.querySelectorAll('tbody tr').forEach((tr, index) => {
    const nama = room.bot[index].nama;
    const button = node('button', nama, 'room-bot');
    button.type = 'button';
    button.title = `Tampilkan jejak ${nama} saja`;
    button.onclick = () => {
      traceFilter = `bot:${nama}`;
      selectedTrace = '';
      renderTraces();
    };
    tr.cells[0].replaceChildren(button);
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
// langkah bot tanpa chat (vote, aksi, diam) menjadi baris kecil; pengumuman engine menjadi baris sistem.
// Klik satu item untuk melihat prosesnya. Chat manusia membawa bacaan NLU IndoBERT-nya.
const isSistem = (t) => t.stage === 'sistem';
const isHuman = (t) => Boolean(t.manusia || (!t.provider && !t.ringkas && !isSistem(t)));
function nluTeks(nlu) {
  if (!nlu) return '—';
  const target = (nlu.target || []).map(
    (t) => `${t.pemain} (${t.relasi}${t.prob == null ? '' : ` ${teks(t.prob)}`})`,
  );
  return `${nlu.intent} ${teks(nlu.confidence)}${target.length ? ` · target ${target.join(', ')}` : ''}`;
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
function chatItem(trace, selected, onSelect) {
  if (isSistem(trace)) return node('p', trace.message, 'chat-system');
  const r = trace.ringkas,
    bot = r?.bot,
    human = isHuman(trace),
    bubble = human || r?.nlg === 'terkirim';
  const kind = human ? 'chat-human' : bubble ? 'chat-bot' : 'chat-step';
  const b = node('button', undefined, `trace chat-item ${kind}${selected ? ' selected' : ''}`);
  b.type = 'button';
  const head = node('span', undefined, 'trace-head');
  head.append(node('strong', bot?.nama || trace.sender));
  if (human) head.append(chip('manusia', 'status-muted'));
  if (bot?.metode) head.append(chip(METODE_SINGKAT[bot.metode] || bot.metode, 'status-good'));
  if (bot?.role) head.append(chip(ROLE_LABEL[bot.role] || bot.role, roleClass(bot.role)));
  b.append(head);
  if (bubble) b.append(node('span', trace.message, 'chat-text'));
  const info = [];
  if (human && trace.nlu) info.push(`NLU: ${nluTeks(trace.nlu)}`);
  if (r?.nlg === 'ditunda' && r.usulan) info.push(`akan ditulis: “${r.usulan}”`);
  if (r) {
    // Chat sudah tampil sebagai gelembung; sisanya vote/aksi rahasia langkah yang sama.
    const lain = (r.keputusan || []).filter((k) => !bubble || !k.startsWith('chat '));
    if (lain.length) info.push(lain.join(' · '));
    else if (!bubble) info.push('diam: tidak chat, vote, atau beraksi');
  } else if (!human) info.push(`${trace.message} · ${trace.stage}`);
  const meta = [
    bot?.ronde && `R${bot.ronde} ${FASE_LABEL[bot.fase] || bot.fase || ''}`.trim(),
    waktu(trace.created_at),
    typeof trace.duration_ms === 'number' && `proses ${duration(trace.duration_ms)}`,
    r?.ditolak && 'ditolak engine',
    r?.nlg === 'ditunda' && 'chat ditunda',
  ].filter(Boolean);
  for (const line of info) b.append(node('small', line, 'chat-info'));
  b.append(node('small', meta.join(' · '), 'chat-meta'));
  b.onclick = () => onSelect(trace.id);
  return b;
}
// Render ulang chat; tetap menempel di bawah bila sebelumnya sudah di bawah (seperti chat game).
function renderChat(box, list, selectedId, onSelect) {
  const bawah = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...list.map((t) => chatItem(t, t.id === selectedId, onSelect)));
  if (bawah) box.scrollTop = box.scrollHeight;
}
function selectTrace(id) {
  selectedTrace = id;
  renderTraces();
}
// Render chat room (sesuai filter) dan detail item terpilih; default item terbaru.
function renderTraces() {
  renderFilter();
  const box = $('traces');
  const list = visibleTraces();
  if (!list.length) {
    box.textContent = traces.length
      ? 'Tidak ada jejak untuk filter ini.'
      : 'Belum ada jejak AI di room ini.';
    $('trace-detail').textContent = 'Belum ada data.';
    renderedDetail = '';
    return;
  }
  const active = list.find((t) => t.id === selectedTrace) || list[0];
  selectedTrace = active.id;
  renderChat(box, [...list].reverse(), active.id, selectTrace);
  showDetail(active).catch((error) => notice(error.message));
}
// Penjelasan langkah sebelumnya dari bot yang sama (untuk kolom perubahan), bila sudah dimuat.
function sebelumnya(trace, urut, ambil) {
  const nama = traceBot(trace),
    i = urut.findIndex((t) => t.id === trace.id);
  for (let j = i - 1; j >= 0; j--) if (traceBot(urut[j]) === nama) return ambil(urut[j]);
  return null;
}
// Jejak otak bot dimuat lengkap sekali (cache); chat manusia memakai kartu NLU; jejak lain laporan lama.
async function showDetail(trace) {
  const container = $('trace-detail');
  const key = `${trace.id}|${trace.stage}|${trace.duration_ms}|${traces.length}`;
  if (renderedDetail === key) return;
  renderedDetail = key;
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
// Chat manusia: langkah server, bacaan NLU IndoBERT (intent, target), dan reaksi bot sesudahnya.
function renderHuman(container, trace, urut, onSelect) {
  container.replaceChildren();
  container.classList.remove('empty-state');
  const head = node('div', undefined, 'decision-head');
  head.append(node('strong', trace.sender), chip('manusia', 'status-muted'));
  head.append(node('span', waktu(trace.created_at), 'room-meta'));
  const t = trace.timings || {},
    n = trace.nlu;
  const steps = [['Diterima server dan izin chat diperiksa', null]];
  if (t.persistence_ms !== undefined) steps.push(['Disimpan ke database', t.persistence_ms]);
  if (t.broadcast_ms !== undefined) steps.push(['Dikirim ke semua pemain di room', t.broadcast_ms]);
  const sasaran = n?.target?.length
    ? `target ${n.target.map((x) => x.pemain).join(', ')}`
    : 'tanpa target';
  steps.push([
    'NLU IndoBERT membaca maksud (intent) dan sasaran (target)',
    t.nlu_ms ?? n?.ms ?? null,
    n
      ? `Hasil: intent ${n.intent} (keyakinan ${teks(n.confidence)}) · ${sasaran}`
      : 'Belum dibaca: otak NPC belum siap saat pesan masuk, atau pesan dari versi lama.',
  ]);
  container.append(
    head,
    node('pre', trace.message || '', 'output'),
    node('h4', 'Langkah proses pesan', 'report-title'),
    processSteps(steps),
  );
  if (n) {
    container.append(
      node('h4', 'Bacaan NLU', 'report-title'),
      keyValues([
        ['Intent', `${n.intent} (keyakinan ${teks(n.confidence)})`],
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
  }
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
        keputusan = x.ringkas.keputusan?.length ? x.ringkas.keputusan.join(' · ') : 'diam';
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
// Kartu keputusan bertab: Proses · Keputusan · Parameter · Penalaran metode · NLG · Teknis.
// lama: penjelasan langkah sebelumnya bot yang sama (kolom perubahan di tab Proses), bila ada.
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
  const meta = [
    bot.persona && `persona ${bot.persona}`,
    bot.ronde && `ronde ${bot.ronde}`,
    FASE_LABEL[bot.fase] || bot.fase,
    bot.langkah && `langkah ${bot.langkah}`,
    waktu(trace.created_at),
  ].filter(Boolean);
  head.append(node('span', meta.join(' · '), 'room-meta'));
  container.append(head);
  if (p.catatan?.length) container.append(node('p', p.catatan.join(' '), 'hint status-pending'));
  const tabs = [
    ['proses', 'Proses', () => prosesTab(trace, p, lama)],
    ['keputusan', 'Keputusan', () => decisionTab(p)],
    ['parameter', 'Parameter', () => parameterTab(p)],
    ['penalaran', `Penalaran ${METODE_LABEL[bot.metode] || ''}`.trim(), () => reasoningTab(p)],
    ['nlg', 'NLG', () => nlgTab(p)],
    [
      'teknis',
      'Teknis',
      () => {
        const box = node('div', undefined, 'report');
        renderReport(box, trace);
        return box;
      },
    ],
  ];
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
  const intent = chat && r.intent ? ` (${r.intent}${r.klaim ? ', mengaku role' : ''})` : '';
  const skor = typeof r.skor === 'number' ? ` · skor ${teks(r.skor)}` : '';
  return `${r.aksi}${r.target ? ` → ${r.target}` : ''}${intent}${skor}`;
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
          ['Aturan + validasi IndoBERT + templat', duration(t.validasi_ms)],
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
        'Rincian hitungan ada di tab Parameter dan Penalaran.',
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
// Jalur Behavior Tree: syarat/aksi yang dievaluasi berurutan dengan status berhasil/gagal.
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
        ['Intent', m.intent],
        ['Mengaku role', m.klaim],
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
      ['Lolos validasi IndoBERT', n.lolos_nlu ?? 'tidak divalidasi'],
      ['Intent terbaca', n.nlu ? `${n.nlu.intent_prediksi} (${teks(n.nlu.confidence)})` : null],
      ['Target terbaca', n.nlu?.target_prediksi?.map(([nama, relasi]) => `${nama}: ${relasi}`)],
      ['Pelanggaran aturan', n.pelanggaran],
      ['Percobaan LLM', n.percobaan_llm],
      ['Varian templat dicoba', n.percobaan_templat],
      ['Waktu tulis (dtk)', n.detik],
    ]),
    masukanNlg(n.masukan),
  );
  return box;
}
// Muat jejak terbaru/lama; tolak respons basi setelah logout atau pergantian ruangan.
async function checker(older = false) {
  if (busy) return;
  const code = $('checker-room').value;
  if (!code) {
    traces = [];
    checkerRoom = null;
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
    }
    renderRoomSummary();
    renderTraces();
  } finally {
    busy = false;
  }
}
// Pergantian room atau sesi: buang filter, cache penjelasan, dan tampilan detail lama.
function resetChecker() {
  checkerRoom = null;
  traceFilter = '';
  selectedTrace = '';
  renderedDetail = '';
  traceDetails.clear();
  $('room-summary').replaceChildren();
  $('room-summary').hidden = true;
}
// FLOWCHART PROSES AI (menu Simulasi): seluruh jalur AI dari chat pemain sampai output bot.
// tahap = nama tahap yang dilaporkan server saat simulasi berjalan, untuk menandai posisi tiap bot.
// metode = kotak cabang metode (dipakai bot dengan metode itu). Teks dibuat singkat dan mudah dipahami.
const ALUR_AI = {
  input: {
    judul: 'Chat pemain masuk',
    kode: 'Simulasi.kirim · SocketGameController._send_chat · Match.can_chat',
    tujuan: 'Menerima kalimat pemain pada fase yang boleh chat.',
    proses:
      'Server memeriksa izin chat (siang/Tribunal, tidak dibungkam), lalu pesan masuk ke chat pertandingan.',
    keluaran: 'Pesan {pengirim, teks} di daftar chat room.',
    alasan: 'Bot membaca chat dari daftar yang sama dengan yang dilihat pemain.',
  },
  nlu_pesan: {
    tahap: ['nlu_pesan'],
    judul: 'NLU IndoBERT membaca chat',
    kode: 'BrainRuntime.baca_chat → anotasi_chat',
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
    kode: 'Ingatan.sinkron_snapshot (+ anotasi_chat untuk chat baru)',
    tujuan: 'Menyamakan memori bot dengan keadaan permainan yang ia lihat.',
    proses:
      'Snapshot privat bot dibaca: chat baru (diberi NLU), vote, eksekusi, hasil Peek, Gag, fase, dan waktu.',
    keluaran: 'view: ronde, fase, pemain hidup, izin chat/vote/aksi milik bot.',
    alasan: 'Bot hanya tahu yang boleh dilihat role-nya; role lawan tidak pernah bocor.',
  },
  bukti: {
    judul: 'Menghitung bukti tiap pemain',
    kode: 'hitung_bukti · pengetahuan_peran · fitur_hitman / fitur_lindung',
    tujuan: 'Mengubah riwayat permainan menjadi angka 0–1 per pemain.',
    proses:
      'Dari chat ber-NLU dan vote dihitung tekanan, dukungan, inkonsistensi, pengalihan, klaim, diam, dll. Hitman juga menilai ancaman; Spy menilai siapa yang perlu di-Guard.',
    keluaran: 'Tabel bukti (lihat tab Parameter).',
    alasan: 'Ketiga metode memakai bukti yang sama, jadi beda perilaku murni dari cara menalar.',
  },
  fl: {
    metode: 'fuzzy',
    judul: 'FL · Fuzzy Mamdani',
    kode: 'otak_fuzzy.putuskan',
    tujuan: 'Menalar dengan aturan bahasa manusia (rendah/sedang/tinggi).',
    proses:
      'Bukti → sistem fuzzy bertingkat → kecurigaan; tiap pilihan chat/vote/aksi diberi prioritas 0–100.',
    keluaran: 'Kecurigaan per pemain dan prioritas tiap pilihan.',
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
    kode: 'fuzzy(nama, a, b) · nilai_kecurigaan (HIERARKI)',
    tujuan: 'Menggabungkan aturan menjadi satu angka.',
    proses:
      'Keluaran aturan digabung (max), lalu centroid → 0–100. Bertingkat: sosial, perilaku, jejak, pribadi, ucapan, bukti_keras → kecurigaan.',
    keluaran: 'Kecurigaan 0–1 dan prioritas 0–100.',
    alasan: 'Centroid membuat nilai berubah halus saat bukti berubah.',
  },
  fl_4: {
    metode: 'fuzzy',
    judul: 'Bandingkan ambang',
    kode: 'keputusan_chat · keputusan_vote · keputusan_aksi',
    tujuan: 'Memutuskan bertindak atau menunggu.',
    proses:
      'Prioritas terbaik dibandingkan AMBANG_CHAT, VOTE_LANGSUNG/AMBANG_VOTE, dan AMBANG_GAG.',
    keluaran: 'Rencana chat, vote, dan aksi rahasia.',
    alasan: 'Bot tidak menuduh tanpa bukti yang cukup.',
  },
  ua: {
    metode: 'utility',
    judul: 'UA · Utility AI (IAUS)',
    kode: 'otak_utility.putuskan',
    tujuan: 'Memberi skor kegunaan setiap pilihan lalu memilih yang terbaik.',
    proses: 'Bukti → kurva → skor IAUS per pilihan; kecurigaan dari noisy-OR.',
    keluaran: 'Utilitas 0–1 tiap pilihan dan kecurigaan per pemain.',
    alasan: 'Mudah menimbang banyak faktor sekaligus, termasuk pilihan untuk diam.',
  },
  ua_1: {
    metode: 'utility',
    judul: 'Kurva pertimbangan',
    kode: 'kurva_linear · kurva_logistik',
    tujuan: 'Bukti menjadi nilai 0–1 yang terasa wajar.',
    proses: 'Tiap pertimbangan (kecurigaan, urgensi, porsi fase, ...) dilewatkan kurva.',
    keluaran: 'Nilai pertimbangan 0–1.',
    alasan: 'Kurva logistik mengabaikan nilai kecil dan cepat menaikkan nilai tinggi.',
  },
  ua_2: {
    metode: 'utility',
    judul: 'Kecurigaan noisy-OR',
    kode: 'nilai_kecurigaan (BOBOT_BUKTI)',
    tujuan: 'Menggabungkan banyak bukti lemah.',
    proses: 'kecurigaan = 1 − Π(1 − bobot × bukti), lalu dikali (1 − p_sandera).',
    keluaran: 'Kecurigaan 0–1 per pemain.',
    alasan: 'Beberapa bukti kecil bersama tetap meyakinkan.',
  },
  ua_3: {
    metode: 'utility',
    judul: 'Skor IAUS',
    kode: 'skor_iaus · _nilai_calon',
    tujuan: 'Memberi skor tiap pilihan.',
    proses:
      'Utilitas = bobot × hasil kali pertimbangan, dengan kompensasi jumlah pertimbangan (k).',
    keluaran: 'Utilitas 0–1 per pilihan chat/vote/aksi.',
    alasan:
      'Satu pertimbangan nol membatalkan pilihan; kompensasi menjaga pilihan dengan banyak pertimbangan tetap adil.',
  },
  ua_4: {
    metode: 'utility',
    judul: 'Pilih utilitas tertinggi',
    kode: 'keputusan_chat · keputusan_vote · keputusan_aksi',
    tujuan: 'Memilih aksi terbaik.',
    proses:
      'Pilihan tertinggi dipakai bila melebihi UTILITAS_TUNGGU (diam) atau UTILITAS_VOTE_LANGSUNG.',
    keluaran: 'Rencana chat, vote, dan aksi rahasia.',
    alasan: 'Diam juga pilihan; bot bergerak hanya bila lebih berguna daripada diam.',
  },
  bt: {
    metode: 'bt',
    judul: 'BT · Behavior Tree',
    kode: 'otak_bt.putuskan',
    tujuan: 'Memilih perilaku lewat pohon prioritas.',
    proses: 'Bukti → poin bendera merah → pohon Selector/Sequence ditelusuri dari atas.',
    keluaran: 'Cabang yang berhasil dan rencananya.',
    alasan: 'Urutan prioritas perilaku terlihat jelas dan mudah diuji.',
  },
  bt_1: {
    metode: 'bt',
    judul: 'Bendera merah',
    kode: 'nilai_kecurigaan (BENDERA)',
    tujuan: 'Bukti menjadi poin.',
    proses: 'Bendera aktif bila nilai bukti ≥ ambangnya; poin dijumlah, kecurigaan = poin / 5.',
    keluaran: 'Poin dan kecurigaan per pemain.',
    alasan: 'Aturan ya/tidak yang jelas.',
  },
  bt_2: {
    metode: 'bt',
    judul: 'Papan (blackboard)',
    kode: '_papan(ctx)',
    tujuan: 'Menyiapkan data untuk pohon.',
    proses: 'Tersangka, poin, izin chat, fase, dan kandidat dimasukkan ke papan.',
    keluaran: 'Papan yang dibaca node Kondisi dan Aksi.',
    alasan: 'Node pohon tetap kecil dan bisa dipakai ulang.',
  },
  bt_3: {
    metode: 'bt',
    judul: 'Telusuri pohon',
    kode: 'Selector · Sequence · Kondisi',
    tujuan: 'Mencari cabang yang berlaku.',
    proses:
      'Selector mencoba cabang dari atas sampai satu SUKSES; Sequence berhenti di syarat yang GAGAL.',
    keluaran: 'Jalur node SUKSES/GAGAL (tab Penalaran).',
    alasan: 'Prioritas perilaku terlihat dari urutan cabang.',
  },
  bt_4: {
    metode: 'bt',
    judul: 'Aksi cabang terpilih',
    kode: 'Aksi (_a_tuduh, _a_vote, _a_aksi)',
    tujuan: 'Menjalankan aksi di cabang yang berhasil.',
    proses: 'Node Aksi membuat rencana chat, vote, atau aksi rahasia.',
    keluaran: 'Rencana chat, vote, dan aksi rahasia.',
    alasan: 'Satu langkah = satu cabang, sehingga perilaku mudah ditebak.',
  },
  keputusan: {
    judul: 'Keputusan langkah ini',
    kode: 'rencana_chat · rencana_vote · pertahanan_suara · format_npc · siapkan_nlg',
    tujuan: 'Menyatukan hasil metode menjadi satu keputusan.',
    proses:
      'Rencana chat (intent + target), vote, dan aksi rahasia digabung; vote dijaga agar tidak memecah suara.',
    keluaran: 'npc_decision {action, target} dan rencana kalimat untuk NLG.',
    alasan: 'Format sama untuk ketiga metode, jadi engine dan NLG tidak perlu tahu metodenya.',
  },
  penjelasan: {
    tahap: ['penjelasan'],
    judul: 'Penjelasan untuk panel',
    kode: 'penjelasan.jelaskan',
    tujuan: 'Mencatat alasan keputusan untuk admin.',
    proses: 'Parameter, penalaran, dan keputusan diringkas (maks 12 KB).',
    keluaran: 'Isi tab Parameter, Penalaran, dan Keputusan.',
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
    tahap: ['validasi'],
    judul: 'Cek aturan + validasi IndoBERT',
    kode: 'bersihkan · periksa_aturan · validasi_nlu · nilai_kalimat',
    tujuan: 'Memastikan kalimat sesuai rencana.',
    proses:
      'Kalimat dibersihkan dan dicek (target disebut, tidak membocorkan role), lalu IndoBERT membaca ulang: intent dan target harus cocok. Gagal → ulang LLM (maks 2 kali) atau templat.',
    keluaran: 'Kalimat yang lolos, atau alasan penolakan.',
    alasan: 'LLM bisa melenceng; validasi menjaga kalimat sesuai keputusan metode.',
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
  utility: ['ua', 'ua_1', 'ua_2', 'ua_3', 'ua_4'],
  bt: ['bt', 'bt_1', 'bt_2', 'bt_3', 'bt_4'],
};
let simProgres = null, // {nama: {tahap, detik}} selama simulasi berjalan
  flowNode = '';
function metodePemain(nama) {
  return sim?.pemain.find((p) => p.nama === nama)?.metode;
}
// Node tempat pemain berada untuk satu tahap live; tahap logika menandai kepala cabang metodenya.
function nodeTahap(nama, tahap) {
  if (tahap === 'logika') return { fuzzy: 'fl', utility: 'ua', bt: 'bt' }[metodePemain(nama)];
  return Object.keys(ALUR_AI).find((id) => ALUR_AI[id].tahap?.includes(tahap));
}
// Lama tiap node untuk item chat terpilih (ms), dari timings jejak.
function waktuNode(trace) {
  if (!trace) return {};
  if (isHuman(trace)) return { nlu_pesan: trace.nlu?.ms };
  const t = trace.timings || {},
    kepala = { fuzzy: 'fl', utility: 'ua', bt: 'bt' }[trace.ringkas?.bot?.metode];
  return {
    sinkron: t.nlu_ms,
    ...(kepala ? { [kepala]: t.logika_ms } : {}),
    penjelasan: t.penjelasan_ms,
    nlg_llm: t.llm_ms,
    nlg_cek: t.validasi_ms,
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
          ['Cek + validasi', duration(t.validasi_ms)],
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
// SIMULASI: pertandingan tiruan (admin + bot pilihan) memakai engine, otak, NLU, dan NLG asli di server.
// Item chat dan detailnya memakai tampilan yang sama dengan checker room.
const BOT_SIMULASI = [
  'NOX',
  'ECHO',
  'VEIL',
  'RAVEN',
  'ASH',
  'DUSK',
  'IRIS',
  'SAGE',
  'ONYX',
  'LARK',
];
const PILIHAN_METODE = [
  ['fuzzy', 'FL · Fuzzy Mamdani'],
  ['utility', 'UA · Utility AI'],
  ['bt', 'BT · Behavior Tree'],
];
let sim = null,
  simTraces = [],
  simSelected = '',
  simBusy = false;
// Satu pilihan metode per bot; pilihan lama dipertahankan saat jumlah pemain diubah.
function renderSimSetup() {
  const lama = [...$('sim-bots').querySelectorAll('select')].map((s) => s.value);
  const jumlah = Number($('sim-count').value) - 1;
  $('sim-bots').replaceChildren(
    ...BOT_SIMULASI.slice(0, jumlah).map((nama, i) => {
      const label = node('label', `${nama} memakai`);
      const select = document.createElement('select');
      for (const [value, text] of PILIHAN_METODE) select.add(new Option(text, value));
      select.value = lama[i] || PILIHAN_METODE[i % 3][0];
      label.append(select);
      return label;
    }),
  );
}
renderSimSetup();
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
function historyQuery() {
  const from = $('date-from').value,
    to = $('date-to').value;
  if (from && to && from > to)
    throw new Error('Tanggal awal harus sebelum atau sama dengan tanggal akhir.');
  const q = new URLSearchParams();
  if (from) q.set('date_from', from);
  if (to) q.set('date_to', to);
  if ($('history-room').value) q.set('room_code', $('history-room').value);
  q.set('sender_kind', $('history-sender').value);
  q.set('urut', $('history-order').value);
  return q;
}
// Muat halaman riwayat dan abaikan respons dari sesi atau filter yang sudah berubah.
async function history(reset = true) {
  const q = historyQuery(),
    epoch = generation;
  if (reset) {
    historyVersion++;
    historyAfter = 0;
    $('history-rows').replaceChildren();
  }
  const version = historyVersion;
  // historyAfter = id terakhir halaman sebelumnya; urut "baru" melanjutkan ke pesan yang lebih lama.
  if (q.get('urut') === 'baru') {
    if (historyAfter) q.set('before_id', String(historyAfter));
  } else q.set('after_id', String(historyAfter));
  const data = await request(`/api/panel/history?${q}`);
  if (epoch !== generation || !token || version !== historyVersion) return;
  for (const row of data.messages) {
    const tr = document.createElement('tr');
    const date = new Date(row.created_at.endsWith('Z') ? row.created_at : row.created_at + 'Z');
    for (const value of [
      `#${row.id}
${date.toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' })}`,
      `${row.room_code || '-'}
Ronde ${row.round_number ?? '-'} | ${row.phase || 'legacy'}`,
      `${row.sender_name}
${row.sender_kind}`,
      row.message,
    ]) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    }
    tr.append(node('td', nluTeks(row.nlu)), konteksSel(row.nlu));
    $('history-rows').append(tr);
  }
  historyAfter = data.next_after_id;
  $('more-history').hidden = !data.has_more;
  $('history-empty').hidden = $('history-rows').children.length > 0;
}
// Bungkus event async agar submit tidak me-reload halaman dan error tampil di panel.
function handle(fn) {
  return async (event) => {
    if (event) event.preventDefault();
    try {
      await fn(event);
    } catch (error) {
      notice(error.message);
    }
  };
}
$('login-form').onsubmit = handle(async () => {
  $('login-button').disabled = true;
  try {
    const data = await request(
      '/api/panel/login',
      { username: $('username').value, password: $('password').value },
      'POST',
    );
    token = data.access_token;
    await loadConfig();
    await loadRooms();
    $('login-view').hidden = true;
    $('workspace').hidden = false;
    $('logout').hidden = false;
    await selectMenu('ai');
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
async function selectMenu(name) {
  menu = name;
  for (const b of document.querySelectorAll('[data-menu]')) {
    if (b.dataset.menu === name) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  }
  for (const id of ['ai', 'checker', 'history', 'users', 'npc', 'survey', 'simulasi', 'dokumen'])
    $('menu-' + id).hidden = id !== name;
  if (name === 'checker' || name === 'history') await loadRooms();
  if (name === 'checker') await checker();
  if (name === 'history') await history();
  if (name === 'users') await loadUsers();
  if (name === 'npc') await loadNpc();
  if (name === 'survey') await loadSurvey();
  if (name === 'simulasi') renderSim();
}

// OTAK NPC: isi pilihan dari server agar panel tidak perlu tahu daftar metode.
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
    fillSelect($('npc-method'), data.pilihan.metode, status.metode);
    fillSelect($('npc-writer'), data.pilihan.penulis, status.penulis_diminta);
    $('npc-validate').checked = status.validasi;
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
    cadangan: 'Cadangan: SVM + nama yang disebut (IndoBERT tidak ditemukan)',
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
const KIND_LABEL = {
  stars: 'Bintang',
  scale: 'Skala angka',
  choice: 'Pilihan ganda',
  text: 'Teks bebas',
};
function surveyScale(question) {
  if (question.kind === 'stars' || question.kind === 'scale')
    return `${KIND_LABEL[question.kind]} ${question.scale_min}–${question.scale_max}`;
  if (question.kind === 'choice') return `${KIND_LABEL.choice}: ${question.options.join(' / ')}`;
  return KIND_LABEL.text;
}
async function loadSurvey() {
  const epoch = generation;
  const data = await request('/api/panel/survey/summary');
  if (!token || epoch !== generation) return;
  const distribution = {};
  for (const row of data.distribution) (distribution[row.question_id] ??= []).push(row);
  const texts = Object.fromEntries(data.text_answers.map((row) => [row.question_id, row.n]));
  $('survey-rows').replaceChildren(
    ...data.questions.map((question) => {
      const rows = distribution[question.id] ?? [];
      const total = rows.reduce((sum, row) => sum + row.n, 0);
      const mean = total
        ? rows.reduce((sum, row) => sum + row.n * row.value_number, 0) / total
        : null;
      const result =
        question.kind === 'text' || question.kind === 'choice'
          ? `${texts[question.id] ?? 0} jawaban`
          : total
            ? `${total} jawaban · rata-rata ${mean.toFixed(2)}`
            : 'Belum ada';
      const meaning =
        question.label_min || question.label_max
          ? `${question.scale_min} = ${question.label_min ?? '—'} · ${question.scale_max} = ${question.label_max ?? '—'}`
          : '—';
      const edit = node('button', 'Edit', 'secondary');
      edit.type = 'button';
      edit.onclick = () => editSurvey(question);
      const toggle = node('button', question.active ? 'Nonaktifkan' : 'Aktifkan', 'secondary');
      toggle.type = 'button';
      toggle.onclick = handle(() =>
        saveSurvey({ ...question, active: !question.active }, question.id),
      );
      const actions = node('td');
      actions.append(edit, ' ', toggle);
      const tr = document.createElement('tr');
      tr.append(
        node('td', String(question.position)),
        node('td', question.prompt + (question.required ? '' : ' (opsional)')),
        node('td', surveyScale(question)),
        node('td', meaning),
        node('td', question.active ? 'Aktif' : 'Nonaktif'),
        node('td', result),
        actions,
      );
      return tr;
    }),
  );
  const prompts = Object.fromEntries(data.questions.map((q) => [q.id, q.prompt]));
  $('survey-method-rows').replaceChildren(
    ...data.per_method.map((row) => {
      const tr = document.createElement('tr');
      tr.append(
        node('td', prompts[row.question_id] ?? String(row.question_id)),
        node('td', row.method),
        node('td', String(row.n)),
        node('td', row.rata == null ? '—' : row.rata.toFixed(2)),
      );
      return tr;
    }),
  );
}
// Isi form dari data pertanyaan untuk diedit.
function editSurvey(question) {
  $('survey-id').value = String(question.id);
  $('survey-code').value = question.code;
  $('survey-position').value = String(question.position);
  $('survey-prompt').value = question.prompt;
  $('survey-kind').value = question.kind;
  $('survey-min').value = String(question.scale_min);
  $('survey-max').value = String(question.scale_max);
  $('survey-label-min').value = question.label_min ?? '';
  $('survey-label-max').value = question.label_max ?? '';
  $('survey-options').value = question.options.join('\n');
  $('survey-required').checked = question.required;
  $('survey-active').checked = question.active;
  $('survey-editor-title').textContent = 'Edit pertanyaan: ' + question.code;
  $('survey-editor-box').open = true;
}
function resetSurveyForm() {
  $('survey-form').reset();
  $('survey-id').value = '';
  $('survey-editor-title').textContent = '+ Tambah pertanyaan';
  $('survey-editor-box').open = false;
}
function surveyPayload() {
  return {
    code: $('survey-code').value.trim().toLowerCase(),
    prompt: $('survey-prompt').value.trim(),
    kind: $('survey-kind').value,
    scale_min: Number($('survey-min').value),
    scale_max: Number($('survey-max').value),
    label_min: $('survey-label-min').value.trim() || null,
    label_max: $('survey-label-max').value.trim() || null,
    options: $('survey-options')
      .value.split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
    required: $('survey-required').checked,
    active: $('survey-active').checked,
    position: Number($('survey-position').value) || 0,
  };
}
async function saveSurvey(body, id) {
  if (id) await request(`/api/panel/survey/questions/${id}`, body, 'PUT');
  else await request('/api/panel/survey/questions', body, 'POST');
  notice('Pertanyaan survei tersimpan. Pemain melihat versi terbaru di pertandingan berikutnya.');
  resetSurveyForm();
  await loadSurvey();
}

// Muat daftar akun tanpa rahasia; versi request mencegah hasil filter lama menimpa pencarian baru.
async function loadUsers(reset = true) {
  const epoch = generation;
  if (reset) {
    usersVersion++;
    usersAfter = 0;
    $('user-rows').replaceChildren();
  }
  const version = usersVersion;
  const query = new URLSearchParams({
    after_id: String(usersAfter),
    search: $('user-search').value.trim(),
  });
  const data = await request('/api/panel/users?' + query);
  if (!token || epoch !== generation || version !== usersVersion) return;
  for (const user of data.users) {
    const row = document.createElement('tr');
    for (const [label, value] of [
      ['Username', user.username],
      ['Nama tampilan', user.display_name],
      ['Login', user.login_method === 'google' ? 'Google' : 'Password'],
    ]) {
      const cell = document.createElement('td');
      cell.dataset.label = label;
      if (label === 'Login') cell.append(node('span', value, 'login-method'));
      else cell.textContent = value;
      row.append(cell);
    }
    const actions = document.createElement('td');
    actions.dataset.label = 'Aksi';
    const actionGroup = node('div', undefined, 'user-actions');
    const editButton = document.createElement('button');
    editButton.className = 'secondary';
    editButton.textContent = 'Edit user';
    editButton.onclick = () => openUserEditor(user, 'profile');
    actionGroup.append(editButton);
    if (user.login_method !== 'google') {
      const passwordButton = document.createElement('button');
      passwordButton.className = 'secondary';
      passwordButton.textContent = 'Ubah password';
      passwordButton.onclick = () => openUserEditor(user, 'password');
      actionGroup.append(passwordButton);
    } else {
      const note = document.createElement('small');
      note.textContent = 'Password dikelola Google. ';
      note.className = 'google-password-note';
      actionGroup.append(note);
    }
    const deleteButton = document.createElement('button');
    deleteButton.className = 'danger';
    deleteButton.textContent = 'Hapus akun';
    deleteButton.onclick = () => openUserEditor(user, 'delete');
    actionGroup.append(deleteButton);
    actions.append(actionGroup);
    row.append(actions);
    $('user-rows').append(row);
  }
  usersAfter = data.next_after_id;
  $('more-users').hidden = !data.has_more;
  $('users-empty').hidden = $('user-rows').children.length > 0;
}

// Bersihkan password/draft konfirmasi setiap editor ditutup atau sesi panel berakhir.
function closeUserEditor() {
  selectedUser = null;
  if ($('user-editor').open) $('user-editor').close();
  $('user-editor').hidden = true;
  $('user-password-form').reset();
  $('user-profile-form').reset();
  $('user-delete-form').reset();
}

// Target disimpan sebagai ID; nama target ditampilkan sebelum admin mengonfirmasi tindakan.
function openUserEditor(user, action) {
  if (userSaving) return;
  closeUserEditor();
  selectedUser = user;
  $('user-editor').hidden = false;
  $('user-editor-title').textContent =
    (action === 'profile'
      ? 'Edit user: '
      : action === 'password'
        ? 'Ubah password: '
        : 'Hapus akun: ') + user.username;
  $('user-profile-form').hidden = action !== 'profile';
  $('edit-user-username').value = user.username;
  $('edit-user-display-name').value = user.display_name;
  $('user-password-form').hidden = action !== 'password';
  $('user-delete-form').hidden = action !== 'delete';
  $('user-editor').showModal();
  (action === 'profile'
    ? $('edit-user-username')
    : action === 'password'
      ? $('user-new-password')
      : $('user-delete-confirmation')
  ).focus();
}

// Cegah klik ganda dan pergantian target selama mutasi akun sedang berlangsung.
async function changeUser(action) {
  if (!selectedUser || userSaving) return;
  const target = selectedUser;
  const epoch = generation;
  let body;
  if (action === 'profile') {
    body = {
      username: $('edit-user-username').value.trim(),
      display_name: $('edit-user-display-name').value.trim(),
    };
  } else if (action === 'password') {
    if (target.login_method === 'google')
      throw new Error('Password akun Google dikelola di Google.');
    if ($('user-new-password').value !== $('user-password-confirmation').value)
      throw new Error('Konfirmasi password tidak cocok.');
    body = {
      password: $('user-new-password').value,
      password_confirmation: $('user-password-confirmation').value,
    };
  } else {
    if ($('user-delete-confirmation').value !== target.username)
      throw new Error('Ketik username target dengan tepat untuk menghapus akun.');
    body = { confirm_username: $('user-delete-confirmation').value };
  }
  userSaving = true;
  for (const id of ['save-user-profile', 'save-user-password', 'delete-user', 'cancel-user-edit'])
    $(id).disabled = true;
  try {
    await request(`/api/panel/users/${target.id}/${action}`, body, 'POST');
    if (!token || epoch !== generation) return;
    closeUserEditor();
    notice(
      action === 'profile'
        ? 'Data user disimpan. Jika username berubah, user perlu login ulang.'
        : action === 'password'
          ? 'Password diganti. Semua sesi user dicabut; user perlu login ulang.'
          : 'Akun dihapus. Riwayat chat dan analisis tetap tersimpan.',
    );
    await loadUsers();
  } finally {
    $('user-new-password').value = '';
    $('user-password-confirmation').value = '';
    userSaving = false;
    for (const id of ['save-user-profile', 'save-user-password', 'delete-user', 'cancel-user-edit'])
      $(id).disabled = false;
  }
}

$('user-search-form').onsubmit = handle(() => loadUsers());
$('more-users').onclick = handle(async () => {
  $('more-users').disabled = true;
  try {
    await loadUsers(false);
  } finally {
    $('more-users').disabled = false;
  }
});
$('cancel-user-edit').onclick = closeUserEditor;
$('user-editor').addEventListener('cancel', (event) => {
  event.preventDefault();
  if (!userSaving) closeUserEditor();
});
$('user-profile-form').onsubmit = handle(() => changeUser('profile'));
$('user-password-form').onsubmit = handle(() => changeUser('password'));
$('user-delete-form').onsubmit = handle(() => changeUser('delete'));

// Buat akun tanpa login sebagai pemain; rahasia form selalu dibersihkan setelah request.
$('create-user-form').onsubmit = handle(async () => {
  if ($('create-user-button').disabled) return;
  if ($('create-password').value !== $('create-password-confirmation').value)
    throw new Error('Konfirmasi password tidak cocok.');
  const epoch = generation;
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
    if (!token || epoch !== generation) return;
    $('create-user-form').reset();
    $('user-search').value = '';
    notice(
      'User berhasil ditambahkan. Pemain dapat login menggunakan username dan password tersebut.',
    );
    await loadUsers();
  } finally {
    $('create-password').value = '';
    $('create-password-confirmation').value = '';
    $('create-user-button').disabled = false;
  }
});
for (const b of document.querySelectorAll('[data-menu]'))
  b.onclick = handle(() => selectMenu(b.dataset.menu));
$('provider').onchange = providerView;
$('key-source').onchange = () => {
  $('api-key').value = '';
  keySourceView();
};
$('config-form').onsubmit = handle(async () => {
  $('save-config').disabled = true;
  $('check-ai').disabled = true;
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
    $('check-ai').disabled = false;
  }
});
$('probe-form').onsubmit = handle(async () => {
  if ($('check-ai').disabled) return;
  $('check-ai').disabled = true;
  $('save-config').disabled = true;
  const epoch = generation,
    started = performance.now();
  $('ai-status').textContent = 'Memproses teks, menyusun prompt, lalu menunggu provider...';
  $('probe-result').textContent = 'Pengujian sedang berjalan. Hasil sebelumnya telah dibersihkan.';
  const timer = setInterval(() => {
    $('probe-progress').textContent =
      `${((performance.now() - started) / 1000).toFixed(1)} dtk berjalan`;
  }, 100);
  try {
    const data = await request(
      '/api/panel/test-ai',
      { message: $('probe-message').value.trim(), scenario: $('probe-scenario').value },
      'POST',
    );
    if (epoch !== generation || !token) return;
    $('ai-status').textContent = data.message_status;
    renderReport($('probe-result'), data);
  } catch (error) {
    if (epoch === generation) {
      $('ai-status').textContent = 'Pemeriksaan gagal: ' + error.message;
      $('probe-result').textContent =
        'Hasil belum tersedia. Periksa koneksi lalu jalankan ulang pengujian.';
    }
    throw error;
  } finally {
    clearInterval(timer);
    $('probe-progress').textContent = '';
    $('save-config').disabled = false;
    $('check-ai').disabled = false;
  }
});
$('refresh-checker').onclick = handle(async () => {
  await loadRooms();
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
$('sim-count').onchange = renderSimSetup;
$('sim-setup').onsubmit = handle(async () => {
  const data = await simRequest(
    '/api/panel/simulasi',
    {
      nama: $('sim-name').value.trim() || 'Pemain',
      metode: [...$('sim-bots').querySelectorAll('select')].map((s) => s.value),
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
$('history-filter').onsubmit = handle(() => history());
$('more-history').onclick = handle(async () => {
  $('more-history').disabled = true;
  try {
    await history(false);
  } finally {
    $('more-history').disabled = false;
  }
});
$('download').onclick = handle(async () => {
  $('download').disabled = true;
  try {
    const response = await fetch(`/api/panel/history.csv?${historyQuery()}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!response.ok) {
      if (response.status === 401) clearSession();
      throw new Error('Download gagal. Periksa login dan koneksi database.');
    }
    const url = URL.createObjectURL(await response.blob()),
      a = document.createElement('a');
    a.href = url;
    a.download = 'riwayat-chat.csv';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
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
        metode: $('npc-method').value,
        penulis: $('npc-writer').value,
        validasi: $('npc-validate').checked,
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
for (const id of [
  'npc-method',
  'npc-writer',
  'npc-validate',
  'npc-openrouter-model',
  'npc-link-model',
])
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
    await saveSurvey(surveyPayload(), Number($('survey-id').value) || null);
  } finally {
    $('save-survey').disabled = false;
  }
});
$('cancel-survey').onclick = resetSurveyForm;
$('download-survey').onclick = handle(async () => {
  $('download-survey').disabled = true;
  try {
    const response = await fetch('/api/panel/survey/responses.csv', {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!response.ok) {
      if (response.status === 401) clearSession();
      throw new Error('Download gagal. Periksa login dan migrasi V7.');
    }
    const url = URL.createObjectURL(await response.blob()),
      a = document.createElement('a');
    a.href = url;
    a.download = 'survei-silent-terror.csv';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
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

// PILIHAN KUSTOM: dropdown bawaan browser diganti tombol + daftar bergaya panel. <select> asli tetap ada dan
// disembunyikan, jadi nilai form, event change, dan kode lain yang membaca/menyetel .value tidak berubah.
// Daftar dibangun ulang saat opsi, nilai, atau status nonaktif berubah; keyboard: panah, Enter/Spasi, Esc, Tab.
const PILIH_PROTO = Object.getOwnPropertyDescriptors(HTMLSelectElement.prototype);
function pilihanKustom(select) {
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
  const judul = label
    ? [...label.childNodes]
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent)
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
      ...[...select.options].map((o) => {
        const li = node('li', o.text, 'pilih-opsi');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', String(o.selected));
        if (o.disabled) li.setAttribute('aria-disabled', 'true');
        li.tabIndex = -1;
        li.dataset.value = o.value;
        return li;
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
  const pilih = (li) => {
    if (!li || li.getAttribute('aria-disabled')) return;
    const berubah = select.value !== li.dataset.value;
    select.value = li.dataset.value;
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
    const opsi = [...daftar.children];
    const i = opsi.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      opsi[
        Math.max(0, Math.min(opsi.length - 1, i + (event.key === 'ArrowDown' ? 1 : -1)))
      ]?.focus();
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      pilih(opsi[i]);
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
      set: (v) => {
        PILIH_PROTO[nama].set.call(select, v);
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
document.querySelectorAll('select').forEach(pilihanKustom);
// <select> yang dibuat belakangan (mis. pilihan metode bot di Simulasi) ikut diganti.
new MutationObserver((perubahan) => {
  for (const p of perubahan)
    for (const n of p.addedNodes)
      if (n.nodeType === 1)
        (n.matches('select') ? [n] : n.querySelectorAll('select')).forEach(pilihanKustom);
}).observe(document.body, { childList: true, subtree: true });
document.addEventListener('click', (event) => {
  for (const daftar of document.querySelectorAll('.pilih-daftar:not([hidden])'))
    if (!daftar.parentElement.contains(event.target)) {
      daftar.hidden = true;
      daftar.previousElementSibling.setAttribute('aria-expanded', 'false');
    }
});
