from applyflow.models import Job
from applyflow.sources import detect_ats, filter_query


def test_detect_ats_from_url():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/123") == "ashby"
    assert detect_ats("mailto:jobs@acme.com") == "email"
    assert detect_ats("https://example.com/careers") == ""


def test_filter_query_empty_stays_empty():
    jobs = [
        Job(external_id="2", source="t", title="Retail Manager", company="B", description="store"),
    ]
    assert filter_query(jobs, "python intern") == []


def test_filter_query_requires_all_terms():
    jobs = [
        Job(external_id="1", source="t", title="Python Engineer", company="A", description="django"),
        Job(external_id="2", source="t", title="Retail Manager", company="B", description="store"),
    ]
    matched = filter_query(jobs, "python engineer")
    assert len(matched) == 1
    assert matched[0].title == "Python Engineer"
