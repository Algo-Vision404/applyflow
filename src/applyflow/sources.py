from __future__ import annotations

import hashlib
import re
from html import unescape
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx

from applyflow.companies import PRESET_ASHBY, PRESET_GREENHOUSE, PRESET_LEVER
from applyflow.config import Profile
from applyflow.majors import search_amazon, search_apple, search_google
from applyflow.models import Job

USER_AGENT = "Applyflow/0.1 (personal job search CLI; +https://github.com)"
TIMEOUT = 10.0


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _id(source: str, *parts: str) -> str:
    raw = "|".join([source, *parts])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def blocked_host(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    blocked = (
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "ziprecruiter.com",
        "facebook.com",
        "instagram.com",
    )
    for item in blocked:
        if host == item or host.endswith("." + item):
            return item
    return ""


def detect_ats(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    path = urlparse(url or "").path.lower()
    if "greenhouse.io" in host or "greenhouse" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "workable.com" in host:
        return "workable"
    if "myworkdayjobs.com" in host or "workday" in host:
        return "workday"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "icims.com" in host:
        return "icims"
    if "taleo.net" in host:
        return "taleo"
    if path.startswith("mailto:") or (url or "").startswith("mailto:"):
        return "email"
    return ""


def search_jobs(
    query: str,
    profile: Profile,
    location: str = "",
    sources: list[str] | None = None,
    limit: int = 40,
    career_level: str = "early",
    include_presets: bool = True,
    on_progress: Callable[[str], None] | None = None,
    resume=None,
) -> list[Job]:
    search_level = career_level
    if resume is not None:
        from applyflow.candidate import infer_candidate, resolve_search_level

        search_level = resolve_search_level(career_level, infer_candidate(resume, profile))
    wanted = {s.strip().lower() for s in (sources or []) if s.strip()}
    all_sources: dict[str, Callable[[], list[Job]]] = {
        "remoteok": lambda: search_remoteok(query),
        "remotive": lambda: search_remotive(query) + search_remotive(_career_query(search_level, query)),
        "arbeitnow": lambda: search_arbeitnow(query, location),
        "jobicy": lambda: search_jobicy(query),
        "themuse": lambda: search_themuse(query, search_level),
        "himalayas": lambda: search_himalayas(query),
        "greenhouse": lambda: search_greenhouse_boards(profile, query, include_presets=include_presets),
        "lever": lambda: search_lever_boards(profile, query, include_presets=include_presets),
        "ashby": lambda: search_ashby_boards(profile, query, include_presets=include_presets),
        "amazon": lambda: search_amazon(_career_query(search_level, query)),
        "google": lambda: search_google(_career_query(search_level, query)),
        "apple": lambda: search_apple(_career_query(search_level, query)),
        "usajobs": lambda: search_usajobs(query, profile, location),
        "adzuna": lambda: search_adzuna(query, profile, location),
    }
    names = wanted or {
        "remoteok",
        "remotive",
        "arbeitnow",
        "jobicy",
        "themuse",
        "himalayas",
        "greenhouse",
        "lever",
        "ashby",
        "amazon",
        "google",
        "apple",
    }
    jobs: list[Job] = []

    def _run(name: str, fn: Callable[[], list[Job]]) -> tuple[str, list[Job]]:
        if on_progress:
            on_progress(f"Searching {name}...")
        return name, fn()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_run, name, all_sources[name]) for name in names if name in all_sources]
        for fut in as_completed(futs):
            try:
                name, found = fut.result()
                jobs.extend(found)
                if on_progress:
                    on_progress(f"{name}: {len(found)} postings")
            except Exception as exc:
                if on_progress:
                    on_progress(f"source failed: {exc}")
                continue
    if location:
        loc = location.lower()
        jobs = [
            j
            for j in jobs
            if loc in j.location.lower() or "remote" in j.location.lower() or loc in j.title.lower()
        ]
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        key = f"{job.company.lower()}|{job.title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    if query.strip():
        unique = filter_query(unique, query)
    if search_level and search_level != "any":
        from applyflow.career import eligible_for_profile

        unique = [
            j
            for j in unique
            if eligible_for_profile(j, search_level, resume=resume, profile=profile)
        ]
    return unique[: max(limit, 1)]


def _career_query(career_level: str, query: str) -> str:
    level = (career_level or "early").lower()
    q = (query or "").strip()
    if level in {"any", "mid", "senior"}:
        return q
    if "intern" in q.lower():
        return q
    return f"{q} intern".strip()


