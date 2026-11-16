'use strict';
/* The web version. The page (app.js) asks for /api/... as it would ask a local server; here those requests go to a Web Worker that
   runs the same Python program (Pyodide) inside this browser. Nothing is sent to any server. */
(() => {
  const page = document.documentElement.lang === 'sq' ? 'sq' : 'en';
  const TEXT = {
    en: {
      loading: 'Starting the analysis engine in your browser. The first visit downloads about 22 MB, which the browser keeps for next time.',
      failed: 'The analysis engine could not be started',
    },
    sq: {
      loading: 'Po niset motori i analizës në shfletuesin tënd. Vizita e parë shkarkon rreth 22 MB, që shfletuesi i mban për herën tjetër.',
      failed: 'Motori i analizës nuk u nis',
    },
  }[page];

  const stored = (() => { try { return localStorage.getItem('instat-lang'); } catch { return null; } })();
  const want = stored || ((navigator.language || '').toLowerCase().startsWith('sq') ? 'sq' : 'en');
  const setLanguage = code => {
    try { localStorage.setItem('instat-lang', code); } catch { /* private mode: the choice lasts for this page only */ }
    location.href = code === 'sq' ? 'sq.html' : 'index.html';
  };

  if (want !== page) {  // the visitor's language (or the one chosen last time) has its own page
    window.instatWeb = {fetch: () => new Promise(() => {}), setLanguage};  // keeps the page quiet while the browser changes page
    location.replace(want === 'sq' ? 'sq.html' : 'index.html');
    return;
  }

  const status = document.getElementById('status');
  let note = null;
  const show = (message, kind = 'info') => {
    note?.remove();
    note = document.createElement('div');
    note.className = 'toast ' + kind;
    if (kind === 'error') note.setAttribute('role', 'alert');
    note.textContent = message;
    status.append(note);
  };

  const pending = new Map();
  let nextId = 0;
  const worker = new Worker('pyworker.js', {type: 'module'});
  const ready = new Promise((resolve, reject) => {
    const fail = reason => {
      const error = new Error(`${TEXT.failed}: ${reason}`);
      show(error.message, 'error');
      console.error(error.message);
      reject(error);
    };
    worker.onmessage = ({data}) => {
      if (data.type === 'ready') { note?.remove(); resolve(); }
      else if (data.type === 'failed') fail(data.message);
      else if (data.type === 'log') console.warn(data.text);
      else if (data.type === 'reply') { pending.get(data.id)?.(data); pending.delete(data.id); }
    };
    worker.onerror = event => fail(event.message || 'the worker stopped');
  });
  ready.catch(() => {});  // the message is shown; requests that wait for it fail with the same text
  show(TEXT.loading);

  async function request(path, init = {}) {
    await ready;
    const url = new URL(path, location.href);
    const headers = {'x-language': page};
    for (const [name, value] of Object.entries(init.headers || {})) headers[name.toLowerCase()] = value;
    let body = new Uint8Array(0);
    if (init.body instanceof Blob) body = new Uint8Array(await init.body.arrayBuffer());
    else if (typeof init.body === 'string') body = new TextEncoder().encode(init.body);
    const id = ++nextId;
    const answer = new Promise(resolve => pending.set(id, resolve));
    worker.postMessage({id, method: (init.method || 'GET').toUpperCase(), target: url.pathname + url.search, headers, body}, [body.buffer]);
    const reply = await answer;
    return new Response(reply.body, {status: reply.status, headers: {...reply.headers, 'Content-Type': reply.ctype}});
  }

  window.instatWeb = {fetch: request, setLanguage};
})();
