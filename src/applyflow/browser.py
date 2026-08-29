from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from applyflow.config import Profile
from applyflow.models import Resume


@dataclass
class BrowserOutcome:
    status: str
    notes: str


FIELD_SELECTORS = {
    "first_name": [
        "#first_name",
        "input[name='first_name']",
        "input[name='firstName']",
        "input[name='firstname']",
        "input[name='job_application[first_name]']",
        "input[autocomplete='given-name']",
        "input[id*='first' i][id*='name' i]",
        "input[placeholder*='First name' i]",
        "input[aria-label*='First name' i]",
    ],
    "last_name": [
        "#last_name",
        "input[name='last_name']",
        "input[name='lastName']",
        "input[name='lastname']",
        "input[name='job_application[last_name]']",
        "input[autocomplete='family-name']",
        "input[id*='last' i][id*='name' i]",
        "input[placeholder*='Last name' i]",
        "input[aria-label*='Last name' i]",
    ],
    "full_name": [
        "input[name='name']",
        "input[name='full_name']",
        "input[name='fullName']",
        "input[name='job_application[name]']",
        "input[autocomplete='name']",
        "input[placeholder*='Full name' i]",
        "input[aria-label*='Full name' i]",
    ],
    "email": [
        "input[type='email']",
        "#email",
        "input[name='email']",
        "input[name='job_application[email]']",
        "input[autocomplete='email']",
        "input[placeholder*='Email' i]",
        "input[aria-label*='Email' i]",
    ],
    "phone": [
        "input[type='tel']",
        "#phone",
        "input[name='phone']",
        "input[name='phone_number']",
        "input[name='cards[phone]']",
        "input[name='job_application[phone]']",
        "input[autocomplete='tel']",
        "input[placeholder*='Phone' i]",
        "input[aria-label*='Phone' i]",
    ],
    "linkedin": [
        "input[name*='linkedin' i]",
        "input[name='urls[LinkedIn]']",
        "input[name='urls[Linkedin]']",
        "input[placeholder*='LinkedIn' i]",
        "input[aria-label*='LinkedIn' i]",
    ],
    "website": [
        "input[name='website']",
        "input[name='url']",
        "input[name*='portfolio' i]",
        "input[placeholder*='Website' i]",
        "input[placeholder*='Portfolio' i]",
    ],
    "github": [
        "input[name*='github' i]",
        "input[name='urls[GitHub]']",
        "input[name='urls[Github]']",
        "input[placeholder*='GitHub' i]",
        "input[aria-label*='GitHub' i]",
    ],
    "school": [
        "input[name*='school' i]",
        "input[name*='university' i]",
        "input[name*='college' i]",
        "input[name='org']",
        "input[placeholder*='School' i]",
        "input[placeholder*='University' i]",
    ],
    "graduation_year": [
        "input[name*='graduat' i]",
        "input[placeholder*='Graduation' i]",
        "input[name*='class_year' i]",
    ],
    "location": [
        "input[name='location']",
        "input[name='city']",
        "input[autocomplete='address-level2']",
        "input[placeholder*='City' i]",
        "input[placeholder*='Location' i]",
    ],
}

LABELS = {
    "first_name": ["First name", "First Name", "Given name"],
    "last_name": ["Last name", "Last Name", "Family name", "Surname"],
    "full_name": ["Full name", "Name"],
    "email": ["Email", "Email address"],
    "phone": ["Phone", "Phone number", "Mobile"],
    "linkedin": ["LinkedIn", "LinkedIn URL"],
    "website": ["Website", "Portfolio", "Personal website"],
    "github": ["GitHub", "Github"],
    "school": ["School", "University", "College"],
    "graduation_year": ["Graduation", "Graduation year", "Class year"],
    "location": ["Location", "City", "Current location"],
}

CAPTCHA_HINTS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    ".g-recaptcha",
    "[data-sitekey]",
    "text=Verify you are human",
]

FORM_READY = (
    "input[type='email'], input[type='tel'], input[type='text'], "
    "input[type='file'], textarea, input:not([type='hidden'])"
)
MISSING_PLAYWRIGHT = (
    "Playwright is not installed, so Applyflow cannot type into forms. "
    "From the project folder run: python -m pip install playwright && python -m playwright install chromium"
)

