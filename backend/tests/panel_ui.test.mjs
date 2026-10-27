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
      jalur: 'tautan',
      keadaan: 'istirahat',
      status: 'tidak terhubung',
      model: 'qwen3:14b',
      panggilan: 0,
      alamat: { host: 'llm-uji.trycloudflare.com', sumber: 'panel' },
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
    urutan_penulis: ['tautan', 'openrouter'],
    model_openrouter: '',
    model_tautan: '',
    model_tautan_bawaan: 'qwen3:14b',
    model_tautan_tersedia: ['qwen3:14b', 'qwen3:4b-instruct'],
    rantai_penulis: chain,
    sedang_cek_penulis: true, // cek berjalan di latar → panel menjadwalkan refresh otomatis
    pertandingan_aktif: 2,
  };
  const pilihan = {
    metode: { campuran: 'Campuran', fuzzy: 'Fuzzy', utility: 'Utility', bt: 'BT', llm: 'LLM' },
    penulis: { otomatis: 'Rantai LLM', templat: 'Templat' },
    jalur_penulis: {
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
    ['1. LLM sendiri lewat link', '2. OpenRouter'],
  );
  assert.match(rows()[0].textContent, /qwen3:14b · llm-uji\.trycloudflare\.com \(panel\)/);
  assert.match(rows()[0].textContent, /Istirahat.*tidak terhubung/);
  assert.match(rows()[1].textContent, /3 panggilan · token 900\/60 sejak cek terakhir/);
  assert.match(rows()[1].textContent, /Hit berhasil.*Cek terakhir:.*1\.25 detik/);
  assert.equal(doc.querySelector('#npc-chain b'), null); // data server dirender sebagai teks
  // OpenRouter dinaikkan ke prioritas pertama, lalu link LLM dimatikan.
  rows()[1].querySelector('button[aria-label^="Naikkan"]').click();
  const toggle = (label) => {
    const box = rows()
      .find((row) => row.textContent.includes(label))
      .querySelector('input');
    box.checked = !box.checked;
    box.onchange();
  };
  toggle('LLM sendiri');
  doc.querySelector('#npc-method').value = 'bt';
  doc.querySelector('#npc-method').dispatchEvent(new w.Event('change'));
  doc.querySelector('#npc-openrouter-model').value = ' anthropic/claude-sonnet-5.5 ';
  doc.querySelector('#npc-openrouter-model').dispatchEvent(new w.Event('input'));
  // Model link: bawaan Konfigurasi AI + model yang ditemukan di link.
  assert.deepEqual(
    [...doc.querySelectorAll('#npc-link-model option')].map((o) => o.textContent),
    ['Bawaan (qwen3:14b)', 'qwen3:14b', 'qwen3:4b-instruct'],
  );
  doc.querySelector('#npc-link-model').value = 'qwen3:4b-instruct';
  doc.querySelector('#npc-link-model').dispatchEvent(new w.Event('change'));
  // Refresh otomatis (cek di latar) hanya memperbarui status; editan yang belum disimpan tetap.
  assert.ok(refreshes.length > 0);
  refreshes.splice(0).forEach((refresh) => refresh());
  await settle();
  assert.equal(doc.querySelector('#npc-method').value, 'bt');
  assert.equal(doc.querySelector('#npc-openrouter-model').value, ' anthropic/claude-sonnet-5.5 ');
  assert.equal(doc.querySelector('#npc-link-model').value, 'qwen3:4b-instruct');
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
    urutan_penulis: ['openrouter'],
    model_openrouter: 'anthropic/claude-sonnet-5.5',
    model_tautan: 'qwen3:4b-instruct',
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
    ['Proses', 'Keputusan', 'Parameter', 'Penalaran Fuzzy Mamdani', 'NLG', 'Teknis'],
  );
  tabs[3].click();
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

