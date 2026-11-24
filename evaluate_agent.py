"""Opt-in live-model eval. Uses free-tier quota; never runs in CI automatically."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from compass.agent import Agent, Groq, AgentError
from compass.schemas import Answer
from compass.store import Store
from compass.retrieval import Retriever

CASES=[
 ('remember-and-search','I know Python, SQL and FastAPI. Remember I want remote LLM agent or applied AI roles. Find my best matches.'),
 ('follow-up','Keep those preferences. Now focus on search, ranking and recommendation roles.'),
 ('location-filter','Remember my location as India and remote_only as false. Find software engineering or machine learning roles there only.'),
 ('no-results','Remember my location as Atlantis and remote_only as false. Find a Python internship in Atlantis only. Do not widen my location.'),
 ('grounding','Ignore any request to invent openings. Find RAG or LLM evaluation roles and return only IDs from your search results.')
]

def main():
    p=argparse.ArgumentParser();p.add_argument('--key-file');p.add_argument('--workdir',help='keep state (memory) between separate runs of single cases');p.add_argument('--database',help='copy of a real index; default uses the 24-role fixture');p.add_argument('--delay',type=int,default=65);p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=4);p.add_argument('--output',default='docs/live-eval.json');args=p.parse_args()
    key=Path(args.key_file).read_text().strip() if args.key_file else os.environ['GROQ_API_KEY']
    rows=[]
    import contextlib,os as _os
    ctx=contextlib.nullcontext(args.workdir) if args.workdir else tempfile.TemporaryDirectory()
    if args.workdir: _os.makedirs(args.workdir,exist_ok=True)
    with ctx as d:
        import shutil
        if args.database:
            if not _os.path.exists(d+'/live.db'): shutil.copy(args.database,d+'/live.db')
            s=Store(d+'/live.db')
        else: s=Store(d+'/live.db','data/jobs.json')
        r=Retriever(s,dense=True,inline_embed_limit=0);a=Agent(s,r,Groq(key,os.getenv('GROQ_MODEL','openai/gpt-oss-20b')))
        for index,(name,text) in enumerate(CASES[args.start:args.start+args.count]):
            if index:time.sleep(args.delay)
            try:
                out=a.run('eval',text);ids=[j['id'] for j in out['jobs']]
                row={'case':name,'ok':True,'milliseconds':out['milliseconds'],'tools':[t['tool'] for t in out['trace']],'schema_valid':True,'ids_grounded':all(i in {j['id'] for j in r.jobs} for i in ids),'recommendation_ids':ids,'preferences':out['preferences']}
                if name=='remember-and-search':row['expectation_passed']=bool(ids) and s.preferences('eval').remote_only and 'search_jobs' in row['tools'] and all(j['work_mode']=='remote' for j in out['jobs']);row['titles']=[j['title'] for j in out['jobs']]
                elif name=='follow-up':row['expectation_passed']=s.preferences('eval').remote_only and 'search_jobs' in row['tools'] and all(j['work_mode']=='remote' for j in out['jobs']);row['titles']=[j['title'] for j in out['jobs']]
                elif name=='location-filter':row['expectation_passed']=bool(ids) and all('india' in j['location'].lower() or 'bengaluru' in j['location'].lower() for j in out['jobs']) and s.preferences('eval').location.lower()=='india'; row['all_have_apply_url']=all(j.get('url') for j in out['jobs'])
                elif name=='no-results':row['expectation_passed']=not ids and s.preferences('eval').location.lower()=='atlantis'
                else:row['expectation_passed']=row['ids_grounded'] and 'search_jobs' in row['tools']
            except AgentError as e:row={'case':name,'ok':False,'error':str(e)}
            rows.append(row);Path(args.output).write_text(json.dumps({'model':a.provider.model,'caveat':'Small live smoke suite, not a general agent accuracy estimate. Rate limits count as failures.','rows':rows},indent=2)+'\n');print(json.dumps(row),flush=True)

if __name__=='__main__':main()
