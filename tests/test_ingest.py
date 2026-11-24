import json
import numpy as np
import pytest
import ingest
from compass import sources, indexing
from compass.store import Store
from compass.retrieval import Retriever
from compass.schemas import Search, Preferences
from manage import Job

GH = {'jobs': [
    {'id': 1, 'title': 'ML Engineer, Search', 'location': {'name': 'Remote - India'}, 'updated_at': '2026-11-20T10:00:00-05:00',
     'absolute_url': 'https://boards.greenhouse.io/acme/jobs/1',
     'content': '&lt;p&gt;Build ranking and embeddings with Python &amp;amp; SQL on Kubernetes.&lt;/p&gt;'},
    {'id': 2, 'title': 'Account Executive', 'location': {'name': 'London'}, 'updated_at': '2026-11-19T10:00:00Z',
     'absolute_url': 'https://boards.greenhouse.io/acme/jobs/2', 'content': '&lt;p&gt;Sell things.&lt;/p&gt;'}]}
LV = [{'id': 'abc-1', 'text': 'Backend Engineer', 'categories': {'location': 'Bengaluru'}, 'workplaceType': 'hybrid',
       'descriptionPlain': 'Python, PostgreSQL, Docker.', 'createdAt': 1763600000000, 'hostedUrl': 'https://jobs.lever.co/x/abc-1'}]
AB = {'jobs': [{'id': 'u1', 'title': 'LLM Engineer', 'location': 'San Francisco', 'isRemote': True, 'isListed': True,
                'descriptionPlain': 'Build LLM agents with tool use and evals.', 'publishedAt': '2026-11-01T00:00:00.000+00:00', 'jobUrl': 'https://jobs.ashbyhq.com/x/u1'},
               {'id': 'u2', 'title': 'Hidden', 'location': 'x', 'isListed': False, 'descriptionPlain': 'x'}]}

class FakeEncoder:
    def __init__(self): self.calls = 0
    def embed(self, texts, batch_size=32):
        self.calls += len(texts)
        for t in texts:
            rng = np.random.default_rng(abs(hash(t)) % 2**32); yield rng.normal(size=384)
    def query_embed(self, q): yield np.ones(384)

def test_parsers_produce_valid_jobs():
    jobs = sources.parse_greenhouse('acme', 'Acme', GH) + sources.parse_lever('x', 'X', LV) + sources.parse_ashby('x', 'X', AB)
    assert len(jobs) == 4  # unlisted Ashby posting dropped
    for j in jobs: Job.model_validate(j)
    ml = jobs[0]
    assert ml['work_mode'] == 'remote' and {'Python', 'SQL', 'Kubernetes', 'Embeddings'} <= set(ml['skills'])
    assert '<' not in ml['description'] and '&amp;' not in ml['description']
    assert jobs[2]['work_mode'] == 'hybrid' and jobs[3]['work_mode'] == 'remote' and 'Agents' not in jobs[2]['skills']
    assert len({j['id'] for j in jobs}) == 4

def test_sync_adds_updates_and_closes(tmp_path):
    s = Store(str(tmp_path / 'a.db'))
    jobs = sources.parse_greenhouse('acme', 'Acme', GH)
    assert s.sync('greenhouse:acme', jobs)['added'] == 2
    again = s.sync('greenhouse:acme', jobs); assert again['unchanged'] == 2 and again['closed'] == 0
    v = s.version(); s.sync('greenhouse:acme', jobs); assert s.version() == v  # no change, no re-index
    st = s.sync('greenhouse:acme', jobs[:1]); assert st['closed'] == 1 and len(s.jobs()) == 1
    changed = dict(jobs[0], title='Senior ML Engineer'); assert s.sync('greenhouse:acme', [changed])['updated'] == 1
    assert s.sync('greenhouse:acme', jobs)['reopened'] == 1 and s.counts()['active'] == 2

def test_sync_only_touches_its_own_source(tmp_path):
    s = Store(str(tmp_path / 'b.db'))
    s.sync('greenhouse:acme', sources.parse_greenhouse('acme', 'Acme', GH)); s.sync('lever:x', sources.parse_lever('x', 'X', LV))
    s.sync('lever:x', [])
    assert {j['source'] for j in s.jobs()} == {'greenhouse:acme'}

def test_incremental_reembedding(tmp_path):
    s = Store(str(tmp_path / 'c.db')); enc = FakeEncoder()
    jobs = sources.parse_greenhouse('acme', 'Acme', GH)
    s.sync('greenhouse:acme', jobs)
    assert indexing.embed_missing(s, enc) == 2
    assert indexing.embed_missing(s, enc) == 0 and enc.calls == 2          # nothing changed
    s.sync('greenhouse:acme', [dict(jobs[0], updated_at='2026-11-22'), jobs[1]])  # metadata only
    assert indexing.embed_missing(s, enc) == 0
    s.sync('greenhouse:acme', [dict(jobs[0], description='Totally new description about ranking'), jobs[1]])
    assert indexing.embed_missing(s, enc) == 1 and enc.calls == 3          # only the edited text
    s.sync('greenhouse:acme', jobs[:1]); assert s.drop_inactive_vectors() == 1

def test_retriever_uses_stored_vectors_and_falls_back(tmp_path, monkeypatch):
    s = Store(str(tmp_path / 'd.db')); s.sync('greenhouse:acme', sources.parse_greenhouse('acme', 'Acme', GH))
    monkeypatch.setattr('compass.retrieval.make_encoder', lambda: FakeEncoder())
    r = Retriever(s, dense=True, inline_embed_limit=1)
    assert r.dense_coverage == 0.5                                          # one posting still lacks a vector
    out = r.search(Search(query='ranking embeddings python'), Preferences())
    assert out and out[0]['title'].startswith('ML Engineer')

def test_failed_board_keeps_rows(tmp_path, monkeypatch):
    db = str(tmp_path / 'e.db'); boards = tmp_path / 'boards.json'
    boards.write_text(json.dumps([{'ats': 'greenhouse', 'slug': 'acme', 'company': 'Acme'}]))
    monkeypatch.setattr(sources, 'polite_sleep', lambda *_: None)
    monkeypatch.setattr(sources, 'fetch_board', lambda c, a, s, n: sources.parse_greenhouse(s, n, GH))
    assert ingest.run(db, str(boards), log=lambda *_: None)['totals']['added'] == 2
    def boom(*a): raise RuntimeError('HTTP 500')
    monkeypatch.setattr(sources, 'fetch_board', boom)
    rep = ingest.run(db, str(boards), log=lambda *_: None)
    assert rep['boards_failed'] == 1 and rep['totals']['closed'] == 0 and rep['index']['active'] == 2
    monkeypatch.setattr(sources, 'fetch_board', lambda c, a, s, n: sources.parse_greenhouse(s, n, {'jobs': GH['jobs'][:1]}))
    assert ingest.run(db, str(boards), log=lambda *_: None)['totals']['closed'] == 1

def test_search_over_real_shaped_index_stays_fast(tmp_path):
    s = Store(str(tmp_path / 'f.db')); base = sources.parse_greenhouse('acme', 'Acme', GH)[0]
    jobs = [dict(base, id=f'gr-acme-{i}', title=f'Engineer {i}', description=f'Work on topic{i % 50} systems and python') for i in range(3000)]
    s.sync('greenhouse:acme', jobs); r = Retriever(s)
    out = r.search(Search(query='topic7 python'), Preferences()); assert len(out) == 5 and all('topic7' in j['description'] for j in out[:3])
