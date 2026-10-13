#!/usr/bin/env python3
"""Deterministic lift grader. FreeCAD runs only in the measurement subprocess.

Usage:
    python harness.py solution.FCStd
    python harness.py --corpus

Install env_requirements.txt and set FREECAD_CMD (or put it in .env).
The drawing supplies the requirements; the frozen reference supplies shape
measurements. Object names are used only to join records, never as answers.
"""
import argparse
import itertools
import uuid
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from freecad_process import discover_command, run_freecad

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[2]
REFERENCE = HERE.parent / 'reference' / 'solution.FCStd'
TIMEOUT_S = 600
SCHEMA_VERSION = 2
ENV_FILES = (TASK.parents[2] / '.env', TASK.parents[1] / '.env', TASK / '.env')
DIAGNOSTICS_OUT = None
FREECAD_MODE = 'auto'
ALL_CRITERIA = {
    'executes and builds geometry': 0,
    'geometry matches ground truth': 1,
    'pantograph joints mated': 1,
    'mechanism articulates': 1,
    'carries dimensional constraints': 1,
    'dimensions drive the geometry': 1,
    'signature dimensions present': 1,
}
MUST_PASS = ('executes and builds geometry',)
MAX_SCORE = sum(ALL_CRITERIA.values())


class InfrastructureError(RuntimeError):
    """A grader/setup error must not be presented as a CAD defect."""


def clamp(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('A score is not finite')
    return max(0.0, min(1.0, value))


def band(error, tolerance, zero_at):
    """Full credit inside a tolerance, then a continuous fall to zero."""
    return clamp(1.0 - max(0.0, float(error)-tolerance) / (zero_at-tolerance))


def average(values, default=0.0):
    values = list(values)
    return sum(values)/len(values) if values else default


def load_freecad_command():
    command = os.environ.get('FREECAD_CMD', '').strip().strip('\"\'')
    if not command:
        # Explicit environment > repository .env > project .env > task .env.
        # Read only FREECAD_CMD, without importing unrelated settings/secrets.
        for env_file in ENV_FILES:
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding='utf-8-sig').splitlines():
                key, separator, value = line.strip().removeprefix('export ').partition('=')
                if not separator or key.strip() != 'FREECAD_CMD':
                    continue
                value = value.strip()
                if value.startswith(('"', "'")):
                    end = value.find(value[0], 1)
                    if end < 0:
                        raise InfrastructureError('Unclosed quote in FREECAD_CMD in %s' % env_file)
                    value = value[1:end]
                else:
                    value = value.split(' #', 1)[0].strip()
                if value:
                    command = os.path.expandvars(os.path.expanduser(value))
                    if not Path(command).is_absolute() and not shutil.which(command):
                        command = str((env_file.parent / command).resolve())
                    break
            if command:
                break
    command = command or discover_command()
    if not command:
        raise InfrastructureError('Set FREECAD_CMD in the repository .env to the FreeCAD 1.1 headless executable')
    if not Path(command).is_file() and not shutil.which(command):
        raise InfrastructureError('FREECAD_CMD does not point to an existing executable: %s' % command)
    if Path(command).name.lower() in ('freecad.exe','freecad'):
        raise InfrastructureError('Use the headless FreeCADCmd executable, not FreeCAD GUI')
    return command


def keep_diagnostics(out, candidate_path, stdout='', stderr=''):
    if not DIAGNOSTICS_OUT:
        return
    target = Path(DIAGNOSTICS_OUT)/(Path(candidate_path).stem+'-'+uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=True)
    for name, value in (('stdout.log', stdout), ('stderr.log', stderr)):
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        (target/name).write_text(value or '', encoding='utf-8')
    for name in ('measure.json','progress.json','launch.json'):
        file=Path(out)/name
        if file.exists():
            shutil.copy2(file,target/name)
    attempts=Path(out).parent/'attempts.json'
    if attempts.exists():
        shutil.copy2(attempts,target/attempts.name)
        for folder in Path(out).parent.glob('attempt-*'):
            saved=target/folder.name
            saved.mkdir(exist_ok=True)
            for name in ('stdout.log','stderr.log','progress.json','launch.json'):
                file=folder/name
                if file.exists():
                    shutil.copy2(file,saved/name)


