from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from applyflow.config import Profile
from applyflow.models import Job, Resume

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
EDU_HINTS = (
    "university", "college", "bachelor", "master", "gpa", "coursework",
    "high school", "education", "graduated", "dean", "thesis", "minor",
)
WORK_HINTS = (
    "intern", "internship", "co-op", "coop", "engineer", "developer",
    "research", "assistant", "analyst", "software", "swe", "sde",
)
INTERN_HINTS = ("intern", "internship", "co-op", "coop", "co op")
SEEK_INTERN = re.compile(r"seek(?:ing)?\b.{0,80}\b(?:intern(?:ship)?s?|co-ops?)", re.I)
SEEK_ENTRY = re.compile(
    r"seek(?:ing)?\b.{0,80}\b(?:entry[\s-]?level|new[\s-]?grad|junior|early[\s-]?career|full[\s-]?time)",
    re.I,
)
SEEK_SENIOR = re.compile(r"seek(?:ing)?\b.{0,80}\b(?:senior|staff|principal|lead)", re.I)


@dataclass
class Candidate:
    graduation_year: int | None = None
    graduation_month: int = 5
    months_until_grad: int | None = None
    in_school: bool = False
    internships: int = 0
    work_months: int = 0
    years_experience: float = 0.0
    stage: str = "early"  # intern | graduating | new_grad | junior | mid | senior
    recommended_search: str = "early"  # intern | early | mid | senior
    max_years_ok: float = 2.0
    summary: str = ""

    @property
    def bands(self) -> set[str]:
        """Job levels this resume can honestly target."""
        rec = self.recommended_search
        if rec == "intern":
            return {"intern"}
        if rec == "early":
            levels = {"early"}
            if self.could_intern:
                levels.add("intern")
            return levels
        if rec == "mid":
            return {"early", "mid"}
        if rec == "senior":
            return {"mid", "senior"}
        return {"early"}

    @property
    def target_label(self) -> str:
        names = {
            "intern": "internships",
            "early": "early-career / new-grad",
            "mid": "mid-level",
            "senior": "senior",
        }
        picked = [names[key] for key in ("intern", "early", "mid", "senior") if key in self.bands]
        return " + ".join(picked) or "early-career"

    @property
    def could_intern(self) -> bool:
        if self.months_until_grad is None:
            return self.years_experience < 4
        return self.months_until_grad >= -12

    @property
    def could_new_grad(self) -> bool:
        if self.months_until_grad is None:
            return self.years_experience < 4
        return -24 <= self.months_until_grad <= 14

    @property
    def could_full_time(self) -> bool:
        if self.months_until_grad is None:
            return True
        return self.months_until_grad <= 14


def infer_candidate(
    resume: Resume | None,
    profile: Profile | None = None,
    today: date | None = None,
) -> Candidate:
    text = resume.text if resume else ""
    return infer_from_text(text, profile, today)


def infer_from_text(
    text: str,
    profile: Profile | None = None,
    today: date | None = None,
) -> Candidate:
    today = today or date.today()
    grad_year, grad_month = _graduation(text, profile)
    work_months, internships = _work_history(text, today)
    years = round(work_months / 12.0, 1)
    months_until = None
    in_school = False
    if grad_year:
        grad_date = date(grad_year, min(max(grad_month, 1), 12), 15)
        months_until = (grad_date.year - today.year) * 12 + (grad_date.month - today.month)
        in_school = months_until > 0

    stage, recommended, max_years = _stage(months_until, years, internships, text)
    summary = _summary(grad_year, grad_month, months_until, internships, work_months, stage)
    return Candidate(
        graduation_year=grad_year,
        graduation_month=grad_month,
        months_until_grad=months_until,
        in_school=in_school,
        internships=internships,
        work_months=work_months,
        years_experience=years,
        stage=stage,
        recommended_search=recommended,
        max_years_ok=max_years,
        summary=summary,
    )


def resolve_search_level(requested: str, candidate: Candidate) -> str:
    level = (requested or "auto").lower().strip()
    if level in {"", "auto"}:
        return candidate.recommended_search
    return level


def intern_program_year(job: Job) -> int | None:
    for blob in (job.title or "", (job.description or "")[:1200]):
        year = _intern_year_in(blob)
        if year:
            return year
    return None


def intern_year_fits(job: Job, candidate: Candidate, today: date | None = None) -> bool:
    if not candidate.could_intern:
        return False
    year = intern_program_year(job)
    if year is None or candidate.graduation_year is None:
        return True
    today = today or date.today()
    low = candidate.graduation_year - 3
    high = candidate.graduation_year + 1
    if not candidate.in_school:
        high = min(high, today.year)
    return low <= year <= high


