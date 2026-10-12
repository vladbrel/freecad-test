"""Read a lift in FreeCAD's Python; write plain facts, never a final grade.

FC_STAGE_INPUT and FC_STAGE_OUT are supplied by harness.py. No pip packages
are needed here. All edits for motion/parameter tests stay in memory.
"""
import bisect
import json
import math
import os
import re
import traceback

import FreeCAD as App
import Part

SCHEMA_VERSION = 2
SAMPLE_COUNT = 384


def vector(v):
    return [float(v.x), float(v.y), float(v.z)]


def scalar(value):
    return float(getattr(value, 'Value', value))


def is_assembly(obj):
    return obj.TypeId in ('Assembly::AssemblyObject', 'Assembly::AssemblyLink')


def is_joint(obj):
    return hasattr(obj, 'JointType') or obj.TypeId == 'Assembly::JointObject'


def source_of(obj):
    return obj.getLinkedObject(True) if hasattr(obj, 'LinkedObject') else obj


def shape_of(obj):
    # Part.getShape understands links and parts containing several bodies.
    return Part.getShape(obj)


def dependencies(obj):
    seen = set()
    todo = [obj]
    while todo:
        item = todo.pop()
        key = (item.Document.Name, item.Name)
        if key in seen:
            continue
        seen.add(key)
        yield item
        if item.TypeId == 'PartDesign::Body':
            if item.Tip is not None:
                todo.append(item.Tip)
        else:
            todo.extend(item.OutList)


def mass_properties(shape):
    solids=shape.Solids
    volume=sum(abs(s.Volume) for s in solids)
    centre=App.Vector()
    for solid in solids:
        centre += solid.CenterOfMass * abs(solid.Volume)
    centre /= max(volume,1e-12)
    matrix=[[0.0]*3 for _ in range(3)]
    for solid in solids:
        inertia=solid.MatrixOfInertia
        delta=vector(solid.CenterOfMass-centre)
        norm=sum(v*v for v in delta)
        for i in range(3):
            for j in range(3):
                matrix[i][j] += getattr(inertia,'A%d%d' % (i+1,j+1)) + abs(solid.Volume)*((norm if i==j else 0)-delta[i]*delta[j])
    return volume,centre,matrix


def shape_facts(shape, samples=False):
    volume, centre, inertia = mass_properties(shape)
    out = {'volume': volume, 'area': float(shape.Area),
           'centre': vector(centre),
           'inertia': inertia, 'cylinders': []}
    for face in shape.Faces:
        surface = face.Surface
        if isinstance(surface, Part.Cylinder):
            out['cylinders'].append({'radius': float(surface.Radius),
                                     'area': float(face.Area),
                                     'axis': vector(surface.Axis),
                                     'centre': vector(surface.Center)})
    if samples:
        # Sample by triangle AREA, not by face/vertex count. A finer mesh must
        # not get extra weight. The fixed sequence makes repeated runs identical.
        verts, triangles = shape.tessellate(0.15)
        cumulative = []
        total = 0.0
        good = []
        for a, b, c in triangles:
            area = (verts[b] - verts[a]).cross(verts[c] - verts[a]).Length / 2.0
            if area > 1e-12:
                total += area
                good.append((a, b, c))
                cumulative.append(total)
        points = []
        for i in range(SAMPLE_COUNT):
            idx = min(bisect.bisect_left(cumulative, total * (i + 0.5) / SAMPLE_COUNT), len(good)-1)
            a, b, c = good[idx]
            u = math.sqrt(((i + 1) * 0.6180339887498949) % 1)
            v = ((i + 1) * 0.4142135623730951) % 1
            p = verts[a] * (1-u) + verts[b] * (u*(1-v)) + verts[c] * (u*v)
            points.append(vector(p - centre))
        out['points'] = points
    return out


