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
    // Uji AI dan cek rantai penulis menunggu provider; request lain cukup 15 detik.
    signal: AbortSignal.timeout(/\/(test-ai|cek-penulis)$/.test(path) ? 60000 : 15000),
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
      'Analisis SVM / fuzzy',
      trace.analysis || {
        intent: trace.intent,
        aggressiveness: trace.aggressiveness,
        suspicion_score: trace.suspicion_score,
        silence_percentage: trace.silence_percentage,
      },
    ],
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
  for (const id of ['checker-room', 'history-room']) {
    const select = $(id),
      current = select.value;
    select.replaceChildren(
      new Option(id === 'history-room' ? 'Semua ruangan' : 'Pilih ruangan', ''),
    );
    for (const room of rooms)
      select.add(
        new Option(
          `${room.room_code} | ${room.message_count} pesan${room.live ? ' | aktif' : ''}`,
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
  detailTab = 'keputusan',
  renderedDetail = ''; // jejak yang sedang tampil: tidak dirender ulang tiap auto-refresh
const traceDetails = new Map(); // id → jejak lengkap (dengan penjelasan), dimuat saat dibuka
const METODE_LABEL = {
  fuzzy: 'Fuzzy Mamdani',
  utility: 'Utility AI (IAUS)',
  bt: 'Behavior Tree',
  llm: 'LLM (mode lama)',
};
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
function traceItem(trace, selected) {
  const b = node('button', undefined, 'trace' + (selected ? ' selected' : ''));
  const r = trace.ringkas;
  if (r) {
    const head = node('span', undefined, 'trace-head');
    head.append(node('strong', r.bot?.nama || trace.sender));
    if (r.bot?.metode) head.append(chip(METODE_LABEL[r.bot.metode] || r.bot.metode, 'status-good'));
    if (r.bot?.role) head.append(chip(ROLE_LABEL[r.bot.role] || r.bot.role, roleClass(r.bot.role)));
    const meta = [
      `Ronde ${r.bot?.ronde ?? '?'} · ${FASE_LABEL[r.bot?.fase] || r.bot?.fase || '—'}`,
      waktu(trace.created_at),
      r.ditolak && 'ditolak engine',
      r.nlg === 'ditunda' && 'chat ditunda',
    ].filter(Boolean);
    b.append(
      head,
      node('span', r.keputusan?.length ? r.keputusan.join(' · ') : trace.message, 'trace-title'),
      node('small', meta.join(' · ')),
    );
  } else {
    b.append(
      node('span', `${trace.sender}: ${trace.message}`, 'trace-title'),
      node(
        'small',
        `${trace.stage} · ${duration(trace.duration_ms)}\n${trace.model || 'belum memanggil AI'}`,
      ),
    );
  }
  b.onclick = () => {
    selectedTrace = trace.id;
    renderTraces();
  };
  return b;
}
// Render daftar jejak (sesuai filter) dan detail jejak terpilih.
function renderTraces() {
  renderFilter();
  const box = $('traces');
  box.replaceChildren();
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
  for (const trace of list) box.append(traceItem(trace, trace.id === active.id));
  showDetail(active).catch((error) => notice(error.message));
}
// Jejak otak bot dimuat lengkap sekali (cache); jejak lain memakai laporan pipeline lama.
async function showDetail(trace) {
  const container = $('trace-detail');
  const key = `${trace.id}|${trace.stage}|${trace.duration_ms}`;
  if (renderedDetail === key) return;
  renderedDetail = key;
  if (!trace.ringkas) {
    renderReport(container, trace);
    return;
  }
  if (traceDetails.has(trace.id)) {
    renderDecision(container, traceDetails.get(trace.id));
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
    if (selectedTrace === trace.id) renderDecision(container, data);
  } catch (error) {
    if (selectedTrace === trace.id) {
      renderedDetail = '';
      container.textContent = error.message;
    }
  }
}
// Kartu keputusan bertab: Keputusan · Parameter · Penalaran metode · NLG · Teknis.
function renderDecision(container, trace) {
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
  show(tabs.some((tab) => tab[0] === detailTab) ? detailTab : 'keputusan');
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
function nlgTab(p) {
  const n = p.nlg,
    box = node('div');
  if (!n) {
    box.append(node('p', 'Jejak ini tidak memuat data NLG.', 'hint'));
    return box;
  }
  if (n.status !== 'terkirim') {
    box.append(
      keyValues([
        ['Status', n.status],
        ['Keterangan', n.keterangan],
      ]),
    );
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
  q.set('after_id', String(historyAfter));
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
  for (const id of ['ai', 'checker', 'history', 'users', 'npc', 'survey'])
    $('menu-' + id).hidden = id !== name;
  if (name === 'checker' || name === 'history') await loadRooms();
  if (name === 'checker') await checker();
  if (name === 'history') await history();
  if (name === 'users') await loadUsers();
  if (name === 'npc') await loadNpc();
  if (name === 'survey') await loadSurvey();
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
for (const id of ['npc-method', 'npc-writer', 'npc-validate', 'npc-openrouter-model'])
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
