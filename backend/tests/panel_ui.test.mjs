import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from '../../frontend/node_modules/jsdom/lib/api.js';

const html = await readFile(new URL('../public/panel/index.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../public/panel/panel.js', import.meta.url), 'utf8');
const config = {
  provider: 'api',
  model: 'qwen/qwen3-14b',
  endpoint: '',
  key_source: 'default',
  api_configured: true,
  default_configured: true,
};

function setup(t, route = () => undefined) {
  const dom = new JSDOM(html, { url: 'http://localhost/panel', runScripts: 'outside-only' });
  t.after(() => dom.window.close());
  const w = dom.window;
  w.AbortSignal.timeout = () => new w.AbortController().signal;
  w.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  w.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  w.fetch = async (path, options) => {
    const custom = await route(path, options);
    if (custom) return custom;
    return response(
      path === '/api/panel/login'
        ? { access_token: 'fixture' }
        : path === '/api/panel/config'
          ? config
          : path.startsWith('/api/panel/rooms')
            ? { rooms: [], has_more: false }
            : {},
    );
  };
  w.eval(script);
  return w;
}
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));
async function login(w) {
  w.document.querySelector('#username').value = 'fixture';
  w.document.querySelector('#password').value = 'fixture-password';
  await w.document.querySelector('#login-form').onsubmit({ preventDefault() {} });
}

test('probe renders request/response as text and clears stale results on config change', async (t) => {
  const w = setup(t, (path) =>
    path === '/api/panel/test-ai'
      ? response({
          active: true,
          valid_decision: true,
          duration_ms: 1234,
          timings: { llm_ms: 1000 },
          message: '<img src=x onerror=alert(1)>',
          output: { action: 'wait', message: 'Alibi?' },
          request: { body: { max_tokens: 320 } },
          response: { status_code: 200 },
          message_status: 'Berhasil',
        })
      : undefined,
  );
  await login(w);
  await w.document.querySelector('#probe-form').onsubmit({ preventDefault() {} });
  const report = w.document.querySelector('#probe-result');
  assert.match(report.textContent, /1.23 dtk/);
  assert.match(report.textContent, /max_tokens/);
  assert.equal(report.querySelector('img'), null);
  assert.equal(w.document.querySelector('#check-ai').disabled, false);
  await w.document.querySelector('#config-form').onsubmit({ preventDefault() {} });
  assert.doesNotMatch(report.textContent, /Alibi\?/);
});

test('late probe response cannot restore private results after logout', async (t) => {
  let finish;
  const w = setup(t, (path) =>
    path === '/api/panel/test-ai'
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined,
  );
  await login(w);
  const pending = w.document.querySelector('#probe-form').onsubmit({ preventDefault() {} });
  await settle();
  await w.document.querySelector('#logout').onclick({ preventDefault() {} });
  finish(response({ active: true, output: 'PRIVATE-RESULT' }));
  await pending;
  assert.equal(w.document.querySelector('#workspace').hidden, true);
  assert.doesNotMatch(w.document.body.textContent, /PRIVATE-RESULT/);
});

test('failed logout keeps session available for retry and does not claim success', async (t) => {
  const w = setup(t, (path) =>
    path === '/api/panel/logout' ? response({ detail: 'Database unavailable' }, 503) : undefined,
  );
  await login(w);
  await w.document.querySelector('#logout').onclick({ preventDefault() {} });
  assert.equal(w.document.querySelector('#workspace').hidden, false);
  assert.match(w.document.querySelector('#notice').textContent, /Database unavailable/);
  assert.equal(w.document.querySelector('#logout').disabled, false);
});

test('user editor uses selected account, clears secrets, and separates destructive action', async (t) => {
  const w = setup(t, (path) =>
    path.startsWith('/api/panel/users?')
      ? response({
          users: [
            {
              id: 1,
              username: 'alice',
              display_name: '<script>bad</script>',
              login_method: 'password',
            },
          ],
          has_more: false,
        })
      : undefined,
  );
  await login(w);
  await w.document.querySelector('[data-menu=users]').onclick({ preventDefault() {} });
  assert.equal(w.document.querySelector('#user-rows script'), null);
  w.document.querySelector('#user-rows button').click();
  assert.equal(w.document.querySelector('#user-editor').open, true);
  assert.equal(w.document.querySelector('#edit-user-username').value, 'alice');
  w.document.querySelector('#user-new-password').value = 'secret-fixture';
  w.document.querySelector('#cancel-user-edit').click();
  assert.equal(w.document.querySelector('#user-editor').open, false);
  assert.equal(w.document.querySelector('#user-new-password').value, '');
  assert.equal(w.document.querySelector('#user-rows .danger').textContent, 'Hapus akun');
});

