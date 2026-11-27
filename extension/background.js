// GA4 & GTM Audit Recorder: background service worker.
// Records every network request of one tab while recording is on, then builds a "gga-capture-1" file that the GA4 & GTM
// Audit tool can analyse. It only observes. Nothing leaves your computer unless you choose to upload the file.
const KEEP = /^(content-|cache-control|expires|etag|last-modified|server|via|age|x-|cf-|akamai|fastly|strict-transport|referrer-policy|permissions-policy|access-control|timing-allow|link|vary|alt-svc|set-cookie|location|accept-ch|cross-origin|report-to|nel)/i;
const BODY_URLS = /collect|\/g\/|\/ee\/|\/tr[\/?]|\/b\/ss\/|\/ccm\/|analytics|event|track|pixel|\/api\//i;
const TYPE_MAP = { main_frame: 'Document', sub_frame: 'Document', stylesheet: 'Stylesheet', script: 'Script', image: 'Image', font: 'Font', xmlhttprequest: 'XHR', ping: 'Ping', media: 'Media', websocket: 'WebSocket', other: 'Other', object: 'Other', csp_report: 'Other' };
const MAX_REQUESTS = 4000;
const sessions = new Map(); // tabId -> session
const timers = new Map();

// ---------------------------------------------------------------- persistence (the worker can be stopped and restarted)
const ready = (async () => {
  try {
    const all = await chrome.storage.session.get(null);
    for (const [k, v] of Object.entries(all)) if (k.startsWith('s_')) sessions.set(Number(k.slice(2)), v);
  } catch (e) {}
})();
function persist(tabId) {
  clearTimeout(timers.get(tabId));
  timers.set(tabId, setTimeout(() => { const s = sessions.get(tabId); if (s) chrome.storage.session.set({ ['s_' + tabId]: s }).catch(() => {}); }, 1200));
}
function badge(tabId, on) {
  chrome.action.setBadgeText({ tabId, text: on ? 'REC' : '' }).catch(() => {});
  if (on) chrome.action.setBadgeBackgroundColor({ tabId, color: '#c0392b' }).catch(() => {});
}

// ---------------------------------------------------------------- recording
async function startRecording(tabId, opts = {}) {
  await ready;
  const tab = await chrome.tabs.get(tabId);
  sessions.set(tabId, { tabId, recording: true, phase: 'load', startedAt: Date.now(), url: tab.url, t0: null, order: [], recs: {}, dropped: 0, docHeaders: {}, markedAt: null });
  persist(tabId);
  badge(tabId, true);
  if (opts.reload) await chrome.tabs.reload(tabId, { bypassCache: true });
  return { ok: true };
}

function rel(s, ts) { if (s.t0 === null) s.t0 = ts; return Math.round((ts - s.t0) * 10) / 10; }
function slimHeaders(list) {
  const out = {};
  for (const h of list || []) { const k = h.name.toLowerCase(); if (KEEP.test(k)) out[k] = String(h.value || '').slice(0, 300); }
  return out;
}
function decodeBody(rb) {
  try {
    if (rb && rb.raw && rb.raw[0] && rb.raw[0].bytes) return new TextDecoder().decode(rb.raw[0].bytes).slice(0, 4000);
    if (rb && rb.formData) return new URLSearchParams(Object.entries(rb.formData).map(([k, v]) => [k, v[0]])).toString().slice(0, 4000);
  } catch (e) {}
  return '';
}
const withSession = (d, fn) => ready.then(() => { const s = sessions.get(d.tabId); if (s && s.recording && d.tabId >= 0) { fn(s); persist(d.tabId); } });

