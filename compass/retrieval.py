"""Hybrid lexical/dense retrieval with explicit hard filters and skill personalization.

Vectors live in SQLite and are matched to postings by a hash of the embedded text, so a refresh
re-embeds only new or edited postings. Postings that have no vector yet fall back to lexical-only
scoring instead of blocking search."""
import threading
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from .indexing import MODEL, make_encoder, normalize, text_hash, embed_missing
from .schemas import Preferences, Search

import os
W_TITLE = float(os.getenv('W_TITLE', '0.5'))      # share of the lexical score that comes from title match
W_DENSE = float(os.getenv('W_DENSE', '0.6'))
QUERY_PREFIX = os.getenv('QUERY_PREFIX', '')       # BGE retrieval prefix

class Retriever:
    def __init__(self, store, dense=False, inline_embed_limit=256):
        self.store = store
        self.lock = threading.RLock()
        self.encoder = None
        self.mode = 'tfidf'
        self.inline_embed_limit = inline_embed_limit
        self.seen_version = -1
        if dense:
            self.encoder = make_encoder()
            self.mode = 'hybrid-bge'
        self.jobs = []
        self.dense_coverage = 0.0
        self.refresh()

    def refresh(self):
        version = self.store.version()
        if self.encoder and self.inline_embed_limit:
            embed_missing(self.store, self.encoder, limit=self.inline_embed_limit)
        self.jobs = self.store.jobs()
        self.seen_version = version
        n = len(self.jobs)
        self.loc = [j['location'].lower() for j in self.jobs]
        self.skillsets = [{s.lower() for s in j['skills']} for j in self.jobs]
        self.dense = None
        self.has_vec = np.zeros(n, dtype=bool)
        if n == 0:
            self.lexical = None
            return
        texts = [f"{j['title']} {j['title']} {j['description'][:2500]} {' '.join(j['skills'])}" for j in self.jobs]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2 if n > 1000 else 1, max_features=150000, dtype=np.float32)
        try:
            self.lexical = self.vectorizer.fit_transform(texts)
        except ValueError:  # tiny catalogs: min_df=2 can empty the vocabulary
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, dtype=np.float32)
            self.lexical = self.vectorizer.fit_transform(texts)
        self.title_vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, dtype=np.float32)
        self.titles = self.title_vectorizer.fit_transform([j['title'] for j in self.jobs])
        if self.encoder:
            have = self.store.vectors(MODEL)
            self.dense = np.zeros((n, 384), dtype=np.float32)
            for i, j in enumerate(self.jobs):
                h = have.get(j['id'])
                if h and h[0] == text_hash(j):
                    self.dense[i] = h[1]; self.has_vec[i] = True
            self.dense_coverage = float(self.has_vec.mean())

    def search(self, args: Search, prefs: Preferences):
        with self.lock:
            if self.store.version() != self.seen_version:
                self.refresh()
            return self._search(args, prefs)

    def _search(self, args: Search, prefs: Preferences):
        if not self.jobs:
            return []
        lex = (self.lexical @ self.vectorizer.transform([args.query]).T).toarray().ravel()
        # Role titles say what a job is; long descriptions are mostly company boilerplate. Weight title matches separately.
        tit = (self.titles @ self.title_vectorizer.transform([args.query]).T).toarray().ravel()
        lex = (1 - W_TITLE) * lex + W_TITLE * tit
        base = lex
        if self.encoder and self.has_vec.any():
            vec = normalize(np.array(list(self.encoder.query_embed(QUERY_PREFIX + args.query)))[0])
            dense = self.dense @ vec
            base = np.where(self.has_vec, W_DENSE * dense + (1 - W_DENSE) * lex, lex)
        location = (args.location or prefs.location).lower().strip()
        remote = args.remote_only or prefs.remote_only
        want = {s.lower() for s in prefs.skills}
        cand = []
        for i, j in enumerate(self.jobs):
            if remote and j['work_mode'] != 'remote':
                continue
            if location and location not in self.loc[i] and not (remote and j['location'] == 'Worldwide'):
                continue
            matched = sorted(want & self.skillsets[i])
            fit = len(matched) / max(len(j['skills']), 1)
            cand.append((float(0.85 * base[i] + 0.15 * fit), i, matched))
        cand.sort(key=lambda t: (-t[0], self.jobs[t[1]]['id']))
        return [dict(self.jobs[i], score=round(s, 4), matched_skills=m, retrieval_mode=self.mode) for s, i, m in cand[:args.limit]]
