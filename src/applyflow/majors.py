from __future__ import annotations

import re
from html import unescape

import httpx

from applyflow.models import Job

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 18.0


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()

GOOGLE_JOB_RE = re.compile(r"jobs/results/(\d+)-([a-z0-9-]+)", re.I)
APPLE_JOB_RE = re.compile(r"/en-us/details/(\d+)/([a-z0-9-]+)", re.I)


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/json"},
        follow_redirects=True,
    )


def _slug_title(slug: str) -> str:
    text = unescape(slug.replace("-", " ")).strip()
    return " ".join(w.upper() if w in {"phd", "ai", "ml", "sre", "ios"} else w.capitalize() for w in text.split())


def search_major_companies(query: str, career_level: str = "early") -> list[Job]:
    jobs: list[Job] = []
    q = (query or "").strip()
    if (career_level or "").lower() == "intern" and "intern" not in q.lower():
        search = f"{q} intern".strip()
    else:
        search = q or "intern"
    fetchers = (
        lambda: search_amazon(search),
        lambda: search_google(search),
        lambda: search_apple(search),
    )
    for fn in fetchers:
        try:
            jobs.extend(fn())
        except Exception:
            continue
    return jobs


def search_amazon(query: str) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    with _client() as client:
        for q in _amazon_queries(query):
            resp = client.get(
                "https://www.amazon.jobs/en/search.json",
                params={"base_query": q, "result_limit": 40, "offset": 0},
            )
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            for row in payload.get("jobs") or []:
                job_id = str(row.get("id_icims") or row.get("id") or "")
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                path = str(row.get("job_path") or "")
                url = f"https://www.amazon.jobs{path}" if path.startswith("/") else path
                loc_parts = [row.get("city"), row.get("state"), row.get("country_code")]
                loc = ", ".join(str(p) for p in loc_parts if p)
                jobs.append(
                    Job(
                        external_id=job_id,
                        source="amazon",
                        title=str(row.get("title") or "Untitled"),
                        company="Amazon",
                        location=loc,
                        url=url,
                        apply_url=url,
                        description=_clean_html(str(row.get("description") or row.get("basic_qualifications") or "")),
                        tags=[str(row.get("job_category") or "")],
                        ats="amazon",
                        posted_at=str(row.get("posted_date") or ""),
                    )
                )
    return jobs


def _amazon_queries(query: str) -> list[str]:
    q = (query or "software").strip()
    out = [q]
    if "intern" not in q.lower():
        out.append(f"{q} intern")
    return list(dict.fromkeys(out))


def parse_google_jobs(html: str) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for job_id, slug in GOOGLE_JOB_RE.findall(html or ""):
        if job_id in seen:
            continue
        seen.add(job_id)
        path = f"jobs/results/{job_id}-{slug}"
        url = "https://www.google.com/about/careers/applications/" + path
        jobs.append(
            Job(
                external_id=job_id,
                source="google",
                title=_slug_title(slug),
                company="Google",
                location="",
                url=url,
                apply_url=url,
                description="",
                tags=["google"],
                ats="google",
            )
        )
    return jobs


def search_google(query: str) -> list[Job]:
    with _client() as client:
        resp = client.get(
            "https://www.google.com/about/careers/applications/jobs/results/",
            params={"q": query or "intern"},
        )
        resp.raise_for_status()
        return parse_google_jobs(resp.text)


def parse_apple_jobs(html: str) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for job_id, slug in APPLE_JOB_RE.findall(html or ""):
        if job_id in seen:
            continue
        seen.add(job_id)
        url = f"https://jobs.apple.com/en-us/details/{job_id}/{slug}"
        jobs.append(
            Job(
                external_id=job_id,
                source="apple",
                title=_slug_title(slug),
                company="Apple",
                location="",
                url=url,
                apply_url=url,
                description="",
                tags=["apple"],
                ats="apple",
            )
        )
    return jobs


def search_apple(query: str) -> list[Job]:
    with _client() as client:
        resp = client.get(
            "https://jobs.apple.com/en-us/search",
            params={"search": query or "intern", "sort": "newest"},
        )
        resp.raise_for_status()
        return parse_apple_jobs(resp.text)
