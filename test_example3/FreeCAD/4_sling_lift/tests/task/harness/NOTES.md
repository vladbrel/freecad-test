# How this grader works

The grader runs without an LLM or a FreeCAD window. `measure_stage.py` opens
one document in FreeCAD, collects facts and writes JSON. `harness.py` runs
under ordinary Python and turns those facts into six scores between 0 and 1.
The original document is never saved. Object names connect records within a
measurement; they are not a list of accepted answers.

## Run

From `test_example3`, use Python 3.11 or later:

```sh
pip install -r env_requirements.txt
python tools/fetch.py
python FreeCAD/4_sling_lift/tests/task/harness/harness.py FreeCAD/4_sling_lift/solution/solution.FCStd
python FreeCAD/4_sling_lift/tests/task/harness/harness.py --corpus
python -m unittest discover -s FreeCAD/4_sling_lift/tests/task/harness -p test_scoring.py
```

Set `FREECAD_CMD` to the FreeCAD 1.1 `freecadcmd` executable, either in the
environment or in `.env`. On PowerShell, for example:

```powershell
$env:FREECAD_CMD = 'C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe'
```

Use `--measurement-out facts.json` to retain the measured facts for a single
candidate. The frozen reference is `tests/task/reference/solution.FCStd`,
loaded separately from the submission. `tools/fetch.py` downloads it too.
A missing executable/reference is a setup error (exit 2), not a CAD defect.
The subprocess has a time limit of 600 seconds. Each run uses separate
FreeCAD settings so it does not change the user's settings. The Docker
recipe has been updated but was not built in this Windows environment.

## Six points

| Check | What earns the point |
|---|---|
| Assembly completeness | Required installed parts exist, without unexplained extras. |
| Geometry and dimensions | Their shape and actual size in millimetres match the reference. |
| Pantograph joints mated | Required connections resolve to real installed parts and meet physically. |
| Mechanism articulates within its limits | FreeCAD solves nearby input positions; links rotate, joints stay together, enabled limits hold and the mechanism hangs below its suspension ring. |
| Dimensional control coverage | Modeled part roles have editable upstream dimensions. |
| Dimensions drive the geometry | Changing those dimensions changes a valid resulting solid. |

A document that cannot rebuild valid solids receives zero through a separate
build gate. This gate has no point of its own. Each other check weighs one.
A missing part is charged to completeness; its absent connections and absent
parameters are excluded from the remaining checks. Existing malformed parts
can still lose geometry points. A broken connection may also stop movement:
these are two observable failures, not a penalty based on its filename.

## Measurements and tolerances

Only installed instances are counted. Unused source parts and copied assembly
definitions are excluded. Links are measured at their installed scale. Part
roles are matched by volume, surface area and inertia, using a one-to-one
assignment. Size is removed only when finding corresponding roles; grading
keeps the real dimensions. Rigid rotation, translation and reflection are
allowed. No filename or document hash gives a submission full credit.

Geometry combines relative volume/area errors, principal inertia-derived
lengths, cylinder radii and a deterministic surface sample (384 points,
0.15 mm tessellation). Length/radius differences up to 0.3% and volume/area
up to 0.8% receive full credit. Larger errors lose credit continuously.
The surface comparison includes sampling-spacing tolerance, so it is a
coarse shape check, not proof that every small feature is correct. Two
ISO 8752 6x16 spring pins shown in the drawing are permitted additions:
the supplied reference omits them. Recognition uses geometric measurements.

Joint references are resolved through FreeCAD's native Assembly API. Joint
count alone earns nothing. Gap tolerance is 0.05 mm, fading to zero at 5 mm;
axis/frame tolerance is 0.2 degrees, fading to zero at 20 degrees. Opposite
axis directions are valid. Equivalent fixed connection chains are accepted.

For movement, the first native slider supplies the input. It is temporarily
locked at four nearby positions; enabled slider bounds restrict the trials.
The native solver moves the remaining parts, in small steps. Measurements
then check physical gaps, rotation and enabled bounds. Angular bounds are
compared modulo 360 degrees. The hanging-side check uses the ring-to-shackle
direction, so a global rotation or mirror has no effect. It detects the
supplied swapped-limits example's wrong folded branch, without assuming a
particular world axis. Joint definitions and placements are restored.

Parameter checks follow the source part's dependencies, looking for driving
sketch dimensions, feature dimensions and numeric spreadsheet inputs used by
expressions. Up to three substantial dimensions per unique source are changed
by 2%, then restored. Volume, area and invariant mass moments detect whether
the solid changes. Imported reference hardware is excluded from the demand
for editable dimensions. A response of 0.01% or more earns full response
credit; smaller responses earn a fraction. Inactive secondary lengths and
inactive chamfer angles are excluded.

## Scope and limits

The movement test supports FreeCAD 1.1's built-in Assembly, including nested
Assembly links. Other assembly workbenches need an explicit adapter. This is
a local movement test, not a proof of the entire reachable workspace. It does
not certify load capacity, collisions, material strength or the 30 kg rating.
The hanging-side test checks the submitted pose; it does not prohibit every
possible unusual pose of an otherwise correct mechanism.

Parameter coverage is measured by part role, not by every dimension in the
PDF. Three edits do not prove that every key dimension is independent, nor
that the complete assembly remates correctly after large size changes.
Equivalent bodies and links are supported; merging several physical parts
into one solid changes the part matching and needs a richer part separator.
Process isolation handles crashes, but is not a security sandbox for hostile
FreeCAD documents.

## Validation

Native integration runs use FreeCAD 1.1.3 on Windows, headless. The score
report is in `validation_scores.json`. Unit regressions cover exact 6/6,
reflection, real scale changes, missing parts, dummy joints, decorative
parameters, failed builds, continuous gap penalties and hanging orientation.

The model called `assembly_mirrored_relative_to_ground_truth` is not a pure
reflection: its two sleeve parts have volume 27408.9913 mm³ instead of
24551.5165 mm³ after a forced rebuild. Only this real geometry difference
reduces its score. The mirror itself is valid. The supplied example labels
are descriptions to investigate, not truth that overrides measurements.


| Model | Score / 6 | Reduced criteria |
|---|---:|---|
| solution | 6.0000 | None |
| assembly_mirrored_relative_to_ground_truth | 5.9929 | Geometry only; reflection accepted. |
| dummy_joints_inflate_the_count | 4.9300 | Geometry, physical joints, movement. |
| half_finished_missing_features | 5.8509 | Completeness and geometry only. |
| joint_limits_swapped | 4.9929 | Geometry and working hanging arrangement. |
| one_link_missing_joints_bridge_gap | 4.9255 | Completeness, physical joints, movement. |

Several supplied examples share the changed sleeve geometry, so their score
can include that small geometry loss as well as the defect in the filename.
The single-candidate command was also run end to end: the supplied solution
returned exactly 6/6 with `passed: true`. Checksums of all seven CAD files
(including the separate frozen reference) remained equal to their manifests.
