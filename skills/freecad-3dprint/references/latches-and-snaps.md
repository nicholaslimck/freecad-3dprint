# Latches, snaps and retention faces

Read this before designing a lid, latch, catch or snap fit. Most of these
failures are decided by the print orientation, not by the modelling.

The rule that catches people out: **a lid is usually printed upside down, so a
retention face that looks vertical in the assembly becomes a horizontal shelf
in the print.** A shelf has no support underneath and droops or needs support.

## Which faces become overhangs

Put the part in print orientation, then look at every face you rely on.

| Feature in the assembly | Printed lid flipped 180 deg | Verdict |
|---|---|---|
| 90 deg positive catch under a lid lip | horizontal down face (shelf) | not support-free |
| 45 deg lead-in on the outside of the lid | 45 deg down face | prints, may droop |
| 90 deg retention face on the *base* | vertical wall | prints fine |
| Hook standing up from the lid floor | vertical cantilever across layer lines | weak, snaps at layer lines |
| Bead running around the lid perimeter | 45 deg chamfer if you profile it | prints fine |
| Hook on the outside of a lid skirt | horizontal shelf if it faces up in print | check the flip |

The check reports the flat down faces it finds as `flat_bridge`,
`flat_cantilever` or `flat_unsupported` with a center and bbox. A cantilever is
anchored on one side only. Do not write "it is a bridge" without two opposing
anchors in `report.json`: the check fails a declared bridge that is a cantilever
(`declared_bridge_is_cantilever`).

## Cantilever snap fits

- Beam length **at least 5x** its thickness; 8-10x is comfortable.
- Keep strain below about 2% for PETG and 1.5% for PLA in a repeated-use snap.
  `strain ~ 1.5 * t * y / L^2`, with `t` the beam thickness, `y` the deflection, `L` the beam length.
- Flex **along the layers**, not across them. A hook that stands up from a
  printed floor flexes across layer lines and delaminates. Print the beam on its
  side, or make it part of a wall that runs in the layer plane.
- Add a lead-in chamfer (30-45 deg) so the parts assemble without hand force.
- The retention face should be at least 0.5-1 mm deep for a reusable latch.
- Put a root fillet of 0.5-1 mm at the fixed end; sharp internal corners are
  where printed snaps crack.
- A snap that must survive many cycles needs a longer beam and less interference,
  not a thicker hook.

## Retention faces: 45 deg or 90 deg

`90 deg` gives positive retention and needs an undercut. In a one-piece,
support-free, lid-mounted design that undercut is often a horizontal shelf in
print orientation. It cannot be both a 90 deg hook on the lid and support-free
after the flip.

`45 deg` (or 30 deg) is printable as an overhang, but it is friction retention:
it releases under load, and PETG tends to string or droop on the face. Test it.

If you need positive 90 deg retention and supports are not allowed, move the
feature: put the hook on the base (where its retention face is vertical in
print), or use a separate printed insert, a sliding latch or a rotating pawl.

## Decision table

| Constraint | Choose | Avoid |
|---|---|---|
| One piece, printed in place, no supports, 90 deg retention | base-mounted hook + lid catch; or bead/groove | hook on the lid with a horizontal retention face |
| One piece, no supports, 45 deg retention acceptable | 45 deg friction catch with a lead-in; perimeter bead | long thin shelves, vertical cantilevers |
| Two parts, assembly allowed | separate latch/insert, screwed or snapped in | making the lid do everything |
| Needs many open/close cycles | long cantilever in the layer plane, or a sliding/pawl latch | short stiff hooks, 45 deg friction |
| Lid must be sealed | perimeter bead/groove plus one latch | discrete hooks only |
| Flex/impact matters (PETG, PP) | thin section with a long beam, coupon first | thick blocks that cannot flex |

## Alternatives, cheapest first

1. **Perimeter bead and groove** - no discrete latch, prints in any orientation,
   retains by friction and is easy to tune with a bead height of 0.4-0.8 mm and
   a groove 0.2-0.3 mm wider. Measure engagement with a `checks.relations` entry.
2. **45 deg friction catch** - printable, weak, test it.
3. **Base-mounted hook** - positive retention, retention face vertical in print.
4. **Sliding latch** - prints flat, assembled after printing, no flex needed.
5. **Rotating pawl / cam** - positive, serviceable, more parts.
6. **Separate insert** - printed flat or in a different orientation, then fitted.

## Before you print

- Slice the real part with supports off and look at the retention face. A 45 deg
  face that looks fine in the render can still droop in PETG.
- Print a coupon cut from the real latch geometry (`params.coupon`), not a block.
  Flex it, assemble it, count cycles, and record the result in `spec.md`.
- If the check reports `flat_cantilever` or `flat_unsupported` on the retention
  face, do not accept it as "a bridge". Redesign, or accept it explicitly in
  `checks.accept` with evidence and expect the print gate to hold you to it.