test('NPC brain menu shows the writer chain, reorders it, and saves method and priority', async (t) => {
  const chain = [
    {
      jalur: 'claude_bedrock',
      keadaan: 'ditolak',
      status: 'key ditolak (401)',
      model: 'anthropic.claude-opus-5-5',
      panggilan: 0,
    },
    {
      jalur: 'openrouter',
      keadaan: 'dipakai',
      status: 'siap',
      model: '<b>anthropic/claude-opus-5.5</b>',
      panggilan: 3,
      token_masuk: 900,
      token_keluar: 60,
      hasil_cek: { keadaan: 'berhasil', waktu: 1800000000, durasi_ms: 1250, detail: 'ok' },
    },
    {
      jalur: 'tautan',
      keadaan: 'istirahat',
      status: 'tidak terhubung',
      model: 'qwen3:14b',
      panggilan: 0,
      alamat: { host: 'llm-uji.trycloudflare.com', sumber: 'panel' },
    },
    {
      jalur: 'claude_api',
      keadaan: 'nonaktif',
      status: 'dinonaktifkan',
      model: null,
      panggilan: 0,
    },
  ];
  const status = {
    siap: true,
    gagal: false,
    detail: 'AI siap.',
    nlu: 'indobert',
    penulis: 'openrouter',
    model_penulis: 'anthropic/claude-opus-5.5',
    metode: 'campuran',
    penulis_diminta: 'otomatis',
    validasi: true,
    penulis_aktif: true,
    urutan_penulis: ['claude_bedrock', 'openrouter', 'tautan'],
    model_openrouter: '',
    rantai_penulis: chain,
    sedang_cek_penulis: true, // cek berjalan di latar → panel menjadwalkan refresh otomatis
    pertandingan_aktif: 2,
  };
  const pilihan = {
    metode: { campuran: 'Campuran', fuzzy: 'Fuzzy', utility: 'Utility', bt: 'BT', llm: 'LLM' },
    penulis: { otomatis: 'Rantai LLM', templat: 'Templat' },
    jalur_penulis: {
      claude_bedrock: { label: 'Claude · Amazon Bedrock', sumber: 'AMAZON_API_KEY di server' },
      claude_api: { label: 'Claude API · Anthropic', sumber: 'ANTHROPIC_API_KEY di server' },
      openrouter: { label: 'OpenRouter', sumber: 'API key di menu Konfigurasi AI' },
      tautan: { label: 'LLM sendiri lewat link', sumber: 'URL tunnel di menu Konfigurasi AI' },
    },
  };
  let saved,
    checked = 0;
  const w = setup(t, (path, options) => {
    if (path === '/api/panel/npc/cek-penulis') {
      checked++;
      return response({ status, pilihan });
    }
    if (path !== '/api/panel/npc') return undefined;
    if (options.method === 'PUT') {
      saved = JSON.parse(options.body);
      return response({ status: { ...status, metode: saved.metode }, pilihan });
    }
    return response({ status, pilihan });
  });
  // Refresh otomatis 3 detik ditangkap dan dijalankan manual agar tes cepat dan deterministik.
  const refreshes = [];
  w.setTimeout = (fn, ms) => (ms === 3000 ? refreshes.push(fn) : 0);
  w.clearTimeout = () => {};
  await login(w);
  await w.document.querySelector('[data-menu=npc]').onclick({ preventDefault() {} });
  const doc = w.document;
  assert.match(doc.querySelector('#npc-status').textContent, /IndoBERT/);
  assert.match(
    doc.querySelector('#npc-status').textContent,
    /OpenRouter \(anthropic\/claude-opus-5.5\)/,
  );
  assert.equal(doc.querySelector('#npc-method').value, 'campuran');
  const rows = () => [...doc.querySelectorAll('#npc-chain li')];
  assert.deepEqual(
    rows().map((row) => row.querySelector('strong').textContent),
    [
      '1. Claude · Amazon Bedrock',
      '2. OpenRouter',
      '3. LLM sendiri lewat link',
      'Claude API · Anthropic',
    ],
  );
  assert.match(rows()[0].textContent, /Ditolak.*key ditolak \(401\)/);
  assert.match(rows()[1].textContent, /3 panggilan · token 900\/60 sejak cek terakhir/);
  assert.match(rows()[1].textContent, /Hit berhasil.*Cek terakhir:.*1\.25 detik/);
  assert.match(rows()[2].textContent, /qwen3:14b · llm-uji\.trycloudflare\.com \(panel\)/);
  assert.match(rows()[2].textContent, /Istirahat.*tidak terhubung/);
  assert.equal(doc.querySelector('#npc-chain b'), null); // data server dirender sebagai teks
  // OpenRouter dinaikkan ke prioritas pertama, link LLM dimatikan, Claude API dinyalakan.
  rows()[1].querySelector('button[aria-label^="Naikkan"]').click();
  const toggle = (label) => {
    const box = rows()
      .find((row) => row.textContent.includes(label))
      .querySelector('input');
    box.checked = !box.checked;
    box.onchange();
  };
  toggle('LLM sendiri');
  toggle('Claude API');
  doc.querySelector('#npc-method').value = 'bt';
  doc.querySelector('#npc-method').dispatchEvent(new w.Event('change'));
  doc.querySelector('#npc-openrouter-model').value = ' anthropic/claude-sonnet-5.5 ';
  doc.querySelector('#npc-openrouter-model').dispatchEvent(new w.Event('input'));
  // Refresh otomatis (cek di latar) hanya memperbarui status; editan yang belum disimpan tetap.
  assert.ok(refreshes.length > 0);
  refreshes.splice(0).forEach((refresh) => refresh());
  await settle();
  assert.equal(doc.querySelector('#npc-method').value, 'bt');
  assert.equal(doc.querySelector('#npc-openrouter-model').value, ' anthropic/claude-sonnet-5.5 ');
  assert.equal(rows()[0].querySelector('strong').textContent, '1. OpenRouter');
  // Cek ulang memakai konfigurasi tersimpan: selama ada editan, diminta simpan dulu tanpa request.
  await doc.querySelector('#check-writers').onclick({ preventDefault() {} });
  assert.equal(checked, 0);
  assert.match(doc.querySelector('#notice').textContent, /Simpan perubahan dulu/);
  await doc.querySelector('#npc-form').onsubmit({ preventDefault() {} });
  assert.deepEqual(saved, {
    metode: 'bt',
    penulis: 'otomatis',
    validasi: true,
    urutan_penulis: ['openrouter', 'claude_bedrock', 'claude_api'],
    model_openrouter: 'anthropic/claude-sonnet-5.5',
  });
  assert.equal(doc.querySelector('#npc-method').value, 'bt');
  await doc.querySelector('#check-writers').onclick({ preventDefault() {} });
  assert.equal(checked, 1);
  assert.equal(doc.querySelector('#check-writers').disabled, true);
  status.sedang_cek_penulis = false;
  refreshes.splice(0).forEach((refresh) => refresh());
  await settle();
  assert.equal(doc.querySelector('#check-writers').disabled, false);
  assert.equal(doc.querySelector('#check-writers').textContent, 'Tes koneksi semua prioritas');
});

