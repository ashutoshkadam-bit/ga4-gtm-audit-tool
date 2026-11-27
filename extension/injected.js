// Runs inside the page (MAIN world) at document_start. It only OBSERVES: it never blocks or changes requests.
// It records console output, script errors, dataLayer pushes, which script created which script (so we can tell tags
// loaded by Tag Manager from hard-coded ones) and performance metrics, and hands them over when the recorder asks.
(() => {
  if (window.__gga) return;
  const g = (window.__gga = { lcp: null, cls: 0, fcp: null, longTasks: 0, dl: [], dlHooked: false, console: [], errors: [], creators: {} });
  const now = () => Math.round(performance.now());

  // ---- console and errors
  for (const type of ['log', 'info', 'warn', 'error', 'debug']) {
    const orig = console[type];
    console[type] = function (...args) {
      try {
        if (g.console.length < 500) {
          g.console.push({ type: type === 'warn' ? 'warning' : type, text: args.map((a) => { try { return typeof a === 'string' ? a : JSON.stringify(a); } catch (e) { return String(a); } }).join(' ').slice(0, 500), url: '', line: null, phase: 'load', t: now() });
        }
      } catch (e) {}
      return orig.apply(this, args);
    };
  }
  window.addEventListener('error', (e) => {
    if (e && e.target && e.target !== window && e.target.src) {
      if (g.console.length < 500) g.console.push({ type: 'error', text: 'Failed to load resource: ' + e.target.src, url: e.target.src, line: null, phase: 'load', t: now() });
      return;
    }
    if (g.errors.length < 200) g.errors.push({ text: String((e && e.message) || e).slice(0, 500), phase: 'load' });
  }, true);
  window.addEventListener('unhandledrejection', (e) => { if (g.errors.length < 200) g.errors.push({ text: 'Unhandled promise rejection: ' + String(e && e.reason).slice(0, 400), phase: 'load' }); });

  // ---- performance
  const obs = (type, fn) => { try { new PerformanceObserver((l) => fn(l.getEntries())).observe({ type, buffered: true }); } catch (e) {} };
  obs('largest-contentful-paint', (es) => { for (const e of es) g.lcp = e.startTime; });
  obs('layout-shift', (es) => { for (const e of es) if (!e.hadRecentInput) g.cls += e.value; });
  obs('paint', (es) => { for (const e of es) if (e.name === 'first-contentful-paint') g.fcp = e.startTime; });
  obs('longtask', (es) => { g.longTasks += es.length; });

  // ---- dataLayer
  const clean = (a) => { try { return JSON.parse(JSON.stringify(Array.isArray(a) || (a && a.length !== undefined && typeof a !== 'string') ? Array.from(a) : a)); } catch (e) { return { _unserializable: true }; } };
  const hook = () => {
    const dl = window.dataLayer;
    if (!dl || typeof dl.push !== 'function' || g.dlHooked) return;
    g.dlHooked = true;
    for (const a of dl.slice(0, 200)) g.dl.push({ t: now(), v: clean(a), pre: true });
    const orig = dl.push;
    dl.push = function () { for (const a of arguments) { if (g.dl.length < 500) g.dl.push({ t: now(), v: clean(a) }); } return orig.apply(this, arguments); };
  };
  hook();
  const iv = setInterval(() => { hook(); if (g.dlHooked) clearInterval(iv); }, 100);
  setTimeout(() => clearInterval(iv), 20000);

  // ---- who created each script element (Tag Manager vs hard-coded). Uses the current script or the call stack.
  const ownUrl = (document.currentScript && document.currentScript.src) || '';
  const creatorUrl = () => {
    const cs = document.currentScript;
    if (cs) return cs.src || 'inline';
    try {
      const frames = String(new Error().stack).split('\n').slice(1);
      for (const f of frames) {
        const m = f.match(/(https?:\/\/[^\s)]+?):\d+:\d+/);
        if (m && m[1] !== ownUrl && !m[1].startsWith('chrome-extension://')) return m[1];
      }
    } catch (e) {}
    return 'inline';
  };
  const note = (el) => {
    try {
      if (el && el.tagName === 'SCRIPT') {
        const watch = () => { if (el.src && !g.creators[el.src]) g.creators[el.src] = creatorUrl(); };
        watch();
        // src is often set after insertion, so also check when it changes
        const mo = new MutationObserver(watch);
        mo.observe(el, { attributes: true, attributeFilter: ['src'] });
      }
    } catch (e) {}
  };
  for (const name of ['appendChild', 'insertBefore']) {
    const orig = Node.prototype[name];
    Node.prototype[name] = function (el) { note(el); return orig.apply(this, arguments); };
  }
  for (const name of ['append', 'prepend']) {
    const orig = Element.prototype[name];
    Element.prototype[name] = function (...els) { els.forEach(note); return orig.apply(this, arguments); };
  }
  const srcDesc = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'src');
  if (srcDesc && srcDesc.set) {
    Object.defineProperty(HTMLScriptElement.prototype, 'src', {
      configurable: true, enumerable: srcDesc.enumerable, get: srcDesc.get,
      set(v) { const r = srcDesc.set.call(this, v); try { if (this.src && !g.creators[this.src]) g.creators[this.src] = creatorUrl(); } catch (e) {} return r; },
    });
  }

  // ---- snapshot handed to the recorder
  window.__ggaSnapshot = () => {
    const names = window.__GGA_GLOBALS || [];
    const present = [];
    for (const n of names) { try { const v = n.split('.').reduce((o, k) => (o == null ? o : o[k]), window); if (v != null) present.push(n); } catch (e) {} }
    const nav = performance.getEntriesByType('navigation')[0] || {};
    let html = '';
    try { html = document.documentElement.outerHTML.slice(0, 600000); } catch (e) {}
    return {
      globals: present,
      perf: { ttfb: nav.responseStart || null, dcl: nav.domContentLoadedEventEnd || null, load: nav.loadEventEnd || null, fcp: g.fcp, lcp: g.lcp, cls: g.cls, longTasks: g.longTasks, transferSize: nav.transferSize || null, domNodes: document.getElementsByTagName('*').length },
      dataLayer: g.dl, console: g.console, errors: g.errors, creators: g.creators,
      storage: { local: Object.keys(localStorage || {}), session: Object.keys(sessionStorage || {}) },
      title: document.title, lang: document.documentElement.lang || '',
      scripts: Array.from(document.scripts).map((s) => ({ src: s.src || '', inline: !s.src, async: s.async, defer: s.defer, type: s.type || '', len: s.src ? 0 : (s.textContent || '').length })).slice(0, 400),
      meta: Array.from(document.querySelectorAll('meta[name],meta[property]')).slice(0, 60).map((m) => [m.getAttribute('name') || m.getAttribute('property'), (m.content || '').slice(0, 200)]),
      iframes: Array.from(document.querySelectorAll('iframe')).map((f) => f.src || '').filter(Boolean).slice(0, 60),
      links: { canonical: (document.querySelector('link[rel=canonical]') || {}).href || '', preconnect: Array.from(document.querySelectorAll('link[rel=preconnect],link[rel=dns-prefetch]')).map((l) => l.href).slice(0, 40) },
      userAgent: navigator.userAgent, html,
    };
  };
})();
