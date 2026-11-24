"""Retrieval check on the real postings index. Relevance is a weak, rule-based label on the POSTING TITLE
(regexes below, written before looking at results), not human judgment and not the text the retriever
mostly matches. Use it to compare lexical vs hybrid, not as a production quality number.

    python evaluate_real.py --database /path/compass.db --output docs/real-eval.json"""
import argparse, json, re, time, statistics
from pathlib import Path
from compass.store import Store
from compass.retrieval import Retriever
from compass.schemas import Search, Preferences

CASES = [  # (query, title regex that makes a posting relevant)
 ('build LLM agents that use tools and keep memory', r'agent|llm|applied ai|ai engineer|machine learning|ml engineer|research engineer'),
 ('semantic search and ranking for a large catalog', r'search|ranking|relevance|retrieval|recommend|ml |machine learning'),
 ('recommendation systems personalization engineer', r'recommend|personali|ranking|machine learning|ml |data scien'),
 ('evaluate and improve LLM output quality', r'eval|quality|llm|applied ai|machine learning|research|alignment|safety'),
 ('python backend engineer APIs and databases', r'backend|back-end|software engineer|platform|infrastructure|api'),
 ('intern software engineering', r'intern'),
 ('machine learning intern', r'intern'),
 ('data engineer pipelines warehouse', r'data engineer|analytics engineer|data platform|data infra'),
 ('site reliability and cloud infrastructure', r'sre|reliab|infrastructure|devops|cloud|platform'),
 ('retrieval augmented generation applied AI', r'applied ai|ai engineer|llm|machine learning|solutions architect|forward deployed'),
 ('postgres sql database internals', r'database|storage|sql|data|backend'),
 ('security engineer application security', r'security|appsec|trust'),
 ('frontend react typescript engineer', r'front-?end|full[- ]?stack|ui |web|product engineer|software engineer'),
 ('mobile ios android developer', r'ios|android|mobile'),
 ('product designer', r'design'),
 ('enterprise sales account executive', r'account exec|sales|account manager|business development'),
 ('technical recruiter talent acquisition', r'recruit|talent'),
 ('data scientist experimentation analytics', r'data scien|analyt|research scien|economist|statistic'),
 ('forward deployed engineer customer solutions', r'forward deployed|solutions|customer engineer|implementation'),
 ('kubernetes docker deployment engineer', r'devops|infrastructure|platform|sre|reliab|cloud|software engineer'),
]
K = 8

def run(db, dense):
    s = Store(db); r = Retriever(s, dense=dense, inline_embed_limit=0)
    rows = []
    for q, rx in CASES:
        t = time.perf_counter(); res = r.search(Search(query=q, limit=K), Preferences()); ms = (time.perf_counter() - t) * 1000
        hits = [bool(re.search(rx, j['title'], re.I)) for j in res]
        rr = next((1 / (i + 1) for i, h in enumerate(hits) if h), 0)
        rows.append({'query': q, 'precision_at_8': sum(hits) / K, 'reciprocal_rank': rr, 'ms': round(ms, 1), 'top3': [f"{j['company']}: {j['title']}" for j in res[:3]]})
    ms = sorted(x['ms'] for x in rows)
    return {'mode': r.mode, 'index_size': len(r.jobs), 'dense_coverage': round(r.dense_coverage, 3), 'queries': len(rows),
            'mean_precision_at_8': round(statistics.mean(x['precision_at_8'] for x in rows), 4),
            'mrr': round(statistics.mean(x['reciprocal_rank'] for x in rows), 4),
            'p50_query_ms': ms[len(ms) // 2], 'max_query_ms': ms[-1], 'rows': rows}

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--database', required=True); p.add_argument('--output', default='docs/real-eval.json'); a = p.parse_args()
    out = {'caveat': 'Weak title-regex labels, 20 queries; compares modes, not absolute quality.', 'lexical': run(a.database, False), 'hybrid': run(a.database, True)}
    Path(a.output).write_text(json.dumps(out, indent=1) + '\n')
    for m in ('lexical', 'hybrid'): print(m, {k: v for k, v in out[m].items() if k != 'rows'})
