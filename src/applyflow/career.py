from __future__ import annotations

import re

from applyflow.candidate import infer_candidate, intern_year_fits
from applyflow.config import Profile
from applyflow.models import Job, Resume

INTERN_RE = re.compile(
    r"\b(?:interns?|internships?|co-ops?|coops?|undergraduates?|undergrads?)\b",
    re.I,
)
EARLY_RE = re.compile(
    r"\b(?:new[\s-]?grads?|university grads?|early[\s-]?career|juniors?|jr\.?|"
    r"entry[\s-]?level|associates?|apprentices?|graduate programs?|campus)\b",
    re.I,
)
NEW_GRAD_RE = re.compile(
    r"\b(?:new[\s-]?grads?|university grads?|recent grads?|early[\s-]?career|"
    r"graduate programs?)\b",
    re.I,
)
SENIOR_RE = re.compile(
    r"\b(?:seniors?|staff|principals?|directors?|vice presidents?|vps?|"
    r"heads? of|distinguished|fellows?|managers?|tech leads?|architects?)\b",
    re.I,
)
def classify_job(job: Job) -> str:
    """Classify from the title first so JD words like internal/international do not mislead."""
    title = job.title or ""
    if INTERN_RE.search(title):
        return "intern"
    if SENIOR_RE.search(title):
        return "senior"
    if EARLY_RE.search(title):
        return "early"
    years = years_required(f"{title} {job.description[:2000]}")
    if years is not None and years >= 5:
        return "senior"
    if years is not None and years <= 2:
        return "early"
    return "mid"


def classify_resume(resume: Resume, profile: Profile | None = None) -> str:
    candidate = infer_candidate(resume, profile)
    return candidate.recommended_search


def job_fits_candidate(job: Job, candidate, override: str | None = None) -> bool:
    """Whether this posting matches intern / early / mid / senior inferred from the resume."""
    rec = (override or candidate.recommended_search or "early").lower()
    if rec == "intern":
        bands = {"intern"}
    elif rec == "early":
        bands = {"early"}
        if candidate.could_intern:
            bands.add("intern")
    elif rec == "mid":
        bands = {"early", "mid"}
    elif rec == "senior":
        bands = {"mid", "senior"}
    else:
        bands = set(candidate.bands)

    job_level = classify_job(job)
    years = years_required(f"{job.title} {job.description[:4000]}")
    if years is not None and years > candidate.max_years_ok + 1 and "senior" not in bands:
        return False
    if job_level == "intern":
        return "intern" in bands and intern_year_fits(job, candidate)
    if job_level == "senior":
        return "senior" in bands
    if job_level == "early":
        if "early" not in bands and "mid" not in bands:
            return False
        if NEW_GRAD_RE.search(job.title or "") and not candidate.could_new_grad:
            return False
        return True
    if job_level == "mid":
        if "mid" in bands:
            return True
        if "early" in bands:
            return candidate.could_full_time and (years is None or years <= candidate.max_years_ok)
        return False
    return False


_YEARS_RE = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)\b", re.I)


def years_required(text: str) -> int | None:
    """Years of experience demanded by a posting, not company age or '10 years ago'."""
    blob = text or ""
    matches: list[int] = []
    for m in _YEARS_RE.finditer(blob):
        rest = blob[m.end() : m.end() + 12]
        if re.match(r"\s*(?:ago|old)\b", rest, re.I):
            continue
        matches.append(int(m.group(1)))
    return max(matches) if matches else None


def eligible_for_profile(
    job: Job,
    career_level: str,
    resume: Resume | None = None,
    profile: Profile | None = None,
) -> bool:
    """Keep roles that fit intern / early / mid / senior as read from the resume."""
    level = (career_level or "auto").lower()
    if level == "any":
        return True
    candidate = infer_candidate(resume, profile) if resume is not None else None
    if candidate is not None:
        override = None if level in {"", "auto"} else level
        return job_fits_candidate(job, candidate, override=override)

    job_level = classify_job(job)
    years = years_required(f"{job.title} {job.description[:4000]}")
    if job_level == "senior" or (years is not None and years >= 5):
        return False
    if level == "intern":
        return job_level == "intern"
    if job_level in {"intern", "early"}:
        return True
    if years is not None and years <= 3:
        return True
    return job_level == "mid"