test('survey menu renders questions as text and edits scale meaning from the panel', async (t) => {
  const question = {
    id: 3,
    code: 'seru',
    prompt: '<b>Seberapa seru?</b>',
    kind: 'stars',
    scale_min: 1,
    scale_max: 6,
    label_min: 'Bosan',
    label_max: 'Seru',
    options: [],
    required: true,
    active: true,
    position: 10,
  };
  let saved;
  const w = setup(t, (path, options) => {
    if (path === '/api/panel/survey/summary')
      return response({
        questions: [question],
        distribution: [{ question_id: 3, value_number: 5, n: 2 }],
        per_method: [{ question_id: 3, method: 'fuzzy', n: 2, rata: 5 }],
        text_answers: [],
      });
    if (path === '/api/panel/survey/questions/3' && options.method === 'PUT') {
      saved = JSON.parse(options.body);
      return response({ id: 3, ...saved });
    }
    return undefined;
  });
  await login(w);
  await w.document.querySelector('[data-menu=survey]').onclick({ preventDefault() {} });
  const rows = w.document.querySelector('#survey-rows');
  assert.equal(rows.querySelector('b'), null);
  assert.match(rows.textContent, /1 = Bosan · 6 = Seru/);
  assert.match(rows.textContent, /rata-rata 5.00/);
  assert.match(w.document.querySelector('#survey-method-rows').textContent, /fuzzy/);
  rows.querySelector('button').click();
  assert.equal(w.document.querySelector('#survey-editor-box').open, true);
  w.document.querySelector('#survey-label-max').value = 'Seru sekali';
  await w.document.querySelector('#survey-form').onsubmit({ preventDefault() {} });
  assert.equal(saved.label_max, 'Seru sekali');
  assert.equal(saved.kind, 'stars');
  assert.equal(w.document.querySelector('#survey-editor-box').open, false);
});

