# Deployment

## State at handoff

- Local app, live Groq calls, dense retrieval, desktop/mobile browser interactions and backend tests have been verified.
- No GitHub repository was pushed. The owner will publish the repository himself.
- A free Hugging Face hosting account was created, but publication of the source and use of a server-side Groq secret on a public service require the owner's separate approval.
- No Docker engine was available locally. The Dockerfile and CI build steps are included, but a successful hosted container build must be verified before calling Docker deployment complete.
- A live vacancy index exists (public job-board APIs, `ingest.py`). The hosted static demo is still the older replay on fixtures. No real users are claimed.
- A fresh container has an empty index until `ingest.py` (or REFRESH_HOURS) populates it: about 3 minutes to fetch and 10 to 20 minutes to embed on 1 vCPU.

## Free Hugging Face Docker Space

1. Create a Docker Space on the free CPU tier. A free public Space also makes its uploaded source public. Review all files first. Do not upload `.env`, a virtualenv, databases or credentials.
2. Upload the project files and folders, keeping their relative paths. `README.md` includes the Space metadata and port 7860.
3. Without `GROQ_API_KEY`, the app is a clearly labeled retrieval preview. This works without consuming API quota. It is not a live conversational LLM demo.
4. Only with the owner's approval, add `GROQ_API_KEY` under the Space's **Secrets**, not Variables and not a committed file. Set `GROQ_MODEL=openai/gpt-oss-20b` as a Variable if that model remains available. Never print or export the secret in build output.
5. Keep `MAX_CHAT_PER_HOUR` at or below 60, a single worker, and the free hardware tier. The included limits are process-local and reset on restart; they are not a hard account quota guarantee. Lower to 10 for a low-traffic portfolio demo.
6. Wait for the image to finish building. Read runtime logs and `/api/health`. A running page alone does not prove model calls work.
7. Test a real prompt, a preference-preserving follow-up, tool activity, JSON download and mobile layout on the actual hosted URL. Check that no secret appears in the page, repository or JSON responses.
8. Record the verified URL and build result here. Do not call a preview-only deployment a live LLM agent.

## Host-independent checks

```bash
docker build -t job-compass .
docker run --rm -p 7860:7860 --env-file .env job-compass
curl http://localhost:7860/api/health
```

`DATABASE_PATH` defaults to temporary storage. Free hosting may sleep or restart and lose memory. Never promise durable user accounts on this setup.

## Before calling it production

Add authentication, durable distributed quotas, a managed database, privacy/retention controls, a source-permitted live feed, incremental vector indexing, metrics/tracing with redaction, dependency/security scans and load testing. Gather real user feedback before claiming adoption.
