"""Daily refresh: fetch every configured public job board, sync the index, embed only what changed.

    python ingest.py --database /data/compass.db --dense --report docs/ingest-report.json

A board whose fetch fails is skipped and keeps its existing rows. Roles are only marked closed
when a board was fetched successfully and no longer lists them."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from compass.store import Store
from compass import sources

def run(database, boards_file='data/boards.json', dense=False, delay=0.4, limit_boards=None, only=None, shard=None, log=print):
    store = Store(database)
    boards = json.loads(Path(boards_file).read_text())
    if only: boards = [b for b in boards if f"{b['ats']}:{b['slug']}" in only]
    if shard: i, n = map(int, shard.split('/')); boards = boards[i::n]
    if limit_boards: boards = boards[:limit_boards]
    t0 = time.perf_counter()
    report = {'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'boards': [], 'totals': dict(added=0, updated=0, unchanged=0, reopened=0, closed=0, fetched=0)}
    with sources.make_client() as client:
        for b in boards:
            src = f"{b['ats']}:{b['slug']}"; tick = time.perf_counter()
            try:
                jobs = sources.fetch_board(client, b['ats'], b['slug'], b['company'])
                dupes = len(jobs) - len({j['id'] for j in jobs})
                if dupes: seen = {}; jobs = list({j['id']: j for j in jobs}.values())
                st = store.sync(src, jobs)
                row = {'source': src, 'fetched': len(jobs), **st, 'seconds': round(time.perf_counter() - tick, 1)}
                for k in ('added', 'updated', 'unchanged', 'reopened', 'closed'): report['totals'][k] += st[k]
                report['totals']['fetched'] += len(jobs)
            except Exception as e:  # keep existing rows for this board
                row = {'source': src, 'error': f'{type(e).__name__}: {str(e)[:120]}'}
            report['boards'].append(row); log(json.dumps(row))
            sources.polite_sleep(delay)
    report['fetch_seconds'] = round(time.perf_counter() - t0, 1)
    report['boards_failed'] = sum('error' in r for r in report['boards'])
    report['dropped_vectors_for_closed_roles'] = store.drop_inactive_vectors()
    if dense:
        from compass.indexing import make_encoder, embed_missing
        tick = time.perf_counter(); enc = make_encoder()
        n = embed_missing(store, enc, progress=lambda d, t: log(f'embedded {d}/{t}') if d % 1024 < 128 else None)
        report['embedded_this_run'] = n; report['embed_seconds'] = round(time.perf_counter() - tick, 1)
    report['index'] = store.counts()
    report['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    store.set_meta('last_refresh', {k: report[k] for k in ('finished_at', 'totals', 'boards_failed')})
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--database', default='/tmp/compass/compass.db'); p.add_argument('--boards', default='data/boards.json')
    p.add_argument('--dense', action='store_true'); p.add_argument('--report'); p.add_argument('--limit-boards', type=int); p.add_argument('--shard', help='i/n: process every n-th board starting at i (for slow machines)')
    a = p.parse_args()
    rep = run(a.database, a.boards, a.dense, limit_boards=a.limit_boards, shard=a.shard)
    if a.report: Path(a.report).write_text(json.dumps(rep, indent=1) + '\n')
    print(json.dumps({k: v for k, v in rep.items() if k != 'boards'}, indent=1))
    sys.exit(1 if rep['boards_failed'] > len(rep['boards']) / 2 else 0)
