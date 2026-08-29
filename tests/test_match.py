from applyflow.config import Profile
from applyflow.match import score_job
from applyflow.models import Job, Resume


def test_score_boosts_title_skill_overlap():
    resume = Resume(
        path="resume.pdf",
        text="python django postgres",
        skills=["python", "django", "postgres"],
        keywords=["python", "django", "postgres"],
    )
    profile = Profile()
    strong = Job(
        external_id="1",
        source="test",
        title="Senior Python Django Engineer",
        company="Acme",
        location="Remote",
        description="Build APIs with django and postgres",
        tags=["python"],
    )
    weak = Job(
        external_id="2",
        source="test",
        title="Retail Store Manager",
        company="Shop",
        location="Boston",
        description="Manage a store and inventory",
        tags=["retail"],
    )
    assert score_job(strong, resume, profile) > score_job(weak, resume, profile)
    assert score_job(strong, resume, profile) >= 45


def test_score_does_not_treat_java_as_javascript():
    resume = Resume(path="x", text="java", skills=["java"], keywords=["java"])
    profile = Profile()
    java = Job(
        external_id="4",
        source="test",
        title="Java Engineer",
        company="Acme",
        description="Backend services in java and spring",
    )
    javascript = Job(
        external_id="5",
        source="test",
        title="JavaScript Engineer",
        company="Acme",
        description="Build UIs with javascript and react",
    )
    assert score_job(java, resume, profile) > score_job(javascript, resume, profile)


def test_exclude_keywords_zero_out_score():
    resume = Resume(path="x", text="python", skills=["python"], keywords=["python"])
    profile = Profile(exclude_keywords=["unpaid intern"])
    job = Job(
        external_id="3",
        source="test",
        title="Python intern",
        company="X",
        description="unpaid intern role using python",
    )
    assert score_job(job, resume, profile) == 0
