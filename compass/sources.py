"""Fetch real postings from public applicant-tracking job-board APIs.

Only documented, unauthenticated GET endpoints that employers publish for job-board use:
Greenhouse Job Board API, Lever Postings API, Ashby Job Postings API. No HTML scraping,
no logins, no applying. Every record keeps its source board and the employer's own apply URL.
"""
import html
import re
import time
from datetime import datetime, timezone

import httpx

USER_AGENT = 'job-compass-portfolio-demo (+https://github.com/ankurrajpat/job-compass)'
ENDPOINTS = {
    'greenhouse': 'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true',
    'lever': 'https://api.lever.co/v0/postings/{slug}?mode=json',
    'ashby': 'https://api.ashbyhq.com/posting-api/job-board/{slug}',
}
MAX_DESCRIPTION = 6000

# Closed vocabulary: skills are only tagged when the posting text literally contains the term.
SKILLS = {
    'Python': r'python', 'SQL': r'sql', 'PostgreSQL': r'postgres(?:ql)?', 'MySQL': r'mysql', 'Redis': r'redis',
    'Kafka': r'kafka', 'Spark': r'(?:apache )?spark', 'Airflow': r'airflow', 'dbt': r'dbt', 'Snowflake': r'snowflake',
    'BigQuery': r'bigquery', 'Java': r'java(?!script)', 'JavaScript': r'javascript', 'TypeScript': r'typescript',
    'React': r'react(?:\.js)?', 'Node.js': r'node(?:\.js|js)', 'Go': r'golang', 'Rust': r'rust', 'Scala': r'scala',
    'Kotlin': r'kotlin', 'Swift': r'swift', 'C++': r'c\+\+', 'C#': r'c#', 'Ruby': r'ruby', 'Rails': r'rails',
    'PHP': r'php', 'Django': r'django', 'FastAPI': r'fastapi', 'Flask': r'flask', 'GraphQL': r'graphql',
    'REST APIs': r'rest(?:ful)? apis?', 'gRPC': r'grpc', 'Docker': r'docker', 'Kubernetes': r'kubernetes|k8s',
    'Terraform': r'terraform', 'AWS': r'aws|amazon web services', 'GCP': r'gcp|google cloud', 'Azure': r'azure',
    'Linux': r'linux', 'CI/CD': r'ci/cd', 'Git': r'git', 'PyTorch': r'pytorch', 'TensorFlow': r'tensorflow',
    'JAX': r'jax', 'scikit-learn': r'scikit-learn|sklearn', 'Pandas': r'pandas', 'NumPy': r'numpy',
    'LLMs': r'llms?|large language models?', 'RAG': r'rag|retrieval[- ]augmented', 'Embeddings': r'embeddings?',
    'Vector Search': r'vector (?:search|databases?|stores?)', 'Agents': r'ai agents?|llm agents?|agentic|autonomous agents?|multi-agent',
    'Prompt Engineering': r'prompt(?:ing| engineering)', 'Fine-tuning': r'fine-?tuning', 'Evals': r'llm evals?|evals|model evaluations?|evaluation (?:harness|framework|suite)s?',
    'NLP': r'nlp|natural language processing', 'Computer Vision': r'computer vision', 'Machine Learning': r'machine learning|\bml\b',
    'Deep Learning': r'deep learning', 'Recommender Systems': r'recommend(?:er|ation) systems?|recommendation', 'Ranking': r'ranking|learning to rank',
    'Search': r'search (?:relevance|ranking|infrastructure|engine)|information retrieval|elasticsearch|opensearch',
    'Data Engineering': r'data engineering|etl|data pipelines?', 'Observability': r'observability|prometheus|opentelemetry',
    'Security': r'application security|appsec|infosec|security engineer(?:ing)?|cybersecurity', 'Distributed Systems': r'distributed systems?', 'Microservices': r'microservices?',
    'iOS': r'ios', 'Android': r'android', 'Figma': r'figma', 'Tableau': r'tableau', 'Excel': r'excel',
    'A/B Testing': r'a/b test(?:ing|s)?|experimentation',
}
SKILL_RE = {k: re.compile(r'(?<![A-Za-z0-9+#.])(?:' + v + r')(?![A-Za-z0-9+#])', re.I) for k, v in SKILLS.items()}
# Short, case-ambiguous tokens must match case exactly to avoid "git" in "digital", "go" etc.
CASE_SENSITIVE = {'Go': r'\bGo\b(?= (?:services?|code|backend|programming)|,| and | or |/)', 'R': None}
TAG = re.compile(r'<[^>]+>')
BLOCK = re.compile(r'</?(?:p|div|br|li|ul|ol|h[1-6]|tr|section)[^>]*>', re.I)


