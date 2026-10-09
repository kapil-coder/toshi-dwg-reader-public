# DWG → {version, texts, dims, attrs, layers, png} using LibreDWG dwg2dxf + ezdxf. Transient: caller passes a temp dir and deletes it.
import subprocess, os, re, io
import ezdxf
VERS = {"AC1012": "R13", "AC1014": "R14", "AC1015": "2000", "AC1018": "2004", "AC1021": "2007", "AC1024": "2010", "AC1027": "2013", "AC1032": "2018"}
def sanitize(path):
    raw = open(path, "rb").read().decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    out = []; i = 0
    while i + 1 < len(raw):
        code = raw[i].strip()
        if not code.lstrip("-").isdigit():
            if out: out[-1] += "\\P" + raw[i]
            i += 1; continue
        out.append(code); out.append(raw[i + 1]); i += 2
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
def clean(t):
    t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t or "")  # MTEXT inline formatting codes
    return re.sub(r"\s+", " ", t.replace("\\P", " ").replace("{", "").replace("}", "")).strip()
def extract_ezdxf(doc):
    texts, dims, attrs, seen = [], [], [], set()
    def walk(entities, depth=0):
        for e in entities:
            t = e.dxftype()
            try:
                if t == "TEXT": texts.append(clean(e.dxf.text))
                elif t == "MTEXT": texts.append(clean(e.plain_text()))
                elif t == "ATTDEF": attrs.append(f"{e.dxf.tag}: {clean(e.dxf.text)}" if clean(e.dxf.text) else e.dxf.tag)
                elif t == "DIMENSION":
                    ov = clean(e.dxf.get("text", ""))
                    try: m = e.get_measurement(); m = round(float(m), 3) if isinstance(m, (int, float)) else None
                    except Exception: m = None
                    dims.append({"text": ov if ov not in ("", "<>") else None, "value": m, "layer": e.dxf.get("layer", "")})
                elif t == "INSERT":
                    for a in e.attribs: attrs.append(f"{a.dxf.tag}: {clean(a.dxf.text)}")
                    b = e.dxf.name
                    if depth < 6 and b not in seen and b in doc.blocks: seen.add(b); walk(doc.blocks[b], depth + 1)
            except Exception: pass
    for lay in doc.layouts: walk(lay)
    # Text inside block definitions that no INSERT reaches (e.g. title blocks behind anonymous *U blocks LibreDWG does not link).
    for b in doc.blocks:
        if b.name.lower() in ("*model_space", "*paper_space") or b.name in seen: continue
        seen.add(b.name); walk([e for e in b if e.dxftype() in ("TEXT", "MTEXT", "ATTDEF")], 6)
    return texts, dims, attrs, [l.dxf.name for l in doc.layers]
def extract_raw(path):
    # Tolerant scan of DXF group codes when ezdxf cannot load the file.
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n"); texts, dims, attrs, layers = [], [], [], set(); ent = None; cur = {}
    def flush():
        if ent in ("TEXT", "MTEXT") and cur.get("1"): texts.append(clean(cur["1"]))
        elif ent in ("ATTRIB", "ATTDEF") and (cur.get("1") or cur.get("2")): attrs.append(f"{cur.get('2', '')}: {clean(cur.get('1', ''))}")
        elif ent == "DIMENSION":
            v = cur.get("42"); dims.append({"text": clean(cur.get("1", "")) or None, "value": round(float(v), 3) if v and re.match(r"^-?[\d.]+(e-?\d+)?$", v.strip()) else None, "layer": cur.get("8", "")})
    for i in range(0, len(lines) - 1, 2):
        c, v = lines[i].strip(), lines[i + 1].rstrip("\r")
        if c == "0": flush(); ent = v.strip(); cur = {}
        else:
            if c in ("1", "2", "42", "8") and c not in cur: cur[c] = v
            if c == "3" and ent == "MTEXT": cur["1"] = v + cur.get("1", "")
            if c == "8": layers.add(v.strip())
    flush(); return texts, dims, attrs, sorted(layers)
def regen_dims(doc):
    # LibreDWG does not write the anonymous geometry blocks AutoCAD uses to draw dimensions → rebuild them so lines + numbers appear.
    ok = bad = 0
    for e in doc.modelspace().query("DIMENSION"):
        try: e.render(); ok += 1
        except Exception:
            try:
                e.dxf.discard("text") if e.dxf.get("text") in ("<>",) else None
                ov = e.override(); ov.set_dxf_attrib("dimpost", ""); ov.commit(); e.render(); ok += 1
            except Exception: bad += 1
    return ok, bad
