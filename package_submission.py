#!/usr/bin/env python3
"""Prepare a small reproducible submission; never include local .env/logs."""
import argparse
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--include-cad',action='store_true',help='Include the downloaded FCStd files for offline use (large archive)')
parser.add_argument('--output',type=Path,default=ROOT/'submission/FreeCAD-CAD-Evaluation.zip')
args=parser.parse_args()
files=[ROOT/name for name in ('.env.example','run_evaluation.py','package_submission.py','SUBMISSION.md')]
project=ROOT/'test_example3';task=project/'FreeCAD/4_sling_lift'
files += [project/name for name in ('README.md','README.assignment.md','env_requirements.txt','tools/fetch.py','docker/freecad-base.Dockerfile')]
files += [task/name for name in ('task.toml','instruction.md','tests/test.sh','environment/Dockerfile')]
files += sorted((task/'tests/task/harness').glob('*.py'))
files += sorted((task/'tests/task/harness').glob('*.md'))
files += [task/'tests/task/harness/validation_scores.json']
if (task/'environment/input.pdf').exists():files.append(task/'environment/input.pdf')
if args.include_cad:
    files += [task/'solution/solution.FCStd',task/'tests/task/reference/solution.FCStd']
    files += sorted((task/'examples').glob('*/*.FCStd'))
for file in files:
    if not file.is_file():raise SystemExit('Missing submission file: '+str(file))
args.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for file in sorted(set(files)):
        relative = file.relative_to(ROOT).as_posix()
        if '.git' in file.relative_to(ROOT).parts:
            raise SystemExit('Git metadata must not be included')
        if file.name == 'validation_scores.json':
            # Keep measured results, but omit the validation machine's paths.
            report = json.loads(file.read_text(encoding='utf-8-sig'))
            for result in report.get('results', []):
                result.get('diagnostics', {}).get('launcher', {}).pop('executable', None)
            archive.writestr(relative, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        else:
            archive.write(file, relative)
print(args.output.resolve())
print('Files:',len(set(files)),'Size:',args.output.stat().st_size,'bytes')
