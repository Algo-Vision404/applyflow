from __future__ import annotations

from collections.abc import Callable

from applyflow.analyze import read_job
from applyflow.apply import apply_to_job, playwright_available
from applyflow.candidate import infer_candidate, resolve_search_level
from applyflow.career import classify_job
from applyflow.config import Profile
from applyflow.match import score_job
from applyflow.models import Job, Resume
from applyflow.sources import search_jobs
from applyflow.store import upsert_job
from applyflow.tailor import tailor_resume


def _default_query(resume: Resume, query: str) -> str:
    if query.strip():
        return query.strip()
    # One skill, in resume order — AND-ing the first two alphabetical skills
    # (e.g. "agile airflow") drops most real internships.
    return (resume.skills[0] if resume.skills else "").strip()


def discover_jobs(
    resume: Resume,
    profile: Profile,
    query: str = "",
    location: str = "",
    career_level: str | None = None,
    sources: list[str] | None = None,
    limit: int = 20,
    on_progress: Callable[[str], None] | None = None,
) -> list[Job]:
    requested = (career_level or "auto").lower()
    candidate = infer_candidate(resume, profile)
    career = resolve_search_level(requested, candidate)
    search_query = _default_query(resume, query)
    if on_progress:
        on_progress(candidate.summary or "Timeline unknown")
        on_progress(f"Eligible from resume: {candidate.target_label}")
        on_progress(f"Query: {search_query or '(all eligible)'}  |  searching as {career}")
    jobs = search_jobs(
        search_query,
        profile,
        location=location,
        sources=sources,
        limit=max(limit * 4, 40),
        career_level=career,
        include_presets=True,
        on_progress=on_progress,
        resume=resume,
    )
    if on_progress:
        on_progress(f"Scoring {len(jobs)} postings against your resume...")
    prepared: list[Job] = []
    for job in jobs:
        job.career_level = classify_job(job)
        job.score = score_job(job, resume, profile)
        job.id = upsert_job(job)
        prepared.append(job)
    prepared.sort(key=lambda j: -j.score)
    top = prepared[:limit]
    from applyflow.analyze import enrich_description

    for job in top:
        if len(job.description or "") < 350:
            if on_progress:
                on_progress(f"Reading JD: {job.title} @ {job.company}")
            job.description = enrich_description(job)
            job.score = score_job(job, resume, profile)
            if job.id is not None:
                upsert_job(job)
    top.sort(key=lambda j: -j.score)
    return top


def prepare_and_apply(
    job: Job,
    resume: Resume,
    profile: Profile,
    *,
    live: bool = False,
    fill: bool = True,
    submit: bool = False,
    tweak: bool = True,
    hold_for_review: bool = True,
):
    reading = read_job(job, resume)
    tailored = resume
    notes = reading.summary
    cover = ""
    if tweak:
        result = tailor_resume(job, resume, profile, reading)
        tailored = result.resume
        cover = result.cover_letter
        notes = result.notes
        if result.tweaked:
            job.tailored_path = str(result.path)
            if job.id is not None:
                upsert_job(job)

    use_browser = fill and not (job.apply_target().lower().startswith("mailto:"))
    if live and use_browser and not playwright_available():
        from applyflow.apply import ApplyResult
        from applyflow.browser import MISSING_PLAYWRIGHT

        result = ApplyResult(job, "failed", "browser", MISSING_PLAYWRIGHT)
        result.notes = f"{notes} | {result.notes}"
        return result, reading

    apply_result = apply_to_job(
        job,
        profile,
        tailored,
        live=live,
        browser=use_browser,
        submit=submit,
        cover_letter=cover,
        hold_for_review=hold_for_review,
    )
    apply_result.notes = f"{notes} | {apply_result.notes}"
    return apply_result, reading
