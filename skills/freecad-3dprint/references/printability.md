# Design-for-printing rules of thumb

These are starting values for FDM with a 0.4 mm nozzle. Printers vary, so treat
them as defaults to confirm with a test coupon, not as specs. When a dimension
matters, put the value in params.json and note in spec.md which of these rules
it came from.

## Walls and features
| Feature | Minimum | Comfortable |
|---|---|---|
| Vertical wall | 0.8 mm (2 perimeters) | 1.2-2.0 mm, multiples of extrusion width (~0.45) |
| Horizontal floor/roof | 4 layers (0.8 mm @ 0.2) | 1.2 mm+ |
| Pin / post diameter | 2 mm | 3 mm+ (fragile across layer lines) |
| Embossed/engraved text stroke | 0.8 mm | 1.2 mm; depth/height 0.6 mm+ |
| Gap that must stay open | 0.4 mm | 0.6 mm+ |

## Fits (clearance per side unless noted)
| Fit | Clearance |
|---|---|
| Press fit | 0.0-0.1 mm |
| Snug / sliding fit | 0.15-0.25 mm |
| Loose / free-moving | 0.3-0.5 mm |
| Print-in-place hinge | 0.3-0.4 mm |
| Lid on box | 0.2-0.3 mm |

Vertical holes print **undersize**, usually by 0.1-0.3 mm in diameter. Horizontal holes
print undersize and sag at the top. For anything that matters, print a coupon with
holes at the nominal value plus 0.1, 0.2 and 0.3 mm, measure them, and record the winner
in params.json.

## Fasteners (metric)
| Use | Hole diameter |
|---|---|
| M2 / M2.5 / M3 / M4 / M5 clearance | 2.4 / 2.9 / 3.4 / 4.5 / 5.5 |
| M3 self-tapping into plastic | 2.5-2.8 (depth 2.5x d) |
| M3 heat-set insert (typical short insert) | 4.0-4.2 hole, depth = insert length + 1 |
| M3 hex nut pocket | 5.7-5.8 across flats, 2.6 deep |
| M3 socket-head counterbore | 6.0-6.5 dia, 3.2 deep |
| M3 flat-head countersink | 6.5 head dia, 90 deg |

Check the actual insert or nut datasheet when it's available. Inserts vary by brand.
Avoid modelling threads below M8. Above that, a threaded profile can work if it's
printed vertically with about 0.2 mm clearance.

## Overhangs, bridges, orientation
- Overhangs up to **45 deg from vertical** print fine without support. Flag anything steeper.
- The first two layers are treated as bed: an elephant-foot chamfer lives there and
  the bed supports it, so it is not reported as an overhang.
- Bridges up to about 10 mm are reliable and 20 mm is usually OK. Anything longer needs support or a redesign.
- **Bridge and cantilever are not the same thing.** A flat downward face is a
  bridge only when it is supported at two opposite ends; attached at one end it is
  a cantilever, and attached at none it needs support. The check reports
  `flat_bridge`, `flat_cantilever` or `flat_unsupported` with area, span, center
  and anchor points. Never justify a shelf by calling it a bridge.
- If a down face is declared a bridge in `checks.accept` but the geometry shows
  one-sided support, the check fails with `declared_bridge_is_cantilever`.
- Make horizontal holes > ~5 mm **teardrop**-shaped (`cadlib.teardrop_hole`), or accept a sagging top.
- Under a horizontal overhang, use a 45 deg chamfer instead of a fillet. Fillets on downward edges become steep overhangs near the tangent point.
- On upward and vertical edges, fillets are fine and look better.
- A fillet can make the OCC bounding box slightly larger than the nominal size
  even though material was removed. Set `checks.bbox_mm` from the built part (or
  leave `bbox_tol` loose enough for the fillet), not from the drawing.
- **Layer lines are the weak direction.** Orient the part so the main load runs along the layers, not across them. Hooks, clips and brackets often need to lie on their side.
- Put the largest flat face on the bed when strength allows. Avoid knife-edge bed contact.
- Elephant foot: chamfer outer bed edges 0.3-0.5 mm (`params.print.elephant_foot_chamfer`), especially where a part must fit against something.

## Mechanical features
- **Snap fits:** cantilever length at least 5x thickness (8-10x comfortable), strain
  kept low (`1.5 * t * y / L^2`, under ~2% for PETG, ~1.5% for PLA in reused snaps),
  and printed so the beam flexes along the layers. Add a lead-in chamfer and a
  0.5-1 mm root fillet. See `latches-and-snaps.md` before designing a latch.
- **90 deg retention on a flipped lid:** the retention face becomes a horizontal
  shelf in print orientation. It cannot be support-free. Move the hook to the base
  or use a 45 deg friction catch.
- **Living hinges:** only realistic in PP or TPU, and only printed flat.
- **Cantilevered tabs and bosses:** add ribs or gussets at the root, and fillet internal corners at 0.5-1 mm to reduce stress concentration.
- **Large flat plates:** tend to warp, especially in ABS/ASA. Use ribs instead of thickness, and round the corners.

## Materials (one-line reminders)
| Material | Notes |
|---|---|
| PLA | easy, stiff, creeps under load, softens around 55 C (avoid car interiors) |
| PETG | tougher, slightly stringy, good general functional parts |
| ASA/ABS | heat and UV resistant, warps, needs an enclosure |
| TPU | flexible; walls >= 1.2 mm; avoid fine detail |
| Nylon / CF blends | strong, hygroscopic, dry before printing |

## Resin (SLA/MSLA) differences
If `print.process` is "resin": min wall about 1 mm (0.6 mm for unsupported tiny details).
Add **drain holes** (>= 2 mm, two per hollow, near the build plate end) to any hollow part.
Orient so islands are minimised, and avoid large flat faces parallel to the plate. Most
of the FDM overhang and bridge rules don't apply because supports are expected. Set
`supports_allowed: true`.
