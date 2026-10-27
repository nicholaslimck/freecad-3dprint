# Part spec: <name>

## Purpose
<What the part does, where it goes, what it attaches to.>

## Interfaces (measured, not guessed)
| Mates with | Feature | Measured value | Measured how | Param name |
|---|---|---|---|---|
| <e.g. M3 screw> | through hole | 3.0 mm shank | datasheet | hole_d (3.4 clearance) |

## Key dimensions
| Param | Value (mm) | Hard limit or flexible? | Why |
|---|---|---|---|

## Fits and tolerances
<Press / sliding / loose fits, clearance used for each, and whether a test coupon is needed.>

## Loads and use
<Forces, heat, outdoor/UV, chemicals. Which direction must be strongest (layer lines are the weak axis).>

## Printer and material
Printer: <model>   Nozzle: <0.4>   Layer: <0.2>   Material: <PLA/PETG/ASA/...>
Slicer profile file: <path or "not exported yet">

## Print orientation
<Which face sits on the bed and why. Supports allowed? yes/no>

## Out of scope
<Things deliberately not modelled: threads, text, cosmetic details...>

## Acceptance criteria
- [ ] report.json passes
- [ ] bbox matches checks.bbox_mm
- [ ] <functional criterion, e.g. "M3 screw head sits flush">
- [ ] <test coupon printed and measured, if fits are tight>

## Open questions
<Anything the agent could not determine. Do not model past an open question on a critical dimension.>
