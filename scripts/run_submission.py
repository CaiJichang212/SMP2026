"""Run an extracted ZIP with a real framework + LLM on a public custom seed."""
import argparse
import hashlib
import importlib.util
import json
import os
import resource
import sys
import tempfile
import time
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.local import LocalLLM, RemoteEnv

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--zip',required=True);ap.add_argument('--seed',required=True);ap.add_argument('--output',required=True);ap.add_argument('--env',default='.env');args=ap.parse_args()
    seed_path=Path(args.seed).resolve();zip_path=Path(args.zip).resolve();output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    seed=json.loads(seed_path.read_text());llm=LocalLLM(args.env)
    # The test harness alone knows seed internals. The participant only receives
    # the documented environment object and a configured public node count.
    start=time.monotonic()
    natural_env=RemoteEnv(seed);natural=natural_env.trigger_eval()
    env=RemoteEnv(seed)
    with tempfile.TemporaryDirectory(prefix='starnet-run-') as temp:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.startswith('/') or '..' in Path(name).parts:raise ValueError('unsafe archive')
            z.extractall(temp)
        spec=importlib.util.spec_from_file_location('submission_under_test',Path(temp)/'starnet_model.py')
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        persons=json.loads((Path(temp)/'config.json').read_text())['person']
        persons[0]['node_count']=len(seed['nodes'])
        model=module.ParticipantSquadModel(env,persons,llm)
        while model.steps < model.max_steps:
            result=model.step()
            # Save completed actions as checkpoints, without credentials/provider bodies.
            (output.parent/(output.stem+'-audit.json')).write_text(json.dumps(model.audit,ensure_ascii=False,indent=2))
            if result:break
        budget=env.get_remaining_budget();score=env.trigger_eval()
        row={'evidence':'official-sandbox-custom-seed-real-llm','seed':seed_path.name,'seed_sha256':hashlib.sha256(seed_path.read_bytes()).hexdigest(),'zip_sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest(),'python':sys.version.split()[0],'framework':module.ModelBase.__module__,'llm_model':llm.model,'initial_budget':seed['global_setting']['max_budget'],'natural_score':natural,'score':score,'delta':score-natural,'remaining_budget':budget,'steps':model.steps,'llm_calls':llm.calls,'model_llm_calls':model.llm_calls,'http_calls':env.calls+natural_env.calls,'seconds':time.monotonic()-start,'rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'stop_reason':model.stop_reason,'usage':llm.usage}
        output.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        (output.parent/(output.stem+'-trace.json')).write_text(json.dumps(env.trace,ensure_ascii=False,indent=2))
        print(json.dumps(row,ensure_ascii=False),flush=True)
        if model.stop_reason in ('environment_or_protocol_error','llm_timeout','invalid_llm_plan'):return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