chrome.webRequest.onBeforeRequest.addListener((d) => withSession(d, (s) => {
  if (s.order.length >= MAX_REQUESTS) { s.dropped++; return; }
  const rec = { id: d.requestId, url: d.url.slice(0, 2000), method: d.method, type: TYPE_MAP[d.type] || 'Other', status: null, mime: '', initiator_type: '', initiator_url: d.initiator || '', from_cache: false, protocol: '', ip: '', encoded_size: null, start_ms: rel(s, d.timeStamp), end_ms: null, error: '', resp_headers: {}, post: '', phase: s.phase, tls: '' };
  if (d.method !== 'GET' && BODY_URLS.test(d.url)) rec.post = decodeBody(d.requestBody);
  let key = d.requestId;
  if (s.recs[key]) key = d.requestId + '#r' + s.order.length; // redirect hop reuses the id
  rec._key = key;
  s.recs[key] = rec;
  s.order.push(key);
  s.last = s.last || {};
  s.last[d.requestId] = key;
}), { urls: ['<all_urls>'] }, ['requestBody']);

chrome.webRequest.onBeforeRedirect.addListener((d) => withSession(d, (s) => {
  const rec = s.recs[(s.last || {})[d.requestId]];
  if (rec) { rec.status = d.statusCode; rec.end_ms = rel(s, d.timeStamp); rec.resp_headers = slimHeaders(d.responseHeaders); rec.ip = d.ip || ''; }
}), { urls: ['<all_urls>'] }, ['responseHeaders']);

chrome.webRequest.onResponseStarted.addListener((d) => withSession(d, (s) => {
  const rec = s.recs[(s.last || {})[d.requestId]];
  if (!rec) return;
  rec.status = d.statusCode; rec.ip = d.ip || ''; rec.from_cache = !!d.fromCache;
  rec.resp_headers = slimHeaders(d.responseHeaders);
  rec.mime = (rec.resp_headers['content-type'] || '').split(';')[0];
  const cl = Number(rec.resp_headers['content-length']);
  if (!Number.isNaN(cl) && rec.resp_headers['content-length'] !== undefined) rec.encoded_size = cl;
  if (d.type === 'main_frame') {
    s.docHeaders = {};
    for (const h of d.responseHeaders || []) s.docHeaders[h.name.toLowerCase()] = String(h.value || '').slice(0, 600);
    s.mainStatus = d.statusCode; s.mainUrl = d.url;
  }
}), { urls: ['<all_urls>'] }, ['responseHeaders']);

chrome.webRequest.onCompleted.addListener((d) => withSession(d, (s) => {
  const rec = s.recs[(s.last || {})[d.requestId]];
  if (rec) { rec.end_ms = rel(s, d.timeStamp); if (rec.status == null) rec.status = d.statusCode; }
}), { urls: ['<all_urls>'] });

chrome.webRequest.onErrorOccurred.addListener((d) => withSession(d, (s) => {
  const rec = s.recs[(s.last || {})[d.requestId]];
  if (rec) { rec.error = d.error || 'failed'; rec.end_ms = rel(s, d.timeStamp); }
}), { urls: ['<all_urls>'] });

chrome.tabs.onRemoved.addListener((tabId) => { sessions.delete(tabId); chrome.storage.session.remove('s_' + tabId).catch(() => {}); });