def collect(doc):
    """Walk installed instances only; omit their unused source definitions."""
    assemblies = [obj for obj in doc.Objects if obj.TypeId == 'Assembly::AssemblyObject']
    linked_targets = {source_of(o).Name for o in doc.Objects if hasattr(o, 'LinkedObject')}
    roots = [a for a in assemblies if a.Name not in linked_targets
             and not any(is_assembly(parent) for parent in a.InList)]
    if not roots and assemblies:
        raise RuntimeError('Cannot identify a top-level assembly unambiguously')
    if not assemblies:
        roots = [o for o in doc.Objects if (o.TypeId in ('PartDesign::Body', 'App::Part') or o.isDerivedFrom('Part::Feature'))
                 and o.Name not in linked_targets
                 and not any(p.TypeId in ('App::Part', 'PartDesign::Body') for p in o.InList)]
    instances = []
    contexts = []
    seen = set()

    def walk(obj, prefix='', parent=None, transform=None):
        transform = transform or App.Placement()
        key = prefix + obj.Name
        if key in seen:
            return
        seen.add(key)
        if is_joint(obj) or obj.TypeId in ('Assembly::JointGroup', 'App::Origin'):
            return
        if is_assembly(obj):
            contexts.append((obj, key + '.', parent or App.Placement()))
            for child in obj.Group:
                walk(child, key + '.', obj, transform * obj.Placement)
            return
        if obj.TypeId == 'App::DocumentObjectGroup':
            for child in obj.Group:
                walk(child, key + '.', parent, transform)
            return
        try:
            shape = shape_of(obj)
        except (AttributeError, RuntimeError, TypeError):
            return
        if shape.isNull() or not shape.Solids:
            return
        source = source_of(obj)
        instances.append({'id': key, 'object': obj, 'source': source,
                          'parent': parent, 'transform': transform, 'shape': shape})

    for root in roots:
        walk(root)
    return instances, contexts


def reference_object(ref):
    if not ref or not ref[0]:
        return None
    return ref[0]


def global_connector(joint, side):
    import UtilsAssembly
    ref = getattr(joint, 'Reference%d' % side)
    return UtilsAssembly.getJcsGlobalPlc(getattr(joint, 'Placement%d' % side), ref)


def joint_facts(joint, context, instances):
    assembly, prefix, parent = context
    refs = [getattr(joint, 'Reference%d' % side, None) for side in (1, 2)]
    owners = [reference_object(ref) for ref in refs]
    ids = []
    for owner in owners:
        choices = [i['id'] for i in instances if owner is not None and i['object'] == owner]
        if not choices and owner is not None:
            # A top-level joint can reference an entire nested assembly. Keep
            # its membership: scoring resolves the fixed groups below it.
            choices = [i['id'] for i in instances if i['id'].startswith(prefix + owner.Name + '.')]
        ids.append(choices)
    anchored = any(owner is not None and owner.TypeId in ('App::Origin','App::Plane','App::Line','App::Point') for owner in owners)
    out = {'id': prefix + joint.Name, 'type': str(joint.JointType),
           'members': ids, 'grounded': anchored, 'suppressed': bool(getattr(joint, 'Suppressed', False)),
           'valid': False, 'error': None, 'gap': None, 'axis_error': None,
           'rotation_error': None, 'coordinate': None, 'limits': {}}
    for kind in ('Length', 'Angle'):
        for end in ('Min', 'Max'):
            prop = kind + end
            if bool(getattr(joint, 'Enable' + prop, False)):
                out['limits'][prop] = scalar(getattr(joint, prop))
    try:
        if not all(owners) or owners[0] == owners[1]:
            raise ValueError('Joint does not join two different installed objects')
        # Resolve the referenced geometry, not just the containing object.
        for owner, ref in zip(owners, refs):
            for sub in ref[1]:
                if sub and owner.getSubObject(sub, 1 if sub.endswith(".") else 0) is None:
                    raise ValueError('Missing geometry referenced by a joint')
        a, b = global_connector(joint, 1), global_connector(joint, 2)
        za = a.Rotation.multVec(App.Vector(0, 0, 1))
        zb = b.Rotation.multVec(App.Vector(0, 0, 1))
        delta = b.Base - a.Base
        along = delta.dot(za)
        perpendicular = (delta - za * along).Length
        axis = math.degrees(math.acos(max(-1.0, min(1.0, abs(za.dot(zb))))))
        xa = a.Rotation.multVec(App.Vector(1, 0, 0))
        xb = b.Rotation.multVec(App.Vector(1, 0, 0))
        angle = math.degrees(math.acos(max(-1.0,min(1.0,abs(xa.dot(xb))))))
        jt = str(joint.JointType)
        gap = perpendicular if jt in ('Slider', 'Cylindrical') else delta.Length
        if jt in ('Parallel', 'Perpendicular', 'Angle'):
            gap = 0.0
        if jt == 'Perpendicular':
            axis = abs(90.0-axis)
        elif jt in ('Ball', 'Distance'):
            axis = 0.0
        if jt == 'Distance':
            gap = abs(delta.Length-abs(scalar(joint.Distance)))
        xa = a.Rotation.multVec(App.Vector(1, 0, 0))
        xb = b.Rotation.multVec(App.Vector(1, 0, 0))
        signed_angle = math.degrees(math.atan2(za.dot(xa.cross(xb)), xa.dot(xb)))
        out.update(valid=bool((ids[0] and ids[1]) or (anchored and (ids[0] or ids[1]))), gap=gap, axis_error=axis,
                   rotation_error=angle if jt in ('Fixed', 'Slider') else 0.0,
                   coordinate=along if jt in ('Slider', 'Cylindrical') else signed_angle,
                   connector_points=[vector(a.Base), vector(b.Base)])
    except Exception as exc:
        out['error'] = '%s: %s' % (type(exc).__name__, exc)
    return out


