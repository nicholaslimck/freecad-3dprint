"""TechDraw line art for the shape views.

Pure geometry and scale maths only; the TechDraw/Qt half lives further down and
is imported lazily so this module stays importable under plain Python.
"""
import os

VIEW_PX = 700                    # nominal long edge of a whole-part panel
STROKE_PX = 2.0                  # stroke floor, in pixels; never thinner
STROKE_PX_PER_DECADE = 1.6       # how much the stroke grows per 10x zoom
WHOLE_PART_PX_PER_MM = 130 / 25.4    # ~5.12: today's 130 dpi, in view space
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


def drawing(polylines, part_xy, caption, section_text=None, minimum_px_per_mm=WHOLE_PART_PX_PER_MM):
    """Complete SVG text for one view: white background, black strokes, caption under it.

    `polylines` are (N,2) arrays in view space (mm, y up). `part_xy` sets the frame
    and the scale, so a panel is sized by the geometry it shows, not by what the
    projection happened to emit.
    """
    import html

    part = _as_xy(part_xy)
    # the panel is sized by the part it shows; minimum_px_per_mm IS the scale.
    # (px_per_mm's VIEW_PX/span term answers "fit a whole part to 700 px", which
    # is decided by the caller passing WHOLE_PART_PX_PER_MM, not here.)
    ppm = max(float(minimum_px_per_mm), WHOLE_PART_PX_PER_MM)
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
    cap_h = (CAPTION_PAD_PX + CAPTION_PX * len(texts)) if texts else 0.0
    total_h = h_px + cap_h
    text_svg = []
    for i, line in enumerate(texts):
        ty = h_px + CAPTION_PAD_PX + CAPTION_PX * (i + 0.8)
        text_svg.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="%.1f" '
                        'fill="#000000">%s</text>' % (CAPTION_PAD_PX, ty, CAPTION_PX,
                                                     html.escape(str(line))))
    total_h = h_px + cap_h + CAPTION_PAD_PX      # bottom margin so the last line is not clipped

    # view space has y up; SVG has y down, so flip and translate the group
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">\n'
        '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>\n'
        '<g transform="translate(%.1f %.1f) scale(%.4f -%.4f)">\n%s\n</g>\n%s\n</svg>\n'
        % (w_px, int(round(total_h)), w_px, int(round(total_h)),
           w_px, int(round(total_h)),
           -x0 * ppm, (h_px + y0 * ppm), ppm, ppm,
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
