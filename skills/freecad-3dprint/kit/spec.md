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

## Parts and components
| Part | Separate print? | Expected solids | How it connects | Purpose |
|---|---|---|---|---|
| <e.g. lid> | yes | 1 | hinge to base | closes the case |

<An unexpected extra solid is a floating feature, not a design choice. Declare
intentional multi-solid parts in `checks.expected_solids`.>

## Fits and tolerances
<Press / sliding / loose fits, clearance used for each, and whether a test coupon is needed.
Declare measured checks in params.checks.relations, e.g.
{"name":"bead_groove","a":"lid","b":"base","min_distance_mm":0.1,"max_interference_mm3":0.2}>

## Latch / snap decision (if any)
<Read references/latches-and-snaps.md. Fill this in before modelling.>

| Question | Answer |
|---|---|
| One piece or assembly? | |
| Print-in-place or assembled after printing? | |
| Retention: 90 deg positive or 45 deg friction? | |
| Hook on lid or base? | |
| Which face becomes the down face when printed? | |
| Support-free possible? Why? | |
| Fallback if the print fails? | |

## Loads and use
<Forces, heat, outdoor/UV, chemicals, open/close cycles. Which direction must be strongest (layer lines are the weak axis).>

## Printer and material
Printer: <model>   Nozzle: <0.4>   Layer: <0.2>   Material: <PLA/PETG/ASA/...>
Slicer profile file: <path or "not exported yet">

## Print orientation
<Which face sits on the bed and why. Supports allowed? yes/no.
List the features that become overhangs when flipped.>

## Coupon plan
| Field | Value |
|---|---|
| Needed? | <yes if a fit, flex, snap or seal matters> |
| Source part and section box | <e.g. base, [[-20,-10,8],[20,10,12]] in design coords> |
| Variants | <nominal / loose / tight, and what each changes> |
| Printed orientation | <same as the part, flipped the same way> |
| Pass/fail | <e.g. lip flexes 20x without cracking; snap holds 5 N> |

## Warning triage
<Every warning in out/report.json needs a row. Accepted warnings also need a
matching entry in params.checks.accept (code + region_center_mm + reason +
evidence), or the print gate will not pass.>

| Warning code | Region | Classification | Evidence | Accepted? | Mitigation |
|---|---|---|---|---|---|
| <flat_cantilever> | <center mm> | <cantilever> | <anchors: 1 side, 48 mm2> | no | <redesign> |

## Slicer / preview check
- [ ] Sliced with supports off (`fcp\run.ps1 -Slice`) or previewed in the slicer with supports off
- Preview by / date: <name, date>
- Evidence: <which layers/features were checked, screenshot path>
- Unsupported regions found: <none / list>

## Out of scope
<Things deliberately not modelled: threads, text, cosmetic details...>

## Acceptance criteria
- [ ] report.json passes with every warning triaged
- [ ] bbox matches checks.bbox_mm
- [ ] print_gate.json says printable
- [ ] <functional criterion, e.g. "M3 screw head sits flush">
- [ ] <coupon printed and measured, if fits are tight>

## Open questions
<Anything the agent could not determine. Do not model past an open question on a critical dimension.>