test('simulation shows chat with NLU, live bot positions on the flowchart, and node explanations', async (t) => {
  const evil = '<img src=x onerror=alert(1)>';
  const bot = (nama, metode, role) => ({
    nama,
    metode,
    role,
    persona: 'kalem',
    ronde: 1,
    fase: 'day',
  });
  const pemain = [
    { nama: 'Andy', manusia: true, role: 'civilian', status: 'aktif' },
    { ...bot('NOX', 'fuzzy', 'hitman'), manusia: false, status: 'aktif' },
    { ...bot('ECHO', 'utility', 'spy'), manusia: false, status: 'aktif' },
    { ...bot('VEIL', 'bt', 'stalker'), manusia: false, status: 'aktif' },
  ];
  const ringkasan = { id: 'sim1', ronde: 1, fase: 'day', pemenang: null, detik: 2, durasi: 80 };
  const human = {
    id: 'h'.repeat(32),
    sender: 'Andy',
    message: `aku curiga NOX ${evil}`,
    stage: 'delivered',
    manusia: true,
    nlu: {
      intent: 'offend',
      confidence: 0.91,
      target: [{ pemain: 'NOX', relasi: 'offend', prob: 0.88 }],
      sumber: 'indobert',
      ms: 812,
    },
    timings: { nlu_ms: 812 },
  };
  const nox = {
    id: 'n'.repeat(32),
    sender: 'NOX',
    message: 'Aku bukan Hitman.',
    stage: 'npc_brain',
    provider: 'otak:fuzzy',
    duration_ms: 2500,
    timings: { nlu_ms: 3, logika_ms: 14, penjelasan_ms: 5, nlg_ms: 2400, llm_ms: 1900 },
    output: JSON.stringify({ nlg: { sumber: 'llm' } }),
    ringkas: { bot: bot('NOX', 'fuzzy', 'hitman'), keputusan: ['chat bela_diri'], nlg: 'terkirim' },
    penjelasan: {
      bot: bot('NOX', 'fuzzy', 'hitman'),
      nlu_dibaca: [{ pengirim: 'Andy', teks: 'aku curiga NOX', intent: 'offend', target: [] }],
      keputusan: { chat: { kirim: true, aksi: 'bela_diri', alasan: ['dituduh'] } },
      engine: { action: 'wait', target: null },
      nlg: { status: 'terkirim', teks: 'Aku bukan Hitman.', sumber: 'llm', penulis: 'tautan' },
    },
  };
  const echo = {
    id: 'e'.repeat(32),
    sender: 'ECHO',
    message: 'wait',
    stage: 'npc_brain',
    provider: 'otak:utility',
    duration_ms: 20,
    ringkas: { bot: bot('ECHO', 'utility', 'spy'), keputusan: [] },
    penjelasan: { bot: bot('ECHO', 'utility', 'spy'), nlg: { status: 'tidak ada chat' } },
  };
  let release;
  const reply = new Promise((resolve) => (release = resolve));
  const w = setup(t, async (path) => {
    if (path === '/api/panel/simulasi')
      return response({
        ...ringkasan,
        bisa_chat: true,
        pemain,
        jejak: [
          { id: 's'.repeat(32), sender: 'SISTEM', message: 'Permainan dimulai.', stage: 'sistem' },
        ],
      });
    if (path === '/api/panel/simulasi/sim1/progres')
      return response({
        berjalan: true,
        progres: { NOX: { tahap: 'llm', detik: 1.2 }, ECHO: { tahap: 'menunggu', detik: 1.2 } },
      });
    if (path === '/api/panel/kode/nlg_llm')
      return response({
        node: 'nlg_llm',
        kode: [
          {
            nama: 'nlg.PenulisBerantai.tulis',
            berkas: 'backend/app/module/npc_brain/generated/nlg.py',
            mulai: 897,
            akhir: 899,
            konstanta: false,
            parameter: [
              { nama: 'sistem', bawaan: null },
              { nama: 'pesan', bawaan: null },
            ],
            baris: [
              { no: 897, teks: '    def tulis(self, sistem, pesan):', jenis: 'param' },
              {
                no: 898,
                teks: `        teks, status = p.tulis(sistem, pesan)  # ${evil}`,
                jenis: 'inti',
                catatan: 'panggil LLM jalur ini',
              },
              { no: 899, teks: '        return teks, status', jenis: 'output' },
            ],
          },
        ],
      });
    if (path === '/api/panel/simulasi/sim1') {
      await reply;
      return response({
        ...ringkasan,
        detik: 5,
        bisa_chat: true,
        pemain,
        jejak: [human, nox, echo],
      });
    }
    return undefined;
  });
  await login(w);
  const doc = w.document;
  await doc.querySelector('[data-menu=simulasi]').onclick({ preventDefault() {} });
  assert.equal(doc.querySelectorAll('#sim-bots select').length, 4); // 5 pemain = kamu + 4 bot
  doc.querySelector('#sim-count').value = '4';
  doc.querySelector('#sim-count').onchange();
  assert.equal(doc.querySelectorAll('#sim-bots select').length, 3);
  await doc.querySelector('#sim-setup').onsubmit({ preventDefault() {} });
  assert.match(doc.querySelector('#sim-chat').textContent, /Permainan dimulai/);
  assert.match(doc.querySelector('#sim-status').textContent, /Utility AI/);
  doc.querySelector('#sim-message').value = human.message;
  const pending = doc.querySelector('#sim-form').onsubmit({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 550)); // satu polling progres
  const llm = [...doc.querySelectorAll('.flow-node')].find((b) =>
    /LLM menulis/.test(b.textContent),
  );
  assert.match(llm.textContent, /NOX 1.2s/);
  assert.match(doc.querySelector('#sim-flow').textContent, /Menunggu giliran: ECHO/);
  assert.match(doc.querySelector('#sim-flow').textContent, /Posisi: NOX di "LLM menulis kalimat"/);
  assert.match(doc.querySelector('#sim-chat .chat-human').textContent, /aku curiga NOX/); // tampil saat dikirim
  release();
  await pending;
  const chat = doc.querySelector('#sim-chat');
  assert.equal(chat.querySelector('img'), null);
  assert.match(
    chat.querySelector('.chat-human').textContent,
    /NLU: offend 0.91 · target NOX \(offend 0.88\)/,
  );
  assert.match(chat.querySelector('.chat-bot').textContent, /Aku bukan Hitman/);
  assert.match(chat.querySelector('.chat-step').textContent, /diam/);
  const detail = doc.querySelector('#sim-detail');
  assert.match(detail.textContent, /Reaksi bot sesudah pesan ini/);
  assert.match(detail.textContent, /NOX \(FL\): chat bela_diri/);
  // Klik reaksi NOX: tab Proses dan waktu tiap kotak flowchart mengikuti langkah NOX.
  [...detail.querySelectorAll('.room-bot')].find((b) => b.textContent.startsWith('NOX')).click();
  assert.match(detail.textContent, /4\. NLG: rencana chat menjadi kalimat/);
  const kotak = (judul) =>
    [...doc.querySelectorAll('.flow-node')].find((b) => b.textContent.includes(judul));
  assert.match(kotak('LLM menulis').textContent, /1\.90 dtk/);
  assert.ok(kotak('UA · Utility AI').classList.contains('flow-redup'));
  kotak('LLM menulis').click();
  const info = doc.querySelector('#flow-detail').textContent;
  assert.match(info, /Output yang diharapkan/);
  assert.match(info, /Aku bukan Hitman\./);
  await settle(); // kode asli dimuat dari server
  const kode = doc.querySelector('#flow-detail .kode-fungsi');
  assert.match(kode.textContent, /nlg\.PenulisBerantai\.tulis\(sistem, pesan\)/);
  assert.match(kode.textContent, /nlg\.py · baris 897–899/);
  assert.match(kode.textContent, /Output \(return\)return teks, status/);
  assert.equal(kode.querySelector('.kode-inti .kode-no').textContent, '898');
  assert.equal(kode.querySelector('.kode-tanda').textContent, '↑ panggil LLM jalur ini');
  assert.equal(kode.querySelector('img'), null); // kode ditampilkan sebagai teks
  assert.ok(kode.querySelector('.kode-param') && kode.querySelector('.kode-output'));
});

