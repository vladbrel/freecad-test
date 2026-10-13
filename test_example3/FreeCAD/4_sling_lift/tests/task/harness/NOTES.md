# FreeCAD Sling Lift grader

The grader uses the original six criterion names and integer weights (one
point each). Each criterion returns a continuous score from 0 to 1, as the
assignment requests. `measure_stage.py` reads CAD facts in a separate FreeCAD
process; `harness.py` scores those facts under ordinary Python. No LLM is used.

The original assignment is preserved in `test_example3/README.assignment.md`.
`DECISIONS.md` explains the business decisions and contains an unsent draft
question to the employer about ambiguous examples.

## Setup

Use Python 3.11 or later. From `test_example3`:

```sh
pip install -r env_requirements.txt
python tools/fetch.py
python FreeCAD/4_sling_lift/tests/task/harness/harness.py FreeCAD/4_sling_lift/solution/solution.FCStd
python FreeCAD/4_sling_lift/tests/task/harness/harness.py --corpus --diagnostics-out freecad-logs
python -m unittest discover -s FreeCAD/4_sling_lift/tests/task/harness -p test_scoring.py
```

Copy the repository's `.env.example` to `.env` and set `FREECAD_CMD` to your
existing FreeCAD 1.1 headless executable. The harness finds `.env` from its
own location, so changing the current directory does not change that search.
Priority: an explicit environment variable, repository `.env`, project `.env`,
task `.env`, then PATH. If an old environment variable points to the wrong
file, update or unset it before using `.env`. Quotes, spaces, comments, UTF-8
BOM and paths relative to the `.env` file are supported.

`--measurement-out facts.json` keeps facts and diagnostics for one submission.
`--diagnostics-out freecad-logs` also retains stdout, stderr, the last recorded
stage and the measurement file when available. This includes native crashes
and timeouts. A missing executable, missing reference, unavailable API or
native crash is an infrastructure error (exit 2), not a measured CAD defect.
The single-candidate command has a 600-second measurement budget. Corpus mode
measures the reference once and gives each candidate its own budget.

## Original six criteria

| Criterion | What is measured |
|---|---|
| geometry matches ground truth | Shape and real size of installed parts, including missing parts and unexplained extras. |
| pantograph joints mated | Required connections resolve to actual installed parts and meet physically. |
| mechanism articulates | The native solver reaches nearby input positions; links rotate, connections hold and enabled limits are respected. |
| carries dimensional constraints | Modeled part roles have editable upstream driving dimensions. |
| dimensions drive the geometry | A small dimension edit changes a valid resulting solid. |
| signature dimensions present | Short-link length 150 mm, hole spacing 120 mm, width 30 mm and thickness 10 mm from the drawing. |

A separate build gate, with weight zero, gives zero overall when the document
cannot rebuild valid solids. Weights stay integer; partial fulfillment and
therefore the total score can be fractional. Do not round the total to an
integer: that would hide defects.

Completeness, average shape quality, hanging arrangement and individual key
measurements are returned in `diagnostics`. Hanging arrangement does not
change the score. Missing connections/parameters with a missing endpoint are
excluded from those checks; geometry already accounts for missing parts.
Missing a required short link also means its signature dimensions are absent.
A connection failure can prevent articulation: both observable criteria may
lose credit for one underlying fault.

## Geometry

Only installed instances are counted; unused source definitions are omitted.
Links are measured at their actual installed scale. Parts are matched by
volume, area and inertia with a one-to-one assignment. Matching removes size
only to find corresponding roles; grading retains millimetres. Rigid motion
and reflection are accepted. Object names connect records, not answers.

Shape quality combines volume/area, principal inertia-derived lengths,
cylinder radii and 384 deterministic surface samples (0.15 mm tessellation).
Length/radius errors up to 0.3% and volume/area up to 0.8% receive full credit;
larger errors lose credit continuously. Sampling-spacing tolerance makes the
surface check coarse: it is not proof of every small cut. Geometry averages
matched shape scores over the reference's installed-part count, gives zero
for missing roles and subtracts unexplained extras. Two ISO 8752 6x16 pins
shown in the PDF are allowed additions; the reference omits them.

## Signature dimensions

The short-link role is identified in the reference by physical dimensions,
not a body name or constraint label. Both installed instances are checked.
Parallel bore axes supply the spacing and orientation. Surface samples give
length, width and thickness in that frame. Face normals distinguish bore
walls from outer rounded caps, so deleted holes cannot earn spacing credit
from the surviving round ends. Older measurements without normals use a
full-cylindrical-wall check; the current producer includes normals.

Full-credit tolerances in mm: length 0.2, spacing 0.05, width 0.1, thickness
0.05. Errors then fade to zero at 40% of the target dimension. The four marks
are averaged. These are four selected distinctive dimensions, not every
annotation in the PDF. Reading bore axes supports native cylindrical BRep
surfaces. If they are absent, exterior dimensions use principal directions
and hole spacing is unverified. A NURBS/mesh-only bore representation needs
an additional geometric reader before equivalent submissions can be graded
fairly; this limitation is not a claim that those representations are wrong.

