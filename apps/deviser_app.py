#!/usr/bin/env python3
"""Deviser — one-file Inventor .ipt viewer/exporter.

Clean-room: derived exclusively from observational format analysis.
Runs a loopback-only web UI: open an .ipt in your browser, inspect
metadata/parameters/geometry, extract the thumbnail, export OBJ/JSON.

No GUI libraries needed — the app serves the UI on 127.0.0.1 and opens
your default browser. Nothing is exposed beyond the local machine.
"""
import os
import sys
import io
import json
import base64
import struct
import threading
import webbrowser
import importlib.util
import importlib.machinery
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

APP = {
    "title": "Deviser",
    "version": "1.0.0",
    "tagline": "clean-room Inventor .ipt viewer/exporter",
}


def load_module(name, target):
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, name),
        os.path.join(getattr(sys, "_MEIPASS", here), name),
    ]
    for p in candidates:
        if os.path.exists(p):
            loader = importlib.machinery.SourceFileLoader(target, p)
            spec = importlib.util.spec_from_loader(target, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            return mod
    raise RuntimeError(f"engine module '{name}' not found in bundle")


iptinfo = load_module("iptinfo", "iptinfo")
ipt2obj_mod = load_module("ipt2obj", "ipt2obj_mod")
IptFile = iptinfo.IptFile

try:
    import cadquery as cq
    HAS_CQ = True
except Exception:
    HAS_CQ = False


def auto_fillet_radius(ipt):
    """Detect a fillet radius stored as a dN (N>=4) model parameter (cm)."""
    try:
        params = ipt.parameters()
    except Exception:
        return 0.0
    cands = {k: v for k, v in params.items()
             if isinstance(v, float) and k.startswith("d")
             and k[1:].isdigit() and int(k[1:]) >= 4}
    if not cands:
        return 0.0
    k = sorted(cands, key=lambda x: int(x[1:]))[0]
    return cands[k] * 10.0  # cm -> mm


def export_step_text(ipt):
    """Exact analytic solid via OpenCascade, with fillet feature replay."""
    if not HAS_CQ:
        raise RuntimeError("cadquery not installed: run  pip install --user cadquery")
    import math
    verts, lines, circles = ipt2obj_mod.extract_geometry(ipt)
    radius = ipt2obj_mod.ellipse_radius(ipt)
    depth = ipt2obj_mod.extrude_depth(ipt)
    S = 10.0  # cm -> mm
    if len(verts) >= 3 and depth > 0:
        pts = [(v[0]*S, v[1]*S) for v in verts]
        wp = cq.Workplane("XY").polyline(pts).close().extrude(depth*S)
        fr = auto_fillet_radius(ipt)
        if fr:
            wp = wp.edges("|Z").fillet(fr)
    elif circles and radius:
        c = circles[0]
        wp = (cq.Workplane("XY").center(c[0][0]*S, c[0][1]*S)
              .circle(radius*S).extrude(depth*S))
    else:
        raise RuntimeError("no exportable solid geometry found")
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        cq.exporters.export(wp, tmp)
        with open(tmp) as f:
            return f.read()
    finally:
        os.unlink(tmp)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Deviser</title>
<style>
 body { font-family: system-ui, sans-serif; background:#1e1f22; color:#dce0e8; margin:2rem; }
 h1 { color:#7aa2f7; } .tag { color:#9aa5ce; font-size:0.85rem; }
 #drop { border:2px dashed #565f89; border-radius:12px; padding:3rem; text-align:center; cursor:pointer; }
 #drop.hover { border-color:#7aa2f7; background:#24283b; }
 .grid { display:grid; grid-template-columns: 1fr 320px; gap:2rem; }
 pre { background:#24283b; padding:1rem; border-radius:8px; overflow:auto; white-space:pre-wrap; }
 img.thumb { max-width:320px; border-radius:8px; background:#fff; }
 button { background:#7aa2f7; color:#1e1f22; border:0; padding:0.5rem 1rem; border-radius:6px;
          font-weight:600; cursor:pointer; margin-right:0.5rem; }
 button:disabled { background:#565f89; color:#9aa5ce; }
 .err { color:#f7768e; }
 table { border-collapse:collapse; } td { padding:0.2rem 1rem 0.2rem 0; }
</style></head><body>
<h1>Deviser</h1><p class="tag">__TAGLINE__ — clean-room · no Autodesk code</p>
<div id="drop">Drop an <b>.ipt</b> here — or click to choose a file</div>
<input id="file" type="file" accept=".ipt" hidden>
<div class="grid">
 <div><pre id="info">Nothing loaded yet.</pre>
  <p>
   <button id="obj" disabled>Export OBJ (mm)</button>
  <button id="step" disabled>Export STEP (exact CAD)</button>
   <button id="json" disabled>Save JSON</button>
  </p>
  <p class="err" id="err"></p>
 </div>
 <div><h3>Thumbnail</h3><img id="thumb" class="thumb" hidden></div>
</div>
<script>
const drop = document.getElementById('drop'), file = document.getElementById('file');
drop.onclick = () => file.click();
['dragover','dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('hover'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('hover'); }));
drop.addEventListener('drop', ev => { ev.preventDefault(); if (ev.dataTransfer.files[0]) send(ev.dataTransfer.files[0]); });
file.onchange = () => { if (file.files[0]) send(file.files[0]); };
function send(f) {
  document.getElementById('err').textContent = '';
  const fd = new FormData(); fd.append('file', f);
  fetch('/analyze', {method:'POST', body: fd})
    .then(r => r.ok ? r.json() : r.text().then(t => Promise.reject(t)))
    .then(d => {
      document.getElementById('info').textContent = d.report;
      const t = document.getElementById('thumb');
      if (d.thumbnail_b64) { t.src = 'data:image/png;base64,' + d.thumbnail_b64; t.hidden = false; }
      else t.hidden = true;
      document.getElementById('obj').disabled = false;
      document.getElementById('json').disabled = false;
      document.getElementById('step').disabled = !d.has_step;
      window._devdata = d;
    })
    .catch(e => { document.getElementById('err').textContent = 'ERROR: ' + e; });
}
function dl(path, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(window._devdata.obj_json)], {type:'text/plain'}));
  fetch('/export?fmt=' + path).then(r => r.blob()).then(b => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  });
}
document.getElementById('step').onclick = () => fetch('/export?fmt=step')
  .then(r => r.ok ? r.blob() : r.text().then(t => Promise.reject(t)))
  .then(b => { const a=document.createElement('a');
    a.href=URL.createObjectURL(b); a.download=(window._devdata.title||'part')+'.step'; a.click(); })
  .catch(e => alert('STEP export: ' + e));
document.getElementById('obj').onclick = () => fetch('/export?fmt=obj')
  .then(r => r.blob()).then(b => { const a=document.createElement('a');
    a.href=URL.createObjectURL(b); a.download=(window._devdata.title||'part')+'.obj'; a.click(); });
document.getElementById('json').onclick = () => fetch('/export?fmt=json')
  .then(r => r.blob()).then(b => { const a=document.createElement('a');
    a.href=URL.createObjectURL(b); a.download=(window._devdata.title||'part')+'.json'; a.click(); });
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    state = {"ipt": None, "summary": None}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.replace("__TAGLINE__", APP["tagline"]).encode())
            return
        if self.path.startswith("/export"):
            fmt = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("fmt", ["obj"])[0]
            ipt = Handler.state.get("ipt")
            if not ipt:
                self._send(400, b"no file loaded", "text/plain")
                return
            if fmt == "json":
                data = json.dumps(Handler.state["summary"], indent=2, default=str).encode()
                self._send(200, data, "application/json")
                return
            if fmt == "step":
                try:
                    text = export_step_text(ipt)
                    self._send(200, text.encode(), "application/step")
                except Exception as e:
                    self._send(500, f"STEP export failed: {e}".encode(), "text/plain")
                return
            try:
                verts, lines, circles = ipt2obj_mod.extract_geometry(ipt)
                radius = ipt2obj_mod.ellipse_radius(ipt)
                depth = ipt2obj_mod.extrude_depth(ipt)
                text = ipt2obj_mod.build_obj(verts, lines, circles, radius, depth)
                self._send(200, text.encode(), "text/plain")
            except Exception as e:
                self._send(500, f"export failed: {e}".encode(), "text/plain")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/analyze":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            # multipart: find the payload between headers and boundary
            boundary = self.headers.get("Content-Type", "").split("boundary=")[-1].encode()
            parts = body.split(b"--" + boundary)
            payload = None
            for part in parts:
                if b"filename=" in part:
                    payload = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
            if payload is None:
                raise ValueError("no file in upload")
            tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), "_deviser_upload.ipt")
            with open(tmp, "wb") as f:
                f.write(payload)
            ipt = IptFile(tmp)
            Handler.state["ipt"] = ipt
            s = ipt.summary()
            Handler.state["summary"] = s
            lines = [f"File:        {s['file']}",
                     f"Title:       {s['part_title']}"]
            for name, val in (s.get("parameters") or {}).items():
                lines.append(f"Parameter:   {name} = {val}")
            lines.append(f"Author:      {s['author']}")
            lines.append(f"Build:       {s['inventor_build']}")
            m = s.get("material") or {}
            if m:
                lines.append(f"Material:    {m.get('material_name')} (density {m.get('density_g_cm3')} g/cm^3)")
            lines.append(f"Locale:      {s['locale']}")
            topo = s.get("asm_topology") or {}
            if topo:
                lines.append("Topology:    " + ", ".join(f"{k}x{v}" for k, v in topo.items()))
            for v in (s.get("asm_vertices") or []):
                lines.append(f"  vertex:    ({v[0]}, {v[1]}, {v[2]}) cm")
            thumb_b64 = None
            png = ipt.thumbnail()
            if png:
                thumb_b64 = base64.b64encode(png).decode()
            has_solid = bool(s.get("asm_vertices")) or bool(topo)
            resp = json.dumps({
                "report": "\n".join(lines),
                "thumbnail_b64": thumb_b64,
                "title": s["part_title"],
                "has_step": has_solid and HAS_CQ,
                "step_hint": "" if HAS_CQ else "pip install --user cadquery to enable",
            }).encode()
            self._send(200, resp, "application/json")
        except Exception as e:
            self._send(400, f"cannot analyze: {e}".encode(), "text/plain")


def main():
    port = int(os.environ.get("DEVISER_PORT", "8765"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP['title']} v{APP['version']} — {APP['tagline']}")
    print(f"  serving UI on {url} (loopback only)")
    if os.environ.get("DEVISER_NO_BROWSER") != "1":
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
