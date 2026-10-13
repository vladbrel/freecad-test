"""Scoring regressions; run with Python, without FreeCAD."""
import copy
import math
import unittest
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import harness as h


def shape():
    # A rectangular solid with distinct principal moments.
    points=[]
    for axis in range(3):
        others=[i for i in range(3) if i!=axis]
        for sign in (-1,1):
            for u in np.linspace(-1,1,12):
                for v in np.linspace(-1,1,12):
                    p=[0.,0.,0.];p[axis]=sign*(axis+1)
                    p[others[0]]=u*(others[0]+1);p[others[1]]=v*(others[1]+1)
                    points.append(p)
    return {'volume':48.,'area':88.,'inertia':[[208.,0,0],[0,160.,0],[0,0,80.]],
            'points':points,'cylinders':[],'centre':[0,0,0]}


def measurement(parts=2):
    data={'build':{'valid':True,'errors':[]},'parts':[], 'shapes':{},'parameters':{},'joints':[],
          'motion':{'supported':True,'probes':[{'ok':True,'gap':0,'axis_error':0,'relative_motion':2,'limit_score':1}]}}
    for i in range(parts):
        name='source_%s' % i
        data['parts'].append({'id':'part_%s' % i,'source':name,'centre':[i*20.,0,0],'volume':48,'valid':True})
        data['shapes'][name]=shape()
        data['parameters'][name]={'controls':[{'type':'Distance'}], 'probes':[{'ok':True,'change':.02}]}
    if parts>=2:
        data['joints']=[{'id':'hinge','members':[['part_0'],['part_1']],'type':'Revolute','valid':True,
                         'suppressed':False,'gap':0,'axis_error':0,'rotation_error':0}]
    return data