def search_remoteok(query: str) -> list[Job]:
    with _client() as client:
        resp = client.get("https://remoteok.com/api")
        resp.raise_for_status()
        rows = resp.json()
    q = query.lower()
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not row.get("position"):
            continue
        blob = " ".join(
            [
                str(row.get("position") or ""),
                str(row.get("company") or ""),
                " ".join(row.get("tags") or []),
                _clean_html(str(row.get("description") or "")),
            ]
        ).lower()
        if q and q not in blob:
            continue
        url = str(row.get("url") or row.get("apply_url") or "")
        jobs.append(
            Job(
                external_id=str(row["id"]),
                source="remoteok",
                title=row["position"],
                company=str(row.get("company") or "Unknown"),
                location=str(row.get("location") or "Remote"),
                url=url,
                apply_url=str(row.get("apply_url") or url),
                description=_clean_html(str(row.get("description") or "")),
                tags=[str(t) for t in (row.get("tags") or [])],
                ats=detect_ats(str(row.get("apply_url") or url)),
                posted_at=str(row.get("date") or ""),
            )
        )
    return jobs


def search_remotive(query: str) -> list[Job]:
    with _client() as client:
        resp = client.get("https://remotive.com/api/remote-jobs", params={"search": query})
        resp.raise_for_status()
        payload = resp.json()
    jobs: list[Job] = []
    for row in payload.get("jobs") or []:
        url = str(row.get("url") or "")
        jobs.append(
            Job(
                external_id=str(row.get("id") or _id("remotive", url)),
                source="remotive",
                title=str(row.get("title") or "Untitled"),
                company=str(row.get("company_name") or "Unknown"),
                location=str(row.get("candidate_required_location") or "Remote"),
                url=url,
                apply_url=url,
                description=_clean_html(str(row.get("description") or "")),
                tags=[str(t) for t in (row.get("tags") or [])],
                ats=detect_ats(url),
                posted_at=str(row.get("publication_date") or ""),
            )
        )
    return jobs


def search_arbeitnow(query: str, location: str = "") -> list[Job]:
    with _client() as client:
        resp = client.get("https://www.arbeitnow.com/api/job-board-api")
        resp.raise_for_status()
        payload = resp.json()
    q = query.lower()
    loc = location.lower()
    jobs: list[Job] = []
    for row in payload.get("data") or []:
        blob = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("company_name") or ""),
                " ".join(row.get("tags") or []),
                _clean_html(str(row.get("description") or "")),
            ]
        ).lower()
        if q and q not in blob:
            continue
        place = str(row.get("location") or "")
        if loc and loc not in place.lower() and not row.get("remote"):
            continue
        url = str(row.get("url") or "")
        jobs.append(
            Job(
                external_id=str(row.get("slug") or _id("arbeitnow", url)),
                source="arbeitnow",
                title=str(row.get("title") or "Untitled"),
                company=str(row.get("company_name") or "Unknown"),
                location=place or ("Remote" if row.get("remote") else ""),
                url=url,
                apply_url=url,
                description=_clean_html(str(row.get("description") or "")),
                tags=[str(t) for t in (row.get("tags") or [])],
                ats=detect_ats(url),
                posted_at=str(row.get("created_at") or ""),
            )
        )
    return jobs


def search_jobicy(query: str) -> list[Job]:
    params: dict[str, str | int] = {"count": 100}
    if query.strip() and " " not in query.strip():
        params["tag"] = query.strip()
    with _client() as client:
        resp = client.get("https://jobicy.com/api/v2/remote-jobs", params=params)
        resp.raise_for_status()
        payload = resp.json()
    jobs: list[Job] = []
    for row in payload.get("jobs") or []:
        url = str(row.get("url") or "")
        jobs.append(
            Job(
                external_id=str(row.get("id") or _id("jobicy", url)),
                source="jobicy",
                title=str(row.get("jobTitle") or "Untitled"),
                company=str(row.get("companyName") or "Unknown"),
                location=str(row.get("jobGeo") or "Remote"),
                url=url,
                apply_url=url,
                description=_clean_html(str(row.get("jobDescription") or "")),
                tags=[str(t) for t in (row.get("jobTags") or [])] if isinstance(row.get("jobTags"), list) else [],
                ats=detect_ats(url),
                posted_at=str(row.get("pubDate") or ""),
            )
        )
    return jobs


def search_themuse(query: str, career_level: str = "early") -> list[Job]:
    level = (career_level or "early").lower()
    if level == "any":
        categories = ["Computer and IT", "Data and Analytics", "Engineering"]
    elif level == "intern":
        categories = ["Internship"]
    elif level in {"mid", "senior"}:
        categories = ["Computer and IT", "Data and Analytics", "Engineering"]
    else:
        categories = ["Internship", "Early Career"]
    jobs: list[Job] = []
    with _client() as client:
        for category in categories:
            resp = client.get(
                "https://www.themuse.com/api/public/jobs",
                params={"page": 0, "descending": "true", "category": category},
            )
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            for row in payload.get("results") or []:
                locs = row.get("locations") or []
                loc = ", ".join(str(x.get("name") or "") for x in locs if isinstance(x, dict))
                refs = row.get("refs") or {}
                url = str(refs.get("landing_page") or "")
                company = str((row.get("company") or {}).get("name") or "Unknown")
                jobs.append(
                    Job(
                        external_id=str(row.get("id") or _id("themuse", url)),
                        source="themuse",
                        title=str(row.get("name") or "Untitled"),
                        company=company,
                        location=loc,
                        url=url,
                        apply_url=url,
                        description=_clean_html(str(row.get("contents") or "")),
                        tags=[str(c.get("name") or "") for c in (row.get("categories") or []) if isinstance(c, dict)],
                        ats=detect_ats(url),
                        posted_at=str(row.get("publication_date") or ""),
                    )
                )
    return jobs


