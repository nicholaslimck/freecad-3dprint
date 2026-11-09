"""TechDraw line art for the shape views.

Pure geometry and scale maths only; the TechDraw/Qt half lives further down and
is imported lazily so this module stays importable under plain Python.
"""
import os

VIEW_PX = 700                    # nominal long edge of a whole-part panel
STROKE_PX = 2.0                  # stroke floor, in pixels; never thinner
STROKE_PX_PER_DECADE = 1.6       # how much the stroke grows per 10x zoom
WHOLE_PART_PX_PER_MM = 130 / 25.4    # ~5.12: today's 130 dpi, in view space
# The contact sheet scales every panel to one cell width, so a panel drawn at
# 5.12 px/mm on a 137 mm part (700 px) is upscaled and soft. Shape panels are
# drawn at least this wide.
WHOLE_PART_MIN_PX = 1100
FEATURE_MIN_PX_PER_MM = 20.0     # 0.4 mm * 20 = 8 px


def viewport(pts_xy, part_xy):
    """Padded view box of `part_xy`: (x0, y0, w, h, pad). 4% of the part span."""
    part = _as_xy(part_xy)
    lo = part.min(axis=0)
    hi = part.max(axis=0)
    pad = 0.04 * float(max(hi - lo)) if len(part) else 0.0
    return lo[0] - pad, lo[1] - pad, (hi - lo)[0] + 2 * pad, (hi - lo)[1] + 2 * pad, pad


def stroke_px(w_mm, w_px):
    """Stroke width in output pixels for a panel `w_px` wide.

    Grows sub-linearly with zoom so a feature panel does not draw a hairline,
    and never falls below STROKE_PX so a small part stays visible.
    `w_mm` is accepted to keep call sites symmetric with stroke_for; it does
    not affect the result.
    """
    grown = STROKE_PX * (float(w_px) / VIEW_PX) ** (1.0 / STROKE_PX_PER_DECADE)
    return max(STROKE_PX, grown)


def stroke_for(w_mm, w_px):
    """View-space stroke width in mm that renders as stroke_px(w_mm, w_px) pixels."""
    return stroke_px(w_mm, w_px) * float(w_mm) / float(w_px)


def px_per_mm(part_xy, view_px, minimum):
    """Pixels per mm for `part_xy` fitted to `view_px`, never below `minimum`."""
    part = _as_xy(part_xy)
    span = float(max(part.max(axis=0) - part.min(axis=0))) if len(part) else 0.0
    if span <= 0:
        return float(minimum)
    return max(float(minimum), float(view_px) / span)


def png_size(part_xy, ppm):
    """Pixel size of the padded viewport of `part_xy` at `ppm` px/mm."""
    _, _, w, h, _ = viewport(part_xy, part_xy)
    return int(round(w * ppm)), int(round(h * ppm))


def _as_xy(pts):
    import numpy as np
    a = np.asarray(pts, dtype=float)
    return a.reshape(-1, 2) if a.size else a.reshape(0, 2)


CAPTION_PX = 13.0          # caption line height, output pixels
CAPTION_PAD_PX = 6.0       # gap between the drawing and the first caption line
# Captions are measured against this canvas width regardless of the panel's real
# one, so a sharp 2635 px panel and a 221 px one print the same size text when
# the sheet scales them to the same cell.
CAPTION_REF_PX = 260.0


def _drawing_ppm(part_xy, minimum):
    """The scale `drawing()` uses: the caller's floor, the whole-part floor, or the sharpness floor."""
    part = _as_xy(part_xy)
    ppm = max(float(minimum), WHOLE_PART_PX_PER_MM)
    span = float(max(part.max(axis=0) - part.min(axis=0))) if len(part) else 0.0
    if span > 0:
        ppm = max(ppm, WHOLE_PART_MIN_PX / span)   # stay sharp once the sheet upscales
    return ppm


