from __future__ import annotations

import smtplib
import time
import webbrowser
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import unquote, urlparse

from applyflow.config import Profile
from applyflow.match import render_cover_letter
from applyflow.models import Job, Resume
from applyflow.sources import blocked_host
from applyflow.store import already_applied, record_application


class ApplyResult:
    def __init__(self, job: Job, status: str, method: str, notes: str = ""):
        self.job = job
        self.status = status
        self.method = method
        self.notes = notes

    @property
    def ok(self) -> bool:
        return self.status in {"applied", "submitted", "opened", "queued"}


def apply_to_job(
    job: Job,
    profile: Profile,
    resume: Resume,
    *,
    live: bool = False,
    browser: bool = False,
    submit: bool = False,
    cover_letter: str = "",
    hold_for_review: bool = True,
) -> ApplyResult:
    if job.id is not None and already_applied(job.id):
        return ApplyResult(job, "skipped", "none", "already applied")

    target = job.apply_target()
    method = _choose_method(target, job.ats, browser)

    if not live:
        notes = f"dry-run via {method}: {target}"
        if job.id is not None:
            record_application(job.id, "dry-run", method, notes)
        return ApplyResult(job, "dry-run", method, notes)

    if method == "email":
        result = _apply_email(job, profile, resume, target)
    elif method == "browser":
        result = _apply_browser(
            job,
            profile,
            resume,
            target,
            submit=submit,
            cover_letter=cover_letter,
            hold_for_review=hold_for_review,
        )
    else:
        webbrowser.open(target)
        result = ApplyResult(job, "opened", "browser-tab", f"opened {target}")

    if job.id is not None:
        record_application(job.id, result.status, result.method, result.notes)
    return result


def apply_many(
    jobs: list[Job],
    profile: Profile,
    resume: Resume,
    *,
    live: bool = False,
    browser: bool = False,
    submit: bool = False,
    delay_seconds: float = 2.0,
) -> list[ApplyResult]:
    results: list[ApplyResult] = []
    for i, job in enumerate(jobs):
        results.append(
            apply_to_job(
                job,
                profile,
                resume,
                live=live,
                browser=browser,
                submit=submit,
            )
        )
        if live and i < len(jobs) - 1:
            time.sleep(delay_seconds)
    return results


def _choose_method(target: str, ats: str, browser: bool) -> str:
    if target.lower().startswith("mailto:") or ats == "email":
        return "email"
    if browser:
        return "browser"
    return "open"


def _mailto_address(target: str) -> str:
    if target.lower().startswith("mailto:"):
        rest = target.split(":", 1)[1]
        return unquote(rest.split("?", 1)[0])
    parsed = urlparse(target)
    if parsed.scheme == "mailto":
        return unquote(parsed.path)
    return ""


def _apply_email(job: Job, profile: Profile, resume: Resume, target: str) -> ApplyResult:
    to_addr = _mailto_address(target)
    if not to_addr:
        return ApplyResult(job, "failed", "email", "no mailto address")
    if not profile.smtp_host or not profile.smtp_user:
        webbrowser.open(target)
        return ApplyResult(
            job,
            "opened",
            "mailto",
            "SMTP not configured; opened mail client",
        )

    cover = render_cover_letter(job, resume, profile)
    msg = EmailMessage()
    sender = profile.smtp_from or profile.email or profile.smtp_user
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = f"Application: {job.title} - {profile.full_name or 'Applicant'}"
    msg.set_content(cover)

    resume_path = Path(resume.path)
    if resume_path.exists():
        data = resume_path.read_bytes()
        maintype, subtype = ("application", "octet-stream")
        if resume_path.suffix.lower() == ".pdf":
            subtype = "pdf"
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=resume_path.name,
        )

    with smtplib.SMTP(profile.smtp_host, profile.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(profile.smtp_user, profile.smtp_password)
        smtp.send_message(msg)

    return ApplyResult(job, "applied", "email", f"emailed {to_addr}")


def _apply_browser(
    job: Job,
    profile: Profile,
    resume: Resume,
    target: str,
    *,
    submit: bool,
    cover_letter: str = "",
    hold_for_review: bool = True,
) -> ApplyResult:
    blocked = blocked_host(target)
    if blocked:
        return ApplyResult(
            job,
            "skipped",
            "browser",
            f"refusing to automate {blocked} (login wall / terms of use)",
        )
    from applyflow.browser import MISSING_PLAYWRIGHT, fill_application

    try:
        outcome = fill_application(
            target,
            profile,
            resume,
            submit=submit,
            cover_letter=cover_letter,
            hold_for_review=hold_for_review,
        )
    except ImportError as exc:
        return ApplyResult(job, "failed", "browser", str(exc) or MISSING_PLAYWRIGHT)
    return ApplyResult(job, outcome.status, "browser", outcome.notes)


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False