def clean_text(raw):
    text = html.unescape(raw or '')
    text = BLOCK.sub('\n', text)
    text = TAG.sub(' ', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t\r\f\v\xa0]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()


def extract_skills(text):
    found = [name for name, rx in SKILL_RE.items() if rx.search(text)]
    if re.search(CASE_SENSITIVE['Go'], text):
        found.append('Go')
    return found[:30]


def infer_mode(*parts, declared=''):
    declared = (declared or '').lower().replace('-', '')
    if declared in ('remote', 'hybrid', 'onsite'):
        return declared
    blob = ' '.join(p for p in parts if p).lower()
    if 'hybrid' in blob:
        return 'hybrid'
    if 'remote' in blob:
        return 'remote'
    return 'onsite'


def _date(value):
    if value in (None, ''):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).strftime('%Y-%m-%d')
    return str(value)[:10]


def _slug(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '-', s)[:60]


def _finish(ats, slug, company, native_id, title, location, mode, text, when, url):
    text = clean_text(text)
    title = (title or '').strip()[:200]
    if not title or not native_id:
        return None
    description = text[:MAX_DESCRIPTION] or title
    skills = extract_skills(title + ' ' + text)
    if not skills:
        skills = ['General']
    return {
        'id': f'{ats[:2]}-{_slug(slug)}-{_slug(str(native_id))}'[:80],
        'title': title, 'company': company[:200], 'location': (location or 'Unspecified').strip()[:200] or 'Unspecified',
        'work_mode': mode, 'skills': skills, 'description': description,
        'source': f'{ats}:{slug}', 'updated_at': _date(when), 'url': url if (url or '').startswith('https://') else None,
    }


def parse_greenhouse(slug, company, data):
    out = []
    for j in data.get('jobs', []):
        loc = (j.get('location') or {}).get('name', '')
        out.append(_finish('greenhouse', slug, company, j.get('id'), j.get('title'), loc,
                           infer_mode(loc, j.get('title')), j.get('content', ''), j.get('updated_at'), j.get('absolute_url')))
    return [x for x in out if x]


def parse_lever(slug, company, data):
    out = []
    for j in data if isinstance(data, list) else []:
        cat = j.get('categories') or {}
        loc = cat.get('location') or ', '.join(cat.get('allLocations') or [])
        text = (j.get('descriptionPlain') or '') + '\n' + '\n'.join(
            f"{l.get('text', '')}\n{clean_text(l.get('content', ''))}" for l in j.get('lists') or []) + '\n' + (j.get('additionalPlain') or '')
        out.append(_finish('lever', slug, company, j.get('id'), j.get('text'), loc,
                           infer_mode(loc, j.get('text'), declared=j.get('workplaceType')), text, j.get('createdAt'), j.get('hostedUrl')))
    return [x for x in out if x]


def parse_ashby(slug, company, data):
    out = []
    for j in data.get('jobs', []):
        if j.get('isListed') is False:
            continue
        loc = j.get('location') or ''
        if j.get('isRemote') and 'remote' not in loc.lower():
            loc = (loc + ' (Remote)').strip()
        out.append(_finish('ashby', slug, company, j.get('id'), j.get('title'), loc,
                           infer_mode(loc, j.get('title'), declared=j.get('workplaceType') or ('remote' if j.get('isRemote') else '')),
                           j.get('descriptionPlain') or j.get('descriptionHtml') or '', j.get('publishedAt'), j.get('jobUrl')))
    return [x for x in out if x]


PARSERS = {'greenhouse': parse_greenhouse, 'lever': parse_lever, 'ashby': parse_ashby}


def fetch_board(client, ats, slug, company):
    """Return all current postings for one board. Raises on any HTTP/parse failure, so a failed
    fetch can never be mistaken for 'every role closed'."""
    r = client.get(ENDPOINTS[ats].format(slug=slug))
    r.raise_for_status()
    return PARSERS[ats](slug, company, r.json())


def make_client():
    return httpx.Client(timeout=60, headers={'User-Agent': USER_AGENT}, follow_redirects=True)


def polite_sleep(seconds=0.5):
    time.sleep(seconds)
