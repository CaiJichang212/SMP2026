"""Python 3.9 protocol tests with an explicit framework double, NOT runtime proof."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

class FakePrompt:
    def __init__(self,llm):self.llm=llm
    def send_prompt(self,extra,agent,model):return self.llm.send_message(extra['state'])
class FakeModelBase:
    def __init__(self,graph,llm,**kwargs):
        self.llm=llm;self.schedule=types.SimpleNamespace(time=0)
        self.prompt_factory=types.SimpleNamespace(get_template=lambda name:FakePrompt(llm))
    def add_agent(self,agent,node):self.agent=agent
class FakeAgentBase:
    def __init__(self,uid,model,description,context):self.model=model
fake=types.ModuleType('agent_mesa');fake.AgentBase=FakeAgentBase;fake.ModelBase=FakeModelBase

def load_model():
    spec=importlib.util.spec_from_file_location('starnet.contract_model',ROOT/'src/starnet/model.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'agent_mesa':fake}):spec.loader.exec_module(module)
    return module.ParticipantSquadModel

class Env:
    def __init__(self,budget=100):self.budget=budget;self.actions=[];self.weight=0;self.left=3
    def get_remaining_budget(self):return self.budget
    def scan_node(self,node):
        self.actions.append(('scan',node));self.budget-=.5
        return {'w':self.weight,'persona':'和平','comm_left':self.left,'neighbors':[]}
    def communicate(self,node,prompt_id):
        self.actions.append(('comm',node,prompt_id));self.budget-=2
        self.weight += [15,10,-5][prompt_id-1]*.5**(3-self.left);self.left-=1
        return {'status':'success','new_w':self.weight}
    def __getattr__(self,name):raise AssertionError('non-public env access '+name)
class LLM:
    def __init__(self,response=None):self.calls=0;self.response=response
    def send_message(self,prompt):
        self.calls+=1
        if self.response is not None:return self.response
        return json.dumps({'choices':[0],'reason':'test authorization'})

class ModelTests(unittest.TestCase):
    def model(self,env=None,llm=None):
        return load_model()(env or Env(),[{'role':'test','node_count':1}],llm or LLM())
    def test_end_to_end_authorization(self):
        env=Env();llm=LLM();m=self.model(env,llm)
        while not m.step():pass
        self.assertEqual(env.actions,[('scan',1),('comm',1,1),('comm',1,2),('comm',1,3)])
        self.assertEqual(llm.calls,4);self.assertEqual(m.llm_calls,4)
        self.assertEqual(m.stop_reason,'no_safe_candidate')
    def test_bad_llm_never_triggers_fallback_action(self):
        for response in ['not-json','[]','{"choices":[true],"reason":"bad"}','{"choices":[999],"reason":"bad"}']:
            env=Env();llm=LLM(response);m=self.model(env,llm)
            self.assertEqual(m.step(),1);self.assertEqual(env.actions,[])
            self.assertEqual(llm.calls,2);self.assertEqual(m.stop_reason,'invalid_llm_plan')
    def test_llm_can_choose_stop(self):
        env=Env();m=self.model(env,LLM('{"choices":[],"reason":"stop"}'))
        self.assertEqual(m.step(),1);self.assertEqual(env.actions,[])
    def test_llm_choice_controls_prompt_id(self):
        env=Env();m=self.model(env,LLM());m.step()
        m.llm.response='{"choices":[2],"reason":"probe3"}'
        self.assertEqual(m.step(),0)
        self.assertEqual(env.actions[-1],('comm',1,3))
    def test_stage_and_step_limits(self):
        for budget,limit in [(100,120),(200,250)]:
            env=Env(budget);m=self.model(env)
            self.assertEqual(m.max_steps,limit)
            m.steps=limit
            self.assertEqual(m.step(),1);self.assertEqual(env.actions,[])
    def test_call_limit_enforced_before_request(self):
        m=self.model();m.llm_calls=m.max_llm_calls
        self.assertEqual(m.step(),1);self.assertEqual(m.llm.calls,0)
    def test_low_budget_no_calls(self):
        m=self.model(Env(1.5))
        self.assertEqual(m.step(),1);self.assertEqual(m.llm.calls,0)
    def test_ambiguous_mutation_failure_stops_without_retry(self):
        class Broken(Env):
            def scan_node(self,node):self.actions.append(('scan',node));raise TimeoutError()
        env=Broken();m=self.model(env)
        self.assertEqual(m.step(),1);self.assertEqual(m.step(),1)
        self.assertEqual(len(env.actions),1)
    def test_timeout_stops_without_overlapping_request(self):
        class Slow(LLM):
            def send_message(self,prompt):self.calls+=1;time.sleep(.06);return '{}'
        llm=Slow();m=self.model(llm=llm);m.llm_timeout=.005
        self.assertEqual(m.step(),1);self.assertEqual(m.stop_reason,'llm_timeout')
        self.assertEqual(m.step(),1);self.assertEqual(llm.calls,1)
    def test_budget_revalidation(self):
        class Changing(Env):
            def __init__(self):super().__init__();self.reads=0
            def get_remaining_budget(self):
                self.reads+=1
                return 1.0 if self.reads>=3 else 100
        env=Changing();m=self.model(env)
        self.assertEqual(m.step(),1);self.assertEqual(env.actions,[])
    def test_authorized_cut_executes_once_and_replans(self):
        class CutEnv(Env):
            def cut_link(self,u,v):self.actions.append(('cut',u,v));self.budget-=3;return True
        env=CutEnv();m=load_model()(env,[{'node_count':2}],LLM())
        for n in (1,2):
            m.book.record_scan(n,{'w':-10,'persona':'和平','comm_left':0,'neighbors':[3-n]})
        cut={'action':'cut','node':1,'other':2,'cost':3}
        m.book.candidates=lambda budget:('intervene',[cut],1)
        self.assertEqual(m.step(),0)
        self.assertEqual(env.actions,[('cut',1,2)])
        self.assertEqual(m.pending,[])
        self.assertEqual(m.audit[0]['approved'][0],cut)

if __name__=='__main__':unittest.main()
