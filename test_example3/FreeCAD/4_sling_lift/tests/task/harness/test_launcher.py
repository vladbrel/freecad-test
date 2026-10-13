"""Launcher regressions. No CAD installation is needed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import freecad_process as f

class LauncherTests(unittest.TestCase):
    def test_posix_has_no_windows_backend_or_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/'freecadcmd';exe.touch()
            plans=f.launch_plans(str(exe),platform='posix')
            self.assertEqual(len(plans),1)
            self.assertEqual(plans[0]['backend'],'cli')
            self.assertEqual(plans[0]['executable'],str(exe.resolve()))

    def test_windows_prefers_official_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'bin').mkdir()
            exe=root/'bin'/'freecadcmd.exe';exe.touch()
            wrapper=root/'FreeCADCmd.exe';wrapper.touch()
            plans=f.launch_plans(str(exe),platform='nt')
            self.assertEqual(plans[0]['executable'],str(wrapper.resolve()))
            self.assertEqual(plans[1]['executable'],str(exe.resolve()))

    def test_startup_failure_retries_and_selects_bundled_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'source.py';script.write_text('pass')
            plans=[{'backend':kind,'executable':str(root/name),'root':str(root)}
                   for kind,name in [('cli','wrapper.exe'),('cli','freecadcmd.exe'),('embedded-python','python.exe')]]
            def run(args,**kwargs):
                folder=Path(kwargs['env']['FC_STAGE_OUT'])
                self.assertEqual(kwargs['input'],'')
                self.assertNotIn('stdin',kwargs)
                if args[0].endswith('python.exe'):
                    (folder/'progress.json').write_text('{"stage":"imports"}')
                    (folder/'measure.json').write_text('{"ok":true}')
                    return subprocess.CompletedProcess(args,0,'','')
                self.assertEqual(len(args),2)
                self.assertNotIn('-u',args);self.assertNotIn('-s',args)
                return subprocess.CompletedProcess(args,1,'','Application unexpectedly terminated')
            with patch.object(f,'launch_plans',return_value=plans),patch.object(f.subprocess,'run',side_effect=run) as calls:
                result=f.run_freecad(str(root/'configured.exe'),script,root/'out',10)
            self.assertEqual(calls.call_count,3)
            self.assertEqual(result['returncode'],0)
            self.assertEqual(result['attempts'][-1]['backend'],'embedded-python')

    def test_crash_after_script_start_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'source.py';script.write_text('pass')
            plans=[{'backend':'cli','executable':'first','root':str(root)},
                   {'backend':'embedded-python','executable':'second','root':str(root)}]
            def run(args,**kwargs):
                folder=Path(kwargs['env']['FC_STAGE_OUT'])
                (folder/'progress.json').write_text('{"stage":"motion check"}')
                return subprocess.CompletedProcess(args,1,'','crash')
            with patch.object(f,'launch_plans',return_value=plans),patch.object(f.subprocess,'run',side_effect=run) as calls:
                result=f.run_freecad('fake.exe',script,root/'out',10)
            self.assertEqual(calls.call_count,1)
            self.assertEqual(result['returncode'],1)

    def test_profile_is_temporary_and_python_settings_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ,{'PYTHONPATH':'foreign','PYTHONHOME':'foreign','QT_PLUGIN_PATH':'foreign'}):
                env=f.child_environment(Path(temp)/'run',Path(temp))
            for key in ('PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH'):
                self.assertNotIn(key,env)
            for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP'):
                self.assertTrue(Path(env[key]).is_dir())
                self.assertTrue(Path(env[key]).is_relative_to(Path(temp)))

if __name__=='__main__':unittest.main()