def search_himalayas(query: str) -> list[Job]:
    with _client() as client:
        resp = client.get("https://himalayas.app/jobs/api", params={"limit": 100})
        resp.raise_for_status()
        payload = resp.json()
    rows = payload.get("jobs") or payload if isinstance(payload, list) else payload.get("data") or []
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or "")
        if not title:
            continue
        url = str(row.get("applicationUrl") or row.get("url") or row.get("excerptUrl") or "")
        jobs.append(
            Job(
                external_id=str(row.get("guid") or row.get("id") or _id("himalayas", url, title)),
                source="himalayas",
                title=title,
                company=str(row.get("companyName") or row.get("company") or "Unknown"),
                location=str(row.get("location") or "Remote"),
                url=url,
                apply_url=url,
                description=_clean_html(str(row.get("description") or row.get("excerpt") or "")),
                tags=[str(t) for t in (row.get("parentCategories") or row.get("categories") or [])][:8]
                if isinstance(row.get("parentCategories") or row.get("categories"), list)
                else [],
                ats=detect_ats(url),
                posted_at=str(row.get("pubDate") or row.get("postedAt") or ""),
            )
        )
    return jobs


def search_usajobs(query: str, profile: Profile, location: str = "") -> list[Job]:
    if not profile.usajobs_key or not profile.usajobs_email:
        return []
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": profile.usajobs_email,
        "Authorization-Key": profile.usajobs_key,
    }
    params = {"Keyword": query, "ResultsPerPage": 25}
    if location:
        params["LocationName"] = location
    with _client() as client:
        resp = client.get("https://data.usajobs.gov/api/search", headers=headers, params=params)
        resp.raise_for_status()
        payload = resp.json()
    jobs: list[Job] = []
    items = (
        (((payload.get("SearchResult") or {}).get("SearchResultItems")) or [])
    )
    for item in items:
        desc = item.get("MatchedObjectDescriptor") or {}
        loc_list = desc.get("PositionLocationDisplay") or ""
        apply_uris = desc.get("ApplyURI") or []
        if isinstance(apply_uris, str):
            apply_uris = [apply_uris]
        url = str(desc.get("PositionURI") or (apply_uris[0] if apply_uris else ""))
        apply_url = apply_uris[0] if apply_uris else url
        jobs.append(
            Job(
                external_id=str(item.get("MatchedObjectId") or _id("usajobs", url)),
                source="usajobs",
                title=str(desc.get("PositionTitle") or "Untitled"),
                company=str(desc.get("OrganizationName") or "USAJobs"),
                location=str(loc_list),
                url=url,
                apply_url=str(apply_url),
                description=_clean_html(str(desc.get("UserArea", {}).get("Details", {}).get("JobSummary") or "")),
                tags=[],
                ats="usajobs",
                posted_at=str(desc.get("PublicationStartDate") or ""),
            )
        )
    return jobs


