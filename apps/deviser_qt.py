#!/usr/bin/env python3
"""Deviser — one-file Inventor .ipt viewer/exporter (Qt native + web fallback).

Qt native window first (Bazzite/KDE native feel); if Qt libs are missing,
falls back to the loopback web UI automatically. Either way: one file.

Clean-room: derived exclusively from observational format analysis.
"""
import os
import sys
import base64
import io
import json
import importlib.util
import importlib.machinery


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
try:
    ipt2deva_mod = load_module("ipt2deva", "ipt2deva_mod")
except Exception:
    ipt2deva_mod = None
IptFile = iptinfo.IptFile
try:
    ipt2devp_mod = load_module("ipt2devp", "ipt2devp_mod")
except Exception:
    ipt2devp_mod = None

try:
    import cadquery as cq
    HAS_CQ = True
except Exception:
    HAS_CQ = False


def auto_fillet_radius(ipt):
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
    return cands[k] * 10.0


# ---------------- E1: parameter editing engine ----------------
import copy
import re
import math

def extract_skeleton(ipt):
    """Geometry skeleton + parameter->geometry bindings (E1)."""
    all_verts, lines, circles = ipt2obj_mod.extract_geometry(ipt)
    # keep only sketch-plane points (z==0); feature edges add z>0 pts
    raw = ipt.asm_sketch_vertices()
    plane = [v for v in raw if abs(float(v[2])) < 1e-9]
    if len(plane) >= 3:
        verts = ipt2obj_mod._canonical_polygon(plane)
    else:
        verts = all_verts
    radius = ipt2obj_mod.ellipse_radius(ipt)
    depth = ipt2obj_mod.extrude_depth(ipt)
    params = ipt.parameters()
    fr = 0.0
    depth_param = None
    dnums = sorted(int(k[1:]) for k in params
                   if isinstance(k, str) and k.startswith("d") and k[1:].isdigit()
                   and isinstance(params[k], float))
    if len(verts) >= 3:
        # sketch dims are d0,d1 (or d2,d3 for linked-style files where
        # MyWidth-style user params shift numbering); the extrude is the
        # next dim. Robust: d1 if it exists and is nonzero; else the first
        # dN>=2 that is not a sketch extent.
        p1 = params.get("d1")
        if isinstance(p1, float) and abs(p1) > 1e-9:
            depth_param = "d1"
        else:
            x_ext = max((v[0] for v in verts), default=None)
            y_ext = max((v[1] for v in verts), default=None)
            depth_param = None
            for n in dnums:
                if n < 2:
                    continue
                v = params.get(f"d{n}")
                if not isinstance(v, float) or abs(v) < 1e-9 or abs(v) >= 3.0:
                    continue
                if x_ext is not None and abs(v - x_ext) < 1e-9:
                    continue
                if y_ext is not None and abs(v - y_ext) < 1e-9:
                    continue
                depth_param = f"d{n}"
                break
    elif circles:
        depth_param = "d1"
    # Feature-param classification (session 14 grammars):
    # angle params: |v| ~ pi/4 (0.785) = chamfer 45deg; |v| ~ pi/2 (1.571) = hole
    angles = {k: v for k, v in params.items()
              if isinstance(v, float) and (abs(abs(v) - math.pi/4) < 0.01 or abs(abs(v) - math.pi/2) < 0.01)}
    simple_d = sorted((int(k[1:]), v) for k, v in params.items()
                     if isinstance(k, str) and k.startswith("d") and k[1:].isdigit()
                     and isinstance(v, float) and 1e-9 < abs(v) < 3.0)
    fr = 0.0
    if not angles and simple_d:
        # no angle features: last dN beyond sketch+depth could be a fillet
        # only when exactly one extra param exists (fillet1: d4 only)
        sketch_depth_nums = set()
        if depth_param: sketch_depth_nums.add(int(depth_param[1:]))
        sketch_depth_nums.update(n for n, _ in simple_d if n <= 3)
        extras = [(n, v) for n, v in simple_d
                  if n not in sketch_depth_nums and f"d{n}" != depth_param]
        if len(extras) == 1:
            fr = extras[0][1] * 10.0

    if len(verts) >= 3 and depth > 0:
        skel = {"type": "prism", "verts_cm": [tuple(v) for v in verts],
                "depth_cm": depth, "fillet_r_mm": fr, "depth_param": depth_param,
                "_orig_params": {k: v for k, v in params.items() if isinstance(v, float)}}
        return skel, params
    elif circles and radius:
        return {"type": "cylinder", "center_cm": tuple(circles[0][0]),
                "radius_cm": radius, "depth_cm": depth, "fillet_r_mm": fr,
                "depth_param": depth_param}, params
    return None, params


def linked_sketch_dim(ipt, param_name):
    """E1.5: find the sketch d-dim driven by a user param (or None).

    Binding rule (session 14 ground truth): user param P links to sketch
    dim dN if the dependency graph lists dN in P's scope AND their values
    are equal. (Value equality + scope = the proven binding signature.)
    """
    try:
        links = ipt.parameter_links()
        params = ipt.parameters()
    except Exception:
        return None
    if param_name not in links or param_name not in params:
        return None
    pval = params[param_name]
    if not isinstance(pval, float):
        return None
    for ref in links[param_name]:
        if ref.startswith("d") and ref[1:].isdigit():
            rval = params.get(ref)
            if isinstance(rval, float) and abs(rval - pval) < 1e-9:
                return ref
    return None


