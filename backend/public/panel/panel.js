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
    signal: AbortSignal.timeout(path.endsWith('/test-ai') ? 45000 : 15000),
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
  $('probe-result').replaceChildren();
  $('ai-status').textContent = 'Belum diperiksa.';
  $('probe-progress').textContent = '';
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
  renderReport($('trace-detail'), active);
  for (const trace of traces) {
    const b = document.createElement('button');
    b.className = 'trace' + (trace.id === active.id ? ' selected' : '');
    b.append(node('span', `${trace.sender}: ${trace.message}`, 'trace-title'));
    const small = document.createElement('small');
    small.textContent = `${trace.stage} · ${duration(trace.duration_ms)}\n${trace.model || 'belum memanggil AI'}`;
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