// ---------------------------------------------------------------- build the capture file
async function stopAndBuild(tabId) {
  await ready;
  const s = sessions.get(tabId);
  if (!s) return { ok: false, error: 'Nothing was recorded for this tab.' };
  s.recording = false;
  badge(tabId, false);
  const tab = await chrome.tabs.get(tabId);
  let snap = null;
  try {
    const res = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: () => (window.__ggaSnapshot ? window.__ggaSnapshot() : null) });
    snap = res && res[0] && res[0].result;
  } catch (e) {}
  snap = snap || { globals: [], perf: {}, dataLayer: [], console: [], errors: [], creators: {}, storage: {}, scripts: [], meta: [], iframes: [], links: {} };
  const finalUrl = tab.url || s.mainUrl || s.url;
  const pageHost = (() => { try { return new URL(finalUrl).hostname; } catch (e) { return ''; } })();

  const requests = s.order.map((k) => s.recs[k]).filter(Boolean);
  const parserScripts = new Set((snap.scripts || []).filter((x) => x.src).map((x) => x.src));
  for (const r of requests) {
    delete r._key;
    if (r.type === 'Script') {
      const c = snap.creators && snap.creators[r.url];
      if (c) { r.initiator_type = 'script'; r.initiator_url = c === 'inline' ? finalUrl : c; }
      else if (parserScripts.has(r.url)) { r.initiator_type = 'parser'; r.initiator_url = ''; }
    }
  }

  // cookies for the page and every host it contacted (these can include cookies from earlier visits)
  const hosts = new Set([pageHost]);
  for (const r of requests) { try { hosts.add(new URL(r.url).hostname); } catch (e) {} }
  const cookieMap = new Map();
  await Promise.all([...hosts].slice(0, 60).map(async (h) => {
    try { for (const c of await chrome.cookies.getAll({ domain: h })) cookieMap.set(c.domain + '|' + c.path + '|' + c.name, c); } catch (e) {}
  }));
  const cookies = [...cookieMap.values()].map((c) => ({ name: c.name, domain: c.domain, path: c.path, expires: c.expirationDate || -1, secure: c.secure, httpOnly: c.httpOnly, sameSite: c.sameSite || '' }));

  const marked = s.markedAt !== null && s.markedAt !== undefined;
  const afterReqs = requests.filter((r) => r.phase === 'after_consent').length;
  const capture = {
    schema: 'gga-capture-1', source: 'extension', extension_version: chrome.runtime.getManifest().version,
    url: s.url, final_url: finalUrl, started: new Date(s.startedAt).toISOString(), seconds: Math.round((Date.now() - s.startedAt) / 100) / 10,
    device: 'desktop', user_agent: snap.userAgent || '', nav_error: '', status: s.mainStatus || null, doc_headers: s.docHeaders || {},
    requests, requests_dropped: s.dropped || 0, console: snap.console || [], errors: snap.errors || [], cookies,
    storage: snap.storage || {}, globals: snap.globals || [], perf: snap.perf || {}, datalayer: snap.dataLayer || [],
    title: snap.title || tab.title || '', lang: snap.lang || '', scripts: snap.scripts || [], meta: snap.meta || [], iframes: snap.iframes || [], links: snap.links || {},
    html: (snap.html || '').slice(0, 600000),
    consent: { tested: marked, clicked: marked ? 'marked by the user in the extension' : '', cookies_after: marked ? cookies.map((c) => c.name) : [], new_requests: afterReqs },
    note: 'Recorded in the browser profile of the person who ran the extension. Response sizes use the content-length header when present. Cookie list can include cookies from earlier visits.',
  };
  if (!capture.html) {
    try { const r = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: () => document.documentElement.outerHTML.slice(0, 600000) }); capture.html = (r[0] && r[0].result) || ''; } catch (e) {}
  }
  persist(tabId);
  return { ok: true, capture };
}

// ---------------------------------------------------------------- messages from the popup
function quickSummary(s) {
  const urls = Object.values(s.recs).map((r) => r.url);
  const uniq = (rx) => [...new Set(urls.map((u) => (u.match(rx) || [])[1]).filter(Boolean))];
  return {
    requests: urls.length,
    gtm: uniq(/gtm\.js\?[^#]*id=(GTM-[A-Z0-9]+)/), ga4: uniq(/\/g\/collect\?[^#]*tid=(G-[A-Z0-9]+)/),
    adobe: urls.some((u) => /\/b\/ss\/|omtrdc\.net|edge\.adobedc\.net|assets\.adobedtm\.com/.test(u)),
    meta: urls.some((u) => /facebook\.com\/tr/.test(u)), failed: Object.values(s.recs).filter((r) => r.error).length,
  };
}
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    await ready;
    if (msg.cmd === 'start') return sendResponse(await startRecording(msg.tabId, { reload: msg.reload }));
    if (msg.cmd === 'stop' || msg.cmd === 'export') return sendResponse(await stopAndBuild(msg.tabId));
    if (msg.cmd === 'mark') { const s = sessions.get(msg.tabId); if (s) { s.phase = 'after_consent'; s.markedAt = Date.now(); persist(msg.tabId); } return sendResponse({ ok: !!s }); }
    if (msg.cmd === 'status') { const s = sessions.get(msg.tabId); return sendResponse(s ? { recording: s.recording, phase: s.phase, summary: quickSummary(s) } : { recording: false }); }
    sendResponse({ ok: false });
  })();
  return true;
});