## Joints, motion and parameters

Native Assembly references are resolved through FreeCAD's Assembly API.
Joint count alone earns nothing. Gap tolerance is 0.05 mm, fading to zero at
5 mm; axis/frame tolerance is 0.2 degrees, fading at 20 degrees. Opposite
axis directions and equivalent fixed connection chains are accepted.

The first native slider is temporarily fixed at four nearby input positions,
inside enabled slider bounds. The native solver moves the other parts in
small steps. Joint definitions are restored before checking physical gaps,
relative rotation and enabled bounds. Angles are compared modulo 360 degrees.
All placements and settings are restored; the CAD document is never saved.

Parameter checks follow the source part's dependencies: driving sketch
constraints, feature dimensions and numeric spreadsheet inputs referenced
by expressions. Up to three substantial dimensions per source are tried
at +2%; testing stops at a successful meaningful response. Volume, area and
invariant mass moments detect change. Imported reference hardware is excluded
from the demand to rebuild parametric threads. A response of 0.01% earns
full response credit; smaller changes earn a fraction. Inactive second pad
lengths and inactive chamfer angles are excluded.

This proves a selected dimension can change each modeled role, not that
every key dimension is independently editable or that large size changes
remate the entire assembly. The signature criterion reads resulting geometry;
it is distinct from that limited parameter-response test.

## Compatibility and scope

Tested natively on official FreeCAD 1.1.4, Windows headless, including the
full reference command and measurements of all five examples. The earlier
measurement code also ran successfully on that release: incompatibility of
UtilsAssembly with 1.1.4 is not established. The reported native termination was reproduced with a Cyrillic script path
on Windows 1.1.4. The CLI failed before Python started; the bundled-Python
fallback recovered successfully. ASCII paths containing spaces worked. Python exceptions are caught; native termination cannot
be caught by Python inside the dying process. The parent detects it, reports
the last recorded stage and retains diagnostics when requested.

FreeCAD uses its own Python/Qt; PYTHONHOME, PYTHONPATH and Qt plugin paths from
the scoring environment are removed for the subprocess. Results are written
before closing the CAD document, and an unsuccessful process exit is always
an error even if a measurement file exists. This is process isolation, not
a security sandbox for hostile documents.

Movement supports FreeCAD 1.1 built-in Assembly and its nested links. Other
assembly workbenches need an adapter. Local trials do not prove the entire
workspace, collisions, load capacity, material strength or the 30 kg rating.
Merging multiple physical parts into one solid also needs a richer separator.
The Docker recipe remains pinned to 1.1.3 and was not built in this Windows
validation; local 1.1.4 results must not be presented as Docker validation.

## Current validation (2026-10-13)

The JSON report is `validation_scores.json`. There are 26 scoring/setup
regressions, including the original criterion names, integer weights, mirrors,
actual size changes, partial penalties, fake joints, decorative parameters,
.env parsing, crashes/timeouts, signature spacing and outer-cap rejection.

| Model | Score / 6 | Reduced criteria |
|---|---:|---|
| solution | 6.0000 | None |
| assembly_mirrored_relative_to_ground_truth | 5.9929 | Geometry only; reflection accepted. |
| dummy_joints_inflate_the_count | 4.9300 | Geometry, joints, movement. |
| half_finished_missing_features | 5.8547 | Geometry, including missing parts. |
| joint_limits_swapped | 5.9929 | Geometry only; limits defect not established. |
| one_link_missing_joints_bridge_gap | 4.9255 | Geometry, joints, movement. |

The mirror and several other examples share sleeve cuts different from the
reference. The mirrored sleeve volume is 27408.9913 mm³ rather than 24551.5165
mm³ after forced rebuild; the reflection itself incurs no penalty.

The supplied joint_limits_swapped and mirrored examples have the same enabled
slider range (-180 to -130 mm), both in the saved Document.xml and in native
measurements. Both move within it. Their hanging/folding arrangement differs.
Whether that working arrangement is mandatory needs clarification from the
employer. The grader reports it without inventing a limits penalty. See the
unsent clarification draft in DECISIONS.md. This corpus issue remains open.


## Portable launcher update

`freecad_process.py` starts the official Windows root launcher when available,
then the direct console executable, then (only on startup failure) the same
bundle's Python. No CAD trial is retried once progress exists. Linux/macOS use
the normal CLI. The CLI receives only the script path, without -u/-s flags.
FreeCAD's documented FREECAD_USER_HOME/DATA/TEMP variables point to precreated
temporary directories. They isolate settings without CLI configuration flags.
Subprocess cwd is the Windows install directory, stdin is an empty pipe,
stdout/stderr are files, and no shell/console-creation flags are used.

`--doctor` checks imports, geometry, PartDesign and Assembly before loading
assets. `--report-out` saves UTF-8 JSON. Root `run_evaluation.py` handles setup
and writes a readable table. See SUBMISSION.md for reviewer instructions.
CLI and embedded Python both measured the complete reference at 6/6. Native
Windows tests covered the Unicode startup failure and automatic recovery;
Linux/macOS selection is unit-tested, not natively executed here.