class Scores(unittest.TestCase):
    def grade(self,reference,candidate):
        with patch.object(h,'signature_dimensions',return_value=(1.0,[])):
            return h.finalize(h.checks({'reference':reference,'measurement':candidate,'error':None}))

    def test_reference_is_exactly_six(self):
        data=measurement(); result=self.grade(data,data)
        self.assertEqual(result['score'],6)
        self.assertTrue(result['passed'])

    def test_shape_rotation_and_reflection_are_allowed(self):
        original=shape(); moved=copy.deepcopy(original)
        angle=.61
        rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,-1]])
        moved['points']=(np.asarray(original['points'])@rotation).tolist()
        moved['inertia']=(rotation.T@np.asarray(original['inertia'])@rotation).tolist()
        self.assertEqual(h.geometry_score(original,moved),1)

    def test_hanging_layout_accepts_mirror_but_rejects_inverted_mechanism(self):
        reference=measurement(3)
        ring=reference['shapes']['source_0']
        transform=np.diag([8.,15.,12.])
        ring['points']=(np.asarray(ring['points'])@transform).tolist()
        reference['parts'][0]['volume']=10000
        reference['parts'][0]['centre']=[0,0,60]
        reference['parts'][1]['centre']=[0,0,0]
        reference['parts'][2]['centre']=[0,0,-100]
        reference['joints'].append(dict(reference['joints'][0],members=[['part_1'],['part_2']]))
        pairs=[(0,0),(1,1),(2,2)]
        candidate=copy.deepcopy(reference)
        for part in candidate['parts']:
            part['centre']=(-np.asarray(part['centre'])+np.array([17,20,9])).tolist()
        self.assertEqual(h.working_layout(reference,candidate,pairs),1)
        candidate=copy.deepcopy(reference)
        candidate['parts'][2]['centre']=[0,0,100]
        self.assertEqual(h.working_layout(reference,candidate,pairs),0)

    def test_scale_is_not_normalized_away(self):
        original=shape(); enlarged=copy.deepcopy(original)
        enlarged['points']=(np.asarray(original['points'])*2).tolist()
        enlarged['volume']*=8;enlarged['area']*=4
        enlarged['inertia']=(np.asarray(original['inertia'])*32).tolist()
        self.assertLess(h.geometry_score(original,enlarged),.1)

    def test_missing_part_only_affects_completeness(self):
        reference=measurement();candidate=measurement(1)
        # No remaining expected edge can be judged when its other part is missing.
        result=self.grade(reference,candidate)
        self.assertEqual(result['subscores']['geometry matches ground truth']['score'],.5)
        self.assertEqual(result['subscores']['dimensions drive the geometry']['score'],1)

    def test_dummy_joint_does_not_replace_required_connection(self):
        reference=measurement();candidate=copy.deepcopy(reference)
        candidate['joints'][0]['members']=[['part_0'],['part_0']]
        candidate['joints'][0]['valid']=False
        self.assertEqual(h.joint_coverage(reference,candidate,[(0,0),(1,1)])[0],0)

    def test_decorative_dimensions_do_not_receive_driving_credit(self):
        reference=measurement();candidate=copy.deepcopy(reference)
        for item in candidate['parameters'].values():
            item['probes'][0]['change']=0
        result=self.grade(reference,candidate)
        self.assertEqual(result['subscores']['carries dimensional constraints']['score'],1)
        self.assertEqual(result['subscores']['dimensions drive the geometry']['score'],0)

    def test_bad_limits_do_not_change_geometry_credit(self):
        reference=measurement();candidate=copy.deepcopy(reference)
        candidate['motion']['probes'][0]['limit_score']=0
        result=self.grade(reference,candidate)
        self.assertEqual(result['subscores']['geometry matches ground truth']['score'],1)
        self.assertEqual(result['subscores']['mechanism articulates']['score'],0)

    def test_failed_build_emits_all_scores(self):
        reference=measurement();candidate=copy.deepcopy(reference);candidate['build']['valid']=False
        result=self.grade(reference,candidate)
        self.assertEqual(result['score'],0)
        self.assertEqual(set(result['subscores']),set(h.ALL_CRITERIA))

    def test_joint_gap_is_continuous(self):
        joint=measurement()['joints'][0]
        joint['gap']=1
        one=h.joint_quality(joint)
        joint['gap']=2
        two=h.joint_quality(joint)
        self.assertGreater(one,two)
        self.assertGreater(two,0)

    def test_unavailable_motion_is_an_infrastructure_error(self):
        data=measurement();data['motion']['supported']=False
        with self.assertRaises(h.InfrastructureError):h.motion_score(data)

    def test_hanging_pose_is_diagnostic_only(self):
        reference=measurement()
        with patch.object(h, 'working_layout', return_value=0):
            result=self.grade(reference, reference)
        self.assertEqual(result['score'],6)

    def test_env_file_quotes_bom_comment_and_relative_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            binary=root/'FreeCAD folder'/'FreeCADCmd.exe'
            binary.parent.mkdir();binary.touch()
            env_file=root/'.env'
            env_file.write_text('export FREECAD_CMD="FreeCAD folder/FreeCADCmd.exe" # local\n',encoding='utf-8-sig')
            with patch.dict(os.environ,{},clear=True),patch.object(h,'ENV_FILES',(env_file,)):
                self.assertEqual(Path(h.load_freecad_command()),binary)

    def test_explicit_environment_has_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            binary=Path(folder)/'FreeCADCmd.exe';binary.touch()
            env_file=Path(folder)/'.env';env_file.write_text('FREECAD_CMD=missing.exe')
            with patch.dict(os.environ,{'FREECAD_CMD':str(binary)},clear=True),patch.object(h,'ENV_FILES',(env_file,)):
                self.assertEqual(h.load_freecad_command(),str(binary))

    def test_invalid_executable_is_setup_error(self):
        with patch.dict(os.environ,{'FREECAD_CMD':'nonexistent-freecad-123.exe'},clear=True):
            with self.assertRaises(h.InfrastructureError):h.load_freecad_command()

    def test_native_crash_reports_stage_and_keeps_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate=Path(folder)/'candidate.FCStd';candidate.touch()
            def crash(args,**kwargs):
                out=Path(kwargs['env']['FC_STAGE_OUT'])
                (out/'progress.json').write_text('{"stage":"recompute","version":["1","1","4"]}')
                self.assertNotIn('PYTHONPATH',kwargs['env'])
                return subprocess.CompletedProcess(args,1,'','Application unexpectedly terminated')
            with patch.object(h,'load_freecad_command',return_value='freecadcmd'),patch.object(h.subprocess,'run',side_effect=crash),patch.object(h,'DIAGNOSTICS_OUT',Path(folder)/'logs'):
                with self.assertRaisesRegex(h.InfrastructureError,'recompute'):
                    h.run_stage(candidate)
            self.assertEqual(len(list((Path(folder)/'logs').glob('*/progress.json'))),1)

    def test_timeout_is_setup_error_and_keeps_partial_log(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate=Path(folder)/'candidate.FCStd';candidate.touch()
            def timeout(args,**kwargs):
                (Path(kwargs['env']['FC_STAGE_OUT'])/'progress.json').write_text('{"stage":"motion check"}')
                raise subprocess.TimeoutExpired(args,1,output=b'partial solver log')
            with patch.object(h,'load_freecad_command',return_value='freecadcmd'),patch.object(h.subprocess,'run',side_effect=timeout),patch.object(h,'DIAGNOSTICS_OUT',Path(folder)/'logs'):
                with self.assertRaisesRegex(h.InfrastructureError,'motion check'):
                    h.run_stage(candidate)
            log=next((Path(folder)/'logs').glob('*/stdout.log'))
            self.assertIn('partial solver log',log.read_text())

    def signature_model(self):
        data=measurement(1)
        item=data['shapes']['source_0']
        item['points']=(np.asarray(item['points'])@np.diag([75.,7.5,5./3.])).tolist()
        item['cylinders']=[{'axis':[0,0,1],'centre':[-60,0,0],'radius':6,'internal':True},
                           {'axis':[0,0,1],'centre':[60,0,0],'radius':8,'internal':True}]
        return data

    def test_original_criteria_and_integer_weights(self):
        self.assertEqual(set(h.ALL_CRITERIA),{
            'executes and builds geometry','geometry matches ground truth',
            'pantograph joints mated','mechanism articulates',
            'carries dimensional constraints','dimensions drive the geometry',
            'signature dimensions present'})
        self.assertEqual(h.MAX_SCORE,6)
        self.assertTrue(all(type(v) is int for v in h.ALL_CRITERIA.values()))

    def test_signature_dimensions_are_geometric_and_allow_reflection(self):
        reference=self.signature_model();candidate=copy.deepcopy(reference)
        rotation=np.array([[0,1,0],[1,0,0],[0,0,1.]])
        item=candidate['shapes']['source_0']
        item['points']=(np.asarray(item['points'])@rotation).tolist()
        for cylinder in item['cylinders']:
            cylinder['axis']=(np.asarray(cylinder['axis'])@rotation).tolist()
            cylinder['centre']=(np.asarray(cylinder['centre'])@rotation+[10,20,30]).tolist()
        self.assertEqual(h.signature_dimensions(reference,candidate,[(0,0)])[0],1)

    def test_wrong_hole_spacing_only_reduces_that_signature(self):
        reference=self.signature_model();candidate=copy.deepcopy(reference)
        for cylinder in candidate['shapes']['source_0']['cylinders']:
            cylinder['centre'][0]*=.9
        score,rows=h.signature_dimensions(reference,candidate,[(0,0)])
        self.assertGreater(score,0);self.assertLess(score,1)
        self.assertLess(rows[0]['scores']['hole_spacing'],1)
        self.assertEqual(rows[0]['scores']['length'],1)
        self.assertEqual(rows[0]['scores']['width'],1)
        self.assertEqual(rows[0]['scores']['thickness'],1)

    def test_outer_caps_do_not_replace_missing_holes(self):
        reference=self.signature_model();candidate=copy.deepcopy(reference)
        for cylinder in candidate['shapes']['source_0']['cylinders']:
            cylinder['internal']=False
        score,rows=h.signature_dimensions(reference,candidate,[(0,0)])
        self.assertEqual(rows[0]['scores']['hole_spacing'],0)
        self.assertEqual(rows[0]['scores']['length'],1)
        self.assertEqual(score,.75)


if __name__=='__main__':
    unittest.main()
