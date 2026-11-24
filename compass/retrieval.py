"""Hybrid lexical/dense retrieval with explicit hard filters and skill personalization."""
import os
import re
import threading
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from .schemas import Preferences, Search

class Retriever:
    def __init__(self, store, dense=False):
        self.store = store
        self.lock = threading.RLock()
        self.encoder = None
        self.mode = 'tfidf'
        if dense:
            from fastembed import TextEmbedding
            self.encoder = TextEmbedding(model_name='BAAI/bge-small-en-v1.5', threads=2)
            self.mode = 'hybrid-bge'
        self.refresh()

    def refresh(self):
        self.jobs = self.store.jobs()
        self.texts = [f"{j['title']} {j['description']} {' '.join(j['skills'])}" for j in self.jobs]
        self.vectorizer = TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True)
        self.lexical = self.vectorizer.fit_transform(self.texts)
        self.dense = None
        if self.encoder:
            self.dense = np.array(list(self.encoder.embed(self.texts)))
            self.dense /= np.maximum(np.linalg.norm(self.dense, axis=1, keepdims=True), 1e-9)

    def search(self, args: Search, prefs: Preferences):
        with self.lock:
            if self.store.jobs() != self.jobs:
                self.refresh()
            return self._search(args,prefs)

    def _search(self, args: Search, prefs: Preferences):
        query = args.query
        lex = (self.lexical @ self.vectorizer.transform([query]).T).toarray().ravel()
        base = lex
        if self.encoder:
            vec = np.array(list(self.encoder.query_embed(query)))[0]
            vec /= max(np.linalg.norm(vec), 1e-9)
            dense = self.dense @ vec
            base = 0.6*dense + 0.4*lex
        location = (args.location or prefs.location).lower().strip()
        remote = args.remote_only or prefs.remote_only
        results = []
        for i,j in enumerate(self.jobs):
            if remote and j['work_mode'] != 'remote':
                continue
            if location and location not in j['location'].lower() and not (remote and j['location'] == 'Worldwide'):
                continue
            matched = sorted(set(s.lower() for s in prefs.skills) & set(s.lower() for s in j['skills']))
            fit = len(matched)/max(len(j['skills']),1)
            score = float(0.85*base[i] + 0.15*fit)
            results.append(dict(j,score=round(score,4),matched_skills=matched,retrieval_mode=self.mode))
        return sorted(results,key=lambda j:(-j['score'],j['id']))[:args.limit]
