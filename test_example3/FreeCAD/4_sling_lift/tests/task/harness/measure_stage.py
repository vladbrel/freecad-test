"""Measurement stage for 4_sling_lift -- A STUB, like harness.py.

Runs inside `freecadcmd`, not in the harness's interpreter. It is
launched by harness.py's `run_stage` with two environment variables
already set:

    FC_STAGE_INPUT    the document to measure
    FC_STAGE_OUT      a directory to write measure.json into

Implement `measure(doc) -> dict`. This file writes it to `measure.json`,
recording any exception as `{"ok": false, "error": ...}` rather than
letting it escape. Your harness reads that dict back.

**Stdlib and FreeCAD only.** This runs in freecadcmd's own Python, which
is not the interpreter your harness runs in and does not have your pip
packages. Anything from numpy up belongs on the scoring side.

WHAT TO MEASURE IS THE DESIGN QUESTION

It is deliberately empty. What comes back from here decides what the
harness can grade, so choosing it is most of the work, not a detail to
fill in afterwards. instruction.md asks for a lift that is driven by key
dimensions rather than dead geometry, with its pantograph joints mated so
it articulates. Some things that might be worth getting out of the
document -- none of them prescribed:

  * the solids, and something comparable about their shape and size that
    survives a candidate modelling the lift in a different order, or
    mirrored;
  * the joints: what kind, what they connect, whether they actually
    constrain anything, and their limits;
  * whether the mechanism moves -- and a way to tell "moves" from
    "flies apart";
  * where the dimensions live: sketch constraints, spreadsheet cells,
    expressions, named parameters. And, separately, whether changing one
    changes the geometry, which is a different question from whether it
    exists.

The last of those is worth dwelling on. A document can carry a tidy set
of named constraints that drive nothing at all, and the corpus contains
models built to look right in exactly that way.
"""
import json
import os
import traceback

import FreeCAD                                            # freecadcmd only


def measure(doc):
    """Return the JSON-serialisable measurement the harness scores.

    `doc` is the opened FreeCAD document. Everything returned has to
    survive `json.dumps` -- FreeCAD vectors, placements and objects do
    not, so convert them to lists and plain values here.
    """
    # TODO: this is the exercise. Measure the document and return it.
    return {
        "objects": len(doc.Objects),
        "note": "measure_stage.py is a stub -- nothing is measured yet",
    }


def run():
    out = os.path.join(os.environ["FC_STAGE_OUT"], "measure.json")
    try:
        doc = FreeCAD.openDocument(os.environ["FC_STAGE_INPUT"])
        doc.recompute()
        result = dict(measure(doc), ok=True)
    except Exception:                                     # noqa: BLE001
        result = {"ok": False, "error": traceback.format_exc(limit=3)}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)


run()