def search_adzuna(query: str, profile: Profile, location: str = "") -> list[Job]:
    if not profile.adzuna_app_id or not profile.adzuna_app_key:
        return []
    country = profile.adzuna_country or "us"
    params = {
        "app_id": profile.adzuna_app_id,
        "app_key": profile.adzuna_app_key,
        "what": query,
        "results_per_page": 25,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    with _client() as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    jobs: list[Job] = []
    for row in payload.get("results") or []:
        job_url = str(row.get("redirect_url") or "")
        jobs.append(
            Job(
                external_id=str(row.get("id") or _id("adzuna", job_url)),
                source="adzuna",
                title=str(row.get("title") or "Untitled"),
                company=str((row.get("company") or {}).get("display_name") or "Unknown"),
                location=str((row.get("location") or {}).get("display_name") or ""),
                url=job_url,
                apply_url=job_url,
                description=_clean_html(str(row.get("description") or "")),
                tags=[],
                ats=detect_ats(job_url),
                posted_at=str(row.get("created") or ""),
            )
        )
    return jobs


def _fetch_json(url: str, params: dict | None = None) -> object:
    with _client() as client:
        resp = client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


def search_greenhouse_boards(profile: Profile, query: str, include_presets: bool = False) -> list[Job]:
    jobs: list[Job] = []
    q = query.lower()
    tokens = [(b.token.strip(), b.label or b.token) for b in profile.boards if b.kind == "greenhouse"]
    if include_presets:
        have = {t for t, _ in tokens}
        tokens.extend((tok, tok) for tok in PRESET_GREENHOUSE if tok not in have)

    def one(token: str, label: str) -> list[Job]:
        payload = _fetch_json(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            {"content": "true"} if not include_presets else {},
        )
        if not isinstance(payload, dict):
            return []
        found: list[Job] = []
        for row in (payload or {}).get("jobs") or []:
            title = str(row.get("title") or "")
            loc = str((row.get("location") or {}).get("name") or "")
            abs_url = str(row.get("absolute_url") or "")
            blob = f"{title} {loc} {_clean_html(str(row.get('content') or ''))}".lower()
            if q and not all(term in blob for term in q.split()):
                continue
            found.append(
                Job(
                    external_id=str(row.get("id") or _id("greenhouse", token, abs_url)),
                    source=f"greenhouse:{token}",
                    title=title or "Untitled",
                    company=label,
                    location=loc,
                    url=abs_url,
                    apply_url=abs_url,
                    description=_clean_html(str(row.get("content") or "")),
                    tags=[],
                    ats="greenhouse",
                    posted_at=str(row.get("updated_at") or ""),
                )
            )
        return found

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(one, token, label) for token, label in tokens]
        for fut in as_completed(futs):
            try:
                jobs.extend(fut.result())
            except Exception:
                continue
    return jobs


def search_lever_boards(profile: Profile, query: str, include_presets: bool = False) -> list[Job]:
    jobs: list[Job] = []
    q = query.lower()
    tokens = [(b.token.strip(), b.label or b.token) for b in profile.boards if b.kind == "lever"]
    if include_presets:
        have = {t for t, _ in tokens}
        tokens.extend((tok, tok) for tok in PRESET_LEVER if tok not in have)
    for token, label in tokens:
        try:
            with _client() as client:
                resp = client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
                resp.raise_for_status()
                rows = resp.json()
        except Exception:
            continue
        for row in rows:
            title = str(row.get("text") or "")
            cats = row.get("categories") or {}
            loc = str(cats.get("location") or "")
            url = str(row.get("hostedUrl") or row.get("applyUrl") or "")
            desc = _clean_html(str((row.get("descriptionPlain") or row.get("description") or "")))
            blob = f"{title} {loc} {desc}".lower()
            if q and not all(term in blob for term in q.split()):
                continue
            jobs.append(
                Job(
                    external_id=str(row.get("id") or _id("lever", token, url)),
                    source=f"lever:{token}",
                    title=title or "Untitled",
                    company=label,
                    location=loc,
                    url=url,
                    apply_url=str(row.get("applyUrl") or url),
                    description=desc,
                    tags=[str(cats.get("team") or ""), str(cats.get("commitment") or "")],
                    ats="lever",
                    posted_at=str(row.get("createdAt") or ""),
                )
            )
    return jobs


def search_ashby_boards(profile: Profile, query: str, include_presets: bool = False) -> list[Job]:
    jobs: list[Job] = []
    q = query.lower()
    tokens = [(b.token.strip(), b.label or b.token) for b in profile.boards if b.kind == "ashby"]
    if include_presets:
        have = {t for t, _ in tokens}
        tokens.extend((tok, tok) for tok in PRESET_ASHBY if tok not in have)
    for token, label in tokens:
        try:
            with _client() as client:
                resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
                resp.raise_for_status()
                payload = resp.json()
        except Exception:
            continue
        for row in payload.get("jobs") or []:
            title = str(row.get("title") or "")
            loc = str(row.get("location") or "")
            url = str(row.get("jobUrl") or "")
            desc = _clean_html(str(row.get("descriptionHtml") or row.get("descriptionPlain") or ""))
            blob = f"{title} {loc} {desc}".lower()
            if q and not all(term in blob for term in q.split()):
                continue
            jobs.append(
                Job(
                    external_id=str(row.get("id") or _id("ashby", token, url)),
                    source=f"ashby:{token}",
                    title=title or "Untitled",
                    company=label,
                    location=loc,
                    url=url,
                    apply_url=url,
                    description=desc,
                    tags=[],
                    ats="ashby",
                    posted_at=str(row.get("publishedAt") or ""),
                )
            )
    return jobs


def filter_query(jobs: Iterable[Job], query: str) -> list[Job]:
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return list(jobs)
    matched: list[Job] = []
    for job in jobs:
        hay = " ".join(
            [job.title, job.company, job.location, " ".join(job.tags), job.description[:5000]]
        ).lower()
        if all(term in hay for term in terms):
            matched.append(job)
    return matched