def view_limits(doc):
    # Frame the drawing on where most geometry is: drop entities whose centre is outside the 1st–99th percentile, then union the rest.
    from ezdxf import bbox
    boxes = []
    for e in doc.modelspace():
        try:
            b = bbox.extents([e], fast=True)
            if b.has_data: boxes.append(b)
        except Exception: pass
    if len(boxes) < 5: return None
    xs = sorted(b.center.x for b in boxes); ys = sorted(b.center.y for b in boxes); k = len(boxes)
    lx, hx, ly, hy = xs[int(k * 0.01)], xs[min(k - 1, int(k * 0.99))], ys[int(k * 0.01)], ys[min(k - 1, int(k * 0.99))]
    keep = [b for b in boxes if lx <= b.center.x <= hx and ly <= b.center.y <= hy] or boxes
    x0 = min(b.extmin.x for b in keep); x1 = max(b.extmax.x for b in keep); y0 = min(b.extmin.y for b in keep); y1 = max(b.extmax.y for b in keep)
    fx0 = min(b.extmin.x for b in boxes); fx1 = max(b.extmax.x for b in boxes); fy0 = min(b.extmin.y for b in boxes); fy1 = max(b.extmax.y for b in boxes)
    if (fx1 - fx0) * (fy1 - fy0) < 20 * max((x1 - x0) * (y1 - y0), 1e-9): x0, x1, y0, y1 = fx0, fx1, fy0, fy1  # no real outlier → whole drawing
    pad = max(x1 - x0, y1 - y0, 1e-6) * 0.04
    return (x0 - pad, x1 + pad, y0 - pad, y1 + pad)
def render_ezdxf(doc, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig = plt.figure(figsize=(14, 10)); ax = fig.add_axes([0, 0, 1, 1]); ctx = RenderContext(doc); be = MatplotlibBackend(ax); fe = Frontend(ctx, be)
    drawn = skipped = 0
    for e in doc.modelspace():
        if e.dxftype() == "INSERT" and e.dxf.name not in doc.blocks: skipped += 1; continue
        try: fe.draw_entities([e]); drawn += 1
        except Exception: skipped += 1
    be.finalize(); lim = view_limits(doc); ax.set_aspect("equal", adjustable="box")
    if lim: ax.set_xlim(lim[0], lim[1]); ax.set_ylim(lim[2], lim[3])
    ax.axis("off"); fig.savefig(png, dpi=110, facecolor="#FFFFFF"); plt.close(fig)
    return drawn, skipped
def read_dwg(dwg, tmp, bin_dir):
    ver = open(dwg, "rb").read(6).decode("ascii", "replace"); r = {"version": ver, "release": VERS.get(ver, "unknown"), "warnings": []}
    dxf = os.path.join(tmp, "x.dxf"); png = os.path.join(tmp, "x.png")
    p = subprocess.run([f"{bin_dir}/dwg2dxf", "-y", "-o", dxf, dwg], capture_output=True, timeout=120)
    if not os.path.exists(dxf) or os.path.getsize(dxf) < 100: raise RuntimeError("could not convert this DWG")
    sanitize(dxf); doc = None
    try: doc = ezdxf.readfile(dxf)
    except Exception:
        try:
            from ezdxf import recover; doc, _ = recover.readfile(dxf)
        except Exception: doc = None
    if doc is not None: texts, dims, attrs, layers = extract_ezdxf(doc); r["parser"] = "ezdxf"
    else: texts, dims, attrs, layers = extract_raw(dxf); r["parser"] = "raw"; r["warnings"].append("drawing structure partly unreadable; text read by fallback scan")
    r.update(texts=[t for t in dict.fromkeys(texts) if t][:400], dims=dims[:300], attrs=[a for a in dict.fromkeys(attrs) if a.strip(": ")][:200], layers=layers[:200])
    r["png"] = None
    try:
        if doc is None: raise RuntimeError("no doc")
        dk, db = regen_dims(doc); d, s = render_ezdxf(doc, png); r["render"] = f"ezdxf ({d} drawn, {s} skipped, dims rebuilt {dk}/{dk + db})"
        if d == 0: raise RuntimeError("nothing drawn")
    except Exception:
        r["render"] = "failed"; r["warnings"].append("could not render a picture of the drawing; only its text was read")
    if r["render"] != "failed" and os.path.exists(png): r["png"] = png
    return r
