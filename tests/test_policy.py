import math
import sys
import unittest
from itertools import permutations
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from starnet.policy import ObservationBook, validate_plan

class PolicyTests(unittest.TestCase):
    def book(self,n=2):
        b=ObservationBook(n)
        for i in range(1,n+1):
            b.record_scan(i,{'w':0,'persona':'和平','comm_left':3,'neighbors':[j for j in range(1,n+1) if j!=i]})
        return b
    def test_prompt_order_is_learned_for_all_permutations(self):
        for strengths in permutations([-5,10,15]):
            b=self.book()
            for p,gain in enumerate(strengths,1):
                b.record_comm({'node':1,'prompt_id':p},{'status':'success','new_w':b.nodes[1]['w']+gain*(.5**(p-1))})
            phase,c,_=b.candidates(20)
            self.assertEqual(phase,'intervene')
            self.assertEqual(c[0]['prompt_id'],strengths.index(15)+1)
            self.assertTrue(all(a['prompt_id']!=strengths.index(-5)+1 for a in c))
    def test_all_negative_stops_after_calibration(self):
        b=self.book()
        for p in (1,2,3):
            b.record_comm({'node':1,'prompt_id':p},{'status':'success','new_w':b.nodes[1]['w']-1})
        self.assertEqual(b.candidates(20)[1],[])
    def test_comm_left_from_scan_is_respected(self):
        b=ObservationBook(1);b.record_scan(1,{'w':0,'persona':'和平','comm_left':0,'neighbors':[]})
        self.assertFalse(b.valid({'action':'comm','node':1,'prompt_id':1},10))
        self.assertEqual(b.candidates(20)[1],[])
    def test_missing_scan_and_repeated_scan(self):
        b=ObservationBook(2);b.record_scan(1,None)
        self.assertFalse(b.valid({'action':'scan','node':1},10))
        self.assertEqual(b.candidates(10)[1][0]['node'],2)
    def test_invalid_feedback_rejected(self):
        b=self.book()
        for res in [None,{}, {'status':'success','new_w':math.nan},{'status':'success','new_w':True}]:
            with self.assertRaises(ValueError):b.record_comm({'node':1,'prompt_id':1},res)
        self.assertEqual(b.nodes[1]['comm_left'],3)
    def test_invalid_scan_rejected(self):
        for w in [math.inf,'10',True]:
            with self.assertRaises(ValueError):ObservationBook(1).record_scan(1,{'w':w,'comm_left':3,'neighbors':[]})
    def test_failed_limit_feedback_marks_exhausted(self):
        b=self.book()
        with self.assertRaises(ValueError):b.record_comm({'node':1,'prompt_id':1},{'status':'max_comm_reached'})
        self.assertEqual(b.nodes[1]['comm_left'],0)
    def test_budget_and_types(self):
        b=self.book()
        for a in [{'action':'comm','node':True,'prompt_id':1},{'action':'comm','node':1,'prompt_id':True},{'action':'shield','node':1},{'action':'comm','node':3,'prompt_id':1}]:
            self.assertFalse(b.valid(a,10))
        self.assertFalse(b.valid({'action':'comm','node':1,'prompt_id':1},1.99))
    def test_plan_rejects_bad_indices_duplicates_and_budget(self):
        b=self.book();_,c,_=b.candidates(10)
        for choices in [[True],[-1],[999],[0,1],[0,3,0]]:
            with self.assertRaises(ValueError):validate_plan({'choices':choices,'reason':'test'},c,4,b,10)
        with self.assertRaises(ValueError):validate_plan({'choices':[0,3],'reason':'test'},c,4,b,3)
    def test_valid_plan_preserves_llm_choice(self):
        b=self.book();_,c,_=b.candidates(10)
        plan=validate_plan({'choices':[4],'reason':'choose second node and prompt2'},c,1,b,10)
        self.assertEqual((plan[0]['node'],plan[0]['prompt_id']),(2,2))
    def test_empty_plan_is_deliberate_stop(self):
        b=self.book();_,c,_=b.candidates(10)
        self.assertEqual(validate_plan({'choices':[],'reason':'uncertain'},c,1,b,10),[])

if __name__=='__main__':unittest.main()

class StructuralTests(unittest.TestCase):
    def book(self):
        b=ObservationBook(4)
        for n in range(1,5):b.record_scan(n,{'w':-50 if n==1 else 10,'persona':'和平','comm_left':3,'neighbors':[x for x in range(1,5) if x!=n]})
        for p,g in [(1,10),(2,5),(3,-5)]:
            b.record_comm({'node':2,'prompt_id':p},{'status':'success','new_w':b.nodes[2]['w']+g})
        return b
    def test_shield_rebuilds_public_neighbors(self):
        b=self.book();self.assertTrue(b.valid({'action':'shield','node':1},5))
        b.record_shield(1,True)
        self.assertNotIn(1,b.nodes)
        self.assertTrue(all(1 not in x['neighbors'] for x in b.nodes.values()))
        self.assertFalse(b.valid({'action':'shield','node':1},5))
    def test_shield_is_single_action_plan(self):
        b=self.book();_,c,_=b.candidates(20)
        shield=next(i for i,a in enumerate(c) if a['action']=='shield')
        self.assertEqual(validate_plan({'choices':[shield],'reason':'negative hub'},c,4,b,20)[0]['node'],1)
        with self.assertRaises(ValueError):validate_plan({'choices':[shield,0],'reason':'bad stale batch'},c,4,b,20)
    def test_unconfirmed_shield_does_not_mutate_graph(self):
        b=self.book()
        with self.assertRaises(ValueError):b.record_shield(1,False)
        self.assertIn(1,b.nodes)