# Keep Playwright sessions alive so Chromium is not killed when fill() returns.
_SESSIONS: list = []


def fill_application(
    url: str,
    profile: Profile,
    resume: Resume,
    *,
    submit: bool = False,
    cover_letter: str = "",
    timeout_ms: int = 45000,
    hold_for_review: bool = True,
) -> BrowserOutcome:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ImportError(MISSING_PLAYWRIGHT) from exc

    resume_path = str(Path(resume.path).resolve())
    values = _values(profile)
    try:
        playwright = sync_playwright().start()
    except Exception as exc:
        return BrowserOutcome("failed", str(exc))
    browser = None
    try:
        browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(accept_downloads=True, no_viewport=True)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        _dismiss_cookies(page)
        _prefer_manual_apply(page)
        if not _form_present(page):
            _click_apply_entry(page)
            _wait_for_form(page)
        if _has_captcha(page):
            outcome = BrowserOutcome("opened", "CAPTCHA detected; complete it in the browser")
            return _finish(playwright, browser, page, outcome, hold_for_review, "CAPTCHA — finish in this window.")

        filled = 0
        uploaded = False
        for frame in _frames(page):
            filled += _fill_fields(frame, values)
            filled += _fill_by_label(frame, values)
            if _upload_resume(frame, resume_path):
                uploaded = True
            _fill_cover_or_text(frame, cover_letter or profile.cover_letter_template, resume)

        if filled == 0 and not uploaded:
            outcome = BrowserOutcome(
                "opened",
                "opened the posting but found no fillable fields (login wall or custom widget)",
            )
            return _finish(
                playwright,
                browser,
                page,
                outcome,
                hold_for_review,
                "No public form fields found. Finish in this window if you can.",
            )

        if submit and filled:
            clicked = False
            for frame in _frames(page):
                if _click_submit(frame):
                    clicked = True
                    break
            page.wait_for_timeout(2000)
            if clicked:
                outcome = BrowserOutcome("submitted", f"filled {filled} fields; resume_uploaded={uploaded}")
                return _finish(playwright, browser, page, outcome, hold_for_review, "Submit clicked — confirm, then close.")
            outcome = BrowserOutcome("opened", f"filled {filled} fields; could not find a safe submit button")
            return _finish(playwright, browser, page, outcome, hold_for_review, "Submit it yourself, then close this window.")

        outcome = BrowserOutcome("opened", f"filled {filled} fields; resume_uploaded={uploaded}")
        return _finish(
            playwright,
            browser,
            page,
            outcome,
            hold_for_review,
            "Review the filled form, submit it yourself, then close this window.",
        )
    except PlaywrightTimeout:
        _stop(playwright, browser)
        return BrowserOutcome("failed", "timed out loading application page")
    except Exception as exc:
        _stop(playwright, browser)
        return BrowserOutcome("failed", str(exc))


def _finish(playwright, browser, page, outcome: BrowserOutcome, hold: bool, message: str) -> BrowserOutcome:
    if hold:
        _hold_for_review(page, message)
        _stop(playwright, browser)
    else:
        _SESSIONS.append((playwright, browser))
    return outcome


def _stop(playwright, browser) -> None:
    try:
        if browser is not None:
            browser.close()
    except Exception:
        pass
    try:
        playwright.stop()
    except Exception:
        pass


def _values(profile: Profile) -> dict[str, str]:
    return {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "linkedin": profile.linkedin,
        "website": profile.website,
        "github": profile.github,
        "school": profile.school,
        "graduation_year": profile.graduation_year,
        "location": profile.location,
    }


def _frames(page):
    yield page
    for frame in page.frames:
        if frame != page.main_frame:
            yield frame


def _form_present(page) -> bool:
    for frame in list(_frames(page)):
        try:
            if frame.locator(
                "input[type='email'], input[type='tel'], input[type='file'], "
                "input[name='first_name'], input[name='firstName'], textarea"
            ).count() > 0:
                return True
        except Exception:
            continue
    return False


