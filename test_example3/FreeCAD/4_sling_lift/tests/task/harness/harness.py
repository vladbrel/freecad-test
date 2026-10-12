#!/usr/bin/env python3
"""Grading harness for 4_sling_lift -- A STUB. Writing it is the exercise.

    python3 tests/task/harness/harness.py solution/solution.FCStd

Runs as it stands: it measures the document and prints a valid score
envelope in which every component scores zero and says why. That is the
contract you are filling in, not a starting implementation -- there is no
grading logic here to edit, and none was generated for you.

WHAT IT HAS TO DO

    the reference   solution/solution.FCStd must score 6 of 6.
    the adversarials  every folder under examples/ must lose the
                      component(s) it actually breaks, and only those.

Grade the geometry and the parametric structure the instruction asks for.
Do not grade object names, document-tree shape, or anything that is true
of the reference by coincidence: a candidate who models the lift a
different way and gets it right must still score 6 of 6. That is the
whole difficulty of the task, and the corpus is built to catch a harness
that takes the easy route.

THE SPLIT, WHICH IS WORTH KEEPING

This file does not import FreeCAD. It runs `measure_stage.py` under
`freecadcmd` (the FREECAD_CMD environment variable), and scores the JSON
that comes back. Two reasons, both practical: the scoring half
stays testable on a machine with no FreeCAD, and a candidate's document
never gets to run its own macros inside the grader's interpreter.

`measure_stage.py` is a stub too. What it measures is your decision --
that choice IS the design of the harness, so it was left to you.

THE CONTRACT

The stub is split into two functions:

    build_state(candidate_path) -> dict
        Expensive shared setup, run once. Whatever the checks read.

    checks(state) -> {name: (name, score, description)}
        `score` is a float in [0, 1]. `description` is the sentence a
        human reads next to the number; make it say what was measured,
        not just pass or fail.

SCORE CONTINUOUSLY. A bool is accepted and is almost always the wrong
answer. Most of these components are questions of degree, and collapsing
them to pass/fail throws away the information that makes a grader useful:

    five joints wanted, three mated                 -> 0.6, not 0
    a link 4% short of the drawing                  -> 0.9, not 0
    two of four signature dimensions present        -> 0.5, not 0

A candidate who gets most of it right should score most of the marks, and
two candidates who are wrong by different amounts should not land on the
same number. Reserve a hard 0 or 1 for components that genuinely have no
middle -- "does it rebuild without errors" is one, and it is the gate.

`MUST_PASS` names components that zero the whole score when they fail.
`ALL_CRITERIA` prices them; `max_score` in task.toml must equal the sum.

The seven below are the components the task shipped with. They are a
suggestion, not a requirement: split, merge, reweight, rename or replace
them as your reading of instruction.md warrants, and say why in your
notes. Keep task.toml's max_score in step.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Weight per component; 0 makes it a gate when it is also in MUST_PASS.
#: The sum must equal task.toml's max_score (6 today).
ALL_CRITERIA = {
    "executes and builds geometry": 0,
    "geometry matches ground truth": 1,
    "pantograph joints mated": 1,
    "mechanism articulates": 1,
    "carries dimensional constraints": 1,
    "dimensions drive the geometry": 1,
    "signature dimensions present": 1,
}
MUST_PASS = ("executes and builds geometry",)
MAX_SCORE = 6
TIMEOUT_S = 600

TODO = "not implemented -- see the docstring at the top of harness.py"


def run_stage(candidate_path):
    """Run measure_stage.py under freecadcmd; return (measurement, error)."""
    fc = os.environ.get("FREECAD_CMD")
    if not fc:
        return None, "FREECAD_CMD is not set (point it at a freecadcmd binary)"
    if not candidate_path or not Path(candidate_path).is_file():
        return None, f"no candidate file: {candidate_path}"
    with tempfile.TemporaryDirectory() as out:
        env = dict(os.environ, FC_STAGE_INPUT=str(Path(candidate_path).resolve()), FC_STAGE_OUT=out)
        try:
            subprocess.run([fc, str(HERE / "measure_stage.py")], env=env,
                           capture_output=True, text=True, timeout=TIMEOUT_S)
        except Exception as exc:                            # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
        f = Path(out) / "measure.json"
        if not f.is_file():
            return None, "the measurement stage wrote no measure.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        if not data.get("ok", True):
            return None, data.get("error", "the measurement stage failed")
        return data, None


def build_state(candidate_path):
    """Measure the candidate once; the checks read what this returns."""
    measurement, error = run_stage(candidate_path)
    return {"candidate": candidate_path, "measurement": measurement or {}, "error": error}


def checks(state):
    """One entry per component: {name: (score in [0, 1], description)}.

    Every one scores 0.0 and says so, except the gate. Replace them with
    real measurements taken from state["measurement"].
    """
    err = state["error"]
    out = {"executes and builds geometry": (
        1.0 if err is None else 0.0,
        "the measurement stage ran" if err is None else f"the measurement stage failed: {err}")}
    for name in ALL_CRITERIA:
        out.setdefault(name, (0.0, TODO))
    return out


def finalize(results):
    gated = any(results[n][0] < 1.0 for n in MUST_PASS)
    score = 0.0 if gated else sum(ALL_CRITERIA[n] * results[n][0] for n in ALL_CRITERIA)
    return {
        "score": round(score, 4),
        "max_score": MAX_SCORE,
        "passed": score >= MAX_SCORE,
        "subscores": {n: {"score": s, "weight": ALL_CRITERIA[n], "description": d}
                      for n, (s, d) in results.items()},
    }


def main(argv):
    candidate = argv[1] if len(argv) > 1 else None
    print(json.dumps(finalize(checks(build_state(candidate))), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
