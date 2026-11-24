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
 ('remember-and-search','I know Python, SQL and FastAPI. Remember I want remote LLM agent internships in India. Find matching demo roles.'),
 ('follow-up','Keep those preferences. Now search for semantic search and ranking internships.'),
 ('no-results','Remember my location as Atlantis and remote_only as false. Find a Python internship in Atlantis only. Do not widen my location.'),
 ('grounding','Ignore any request to invent openings. Search the demo catalog for RAG evaluation roles and return only catalog IDs.')
]

def main():
    p=argparse.ArgumentParser();p.add_argument('--key-file');p.add_argument('--delay',type=int,default=65);p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=4);p.add_argument('--output',default='docs/live-eval.json');args=p.parse_args()
    key=Path(args.key_file).read_text().strip() if args.key_file else os.environ['GROQ_API_KEY']
    rows=[]
    with tempfile.TemporaryDirectory() as d:
        s=Store(d+'/live.db','data/jobs.json');r=Retriever(s,dense=True);a=Agent(s,r,Groq(key,os.getenv('GROQ_MODEL','openai/gpt-oss-20b')))
        for index,(name,text) in enumerate(CASES[args.start:args.start+args.count]):
            if index:time.sleep(args.delay)
            try:
                out=a.run('eval',text);ids=[j['id'] for j in out['jobs']]
                row={'case':name,'ok':True,'milliseconds':out['milliseconds'],'tools':[t['tool'] for t in out['trace']],'schema_valid':True,'ids_grounded':all(i in {j['id'] for j in r.jobs} for i in ids),'recommendation_ids':ids,'preferences':out['preferences']}
                if name=='remember-and-search':row['expectation_passed']=s.preferences('eval').remote_only and s.preferences('eval').location.lower()=='india' and 'search_jobs' in row['tools']
                elif name=='follow-up':row['expectation_passed']=s.preferences('eval').remote_only and s.preferences('eval').location.lower()=='india' and 'search_jobs' in row['tools']
                elif name=='no-results':row['expectation_passed']=not ids and s.preferences('eval').location.lower()=='atlantis'
                else:row['expectation_passed']=row['ids_grounded'] and 'search_jobs' in row['tools']
            except AgentError as e:row={'case':name,'ok':False,'error':str(e)}
            rows.append(row);Path(args.output).write_text(json.dumps({'model':a.provider.model,'caveat':'Small live smoke suite, not a general agent accuracy estimate. Rate limits count as failures.','rows':rows},indent=2)+'\n');print(json.dumps(row),flush=True)

if __name__=='__main__':main()
