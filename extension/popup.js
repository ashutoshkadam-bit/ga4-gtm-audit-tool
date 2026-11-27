let tab = null;
let timer = null;
const $ = (id) => document.getElementById(id);
const send = (m) => chrome.runtime.sendMessage(m);

async function refresh() {
  if (!tab) return;
  const st = await send({ cmd: 'status', tabId: tab.id });
  $('startReload').disabled = $('start').disabled = !!st.recording;
  $('stop').disabled = !(st.recording || st.summary);
  $('mark').disabled = !st.recording;
  if (st.summary) {
    const s = st.summary;
    $('stats').innerHTML = (st.recording ? '<span class="rec">Recording...</span> ' : 'Stopped. ') +
      `${s.requests} requests` + (s.failed ? `, ${s.failed} failed` : '') + '<br>' +
      (s.gtm.length ? 'GTM: ' + s.gtm.join(', ') + '<br>' : '') + (s.ga4.length ? 'GA4: ' + s.ga4.join(', ') + '<br>' : '') +
      (s.adobe ? 'Adobe seen<br>' : '') + (s.meta ? 'Meta pixel seen<br>' : '') + (st.phase === 'after_consent' ? 'Marked: after cookie consent' : '');
  } else {
    $('stats').textContent = 'Not recording.';
  }
}

async function download(capture) {
  const host = (() => { try { return new URL(capture.final_url).hostname; } catch (e) { return 'page'; } })();
  const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 16);
  const blob = new Blob([JSON.stringify(capture)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `capture-${host}-${stamp}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('url').textContent = tab && tab.url ? tab.url : '';
  const ok = tab && /^https?:/.test(tab.url || '');
  if (!ok) { $('stats').textContent = 'Open a normal web page (http or https) first.'; $('startReload').disabled = $('start').disabled = true; return; }
  $('startReload').onclick = async () => { await send({ cmd: 'start', tabId: tab.id, reload: true }); refresh(); };
  $('start').onclick = async () => { await send({ cmd: 'start', tabId: tab.id, reload: false }); refresh(); };
  $('mark').onclick = async () => { await send({ cmd: 'mark', tabId: tab.id }); refresh(); };
  $('stop').onclick = async () => {
    $('stats').textContent = 'Building the capture...';
    const r = await send({ cmd: 'stop', tabId: tab.id });
    if (r && r.ok) { await download(r.capture); $('stats').textContent = `Downloaded. ${r.capture.requests.length} requests captured.`; }
    else $('stats').textContent = (r && r.error) || 'Nothing to download.';
    refresh();
  };
  await refresh();
  timer = setInterval(refresh, 1500);
})();