def timeline_score(job: Job, candidate: Candidate) -> int:
    """Adjust match score by graduation window and experience vs JD years."""
    from applyflow.career import classify_job, years_required

    level = classify_job(job)
    required = years_required(f"{job.title} {job.description[:4000]}")
    delta = 0
    if required is not None:
        if required > candidate.max_years_ok + 0.5:
            delta -= 35
        elif required <= candidate.years_experience + 1.5:
            delta += 8
    if level == "intern":
        if intern_year_fits(job, candidate):
            year = intern_program_year(job)
            if year and candidate.graduation_year and abs(year - candidate.graduation_year) <= 1:
                delta += 8
        else:
            delta -= 30
    elif level == "early" and candidate.in_school and (candidate.months_until_grad or 0) > 14:
        delta -= 28
    elif level == "early" and candidate.could_new_grad:
        delta += 6
    elif level == "mid" and candidate.in_school and (candidate.months_until_grad or 0) > 14:
        delta -= 22
    return delta


def explain_fit(job: Job, candidate: Candidate) -> str:
    from applyflow.career import classify_job, years_required

    level = classify_job(job)
    required = years_required(f"{job.title} {job.description[:2500]}")
    bits: list[str] = []
    if candidate.summary:
        bits.append(candidate.summary.split(" · ")[0])
    if level == "intern":
        year = intern_program_year(job)
        if year and candidate.graduation_year:
            if intern_year_fits(job, candidate):
                bits.append(f"intern {year} fits grad {candidate.graduation_year}")
            else:
                bits.append(f"intern {year} is outside your {candidate.graduation_year} window")
        elif candidate.could_intern:
            bits.append("internship fits while you are still in range")
        else:
            bits.append("internship is a weak fit after graduation")
    elif level == "early":
        bits.append("new-grad / junior window" if candidate.could_new_grad else "full-time may be early vs graduation")
    if required is not None:
        bits.append(
            f"JD asks {required}+ years; you show ~{candidate.years_experience:g}y dated experience"
        )
    return "; ".join(bits)


def _graduation(text: str, profile: Profile | None) -> tuple[int | None, int]:
    month = 5
    year: int | None = None
    if profile and profile.graduation_year:
        parsed = _parse_year_month(profile.graduation_year)
        if parsed[0]:
            year, month = parsed[0], parsed[1] or 5
    blob = text or ""
    patterns = [
        re.compile(
            rf"expected\s+(?P<mon>{MONTH_ALT})\.?\s+(?P<year>20\d{{2}})",
            re.I,
        ),
        re.compile(
            rf"(?:expected|expecting|anticipat\w*)\s+(?:to\s+)?(?:graduat\w*|graduation)\s*"
            rf"(?:in\s+|:\s*)?(?P<mon>{MONTH_ALT})?\.?\s*(?P<year>20\d{{2}})",
            re.I,
        ),
        re.compile(
            rf"graduat(?:ing|ion|e[sd]?)\s*(?:date\s*)?(?:in\s+|:\s*)?(?P<mon>{MONTH_ALT})?\.?\s*(?P<year>20\d{{2}})",
            re.I,
        ),
        re.compile(r"class of\s+(?P<year>20\d{2})", re.I),
        re.compile(
            rf"\b(?:bsc|b\.s\.|bachelor(?:'?s)?|msc|m\.s\.|master(?:'?s)?|ph\.?d\.?)\b"
            rf"[^0-9]{{0,80}}(?P<mon>{MONTH_ALT})?\.?\s*(?P<year>20\d{{2}})",
            re.I,
        ),
    ]
    found: list[tuple[int, int]] = []
    for pat in patterns:
        for m in pat.finditer(blob):
            y = int(m.group("year"))
            mon = MONTHS.get((m.groupdict().get("mon") or "").lower(), 0)
            found.append((y, mon or 5))
    if not year and found:
        # Latest dated graduation / expected date wins (MS after BS).
        year, month = max(found, key=lambda p: (p[0], p[1]))
    elif not year:
        edu_end = re.search(
            rf"(?:university|college|bachelor|education)[^0-9]{{0,80}}"
            rf"(20\d{{2}})\s*[-–—]\s*(20\d{{2}})",
            blob,
            re.I,
        )
        if edu_end:
            year = int(edu_end.group(2))
    return year, month


def _parse_year_month(value: str) -> tuple[int | None, int]:
    m = re.search(rf"(?P<mon>{MONTH_ALT})?\.?\s*(?P<year>20\d{{2}})", value or "", re.I)
    if not m:
        return None, 5
    mon = MONTHS.get((m.group("mon") or "").lower(), 0)
    return int(m.group("year")), mon or 5


