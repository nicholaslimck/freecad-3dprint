"""TechDraw line art for the shape views.

Pure geometry and scale maths only; the TechDraw/Qt half lives further down and
is imported lazily so this module stays importable under plain Python.
"""
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
