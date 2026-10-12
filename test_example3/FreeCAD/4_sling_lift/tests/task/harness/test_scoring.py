"""Scoring regressions; run with Python, without FreeCAD."""
import copy
import math
import unittest

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
        self.assertEqual(result['subscores']['assembly completeness']['score'],.5)
        self.assertEqual(result['subscores']['geometry and dimensions']['score'],1)
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
        self.assertEqual(result['subscores']['dimensional control coverage']['score'],1)
        self.assertEqual(result['subscores']['dimensions drive the geometry']['score'],0)

    def test_bad_limits_do_not_change_geometry_credit(self):
        reference=measurement();candidate=copy.deepcopy(reference)
        candidate['motion']['probes'][0]['limit_score']=0
        result=self.grade(reference,candidate)
        self.assertEqual(result['subscores']['geometry and dimensions']['score'],1)
        self.assertEqual(result['subscores']['mechanism articulates within its limits']['score'],0)

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


if __name__=='__main__':
    unittest.main()
