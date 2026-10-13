# Sling Lift grader

This repository contains a deterministic grader for the FreeCAD 1.1 Sling
Lift task. It uses FreeCAD's Python API to read installed parts, joints and
editable dimensions, then calculates six scores without an LLM.

The reference must receive exactly 6/6. Broken examples lose credit for
measured defects. Object names, document tree layout and example filenames
do not supply the answer. A valid reflected model is accepted.

## Setup and run

From this directory, with Python 3.11 or later:

```sh
pip install -r env_requirements.txt
python tools/fetch.py
```

Large CAD assets are downloaded from the URLs and checksums in `task.toml`.
Set `FREECAD_CMD` to your FreeCAD 1.1 headless executable. On PowerShell:

```powershell
$env:FREECAD_CMD = 'C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe'
```

On Linux, for example:

```sh
export FREECAD_CMD=/usr/bin/freecadcmd
```

Copy `../.env.example` to `../.env` and set the executable path once.
The harness reads it independently of the current directory. An explicitly
set environment variable takes priority. Then run:

```sh
python FreeCAD/4_sling_lift/tests/task/harness/harness.py FreeCAD/4_sling_lift/solution/solution.FCStd
python FreeCAD/4_sling_lift/tests/task/harness/harness.py --corpus
python -m unittest discover -s FreeCAD/4_sling_lift/tests/task/harness -p test_scoring.py
```

The output is JSON containing `score`, `max_score`, `passed` and `subscores`.
Use `--measurement-out facts.json` to keep the facts behind a single result.

## Six criteria

Each criterion contributes one point:

1. Geometry matches ground truth, including missing/unexplained extra parts.
2. Pantograph joints physically mated.
3. Mechanism articulates within enabled limits.
4. Carries dimensional constraints.
5. Dimensions drive the geometry.
6. Signature dimensions present: short-link length 150, hole spacing 120,
   width 30 and thickness 10 mm.

The separate build gate gives zero if the document cannot rebuild valid
solids. Geometry tolerances and connection errors produce gradual penalties.
The original assignment is preserved in [README.assignment.md](README.assignment.md).
The original six criterion names and integer weights are restored. Additional
checks are reported under `diagnostics`; continuous scores remain as required
by the assignment. The scoring decision and unresolved limits/pose issue are in
[DECISIONS.md](FreeCAD/4_sling_lift/tests/task/harness/DECISIONS.md).
The detailed choices, limitations and actual corpus results are documented
in [NOTES.md](FreeCAD/4_sling_lift/tests/task/harness/NOTES.md).

The supplied example labels need checking against the CAD facts. In
particular, the mirrored example also has different sleeve cuts. Its
reflection is accepted; those real geometry differences reduce its score.

## Files

Task files are under `FreeCAD/4_sling_lift/`:

| Path | Purpose |
|---|---|
| `instruction.md` | Candidate's brief. |
| `environment/input.pdf` | Technical drawing. |
| `task.toml` | Metadata, asset URLs and checksums. |
| `solution/solution.FCStd` | Supplied solution. |
| `examples/` | Five adversarial CAD documents. |
| `tests/task/reference/solution.FCStd` | Frozen grading reference. |
| `tests/task/harness/measure_stage.py` | FreeCAD measurements in a separate process. |
| `tests/task/harness/harness.py` | Ordinary Python scoring and command line interface. |
| `tests/task/harness/test_scoring.py` | Scoring regressions without FreeCAD. |
| `tests/task/harness/validation_scores.json` | Headless integration results. |
| `tests/test.sh` | Harbor verifier entrypoint. |

The original exercise had no `common/` directory. The grader is self-contained
and depends on NumPy and SciPy in its scoring interpreter. Measurement uses
only modules supplied with FreeCAD. Temporary edits are restored and the CAD
file is never saved.

## Docker

From this directory:

```sh
docker build -f docker/freecad-base.Dockerfile -t freecad-base:latest .
docker build -f FreeCAD/4_sling_lift/environment/Dockerfile -t sling-lift FreeCAD/4_sling_lift/environment
```

The base image supplies FreeCAD 1.1.3 and the Python dependencies. Harbor
mounts the tests; `tests/test.sh` grades `/app/solution.FCStd` and writes
`/logs/verifier/reward.json`. The Docker recipe was not built during the
Windows validation run.


For a startup or native crash, keep the logs:

```sh
python FreeCAD/4_sling_lift/tests/task/harness/harness.py --corpus --diagnostics-out freecad-logs
```

The error includes the last recorded stage and FreeCAD version when available.
Python exceptions produce JSON inside the measurement process; native crashes
are detected by the parent process. A native crash cannot be caught by Python
`try/except`. FreeCAD uses its own Python and Qt, isolated from those settings
in the scoring environment.
