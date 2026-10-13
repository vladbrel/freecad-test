"""A fast headless check; does not open or edit the supplied CAD files."""
import json
import os
from pathlib import Path
import traceback

out = Path(os.environ['FC_STAGE_OUT'])
(out/'progress.json').write_text('{"stage":"startup probe"}',encoding='utf-8')
try:
    import FreeCAD as App
    import Part
    import UtilsAssembly
    if App.GuiUp:
        raise RuntimeError('Use FreeCADCmd, not the GUI executable')
    if not callable(getattr(UtilsAssembly,'getJcsGlobalPlc',None)):
        raise RuntimeError('The native Assembly API is unavailable')
    doc = App.newDocument('StartupProbe')
    body = doc.addObject('PartDesign::Body','Body')
    assembly = doc.addObject('Assembly::AssemblyObject','Assembly')
    shape = Part.makeBox(1,2,3)
    if not shape.isValid() or abs(shape.Volume-6)>1e-8:
        raise RuntimeError('The geometry kernel did not pass its basic check')
    if not callable(getattr(assembly,'solve',None)):
        raise RuntimeError('Native Assembly.solve is unavailable')
    App.closeDocument(doc.Name)
    result = {'ok':True,'version':App.Version(),'gui':bool(App.GuiUp),
              'checks':['Python imports','Part solid','PartDesign','Assembly API','Assembly.solve']}
except Exception:
    result = {'ok':False,'error_kind':'infrastructure','error':traceback.format_exc(limit=8)}
(out/'measure.json').write_text(json.dumps(result),encoding='utf-8')
