"""Validate and transactionally import a JSON catalog. Existing IDs update in place."""
import argparse
import json
from pathlib import Path
from typing import Literal
from pydantic import Field, HttpUrl
from compass.schemas import Strict
from compass.store import Store

class Job(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    title: str = Field(min_length=1,max_length=200)
    company: str = Field(min_length=1,max_length=200)
    location: str = Field(min_length=1,max_length=200)
    work_mode: Literal['remote','hybrid','onsite']
    skills: list[str] = Field(min_length=1,max_length=30)
    description: str = Field(min_length=1,max_length=10000)
    source: str = Field(min_length=1,max_length=200)
    updated_at: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    url: HttpUrl | None = None

def import_catalog(path,database):
    raw=json.loads(Path(path).read_text())
    if not isinstance(raw,list) or not 1<=len(raw)<=5000:raise ValueError('Catalog must contain between 1 and 5000 records.')
    jobs=[Job.model_validate(x).model_dump(mode='json') for x in raw]
    if len({j['id'] for j in jobs})!=len(jobs):raise ValueError('Duplicate job IDs in import.')
    store=Store(database);store.upsert(jobs)
    return len(jobs)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('file');p.add_argument('--database',default='/tmp/compass/compass.db');a=p.parse_args();print(f'Imported {import_catalog(a.file,a.database)} validated jobs. The running index refreshes on its next search.')
