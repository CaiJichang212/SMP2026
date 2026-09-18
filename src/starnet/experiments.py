"""Public research fixtures and no-LLM controls; never a submission policy."""
import random


def make_seed(index, n=10, budget=30):
    rng = random.Random(index)
    edges = set()
    for i in range(1,n):
        edges.add((i,i+1))
    if index % 3 == 0:
        edges.update((1,i) for i in range(2,n+1))
    elif index % 3 == 1:
        edges.update((i,j) for i in range(1,n+1) for j in range(i+1,n+1) if rng.random()<0.15)
    nodes=[]
    for i in range(1,n+1):
        persona=rng.choice(['和平','中立','暴力'])
        w=rng.uniform(-30,20)
        if i==1 and index%3==0: w=-65
        nodes.append(dict(id=i,w=round(w,3),persona=persona,r={'和平':1.4,'中立':0.9,'暴力':0.25}[persona]*rng.uniform(.8,1.2),comm_left=3))
    strengths=[[15,10,-5],[-5,15,10],[10,-5,15]][index%3]
    return dict(global_setting=dict(max_budget=budget,max_api_calls=120 if n<=50 else 250),original_total=round(sum(x['w'] for x in nodes), 3),nodes=nodes,edges=sorted(edges),prompts={str(i+1):x for i,x in enumerate(strengths)})


def run_policy(env, policy, n):
    limit = 250 if n > 50 else 120
    if policy=='natural': return 0
    nodes={};steps=0
    for i in range(1,n+1):
        if env.get_remaining_budget()<2.5: break
        x=env.scan_node(i); steps+=1
        if x is not None: nodes[i]=x
    pid=1;gain={};samples=[]
    if policy!='fixed' and nodes:
        target=max(nodes,key=lambda i: (nodes[i]['persona']=='和平',len(nodes[i]['neighbors'])))
        for p in (1,2,3):
            if env.get_remaining_budget()<2 or nodes[target]['comm_left']<=0: break
            old=nodes[target]['w'];used=3-nodes[target]['comm_left']
            r=env.communicate(target,p);steps+=1
            if r.get('status')!='success': break
            value=(r['new_w']-old)/(0.5**used)
            samples.append((value,p));gain[p]=value
            nodes[target]['w']=r['new_w'];nodes[target]['comm_left']-=1
        if not samples or max(samples)[0]<=0:return steps
        pid=max(samples)[1]
    if policy=='structural':
        for i in sorted(nodes,key=lambda j:nodes[j]['w']*(len(nodes[j]['neighbors'])+1)):
            if env.get_remaining_budget()<5:break
            if nodes[i]['w'] < -20 and len(nodes[i]['neighbors'])>=3:
                if env.shield_node(i):
                    steps+=1
                    for x in nodes.values(): x['neighbors']=[v for v in x['neighbors'] if v!=i]
                    nodes[i]['comm_left']=0
    while env.get_remaining_budget()>=2 and steps<limit:
        candidates=[i for i,x in nodes.items() if x['comm_left']>0]
        if not candidates:break
        i=max(candidates,key=lambda j:(len(nodes[j]['neighbors'])+1)*{'和平':1.4,'中立':.9,'暴力':.25}.get(nodes[j]['persona'],.5)*(.5**(3-nodes[j]['comm_left'])))
        r=env.communicate(i,pid);steps+=1
        if r.get('status')!='success': break
        nodes[i]['w']=r['new_w'];nodes[i]['comm_left']-=1
    return steps
