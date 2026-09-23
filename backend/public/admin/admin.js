'use strict';

// Token hanya di memori halaman ini. Seluruh data dinamis memakai textContent, bukan innerHTML.
const byId = (id) => document.getElementById(id);
let token = '',
  busy = false,
  selectedEvent = '',
  selectedTrace = '';
// Tampilkan status sebagai teks agar pesan dinamis tidak dieksekusi sebagai HTML.
const notice = (message) => {
  byId('notice').textContent = message;
};

// Kirim request admin ber-token dengan batas waktu dan normalisasi error HTTP.
async function request(path, body, method) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      method: method || (body ? 'POST' : 'GET'),
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok)
      throw new Error(
        typeof data.detail === 'string'
          ? data.detail
          : 'Permintaan ditolak (' + response.status + ').',
      );
    return data;
  } finally {
    clearTimeout(timer);
  }
}

// Tampilkan provider aktif serta ketersediaan model tanpa mengekspos API key.
async function configuration() {
  const data = await request('/api/admin/status');
  byId('current-provider').textContent =
    `Aktif: ${data.provider} / ${data.provider === 'api' ? data.api_model : data.model} · sumber: ${data.source} · API key: ${data.api_configured ? 'terkonfigurasi' : 'belum ada'} · model Ollama: ${data.ollama_model_available ? 'tersedia' : 'belum tersedia'}`;
  byId('provider').value = data.provider;
  byId('model').value = data.model.includes('14b') ? '14' : '8';
}

// Render daftar dan detail yang dipilih; ID tetap stabil ketika polling datang.
function renderList(id, detailId, items, chosen, label) {
  const container = byId(id);
  container.replaceChildren();
  const active = items.find((item) => item.id === chosen) || items[0];
  byId(detailId).textContent = active ? JSON.stringify(active, null, 2) : 'Belum ada data.';
  for (const item of items) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'event' + (item === active ? ' selected' : '');
    button.textContent = label(item);
    const small = document.createElement('small');
    small.textContent = `${item.status || item.stage} · ${item.room || item.room_code || 'global'} · ${item.at || item.created_at}`;
    button.append(small);
    button.addEventListener('click', () => {
      if (id === 'events') selectedEvent = item.id;
      else selectedTrace = item.id;
      renderList(id, detailId, items, item.id, label);
    });
    container.append(button);
  }
}

// Perbarui daftar aktivitas dan jejak sesuai ruangan yang sedang dipilih.
async function refresh() {
  if (!token || busy) return;
  busy = true;
  byId('refresh').disabled = true;
  byId('room').disabled = true;
  try {
    const code = byId('room').value;
    const [rooms, events, traces] = await Promise.all([
      request('/api/admin/rooms'),
      request('/api/admin/activity' + (code ? '?code=' + encodeURIComponent(code) : '')),
      code
        ? request('/api/admin/rooms/' + encodeURIComponent(code) + '/traces')
        : Promise.resolve({ traces: [] }),
    ]);
    const select = byId('room');
    select.replaceChildren(new Option('Semua room', ''));
    for (const room of rooms.rooms)
      select.add(
        new Option(
          `${room.code} · ${room.phase} · ${room.members.length + room.bots.length} pemain`,
          room.code,
        ),
      );
    select.value = code;
    const room = rooms.rooms.find((room) => room.code === code);
    byId('room-info').textContent = room
      ? `Host: ${room.owner} · ronde ${room.round || '—'} · ${room.phase} · pemain: ${room.members.join(', ')} · bot: ${room.bots.join(', ') || 'tidak ada'}`
      : `${rooms.rooms.length} room tersimpan pada proses ini.`;
    renderList('events', 'event-detail', events.events, selectedEvent, (item) => item.function);
    renderList(
      'traces',
      'trace-detail',
      traces.traces,
      selectedTrace,
      (item) => `${item.sender}: ${item.message}`,
    );
    byId('updated').textContent = 'Diperbarui ' + new Date().toLocaleTimeString('id-ID');
  } catch (error) {
    notice('Monitor: ' + error.message);
  } finally {
    busy = false;
    byId('refresh').disabled = false;
    byId('room').disabled = false;
  }
}

byId('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  byId('login-button').disabled = true;
  try {
    const result = await request('/api/auth/login', {
      username: byId('username').value,
      password: byId('password').value,
    });
    token = result.access_token;
    await configuration();
    byId('login-panel').hidden = true;
    byId('console').hidden = false;
    byId('logout').hidden = false;
    notice('Login admin berhasil.');
    await refresh();
  } catch (error) {
    if (token) await request('/api/auth/logout', undefined, 'POST').catch(() => {});
    token = '';
    notice(error.message);
  } finally {
    byId('password').value = '';
    byId('login-button').disabled = false;
  }
});

byId('provider-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  byId('apply-provider').disabled = true;
  try {
    await request('/api/admin/provider', {
      provider: byId('provider').value,
      model: byId('model').value,
    });
    await configuration();
    notice('Provider diterapkan untuk request AI berikutnya.');
    await refresh();
  } catch (error) {
    notice(error.message);
  } finally {
    byId('apply-provider').disabled = false;
  }
});
byId('reset-provider').addEventListener('click', async () => {
  byId('reset-provider').disabled = true;
  try {
    await request('/api/admin/provider/reset', undefined, 'POST');
    await configuration();
    notice('Kembali ke konfigurasi environment.');
  } catch (error) {
    notice(error.message);
  } finally {
    byId('reset-provider').disabled = false;
  }
});
byId('logout').addEventListener('click', async () => {
  try {
    await request('/api/auth/logout', undefined, 'POST');
  } finally {
    token = '';
    byId('login-panel').hidden = false;
    byId('console').hidden = true;
    byId('logout').hidden = true;
    notice('Logout.');
  }
});
byId('room').addEventListener('change', () => {
  selectedEvent = selectedTrace = '';
  void refresh();
});
byId('refresh').addEventListener('click', () => void refresh());
setInterval(() => {
  if (byId('auto').checked && !document.hidden) void refresh();
}, 2000);