def active_joints(contexts):
    seen = set()
    for context in contexts:
        assembly = context[0]
        joints = [obj for obj in assembly.Group if is_joint(obj)]
        for group in assembly.Group:
            if group.TypeId == 'Assembly::JointGroup':
                joints.extend(obj for obj in group.Group if is_joint(obj))
        for joint in joints:
            key = context[1] + joint.Name
            if key not in seen:
                seen.add(key)
                yield joint, context


def dimension_controls(source):
    """Find upstream editable dimensions, including expression input cells."""
    controls=[]
    objects=list(dependencies(source))
    expressions=[str(expr) for obj in objects for prop,expr in getattr(obj,'ExpressionEngine',[])]
    for obj in objects:
        if obj.TypeId=='Sketcher::SketchObject':
            driven={prop for prop,expr in obj.ExpressionEngine}
            for idx,constraint in enumerate(obj.Constraints):
                if constraint.Type not in ('Distance','DistanceX','DistanceY','Radius','Diameter','Angle') or not obj.getDriving(idx):
                    continue
                value=math.degrees(constraint.Value) if constraint.Type=='Angle' else float(constraint.Value)
                if abs(value)>1e-6 and 'Constraints[%s]' % idx not in driven:
                    controls.append({'object':obj.Name,'kind':'constraint','index':idx,
                                     'type':constraint.Type,'value':value})
        driven={prop for prop,expr in getattr(obj,'ExpressionEngine',[])}
        for name in obj.PropertiesList:
            if name in driven or obj.TypeId.startswith(('App::Origin','Assembly::')) or is_joint(obj):
                continue
            typ=obj.getTypeIdOfProperty(name)
            standard=name in ('Length','Length2','Radius','Radius1','Radius2','Height','Width','Angle','Pitch','Size')
            referenced=any(re.search(r'\b'+re.escape(obj.Name)+r'\.'+re.escape(name)+r'\b',expr) for expr in expressions)
            if typ not in ('App::PropertyLength','App::PropertyAngle','App::PropertyDistance','App::PropertyQuantityConstraint','App::PropertyLengthConstraint','App::PropertyAngleConstraint','App::PropertyFloat','App::PropertyFloatConstraint') or not (standard or referenced):
                continue
            if name == 'Length2' and str(getattr(obj,'Type','')) not in ('TwoLengths','Two lengths'):
                continue
            if name == 'Angle' and hasattr(obj,'ChamferType') and str(obj.ChamferType) != 'Distance and angle':
                continue
            value=scalar(getattr(obj,name))
            if abs(value)>1e-6:
                controls.append({'object':obj.Name,'kind':'property','property':name,
                                 'type':'Angle' if 'Angle' in typ else 'Distance','value':value})
        if obj.TypeId=='Spreadsheet::Sheet':
            wanted=set()
            for expr in expressions:
                wanted.update(re.findall(r'\b'+re.escape(obj.Name)+r'\.([A-Za-z][A-Za-z0-9_]*)',expr))
                wanted.update(re.findall(r'<<'+re.escape(obj.Label)+r'>>\.([A-Za-z][A-Za-z0-9_]*)',expr))
            seen=set()
            def cell_inputs(cell):
                if not re.fullmatch(r'[A-Z]+[1-9][0-9]*',cell):
                    cell=obj.getCellFromAlias(cell)
                if not cell or cell in seen:
                    return
                seen.add(cell)
                contents=obj.getContents(cell).strip()
                if contents.startswith('='):
                    for dependency in re.findall(r'\b[A-Z]+[1-9][0-9]*\b',contents):
                        cell_inputs(dependency)
                    return
                match=re.fullmatch(r'([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*(.*)',contents)
                if match and abs(float(match.group(1)))>1e-6:
                    controls.append({'object':obj.Name,'kind':'cell','cell':cell,
                                     'type':'Distance','value':float(match.group(1)),
                                     'unit':match.group(2),'contents':contents})
            for cell in sorted(wanted):
                cell_inputs(cell)
    return controls