def run_script(script, candidate_path=None, timeout=TIMEOUT_S):
    command = load_freecad_command()
    with tempfile.TemporaryDirectory(prefix='sling-measure-') as out:
        extra = {'FC_STAGE_INPUT':str(Path(candidate_path).resolve())} if candidate_path else {}
        label = candidate_path or 'startup-probe'
        try:
            record = run_freecad(command, script, out, timeout, extra, mode=FREECAD_MODE)
        except subprocess.TimeoutExpired as exc:
            folder = getattr(exc,'stage_directory',Path(out))
            keep_diagnostics(folder, label, exc.stdout, exc.stderr)
            progress = folder/'progress.json'
            stage = progress.read_text(encoding='utf-8') if progress.exists() else 'startup'
            raise InfrastructureError('FreeCAD exceeded its time limit; last stage: %s' % stage)
        except OSError as exc:
            raise InfrastructureError('Could not start FreeCAD: %s' % exc) from exc
        folder=record['directory']
        output=folder/'measure.json'
        progress=folder/'progress.json'
        stage=progress.read_text(encoding='utf-8') if progress.exists() else 'before Python script startup'
        keep_diagnostics(folder,label,record['stdout'],record['stderr'])
        if record['returncode'] or not output.is_file():
            tail=(record['stderr']+'\n'+record['stdout'])[-2500:]
            raise InfrastructureError('FreeCAD terminated or wrote no measurement (exit %s); last stage: %s; %s. Run --doctor --diagnostics-out freecad-logs' %
                                      (record['returncode'],stage,tail))
        try:
            data=json.loads(output.read_text(encoding='utf-8'),
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError,OSError) as exc:
            raise InfrastructureError('FreeCAD wrote an invalid measurement: %s' % exc) from exc
        if not data.get('ok'):
            if data.get('error_kind')=='infrastructure':
                raise InfrastructureError(data.get('error','FreeCAD API is unavailable'))
            return None,data.get('error','FreeCAD could not read this document')
        data['launcher']={'backend':record['attempts'][-1]['backend'],
                          'executable':record['attempts'][-1]['argv'][0]}
        return data,None


def run_stage(candidate_path, timeout=TIMEOUT_S):
    """Setup errors raise; a readable but invalid CAD file returns its error."""
    if not candidate_path or not Path(candidate_path).is_file():
        return None,'No candidate FCStd file was found'
    data,error=run_script(HERE/'measure_stage.py',candidate_path,timeout)
    if data and data.get('schema_version')!=SCHEMA_VERSION:
        raise InfrastructureError('The measurement schema is incompatible with the grader')
    return data,error


def load_reference(timeout=TIMEOUT_S):
    if not REFERENCE.is_file():
        raise InfrastructureError('Missing frozen reference: run tools/fetch.py to download CAD assets')
    data,error = run_stage(REFERENCE, timeout)
    if error or not data['build']['valid']:
        raise InfrastructureError('The frozen reference cannot be measured: %s' % (error or data['build']['errors']))
    if not data['motion'].get('supported'):
        raise InfrastructureError('The reference motion test is unavailable: %s' % data['motion'].get('error'))
    return data


def build_state(candidate_path, reference=None, timeout=TIMEOUT_S):
    started = time.monotonic()
    reference = reference if reference is not None else load_reference(timeout)
    measurement,error = run_stage(candidate_path, timeout-(time.monotonic()-started))
    return {'candidate':str(candidate_path), 'measurement':measurement or {},
            'reference':reference, 'error':error}


def eigenfacts(shape):
    values, axes = np.linalg.eigh(np.asarray(shape['inertia'],dtype=float))
    return np.maximum(values,1e-12),axes


def shape_descriptor(shape):
    values,_ = eigenfacts(shape)
    volume = max(shape['volume'],1e-12)
    # Remove size ONLY for matching roles. The actual grade retains mm.
    return np.r_[np.log(values/(volume**(5/3))), math.log(max(shape['area'],1e-12)/volume**(2/3))]


