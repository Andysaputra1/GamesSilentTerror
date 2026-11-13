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
    penulis_diminta: 'otomatis',
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
      return response({ status, pilihan });
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
  assert.equal(doc.querySelector('#npc-openrouter-model').value, ' anthropic/claude-sonnet-5.5 ');
  assert.equal(doc.querySelector('#npc-link-model').value, 'qwen3:4b-instruct');
  assert.equal(rows()[0].querySelector('strong').textContent, '1. OpenRouter');
  // Cek ulang memakai konfigurasi tersimpan: selama ada editan, diminta simpan dulu tanpa request.
  await doc.querySelector('#check-writers').onclick({ preventDefault() {} });
  assert.equal(checked, 0);
  assert.match(doc.querySelector('#notice').textContent, /Simpan perubahan dulu/);
  await doc.querySelector('#npc-form').onsubmit({ preventDefault() {} });
  assert.equal(doc.querySelector('#npc-validate'), null);
  assert.deepEqual(saved, {
    penulis: 'otomatis',
    urutan_penulis: ['openrouter'],
    model_openrouter: 'anthropic/claude-sonnet-5.5',
    model_tautan: 'qwen3:4b-instruct',
  });
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
        per_method: [
          { question_id: 3, method: 'fuzzy', n: 2, rata: 5 },
          { question_id: 3, method: 'campuran', n: 4, rata: 3.5 }, // data lama
        ],
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
  assert.match(w.document.querySelector('#survey-method-rows').textContent, /campuran/);
  assert.equal(w.document.querySelector('#survey-position'), null); // posisi ditentukan server
  [...rows.querySelectorAll('button')].find((tombol) => tombol.textContent === 'Edit').click();
  assert.equal(w.document.querySelector('#survey-editor-box').open, true);
  w.document.querySelector('#survey-label-max').value = 'Seru sekali';
  await w.document.querySelector('#survey-form').onsubmit({ preventDefault() {} });
  assert.equal(saved.label_max, 'Seru sekali');
  assert.equal(saved.kind, 'stars');
  assert.equal('position' in saved, false);
  assert.equal(w.document.querySelector('#survey-editor-box').open, false);
});