def drawing(polylines, part_xy, caption, section_text=None, minimum_px_per_mm=WHOLE_PART_PX_PER_MM):
    """Complete SVG text for one view: white background, black strokes, caption under it.

    `polylines` are (N,2) arrays in view space (mm, y up). `part_xy` sets the frame
    and the scale, so a panel is sized by the geometry it shows, not by what the
    projection happened to emit.
    """
    import html

    part = _as_xy(part_xy)
    ppm = _drawing_ppm(part, minimum_px_per_mm)
    x0, y0, w, h, _pad = viewport(part, part)
    w_px = max(1, int(round(w * ppm)))
    h_px = max(1, int(round(h * ppm)))
    stroke_mm = stroke_for(w, w_px)

    lines = [ln for ln in (_as_xy(p) for p in polylines) if len(ln) >= 2]
    body = []
    for ln in lines:
        d = "M %.4f %.4f" % (ln[0][0], ln[0][1])
        for q in ln[1:]:
            d += " L %.4f %.4f" % (q[0], q[1])
        body.append('<path d="%s" fill="none" stroke="#000000" stroke-width="%.4f" '
                    'stroke-linecap="round" stroke-linejoin="round"/>' % (d, stroke_mm))

    texts = list(caption or [])
    if section_text:
        texts.append(section_text)
    # Caption size is a fraction of the canvas, so a panel drawn sharp at 2600 px
    # and one at 220 px print the same text size once the sheet scales both to a
    # cell. CAPTION_PX is the size at CAPTION_REF_PX.
    cap = max(CAPTION_PX, w_px / CAPTION_REF_PX * CAPTION_PX) if texts else CAPTION_PX
    cap_pad = cap * (CAPTION_PAD_PX / CAPTION_PX)
    # the canvas must fit the widest caption line too, or the text is clipped;
    # the drawing is then centred in the extra width rather than stretched
    text_w = max((len(str(t)) * cap * 0.55 for t in texts), default=0.0)
    canvas_w = max(w_px, int(round(text_w + 2 * cap_pad)))
    x_off = (canvas_w - w_px) / 2.0
    cap_h = (cap_pad + cap * len(texts)) if texts else 0.0
    text_svg = []
    for i, line in enumerate(texts):
        ty = h_px + cap_pad + cap * (i + 0.8)
        text_svg.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="%.1f" '
                        'fill="#000000">%s</text>' % (cap_pad, ty, cap,
                                                     html.escape(str(line))))
    total_h = h_px + cap_h + CAPTION_PAD_PX      # bottom margin so the last line is not clipped

    # view space has y up; SVG has y down, so flip and translate the group
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">\n'
        '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>\n'
        '<g transform="translate(%.1f %.1f) scale(%.4f -%.4f)">\n%s\n</g>\n%s\n</svg>\n'
        % (canvas_w, int(round(total_h)), canvas_w, int(round(total_h)),
           canvas_w, int(round(total_h)),
           x_off - x0 * ppm, (h_px + y0 * ppm), ppm, ppm,
           "\n".join(body), "\n".join(text_svg)))


def svg_size(svg):
    """(width, height) in pixels from an SVG root element."""
    import re
    m = re.search(r'<svg[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"', svg)
    if not m:
        raise ValueError("no width/height on the svg root")
    return int(m.group(1)), int(m.group(2))



# ---------------------------------------------------------------- TechDraw (FreeCAD only)
TEMPLATE_REL = os.path.join("Mod", "TechDraw", "Templates", "Default_Template_A4_Landscape.svg")


def template_path():
    """The A4 landscape TechDraw template from the running FreeCAD install."""
    import FreeCAD
    path = os.path.join(FreeCAD.getResourceDir(), TEMPLATE_REL)
    if not os.path.isfile(path):
        raise RuntimeError("TechDraw template not found: %s" % path)
    return path


def techdraw_document(shape, name):
    """New document holding `shape` as a Part::Feature. Caller closes it."""
    import FreeCAD
    doc = FreeCAD.newDocument("fcplines_" + name)
    obj = doc.addObject("Part::Feature", "shape_" + name)
    obj.Shape = shape
    doc.recompute()
    return doc, obj


def visible_edges(doc, shape_obj, eye, up, name):
    """Projected, hidden-line-removed edges of `shape_obj` seen from `eye`.

    TechDraw projects about the shape's centre, so each edge is translated into
    a frame whose origin is the projection's own bounding-box minimum. View
    space is then absolute and up is +Y, which is what the SVG builder expects.
    """
    import FreeCAD
    page = doc.addObject("TechDraw::DrawPage", "Page_" + name)
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Tpl_" + name)
    tpl.Template = template_path()
    page.Template = tpl
    view = doc.addObject("TechDraw::DrawViewPart", "View_" + name)
    page.addView(view)
    view.Source = [shape_obj]
    e = FreeCAD.Vector(*eye)
    e.normalize()
    view.Direction = e
    x = FreeCAD.Vector(*up).cross(e)
    if x.Length < 1e-9:
        x = FreeCAD.Vector(1, 0, 0)
    x.normalize()
    view.XDirection = x
    doc.recompute()
    edges = view.getVisibleEdges()
    return _rebase(edges, FreeCAD)


