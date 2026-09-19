"""Deterministic allowlisted single-file submission builder and validator."""
import argparse
import ast
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/starnet'


def build(output):
    policy=(SOURCE/'policy.py').read_text()
    topology=(SOURCE/'topology.py').read_text()
    model=(SOURCE/'model.py').read_text()
    line='from .policy import ObservationBook, finite_number, validate_plan\n'
    if model.count(line)!=1:raise ValueError('unexpected module boundary')
    topology_import='from .policy import ObservationBook, finite_number\n'
    model_import='from .topology import TopologyBook\n'
    if topology.count(topology_import)!=1 or model.count(model_import)!=1:
        raise ValueError('unexpected topology module boundary')
    code=policy+'\n\n'+topology.replace(topology_import,'')+'\n\n'+model.replace(line,'').replace(model_import,'')
    tree=ast.parse(code,feature_version=(3,9))
    allowed={'get_remaining_budget','scan_node','communicate','cut_link','shield_node'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Attribute) and node.value.attr=='env':
            if node.attr not in allowed:raise ValueError('non-public environment access')
        if isinstance(node,ast.ImportFrom) and node.level:raise ValueError('unresolved relative import')
    payload={'starnet_model.py':code.encode(),'config.json':(SOURCE/'config.json').read_bytes()}
    for name in ['commander.txt','reflect.txt']:payload['prompt/'+name]=(SOURCE/'prompt'/name).read_bytes()
    json.loads(payload['config.json'])
    # Check actual local secret values without writing them to logs.
    env_file=ROOT/'.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' not in line or line.lstrip().startswith('#'):continue
            key,value=line.split('=',1);value=value.strip().strip('\"\'')
            if any(x in key.upper() for x in ['KEY','SECRET','TOKEN']) and len(value)>=8:
                if any(value.encode() in b for b in payload.values()):raise ValueError('secret found in package')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,body in sorted(payload.items()):
            entry=zipfile.ZipInfo(name,date_time=(2026,9,18,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
            z.writestr(entry,body)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None or set(z.namelist())!=set(payload):raise ValueError('archive failed verification')
        for name,body in payload.items():
            if z.read(name)!=body:raise ValueError('artifact drift')
    result={'path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size,'members':sorted(payload),'python39_syntax':True,'secret_scan':'pass','public_api_ast':'pass'}
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',default=str(ROOT/'submissions/starnet-20260918-v2.zip'));build(ap.parse_args().output)
