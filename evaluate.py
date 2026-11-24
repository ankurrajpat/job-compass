"""Retrieval benchmark on explicit, synthetic relevance judgments. No LLM needed."""
import argparse
import json
import tempfile
import time
from pathlib import Path
from compass.store import Store
from compass.retrieval import Retriever
from compass.schemas import Search, Preferences

CASES=[
 ('LLM agents tool calling structured outputs',['j01','j09','j14']),
 ('semantic search embeddings retrieval ranking',['j02','j15']),
 ('recommendation two tower cold start',['j03','j20']),
 ('SQL database schemas transactions indexing',['j10','j04']),
 ('Docker container deployment cloud reliability',['j08','j22']),
 ('RAG question answering citation evaluation',['j05','j21']),
 ('React TypeScript accessible frontend',['j06','j13']),
 ('Python API endpoints FastAPI SQL',['j19','j04']),
 ('data ETL ingestion changing feeds',['j18']),
 ('computer vision image object detection',['j11']),
 ('Android Kotlin mobile screens',['j17']),
 ('LLM quality evaluation labeled test sets',['j24','j05'])
]

def run(dense=False):
    with tempfile.TemporaryDirectory() as d:
        s=Store(d+'/eval.db','data/jobs.json');r=Retriever(s,dense=dense)
        rows=[]
        for query,relevant in CASES:
            start=time.perf_counter();results=r.search(Search(query=query,limit=5),Preferences());latency=(time.perf_counter()-start)*1000
            ids=[j['id'] for j in results];hits=set(ids)&set(relevant);ranks=[ids.index(x)+1 for x in relevant if x in ids]
            rows.append({'query':query,'relevant':relevant,'top5':ids,'recall_at_5':len(hits)/len(relevant),'reciprocal_rank':1/min(ranks) if ranks else 0,'milliseconds':round(latency,2)})
        times=sorted(row['milliseconds'] for row in rows)
        return {'mode':r.mode,'queries':len(rows),'catalog_size':len(r.jobs),'recall_at_5':round(sum(x['recall_at_5'] for x in rows)/len(rows),4),'mrr_at_5':round(sum(x['reciprocal_rank'] for x in rows)/len(rows),4),'p50_query_ms':times[len(times)//2],'max_query_ms':max(times),'caveat':'Hand-authored synthetic catalog and relevance labels, not a production retrieval benchmark. Dense model loading and index construction excluded from query timing. Tiny sample: report max, not p95.','rows':rows}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dense',action='store_true');parser.add_argument('--output',default='docs/retrieval-eval.json');args=parser.parse_args();result=run(args.dense);Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
