"""Run comparable public sandbox research controls (not submission policies)."""
import argparse
import json
import resource
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.local import RemoteEnv
from starnet.experiments import make_seed, run_policy


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--seeds',default='21,22,23,24,25,26');ap.add_argument('--nodes',type=int,default=10);ap.add_argument('--budget',type=float,default=30);args=ap.parse_args()
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w') as f:
        for index in map(int,args.seeds.split(',')):
            seed=make_seed(index,args.nodes,args.budget)
            for policy in ['natural','fixed','adaptive','structural']:
                start=time.monotonic();env=RemoteEnv(seed)
                steps=run_policy(env,policy,args.nodes)
                budget=env.get_remaining_budget();score=env.trigger_eval()
                row=dict(seed=index,n=args.nodes,initial_budget=args.budget,policy=policy,score=score,budget=budget,steps=steps,llm_calls=0,http_calls=env.calls,seconds=time.monotonic()-start,rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,evidence='official-sandbox-custom-seed')
                f.write(json.dumps(row)+'\n');f.flush();print(json.dumps(row),flush=True)
                (p.parent/('%s-%s-trace.json'%(index,policy))).write_text(json.dumps(env.trace,ensure_ascii=False,indent=2))
            (p.parent/('%s-seed.json'%index)).write_text(json.dumps(seed,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