def apply_edit_linked(sk, param_name, new_value_cm, ipt=None):
    """E1.5-aware apply_edit: user-param edits propagate to linked dims."""
    if ipt is not None and not param_name.startswith("d"):
        dim = linked_sketch_dim(ipt, param_name)
        if dim:
            # propagate: scale the sketch by the dim's new value
            scale_dim = dim  # e.g. 'd2' -> drives sketch extent
            return apply_edit(sk, scale_dim, new_value_cm)
    return apply_edit(sk, param_name, new_value_cm)


def apply_edit(sk, param_name, new_value_cm):
    sk = copy.deepcopy(sk)
    # E4: skeleton-native names (new parts)
    if param_name == "w_cm" and sk["type"] == "prism":
        w_old = max(max(v[0] for v in sk["verts_cm"]), 0.001)
        scale = new_value_cm / w_old
        sk["verts_cm"] = [(v[0]*scale, v[1]) for v in sk["verts_cm"]]
    elif param_name == "h_cm" and sk["type"] == "prism":
        h_old = max(max(v[1] for v in sk["verts_cm"]), 0.001)
        scale = new_value_cm / h_old
        sk["verts_cm"] = [(v[0], v[1]*scale) for v in sk["verts_cm"]]
    elif param_name == "radius_cm" or (param_name == "w_cm" and sk["type"] == "cylinder"):
        sk["radius_cm"] = new_value_cm
    elif param_name == "depth_cm":
        sk["depth_cm"] = new_value_cm
    elif param_name == "fillet_r_mm":
        sk["fillet_r_mm"] = new_value_cm
    # E1: Inventor d-params
    elif sk["type"] == "cylinder" and param_name == "d0":
        sk["radius_cm"] = new_value_cm / 2.0
    elif (sk["type"] == "prism" and param_name != sk.get("depth_param")
          and re.match(r"^d\d+$", param_name)):
        # a sketch dim scales the axis it dimensions. Determine which axis:
        # if the dim value equals the X extent -> scale X only;
        # if it equals the Y extent -> scale Y only; else uniform.
        xs = [v[0] for v in sk["verts_cm"]]
        ys = [v[1] for v in sk["verts_cm"]]
        x_ext = max(xs) if xs else 0
        y_ext = max(ys) if ys else 0
        old_val = None
        if abs(x_ext - y_ext) > 1e-9:
            old_val = x_ext  # ambiguous when equal; use max
        else:
            old_val = x_ext
        # heuristics: scale the axis whose extent is NOT equal to the other
        # — simpler: scale BOTH from the edited dim's original value.
        # We need the original param value; passed via sk['_orig_params']:
        orig = sk.get("_orig_params", {}).get(param_name)
        if orig is not None and orig > 1e-9:
            scale = new_value_cm / orig
        else:
            scale = new_value_cm / max(x_ext, y_ext) if max(x_ext, y_ext) else 1.0
        # axis discrimination: if only one axis' extent matches the ORIGINAL
        # value and the other doesn't, and they differ, scale only that axis:
        x_matches = abs(x_ext - (orig if orig else -1)) < 1e-9
        y_matches = abs(y_ext - (orig if orig else -1)) < 1e-9
        if x_matches and not y_matches and abs(x_ext - y_ext) > 1e-9:
            sk["verts_cm"] = [(v[0]*scale, v[1]) for v in sk["verts_cm"]]
        elif y_matches and not x_matches and abs(x_ext - y_ext) > 1e-9:
            sk["verts_cm"] = [(v[0], v[1]*scale) for v in sk["verts_cm"]]
        else:
            sk["verts_cm"] = [(v[0]*scale, v[1]*scale) for v in sk["verts_cm"]]
    elif param_name == sk.get("depth_param"):
        sk["depth_cm"] = new_value_cm
    elif param_name.startswith("d") and param_name[1:].isdigit() and int(param_name[1:]) >= 4:
        sk["fillet_r_mm"] = new_value_cm * 10.0
    return sk


def rebuild_solid(sk):
    """Rebuild the solid from a (possibly edited) skeleton via OpenCascade."""
    import cadquery as cq
    S = 10.0
    if sk["type"] == "cylinder":
        wp = (cq.Workplane("XY")
              .center(sk["center_cm"][0]*S, sk["center_cm"][1]*S)
              .circle(sk["radius_cm"]*S)
              .extrude(sk["depth_cm"]*S))
    else:
        wp = (cq.Workplane("XY")
              .polyline([(v[0]*S, v[1]*S) for v in sk["verts_cm"]])
              .close().extrude(sk["depth_cm"]*S))
    if sk["fillet_r_mm"] > 0:
        wp = wp.edges("|Z").fillet(sk["fillet_r_mm"])
    return wp


def skeleton_to_step(sk, path):
    """Write the (edited) solid as STEP."""
    import cadquery as cq
    wp = rebuild_solid(sk)
    cq.exporters.export(wp, path)
    return wp.val().Volume()


def build_report(ipt):
    s = ipt.summary()
    lines = [f"File:        {s['file']}",
             f"Title:       {s['part_title']}"]
    for name, val in (s.get("parameters") or {}).items():
        lines.append(f"Parameter:   {name} = {val}")
    lines.append(f"Author:      {s['author']}")
    lines.append(f"Build:       {s['inventor_build']}")
    m = s.get("material") or {}
    if m:
        lines.append(f"Material:    {m.get('material_name')} "
                     f"(density {m.get('density_g_cm3')} g/cm^3)")
    lines.append(f"Locale:      {s['locale']}")
    topo = s.get("asm_topology") or {}
    if topo:
        lines.append("Topology:    " + ", ".join(f"{k}x{v}" for k, v in topo.items()))
    for v in (s.get("asm_vertices") or []):
        lines.append(f"  vertex:    ({v[0]}, {v[1]}, {v[2]}) cm")
    lines.append(f"Thumbnail:   {'yes' if s['thumbnail_png'] else 'no'}")
    return s, "\n".join(lines)