def _wait_for_form(page) -> None:
    for _ in range(4):
        for frame in list(_frames(page)):
            try:
                frame.wait_for_selector(FORM_READY, timeout=2500, state="visible")
                return
            except Exception:
                continue
        page.wait_for_timeout(800)


def _fill_one(locator, value: str) -> bool:
    try:
        locator.wait_for(state="visible", timeout=900)
        locator.fill(value, timeout=1800)
        return True
    except Exception:
        try:
            locator.click(timeout=800)
            locator.fill(value, timeout=1800)
            return True
        except Exception:
            return False


def _fill_fields(page, values: dict[str, str]) -> int:
    filled = 0
    for key, value in values.items():
        if not value:
            continue
        for selector in FIELD_SELECTORS.get(key, []):
            locator = page.locator(selector).first
            if _fill_one(locator, value):
                filled += 1
                break
    return filled


def _fill_by_label(page, values: dict[str, str]) -> int:
    filled = 0
    for key, labels in LABELS.items():
        value = values.get(key) or ""
        if not value:
            continue
        for label in labels:
            try:
                locator = page.get_by_label(label, exact=False).first
            except Exception:
                continue
            if _fill_one(locator, value):
                filled += 1
                break
    return filled


def _upload_resume(page, resume_path: str) -> bool:
    inputs = page.locator("input[type='file']")
    try:
        count = inputs.count()
    except Exception:
        return False
    for i in range(count):
        try:
            inputs.nth(i).set_input_files(resume_path, timeout=4000)
            return True
        except Exception:
            continue
    return False


def _fill_cover_or_text(page, cover: str, resume: Resume) -> None:
    snippet = (cover or "")[:2000] or (resume.text or "")[:800]
    if not snippet:
        return
    textareas = page.locator("textarea")
    try:
        count = textareas.count()
    except Exception:
        return
    for i in range(min(count, 3)):
        box = textareas.nth(i)
        try:
            name = (box.get_attribute("name") or "") + (box.get_attribute("placeholder") or "")
            if any(skip in name.lower() for skip in ("password", "search", "filter")):
                continue
        except Exception:
            pass
        _fill_one(box, snippet)


def _prefer_manual_apply(page) -> None:
    for selector in (
        "button:has-text('Apply manually')",
        "a:has-text('Apply manually')",
        "button:has-text('Apply without LinkedIn')",
        "a:has-text('Apply without LinkedIn')",
        "button:has-text('Continue without')",
        "button:has-text('Apply with resume')",
        "a:has-text('Apply with resume')",
    ):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=700)
            loc.click(timeout=1200)
            page.wait_for_timeout(800)
            return
        except Exception:
            continue


def _click_apply_entry(page) -> None:
    for selector in (
        "a#apply_button",
        "#apply_button",
        "a.applyButton",
        "button.apply-button",
        "a:has-text('Apply for this job')",
        "button:has-text('Apply for this job')",
        "a:has-text('Apply now')",
        "button:has-text('Apply now')",
        "a:has-text(\"I'm interested\")",
        "button:has-text(\"I'm interested\")",
        "a:has-text('Submit application')",
        "a:has-text('Apply')",
        "button:has-text('Apply')",
    ):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=900)
            loc.click(timeout=1500)
            page.wait_for_timeout(1200)
            return
        except Exception:
            continue


def _click_submit(page) -> bool:
    candidates = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Send application')",
        "button:has-text('Submit')",
    ]
    for selector in candidates:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=800)
            locator.click(timeout=2000)
            return True
        except Exception:
            continue
    return False


def _has_captcha(page) -> bool:
    for selector in CAPTCHA_HINTS:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def _hold_for_review(page, message: str) -> None:
    try:
        page.bring_to_front()
    except Exception:
        pass
    if getattr(sys.stdin, "isatty", lambda: False)():
        try:
            print(message, flush=True)
            input("Press Enter in this terminal when you are done reviewing... ")
            return
        except EOFError:
            pass
    try:
        page.wait_for_event("close", timeout=15 * 60 * 1000)
    except Exception:
        try:
            page.wait_for_timeout(120_000)
        except Exception:
            pass


def _dismiss_cookies(page) -> None:
    for label in ("Accept all", "Accept All", "Accept", "I agree", "Got it"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=1000)
                return
        except Exception:
            continue
