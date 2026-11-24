import json
import pytest
from fastapi.testclient import TestClient
from compass.store import Store
from compass.retrieval import Retriever
from compass.schemas import Search, Remember, Answer
from compass.agent import Agent, AgentError
from compass.app import create_app

class Scripted:
    def __init__(self, messages): self.messages=iter(messages); self.seen=[]
    def complete(self, messages): self.seen.append(list(messages)); return next(self.messages)

def tool(name,args,id='c1'):
    return {'role':'assistant','content':None,'tool_calls':[{'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}

def final(ids=('j01',)):
    return {'role':'assistant','content':json.dumps({'summary':'Matches from the demo catalog.','recommendations':[{'job_id':i,'reason':'Relevant skills in source.','gaps':[]} for i in ids],'follow_up':''})}

@pytest.fixture
def stack(tmp_path):
    store=Store(str(tmp_path/'test.db'),'data/jobs.json'); return store,Retriever(store)

def test_seed_and_upsert(stack):
    s,r=stack; assert len(s.jobs())==24
    job=s.jobs()[0];job['title']='Changed';s.upsert([job]);assert len(s.jobs())==24; assert s.jobs()[0]['title']=='Changed'

def test_memory_isolation_and_merge(stack):
    s,r=stack;s.remember('a',Remember(skills=['Python'],location='India'));s.remember('a',Remember(remote_only=True));assert s.preferences('a').skills==['Python'];assert s.preferences('b').skills==[];assert s.preferences('a').location=='India'

def test_clear_session(stack):
    s,r=stack;s.remember('a',Remember(skills=['SQL']));s.log('a','user','hello');s.clear('a');assert not s.history('a');assert not s.preferences('a').skills

def test_sql_injection_is_data(stack):
    s,r=stack;s.remember("'; DROP TABLE jobs;--",Remember(location="'; DROP TABLE jobs;--"));assert len(s.jobs())==24

def test_history_bounded_and_isolated(stack):
    s,r=stack
    for i in range(15):s.log('a','user',str(i))
    assert len(s.history('a'))==10;assert s.history('a')[0]['content']=='5';assert not s.history('b')

def test_search_relevance(stack):
    s,r=stack;j=r.search(Search(query='LLM agents tool calling structured outputs'),s.preferences('x'));assert 'j01' in [x['id'] for x in j[:3]]

def test_remote_and_location_filters(stack):
    s,r=stack;s.remember('x',Remember(location='India',remote_only=True));j=r.search(Search(query='Python'),s.preferences('x'));assert all(x['work_mode']=='remote' and ('India' in x['location'] or x['location']=='Worldwide') for x in j)

def test_no_matches_not_relaxed(stack):
    s,r=stack;assert r.search(Search(query='Python',location='Atlantis'),s.preferences('x'))==[]

def test_tool_execution_and_grounding(stack):
    s,r=stack;p=Scripted([tool('remember_preferences',{'skills':['Python'],'remote_only':True}),tool('search_jobs',{'query':'LLM agents'}),tool('get_job_details',{'job_ids':['j01']}),final()]);out=Agent(s,r,p).run('a','Find jobs');assert [t['tool'] for t in out['trace']]==['remember_preferences','search_jobs','get_job_details'];assert out['jobs'][0]['id']=='j01';assert out['preferences']['remote_only'];assert out['provider']=='groq'

def test_unknown_tool_rejected(stack):
    s,r=stack;p=Scripted([tool('execute_sql',{'query':'select *'}),final(())]);out=Agent(s,r,p).run('a','hi');assert out['trace'][0]['status']=='rejected'

def test_bad_args_rejected(stack):
    s,r=stack;p=Scripted([tool('search_jobs',{'query':'python','limit':100}),final(())]);assert Agent(s,r,p).run('a','hi')['trace'][0]['status']=='rejected'

def test_details_must_be_retrieved(stack):
    s,r=stack;p=Scripted([tool('get_job_details',{'job_ids':['j01']}),final(())]);assert Agent(s,r,p).run('a','hi')['trace'][0]['status']=='rejected'

def test_hallucinated_ids_fail_closed(stack):
    s,r=stack;p=Scripted([final(('fake',)),final(('fake',))]);
    with pytest.raises(AgentError):Agent(s,r,p).run('a','hi')
    assert not s.history('a')

def test_malformed_output_repair(stack):
    s,r=stack;p=Scripted([{'role':'assistant','content':'not json'},final(())]);assert Agent(s,r,p).run('a','hi')['recommendations']==[]

def test_duplicate_ids_fail(stack):
    s,r=stack;p=Scripted([tool('search_jobs',{'query':'LLM agents'}),final(('j01','j01')),final(('j01','j01'))]);
    with pytest.raises(AgentError):Agent(s,r,p).run('a','hi')

def test_tool_budget(stack):
    s,r=stack;p=Scripted([tool('search_jobs',{'query':'Python'})]*3)
    with pytest.raises(AgentError):Agent(s,r,p,max_steps=3).run('a','hi')

def test_followup_receives_memory(stack):
    s,r=stack;s.remember('a',Remember(location='India'));s.log('a','user','I like agents');p=Scripted([final(())]);Agent(s,r,p).run('a','continue');assert 'India' in p.seen[0][0]['content'];assert p.seen[0][1]['content']=='I like agents'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    return TestClient(create_app(str(tmp_path/'api.db'),dense=False))

def test_health_and_preview(client):
    h=client.get('/api/health');assert h.json()['provider']=='preview';assert h.json()['job_count']==24
    d=client.post('/api/chat',json={'message':'LLM agents'}).json();Answer.model_validate({k:d[k] for k in ['summary','recommendations','follow_up']});assert d['provider']=='preview'

def test_cookie_and_headers(client):
    r=client.get('/');assert 'httponly' in r.headers['set-cookie'].lower();assert 'Content-Security-Policy' in r.headers;assert 'Job Compass' in r.text

def test_api_memory_and_delete(client):
    client.patch('/api/preferences',json={'skills':['Python']});assert client.get('/api/session').json()['preferences']['skills']==['Python'];client.delete('/api/session');assert not client.get('/api/session').json()['preferences']['skills']

def test_cross_origin_mutations_rejected(client):
    assert client.post('/api/chat',headers={'Origin':'https://evil.invalid'},json={'message':'hi'}).status_code==403

def test_message_validation(client):
    assert client.post('/api/chat',json={'message':''}).status_code==422
    assert client.post('/api/chat',json={'message':'x'*2001}).status_code==422
    assert client.post('/api/chat',json={'message':'hi','sql':'no'}).status_code==422

def test_rate_limit_survives_cookie_rotation(client):
    for _ in range(5):
        client.cookies.clear();assert client.post('/api/chat',json={'message':'Python'}).status_code==200
    client.cookies.clear();assert client.post('/api/chat',json={'message':'Python'}).status_code==429

def test_static_js_uses_text_nodes(client):
    js=client.get('/static/app.js').text;assert '.innerHTML' not in js;assert 'textContent' in js

def test_api_sessions_isolated(tmp_path):
    app=create_app(str(tmp_path/'shared.db'),dense=False);a=TestClient(app);b=TestClient(app);a.patch('/api/preferences',json={'skills':['SQL']});assert b.get('/api/session').json()['preferences']['skills']==[]

def test_running_retriever_refreshes(stack):
    s,r=stack;j=s.jobs()[0];j['title']='Uniquequartz Internship';j['description']='Uniquequartz uniquequartz';s.upsert([j]);out=r.search(Search(query='uniquequartz'),s.preferences('a'));assert out[0]['id']=='j01';assert out[0]['title']=='Uniquequartz Internship'

def test_catalog_validation_before_write(tmp_path):
    from manage import import_catalog
    p=tmp_path/'bad.json';p.write_text('[{"id":"no"}]')
    with pytest.raises(ValueError):import_catalog(p,str(tmp_path/'bad.db'))
    assert not (tmp_path/'bad.db').exists()

def test_catalog_import_and_duplicates(tmp_path):
    from manage import import_catalog
    p=tmp_path/'jobs.json';j=json.loads(open('data/jobs.json').read())[0];p.write_text(json.dumps([j]));assert import_catalog(p,str(tmp_path/'import.db'))==1
    p.write_text(json.dumps([j,j]));
    with pytest.raises(ValueError):import_catalog(p,str(tmp_path/'import.db'))

def test_logging_creates_expiring_session(stack):
    s,r=stack;s.log('a','user','hello')
    with s.connect() as db:assert db.execute('SELECT count(*) FROM sessions WHERE id=?',('a',)).fetchone()[0]==1

def test_unknown_tool_cannot_mutate_store(stack):
    s,r=stack;p=Scripted([tool('delete_database',{}),final(())]);Agent(s,r,p).run('x','hi');assert len(s.jobs())==24