test('survei: jumlah pengisi, diagram per pertanyaan, dan isian tiap nama dibuka lewat klik', async (t) => {
  const evil = '<img src=x onerror=alert(1)>';
  const dasar = { label_min: null, label_max: null, options: [], required: false, active: true };
  const questions = [
    { ...dasar, id: 1, code: 'kemiripan_manusia', prompt: 'Bot NPC berperilaku layaknya pemain manusia.',
      kind: 'scale', scale_min: 1, scale_max: 5, label_min: 'Sangat tidak setuju',
      label_max: 'Sangat setuju', required: true, position: 10 },
    { ...dasar, id: 2, code: 'aspek_perbaikan', prompt: 'Aspek yang perlu ditingkatkan?', kind: 'choice',
      scale_min: 1, scale_max: 6, options: ['Kewajaran bahasa', 'Lainnya'], position: 20 },
    { ...dasar, id: 3, code: 'saran_masukan', prompt: 'Saran Anda?', kind: 'text', scale_min: 1,
      scale_max: 6, position: 30 },
    { ...dasar, id: 4, code: 'lama', prompt: 'Pertanyaan lama', kind: 'text', scale_min: 1,
      scale_max: 6, active: false, position: 40 }, // nonaktif tanpa jawaban: tanpa diagram
  ]; // prettier-ignore
  const jawab = (q, value_number, value_text) => ({
    question_id: q.id, code: q.code, prompt: q.prompt, kind: q.kind, scale_min: q.scale_min,
    scale_max: q.scale_max, label_min: q.label_min, label_max: q.label_max, value_number, value_text,
  }); // prettier-ignore
  const [kemiripan, aspek, saran] = questions;
  const pengisi = {
    total_submissions: 2,
    total_people: 2,
    total_matches: 1,
    respondents: [
      { match_id: 'm1', room_code: 'ABC123', username: evil, role: 'spy', team: 'civilians',
        outcome: 'won', created_at: '2026-11-13T05:00:00', bots: 'NOX:fuzzy:santai | RAVEN:fuzzy:tegas',
        answers: [jawab(kemiripan, 5, null), jawab(aspek, null, `Lainnya: lebih ${evil}`),
          jawab(saran, null, evil)] },
      { match_id: 'm1', room_code: 'ABC123', username: 'budi', role: 'hitman', team: 'hitman',
        outcome: 'lost', created_at: '2026-11-13T04:59:00', bots: '',
        answers: [jawab(kemiripan, 4, null), jawab(aspek, null, 'Kewajaran bahasa'),
          jawab(saran, null, null)] },
    ],
  }; // prettier-ignore
  const w = setup(t, (path) => {
    if (path === '/api/panel/survey/summary')
      return response({ questions, distribution: [], per_method: [], text_answers: [] });
    if (path === '/api/panel/survey/respondents') return response(pengisi);
    return undefined;
  });
  await login(w);
  await w.document.querySelector('[data-menu=survey]').onclick({ preventDefault() {} });
  const doc = w.document;
  const teks = (daftar) => [...daftar].map((el) => el.textContent);

  // Kotak jumlah: kiriman, orang, pertandingan.
  assert.deepEqual(teks(doc.querySelectorAll('#survey-stats .metric strong')), ['2', '2', '1']);

  // Diagram: skala 1–5 dengan arti ujung, persentase dari jawaban pertanyaan itu.
  const diagram = [...doc.querySelectorAll('#survey-charts .survey-chart')];
  assert.equal(diagram.length, 3);
  assert.match(diagram[0].querySelector('figcaption').textContent, /2 jawaban · rata-rata 4\.50/);
  assert.deepEqual(teks(diagram[0].querySelectorAll('.survey-bar-label')), [
    '1 · Sangat tidak setuju', '2', '3', '4', '5 · Sangat setuju',
  ]); // prettier-ignore
  assert.deepEqual(teks(diagram[0].querySelectorAll('.survey-bar-value')), [
    '0 · 0%', '0 · 0%', '0 · 0%', '1 · 50%', '1 · 50%',
  ]); // prettier-ignore
  assert.equal(diagram[0].querySelectorAll('.survey-bar-fill')[4].style.width, '50%');
  assert.match(diagram[0].querySelectorAll('.survey-bar')[4].title, /1 dari 2 jawaban \(50%\)/);
  // Pilihan ganda: "Lainnya: …" masuk batang Lainnya, isiannya bisa dibuka.
  assert.deepEqual(teks(diagram[1].querySelectorAll('.survey-bar-value')), ['1 · 50%', '1 · 50%']);
  assert.match(diagram[1].querySelector('.survey-isian').textContent, /Isian Lainnya \(1\)/);
  // Teks bebas: isian kosong tidak dihitung.
  assert.match(diagram[2].querySelector('figcaption').textContent, /1 jawaban/);
  assert.match(diagram[2].querySelector('.survey-isian li').textContent, /onerror/);

  // Daftar pengisi: klik nama membuka dan menutup semua isiannya.
  const tombol = [...doc.querySelectorAll('#survey-respondent-rows .tombol-nama')];
  assert.deepEqual(teks(tombol), [evil, 'budi']);
  const rincian = tombol[0].closest('tr').nextElementSibling;
  assert.equal(rincian.hidden, true);
  tombol[0].onclick();
  assert.equal(rincian.hidden, false);
  assert.equal(tombol[0].getAttribute('aria-expanded'), 'true');
  assert.deepEqual(teks(rincian.querySelectorAll('dd')), [
    '5 dari 5 (Sangat setuju)', `Lainnya: lebih ${evil}`, evil,
  ]); // prettier-ignore
  assert.match(rincian.textContent, /NOX \(fuzzy, santai\), RAVEN \(fuzzy, tegas\)/);
  tombol[0].onclick();
  assert.equal(rincian.hidden, true);
  assert.match(tombol[1].closest('tr').textContent, /Hitman · kalah2 dari 3/);
  assert.equal(
    teks(tombol[1].closest('tr').nextElementSibling.querySelectorAll('dd'))[2],
    '— (tidak diisi)',
  );
  assert.equal(doc.querySelector('#menu-survey img'), null); // data pemain selalu teks
});

