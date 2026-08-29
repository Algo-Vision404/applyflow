from applyflow.career import classify_job, eligible_for_profile
from applyflow.config import Profile
from applyflow.models import Job, Resume
from applyflow.analyze import JobRead, _skills_already_front
from applyflow.tailor import tailor_resume


def _job(title: str, description: str = "") -> Job:
    return Job(external_id="1", source="t", title=title, company="Acme", description=description)


def test_intern_title_classifies_as_intern():
    assert classify_job(_job("Software Engineering Intern")) == "intern"
    assert classify_job(_job("New Grad Backend Engineer")) == "early"
    assert classify_job(_job("Senior Staff Engineer")) == "senior"
    assert classify_job(_job("Software Engineer, Backend (Cooperative AI)")) != "intern"
    assert classify_job(_job("Software Engineer, Full Stack")) == "mid"


def test_intern_mode_keeps_internships_only():
    intern = _job("Software Engineering Intern", "summer internship for students")
    new_grad = _job("New Grad Backend Engineer")
    junior = _job("Junior Software Engineer")
    senior = _job("Principal Engineer", "10+ years of experience")
    assert eligible_for_profile(intern, "intern")
    assert not eligible_for_profile(new_grad, "intern")
    assert not eligible_for_profile(junior, "intern")
    assert not eligible_for_profile(senior, "intern")
    assert eligible_for_profile(new_grad, "early")
    assert eligible_for_profile(intern, "early")
    assert not eligible_for_profile(senior, "early")


def test_years_required_ignores_company_age():
    from applyflow.career import years_required

    assert years_required("We were founded 20 years ago and want 2 years of experience") == 2
    assert years_required("10+ years of experience required") == 10
    assert years_required("a company founded 15 years ago hiring students") is None


def test_tailor_does_not_invent_missing_skills(tmp_path, monkeypatch):
    monkeypatch.setattr("applyflow.tailor.TAILORED_DIR", tmp_path / "tailored")
    resume = Resume(
        path=str(tmp_path / "resume.txt"),
        text="Jane Doe\npython django\nBuilt an API with django.\n",
        skills=["python", "django"],
        keywords=["python", "django"],
    )
    job = Job(
        id=1,
        external_id="x",
        source="t",
        title="Python Intern",
        company="Acme",
        description="Need python, django, and kubernetes",
    )
    reading = JobRead(
        matching=["python", "django"],
        missing=["kubernetes"],
        needs_tweak=True,
        summary="test",
    )
    result = tailor_resume(job, resume, Profile(first_name="Jane", last_name="Doe"), reading)
    assert result.tweaked
    assert "python" in result.resume.text.lower()
    assert "kubernetes" not in result.resume.text.lower()


def test_skills_already_front():
    resume = Resume(path="x", text="", skills=["python", "django", "aws"])
    assert _skills_already_front(resume, ["python", "django"])


def test_read_job_skips_tweak_when_skills_already_front():
    from applyflow.analyze import read_job

    resume = Resume(
        path="x",
        text="python django aws",
        skills=["python", "django", "aws"],
    )
    job = _job("Python Intern", "Need python and django")
    reading = read_job(job, resume)
    assert reading.matching
    assert reading.needs_tweak is False


def test_tailor_keeps_original_when_no_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr("applyflow.tailor.TAILORED_DIR", tmp_path / "tailored")
    resume = Resume(
        path=str(tmp_path / "resume.txt"),
        text="Jane Doe\npython\n",
        skills=["python"],
        keywords=["python"],
    )
    job = _job("Rust Intern", "Need rust and kubernetes")
    reading = JobRead(matching=[], missing=["rust"], needs_tweak=False, summary="test")
    result = tailor_resume(job, resume, Profile(first_name="Jane", last_name="Doe"), reading)
    assert result.tweaked is False
