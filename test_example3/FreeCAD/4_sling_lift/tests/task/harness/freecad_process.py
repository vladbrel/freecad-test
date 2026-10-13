"""Start FreeCAD independently of the scoring interpreter (stdlib only)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

_SELECTED = {}


def launch_plans(command, platform=None):
    """Windows bundles have an official launcher and their own Python."""
    platform = platform or os.name
    executable = Path(shutil.which(command) or command).resolve()
    root = executable.parent.parent if executable.parent.name.lower() == 'bin' else executable.parent
    plans = []
    if platform == 'nt':
        wrapper = root / 'FreeCADCmd.exe'
        if wrapper.is_file() and wrapper != executable:
            plans.append({'backend':'cli', 'executable':str(wrapper), 'root':str(root)})
    plans.append({'backend':'cli', 'executable':str(executable), 'root':str(root)})
    if platform == 'nt':
        direct = root / 'bin' / 'freecadcmd.exe'
        if direct.is_file() and direct != executable:
            plans.append({'backend':'cli', 'executable':str(direct), 'root':str(root)})
        python = root / 'bin' / 'python.exe'
        if python.is_file() and (root / 'bin' / 'FreeCAD.pyd').is_file():
            plans.append({'backend':'embedded-python', 'executable':str(python), 'root':str(root)})
    selected = _SELECTED.get(str(executable))
    if selected in plans:
        plans.remove(selected)
        plans.insert(0, selected)
    return plans


def discover_command():
    for name in ('freecadcmd','FreeCADCmd','FreeCADCmd.exe'):
        command = shutil.which(name)
        if command:
            return command
    if os.name == 'nt':
        for key in ('ProgramFiles','ProgramW6432','LOCALAPPDATA'):
            folder = os.environ.get(key)
            if not folder:
                continue
            parent = Path(folder) / 'Programs' if key == 'LOCALAPPDATA' else Path(folder)
            installs = sorted(parent.glob('FreeCAD*'),key=lambda p:('1.1' not in p.name,p.name))
            for install in installs:
                for candidate in (install/'FreeCADCmd.exe',install/'bin'/'freecadcmd.exe'):
                    if candidate.is_file():
                        return str(candidate)
    return None


def child_environment(out, root, extra=None):
    env = dict(os.environ)
    for name in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(name, None)
    # FreeCAD documents this portable profile mechanism on all three OSes.
    # The directories must exist before the application starts.
    for name, folder in (('FREECAD_USER_HOME','profile'),('FREECAD_USER_DATA','profile'),
                         ('FREECAD_USER_TEMP','temp')):
        path = Path(out) / folder
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    if os.name == 'nt':
        env['PATH'] = str(Path(root)/'bin') + os.pathsep + env.get('PATH','')
    env.update(extra or {})
    env['FC_STAGE_OUT'] = str(out)
    env['FC_INSTALL_ROOT'] = str(root)
    return env


def run_freecad(command, script, out, timeout, extra=None, mode='auto'):
    """Retry startup only. Once progress exists, never rerun CAD mutations."""
    plans = launch_plans(command)
    if mode != 'auto':
        plans = [p for p in plans if p['backend'] == mode]
    if not plans:
        raise OSError('No %s backend is available in this FreeCAD installation' % mode)
    started = time.monotonic()
    history = []
    record = None
    for index, plan in enumerate(plans):
        remaining = timeout - (time.monotonic()-started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        folder = Path(out) / ('attempt-%s' % (index+1))
        folder.mkdir(parents=True, exist_ok=True)
        # Use the same short ASCII filename for the probe and measurements.
        # Python reads the UTF-8 script rather than FreeCAD importing a file
        # directly from a possibly Unicode workspace path.
        task = folder / 'run_task.py'
        shutil.copyfile(script, task)
        env = child_environment(folder, plan['root'], extra)
        args = [plan['executable'], str(task)]
        if plan['backend'] == 'embedded-python':
            env['FC_RUN_SCRIPT'] = str(task)
            args = [plan['executable'], '-s', str(Path(__file__).with_name('embedded_bootstrap.py'))]
        cwd = plan['root'] if os.name == 'nt' else str(folder)
        launch = {'backend':plan['backend'], 'argv':args, 'cwd':cwd,
                  'profile':env['FREECAD_USER_HOME']}
        (folder/'launch.json').write_text(json.dumps(launch,indent=2),encoding='utf-8')
        try:
            with (folder/'stdout.log').open('w',encoding='utf-8') as stdout, (folder/'stderr.log').open('w',encoding='utf-8') as stderr:
                # No shell, detached-console flags or NUL stdin. Empty input
                # supplies a valid pipe and EOF; log files avoid pipe buffering.
                process = subprocess.run(args, cwd=cwd, env=env, input='',
                                         stdout=stdout, stderr=stderr, text=True,
                                         encoding='utf-8', errors='replace', timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            exc.stage_directory = folder
            raise
        stdout_text = getattr(process,'stdout',None) or (folder/'stdout.log').read_text(encoding='utf-8',errors='replace')
        stderr_text = getattr(process,'stderr',None) or (folder/'stderr.log').read_text(encoding='utf-8',errors='replace')
        history.append(dict(launch,returncode=process.returncode))
        record = {'returncode':process.returncode,'stdout':stdout_text,'stderr':stderr_text,
                  'directory':folder,'attempts':history}
        (Path(out)/'attempts.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        entered = (folder/'progress.json').exists() or (folder/'measure.json').exists()
        if process.returncode == 0 and (folder/'measure.json').exists():
            _SELECTED[str(Path(shutil.which(command) or command).resolve())] = plan
            return record
        if entered:
            return record
    return record