test('survei kosong: jumlah 0 dan daftar pengisi memberi tahu belum ada yang mengisi', async (t) => {
  const w = setup(t, (path) =>
    path === '/api/panel/survey/summary'
      ? response({ questions: [], distribution: [], per_method: [], text_answers: [] })
      : undefined,
  );
  await login(w);
  await w.document.querySelector('[data-menu=survey]').onclick({ preventDefault() {} });
  const doc = w.document;
  assert.deepEqual(
    [...doc.querySelectorAll('#survey-stats .metric strong')].map((s) => s.textContent),
    ['0', '0', '0'],
  );
  assert.match(doc.querySelector('#survey-respondent-rows').textContent, /Belum ada yang mengisi/);
});

test('urutan survei: seret, ▲▼, Alt+panah tersimpan; gagal simpan memulihkan urutan', async (t) => {
  const questions = [1, 2, 3].map((id) => ({
    id,
    code: `q${id}`,
    prompt: `Pertanyaan ${id}`,
    kind: id === 3 ? 'choice' : 'text',
    scale_min: 1,
    scale_max: 6,
    label_min: null,
    label_max: null,
    options: id === 3 ? ['Lebih cepat', 'Lainnya'] : [],
    required: false,
    active: id !== 2, // pertanyaan nonaktif ikut diurutkan
    position: id * 10,
  }));
  const saved = [];
  let gagal = false;
  const w = setup(t, (path, options) => {
    if (path === '/api/panel/survey/summary')
      return response({ questions, distribution: [], per_method: [], text_answers: [] });
    if (path === '/api/panel/survey/questions/order' && options.method === 'PUT') {
      saved.push(JSON.parse(options.body).ids);
      return gagal
        ? response({ detail: 'Database survei belum siap.' }, 503)
        : response({ questions: [] });
    }
    return undefined;
  });
  await login(w);
  await w.document.querySelector('[data-menu=survey]').onclick({ preventDefault() {} });
  const doc = w.document;
  const status = doc.querySelector('#survey-order-status');
  const baris = (id) => doc.querySelector(`#survey-rows tr[data-id="${id}"]`);
  const urutan = () =>
    [...doc.querySelectorAll('#survey-rows tr')].map((tr) => Number(tr.dataset.id));
  const nomor = () =>
    [...doc.querySelectorAll('#survey-rows .urutan-nomor')].map((n) => n.textContent);
  // jsdom tanpa DragEvent; getBoundingClientRect bernilai 0, jadi clientY > 0 = separuh bawah.
  const seret = (jenis, sasaran, clientY = 0) =>
    sasaran.dispatchEvent(new w.MouseEvent(jenis, { bubbles: true, cancelable: true, clientY }));
  assert.deepEqual(urutan(), [1, 2, 3]);
  assert.deepEqual(nomor(), ['1', '2', '3']);
  assert.match(baris(3).textContent, /Lainnya \(isian bebas\)/);
  assert.equal(baris(1).querySelector('.urutan-naik').disabled, true);
  assert.equal(baris(3).querySelector('.urutan-turun').disabled, true);

  // Seret baris 1 ke bawah baris 3: penanda tempat jatuh muncul, lalu urutan baru disimpan.
  seret('dragstart', baris(1).querySelector('.pegangan-seret'));
  assert.ok(baris(1).classList.contains('sedang-diseret'));
  // Di atas baris yang sedang diseret tidak ada penanda.
  seret('dragover', baris(1).querySelector('td'), 5);
  assert.equal(doc.querySelector('.jatuh-sebelum, .jatuh-sesudah'), null);
  seret('dragover', baris(3).querySelector('td'), -5);
  assert.ok(baris(3).classList.contains('jatuh-sebelum'));
  seret('dragover', baris(3).querySelector('td'), 5);
  assert.ok(baris(3).classList.contains('jatuh-sesudah'));
  assert.equal(baris(3).classList.contains('jatuh-sebelum'), false);
  seret('drop', baris(3).querySelector('td'), 5);
  assert.equal(status.textContent, 'Menyimpan…');
  seret('dragend', baris(1).querySelector('.pegangan-seret'));
  await settle();
  assert.deepEqual(urutan(), [2, 3, 1]);
  assert.deepEqual(saved, [[2, 3, 1]]);
  assert.deepEqual(nomor(), ['1', '2', '3']);
  assert.equal(status.textContent, 'Tersimpan');
  assert.equal(doc.querySelector('.jatuh-sebelum, .jatuh-sesudah, .sedang-diseret'), null);
  // Seret yang tidak berawal dari pegangan tidak memindah apa pun.
  seret('dragstart', baris(2).querySelector('button'));
  seret('dragover', baris(1).querySelector('td'), 5);
  seret('drop', baris(1).querySelector('td'), 5);
  await settle();
  assert.equal(saved.length, 1);

  // Tombol ▲ dan Alt+↓; fokus tetap di baris yang dipindah.
  const naik = baris(1).querySelector('.urutan-naik');
  naik.focus();
  naik.click();
  await settle();
  assert.deepEqual(urutan(), [2, 1, 3]);
  assert.equal(doc.activeElement, naik);
  baris(2)
    .querySelector('.urutan-turun')
    .dispatchEvent(
      new w.KeyboardEvent('keydown', { key: 'ArrowDown', altKey: true, bubbles: true }),
    );
  await settle();
  assert.deepEqual(urutan(), [1, 2, 3]);
  assert.deepEqual(saved.slice(1), [
    [2, 1, 3],
    [1, 2, 3],
  ]);
  // Ujung tabel: tidak ada request.
  baris(1)
    .querySelector('.urutan-turun')
    .dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowUp', altKey: true, bubbles: true }));
  await settle();
  assert.equal(saved.length, 3);

  // Dua perubahan cepat: yang kedua menunggu simpan pertama, lalu dikirim sebagai urutan terbaru.
  baris(3).querySelector('.urutan-naik').click();
  baris(3).querySelector('.urutan-naik').click();
  await settle();
  assert.deepEqual(saved.slice(3), [
    [1, 3, 2],
    [3, 1, 2],
  ]);
  assert.equal(status.textContent, 'Tersimpan');

  // Gagal simpan: tabel kembali ke urutan tersimpan terakhir dan pesan error tampil.
  gagal = true;
  baris(2).querySelector('.urutan-naik').click();
  assert.deepEqual(urutan(), [3, 2, 1]);
  assert.equal(status.textContent, 'Menyimpan…');
  await settle();
  assert.deepEqual(urutan(), [3, 1, 2]);
  assert.deepEqual(nomor(), ['1', '2', '3']);
  assert.match(status.textContent, /gagal disimpan/);
  assert.match(status.textContent, /Database survei belum siap/);
  assert.match(doc.querySelector('#notice').textContent, /Database survei belum siap/);
});