def _work_history(text: str, today: date) -> tuple[int, int]:
    blob = text or ""
    ranges: list[tuple[date, date, bool]] = []
    month_range = re.compile(
        rf"(?P<m1>{MONTH_ALT})\.?\s+(?P<y1>20\d{{2}})\s*[-–—to]+\s*"
        rf"(?:(?P<present>present|current|now)|(?P<m2>{MONTH_ALT})\.?\s+(?P<y2>20\d{{2}}))",
        re.I,
    )
    for m in month_range.finditer(blob):
        start = date(int(m.group("y1")), MONTHS[m.group("m1").lower()], 1)
        if m.group("present"):
            end = today
        else:
            end = date(int(m.group("y2")), MONTHS[m.group("m2").lower()], 1)
        ctx = blob[max(0, m.start() - 140) : m.start()].lower()
        if _looks_education(ctx, start, end):
            continue
        intern = any(h in ctx or h in blob[m.start() : m.end() + 40].lower() for h in INTERN_HINTS)
        if intern or _looks_work(ctx):
            ranges.append((start, end, intern))

    summer = re.compile(rf"summer\s+(?P<year>20\d{{2}})", re.I)
    for m in summer.finditer(blob):
        ctx = blob[max(0, m.start() - 80) : m.end() + 40].lower()
        if any(h in ctx for h in INTERN_HINTS) or "intern" in ctx:
            y = int(m.group("year"))
            ranges.append((date(y, 6, 1), date(y, 8, 31), True))

    internships = 0
    months = 0
    seen: set[tuple[int, int, int, int]] = set()
    for start, end, intern in ranges:
        key = (start.year, start.month, end.year, end.month)
        if key in seen:
            continue
        seen.add(key)
        span = max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)
        span = min(span, 60)
        months += span
        if intern:
            internships += 1
    return months, internships


def _looks_education(ctx: str, start: date, end: date) -> bool:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months >= 20 and any(h in ctx for h in EDU_HINTS):
        return True
    return any(h in ctx for h in EDU_HINTS) and not any(h in ctx for h in INTERN_HINTS)


def _looks_work(ctx: str) -> bool:
    return any(h in ctx for h in WORK_HINTS)


def _intern_year_in(text: str) -> int | None:
    patterns = (
        rf"\b(?:summer|fall|winter|spring)\s+(20\d{{2}})\b",
        rf"\b(20\d{{2}})\s+(?:summer|fall|winter|spring)\s+intern",
        rf"\bintern(?:ship)?\b[^0-9]{{0,28}}(20\d{{2}})\b",
        rf"\b(20\d{{2}})\s+intern(?:ship)?\b",
    )
    for pat in patterns:
        m = re.search(pat, text or "", re.I)
        if m:
            year = int(m.group(1))
            if 2018 <= year <= 2040:
                return year
    return None


def _stage(
    months_until: int | None,
    years: float,
    internships: int,
    text: str,
) -> tuple[str, str, float]:
    lowered = (text or "").lower()
    studentish = any(
        h in lowered
        for h in ("intern", "student", "undergraduate", "gpa", "coursework", "expected graduation", "expected may")
    )
    wants_intern = bool(SEEK_INTERN.search(text or ""))
    wants_entry = bool(SEEK_ENTRY.search(text or ""))
    wants_senior = bool(SEEK_SENIOR.search(text or "")) and years >= 4

    if wants_senior or years >= 7:
        return "senior", "senior", max(years, 7.0)
    if years >= 3.5 and not (months_until is not None and months_until > 0):
        return "mid", "mid", max(5.0, years + 1.5)

    if months_until is not None:
        if months_until > 14 and not wants_entry:
            return "intern", "intern", max(1.0, years + 1.0)
        if months_until > 0 or wants_entry:
            return "graduating" if (months_until or 0) > 0 else "new_grad", "early", max(1.5, years + 1.5)
        if months_until >= -18:
            return "new_grad", "early", max(2.0, years + 2.0)
        if years < 3.5:
            return "junior", "early", max(3.0, years + 1.5)
        return "mid", "mid", max(4.0, years + 1.0)
    if wants_intern and not wants_entry:
        return "intern", "intern", max(1.0, years + 1.0)
    if studentish or internships or wants_entry:
        if wants_entry or internships:
            return "early", "early", max(1.5, years + 1.5)
        return "intern", "intern", max(1.0, years + 1.0)
    if years <= 2:
        return "early", "early", 2.5
    return "junior", "early", 3.5


def _summary(
    grad_year: int | None,
    grad_month: int,
    months_until: int | None,
    internships: int,
    work_months: int,
    stage: str,
) -> str:
    month_lookup = {}
    for name, num in MONTHS.items():
        if num not in month_lookup or len(name) > len(month_lookup[num]):
            month_lookup[num] = name.title()
    month_name = month_lookup.get(grad_month, "")
    parts: list[str] = []
    if stage == "intern":
        parts.append("student")
    elif stage == "graduating":
        parts.append("graduating soon")
    elif stage == "new_grad":
        parts.append("new grad")
    elif stage == "junior":
        parts.append("early-career")
    elif stage == "senior":
        parts.append("senior")
    elif stage == "mid":
        parts.append("mid-level")
    else:
        parts.append(stage)
    if grad_year:
        when = f"{month_name} {grad_year}".strip()
        if months_until is not None and months_until > 0:
            parts.append(f"expected {when} ({months_until} mo left)")
        elif months_until is not None:
            parts.append(f"graduated {when} ({abs(months_until)} mo ago)")
        else:
            parts.append(f"grad {when}")
    if internships:
        parts.append(f"{internships} internship" + ("s" if internships != 1 else ""))
    if work_months:
        parts.append(f"~{work_months} mo dated experience")
    return " · ".join(parts) or "experience timeline unknown"
