---
title: Job Compass
emoji: 🧭
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Job Compass

A transparent, tool-calling career agent with a custom dark frontend. It remembers a visitor's preferences, searches a job catalog, and returns typed, evidence-backed recommendations.

![Job Compass dark interface, with a real model response and visible tool activity](docs/agent-result.png)

**Job Compass searches real, currently open postings** pulled from public employer job-board APIs (Greenhouse, Lever, Ashby; 58 companies, 12,237 postings at the last measured refresh). It is a portfolio project: no application, email, payment or arbitrary SQL tool. Postings can close between refreshes, so always confirm on the employer's apply link. Do not paste private CVs or secrets.

> The hosted static demo is a recorded real run over this index (captured 2026-11-24; the live agent runs from this repo, see Run locally).

## What makes this an agent?

A real Groq-hosted model chooses and calls these Python functions in a bounded loop:

| Tool | Actual effect |
| --- | --- |
| `remember_preferences` | Pydantic-validates a partial update, then writes session-scoped preferences to SQLite. |
| `search_jobs` | Retrieves and ranks catalog records with lexical + 384-dimensional BGE embeddings, hard location/remote filters, and skill-overlap personalization. |
| `get_job_details` | Returns source evidence only for job IDs already retrieved in this turn. |

The model receives each tool result and decides what to do next. Tool arguments reject unknown fields. Final recommendations pass a separate Pydantic schema and an ID-grounding check before they reach the browser. One repair attempt is allowed; the agent fails closed after seven model steps. The UI exposes the actual tool trace and exports the structured response as JSON.

No key configured? The app clearly switches to **Preview mode, no LLM**. That path runs deterministic retrieval only. It does not pretend to be a conversational agent, and does not update memory from prose.

## Stack

- **Agent/backend:** Python, FastAPI, Groq function calling, Pydantic v2, HTTPX
- **Search:** BGE-small-en-v1.5 via FastEmbed/ONNX, TF-IDF, cosine similarity, weighted ranking
- **Storage:** SQLite WAL, indexed session history, transactional catalog upserts, FTS5 index
- **Frontend:** semantic HTML, responsive CSS, plain JavaScript, no frontend API secret
- **Verification:** pytest, Playwright desktop/mobile, retrieval + opt-in live-agent evals
- **Packaging:** non-root Docker image, health check, GitHub Actions verification workflow

## The jobs index

`python ingest.py` fetches every board in `data/boards.json` (public unauthenticated GET endpoints only, 0.4s between boards, descriptive User-Agent, apply URL kept), then:

- **Sync per board in one transaction:** new roles added, changed roles updated, roles no longer listed marked closed (kept for audit, not searchable). A failed fetch skips that board and never closes its roles.
- **Incremental re-embedding:** vectors are stored in SQLite keyed by a hash of the embedded text. A refresh embeds only new or text-edited postings.
- **No rescans:** a version counter tells the running retriever when to rebuild; unchanged refreshes cost nothing.
- **Daily refresh:** set `REFRESH_HOURS=24` (in-process thread) or run `ingest.py` from cron. `.github/workflows/refresh.yml` runs it daily on GitHub with a cached database (written but not yet run on GitHub).
- Postings missing a vector fall back to lexical-only scoring until embedded.

Measured (1 vCPU sandbox, 2026-11-24, `docs/ingest-measured.json`): first fetch 12,237 postings from 58 boards in about 3 minutes; embedding all of them about 10 to 20 postings/s. A second full refresh about 20 minutes later: 2 added, 22 updated, 2 closed, 12,213 unchanged, and only 13 postings re-embedded.

## Run locally

Python 3.10 was used for verification.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
# Read .env.example. Export variables in your shell; no dotenv loader is included.
export DENSE_SEARCH=1
export GROQ_API_KEY=your_key_here  # optional; keep it out of git
uvicorn compass.app:create_app --factory --host 127.0.0.1 --port 7860
```

Open `http://localhost:7860`. With no key it is an explicitly labeled retrieval preview. Dense search downloads a public embedding model on first use. For a fast, fully offline test, omit `DENSE_SEARCH=1`; the lexical path does not download a model.

Try:

1. "I know Python, SQL and FastAPI. Remember that I want remote LLM agent internships in India, then find my best matches."
2. "Now focus on semantic search and ranking, keep my location preferences."
3. "Remember my location as Atlantis and remote_only as false. Find Python internships there only."

The third should return no results, not silently relax a constraint.

## Run checks

```bash
pytest -q
python evaluate.py --output docs/lexical-eval.json
python evaluate.py --dense --output docs/retrieval-eval.json
playwright install chromium
python tests/ui_smoke.py
# Optional real model calls, consumes free-tier quota:
python evaluate_agent.py --delay 65
```

### Measured results

