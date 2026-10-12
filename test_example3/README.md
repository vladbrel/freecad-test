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

You can also put this setting in `.env`. Then run:

```sh
python FreeCAD/4_sling_lift/tests/task/harness/harness.py FreeCAD/4_sling_lift/solution/solution.FCStd
python FreeCAD/4_sling_lift/tests/task/harness/harness.py --corpus
python -m unittest discover -s FreeCAD/4_sling_lift/tests/task/harness -p test_scoring.py
```

The output is JSON containing `score`, `max_score`, `passed` and `subscores`.
Use `--measurement-out facts.json` to keep the facts behind a single result.

## Six criteria

Each criterion contributes one point:

1. Assembly completeness.
2. Geometry and actual dimensions.
3. Pantograph joints physically mated.
4. Movement within enabled limits and the intended hanging arrangement.
5. Editable dimensions on modeled part roles.
6. Those dimensions actually change the resulting solids.

The separate build gate gives zero if the document cannot rebuild valid
solids. Geometry tolerances and connection errors produce gradual penalties.
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
