// Tests the extension's background worker with a mocked chrome API. Run with: node --test extension/tests
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function load(snapshot) {
  const L = {};
  const on = (name) => ({ addListener: (fn) => { L[name] = fn; } });
  const store = {};
  const chrome = {
    storage: { session: { get: async () => ({}), set: async (o) => Object.assign(store, o), remove: async () => {} } },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    tabs: { get: async (id) => ({ id, url: 'https://shop.example.com/', title: 'Shop' }), reload: async () => {}, onRemoved: { addListener() {} } },
    webRequest: { onBeforeRequest: on('before'), onBeforeRedirect: on('redirect'), onResponseStarted: on('started'), onCompleted: on('completed'), onErrorOccurred: on('error') },
    scripting: { executeScript: async () => [{ result: snapshot }] },
    cookies: { getAll: async () => [{ name: '_ga', domain: '.example.com', path: '/', secure: false, httpOnly: false, sameSite: 'unspecified' }] },
    runtime: { getManifest: () => ({ version: '9.9.9' }), onMessage: on('message') },
  };
  const ctx = vm.createContext({ chrome, console, setTimeout, clearTimeout, TextDecoder, URL, URLSearchParams, Date, Math, Promise, Object, Number, String, Set, Map, Array, JSON });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'background.js'), 'utf8'), ctx);
  const send = (msg) => new Promise((r) => L.message(msg, null, r));
  return { L, ctx, send };
}

const SNAP = {
  globals: ['dataLayer'], perf: { fcp: 800 }, dataLayer: [{ t: 1, v: { event: 'page_ready' } }],
  console: [{ type: 'error', text: 'boom' }], errors: [], storage: {}, scripts: [{ src: 'https://shop.example.com/app.js' }], meta: [], iframes: [], links: {},
  creators: { 'https://cdn.tags.net/tag.js': 'https://www.googletagmanager.com/gtm.js?id=GTM-1', 'https://cdn.tags.net/inline.js': 'inline' },
  html: '<html>hello</html>', title: 'Shop', lang: 'en', userAgent: 'test',
};

function fire(L, tab, id, url, type, ts, extra = {}) {
  const d = { requestId: id, tabId: tab, url, method: 'GET', type, timeStamp: ts, initiator: 'https://shop.example.com', ...extra };
  L.before(d);
  L.started({ ...d, statusCode: 200, ip: '1.2.3.4', fromCache: false, responseHeaders: extra.headers || [] });
  L.completed({ ...d, statusCode: 200, timeStamp: ts + 20 });
}

test('records requests, resolves who loaded each script, and builds a gga-capture-1 file', async () => {
  const { L, send } = load(SNAP);
  assert.strictEqual((await send({ cmd: 'start', tabId: 5, reload: true })).ok, true);
  fire(L, 5, 'r1', 'https://shop.example.com/', 'main_frame', 1000, { headers: [{ name: 'Server', value: 'nginx' }, { name: 'Content-Security-Policy', value: "default-src 'self'" }] });
  fire(L, 5, 'r2', 'https://shop.example.com/app.js', 'script', 1100);
  fire(L, 5, 'r3', 'https://cdn.tags.net/tag.js', 'script', 1200);
  fire(L, 5, 'r4', 'https://cdn.tags.net/inline.js', 'script', 1250);
  const ga = { requestBody: { raw: [{ bytes: new TextEncoder().encode('en=page_view&dl=x') }] } };
  L.before({ requestId: 'r5', tabId: 5, url: 'https://www.google-analytics.com/g/collect?v=2&tid=G-X', method: 'POST', type: 'ping', timeStamp: 1300, ...ga });
  L.error({ requestId: 'r6', tabId: 5, url: 'https://blocked.example.net/x.js', timeStamp: 1350, error: 'net::ERR_BLOCKED_BY_CLIENT' });
  L.before({ requestId: 'r6', tabId: 5, url: 'https://blocked.example.net/x.js', method: 'GET', type: 'script', timeStamp: 1340 });
  await new Promise((r) => setTimeout(r, 20));

  const st = await send({ cmd: 'status', tabId: 5 });
  assert.strictEqual(st.recording, true);
  assert.strictEqual(st.summary.requests, 6);
  assert.strictEqual(JSON.stringify(st.summary.ga4), '["G-X"]');

  const res = await send({ cmd: 'stop', tabId: 5 });
  assert.strictEqual(res.ok, true);
  const c = res.capture;
  assert.strictEqual(c.schema, 'gga-capture-1');
  assert.strictEqual(c.source, 'extension');
  assert.strictEqual(c.extension_version, '9.9.9');
  assert.strictEqual(c.status, 200);
  assert.strictEqual(c.doc_headers['content-security-policy'], "default-src 'self'");
  assert.strictEqual(c.requests.length, 6);
  const by = (u) => c.requests.find((r) => r.url === u);
  assert.strictEqual(by('https://shop.example.com/app.js').initiator_type, 'parser');
  assert.strictEqual(by('https://cdn.tags.net/tag.js').initiator_url, 'https://www.googletagmanager.com/gtm.js?id=GTM-1');
  assert.strictEqual(by('https://cdn.tags.net/inline.js').initiator_url, 'https://shop.example.com/');
  assert.match(by('https://www.google-analytics.com/g/collect?v=2&tid=G-X').post, /en=page_view/);
  assert.strictEqual(c.console[0].text, 'boom');
  assert.strictEqual(c.cookies[0].name, '_ga');
  assert.ok(c.html.includes('hello'));
  assert.ok(c.requests.every((r) => !('_key' in r)));
});

test('marking the cookie banner labels later requests as after consent', async () => {
  const { L, send } = load(SNAP);
  await send({ cmd: 'start', tabId: 9 });
  fire(L, 9, 'a', 'https://shop.example.com/', 'main_frame', 100);
  assert.strictEqual((await send({ cmd: 'mark', tabId: 9 })).ok, true);
  fire(L, 9, 'b', 'https://ads.example.net/pixel.js', 'script', 200);
  const c = (await send({ cmd: 'stop', tabId: 9 })).capture;
  assert.strictEqual(JSON.stringify(c.requests.map((r) => r.phase)), '["load","after_consent"]');
  assert.strictEqual(c.consent.tested, true);
  assert.strictEqual(c.consent.new_requests, 1);
});

test('requests from tabs that are not being recorded are ignored', async () => {
  const { L, send } = load(SNAP);
  await send({ cmd: 'start', tabId: 1 });
  fire(L, 2, 'x', 'https://other.example.com/', 'main_frame', 100);
  fire(L, -1, 'y', 'https://background.example.com/', 'other', 110);
  assert.strictEqual((await send({ cmd: 'status', tabId: 1 })).summary.requests, 0);
});

test('stopping a tab that was never recorded fails politely', async () => {
  const { send } = load(SNAP);
  const r = await send({ cmd: 'stop', tabId: 42 });
  assert.strictEqual(r.ok, false);
  assert.ok(r.error);
});

test('manifest is valid Manifest V3 and every referenced file exists', () => {
  const dir = path.join(__dirname, '..');
  const m = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
  assert.strictEqual(m.manifest_version, 3);
  const files = [m.background.service_worker, m.action.default_popup, ...m.content_scripts.flatMap((c) => c.js)];
  for (const f of files) assert.ok(fs.existsSync(path.join(dir, f)), f + ' is missing');
});
