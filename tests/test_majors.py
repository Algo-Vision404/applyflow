from applyflow.majors import parse_apple_jobs, parse_google_jobs


def test_parse_google_job_links():
    html = (
        'jobs/results/91436104816698054-software-engineering-intern-phd-summer-2027?q=x'
        ' jobs/results/91436104816698054-software-engineering-intern-phd-summer-2027'
    )
    jobs = parse_google_jobs(html)
    assert len(jobs) == 1
    assert jobs[0].company == "Google"
    assert "Intern" in jobs[0].title
    assert "91436104816698054" in jobs[0].url


def test_parse_apple_job_links():
    html = '/en-us/details/200313991/software-engineering-intern'
    jobs = parse_apple_jobs(html)
    assert len(jobs) == 1
    assert jobs[0].company == "Apple"
    assert "200313991" in jobs[0].url
