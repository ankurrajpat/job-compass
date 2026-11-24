"""ASGI service. Public demo: no account, no private CVs, no outbound actions."""
import os
import re
import time
import uuid
import threading
from collections import defaultdict, deque
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .schemas import Chat, Remember
from .store import Store
from .retrieval import Retriever
from .agent import Agent, Groq, AgentError, demo
from .refresher import start_refresher

ROOT=Path(__file__).resolve().parent.parent

def create_app(db_path=None, provider=None, dense=None, seed=None):
    app=FastAPI(title='Job Compass API',version='1.0.0')
    store=Store(db_path or os.getenv('DATABASE_PATH','/tmp/compass/compass.db'),seed)
    retriever=Retriever(store,dense=(os.getenv('DENSE_SEARCH','0')=='1') if dense is None else dense)
    key=os.getenv('GROQ_API_KEY','')
    provider=provider or (Groq(key,os.getenv('GROQ_MODEL','openai/gpt-oss-20b')) if key else None)
    agent=Agent(store,retriever,provider) if provider else None
    app.state.store=store; app.state.retriever=retriever
    refresh_hours=float(os.getenv('REFRESH_HOURS','0'))
    if refresh_hours>0: start_refresher(store,refresh_hours,dense=retriever.encoder is not None)
    calls=defaultdict(deque); gate=threading.Lock(); active=set(); total=0; last_prune=0
    budget=int(os.getenv('MAX_CHAT_PER_HOUR','60'))
    global_calls=deque()

    @app.middleware('http')
    async def headers(request,call_next):
        # Same-origin only for mutations; no CORS. Also rejects cross-site forms.
        origin=request.headers.get('origin')
        host=request.headers.get('host','')
        if request.method in ('POST','DELETE','PATCH') and origin and origin not in (f'https://{host}',f'http://{host}'):
            return JSONResponse({'detail':'Cross-origin request rejected'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site' and request.method!='GET':
            return JSONResponse({'detail':'Cross-site request rejected'},status_code=403)
        sid=request.cookies.get('compass_session','')
        fresh=not re.fullmatch(r'[a-f0-9]{32}',sid)
        request.state.sid=uuid.uuid4().hex if fresh else sid
        response=await call_next(request)
        if fresh:
            response.set_cookie('compass_session',request.state.sid,httponly=True,samesite='lax',secure=request.url.scheme=='https',max_age=86400)
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://huggingface.co; base-uri 'none'; form-action 'self'"})
        return response

    @app.get('/api/health')
    def health():
        return {'status':'ok','provider':'groq' if agent else 'preview','retrieval_mode':retriever.mode,'job_count':len(retriever.jobs),'dense_coverage':round(retriever.dense_coverage,3),'index':store.counts(),'last_refresh':store.meta('last_refresh'),'catalog':'real postings from public employer job-board APIs (Greenhouse, Lever, Ashby)'}

    @app.get('/api/session')
    def session(request:Request):
        return {'preferences':store.preferences(request.state.sid).model_dump(),'history':store.history(request.state.sid)}

    @app.patch('/api/preferences')
    def preferences(body:Remember,request:Request):
        return store.remember(request.state.sid,body)

    @app.delete('/api/session')
    def clear(request:Request):
        store.clear(request.state.sid)
        return {'cleared':True}

    @app.post('/api/chat')
    def chat(body:Chat,request:Request):
        nonlocal last_prune
        sid=request.state.sid; now=time.monotonic()
        ip=request.client.host if request.client else 'unknown'
        with gate:
            # Per-IP + global limits prevent cookie rotation bypassing the API budget.
            while global_calls and now-global_calls[0]>3600: global_calls.popleft()
            recent=calls[ip]
            while recent and now-recent[0]>60: recent.popleft()
            if len(recent)>=5 or len(global_calls)>=budget:
                raise HTTPException(429,'Demo request limit reached. Please try later.')
            if sid in active: raise HTTPException(409,'A request is already running for this session.')
            if len(active)>=2: raise HTTPException(429,'Demo is busy. Please try shortly.')
            recent.append(now);global_calls.append(now);active.add(sid)
            if now-last_prune>3600:
                store.prune();last_prune=now
                for k in list(calls):
                    if calls[k] and now-calls[k][-1]>3600: del calls[k]
        try:
            return agent.run(sid,body.message) if agent else demo(store,retriever,sid,body.message)
        except AgentError as e:
            raise HTTPException(502,str(e))
        except Exception:
            # Never return provider payloads, credentials or stack traces to clients.
            raise HTTPException(503,'The agent is temporarily unavailable. Your request did not send an application.')
        finally:
            with gate: active.discard(sid)

    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    @app.get('/')
    def home(): return FileResponse(ROOT/'static/index.html')
    return app
