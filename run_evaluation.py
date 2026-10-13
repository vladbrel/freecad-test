#!/usr/bin/env python3
"""One entry point: dependencies, verified CAD assets, startup check, reports."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import tomllib
import urllib.request

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT/'test_example3'
TASK=PROJECT/'FreeCAD/4_sling_lift'
HARNESS=TASK/'tests/task/harness/harness.py'


def run(args,env):
    print('Running:',subprocess.list2cmdline([str(a) for a in args]),flush=True)
    subprocess.run([str(a) for a in args],cwd=str(ROOT),env=env,check=True)


def fetch_cad():
    with (TASK/'task.toml').open('rb') as handle:
        assets=tomllib.load(handle)['metadata']['assets']
    expected={}
    for asset in assets:
        if asset.get('manifest'):
            entries=[(TASK/asset['path']/name,asset['url'].rstrip('/')+'/'+name,sha)
                     for name,sha,size in asset['manifest'] if name.lower().endswith('.fcstd')]
        elif asset['path'].lower().endswith('.fcstd'):
            entries=[(TASK/asset['path'],asset['url'],asset['sha256'])]
        else:
            continue
        for path,url,sha in entries:expected[path]=(url,sha)
    for path,(url,sha) in expected.items():
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==sha:
            continue
        # Never replace a locally modified CAD file automatically.
        if path.exists():
            raise RuntimeError('CAD checksum differs; move your edited file before fetching: '+str(path))
        print('Downloading:',path.relative_to(ROOT),flush=True)
        path.parent.mkdir(parents=True,exist_ok=True)
        partial=path.with_suffix(path.suffix+'.download')
        with urllib.request.urlopen(url,timeout=60) as source,partial.open('wb') as dest:
            while block:=source.read(1024*1024):dest.write(block)
        if hashlib.sha256(partial.read_bytes()).hexdigest()!=sha:
            raise RuntimeError('Downloaded CAD checksum mismatch: '+str(path))
        partial.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',help='FreeCADCmd executable; otherwise .env/PATH/standard Windows install')
    parser.add_argument('--freecad-mode',choices=('auto','cli','embedded-python'),default='auto')
    parser.add_argument('--use-current-python',action='store_true',help='Use this interpreter instead of a private virtualenv')
    parser.add_argument('--skip-install',action='store_true',help='Dependencies are already installed')
    parser.add_argument('--skip-fetch',action='store_true',help='CAD assets are already present')
    parser.add_argument('--doctor-only',action='store_true',help='Only check FreeCAD startup')
    parser.add_argument('--output',type=Path,default=ROOT/'results')
    args=parser.parse_args()
    if not (3,11)<=sys.version_info[:2]<=(3,13):
        parser.error('Use ordinary Python 3.11, 3.12 or 3.13; FreeCAD uses its own Python separately')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ)
    if args.freecad:env['FREECAD_CMD']=args.freecad
    python=Path(sys.executable)
    if not args.use_current_python:
        venv=ROOT/'.venv-evaluation'
        python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not python.exists():run([sys.executable,'-m','venv',venv],env)
    if not args.skip_install:
        run([python,'-m','pip','install','-r',PROJECT/'env_requirements.txt'],env)
    common=['--freecad-mode',args.freecad_mode,'--diagnostics-out',output/'logs']
    run([python,HARNESS,'--doctor','--report-out',output/'doctor.json',*common],env)
    if args.doctor_only:return 0
    if not args.skip_fetch:fetch_cad()
    run([python,HARNESS,'--corpus','--report-out',output/'scores.json',*common],env)
    rows=json.loads((output/'scores.json').read_text(encoding='utf-8'))
    lines=['# FreeCAD CAD evaluation results','',
           '| Model | Score / 6 | Full credit |','|---|---:|---|']
    for row in rows:
        name=Path(row['candidate']).parent.name
        lines.append('| %s | %.4f | %s |' % (name,row['score'],'yes' if row['passed'] else 'no'))
    lines+=['','Scores are continuous, with the original six equally weighted criteria.',
            'See scores.json for subscores and diagnostic measurements.',
            'The joint_limits_swapped pose question remains documented in DECISIONS.md.']
    (output/'scores.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\nFinished. Read:',output/'scores.md',flush=True)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('Evaluation failed:',exc,file=sys.stderr)
        print('If FreeCAD failed, inspect results/logs and doctor.json.',file=sys.stderr)
        sys.exit(2)
