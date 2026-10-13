# CAD Evaluation Engineer submission

The grader implements the original six equally weighted criteria, continuous
scores and deterministic FreeCAD measurements. There is no LLM dependency.
The included validation report records the supplied solution at exactly 6/6.

## For the reviewer: one-command reproduction

Requirements: ordinary Python 3.11, 3.12 or 3.13; FreeCAD 1.1 (tested on 1.1.4).
Install FreeCAD from its official distribution. Unzip this submission and open
a terminal in the directory containing `run_evaluation.py`.

Windows PowerShell, when FreeCAD is installed at the usual location:

```powershell
py -3.12 run_evaluation.py
```

If Python is available as `python`, that command is also supported. If FreeCAD
is portable or installed elsewhere, supply its path explicitly:

```powershell
py -3.12 run_evaluation.py --freecad "C:\Program Files\FreeCAD 1.1\FreeCADCmd.exe"
```

Both the root launcher and `bin\freecadcmd.exe` paths are accepted. A standard
Windows installation is discovered automatically if no path is configured.
An explicit `--freecad` overrides a stale FREECAD_CMD environment variable.
Alternatively set the path once in a local `.env` based on `.env.example`.

Linux/macOS, with FreeCADCmd on PATH (or supply `--freecad /actual/path`):

```sh
python3 run_evaluation.py
```

The script creates a private `.venv-evaluation`, installs the two pinned
scoring dependencies, checks FreeCAD startup, fetches the seven CAD files from
the original assignment URLs and verifies their SHA-256 checksums, then grades
the supplied solution and five examples. Existing edited CAD files are never
silently overwritten. An existing virtualenv can be reused on later runs.
Downloading assets/dependencies needs network access; the corpus run takes
several minutes. Each model has a measurement timeout.

Output:

- `results/doctor.json`: actual FreeCAD version and startup backend.
- `results/scores.md`: compact readable score table.
- `results/scores.json`: complete score/criterion/diagnostic breakdown.
- `results/logs/`: exact launch commands, working directories, all attempts,
  stdout/stderr and the last measurement stage.

To use an existing Python environment, install `test_example3/env_requirements.txt`
and add `--use-current-python --skip-install`. With offline CAD assets already
present, add `--skip-fetch`. Scoring Python and FreeCAD's Python are separate.

## Quick startup check and Windows recovery

```powershell
py -3.12 run_evaluation.py --doctor-only
```

On Windows 1.1.4 the console launcher can terminate before running a Python
script whose path contains Cyrillic characters. This exact failure was
reproduced: exit 1, `Application unexpectedly terminated`, no progress file.
ASCII paths with spaces worked. The automatic launcher recovered by using
`python.exe` bundled inside the SAME FreeCAD installation; the geometry kernel,
Assembly API and scoring rules remain the same. Both backends measured the full
reference assembly and independently received 6/6.

The console command is simply `FreeCADCmd script.py`, without `-u`/`-s` flags,
shell wrappers or forced console-creation flags. FreeCAD's documented portable
profile environment variables keep settings/data/temp inside the measurement
folder. This preserves the reviewer's own preferences. The Windows launcher
uses the installation directory as cwd and puts its DLL directory first.

The bundled-Python fallback is Windows-only and is attempted only if the CLI
fails BEFORE any progress/measurement is written. A failure while measuring
CAD is never rerun behind the reviewer's back. Linux/macOS retain the normal
headless CLI path. Native Linux/macOS execution was not performed in this
Windows environment; their launch selection is covered by regression tests.

If necessary, explicitly bypass a broken Windows console launcher:

```powershell
py -3.12 run_evaluation.py --freecad-mode embedded-python
```

This requires `bin/python.exe` and `bin/FreeCAD.pyd` from the FreeCAD bundle.
It never imports FreeCAD into the scoring Python. If both modes fail, inspect
the saved logs rather than treating the failure as a CAD score.

## Evaluation choices and open corpus question

Detailed rules and tolerances are in
`test_example3/FreeCAD/4_sling_lift/tests/task/harness/NOTES.md`.
The original assignment text is preserved in `test_example3/README.assignment.md`.
The six criterion names/weights match the original stub. Reflection is valid.
Completeness belongs to geometry; hanging pose is diagnostic only. Signature
checks cover short-link length 150, hole spacing 120, width 30 and thickness
10 mm from the PDF. All geometry edits and solver trials are restored; the
original CAD files are not saved.

The supplied `joint_limits_swapped` and mirrored files have identical enabled
slider limits (-180 to -130 mm), both in their saved XML and in measurements.
Both move inside them. Their hanging pose differs. Whether a required working
pose should be graded needs clarification; the grader does not invent a limits
penalty to match the example filename. Several examples also share sleeve cuts
different from the reference. These differences are reported independently
from reflection. See DECISIONS.md for an unsent clarification draft.

## Sending this submission

Build the small archive:

```sh
python package_submission.py
```

`submission/FreeCAD-CAD-Evaluation.zip` contains source, tests, drawing (if
available), setup script, original metadata and validation results. It excludes
local `.env`, virtualenvs, runtime binaries and diagnostic logs. CAD assets are
fetched from the authors' URLs when the reviewer runs it.

For an offline reviewer, use `python package_submission.py --include-cad` and
send a download link instead of a large email attachment. The archive still
excludes the FreeCAD installation and scoring environment.

Send to `careers@storygold.com`, subject **CAD Evaluation Engineer**, as the
recruitment message requests. Attach the small ZIP, or provide a repository /
archive link the recipient can access. Suggested text:

> Hello StoryGold Team,
>
> Please find my FreeCAD CAD Evaluation Engineer submission attached.
> SUBMISSION.md contains one-command reproduction instructions. The grader
> uses the original six criteria, continuous deterministic scores and no LLM.
> The supplied solution scores 6/6 on FreeCAD 1.1.4 headless. Startup supports
> the Windows console launcher and the same bundle's Python as a fallback.
> The validation report and an explicitly documented corpus ambiguity are
> included. Running `python run_evaluation.py` produces a readable score table
> and the detailed JSON report.
>
> Kind regards,
> [Your name]

No email has been sent by the assistant. Review the code, results and the open
question before submitting; the draft is provided for you to adapt.