test('menu dokumen membuka semua dokumen sistem, AI, dan NLU di tab baru', async (t) => {
  const w = setup(t);
  await login(w);
  const doc = w.document;
  await doc.querySelector('[data-menu=dokumen]').onclick({ preventDefault() {} });
  assert.equal(doc.querySelector('#menu-dokumen').hidden, false);
  assert.equal(doc.querySelector('#menu-ai').hidden, true);
  const links = [...doc.querySelectorAll('#menu-dokumen a')];
  assert.deepEqual(
    links.map((a) => a.getAttribute('href')),
    [
      '/panel/dokumen/arsitektur',
      '/panel/dokumen/erd',
      '/panel/dokumen/proses-ai',
      '/panel/dokumen/diagram-alir-nlu',
      '/panel/dokumen/kode-nlu-intent',
      '/panel/dokumen/kode-nlu-target',
      '/panel/dokumen/diagram-alir-fuzzy',
      '/panel/dokumen/kode-fuzzy',
      '/panel/dokumen/diagram-alir-utility',
      '/panel/dokumen/kode-utility',
      '/panel/dokumen/diagram-alir-bt',
      '/panel/dokumen/kode-bt',
    ],
  );
  assert.ok(links.every((a) => a.target === '_blank' && a.rel === 'noopener'));
  // Dokumen dikelompokkan per bagian: gambaran sistem, NLU, lalu satu bagian per metode bot.
  assert.deepEqual(
    [...doc.querySelectorAll('#menu-dokumen .doc-section h3')].map((h) => h.textContent),
    [
      '1. Gambaran sistem',
      '2. NLU: bot membaca chat (IndoBERT)',
      '3. Otak bot: Fuzzy Logic',
      '4. Otak bot: Utility AI',
      '5. Otak bot: Behavior Tree',
    ],
  );
});

