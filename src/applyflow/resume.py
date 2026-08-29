from __future__ import annotations

import re
import shutil
from pathlib import Path

from applyflow.config import RESUME_DIR, ensure_app_dir, load_profile, save_profile
from applyflow.models import Resume

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}")
LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[\w\-/%]+", re.I)
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[\w\-]+", re.I)
SCHOOL_RE = re.compile(
    r"\b(?:University of [A-Z][A-Za-z .'-]{2,48}|"
    r"[A-Z][A-Za-z][A-Za-z .'-]{2,48}(?:University|College|Polytechnic|Institute of Technology))\b"
)

SKILL_HINTS = {
    "python", "javascript", "typescript", "java", "kotlin", "swift", "go", "golang",
    "rust", "c++", "c#", "ruby", "php", "scala", "r", "sql", "nosql", "graphql",
    "react", "vue", "angular", "next.js", "node", "node.js", "django", "flask",
    "fastapi", "spring", "rails", "laravel", "aws", "gcp", "azure", "docker",
    "kubernetes", "k8s", "terraform", "ansible", "linux", "git", "ci/cd",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "pandas", "numpy", "pytorch", "tensorflow", "sklearn", "spark", "airflow",
    "hadoop", "kafka", "snowflake", "dbt", "looker", "tableau", "powerbi",
    "html", "css", "sass", "tailwind", "figma", "excel", "salesforce",
    "rest", "grpc", "microservices", "agile", "scrum", "jira", "figma",
    "machine learning", "deep learning", "nlp", "llm", "data science",
    "product management", "project management", "customer success",
}


def save_resume(src: Path) -> Path:
    ensure_app_dir()
    src = src.expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Resume not found: {src}")
    suffix = src.suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise ValueError("Resume must be PDF, DOCX, TXT, or MD")
    dest = RESUME_DIR / f"resume{suffix}"
    for old in RESUME_DIR.glob("*"):
        if old != dest:
            old.unlink(missing_ok=True)
    shutil.copy2(src, dest)
    profile = load_profile()
    profile.resume_path = str(dest)
    save_profile(profile)
    return dest


def parse_resume(path: Path | None = None) -> Resume:
    profile = load_profile()
    resume_path = path or profile.resume_file()
    if not resume_path:
        raise FileNotFoundError("No resume uploaded. Run: applyflow resume set <file>")
    text = extract_text(Path(resume_path))
    emails = sorted(set(EMAIL_RE.findall(text)))
    phones = sorted({re.sub(r"\s+", " ", p).strip() for p in PHONE_RE.findall(text)})
    skills = _detected_skills(text)
    extra = _keywords_from_text(text)
    keywords = sorted(set(skills) | extra | set(profile.keywords))
    from applyflow.candidate import infer_from_text

    timeline = infer_from_text(text, profile)
    first, last = extract_name(text)
    school = extract_school(text)
    linkedin = (LINKEDIN_RE.findall(text) or [""])[0]
    github = (GITHUB_RE.findall(text) or [""])[0]
    resume = Resume(
        path=str(resume_path),
        text=text,
        emails=emails,
        phones=phones,
        skills=skills,
        keywords=keywords,
        graduation_year=str(timeline.graduation_year or profile.graduation_year or ""),
        experience_months=timeline.work_months,
        internships=timeline.internships,
        stage=timeline.stage,
        timeline=timeline.summary,
        school=school,
        linkedin=linkedin,
        github=github,
        first_name=first,
        last_name=last,
    )
    _backfill_profile(profile, resume)
    return resume


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(path)
    if suffix == ".docx":
        return _docx_text(path)
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _has_skill(text: str, skill: str) -> bool:
    if any(ch in skill for ch in " .+#/"):
        return skill in text
    return re.search(rf"(?<![A-Za-z]){re.escape(skill)}(?![A-Za-z])", text) is not None


def _detected_skills(text: str) -> list[str]:
    lowered = text.lower()
    found = [skill for skill in SKILL_HINTS if _has_skill(lowered, skill)]

    def first_pos(skill: str) -> int:
        needle = skill.lower()
        if any(ch in needle for ch in " .+#/"):
            idx = lowered.find(needle)
            return idx if idx >= 0 else 10**9
        m = re.search(rf"(?<![A-Za-z]){re.escape(needle)}(?![A-Za-z])", lowered)
        return m.start() if m else 10**9

    found.sort(key=first_pos)
    return found


def _keywords_from_text(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z+#.]{1,}", text.lower())
    stop = {
        "and", "the", "with", "for", "that", "this", "from", "have", "has",
        "were", "was", "are", "been", "will", "your", "you", "our", "their",
        "experience", "years", "work", "working", "using", "used", "team",
        "skills", "education", "university", "college", "bachelor", "master",
        "responsible", "including", "ability", "strong", "knowledge",
    }
    counts: dict[str, int] = {}
    for token in tokens:
        if token in stop or len(token) < 3:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts, key=counts.get, reverse=True)
    return set(ranked[:40])


def extract_name(text: str) -> tuple[str, str]:
    for line in (text or "").splitlines()[:8]:
        line = re.sub(r"\s+", " ", line).strip()
        if not line or "@" in line or any(ch.isdigit() for ch in line):
            continue
        lowered = line.lower()
        if "linkedin" in lowered or "github" in lowered or "http" in lowered:
            continue
        parts = [p for p in re.split(r"[\s,|]+", line) if p.isalpha()]
        if 2 <= len(parts) <= 4:
            return parts[0].title(), " ".join(p.title() for p in parts[1:])
    return "", ""


def extract_school(text: str) -> str:
    head = (text or "")[:2500]
    match = SCHOOL_RE.search(head)
    if not match:
        return ""
    school = re.sub(r"\s+", " ", match.group(0)).strip(" ,.-")
    if len(school) < 8:
        return ""
    return school


def _backfill_profile(profile, resume: Resume) -> None:
    changed = False
    if not profile.school and resume.school:
        profile.school = resume.school
        changed = True
    if not profile.graduation_year and resume.graduation_year:
        profile.graduation_year = resume.graduation_year
        changed = True
    if not profile.linkedin and resume.linkedin:
        profile.linkedin = resume.linkedin
        changed = True
    if not profile.github and resume.github:
        profile.github = resume.github
        changed = True
    if changed:
        save_profile(profile)
