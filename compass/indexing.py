"""Incremental embedding: only postings that are new or whose embedded text changed are re-embedded."""
import hashlib
import numpy as np

MODEL = 'BAAI/bge-small-en-v1.5'
EMBED_CHARS = 450


def embed_text(job):
    return f"{job['title']} at {job['company']}. {job['location']}. {job['description'][:EMBED_CHARS]}"


def text_hash(job):
    return hashlib.sha1(embed_text(job).encode()).hexdigest()


def make_encoder(threads=2):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL, threads=threads)


def normalize(m):
    m = np.asarray(m, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-9)


def embed_missing(store, encoder, limit=None, chunk=128, progress=None):
    """Embed active jobs that have no vector for their current text. Saves after every chunk,
    so an interrupted run resumes where it stopped. Returns number embedded."""
    have = store.vectors(MODEL)
    todo = [j for j in store.jobs() if have.get(j['id'], ('',))[0] != text_hash(j)]
    if limit is not None:
        todo = todo[:limit]
    done = 0
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        vecs = normalize(list(encoder.embed([embed_text(j) for j in batch], batch_size=32)))
        store.put_vectors(MODEL, [(j['id'], text_hash(j), v) for j, v in zip(batch, vecs)])
        done += len(batch)
        if progress:
            progress(done, len(todo))
    return done
