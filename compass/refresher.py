"""Optional in-process daily refresh (REFRESH_HOURS>0). Runs the same code as ingest.py in a daemon
thread: fetch boards, sync, embed only changed postings. Search keeps serving the old index meanwhile."""
import logging
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger('compass.refresh')

def _due(store, hours):
    last = store.meta('last_refresh')
    if not last: return True
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last['finished_at'])).total_seconds() / 3600
    return age >= hours

def start_refresher(store, hours, dense=False):
    import ingest
    def loop():
        while True:
            try:
                if _due(store, hours):
                    rep = ingest.run(store.path, dense=dense, log=lambda *_: None)
                    log.info('refresh done: %s', rep['totals'])
            except Exception:
                log.exception('refresh failed; keeping previous index')
            time.sleep(900)
    t = threading.Thread(target=loop, daemon=True, name='compass-refresh'); t.start(); return t