def make_obj(ipt):
    verts, lines_, circles = ipt2obj_mod.extract_geometry(ipt)
    radius = ipt2obj_mod.ellipse_radius(ipt)
    depth = ipt2obj_mod.extrude_depth(ipt)
    return ipt2obj_mod.build_obj(verts, lines_, circles, radius, depth)


def make_step(ipt):
    if not HAS_CQ:
        raise RuntimeError("cadquery not installed:\npip install --user cadquery")
    verts, _lines, circles = ipt2obj_mod.extract_geometry(ipt)
    radius = ipt2obj_mod.ellipse_radius(ipt)
    depth = ipt2obj_mod.extrude_depth(ipt)
    S = 10.0
    if len(verts) >= 3 and depth > 0:
        wp = cq.Workplane("XY").polyline(
            [(v[0]*S, v[1]*S) for v in verts]).close().extrude(depth*S)
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


# ------------- Feature replayer (chamfer / hole / boss) -------------

def classify_features(params):
    """Session-14 grammars -> ordered feature list from params."""
    feats = []
    has_ch = any(isinstance(v, float) and abs(abs(v) - math.pi/4) < 0.01 for v in params.values())
    has_hole = any(isinstance(v, float) and abs(abs(v) - math.pi/2) < 0.01 for v in params.values())
    has_angle = has_ch or has_hole
    feat = sorted((int(k[1:]), v) for k, v in params.items()
                  if isinstance(k, str) and k.startswith("d") and k[1:].isdigit()
                  and isinstance(v, float) and 1e-9 < abs(v) < 3.0 and int(k[1:]) >= 4)
    if has_ch:
        dists = [v for n, v in feat if abs(v) < 1.0]
        feats.append({"op": "chamfer", "mm": (dists[0] if dists else 0.2) * 10.0})
    elif has_hole:
        dias = [v for n, v in feat]
        feats.append({"op": "hole", "dia_mm": (dias[0] if dias else 0.5) * 10.0})
    elif not has_angle and len(feat) >= 2:
        feats.append({"op": "boss", "dia_mm": feat[0][1] * 10.0,
                      "depth_mm": feat[1][1] * 10.0})
    return feats


def replay_features(wp, feats, sk):
    """Apply feature ops (chamfer/hole/boss) to a rebuilt base solid."""
    import cadquery as cq
    for f in feats:
        if f["op"] == "chamfer":
            wp = wp.edges("|Z").chamfer(f["mm"])
        elif f["op"] == "hole":
            xs = [v[0] for v in sk["verts_cm"]]
            ys = [v[1] for v in sk["verts_cm"]]
            cx = (min(xs) + max(xs)) / 2 * 10.0
            cy = (min(ys) + max(ys)) / 2 * 10.0
            wp = wp.faces(">Z").workplane().center(cx, cy).hole(f["dia_mm"])
        elif f["op"] == "boss":
            base_depth = sk["depth_cm"] * 10.0
            xs = [v[0] for v in sk["verts_cm"]]
            ys = [v[1] for v in sk["verts_cm"]]
            cx = (min(xs) + max(xs)) / 2 * 10.0
            cy = (min(ys) + max(ys)) / 2 * 10.0
            wp = wp.union(cq.Workplane("XY").workplane(offset=base_depth)
                          .center(cx, cy).circle(f["dia_mm"] / 2)
                          .extrude(f["depth_mm"]))
    return wp


def rebuild_full(ipt):
    """Base solid + feature replay (chamfer/hole/boss) -> workplane."""
    sk, params = extract_skeleton(ipt)
    if sk is None:
        return None
    wp = rebuild_solid(sk)
    feats = classify_features(params)
    if feats:
        wp = replay_features(wp, feats, sk)
    return wp