def matching(reference, candidate):
    """Match roles by shape; spatial information only breaks repeated-part ties."""
    rp,cp = reference['parts'],candidate['parts']
    if not rp or not cp:
        return [], len(rp), len(cp)
    rd = np.array([shape_descriptor(reference['shapes'][p.get('shape',p['source'])]) for p in rp])
    cd = np.array([shape_descriptor(candidate['shapes'][p.get('shape',p['source'])]) for p in cp])
    cost = np.mean(np.abs(rd[:,None,:]-cd[None,:,:]),axis=2)
    initial_r,initial_c=linear_sum_assignment(cost)
    rv=np.array([max(p['volume'],1e-12) for p in rp])
    cv=np.array([max(p['volume'],1e-12) for p in cp])
    log_scale=float(np.median(np.log(cv[initial_c]/rv[initial_r])))
    cost += 0.3*np.abs(np.log(cv[None,:]/rv[:,None])-log_scale)
    rcent = np.array([p['centre'] for p in rp]); rcent-=rcent.mean(axis=0)
    ccent = np.array([p['centre'] for p in cp]); ccent-=ccent.mean(axis=0)
    _,ra = np.linalg.eigh(rcent.T@rcent)
    _,ca = np.linalg.eigh(ccent.T@ccent)
    scale = max(float(np.linalg.norm(rcent,axis=1).max()),1)
    best = None
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1,1),repeat=3):
            rotation = ca[:,permutation] @ np.diag(signs) @ ra.T
            aligned = ccent@rotation
            positional = np.linalg.norm(rcent[:,None,:]-aligned[None,:,:],axis=2)/scale
            rows,cols = linear_sum_assignment(cost + 0.0001*np.minimum(positional,2))
            value = float(sum(cost[rows,cols]+0.0001*np.minimum(positional[rows,cols],2)))
            if best is None or value < best[0]:
                best = value,rows,cols
    pairs = [(int(r),int(c)) for r,c in zip(best[1],best[2]) if cost[r,c] <= 0.7]
    return pairs,len(rp)-len(pairs),len(cp)-len(pairs)


def surface_error(reference, candidate):
    """Compare surfaces after a rigid move or a reflection; never change scale."""
    r=np.asarray(reference['points'],dtype=float)
    c=np.asarray(candidate['points'],dtype=float)
    _,ra=eigenfacts(reference); _,ca=eigenfacts(candidate)
    tree_r=cKDTree(r)
    starts=[]
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1,1),repeat=3):
            transform=ca[:,permutation]@np.diag(signs)@ra.T
            moved=c@transform
            error=float(np.quantile(np.r_[tree_r.query(moved)[0],cKDTree(moved).query(r)[0]],0.9))
            starts.append((error,moved))
    best=min(item[0] for item in starts)
    # Round/cubic parts have non-unique inertia axes. Refine the best starting
    # orientations so rotating one of these parts cannot cause a false penalty.
    for error,moved in sorted(starts,key=lambda item:item[0])[:4]:
        for _ in range(12):
            _,nearest=tree_r.query(moved)
            target=r[nearest]
            mc=moved.mean(axis=0); tc=target.mean(axis=0)
            u,_,vt=np.linalg.svd((moved-mc).T@(target-tc))
            correction=u@vt
            if np.linalg.det(correction)<0:
                u[:,-1]*=-1
                correction=u@vt
            moved=(moved-mc)@correction+tc
        distances=np.r_[tree_r.query(moved)[0],cKDTree(moved).query(r)[0]]
        best=min(best,float(np.quantile(distances,0.9)))
    return best


def geometry_score(reference, candidate):
    if reference == candidate:
        return 1.0
    rv,cv = reference['volume'],candidate['volume']
    ri,_ = eigenfacts(reference); ci,_ = eigenfacts(candidate)
    # Convert mass moments into length measures. Volume alone misses moved holes.
    lengths_r = np.sqrt(ri/max(rv,1e-12)); lengths_c=np.sqrt(ci/max(cv,1e-12))
    size_error = float(np.max(np.abs(lengths_r-lengths_c)/np.maximum(lengths_r,1)))
    volume_error = abs(rv-cv)/max(rv,cv,1)
    area_error = abs(reference['area']-candidate['area'])/max(reference['area'],candidate['area'],1)
    characteristic = max(float(np.max(lengths_r)),1)
    surface=surface_error(reference,candidate)
    spacing=max(math.sqrt(reference['area']/len(reference['points'])),math.sqrt(candidate['area']/len(candidate['points'])))
    surface_score=band(surface,1.5*spacing,1.5*spacing+0.3*characteristic)
    radius_score=1.0
    if reference['cylinders'] and candidate['cylinders']:
        radii=sorted({round(c['radius'],6) for c in reference['cylinders']})
        observed=sorted({round(c['radius'],6) for c in candidate['cylinders']})
        radius_score=average(band(min(abs(r-a) for a in observed)/max(r,1),0.003,0.4) for r in radii)
    # Sampling spacing is larger than BRep numerical tolerance; exact dimension
    # and mass checks prevent a sparse sample from hiding a wrong size.
    return min(band(size_error,0.003,0.4), band(volume_error,0.008,0.65),
               band(area_error,0.008,0.65),surface_score,radius_score)