def set_control(doc, control, value):
    obj = doc.getObject(control['object'])
    if control['kind'] == 'cell':
        obj.set(control['cell'], control['contents'] if value == control['value'] else '%s %s' % (value, control['unit']))
    elif control['kind'] == 'constraint':
        unit = 'deg' if control['type'] == 'Angle' else 'mm'
        obj.setDatum(control['index'], App.Units.Quantity('%s %s' % (value, unit)))
    else:
        setattr(obj, control['property'], value)


def simple_signature(shape):
    # These moments are independent of rigid motion and catch moved holes.
    volume,centre,a=mass_properties(shape)
    trace=sum(a[i][i] for i in range(3))
    squared=sum(a[i][j]*a[j][i] for i in range(3) for j in range(3))
    determinant=(a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
                 -a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
                 +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))
    return [volume,float(shape.Area),trace,squared,determinant]


def changed(before, after):
    return max(abs(a-b)/max(abs(a), abs(b), 1.0) for a,b in zip(before,after))


def parameter_facts(doc, sources):
    result = {}
    placements = {o.Name:App.Placement(o.Placement) for o in doc.Objects if hasattr(o,'Placement')}
    for name, source in sources.items():
        controls = dimension_controls(source)
        expressions = []
        for obj in dependencies(source):
            expressions.extend({'object': obj.Name, 'property': prop, 'expression': str(expr)}
                               for prop,expr in getattr(obj, 'ExpressionEngine', []))
        row = {'controls': controls, 'expressions': expressions, 'probes': []}
        result[name] = row
        if not controls:
            continue
        baseline = simple_signature(shape_of(source))
        # Test independent sources, not every repeated link or every tiny fillet.
        selected = sorted(controls, key=lambda c: (c['type']=='Angle', -abs(c['value']), c['object'], str(c.get('index', c.get('property',c.get('cell'))))))
        selected = selected[:3]
        for control in selected:
            probe = {'control': control, 'ok': False, 'change': 0.0, 'error': None}
            doc.openTransaction('Temporary dimension check')
            try:
                value = control['value']
                set_control(doc, control, value * 1.02)
                doc.recompute()
                shape = shape_of(source)
                if shape.isNull() or not shape.isValid() or any('Invalid' in o.State for o in dependencies(source)):
                    raise ValueError('Changing this dimension produced an invalid shape')
                probe['change'] = changed(baseline, simple_signature(shape))
                probe['ok'] = True
            except Exception as exc:
                probe['error'] = '%s: %s' % (type(exc).__name__, exc)
            finally:
                doc.abortTransaction()
                set_control(doc, control, control['value'])
                for obj_name,placement in placements.items():
                    doc.getObject(obj_name).Placement=App.Placement(placement)
                doc.recompute()
            if changed(baseline, simple_signature(shape_of(source))) > 1e-5:
                raise RuntimeError('Could not restore %s after %s; difference=%s' % (name, control, changed(baseline, simple_signature(shape_of(source)))))
            row['probes'].append(probe)
            # One successful edit proves this part responds. Try the next
            # dimension only if the first does not affect the final solid.
            if probe['ok'] and probe['change'] >= 0.0001:
                break
    return result


