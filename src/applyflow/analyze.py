from __future__ import annotations

from dataclasses import dataclass, field

from applyflow.career import years_required
from applyflow.models import Job, Resume
from applyflow.resume import SKILL_HINTS, _has_skill
from applyflow.sources import USER_AGENT, _clean_html, _client, blocked_host


@dataclass
class JobRead:
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    matching: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    years: int | None = None
    degree: str = ""
    summary: str = ""
    needs_tweak: bool = False


def read_job(job: Job, resume: Resume, *, fetch: bool = True) -> JobRead:
    text = job.description or ""
    if fetch and len(text) < 400:
        text = enrich_description(job) or text
        if text and len(text) > len(job.description or ""):
            job.description = text

    hay = f"{job.title} {job.company} {text}".lower()
    found_skills = sorted({skill for skill in SKILL_HINTS if _has_skill(hay, skill)})
    resume_blob = f"{' '.join(resume.skills)} {resume.text}".lower()
    matching = [s for s in found_skills if _has_skill(resume_blob, s)]
    missing = [s for s in found_skills if s not in matching]

    years = years_required(hay)

    degree = ""
    if "ph.d" in hay or "phd" in hay:
        degree = "phd"
    elif "master" in hay or "ms " in hay or "m.s" in hay:
        degree = "masters"
    elif "bachelor" in hay or "bs " in hay or "b.s" in hay or "ba " in hay:
        degree = "bachelors"

    needs_tweak = bool(matching) and not _skills_already_front(resume, matching)
    summary = _summary(job, matching, missing, years)
    try:
        from applyflow.candidate import explain_fit, infer_candidate
        from applyflow.config import load_profile

        fit = explain_fit(job, infer_candidate(resume, load_profile()))
        if fit:
            summary = f"{summary}; {fit}"
    except Exception:
        pass
    return JobRead(
        must_have=found_skills[:12],
        matching=matching,
        missing=missing[:12],
        years=years,
        degree=degree,
        summary=summary,
        needs_tweak=needs_tweak,
    )


def enrich_description(job: Job) -> str:
    url = job.url or job.apply_url
    if not url.startswith("http"):
        return job.description or ""
    if blocked_host(url):
        return job.description or ""
    try:
        with _client() as client:
            resp = client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=12.0,
            )
            resp.raise_for_status()
            text = _clean_html(resp.text)
            return text[:12000] if text else (job.description or "")
    except Exception:
        return job.description or ""


def _skills_already_front(resume: Resume, matching: list[str]) -> bool:
    front = [s.lower() for s in resume.skills[:8]]
    return all(m.lower() in front for m in matching[:5]) if matching else True


def _summary(job: Job, matching: list[str], missing: list[str], years: int | None) -> str:
    bits = [f"{job.title} at {job.company}"]
    if matching:
        bits.append("resume already covers: " + ", ".join(matching[:8]))
    if missing:
        bits.append("not on resume (will not be invented): " + ", ".join(missing[:6]))
    if years:
        bits.append(f"posting mentions {years}+ years")
    return "; ".join(bits)