def drawing_pin(shape):
    # The main drawing includes two ISO 8752 pins (diameter 6, length 16).
    # They are absent from the frozen reference, so a candidate must not lose
    # completeness for adding these explicitly requested small parts.
    points=np.asarray(shape['points'])
    _,axes=eigenfacts(shape)
    extents=sorted(np.ptp(points@axes,axis=0))
    return (5.4<=extents[0]<=7.0 and 5.4<=extents[1]<=7.0
            and 15.4<=extents[2]<=16.5 and 250<=shape['volume']<=480)


def unexplained_extras(reference,candidate,pairs):
    matched={c for r,c in pairs}
    allowance=max(0,2-sum(drawing_pin(reference['shapes'][p.get('shape',p['source'])]) for p in reference['parts']))
    unexpected=0
    for c,part in enumerate(candidate['parts']):
        if c in matched:
            continue
        if allowance and drawing_pin(candidate['shapes'][part.get('shape',part['source'])]):
            allowance-=1
        else:
            unexpected+=1
    return unexpected


def joint_quality(joint):
    if not joint['valid'] or joint['suppressed']:
        return 0.0
    return min(band(joint['gap'],0.05,5.0),band(joint['axis_error'],0.2,20.0),
               band(joint['rotation_error'],0.2,20.0))


class FixedGroups:
    def __init__(self, ids):
        self.parent = {i:i for i in ids}
    def find(self, i):
        if self.parent[i] != i:
            self.parent[i] = self.find(self.parent[i])
        return self.parent[i]
    def join(self, a,b):
        self.parent[self.find(a)] = self.find(b)


def joint_coverage(reference,candidate,pairs):
    mapped = {reference['parts'][r]['id']:candidate['parts'][c]['id'] for r,c in pairs}
    groups = FixedGroups([p['id'] for p in candidate['parts']])
    for joint in candidate['joints']:
        if joint['type'] == 'Fixed' and joint_quality(joint) == 1:
            members = joint['members'][0]+joint['members'][1]
            for a,b in zip(members,members[1:]):
                groups.join(a,b)
    scores=[]
    # Missing parts are charged to completeness. Here we grade connections
    # between the parts that exist, to avoid mechanically repeating penalties.
    for expected in reference['joints']:
        left=[mapped[i] for i in expected['members'][0] if i in mapped]
        right=[mapped[i] for i in expected['members'][1] if i in mapped]
        if not left or not right:
            continue
        best=0.0
        if expected['type']=='Fixed' and any(groups.find(a)==groups.find(b) for a in left for b in right):
            best=1.0
        for actual in candidate['joints']:
            if actual['type']!=expected['type']:
                continue
            a,b=actual['members']
            def overlaps(first,second):
                return any(groups.find(x)==groups.find(y) for x in first for y in second)
            if (overlaps(left,a) and overlaps(right,b)) or (overlaps(left,b) and overlaps(right,a)):
                best=max(best,joint_quality(actual))
        scores.append(best)
    return average(scores,default=1.0),len(scores)


def parameter_scores(reference,candidate,pairs):
    coverage=[]; driving=[]
    visited=set()
    for r,c in pairs:
        rp=reference['parts'][r]; cp=candidate['parts'][c]
        # Imported bolts in the reference are not demands to rebuild thread sketches.
        expected_parameters=reference['parameters'][rp['source']]
        if not expected_parameters['controls'] or not any(p['ok'] and p['change']>=0.0001 for p in expected_parameters['probes']):
            continue
        key=(rp['source'],cp['source'])
        if key in visited:
            continue
        visited.add(key)
        expected=reference['parameters'][rp['source']]
        actual=candidate['parameters'][cp['source']]
        # Credit the part role, rather than requiring the reference's sketch
        # direction names or its exact count of dimensions. A pad property,
        # a spreadsheet and an equivalent sketch are equally legitimate.
        coverage.append(1.0 if actual['controls'] else 0.0)
        successful=[p for p in actual['probes'] if p['ok']]
        response=max((p['change'] for p in successful),default=0.0)
        driving.append(clamp(response/0.0001))

    return average(coverage,default=1.0),average(driving,default=1.0),len(visited)