test('checker room shows bots, filters per bot, and explains decisions as text', async (t) => {
  const evil = '<img src=x onerror=alert(1)>';
  const bot = (nama, role, metode, fase) => ({
    nama,
    role,
    metode,
    persona: 'santai',
    ronde: 2,
    fase,
  });
  const nox = {
    id: 'a'.repeat(32),
    created_at: '2026-09-30T10:00:00+00:00',
    sender: 'NOX',
    message: 'vote',
    stage: 'npc_brain',
    provider: 'otak:fuzzy',
    ringkas: { bot: bot('NOX', 'hitman', 'fuzzy', 'tribunal'), keputusan: ['vote → ECHO'] },
  };
  const echo = {
    id: 'b'.repeat(32),
    created_at: '2026-09-30T09:59:00+00:00',
    sender: 'ECHO',
    message: evil,
    stage: 'npc_brain',
    provider: 'otak:bt',
    ringkas: { bot: bot('ECHO', 'spy', 'bt', 'day'), keputusan: [`chat tuduh → ${evil}`] },
  };
  const human = { id: 'c'.repeat(32), sender: 'human', message: 'Halo', stage: 'complete' };
  const room = {
    kode: 'ROOM01',
    status: 'live',
    ronde: 2,
    fase: 'tribunal',
    komposisi: { hitman: 1, spy: 1, stalker: 1, civilian: 3 },
    manusia: 1,
    bot: [
      { ...bot('NOX', 'hitman', 'fuzzy'), status: 'aktif' },
      { ...bot('ECHO', 'spy', 'bt'), status: 'disandera' },
    ],
  };
  const fuzzyVote = {
    judul: 'Vote Tribunal',
    hasil: 'vote → ECHO (skor 0.85)',
    kandidat: { kolom: ['pemain', 'kambing_hitam'], baris: [['ECHO', 0.85]] },
    sistem: [
      {
        nama: 'kambing',
        arti: 'Kambing hitam terbaik.',
        input: [
          {
            nama: 'kecurigaan_publik',
            nilai: 0.685,
            derajat: { rendah: 0, sedang: 0.383, tinggi: 0.617 },
          },
          { nama: 'dukungan_suara', nilai: 1, derajat: { rendah: 0, sedang: 0, tinggi: 1 } },
        ],
        aturan: [['kecurigaan_publik=tinggi DAN dukungan_suara=tinggi', 'tinggi', 0.617]],
        keluaran: 85,
      },
    ],
    ambang: [['VOTE_TUNGGU_FRAKSI', 0.5, 'Hitman menunggu arah suara']],
  };
  const penjelasan = {
    nox: {
      bot: nox.ringkas.bot,
      keputusan: { vote: { aksi: 'vote', target: 'ECHO', skor: 0.85, alasan: [`ECHO ${evil}`] } },
      tersangka: { judul: 'Citra publik', kolom: ['pemain', 'tekanan'], baris: [['ECHO', 0.5]] },
      penalaran: { vote: fuzzyVote },
      engine: { action: 'vote', target: 'ECHO', ditolak: null },
      nlg: { status: 'tidak ada chat', keterangan: 'Chat hanya saat siang dan Tribunal.' },
    },
    echo: {
      bot: echo.ringkas.bot,
      keputusan: { chat: { kirim: true, aksi: 'tuduh', target: 'VEIL', alasan: [evil] } },
      penalaran: {
        chat: {
          judul: 'Chat',
          hasil: 'tuduh → VEIL',
          status_akar: 'SUKSES',
          cabang: 'tuduh (kuat)',
          jalur: {
            kolom: ['node', 'jenis', 'status'],
            baris: [
              ['bot dituduh baru', 'kondisi', 'GAGAL'],
              ['tuduh (kuat)', 'aksi', 'SUKSES'],
            ],
          },
        },
      },
      engine: { action: 'wait', target: null, ditolak: null },
      nlg: { status: 'terkirim', teks: evil, sumber: 'llm', penulis: 'openrouter', nlu: null },
    },
  };
  let detailCalls = 0;
  const w = setup(t, (path) => {
    if (path.startsWith('/api/panel/rooms'))
      return response({ rooms: [{ room_code: 'ROOM01', message_count: 3, live: true }] });
    if (path === '/api/panel/checker/ROOM01')
      return response({ traces: [nox, echo, human], events: [], room, has_more: false });
    if (path === `/api/panel/checker/ROOM01/jejak/${nox.id}`) {
      detailCalls++;
      return response({ ...nox, penjelasan: penjelasan.nox });
    }
    if (path === `/api/panel/checker/ROOM01/jejak/${echo.id}`)
      return response({ ...echo, penjelasan: penjelasan.echo });
    return undefined;
  });
  await login(w);
  await w.document.querySelector('[data-menu=checker]').onclick({ preventDefault() {} });
  const select = w.document.querySelector('#checker-room');
  select.value = 'ROOM01';
  await select.onchange({ preventDefault() {} });
  await settle();
  const summary = w.document.querySelector('#room-summary');
  const detail = w.document.querySelector('#trace-detail');
  assert.equal(summary.hidden, false);
  assert.match(summary.textContent, /Hitman × 1/);
  assert.match(summary.textContent, /Fuzzy Mamdani/);
  assert.match(summary.textContent, /vote → ECHO/); // keputusan terakhir NOX
  assert.match(detail.textContent, /Diterapkan ke engine/);
  const tabs = [...detail.querySelectorAll('.decision-tab')];
  assert.deepEqual(
    tabs.map((b) => b.textContent),
    ['Keputusan', 'Parameter', 'Penalaran Fuzzy Mamdani', 'NLG', 'Teknis'],
  );
  tabs[2].click();
  assert.match(detail.textContent, /kecurigaan_publik=tinggi DAN dukungan_suara=tinggi/);
  assert.match(detail.textContent, /Keluaran defuzzifikasi \(centroid, 0–100\): 85/);
  assert.equal(detail.querySelectorAll('meter').length, 6);
  // Klik nama bot di ringkasan: linimasa hanya berisi jejak bot itu, tab penalaran tetap terbuka.
  [...summary.querySelectorAll('.room-bot')].find((b) => b.textContent === 'ECHO').click();
  await settle();
  assert.equal(w.document.querySelector('#checker-filter').value, 'bot:ECHO');
  assert.equal(w.document.querySelectorAll('#traces .trace').length, 1);
  assert.match(detail.textContent, /Penalaran Behavior Tree/);
  assert.match(detail.textContent, /✗Syarat: bot dituduh baru/);
  assert.match(detail.textContent, /aksi terpilih: tuduh \(kuat\)/);
  [...detail.querySelectorAll('.decision-tab')].find((b) => b.textContent === 'NLG').click();
  assert.match(detail.textContent, /openrouter/);
  assert.equal(w.document.querySelector('#menu-checker img'), null);
  // Refresh dan kembali ke NOX tidak memuat ulang penjelasan yang sudah ada di cache.
  w.document.querySelector('#checker-filter').value = '';
  w.document.querySelector('#checker-filter').onchange();
  await w.document.querySelector('#refresh-checker').onclick({ preventDefault() {} });
  await settle();
  assert.equal(detailCalls, 1);
  assert.equal(w.document.querySelectorAll('#traces .trace').length, 3);
});
