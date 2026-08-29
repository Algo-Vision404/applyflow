from __future__ import annotations

import re

from applyflow.config import Profile
from applyflow.models import Job, Resume
from applyflow.resume import _has_skill


def score_job(job: Job, resume: Resume, profile: Profile) -> int:
    haystack = " ".join(
        [
            job.title,
            job.company,
            job.location,
            " ".join(job.tags),
            job.description[:8000],
        ]
    ).lower()

    for banned in profile.exclude_keywords:
        if banned.strip() and banned.lower() in haystack:
            return 0

    terms = {t.lower() for t in resume.skills if t}
    if profile.keywords:
        terms |= {t.lower() for t in profile.keywords}

    if not terms:
        return 10 if job.title else 0

    hits = 0
    weighted = 0
    title = job.title.lower()
    for term in terms:
        if _has_skill(haystack, term):
            hits += 1
            weighted += 3 if _has_skill(title, term) else 1

    coverage = hits / max(len(terms), 1)
    score = int(min(100, coverage * 70 + weighted * 2 + min(len(job.tags), 10)))
    if profile.location and profile.location.lower() in (job.location or "").lower():
        score = min(100, score + 8)
    if "remote" in (job.location or "").lower() or "remote" in title:
        score = min(100, score + 4)

    job_level = None
    try:
        from applyflow.candidate import infer_candidate, timeline_score
        from applyflow.career import classify_job, classify_resume

        job_level = classify_job(job)
        resume_level = classify_resume(resume, profile)
        if job_level == "intern":
            score = min(100, score + (18 if resume_level == "intern" else 10))
        elif job_level == "early":
            score = min(100, score + 10)
        elif job_level == "senior":
            score = max(0, score - 30)
        score = max(0, min(100, score + timeline_score(job, infer_candidate(resume, profile))))
    except Exception:
        pass
    return score


def render_cover_letter(job: Job, resume: Resume, profile: Profile) -> str:
    skills = ", ".join(resume.skills[:8]) or "relevant experience"
    template = profile.cover_letter_template or "Hello, I am applying for {title} at {company}."
    text = template.format(
        company=job.company or "the company",
        title=job.title,
        skills=skills,
        full_name=profile.full_name or "Applicant",
        email=profile.email,
        phone=profile.phone,
        location=profile.location,
        linkedin=profile.linkedin,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()