def motion_score(measurement):
    motion=measurement['motion']
    if not motion.get('supported'):
        raise InfrastructureError('Motion measurement unavailable: %s' % motion.get('error'))
    results=[]
    for probe in motion['probes']:
        if not probe['ok']:
            results.append(0)
            continue
        results.append(min(band(probe['gap'],0.05,5),band(probe['axis_error'],0.2,20),
                           min(clamp(probe['relative_motion']/0.01),clamp(probe['relative_motion']/(10*max(probe.get('input_fraction',0.05),1e-6)))),probe['limit_score']))
    return average(results)


def working_layout(reference, candidate, pairs):
    """The mechanism hangs below the ring, whatever the world axes or mirror."""
    neighbours = {p['id']:set() for p in reference['parts']}
    for joint in reference['joints']:
        for a in joint['members'][0]:
            for b in joint['members'][1]:
                if a != b:
                    neighbours[a].add(b)
                    neighbours[b].add(a)
    landmarks=[]
    for index,part in enumerate(reference['parts']):
        if len(neighbours[part['id']]) != 1:
            continue
        shape=reference['shapes'][part.get('shape',part['source'])]
        _,axes=eigenfacts(shape)
        extents=sorted(np.ptp(np.asarray(shape['points'])@axes,axis=0))
        if 12 <= extents[0] <= 20 and extents[1] > 40 and extents[2] > 60:
            landmarks.append(index)
    if not landmarks:
        return 1.0
    ring=max(landmarks,key=lambda i:reference['parts'][i]['volume'])
    ids={part['id']:i for i,part in enumerate(reference['parts'])}
    shackle=ids[next(iter(neighbours[reference['parts'][ring]['id']]))]
    mapped=dict(pairs)
    if ring not in mapped or shackle not in mapped:
        return 1.0  # Missing hardware is already charged to completeness.
    def projection(data, mapping):
        top=np.asarray(data['parts'][mapping[ring]]['centre'])
        below=np.asarray(data['parts'][mapping[shackle]]['centre'])
        up=top-below
        length=np.linalg.norm(up)
        if length < 1e-6:
            return 0.0
        weights=[]; values=[]
        for r,c in mapping.items():
            if r not in (ring,shackle):
                weights.append(reference['parts'][r]['volume'])
                values.append(np.dot(np.asarray(data['parts'][c]['centre'])-below,up/length))
        return float(np.average(values,weights=weights)) if weights else 0.0
    expected=projection(reference,{r:r for r,c in pairs})
    if expected >= -1e-6:
        return 1.0
    return band(projection(candidate,mapped)/abs(expected),-0.1,0.1)


# Four distinctive dimensions of the short link, from the PDF drawing.
# The criteria stay independent: this reads geometry, not parameter labels.
SIGNATURE_TARGETS = {'length':150.0, 'hole_spacing':120.0, 'width':30.0, 'thickness':10.0}
SIGNATURE_TOLERANCES = {'length':0.2, 'hole_spacing':0.05, 'width':0.1, 'thickness':0.05}


def link_dimension_options(shape):
    points=np.asarray(shape['points'],dtype=float)
    options=[]
    cylinders=[]
    for cylinder in shape.get('cylinders',[]):
        if cylinder.get('internal') is not None:
            if cylinder['internal']:
                cylinders.append(cylinder)
            continue
        # Older measurements lack the normal direction. A full cylindrical
        # wall is a bore here; rounded link ends cover only half a circle.
        axis=np.asarray(cylinder['axis'],dtype=float)
        axis/=max(np.linalg.norm(axis),1e-12)
        thickness=float(np.ptp(points@axis))
        fraction=cylinder.get('area',0)/(2*math.pi*max(cylinder['radius']*thickness,1e-12))
        if fraction > 0.65:
            cylinders.append(cylinder)
    for a,b in itertools.combinations(cylinders,2):
        axis=np.asarray(a['axis'],dtype=float)
        axis/=max(np.linalg.norm(axis),1e-12)
        other=np.asarray(b['axis'],dtype=float)
        other/=max(np.linalg.norm(other),1e-12)
        if abs(np.dot(axis,other)) < 0.9999:
            continue
        delta=np.asarray(b['centre'],dtype=float)-np.asarray(a['centre'],dtype=float)
        delta-=axis*np.dot(delta,axis)
        spacing=float(np.linalg.norm(delta))
        if spacing < 1.0:
            continue
        along=delta/spacing
        across=np.cross(axis,along)
        options.append({'length':float(np.ptp(points@along)),
                        'hole_spacing':spacing,
                        'width':float(np.ptp(points@across)),
                        'thickness':float(np.ptp(points@axis))})
    return options


