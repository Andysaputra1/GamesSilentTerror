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
  for (const id of ['ai', 'checker', 'history', 'users']) $('menu-' + id).hidden = id !== name;
  if (name === 'checker' || name === 'history') await loadRooms();
  if (name === 'checker') await checker();
  if (name === 'history') await history();
  if (name === 'users') await loadUsers();
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
      cell.textContent = value;
      row.append(cell);
    }
    const actions = document.createElement('td');
    actions.dataset.label = 'Aksi';
    if (user.login_method !== 'google') {
      const passwordButton = document.createElement('button');
      passwordButton.className = 'secondary';
      passwordButton.textContent = 'Ubah password';
      passwordButton.onclick = () => openUserEditor(user, 'password');
      actions.append(passwordButton);
    } else {
      const note = document.createElement('small');
      note.textContent = 'Password dikelola Google. ';
      actions.append(note);
    }
    const deleteButton = document.createElement('button');
    deleteButton.className = 'secondary';
    deleteButton.textContent = 'Hapus akun';
    deleteButton.onclick = () => openUserEditor(user, 'delete');
    actions.append(deleteButton);
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
  $('user-editor').hidden = true;
  $('user-password-form').reset();
  $('user-delete-form').reset();
}

// Target disimpan sebagai ID; nama target ditampilkan sebelum admin mengonfirmasi tindakan.
function openUserEditor(user, action) {
  if (userSaving) return;
  closeUserEditor();
  selectedUser = user;
  $('user-editor').hidden = false;
  $('user-editor-title').textContent =
    (action === 'password' ? 'Ubah password: ' : 'Hapus akun: ') + user.username;
  $('user-password-form').hidden = action !== 'password';
  $('user-delete-form').hidden = action !== 'delete';
  (action === 'password' ? $('user-new-password') : $('user-delete-confirmation')).focus();
}

// Cegah klik ganda dan pergantian target selama mutasi akun sedang berlangsung.
async function changeUser(action) {
  if (!selectedUser || userSaving) return;
  const target = selectedUser;
  const epoch = generation;
  let body;
  if (action === 'password') {
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
  for (const id of ['save-user-password', 'delete-user', 'cancel-user-edit']) $(id).disabled = true;
  try {
    await request(`/api/panel/users/${target.id}/${action}`, body, 'POST');
    if (!token || epoch !== generation) return;
    closeUserEditor();
    notice(
      action === 'password'
        ? 'Password diganti. Semua sesi user dicabut; user perlu login ulang.'
        : 'Akun dihapus. Riwayat chat dan analisis tetap tersimpan.',
    );
    await loadUsers();
  } finally {
    $('user-new-password').value = '';
    $('user-password-confirmation').value = '';
    userSaving = false;
    for (const id of ['save-user-password', 'delete-user', 'cancel-user-edit'])
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