def limit_quality(facts):
    q = facts['coordinate']
    if q is None:
        return 0.0
    limits = facts['limits']
    kind = 'Length' if facts['type'] in ('Slider', 'Cylindrical') else 'Angle'
    low = limits.get(kind+'Min')
    high = limits.get(kind+'Max')
    if low is not None and high is not None and low > high:
        return 0.0
    if kind == 'Angle' and (low is not None or high is not None):
        def overflow(value):
            return max(0.0, low-value if low is not None else 0.0, value-high if high is not None else 0.0)
        q = min((q+360*k for k in range(-3,4)), key=overflow)
    excess = max(0.0, (low-q) if low is not None else 0.0,
                 (q-high) if high is not None else 0.0)
    return max(0.0, 1.0-max(0.0, excess-0.05)/10.0)


def motion_facts(doc, instances, contexts):
    """Ask the solver for nearby positions; then check physical joints again.

    A Slider is temporarily fixed at a chosen position. This adds the input
    coordinate without replacing the remaining joints with a hand animation.
    The document is restored after every trial and is never saved.
    """
    sliders = [(j,c) for j,c in active_joints(contexts)
               if str(j.JointType)=='Slider' and not getattr(j,'Suppressed',False)]
    movable = [(j,c) for j,c in active_joints(contexts)
               if str(j.JointType) in ('Slider','Revolute') and not getattr(j,'Suppressed',False)]
    if not contexts:
        return {'supported':True, 'error':None, 'probes':[]}
    if not sliders:
        return {'supported':True, 'error':None, 'probes':[],
                'reason':'No supported input slider in the pantograph'}
    joint,context = sliders[0]
    facts = joint_facts(joint,context,instances)
    if not facts['valid']:
        return {'supported':True,'error':None,'probes':[], 'reason':facts['error']}
    root = contexts[0][0]
    if not callable(getattr(root,'solve',None)):
        return {'supported':False,'error':'Native Assembly.solve is not available','probes':[]}
    start = facts['coordinate']
    original = App.Placement(joint.Placement2)
    detach = joint.Detach2
    placements = {o.Name:App.Placement(o.Placement) for o in doc.Objects if hasattr(o,'Placement')}
    before = {j.Name:joint_facts(j,c,instances)['coordinate'] for j,c in movable}
    probes=[]
    deltas = (-12.0,-3.0,3.0,12.0)
    low = facts['limits'].get('LengthMin', float('-inf'))
    high = facts['limits'].get('LengthMax', float('inf'))
    if low <= start <= high:
        left, right = max(start-12.0,low+0.1), min(start+12.0,high-0.1)
        if right-left > 0.1:
            deltas = tuple(left+(right-left)*fraction-start for fraction in (0.1,0.35,0.65,0.9))
    for delta in deltas:
        row={'target':start+delta,'input_fraction':abs(delta)/max(abs(start),100.0),'ok':False,'gap':0.0,'axis_error':0.0,
             'relative_motion':0.0,'limit_score':0.0,'solver_status':None,'error':None}
        doc.openTransaction('Temporary motion check')
        try:
            joint.Detach2=True
            joint.JointType='Fixed'
            # Small steps help the solver keep the same folding branch. One
            # large jump can fail numerically even for a correct mechanism.
            steps=max(1,int(math.ceil(abs(delta))))
            status=0
            for step in range(steps+1):
                target=start+delta*step/steps
                temporary=App.Placement(original)
                temporary.Base -= temporary.Rotation.multVec(App.Vector(0,0,target))
                joint.Placement2=temporary
                status=root.solve()
                if status!=0:
                    break
            row['solver_status']=status
            if status != 0:
                raise ValueError('Assembly solver could not reach the test position')
            # Restore the real joint definition before measuring its physical gap.
            joint.JointType='Slider'
            joint.Placement2=App.Placement(original)
            joint.Detach2=detach
            after=[joint_facts(j,c,instances) for j,c in active_joints(contexts)
                   if not getattr(j,'Suppressed',False)]
            good=[f for f in after if f['valid']]
            if len(good)!=len(after):
                raise ValueError('A joint lost its installed references during movement')
            coordinate=joint_facts(joint,context,instances)['coordinate']
            if abs(coordinate-(start+delta)) > 0.05:
                raise ValueError('Solver did not achieve the requested physical position')
            # At least one Revolute must move: a sliding detached assembly is not a lift.
            rotations=[]
            for j,c in movable:
                now=joint_facts(j,c,instances)['coordinate']
                old=before[j.Name]
                if str(j.JointType)=='Revolute' and now is not None and old is not None:
                    rotations.append(abs((now-old+180)%360-180))
            row.update(ok=True, gap=max((f['gap'] for f in good),default=0.0),
                       axis_error=max((f['axis_error'] for f in good),default=0.0),
                       relative_motion=max(rotations,default=0.0),
                       limit_score=min((limit_quality(f) for f in good),default=0.0))
        except Exception as exc:
            row['error']='%s: %s' % (type(exc).__name__,exc)
        finally:
            doc.abortTransaction()
            # Native solver placements are not all covered by document undo.
            for name,placement in placements.items():
                doc.getObject(name).Placement=App.Placement(placement)
            joint.JointType='Slider'
            joint.Placement2=App.Placement(original)
            joint.Detach2=detach
            doc.recompute()
        probes.append(row)
    return {'supported':True,'error':None,'input_joint':context[1]+joint.Name,'probes':probes}