def dimension_marks(values):
    return {name:band(abs(values[name]-target),SIGNATURE_TOLERANCES[name],0.4*target)
            for name,target in SIGNATURE_TARGETS.items()}


def signature_dimensions(reference,candidate,pairs):
    mapped=dict(pairs)
    rows=[]
    for r,part in enumerate(reference['parts']):
        shape=reference['shapes'][part.get('shape',part['source'])]
        options=link_dimension_options(shape)
        # Find the drawing's short-link role by measured geometry, not its name.
        if not any(all(abs(v[name]-target)<=SIGNATURE_TOLERANCES[name]
                       for name,target in SIGNATURE_TARGETS.items()) for v in options):
            continue
        if r not in mapped:
            rows.append({'reference_part':part['id'],'candidate_part':None,
                         'values':None,'scores':dict.fromkeys(SIGNATURE_TARGETS,0.0)})
            continue
        actual=candidate['parts'][mapped[r]]
        actual_shape=candidate['shapes'][actual.get('shape',actual['source'])]
        options=link_dimension_options(actual_shape)
        if options:
            values=max(options,key=lambda v:average(dimension_marks(v).values()))
            scores=dimension_marks(values)
        else:
            # Straight exterior dimensions remain measurable without circular
            # surfaces. Hole spacing is unverified if no hole axes resolve.
            _,axes=eigenfacts(actual_shape)
            extents=sorted(np.ptp(np.asarray(actual_shape['points'])@axes,axis=0))
            values=dict(length=float(extents[2]),width=float(extents[1]),
                        thickness=float(extents[0]),hole_spacing=0.0)
            scores=dimension_marks(values)
        rows.append({'reference_part':part['id'],'candidate_part':actual['id'],
                     'values':values,'scores':scores})
    if not rows:
        raise InfrastructureError('The reference has no measurable 150/120/30/10 mm short link')
    score=average(mark for row in rows for mark in row['scores'].values())
    return score,rows


def checks(state):
    data=state['measurement']; reference=state['reference']; error=state['error']
    valid=not error and data.get('build',{}).get('valid',False)
    out={'executes and builds geometry':(float(valid),'The document rebuilds and contains valid solids' if valid
                                         else 'No valid rebuilt assembly: %s' % (error or data.get('build',{}).get('errors')))}
    if not valid:
        for name in ALL_CRITERIA:
            out.setdefault(name,(0.0,'Not evaluated because the document did not build'))
        return out
    pairs,missing,extra=matching(reference,data)
    extra=unexplained_extras(reference,data,pairs)
    count=len(reference['parts'])
    completeness=clamp(1-(missing+extra)/max(count,1))
    scores=[]; cache={}
    for r,c in pairs:
        rp=reference['parts'][r]; cp=data['parts'][c]
        key=(rp.get('shape',rp['source']),cp.get('shape',cp['source']))
        if key not in cache:
            cache[key]=geometry_score(reference['shapes'][key[0]],data['shapes'][key[1]])
        scores.append(cache[key])
    out['geometry matches ground truth']=(clamp((sum(scores)-extra)/max(count,1)),
        'Compared shape and size in mm: %s of %s parts matched, %s missing, %s extra; reflections allowed' % (len(pairs),count,missing,extra))
    mate,n=joint_coverage(reference,data,pairs)
    out['pantograph joints mated']=(mate,'Checked %s required connections between matched parts' % n)
    movement=motion_score(data)
    hanging=working_layout(reference,data,pairs)
    out['mechanism articulates']=(movement,
        'Checked %s positions: movement %.3f; hanging arrangement %.3f is diagnostic only' %
        (len(data['motion']['probes']),movement,hanging))
    coverage,drive,n=parameter_scores(reference,data,pairs)
    out['carries dimensional constraints']=(coverage,'Found upstream editable dimensions on %s modeled part roles' % n)
    out['dimensions drive the geometry']=(drive,'Changed dimensions on %s part roles and checked the resulting shapes' % n)
    signature,dimension_rows=signature_dimensions(reference,data,pairs)
    out['signature dimensions present']=(signature,
        'Measured short-link length 150, hole spacing 120, width 30 and thickness 10 mm on %s instances' % len(dimension_rows))
    state['diagnostics']={'freecad_version':data.get('version'),
                          'launcher':data.get('launcher'),
                          'assembly_completeness':completeness,
                          'matched_part_shape_score':average(scores),
                          'hanging_arrangement':hanging,
                          'signature_dimensions':dimension_rows}
    return {name:(clamp(score),description) for name,(score,description) in out.items()}


