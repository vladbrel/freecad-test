"""Windows fallback: use ONLY the Python shipped with this FreeCAD bundle."""
import json
import os
from pathlib import Path
import runpy
import sys
import traceback

out = Path(os.environ['FC_STAGE_OUT'])
(out/'progress.json').write_text('{"stage":"embedded Python bootstrap"}',encoding='utf-8')
try:
    root = Path(os.environ['FC_INSTALL_ROOT'])
    handles = []
    for folder in (root/'bin',root/'lib'):
        if not folder.is_dir():
            continue
        if hasattr(os,'add_dll_directory'):
            handles.append(os.add_dll_directory(str(folder)))
        sys.path.insert(0,str(folder))
    sys.path.insert(0,str(root/'Mod'/'Assembly'))
    import FreeCAD
    import Part
    import _PartDesign
    import Sketcher
    import Spreadsheet
    import AssemblyApp
    runpy.run_path(os.environ['FC_RUN_SCRIPT'],run_name='__main__')
except Exception:
    (out/'measure.json').write_text(json.dumps({'ok':False,'error_kind':'infrastructure',
        'error':traceback.format_exc(limit=12)}),encoding='utf-8')
    raise
