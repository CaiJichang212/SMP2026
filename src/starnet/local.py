"""Local experiment transports; excluded from the submission ZIP."""
from pathlib import Path
import requests

URL = 'http://8.222.218.162:5000'

class RemoteEnv:
    """Bounded requests; never retry possibly applied mutations."""
    def __init__(self, seed, url=URL):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session.headers["Connection"] = "close"
        self.sid = None
        self.calls = 0
        self.trace = []
        self.sid = self.request('start_session', seed=seed)['session_id']

    def request(self, endpoint, **data):
        if self.sid is not None:
            data['session_id'] = self.sid
        self.calls += 1
        r = self.session.post(self.url + '/api/' + endpoint, json=data, timeout=(5, 20))
        r.raise_for_status()
        result = r.json()
        if not isinstance(result, dict) or 'error' in result:
            raise RuntimeError('sandbox protocol error: ' + endpoint)
        self.trace.append({'endpoint': endpoint, 'arguments': {k:v for k,v in data.items() if k not in ('session_id','seed')}, 'result': result if endpoint != 'start_session' else {'created': True}})
        return result

    def get_remaining_budget(self):
        return float(self.request('get_budget')['budget'])
    def scan_node(self, node_id):
        return self.request('scan', node_id=node_id)['data']
    def communicate(self, node_id, prompt_id):
        return self.request('communicate', node_id=node_id, prompt_id=prompt_id)
    def cut_link(self, u, v):
        return self.request('cut', u=u, v=v)['success']
    def shield_node(self, node_id):
        return self.request('shield', node_id=node_id)['success']
    def trigger_eval(self):
        return float(self.request('evaluate')['final_score'])


class LocalLLM:
    def __init__(self, env_file):
        values={}
        for line in Path(env_file).read_text().splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1);values[key.strip()]=value.strip().strip('\"\'')
        self.url=values['LLM_BASE_URL'].rstrip('/')+'/chat/completions'
        self.key=values['LLM_API_KEY']
        self.model=values['LLM_MODEL']
        self.calls=0
        self.usage=[]
    def send_message(self,prompt,json_flag=False):
        self.calls+=1
        try:
            r=requests.post(self.url,headers={'Authorization':'Bearer '+self.key},json={'model':self.model,'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':900},timeout=(5,45))
            if not r.ok: raise RuntimeError('LLM HTTP status '+str(r.status_code))
            body=r.json();self.usage.append(body.get('usage',{}))
            return body['choices'][0]['message']['content']
        except requests.RequestException:
            raise RuntimeError('LLM transport failed (details redacted)') from None
    def get_lang_embedding(self):
        return None  # Memory is instantiated but no embedding/retrieval is used.
