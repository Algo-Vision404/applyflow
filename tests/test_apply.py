from applyflow.apply import ApplyResult, _choose_method, apply_to_job
from applyflow.config import Profile
from applyflow.models import Job, Resume


def _job() -> Job:
    return Job(
        id=None,
        external_id="1",
        source="test",
        title="Software Engineer Intern",
        company="Acme",
        url="https://boards.greenhouse.io/acme/jobs/1",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )


def _resume() -> Resume:
    return Resume(path="resume.pdf", text="python", skills=["python"])


def test_choose_method_opens_tab_unless_browser_requested():
    assert _choose_method("https://example.com/job", "greenhouse", False) == "open"
    assert _choose_method("https://example.com/job", "greenhouse", True) == "browser"
    assert _choose_method("mailto:jobs@acme.com", "", True) == "email"


def test_dry_run_does_not_open_browser(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("applyflow.apply.webbrowser.open", lambda url: opened.append(url))
    result = apply_to_job(_job(), Profile(), _resume(), live=False, browser=True)
    assert result.status == "dry-run"
    assert opened == []


def test_live_without_playwright_does_not_silently_open_tab(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("applyflow.apply.webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr("applyflow.hunt.playwright_available", lambda: False)
    from applyflow.hunt import prepare_and_apply

    result, _reading = prepare_and_apply(
        _job(),
        _resume(),
        Profile(first_name="Alex", last_name="Rivera", email="alex@example.com"),
        live=True,
        fill=True,
        tweak=False,
    )
    assert result.status == "failed"
    assert "Playwright" in result.notes
    assert opened == []


def test_apply_result_status():
    result = ApplyResult(_job(), "opened", "browser", "filled 3 fields")
    assert result.ok


def test_linkedin_apply_allowed_but_not_scraped():
    from applyflow.apply import job_from_linkedin_url
    from applyflow.sources import blocked_for_apply, blocked_host, detect_ats, is_linkedin_url

    url = "https://www.linkedin.com/jobs/view/123"
    assert is_linkedin_url(url)
    assert blocked_host(url) == "linkedin.com"
    assert blocked_for_apply(url) == ""
    assert blocked_for_apply("https://www.indeed.com/viewjob?jk=1") == "indeed.com"
    assert detect_ats(url) == "linkedin"
    job = job_from_linkedin_url(url)
    assert job.ats == "linkedin"
    try:
        job_from_linkedin_url("https://example.com/job")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
