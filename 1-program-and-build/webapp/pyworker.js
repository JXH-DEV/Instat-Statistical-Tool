/* Runs the program's Python (Pyodide) for the web version. It loads the interpreter, numpy, pandas and xlrd from this site, unpacks
   instatkit.zip, and answers the page's requests with instatkit.web.embedded.handle. One request at a time: Python has one thread here. */
import {loadPyodide} from './pyodide/pyodide.mjs';

const here = new URL('.', import.meta.url);

const GLUE = `
import sys
sys.path.insert(0, "/opt/instat")
from js import Object
from pyodide.ffi import to_js
from instatkit.web import embedded


def handle(method, target, headers, body):
    status, ctype, out_headers, data = embedded.handle(method, target, headers.to_py(), bytes(body.to_py()))
    return to_js({"status": status, "ctype": ctype, "headers": out_headers, "body": data}, dict_converter=Object.fromEntries)


handle
`;

let handle = null;

async function boot() {
  const py = await loadPyodide({
    indexURL: new URL('pyodide/', here).href,
    lockFileURL: new URL('pyodide/pyodide-lock.json', here).href,
    stdout: () => {},
    stderr: text => postMessage({type: 'log', text}),
  });
  await py.loadPackage(['numpy', 'pandas', 'xlrd']);
  const zip = await (await fetch(new URL('instatkit.zip', here))).arrayBuffer();
  py.unpackArchive(zip, 'zip', {extractDir: '/opt/instat'});
  handle = py.runPython(GLUE);
  call({method: 'GET', target: '/api/state', headers: {'x-language': 'en'}, body: new Uint8Array(0)});  // imports pandas and the analysis code now
}

function call({method, target, headers, body}) {
  return handle(method, target, headers, body);  // already a plain JavaScript object: see to_js above
}

boot().then(
  () => postMessage({type: 'ready'}),
  error => postMessage({type: 'failed', message: String(error?.message || error)}),
);

onmessage = ({data}) => {
  try {
    postMessage({type: 'reply', id: data.id, ...call(data)});
  } catch (error) {
    const message = JSON.stringify({error: String(error?.message || error)});
    postMessage({type: 'reply', id: data.id, status: 500, ctype: 'application/json; charset=utf-8', headers: {}, body: new TextEncoder().encode(message)});
  }
};