# ------------------------- Qt native UI -------------------------
def run_qt():
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QFileDialog, QTextEdit, QLabel, QMessageBox, QSplitter,
        QTableWidget, QTableWidgetItem, QGroupBox, QDoubleSpinBox, QDialog,
        QFormLayout, QDialogButtonBox, QComboBox, QRadioButton)
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush

    class SketchCanvas(QWidget):
        """E5: freehand sketch canvas. Left-click adds polyline points;
        circle mode: click center then radius point. Grid = 5 mm."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setMinimumSize(500, 400)
            self.mode = "polyline"
            self.points = []       # list of (x_mm, y_mm), origin bottom-left
            self.circle_center = None
            self.circle_r = None
            self.scale = 4.0       # pixels per mm
            self.margin = 20.0

        def set_mode(self, mode):
            self.mode = mode
            if mode == "circle":
                self.points = []
            else:
                self.circle_center = self.circle_r = None
            self.update()

        def clear(self):
            self.points = []
            self.circle_center = self.circle_r = None
            self.update()

        def _to_mm(self, pos):
            return ((pos.x() - self.margin) / self.scale,
                    (self.height() - self.margin - pos.y()) / self.scale)

        def _to_px(self, x_mm, y_mm):
            return (self.margin + x_mm * self.scale,
                    self.height() - self.margin - y_mm * self.scale)

        def mousePressEvent(self, ev):
            if ev.button() != Qt.LeftButton:
                return
            pt = self._to_mm(ev.position())
            if self.mode == "circle":
                if self.circle_center is None:
                    self.circle_center = pt
                else:
                    self.circle_r = ((pt[0] - self.circle_center[0]) ** 2
                                     + (pt[1] - self.circle_center[1]) ** 2) ** 0.5
            else:
                self.points.append(pt)
            self.update()

        def paintEvent(self, ev):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(), QColor(30, 30, 30))
            pen = QPen(QColor(70, 70, 70), 1)
            p.setPen(pen)
            step = 5 * self.scale
            x = self.margin
            while x < self.width():
                p.drawLine(int(x), 0, int(x), self.height())
                x += step
            y = self.height() - self.margin
            while y > 0:
                p.drawLine(0, int(y), self.width(), int(y))
                y -= step
            pen = QPen(QColor(150, 150, 150), 2)
            p.setPen(pen)
            p.drawLine(int(self.margin), 0, int(self.margin), self.height())
            p.drawLine(0, int(self.height() - self.margin),
                       self.width(), int(self.height() - self.margin))
            if self.mode == "circle" and self.circle_center:
                c = self._to_px(*self.circle_center)
                p.setPen(QPen(QColor(80, 170, 255), 2))
                if self.circle_r:
                    p.setBrush(QBrush(QColor(80, 170, 255, 40)))
                    p.drawEllipse(QPointF(*c), self.circle_r * self.scale,
                                  self.circle_r * self.scale)
                p.drawEllipse(QPointF(*c), 3, 3)
            elif self.points:
                p.setPen(QPen(QColor(80, 170, 255), 2))
                p.setBrush(QBrush(QColor(80, 170, 255, 40)))
                pts = [QPointF(*self._to_px(*pt)) for pt in self.points]
                if len(pts) >= 3:
                    p.drawPolygon(pts)
                for i in range(len(pts) - 1):
                    p.drawLine(pts[i], pts[i + 1])
                for pt in pts:
                    p.drawEllipse(pt, 3, 3)
            p.end()

    class SketchDialog(QDialog):
        """E5: freehand sketch -> skeleton (prism or cylinder)."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("E5 — Sketch a part")
            self.resize(760, 560)
            lay = QVBoxLayout(self)
            top = QHBoxLayout()
            self.rb_poly = QRadioButton("Polyline")
            self.rb_circ = QRadioButton("Circle")
            self.rb_poly.setChecked(True)
            top.addWidget(self.rb_poly)
            top.addWidget(self.rb_circ)
            btn_clear = QPushButton("Clear")
            btn_clear.clicked.connect(self._clear)
            top.addWidget(btn_clear)
            top.addStretch()
            lbl = QLabel("click to add points (grid 5 mm) — ≥3 points close a prism")
            top.addWidget(lbl)
            lay.addLayout(top)
            self.canvas = SketchCanvas()
            lay.addWidget(self.canvas, stretch=1)
            self.rb_poly.toggled.connect(
                lambda on: self.canvas.set_mode("polyline" if on else "circle"))
            self.rb_circ.toggled.connect(
                lambda on: self.canvas.set_mode("circle" if on else "polyline"))
            form = QFormLayout()
            self.depth = QDoubleSpinBox(); self.depth.setDecimals(2)
            self.depth.setRange(0.1, 1000); self.depth.setValue(10.0)
            self.fillet = QDoubleSpinBox(); self.fillet.setDecimals(2)
            self.fillet.setRange(0.0, 100); self.fillet.setValue(0.0)
            form.addRow("Extrude depth (mm):", self.depth)
            form.addRow("Fillet r (mm, 0=none):", self.fillet)
            lay.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)

        def _clear(self):
            self.canvas.clear()

        def skeleton(self):
            """Build a skeleton dict from the sketch (None if incomplete)."""
            if self.canvas.mode == "circle":
                c = self.canvas.circle_center
                r = self.canvas.circle_r
                if not (c and r and r > 0.1):
                    return None
                return {"type": "cylinder",
                        "center_cm": [c[0] / 10.0, c[1] / 10.0],
                        "radius_cm": r / 10.0,
                        "depth_cm": self.depth.value() / 10.0,
                        "fillet_r_mm": self.fillet.value(), "chamfer_mm": 0,
                        "holes": []}
            pts = self.canvas.points
            if len(pts) < 3:
                return None
            area = 0.0
            for i in range(len(pts)):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % len(pts)]
                area += x1 * y2 - x2 * y1
            if abs(area) / 2.0 < 1.0:
                return None
            if area > 0:
                pts = list(reversed(pts))
            return {"type": "prism",
                    "verts_cm": [[p[0] / 10.0, p[1] / 10.0] for p in pts],
                    "depth_cm": self.depth.value() / 10.0,
                    "fillet_r_mm": self.fillet.value(), "chamfer_mm": 0,
                    "holes": []}

    class Win(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Deviser — Inventor .ipt viewer/exporter (clean-room)")
            self.resize(1100, 700)
            self.ipt = None
            self.summary = None

            central = QWidget()
            self.setCentralWidget(central)
            root = QVBoxLayout(central)

            top = QHBoxLayout()
            btn_new = QPushButton("New Part…")
            btn_sketch = QPushButton("Sketch…")
            btn_open = QPushButton("Open .ipt…")
            btn_open_devp = QPushButton("Open .devp…")
            btn_devp = QPushButton("Save .devp…")
            btn_deva = QPushButton("Save .deva…")
            btn_obj = QPushButton("Export OBJ…")
            btn_step = QPushButton("Export STEP…")
            btn_json = QPushButton("Save JSON…")
            for b in (btn_new, btn_sketch, btn_open, btn_open_devp, btn_devp, btn_deva, btn_obj, btn_step, btn_json):
                top.addWidget(b)
            lbl = QLabel("clean-room · no Autodesk code")
            top.addStretch()
            top.addWidget(lbl)
            root.addLayout(top)

            split = QSplitter(Qt.Horizontal)
            self.info = QTextEdit()
            self.info.setReadOnly(True)
            self.info.setFont(self.info.font())
            split.addWidget(self.info)
            panel = QWidget()
            pv = QVBoxLayout(panel)
            self.thumb = QLabel("(nothing loaded)")
            self.thumb.setAlignment(Qt.AlignCenter)
            self.thumb.setMinimumWidth(340)
            pv.addWidget(self.thumb)
            self.thumb_panel = panel
            split.addWidget(panel)
            split.setSizes([700, 380])
            root.addWidget(split, stretch=1)

            # ---- E1: Parameter Editor panel ----
            edit_group = QGroupBox("Parameter Editor (E1) — edit a value, rebuild the solid")
            ev = QVBoxLayout(edit_group)
            self.param_table = QTableWidget(0, 2)
            self.param_table.setHorizontalHeaderLabels(["Parameter", "Value (cm)"])
            self.param_table.horizontalHeader().setStretchLastSection(True)
            ev.addWidget(self.param_table)
            btn_row = QHBoxLayout()
            self.btn_rebuild = QPushButton("Apply & Rebuild")
            self.btn_rebuild.clicked.connect(self.rebuild_edited)
            btn_row.addWidget(self.btn_rebuild)
            self.btn_step_edited = QPushButton("Export EDITED solid as STEP…")
            self.btn_step_edited.clicked.connect(self.export_edited_step)
            btn_row.addWidget(self.btn_step_edited)
            btn_row.addStretch()
            ev.addLayout(btn_row)
            self.edit_status = QLabel("Load an .ipt to edit its parameters.")
            ev.addWidget(self.edit_status)
            root.addWidget(edit_group)

            btn_new.clicked.connect(self.new_part)
            btn_sketch.clicked.connect(self.sketch_part)
            btn_open.clicked.connect(self.open_file)
            btn_open_devp.clicked.connect(self.open_devp)
            btn_devp.clicked.connect(self.save_devp)
            btn_deva.clicked.connect(self.save_deva)
            btn_obj.clicked.connect(self.export_obj)
            btn_step.clicked.connect(self.export_step)
            btn_json.clicked.connect(self.export_json)
            self.btn_step = btn_step

        def open_file(self):
            p, _ = QFileDialog.getOpenFileName(
                self, "Choose an Inventor part or assembly", "",
                "Inventor part/assembly (*.ipt *.iam);;All files (*)")
            if not p:
                return
            try:
                self.ipt = IptFile(p)
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Cannot open file:\n{e}")
                return
            if p.lower().endswith(".iam"):
                self._open_assembly(p)
                return
            self.summary, report = build_report(self.ipt)
            self.info.setPlainText(report)
            png = self.ipt.thumbnail()
            if png:
                pm = QPixmap()
                pm.loadFromData(png)
                self.thumb.setPixmap(pm.scaled(
                    340, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.thumb.setText("(no thumbnail)")
            self.btn_step.setEnabled(bool(self.summary.get("asm_vertices")) and HAS_CQ)
            if not HAS_CQ:
                self.btn_step.setToolTip("pip install --user cadquery to enable")
            else:
                self.btn_step.setToolTip("")

            # E1/E3: populate editor + classify features for replay
            self.skeleton, self.orig_params = extract_skeleton(self.ipt)
            self.features = classify_features(self.orig_params) if self.skeleton else []
            if self.features:
                fl = ", ".join(f["op"] for f in self.features)
                self.info.append(f"Features:    {fl} (will replay on rebuild)")
            self.param_table.setRowCount(0)
            if self.skeleton:
                sortable = sorted(self.orig_params.items(),
                                  key=lambda kv: (0, int(kv[0][1:])) if kv[0].startswith("d") and kv[0][1:].isdigit() and isinstance(kv[1], float) else (1, 0))
                for name, val in sortable:
                    if not isinstance(val, float):
                        continue
                    row = self.param_table.rowCount()
                    self.param_table.insertRow(row)
                    self.param_table.setItem(row, 0, QTableWidgetItem(str(name)))
                    sb = QDoubleSpinBox()
                    sb.setDecimals(4)
                    sb.setRange(-10000.0, 10000.0)
                    sb.setValue(float(val))
                    self.param_table.setCellWidget(row, 1, sb)
                self.btn_rebuild.setEnabled(True)
                self.btn_step_edited.setEnabled(HAS_CQ)
                self.edit_status.setText(
                    f"Skeleton: {self.skeleton['type']}; depth param: {self.skeleton.get('depth_param')}. "
                    "Edit values, then Apply & Rebuild.")
            else:
                self.btn_rebuild.setEnabled(False)
                self.btn_step_edited.setEnabled(False)
                self.edit_status.setText("No editable geometry skeleton in this file.")

        def _loaded(self):
            if not self.ipt:
                QMessageBox.information(self, "Deviser", "Load an .ipt first.")
                return False
            return True

        def export_obj(self):
            if not self._loaded():
                return
            p, _ = QFileDialog.getSaveFileName(
                self, "Export OBJ", os.path.splitext(self.ipt.path)[0] + ".obj",
                "Wavefront OBJ (*.obj)")
            if not p:
                return
            try:
                with open(p, "w") as f:
                    f.write(make_obj(self.ipt))
                QMessageBox.information(self, "Deviser", f"Exported:\n{p}\n(units: mm)")
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Export failed:\n{e}")

        def export_step(self):
            if not self._loaded():
                return
            p, _ = QFileDialog.getSaveFileName(
                self, "Export STEP", os.path.splitext(self.ipt.path)[0] + ".step",
                "STEP (*.step *.stp)")
            if not p:
                return
            try:
                with open(p, "w") as f:
                    f.write(make_step(self.ipt))
                QMessageBox.information(
                    self, "Deviser", f"Exported exact solid:\n{p}")
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"STEP export failed:\n{e}")

        def rebuild_edited(self):
            if not getattr(self, "skeleton", None):
                return
            sk = copy.deepcopy(self.skeleton)
            for row in range(self.param_table.rowCount()):
                name_item = self.param_table.item(row, 0)
                sb = self.param_table.cellWidget(row, 1)
                if name_item is None or sb is None:
                    continue
                sk = apply_edit_linked(sk, name_item.text(), sb.value(),
                                       getattr(self, "ipt", None))
            try:
                wp = rebuild_solid(sk)
                feats = getattr(self, "features", None) or []
                if feats:
                    wp = replay_features(wp, feats, sk)
                vol = wp.val().Volume()
                fdesc = (" + " + ", ".join(f["op"] for f in feats)) if feats else ""
                self.edit_status.setText(f"Rebuilt ✓{fdesc}  volume: {vol:.2f} mm³  "
                                         f"({wp.val().Faces().__len__()} faces)")
                self.edited_skeleton = sk
            except Exception as e:
                QMessageBox.warning(self, "Deviser", f"Rebuild failed:\n{e}")

        def export_edited_step(self):
            if not getattr(self, "edited_skeleton", None):
                self.rebuild_edited()
            if not getattr(self, "edited_skeleton", None):
                QMessageBox.information(self, "Deviser", "Rebuild first.")
                return
            p, _ = QFileDialog.getSaveFileName(
                self, "Export EDITED solid", 
                os.path.splitext(self.ipt.path)[0] + "_edited.step",
                "STEP (*.step *.stp)")
            if not p:
                return
            try:
                import cadquery as cq
                sk = self.edited_skeleton
                wp = rebuild_solid(sk)
                feats = getattr(self, "features", None) or []
                if feats:
                    wp = replay_features(wp, feats, sk)
                cq.exporters.export(wp, p)
                vol = wp.val().Volume()
                QMessageBox.information(
                    self, "Deviser", f"Exported EDITED solid{' + features' if feats else ''}:\n{p}\nvolume {vol:.2f} mm³")
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Export failed:\n{e}")

        def sketch_part(self):
            """E5: freehand sketch -> skeleton -> editable/saveable part."""
            dlg = SketchDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return
            sk = dlg.skeleton()
            if sk is None:
                QMessageBox.information(
                    self, "Deviser",
                    "Sketch incomplete:\n- polyline: click ≥3 points (area > 1 mm²)\n"
                    "- circle: click center, then a radius point")
                return
            self.skeleton = sk
            self.ipt = None
            self.summary = None
            self.devp_doc = {
                "format": "devp", "version": 1, "units": "mm",
                "part": {"title": "Sketched part", "author": "", "material": {}},
                "parameters": {}, "skeleton": sk, "history": [],
                "provenance": {"source": "deviser-sketch"},
            }
            if sk["type"] == "cylinder":
                desc = (f"circle Ø{sk['radius_cm']*20:.1f} mm "
                        f"at ({sk['center_cm'][0]*10:.0f}, {sk['center_cm'][1]*10:.0f})")
            else:
                desc = f"polygon with {len(sk['verts_cm'])} vertices"
            self.info.setPlainText(
                f"Sketched Deviser part\nType:    {sk['type']} ({desc})\n"
                f"Depth:   {sk['depth_cm']*10:.1f} mm\n"
                f"Fillet:  {sk['fillet_r_mm'] or 0} mm\n\n"
                "Edit values below, Apply & Rebuild, then Save .devp / Export STEP.")
            self.thumb.setText("(sketched part)")
            self.param_table.setRowCount(0)
            for pname, pval in [("depth_cm", sk["depth_cm"]),
                                ("fillet_r_mm", sk.get("fillet_r_mm", 0.0))]:
                row = self.param_table.rowCount()
                self.param_table.insertRow(row)
                self.param_table.setItem(row, 0, QTableWidgetItem(pname))
                sb = QDoubleSpinBox(); sb.setDecimals(4); sb.setRange(-1000, 1000)
                sb.setValue(float(pval))
                self.param_table.setCellWidget(row, 1, sb)
            self.btn_rebuild.setEnabled(True)
            self.btn_step_edited.setEnabled(HAS_CQ)
            self.btn_devp.setEnabled(True)
            self.edit_status.setText("Sketch done — edit depth/fillet, rebuild, save .devp.")

        def new_part(self):
            """E4: create a Deviser part from scratch (no .ipt source)."""
            from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QComboBox
            dlg = QDialog(self)
            dlg.setWindowTitle("New Deviser Part")
            form = QFormLayout(dlg)
            shape = QComboBox()
            shape.addItems(["Rectangle", "Circle"])
            w = QDoubleSpinBox(); w.setDecimals(2); w.setRange(0.1, 1000); w.setValue(20.0)   # mm
            h = QDoubleSpinBox(); h.setDecimals(2); h.setRange(0.1, 1000); h.setValue(15.0)   # mm
            depth = QDoubleSpinBox(); depth.setDecimals(2); depth.setRange(0.1, 1000); depth.setValue(10.0)
            fillet = QDoubleSpinBox(); fillet.setDecimals(2); fillet.setRange(0.0, 100); fillet.setValue(0.0)
            form.addRow("Shape:", shape)
            form.addRow("Width/Ø (mm):", w)
            form.addRow("Height (mm):", h)
            form.addRow("Extrude depth (mm):", depth)
            form.addRow("Fillet r (mm, 0=none):", fillet)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            form.addRow(buttons)
            if dlg.exec() != QDialog.Accepted:
                return
            W, H, D, F = w.value()/10.0, h.value()/10.0, depth.value()/10.0, fillet.value()
            if shape.currentText() == "Circle":
                skeleton = {"type": "cylinder", "center_cm": [0,0], "radius_cm": W/2,
                            "depth_cm": D, "fillet_r_mm": F, "chamfer_mm": 0, "holes": []}
            else:
                skeleton = {"type": "prism",
                            "verts_cm": [[W,0],[W,H],[0,H],[0,0]],
                            "depth_cm": D, "fillet_r_mm": F, "chamfer_mm": 0, "holes": []}
            self.skeleton = skeleton
            self.devp_doc = {
                "format": "devp", "version": 1, "units": "mm",
                "part": {"title": "Untitled", "author": "", "material": {}},
                "parameters": {}, "skeleton": skeleton,
                "history": [], "provenance": {"source": "deviser"},
            }
            self.ipt = None
            self.summary = None
            self.info.setPlainText(
                f"New Deviser part\nShape: {skeleton['type']}\n"
                f"Size: {w.value()} x {h.value()} mm, extrude {depth.value()} mm"
                + (f", fillet {F} mm" if F else ""))
            self.thumb.setText("(new part)")
            # editor rows for the new part's key dims:
            self.param_table.setRowCount(0)
            for pname, pval in [("w_cm", W), ("h_cm", H), ("depth_cm", D), ("fillet_r_mm", F)]:
                row = self.param_table.rowCount()
                self.param_table.insertRow(row)
                self.param_table.setItem(row, 0, QTableWidgetItem(pname))
                sb = QDoubleSpinBox(); sb.setDecimals(4); sb.setRange(-1000, 1000); sb.setValue(pval)
                self.param_table.setCellWidget(row, 1, sb)
            self.btn_rebuild.setEnabled(True)
            self.btn_step_edited.setEnabled(HAS_CQ)
            self.btn_devp.setEnabled(True)
            self.edit_status.setText("New part created — edit dims, rebuild, save .devp.")

        def _open_assembly(self, p):
            """Session 17: .iam assembly view (tree + occurrences + transforms)."""
            s = self.ipt.summary()
            lines = [f"=== Assembly: {os.path.basename(p)} ===",
                     f"Title:       {s['part_title']}",
                     f"Author:      {s.get('author')}",
                     ""]
            occs = s.get("occurrences") or []
            lines.append(f"Occurrences ({len(occs)}):")
            for o in occs:
                lines.append(f"  - {o['name']}")
            placed = s.get("placed_transform") or []
            if placed:
                lines.append("Placed transforms:")
                for t in placed:
                    lines.append(f"  {[round(v, 4) for v in t]}")
            cons = [o for o in occs
                    if any(o['name'].startswith(k) for k in
                           ("Mate", "Insert", "Angle", "Tangent", "Flush"))]
            if cons:
                lines.append(f"Constraints ({len(cons)}): "
                             + ", ".join(c['name'] for c in cons))
            lines.append("")
            lines.append("(Assembly decode: clean-room, session 16-17. "
                         "Save as .deva via File dialog filter.)")
            self.info.setPlainText("\n".join(lines))
            png = self.ipt.thumbnail()
            if png:
                pm = QPixmap()
                pm.loadFromData(png)
                self.thumb.setPixmap(pm.scaled(
                    340, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.thumb.setText("(no thumbnail)")
            self.btn_step.setEnabled(False)
            self.btn_rebuild.setEnabled(False)
            self.btn_step_edited.setEnabled(False)
            self.edit_status.setText("Assembly loaded — occurrence tree decoded.")

        def save_deva(self):
            """Session 17: convert the loaded .iam to native .deva format."""
            if ipt2deva_mod is None:
                QMessageBox.warning(self, "Deviser", ".deva module unavailable")
                return
            if not (self.ipt and self.ipt.path.lower().endswith(".iam")):
                QMessageBox.information(self, "Deviser", "Open an .iam assembly first.")
                return
            p, _ = QFileDialog.getSaveFileName(
                self, "Save Deviser assembly", os.path.splitext(self.ipt.path)[0] + ".deva",
                "Deviser assembly (*.deva)")
            if not p:
                return
            try:
                doc = ipt2deva_mod.make_deva(self.ipt.path)
                size = ipt2deva_mod.save_deva(doc, p)
                QMessageBox.information(
                    self, "Deviser",
                    f"Saved {p}\n({size} bytes, deva v{doc['version']}, "
                    f"{len(doc['occurrences'])} occurrences)")
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Cannot save .deva:\n{e}")

        def open_devp(self):
            if ipt2devp_mod is None:
                QMessageBox.warning(self, "Deviser", ".devp module unavailable")
                return
            p, _ = QFileDialog.getOpenFileName(
                self, "Open Deviser part", "", "Deviser part (*.devp);;All files (*)")
            if not p:
                return
            try:
                doc = ipt2devp_mod.load_devp(p)
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Cannot open .devp:\n{e}")
                return
            self.devp_doc = doc
            self.devp_path = p
            sk = doc.get("skeleton") or {}
            lines = [f"Deviser part (.devp v{doc['version']}): {p}",
                     f"Title:       {doc['part']['title']}",
                     f"Author:      {doc['part'].get('author')}"]
            params = doc.get("parameters", {})
            for k in sorted(params):
                lines.append(f"Parameter:   {k} = {params[k]}")
            lines.append(f"Type:        {sk.get('type')}")
            lines.append(f"History:     " + " -> ".join(h["op"] for h in doc.get("history", [])))
            self.info.setPlainText("\n".join(lines))
            self.thumb.setText("(native format — no thumbnail)")
            # populate editor from the skeleton
            self.param_table.setRowCount(0)
            if sk:
                self.skeleton = dict(sk)
                self.skeleton.setdefault("chamfer_mm", 0.0)
                self.skeleton.setdefault("holes", [])
                for name in sorted(params):
                    val = params[name]
                    if not isinstance(val, (int, float)):
                        continue
                    row = self.param_table.rowCount()
                    self.param_table.insertRow(row)
                    self.param_table.setItem(row, 0, QTableWidgetItem(str(name)))
                    sb = QDoubleSpinBox()
                    sb.setDecimals(4)
                    sb.setRange(-10000.0, 10000.0)
                    sb.setValue(float(val))
                    self.param_table.setCellWidget(row, 1, sb)
                self.btn_rebuild.setEnabled(True)
                self.btn_step_edited.setEnabled(HAS_CQ)
                self.edit_status.setText("Opened .devp — edit, rebuild, save back.")

        def save_devp(self):
            if ipt2devp_mod is None:
                QMessageBox.warning(self, "Deviser", ".devp module unavailable")
                return
            if getattr(self, "skeleton", None) is None:
                QMessageBox.information(self, "Deviser", "Load an .ipt or .devp first.")
                return
            # gather current edits into the doc
            if getattr(self, "devp_doc", None) is None:
                # build a fresh doc from current state
                self.devp_doc = {
                    "format": "devp", "version": 1, "units": "mm",
                    "part": {"title": self.summary["part_title"] if self.summary else "Deviser part",
                             "author": "", "material": {}},
                    "parameters": {},
                    "skeleton": None,
                    "history": [],
                    "provenance": {"source": "deviser"},
                }
            doc = self.devp_doc
            # apply table edits (params dict + skeleton edits like rebuild)
            sk = copy.deepcopy(self.skeleton)
            for row in range(self.param_table.rowCount()):
                name_item = self.param_table.item(row, 0)
                sb = self.param_table.cellWidget(row, 1)
                if name_item is None or sb is None:
                    continue
                name, val = name_item.text(), sb.value()
                doc["parameters"][name] = val
                sk = apply_edit(sk, name, val)
            doc["skeleton"] = sk
            doc["history"] = ipt2devp_mod._history_from_skeleton(sk)
            default = getattr(self, "devp_path", None) or (
                os.path.splitext(self.ipt.path)[0] + ".devp" if getattr(self, "ipt", None) else "part.devp")
            p, _ = QFileDialog.getSaveFileName(self, "Save Deviser part", default,
                                                "Deviser part (*.devp)")
            if not p:
                return
            try:
                size = ipt2devp_mod.save_devp(doc, p)
                self.devp_path = p
                QMessageBox.information(self, "Deviser", f"Saved:\n{p} ({size} bytes)")
            except Exception as e:
                QMessageBox.critical(self, "Deviser", f"Save failed:\n{e}")

        def export_json(self):
            if not self._loaded():
                return
            p, _ = QFileDialog.getSaveFileName(
                self, "Save JSON", os.path.splitext(self.ipt.path)[0] + ".json",
                "JSON (*.json)")
            if not p:
                return
            with open(p, "w") as f:
                json.dump(self.summary, f, indent=2, default=str)
            QMessageBox.information(self, "Deviser", f"Saved:\n{p}")

    app = QApplication(sys.argv)
    win = Win()
    win.show()
    sys.exit(app.exec())


# ------------------------- Web fallback UI -------------------------
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
</style></head><body>
<h1>Deviser</h1><p class="tag">clean-room Inventor .ipt viewer/exporter — Qt unavailable, web fallback</p>
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


def run_web():
    import threading
    import webbrowser
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    state = {"ipt": None, "summary": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/index") or self.path == "/":
                self._send(200, PAGE.encode())
                return
            if self.path.startswith("/export"):
                fmt = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query).get("fmt", ["obj"])[0]
                if not state["ipt"]:
                    self._send(400, b"no file loaded", "text/plain")
                    return
                try:
                    if fmt == "json":
                        data = json.dumps(state["summary"], indent=2, default=str).encode()
                        self._send(200, data, "application/json")
                    elif fmt == "step":
                        self._send(200, make_step(state["ipt"]).encode(), "application/step")
                    else:
                        self._send(200, make_obj(state["ipt"]).encode(), "text/plain")
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
                boundary = self.headers.get("Content-Type", "").split("boundary=")[-1].encode()
                payload = None
                for part in body.split(b"--" + boundary):
                    if b"filename=" in part:
                        payload = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                if payload is None:
                    raise ValueError("no file in upload")
                tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), "_deviser_upload.ipt")
                with open(tmp, "wb") as f:
                    f.write(payload)
                state["ipt"] = IptFile(tmp)
                state["summary"], report = build_report(state["ipt"])
                thumb_b64 = None
                png = state["ipt"].thumbnail()
                if png:
                    thumb_b64 = base64.b64encode(png).decode()
                self._send(200, json.dumps({
                    "report": report,
                    "thumbnail_b64": thumb_b64,
                    "title": state["summary"]["part_title"],
                    "has_step": bool(state["summary"].get("asm_vertices")) and HAS_CQ,
                }).encode(), "application/json")
            except Exception as e:
                self._send(400, f"cannot analyze: {e}".encode(), "text/plain")

    port = int(os.environ.get("DEVISER_PORT", "8765"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Deviser 1.1 (web fallback) — serving {url} (loopback only)")
    if os.environ.get("DEVISER_NO_BROWSER") != "1":
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    server.serve_forever()


def main():
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
        run_qt()
    except ImportError:
        print("Qt not available — using web fallback UI")
        run_web()


if __name__ == "__main__":
    main()