def finalize(results):
    gated=any(results[name][0]<1 for name in MUST_PASS)
    raw=0.0 if gated else sum(ALL_CRITERIA[name]*results[name][0] for name in ALL_CRITERIA)
    return {'score':round(raw,4),'max_score':MAX_SCORE,'passed':raw>=MAX_SCORE,
            'subscores':{name:{'score':round(clamp(score),6),'weight':ALL_CRITERIA[name],'description':description}
                         for name,(score,description) in results.items()}}


def main(argv=None):
    global DIAGNOSTICS_OUT, FREECAD_MODE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',nargs='?',type=Path)
    parser.add_argument('--corpus',action='store_true',help='Measure the reference once, then grade every example')
    parser.add_argument('--measurement-out',type=Path,help='Keep the measured facts for inspection')
    parser.add_argument('--diagnostics-out',type=Path,help='Keep FreeCAD logs and last measurement stage, including crashes')
    parser.add_argument('--doctor',action='store_true',help='Check FreeCAD startup and API without loading a CAD assembly')
    parser.add_argument('--freecad-mode',choices=('auto','cli','embedded-python'),default='auto',help='Windows auto can bypass a failed console launcher using FreeCAD bundled Python')
    parser.add_argument('--report-out',type=Path,help='Save the JSON result as UTF-8')
    args=parser.parse_args(argv)
    if not args.doctor and not args.corpus and args.candidate is None:
        parser.error('provide a candidate FCStd path, --corpus or --doctor')
    DIAGNOSTICS_OUT = args.diagnostics_out
    FREECAD_MODE = args.freecad_mode
    def emit(value):
        payload=json.dumps(value,indent=2,allow_nan=False)
        if args.report_out:
            args.report_out.parent.mkdir(parents=True,exist_ok=True)
            args.report_out.write_text(payload+'\n',encoding='utf-8')
        print(payload)
    try:
        if args.doctor:
            data,error=run_script(HERE/'doctor_stage.py',timeout=45)
            if error:
                raise InfrastructureError(error)
            emit(dict(status='ok',**data))
            return 0
        started=time.monotonic()
        print('Measuring frozen reference...',file=sys.stderr,flush=True)
        reference=load_reference()
        if args.corpus:
            paths=[TASK/'solution'/'solution.FCStd']+sorted((TASK/'examples').glob('*/*.FCStd'))
            report=[]
            for index,path in enumerate(paths,1):
                print('Measuring %s (%s/%s)...' % (path.parent.name,index,len(paths)),file=sys.stderr,flush=True)
                state=build_state(path,reference)
                result=finalize(checks(state))
                print('Score: %s / %s' % (result['score'],MAX_SCORE),file=sys.stderr,flush=True)
                report.append(dict(candidate=str(path),diagnostics=state.get('diagnostics',{}),**result))
            emit(report)
        else:
            state=build_state(args.candidate,reference, TIMEOUT_S-(time.monotonic()-started))
            result=finalize(checks(state))
            result['diagnostics']=state.get('diagnostics',{})
            if args.measurement_out:
                args.measurement_out.parent.mkdir(parents=True,exist_ok=True)
                args.measurement_out.write_text(json.dumps(state,indent=2,allow_nan=False),encoding='utf-8')
            emit(result)
        return 0
    except InfrastructureError as exc:
        emit({'status':'error','error':str(exc),'score':0,'max_score':MAX_SCORE,'passed':False})
        return 2


if __name__=='__main__':
    sys.exit(main())
