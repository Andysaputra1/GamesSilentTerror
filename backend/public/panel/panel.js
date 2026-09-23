'use strict';
// Ambil elemen panel berdasarkan ID.
const $ = (id) => document.getElementById(id);
let historyVersion = 0;
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
};
// Kirim request panel dan hapus sesi lokal jika server menyatakan token tidak valid.
async function request(path, body, method = 'GET') {
  const response = await fetch(path, {
    method,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return {};
  const data = await response.json();
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
  traces = [];
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
// Render daftar jejak dan detail terpilih menggunakan textContent.
function renderTraces() {
  const box = $('traces');
  box.replaceChildren();
  if (!traces.length) {
    box.textContent = 'Belum ada jejak AI di room ini.';
    $('trace-detail').textContent = 'Belum ada data.';
    return;
  }
  const active = traces.find((t) => t.id === selectedTrace) || traces[0];
  selectedTrace = active.id;
  $('trace-detail').textContent = JSON.stringify(active, null, 2);
  for (const trace of traces) {
    const b = document.createElement('button');
    b.className = 'trace' + (trace.id === active.id ? ' selected' : '');
    b.textContent = `${trace.sender}: ${trace.message}`;
    const small = document.createElement('small');
    small.textContent = `${trace.stage} | ${trace.model || 'belum memanggil AI'}`;
    b.append(small);
    b.onclick = () => {
      selectedTrace = trace.id;
      renderTraces();
    };
    box.append(b);
  }
}
// Muat jejak terbaru/lama; tolak respons basi setelah logout atau pergantian ruangan.
async function checker(older = false) {
  if (busy) return;
  const code = $('checker-room').value;
  if (!code) {
    traces = [];
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
    if (!older) $('events').textContent = JSON.stringify(data.events, null, 2);
    renderTraces();
  } finally {
    busy = false;
  }
}
// Validasi urutan tanggal dan susun parameter untuk riwayat serta ekspor CSV.
function dateQuery() {
  const from = $('date-from').value,
    to = $('date-to').value;
  if (from && to && from > to)
    throw new Error('Tanggal awal harus sebelum atau sama dengan tanggal akhir.');
  const q = new URLSearchParams();
  if (from) q.set('date_from', from);
  if (to) q.set('date_to', to);
  return q;
}
// Muat halaman riwayat dan abaikan respons dari sesi atau filter yang sudah berubah.
async function history(reset = true) {
  const q = dateQuery(),
    epoch = generation;
  if (reset) {
    historyVersion++;
    historyAfter = 0;
    $('history-rows').replaceChildren();
  }
  const version = historyVersion;
  q.set('after_id', String(historyAfter));
  if ($('history-room').value) q.set('room_code', $('history-room').value);
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
  for (const id of ['ai', 'checker', 'history']) $('menu-' + id).hidden = id !== name;
  if (name !== 'ai') await loadRooms();
  if (name === 'checker') await checker();
  if (name === 'history') await history();
}
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
$('check-ai').onclick = handle(async () => {
  $('check-ai').disabled = true;
  $('save-config').disabled = true;
  $('ai-status').textContent = 'Memeriksa konfigurasi yang tersimpan di server...';
  try {
    const data = await request('/api/panel/check-ai', null, 'POST');
    $('ai-status').textContent = (data.active ? 'Aktif: ' : 'Tidak aktif: ') + data.message;
  } catch (error) {
    $('ai-status').textContent = 'Pemeriksaan gagal: ' + error.message;
    throw error;
  } finally {
    $('save-config').disabled = false;
    $('check-ai').disabled = false;
  }
});
$('refresh-checker').onclick = handle(async () => {
  await loadRooms();
  await checker();
});
$('checker-room').onchange = handle(() => {
  selectedTrace = '';
  return checker();
});
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
    const response = await fetch(`/api/panel/history.csv?${dateQuery()}`, {
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
    notice('CSV semua room berhasil diunduh.');
  } finally {
    $('download').disabled = false;
  }
});
$('logout').onclick = handle(async () => {
  try {
    await request('/api/panel/logout', null, 'POST');
  } finally {
    clearSession();
    notice('Kamu sudah keluar dari panel.');
  }
});
setInterval(() => {
  if (token && menu === 'checker' && $('auto-checker').checked && !document.hidden)
    checker().catch((error) => notice(error.message));
}, 5000);