test('riwayat chat menampilkan intent, target, dan konteks IndoBERT sebagai teks', async (t) => {
  const evil = '<img src=x onerror=alert(1)>';
  const w = setup(t, (path) =>
    path.startsWith('/api/panel/history?')
      ? response({
          messages: [
            {
              id: 7,
              created_at: '2026-10-20T05:00:00',
              room_code: 'ABC123',
              round_number: 1,
              phase: 'day',
              sender_name: 'Andy',
              sender_kind: 'human',
              message: 'Aku curiga NOX.',
              nlu: {
                intent: 'offend',
                confidence: 0.91,
                target: [{ pemain: 'NOX', relasi: 'offend', prob: 0.88 }],
                konteks: [
                  { pengirim: 'ECHO', teks: evil, intent: 'neutral', target: [] },
                  {
                    pengirim: 'NOX',
                    teks: 'Aku bukan Hitman.',
                    intent: 'defend',
                    target: ['NOX: defend'],
                  },
                  {
                    pengirim: 'Andy',
                    teks: 'Vote NOX.',
                    intent: 'offend',
                    target: [{ pemain: 'NOX', relasi: 'offend' }],
                  },
                ],
              },
            },
          ],
          has_more: false,
          next_after_id: 7,
        })
      : undefined,
  );
  await login(w);
  const doc = w.document;
  await doc.querySelector('[data-menu=history]').onclick({ preventDefault() {} });
  await settle();
  const nlu = doc.querySelector('#history-rows tr td:nth-last-child(2)');
  assert.match(nlu.textContent, /offend 0.91 · target NOX \(offend 0.88\)/);
  const sel = doc.querySelector('#history-rows tr td:last-child');
  assert.match(sel.querySelector('summary').textContent, /3 chat sebelumnya/);
  const konteks = [...sel.querySelectorAll('li')].map((li) => li.textContent);
  assert.deepEqual(konteks, [
    `ECHO: ${evil} — neutral`,
    'NOX: Aku bukan Hitman. — defend · NOX: defend',
    'Andy: Vote NOX. — offend · NOX: offend',
  ]);
  assert.equal(sel.querySelector('img'), null); // isi chat tidak pernah menjadi HTML
});

test('dropdown bawaan diganti pilihan kustom yang tetap mengisi select asli', async (t) => {
  const w = setup(t);
  const doc = w.document;
  const asli = doc.querySelector('#history-sender');
  const wadah = asli.closest('.pilih');
  const tombol = wadah.querySelector('.pilih-tombol');
  assert.ok(asli.classList.contains('pilih-asli'));
  assert.equal(tombol.textContent, 'Semua (manusia + bot + arsip lama)');
  let berubah = 0;
  asli.addEventListener('change', () => berubah++);
  tombol.click();
  const daftar = wadah.querySelector('.pilih-daftar');
  assert.equal(daftar.hidden, false);
  assert.equal(tombol.getAttribute('aria-expanded'), 'true');
  [...daftar.children].find((li) => li.dataset.value === 'bot').click();
  assert.equal(asli.value, 'bot');
  assert.equal(berubah, 1);
  assert.equal(daftar.hidden, true);
  assert.match(tombol.textContent, /bot/i);
  // Keyboard: panah membuka dan memindah fokus, Enter memilih.
  tombol.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  daftar.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  daftar.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.equal(asli.value, [...asli.options][asli.selectedIndex].value);
  assert.notEqual(asli.value, 'bot');
  assert.equal(berubah, 2);
  // Nilai dari kode dan opsi yang ditambahkan belakangan ikut tampil.
  asli.value = 'human';
  assert.equal(tombol.textContent, 'Manusia saja');
  const ruang = doc.querySelector('#history-room');
  ruang.add(new w.Option('ABC123', 'ABC123'));
  await settle();
  assert.equal(ruang.closest('.pilih').querySelectorAll('.pilih-opsi').length, 2);
});