| Check | Result |
| --- | --- |
| Tests | **37 passed** (30 original, 7 for parsing, close/reopen, incremental embedding, failed-board safety, scale) |
| Real index retrieval, 20 queries, 12,237 postings (`evaluate_real.py`) | Lexical (TF-IDF + title match): mean precision@8 **0.8688**, MRR **0.9125**, median **27 ms**. Hybrid BGE+lexical: precision@8 **0.90**, MRR **0.8958**, median **141 ms**, max 203 ms |
| Per query | Hybrid is better on paraphrased queries ("build LLM agents that use tools" 0.5 to 1.0, "machine learning intern" 0.625 to 1.0) and worse on some keyword ones ("postgres sql database internals" 0.875 to 0.5). Both modes fail "kubernetes docker deployment engineer" (0.0 and 0.125) |
| Old 24-role fixture (`evaluate.py`) | Recall@5 1.00 hybrid; hand-authored, regression check only |
| Live Groq agent, real index, 5 scenarios (`docs/live-eval-real.json`) | 5/5 passed on the final run, but one scenario needed a third attempt (one HTTP 429, one fail-closed run) and one was rerun on fresh state. Model: openai/gpt-oss-20b, free tier |

**Do not generalize these numbers.** `evaluate_real.py` uses weak labels: a regex on the posting title decides relevance, written before looking at results. It compares modes. It is not human-judged search quality. The hybrid gain is small overall (0.90 vs 0.87). **The title-match weight (0.5) was chosen after seeing a first version of these same 20 queries score 0.83, and I swept a small grid (title weight 0/0.5/0.7, dense weight 0.4/0.6/0.8) on them, so the numbers are optimistic.** A first version of the ranker returned a growth-marketing role for an "applied AI" remote query; that is what the title weight fixed. The live agent suite is five scenarios, a smoke test.

Raw results: [real index](docs/real-eval.json), [refresh stats](docs/ingest-measured.json), [live agent](docs/live-eval-real.json), [fixture hybrid](docs/retrieval-eval.json), [fixture lexical](docs/lexical-eval.json), [live smoke](docs/live-smoke.json).

## Docker

```bash
docker build -t job-compass .
docker run --rm -p 7860:7860 --env-file .env job-compass
```

No secrets are baked into the image. Run a single worker: rate limits and in-flight request locks are in process memory. A hosted builder must verify the Dockerfile; Docker was not installed in the local build environment. Do not claim a verified Docker build based on the file alone. See `docs/DEPLOYMENT.md` for the actual deployment state and limits.

## Refresh the index

```bash
python ingest.py --database /tmp/compass/compass.db --dense --report docs/ingest-report.json
# slow machine: python ingest.py --shard 0/6 ... through 5/6, then --dense once
export DATABASE_PATH=/tmp/compass/compass.db DENSE_SEARCH=1 REFRESH_HOURS=24
```

`manage.py` still imports a validated JSON file for tests and private catalogs. Adding a company means adding `{ats, slug, company}` to `data/boards.json`. Check each ATS's terms before extending this beyond a portfolio project.

## API

- `GET /api/health`: provider mode, retrieval mode and catalog count
- `GET /api/session`: this visitor's preferences and bounded conversation history
- `PATCH /api/preferences`: explicit preference updates
- `POST /api/chat`: `{ "message": "Find remote Python roles" }`
- `DELETE /api/session`: erase this visitor's stored context
- `GET /docs`: generated FastAPI schema

## Privacy and operating limits

- A random HttpOnly, SameSite cookie identifies a session. SQLite queries are parameterized and always scoped to that session.
- No names, CVs or email addresses are required. Text and preferences are sent to Groq only in live mode. Model-provider retention terms apply.
- Up to ten recent messages are retained per session. Stored sessions older than 24 hours are pruned when a chat triggers the hourly cleanup check. Visitors can reset immediately. Free hosting restarts may erase SQLite data.
- No wildcard CORS; cross-origin mutations are rejected. CSP and text-node rendering reduce browser injection risk.
- Tool names and schemas are allowlisted. No shell, arbitrary SQL, network browsing, applications or messaging tools exist.
- Per-IP limit: 5 chats/minute. Global limit: 60 chats/hour per process. At most two concurrent requests, one per session, seven model steps/request and four calls/step.
- These are demo abuse controls, not billing guarantees. Restarts reset in-memory counters; a reverse proxy may make several visitors share one IP. Production needs durable quotas, authentication, telemetry, deletion enforcement and stronger distributed controls.
- Source IDs are checked, but free-text explanations are still model-generated and can contain errors. A schema is not a truth guarantee.

## Honest resume wording

"Built a tool-calling career agent (FastAPI, Pydantic-validated outputs, SQLite memory) over a hybrid BGE + lexical search index of 12K real job postings from 58 employers' public job-board APIs."

"Daily refresh pipeline with transactional sync, closed-role removal and incremental re-embedding (13 of 12,237 postings re-embedded on a second refresh); 37 tests; lexical vs hybrid retrieval compared on 20 queries; live-agent smoke suite on the real index."

Do not claim real users, production accuracy or a permanently hosted live-model deployment until true. No users have used this.