test('survey menu deletes answers only after typed confirmation and a question after confirm', async (t) => {
  const question = {
    id: 3,
    code: 'lama',
    prompt: 'Pertanyaan lama',
    kind: 'text',
    scale_min: 1,
    scale_max: 6,
    label_min: null,
    label_max: null,
    options: [],
    required: false,
    active: true,
    position: 10,
  };
  const deleted = [];
  const w = setup(t, (path, options) => {
    if (path === '/api/panel/survey/summary')
      return response({ questions: [question], distribution: [], per_method: [], text_answers: [] });
    if (options.method === 'DELETE') {
      deleted.push(path);
      return response({ deleted: 72 });
    }
    return undefined;
  });
  await login(w);
  await w.document.querySelector('[data-menu=survey]').onclick({ preventDefault() {} });
  const clean = w.document.querySelector('#survey-clean');
  const confirmation = w.document.querySelector('#survey-clean-confirm');
  confirmation.value = 'bersihkan';
  await clean.onclick({ preventDefault() {} });
  assert.deepEqual(deleted, []);
  confirmation.value = 'BERSIHKAN';
  await clean.onclick({ preventDefault() {} });
  assert.deepEqual(deleted, ['/api/panel/survey/responses']);
  assert.equal(confirmation.value, '');
  deleted.length = 0;
  const remove = () => w.document.querySelector('#survey-rows button.danger');
  w.confirm = () => false;
  await remove().onclick({ preventDefault() {} });
  assert.deepEqual(deleted, []);
  w.confirm = () => true;
  await remove().onclick({ preventDefault() {} });
  assert.deepEqual(deleted, ['/api/panel/survey/questions/3']);
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
      nlg: { status: 'terkirim', teks: evil, sumber: 'llm', penulis: 'openrouter' },
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

test('jejak lama Utility AI dan Behavior Tree tetap terbuka walau metodenya sudah diarsipkan', async (t) => {
  const bot = (nama, metode) => ({
    nama,
    role: 'spy',
    metode,
    persona: 'santai',
    ronde: 2,
    fase: 'day',
  });
  const jejak = (id, nama, metode) => ({
    id: id.repeat(32),
    created_at: '2026-10-20T10:00:00+00:00',
    sender: nama,
    message: 'wait',
    stage: 'npc_brain',
    provider: `otak:${metode}`,
    ringkas: { bot: bot(nama, metode), keputusan: ['chat tuduh → VEIL'] },
  });
  const nox = jejak('a', 'NOX', 'utility');
  const echo = jejak('b', 'ECHO', 'bt');
  const room = {
    kode: 'LAMA01',
    status: 'arsip',
    ronde: 2,
    fase: 'finished',
    manusia: 1,
    bot: [
      { ...bot('NOX', 'utility'), status: 'aktif' },
      { ...bot('ECHO', 'bt'), status: 'aktif' },
    ],
  };
  const penjelasan = {
    [nox.id]: {
      bot: bot('NOX', 'utility'),
      keputusan: { chat: { kirim: true, aksi: 'tuduh', target: 'VEIL', alasan: ['x'] } },
      tersangka: {
        judul: 'Tersangka',
        kolom: ['pemain', 'kecurigaan_mentah'],
        baris: [['VEIL', 0.5]],
      },
      penalaran: {
        kecurigaan: {
          judul: 'Kecurigaan',
          hasil: 'kecurigaan akhir 0.50',
          komponen: {
            kolom: ['bukti', 'nilai', 'bobot', 'kontribusi'],
            baris: [['tekanan', 1, 0.5, 0.5]],
          },
          catatan: 'Noisy-OR',
        },
        chat: {
          judul: 'Chat',
          jenis: 'utility',
          hasil: 'tuduh → VEIL (nilai 0.70)',
          kandidat: {
            kolom: ['aksi', 'target', 'bobot', 'pertimbangan', 'utilitas'],
            baris: [['tuduh', 'VEIL', 1, 'kecurigaan=0.70', 0.7]],
          },
          ambang: [['UTILITAS_TUNGGU', 0.3, 'utilitas diam']],
        },
      },
      engine: { action: 'wait', target: null, ditolak: null },
      nlg: { status: 'tidak ada chat', keterangan: 'x' },
    },
    [echo.id]: {
      bot: bot('ECHO', 'bt'),
      keputusan: {},
      penalaran: {
        kecurigaan: {
          judul: 'Kecurigaan',
          hasil: 'kecurigaan akhir 0.60',
          bendera: {
            kolom: ['bendera', 'nilai', 'ambang', 'poin', 'aktif'],
            baris: [['tekanan', 0.6, 0.5, 2, true]],
          },
          catatan: 'Total poin 3',
        },
        chat: {
          judul: 'Chat',
          jenis: 'bt',
          hasil: 'tuduh → VEIL',
          status_akar: 'SUKSES',
          cabang: 'tuduh (kuat)',
          jalur: {
            kolom: ['node', 'jenis', 'status'],
            baris: [['tuduh (kuat)', 'aksi', 'SUKSES']],
          },
        },
      },
      engine: { action: 'wait', target: null, ditolak: null },
      nlg: { status: 'tidak ada chat', keterangan: 'x' },
    },
  };
  const w = setup(t, (path) => {
    if (path.startsWith('/api/panel/rooms'))
      return response({ rooms: [{ room_code: 'LAMA01', message_count: 1, live: false }] });
    if (path === '/api/panel/checker/LAMA01')
      return response({ traces: [nox, echo], events: [], room, has_more: false });
    const id = path.split('/jejak/')[1];
    return id
      ? response({
          ...jejak(id[0], id[0] === 'a' ? 'NOX' : 'ECHO', id[0] === 'a' ? 'utility' : 'bt'),
          penjelasan: penjelasan[id],
        })
      : undefined;
  });
  await login(w);
  const doc = w.document;
  // Legenda tetap menjelaskan metode lama, dengan tanda jejak lama.
  assert.match(doc.querySelector('#checker-legend').textContent, /Utility AI \(jejak lama\)/);
  assert.match(doc.querySelector('#checker-legend').textContent, /Behavior Tree \(jejak lama\)/);
  await doc.querySelector('[data-menu=checker]').onclick({ preventDefault() {} });
  const select = doc.querySelector('#checker-room');
  select.value = 'LAMA01';
  await select.onchange({ preventDefault() {} });
  await settle();
  const summary = doc.querySelector('#room-summary');
  const detail = doc.querySelector('#trace-detail');
  assert.match(summary.textContent, /Utility AI \(jejak lama\)/);
  assert.match(summary.textContent, /Behavior Tree \(jejak lama\)/);
  const tab = (judul) =>
    [...detail.querySelectorAll('.decision-tab')].find((b) => b.textContent.startsWith(judul));
  [...summary.querySelectorAll('.room-bot')].find((b) => b.textContent === 'NOX').click();
  await settle();
  tab('Penalaran Utility AI').click();
  assert.match(detail.textContent, /Komponen noisy-OR/);
  assert.match(detail.textContent, /kecurigaan=0\.70/);
  assert.match(detail.textContent, /UTILITAS_TUNGGU/);
  [...summary.querySelectorAll('.room-bot')].find((b) => b.textContent === 'ECHO').click();
  await settle();
  tab('Penalaran Behavior Tree').click();
  assert.match(detail.textContent, /Bendera merah/);
  assert.match(detail.textContent, /aksi terpilih: tuduh \(kuat\)/);
  assert.match(detail.textContent, /✓Aksi: tuduh \(kuat\)/);
});

test('jejak lama dengan validasi IndoBERT tetap terbaca, jejak baru tidak memuat barisnya', async (t) => {
  const bot = (nama) => ({
    nama,
    role: 'spy',
    metode: 'fuzzy',
    persona: 'santai',
    ronde: 2,
    fase: 'day',
  });
  const jejak = (id, nama, timings) => ({
    id: id.repeat(32),
    created_at: '2026-10-20T10:00:00+00:00',
    sender: nama,
    message: 'Aku curiga VEIL.',
    stage: 'npc_brain',
    provider: 'otak:fuzzy',
    timings,
    ringkas: { bot: bot(nama), keputusan: ['chat tuduh → VEIL'], nlg: 'terkirim' },
  });
  const lama = jejak('a', 'NOX', { nlg_ms: 6000, llm_ms: 2000, validasi_ms: 4000 });
  const baru = jejak('b', 'ECHO', { nlg_ms: 2001, llm_ms: 2000, aturan_ms: 1 });
  const nlg = {
    status: 'terkirim',
    teks: 'Aku curiga VEIL.',
    sumber: 'llm',
    penulis: 'openrouter',
    lolos_aturan: true,
    pelanggaran: [],
  };
  const isi = (nama, hasil) => ({
    bot: bot(nama),
    keputusan: {},
    engine: { action: 'wait', target: null, ditolak: null },
    nlg: hasil,
  });
  const penjelasan = {
    [lama.id]: isi('NOX', {
      ...nlg,
      lolos_nlu: false,
      nlu: { intent_prediksi: 'neutral', confidence: 0.7, target_prediksi: [['VEIL', 'offend']] },
    }),
    [baru.id]: isi('ECHO', nlg),
  };
  const room = {
    kode: 'LAMA02',
    status: 'arsip',
    ronde: 2,
    fase: 'finished',
    manusia: 1,
    bot: [
      { ...bot('NOX'), status: 'aktif' },
      { ...bot('ECHO'), status: 'aktif' },
    ],
  };
  const w = setup(t, (path) => {
    if (path.startsWith('/api/panel/rooms'))
      return response({ rooms: [{ room_code: 'LAMA02', message_count: 2, live: false }] });
    if (path === '/api/panel/checker/LAMA02')
      return response({ traces: [lama, baru], events: [], room, has_more: false });
    const id = path.split('/jejak/')[1];
    return id
      ? response({ ...(id === lama.id ? lama : baru), penjelasan: penjelasan[id] })
      : undefined;
  });
  await login(w);
  const doc = w.document;
  await doc.querySelector('[data-menu=checker]').onclick({ preventDefault() {} });
  const select = doc.querySelector('#checker-room');
  select.value = 'LAMA02';
  await select.onchange({ preventDefault() {} });
  await settle();
  const summary = doc.querySelector('#room-summary');
  const detail = doc.querySelector('#trace-detail');
  const tab = (judul) =>
    [...detail.querySelectorAll('.decision-tab')].find((b) => b.textContent === judul).click();
  const pilih = async (nama) => {
    [...summary.querySelectorAll('.room-bot')].find((b) => b.textContent === nama).click();
    await settle();
  };
  await pilih('NOX');
  tab('Proses');
  assert.match(detail.textContent, /Aturan \+ templat4\.00 dtk/);
  tab('NLG');
  assert.match(detail.textContent, /Lolos validasi IndoBERT/);
  assert.match(detail.textContent, /Intent terbacaneutral \(0\.7\)/);
  assert.match(detail.textContent, /VEIL: offend/);
  await pilih('ECHO');
  tab('Proses');
  assert.match(detail.textContent, /Aturan \+ templat1\.0 ms/);
  tab('NLG');
  assert.match(detail.textContent, /Lolos aturan/);
  assert.doesNotMatch(detail.textContent, /validasi IndoBERT|Intent terbaca|Target terbaca/);
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
    { ...bot('ECHO', 'fuzzy', 'spy'), manusia: false, status: 'aktif' },
    { ...bot('VEIL', 'fuzzy', 'stalker'), manusia: false, status: 'aktif' },
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
    timings: {
      nlu_ms: 3,
      logika_ms: 14,
      penjelasan_ms: 5,
      nlg_ms: 2400,
      llm_ms: 1900,
      aturan_ms: 500,
    },
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
    provider: 'otak:fuzzy',
    duration_ms: 20,
    ringkas: { bot: bot('ECHO', 'fuzzy', 'spy'), keputusan: [] },
    penjelasan: { bot: bot('ECHO', 'fuzzy', 'spy'), nlg: { status: 'tidak ada chat' } },
  };
  let release, mulai;
  const reply = new Promise((resolve) => (release = resolve));
  const w = setup(t, async (path, options) => {
    if (path === '/api/panel/simulasi') {
      mulai = JSON.parse(options.body);
      return response({
        ...ringkasan,
        bisa_chat: true,
        pemain,
        jejak: [
          { id: 's'.repeat(32), sender: 'SISTEM', message: 'Permainan dimulai.', stage: 'sistem' },
        ],
      });
    }
    if (path === '/api/panel/simulasi/sim1/progres')
      return response({
        berjalan: true,
        progres: {
          NOX: { tahap: 'llm', detik: 1.2 },
          ECHO: { tahap: 'menunggu', detik: 1.2 },
          VEIL: { tahap: 'aturan', detik: 0.1 },
        },
      });
    if (path === '/api/panel/kode/nlg_llm')
      return response({
        node: 'nlg_llm',
        kode: [
          {
            nama: 'nlg.PenulisBerantai.tulis',
            berkas: 'backend/app/bot/nlg.py',
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
  doc.querySelector('#sim-count').value = '4'; // 4 pemain = kamu + 3 bot
  await doc.querySelector('#sim-setup').onsubmit({ preventDefault() {} });
  assert.equal(mulai.jumlah_bot, 3);
  assert.match(doc.querySelector('#sim-chat').textContent, /Permainan dimulai/);
  assert.match(doc.querySelector('#sim-status').textContent, /Fuzzy Mamdani/);
  doc.querySelector('#sim-message').value = human.message;
  const pending = doc.querySelector('#sim-form').onsubmit({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 550)); // satu polling progres
  const llm = [...doc.querySelectorAll('.flow-node')].find((b) =>
    /LLM menulis/.test(b.textContent),
  );
  assert.match(llm.textContent, /NOX 1.2s/);
  const cek = [...doc.querySelectorAll('.flow-node')].find((b) => /Cek aturan/.test(b.textContent));
  assert.match(cek.textContent, /VEIL 0.1s/);
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
  assert.match(kotak('Cek aturan').textContent, /500\.0 ms/);
  assert.equal(kotak('FL · Fuzzy Mamdani').classList.contains('flow-redup'), false);
  assert.match(kotak('FL · Fuzzy Mamdani').textContent, /14\.0 ms/);
  assert.ok(kotak('Cadangan templat').classList.contains('flow-redup')); // kalimat dari LLM
  assert.equal(kotak('UA · Utility AI'), undefined);
  assert.equal(kotak('BT · Behavior Tree'), undefined);
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
      '/panel/dokumen/peta-dokumen',
      '/panel/dokumen/arsitektur',
      '/panel/dokumen/erd',
      '/panel/dokumen/proses-ai',
      '/panel/dokumen/bedah-alur',
      '/panel/dokumen/dataset-nlu',
      '/panel/dokumen/diagram-alir-nlu',
      '/panel/dokumen/kode-nlu-intent',
      '/panel/dokumen/kode-nlu-target',
      '/panel/dokumen/diagram-alir-fuzzy',
      '/panel/dokumen/bedah-otak-fuzzy',
      '/panel/dokumen/cara-kerja-bot',
      '/panel/dokumen/kode-fuzzy',
      '/panel/dokumen/kode-nlg',
    ],
  );
  assert.ok(links.every((a) => a.target === '_blank' && a.rel === 'noopener'));
  // Setiap kartu bertanda sumber: Training (notebook skripsi), Backend (kode game), atau Panduan (peta).
  assert.deepEqual(
    links.map((a) => [a.dataset.sumber, a.querySelector('.doc-src').textContent]),
    [
      ['panduan', 'Panduan'],
      ['backend', 'Backend'],
      ['backend', 'Backend'],
      ['backend', 'Backend'],
      ['backend', 'Backend'],
      ['training', 'Training'],
      ['training', 'Training'],
      ['training', 'Training'],
      ['training', 'Training'],
      ['training', 'Training'],
      ['backend', 'Backend'],
      ['backend', 'Backend'],
      ['training', 'Training'],
      ['training', 'Training'],
    ],
  );
  // Dokumen dikelompokkan per bagian: gambaran sistem, NLU, lalu otak bot Fuzzy.
  assert.deepEqual(
    [...doc.querySelectorAll('#menu-dokumen .doc-section h3')].map((h) => h.textContent),
    ['1. Gambaran sistem', '2. NLU: bot membaca chat (IndoBERT)', '3. Otak bot: Fuzzy Logic dan NLG'],
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