def _rebase(edges, FreeCAD):
    """Shift projected edges so the projection's bbox minimum sits at the origin."""
    if not edges:
        return edges
    xs = [p.x for e in edges for p in (e.firstVertex().Point, e.lastVertex().Point)]
    ys = [p.y for e in edges for p in (e.firstVertex().Point, e.lastVertex().Point)]
    dx, dy = min(xs), min(ys)
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return edges
    out = []
    for e in edges:
        c = e.copy()
        c.translate(FreeCAD.Vector(-dx, -dy, 0))
        out.append(c)
    return out


def rasterise(svg_text, png_path):
    """SVG text to PNG through Qt, which FreeCAD already ships."""
    QtSvg, QtGui, QtCore = _qt()
    if QtSvg is None:
        raise RuntimeError("no QtSvg binding")
    app = QtGui.QGuiApplication.instance()
    if app is None:
        # freecadcmd has no Qt app when a script runs outside the GUI; QImage and
        # QPainter need one, so hold a reference for the duration of the call.
        app = QtGui.QGuiApplication([])
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_text.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("QSvgRenderer rejected the SVG")
    size = renderer.defaultSize()
    img = QtGui.QImage(size, QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(img)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    if not img.save(png_path):
        raise RuntimeError("QImage.save failed: %s" % png_path)
    return png_path


def _qt():
    for mod in ("PySide6", "PySide2", "PySide"):
        try:
            ns = __import__(mod, fromlist=["QtSvg", "QtGui", "QtCore"])
            if hasattr(ns, "QtSvg"):
                return ns.QtSvg, ns.QtGui, ns.QtCore
        except Exception:  # noqa: BLE001 - try the next binding
            continue
    return None, None, None


def close_document(doc):
    """Close a document opened by techdraw_document(), swallowing teardown errors."""
    import FreeCAD
    try:
        FreeCAD.closeDocument(doc.Name)
    except Exception:  # noqa: BLE001 - the app is going away anyway
        pass


# ---------------------------------------------------------------- per-part entry point
SIX_VIEWS = {
    "iso": ((1.0, -1.0, 0.8), (0, 0, 1)),
    "front": ((0.0, -1.0, 0.0), (0, 0, 1)),
    "right": ((1.0, 0.0, 0.0), (0, 0, 1)),
    "top": ((0.0, 0.0, 1.0), (0, 1, 0)),
    "back_iso": ((-1.0, 1.0, 0.8), (0, 0, 1)),
    "bottom": ((0.0, 0.0, -1.0), (0, 1, 0)),
}
FEATURE_SHAPE_VIEWS = {"iso": SIX_VIEWS["iso"], "front": SIX_VIEWS["front"],
                       "top": SIX_VIEWS["top"]}


def render_part(shape, name, bbox, outdir, views=None, tag="", section_text=None,
                minimum_px_per_mm=WHOLE_PART_PX_PER_MM):
    """Line art for each view of `shape`. Returns (records, warnings, timings).

    One TechDraw document per part (BC3). A view that fails is a warning, not a
    lost sheet, matching render_views.py's per-feature policy.
    """
    import time

    views = SIX_VIEWS if views is None else views
    os.makedirs(outdir, exist_ok=True)
    dims = "bbox %.2f x %.2f x %.2f mm (print orientation)" % tuple(bbox)
    minimum = minimum_px_per_mm
    records, warnings, timings = [], [], []
    doc = None
    try:
        doc, obj = techdraw_document(shape, "%s%s" % (name, tag))
        for view, (eye, up) in views.items():
            t0 = time.time()
            try:
                edges = visible_edges(doc, obj, eye, up, "%s%s_%s" % (name, tag, view))
                hlr_s = time.time() - t0
                timings.append({"part": name, "view": view, "hlr_s": round(hlr_s, 3)})
                if not edges:
                    warnings.append("shape render %s%s_%s: no visible edges"
                                    % (name, tag, view))
                    continue
                polys = [_edge_polyline(e) for e in edges]
                part_xy = _polys_bounds(polys)
                actual_ppm = _drawing_ppm(part_xy, minimum)
                caption = ["%s%s - %s" % (name, tag, view), dims,
                           "scale %.2f px/mm" % actual_ppm]
                svg = drawing(polys, part_xy, caption=caption, section_text=section_text,
                              minimum_px_per_mm=minimum)
                path = os.path.join(outdir, "%s%s_%s_lines.png" % (name, tag, view))
                rasterise(svg, path)
                records.append({"path": path, "view": view, "engine": "techdraw"})
            except Exception as exc:  # noqa: BLE001 - one bad view must not lose the sheet
                warnings.append("shape render %s%s_%s failed: %s" % (name, tag, view, exc))
    finally:
        if doc is not None:
            close_document(doc)
    return records, warnings, timings


def _edge_polyline(edge, n=48):
    import numpy as np
    pts = edge.discretize(n)
    return np.array([[p.x, p.y] for p in pts], dtype=float)


def _polys_bounds(polys):
    import numpy as np
    return np.vstack([p for p in polys if len(p)]) if polys else np.zeros((0, 2))



# ---------------------------------------------------------------- contact sheet
ENGINE_FOOTER = ("shape: TechDraw line art | support: flat raster classification "
                 "(bottom view only)")
SHEET_PANEL_PX = 420      # widest panel on the sheet
SHEET_PAD_PX = 8


def sheet_grid(n_panels):
    """(cols, rows) for a contact sheet, matching render_views' old layout."""
    import math
    cols = 2 if n_panels <= 4 else 3
    return cols, max(1, int(math.ceil(n_panels / float(cols))))


def contact_sheet(panels, path, title, footer):
    """Composite panel PNGs into one sheet SVG, rasterise to `path`, return `path`.

    Panels are embedded as base64 so the sheet is one self-contained file that
    survives the workspace being moved.
    """
    import base64
    import html
    import struct

    cells = []
    for p in panels:
        with open(p, "rb") as f:
            raw = f.read()
        w, h = struct.unpack(">II", raw[16:24])       # PNG IHDR width/height
        cells.append((base64.b64encode(raw).decode("ascii"), w, h))

    cols, rows = sheet_grid(max(1, len(cells)))
    cell_w = SHEET_PANEL_PX
    cell_h = int(SHEET_PANEL_PX * 0.8)
    head_h = 26
    foot_h = 18
    for _, w, h in cells:                                  # one tall panel sets the row height
        cell_h = max(cell_h, int(cell_w * h / float(w)) if w else cell_h)
    sheet_w = cols * cell_w + (cols + 1) * SHEET_PAD_PX
    sheet_h = head_h + rows * cell_h + (rows + 1) * SHEET_PAD_PX + foot_h

    parts = ['<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>'
             % (sheet_w, sheet_h),
             '<text x="%d" y="18" font-family="sans-serif" font-size="15" fill="#000000">%s</text>'
             % (SHEET_PAD_PX, html.escape(str(title)))]
    for i, (b64, w, h) in enumerate(cells):
        r, c = divmod(i, cols)
        x = SHEET_PAD_PX + c * (cell_w + SHEET_PAD_PX)
        y = head_h + SHEET_PAD_PX + r * (cell_h + SHEET_PAD_PX)
        draw_w = cell_w
        draw_h = int(cell_w * h / float(w)) if w else cell_h
        offset = (cell_h - draw_h) / 2.0
        parts.append('<image x="%d" y="%.1f" width="%d" height="%d" '
                     'xlink:href="data:image/png;base64,%s"/>'
                     % (x, y + offset, draw_w, draw_h, b64))
    parts.append('<text x="%d" y="%d" font-family="sans-serif" font-size="12" fill="#444444">%s</text>'
                 % (SHEET_PAD_PX, sheet_h - 5, html.escape(str(footer))))

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" '
           'xmlns:xlink="http://www.w3.org/1999/xlink" width="%d" height="%d" '
           'viewBox="0 0 %d %d">\n%s\n</svg>\n'
           % (sheet_w, sheet_h, sheet_w, sheet_h, "\n".join(parts)))
    rasterise(svg, path)
    return path
