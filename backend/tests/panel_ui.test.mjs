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

test('NPC brain menu shows server status and saves the selected method', async (t) => {
  const status = {
    siap: true,
    gagal: false,
    detail: 'AI siap.',
    nlu: 'indobert',
    penulis: 'templat',
    metode: 'campuran',
    penulis_diminta: 'otomatis',
    validasi: true,
    penulis_aktif: false,
    pertandingan_aktif: 2,
  };
  const pilihan = {
    metode: { campuran: 'Campuran', fuzzy: 'Fuzzy', utility: 'Utility', bt: 'BT', llm: 'LLM' },
    penulis: { otomatis: 'Otomatis', claude: 'Claude', templat: 'Templat' },
  };
  let saved;
  const w = setup(t, (path, options) => {
    if (path !== '/api/panel/npc') return undefined;
    if (options.method === 'PUT') {
      saved = JSON.parse(options.body);
      return response({ status: { ...status, metode: saved.metode }, pilihan });
    }
    return response({ status, pilihan });
  });
  await login(w);
  await w.document.querySelector('[data-menu=npc]').onclick({ preventDefault() {} });
  assert.match(w.document.querySelector('#npc-status').textContent, /IndoBERT/);
  assert.equal(w.document.querySelector('#npc-method').value, 'campuran');
  w.document.querySelector('#npc-method').value = 'bt';
  await w.document.querySelector('#npc-form').onsubmit({ preventDefault() {} });
  assert.deepEqual(saved, { metode: 'bt', penulis: 'otomatis', validasi: true });
  assert.equal(w.document.querySelector('#npc-method').value, 'bt');
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
