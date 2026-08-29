from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from applyflow.analyze import JobRead
from applyflow.config import APP_DIR, Profile, ensure_app_dir
from applyflow.models import Job, Resume

TAILORED_DIR = APP_DIR / "tailored"


@dataclass
class TailorResult:
    resume: Resume
    path: Path
    tweaked: bool
    notes: str
    cover_letter: str


def tailor_resume(job: Job, resume: Resume, profile: Profile, reading: JobRead) -> TailorResult:
    """Rewrite emphasis only. Never add skills or jobs that are not on the original resume."""
    ensure_app_dir()
    out_dir = TAILORED_DIR / str(job.id or job.external_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not reading.needs_tweak:
        notes = (
            "Resume already emphasizes the overlapping skills."
            if reading.matching
            else "No overlapping skills to emphasize; original resume kept."
        )
        return TailorResult(
            resume=resume,
            path=Path(resume.path),
            tweaked=False,
            notes=notes,
            cover_letter=_cover(job, resume, profile, reading),
        )

    original = resume.text.strip()
    matching = reading.matching
    missing = reading.missing
    summary = _targeted_summary(job, profile, matching, original)
    skills_line = _skills_line(resume, matching)
    body = _strip_leading_skills(original)

    parts = [
        profile.full_name or _guess_name(original),
        " | ".join(x for x in [profile.email, profile.phone, profile.linkedin, profile.github] if x),
        "",
        "TARGETED SUMMARY",
        summary,
        "",
        "SKILLS",
        skills_line,
        "",
        "EXPERIENCE AND EDUCATION",
        body,
    ]
    tailored_text = re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip() + "\n"

    txt_path = out_dir / "resume.txt"
    docx_path = out_dir / "resume.docx"
    txt_path.write_text(tailored_text, encoding="utf-8")
    _write_docx(docx_path, tailored_text)
    notes_path = out_dir / "notes.txt"
    notes = (
        f"Tweaked for {job.title} @ {job.company}\n"
        f"Emphasized: {', '.join(matching) or '(none)'}\n"
        f"Left off the resume (not claimed): {', '.join(missing) or '(none)'}\n"
    )
    notes_path.write_text(notes, encoding="utf-8")

    new_resume = resume.model_copy(
        update={
            "path": str(docx_path),
            "text": tailored_text,
            "skills": matching + [s for s in resume.skills if s not in matching],
            "keywords": sorted(set(resume.keywords) | set(matching)),
        }
    )
    return TailorResult(
        resume=new_resume,
        path=docx_path,
        tweaked=True,
        notes=notes.strip(),
        cover_letter=_cover(job, new_resume, profile, reading),
    )


def _targeted_summary(job: Job, profile: Profile, matching: list[str], original: str) -> str:
    name = profile.full_name or "I"
    skills = ", ".join(matching[:8]) or "the experience on my resume"
    return (
        f"{name} is applying for the {job.title} role at {job.company}. "
        f"Relevant strengths already on this resume include {skills}. "
        "The experience and education below are unchanged; skills that match this posting are listed first."
    )


def _skills_line(resume: Resume, matching: list[str]) -> str:
    ordered = list(dict.fromkeys([*matching, *resume.skills]))
    return ", ".join(ordered) if ordered else "(see original resume)"


def _strip_leading_skills(text: str) -> str:
    lines = text.splitlines()
    skip = {"skills", "technical skills", "core skills", "technologies"}
    out: list[str] = []
    dropping = False
    for i, line in enumerate(lines):
        if line.strip().lower() in skip:
            dropping = True
            continue
        if dropping and line.strip() and not line.strip().endswith(":") and i < 8:
            continue
        dropping = False
        out.append(line)
    return "\n".join(out).strip() or text


def _guess_name(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:80]
    return "Applicant"


def _cover(job: Job, resume: Resume, profile: Profile, reading: JobRead) -> str:
    skills = ", ".join(reading.matching[:8] or resume.skills[:8]) or "relevant experience"
    return (
        f"Hi {job.company} team,\n\n"
        f"I am applying for the {job.title} role. My resume highlights {skills}, "
        "which already appear in my experience.\n\n"
        "Thank you for your consideration.\n\n"
        f"{profile.full_name or 'Applicant'}\n{profile.email}\n{profile.phone}"
    ).strip()


def _write_docx(path: Path, text: str) -> None:
    from docx import Document

    doc = Document()
    for block in text.split("\n"):
        doc.add_paragraph(block)
    doc.save(str(path))
