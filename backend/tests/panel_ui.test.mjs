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