def measure(doc):
    doc.UndoMode = 1
    doc.recompute(None, True)
    instances, contexts = collect(doc)
    sources = {i['source'].Name: i['source'] for i in instances}
    relevant = {o.Name for s in sources.values() for o in dependencies(s)}
    errors = [{'object': o.Name, 'state': list(o.State)} for o in doc.Objects
              if o.Name in relevant and any(s in o.State for s in ('Invalid', 'Error'))]
    shapes = {}
    validity = {}
    parts = []
    for instance in instances:
        obj=instance['object']
        shape=instance['shape']
        # Measure the installed shape, including App::Link scale. Its source
        # alone would silently accept an enlarged link to an unchanged part.
        scale=scalar(getattr(obj,'Scale',1.0))
        scale_vector=vector(getattr(obj,'ScaleVector',App.Vector(1,1,1)))
        key=instance['source'].Name+'|'+json.dumps([scale,scale_vector])
        if key not in shapes:
            shapes[key]=shape_facts(shape,samples=True)
            validity[key]=bool(shape.isValid())
        volume,centre,inertia=mass_properties(shape)
        world_centre=instance['transform'].multVec(centre)
        parts.append({'id':instance['id'],'source':instance['source'].Name,'shape':key,
                      'centre':vector(world_centre),'volume':volume,
                      'valid':validity[key] and volume>1e-9})
    joints = [joint_facts(j,ctx,instances) for j,ctx in active_joints(contexts)]
    return {'schema_version': SCHEMA_VERSION, 'version': App.Version(),
            'build': {'valid': bool(parts) and not errors and all(p['valid'] for p in parts),
                      'errors': errors}, 'parts': parts, 'shapes': shapes, 'joints': joints,
            'parameters': parameter_facts(doc, sources),
            'motion': motion_facts(doc, instances, contexts)}


def run():
    out_dir = os.environ['FC_STAGE_OUT']
    os.makedirs(out_dir, exist_ok=True)
    doc = None
    preferences = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Assembly')
    automatic = preferences.GetBool('SolveInJointCreation', True)
    preferences.SetBool('SolveInJointCreation', False)
    recompute_solve = preferences.GetBool('SolveOnRecompute', True)
    preferences.SetBool('SolveOnRecompute', False)
    try:
        doc = App.openDocument(os.environ['FC_STAGE_INPUT'])
        result = dict(measure(doc), ok=True)
    except Exception:
        result = {'ok': False, 'error': traceback.format_exc(limit=8)}
    finally:
        preferences.SetBool('SolveInJointCreation', automatic)
        preferences.SetBool('SolveOnRecompute', recompute_solve)
        if doc is not None:
            App.closeDocument(doc.Name)
    with open(os.path.join(out_dir, 'measure.json'), 'w', encoding='utf-8') as handle:
        json.dump(result, handle, allow_nan=False)


if os.environ.get('FC_STAGE_INPUT') and os.environ.get('FC_STAGE_OUT'):
    run()
