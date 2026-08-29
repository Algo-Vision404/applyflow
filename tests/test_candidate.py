from datetime import date

from applyflow.candidate import infer_from_text, intern_program_year, intern_year_fits
from applyflow.career import eligible_for_profile
from applyflow.config import Profile
from applyflow.models import Job, Resume


TODAY = date(2026, 8, 29)


def _resume(text: str) -> Resume:
    return Resume(path="r.txt", text=text, skills=["python"])


def test_infers_graduation_and_internship_months():
    text = """
    Jane Doe
    University of Example, B.S. Computer Science
    Expected graduation May 2028
    GPA 3.8

    Software Engineering Intern, Amazon
    May 2025 – August 2025
    python

    Research Intern, Campus Lab
    June 2024 - August 2024
    """
    cand = infer_from_text(text, today=TODAY)
    assert cand.graduation_year == 2028
    assert cand.in_school
    assert cand.stage == "intern"
    assert cand.recommended_search == "intern"
    assert cand.internships == 2
    assert 6 <= cand.work_months <= 10


def test_graduating_soon_can_see_new_grad_roles():
    text = "Expected graduation May 2027\nIntern, Acme\nJune 2025 - August 2025"
    cand = infer_from_text(text, today=TODAY)
    assert cand.stage == "graduating"
    assert cand.could_new_grad
    intern = Job(external_id="1", source="t", title="Software Engineering Intern, Summer 2027", company="Google")
    new_grad = Job(external_id="2", source="t", title="New Grad Backend Engineer", company="Stripe")
    senior = Job(external_id="3", source="t", title="Senior Staff Engineer", company="X")
    resume = _resume(text)
    profile = Profile(graduation_year="2027")
    assert eligible_for_profile(intern, "auto", resume, profile)
    assert eligible_for_profile(new_grad, "auto", resume, profile)
    assert not eligible_for_profile(senior, "auto", resume, profile)


def test_student_far_from_grad_skips_new_grad_full_time():
    text = "Expected graduation May 2029\nIntern, Acme\nMay 2025 - August 2025"
    resume = _resume(text)
    profile = Profile(graduation_year="2029")
    intern = Job(external_id="1", source="t", title="Software Engineering Intern", company="Amazon")
    new_grad = Job(external_id="2", source="t", title="New Grad Backend Engineer", company="Stripe")
    assert eligible_for_profile(intern, "auto", resume, profile)
    assert not eligible_for_profile(new_grad, "auto", resume, profile)


def test_intern_year_must_fit_graduation_window():
    cand = infer_from_text("Expected graduation May 2027", Profile(graduation_year="2027"), TODAY)
    good = Job(external_id="1", source="t", title="Software Engineering Intern, Summer 2027", company="Google")
    bad = Job(external_id="2", source="t", title="Software Engineering Intern, Summer 2023", company="Google")
    assert intern_program_year(good) == 2027
    assert intern_year_fits(good, cand, TODAY)
    assert not intern_year_fits(bad, cand, TODAY)


def test_alumni_are_not_matched_to_internships():
    text = "Graduated May 2023\nSoftware Engineer, Acme\nJune 2023 - Present"
    resume = _resume(text)
    profile = Profile(graduation_year="2023")
    intern = Job(external_id="1", source="t", title="Software Engineering Intern, Summer 2027", company="Google")
    junior = Job(external_id="2", source="t", title="Junior Software Engineer", company="Acme")
    assert not eligible_for_profile(intern, "early", resume, profile)
    assert eligible_for_profile(junior, "early", resume, profile)


def test_expected_month_year_is_graduation_not_internship():
    text = """
    Example Technical University
    BSc Data Science and Analytics Expected May 2027
    Intelligent Systems Security Intern Mar 2025 – Jun 2025
    Machine Learning Engineer Intern Aug 2025 – Oct 2025
    """
    cand = infer_from_text(text, today=TODAY)
    assert cand.graduation_year == 2027
    assert cand.in_school
    assert cand.internships >= 1


def test_extract_school_and_name():
    from applyflow.resume import extract_name, extract_school

    text = "ALEX RIVERA\nExample Technical University Springfield\nBSc Data Science"
    assert extract_name(text) == ("Alex", "Rivera")
    assert "University" in extract_school(text)


def test_resume_seeking_entry_level_includes_intern_and_new_grad():
    text = """
    Expected May 2027
    Seeking an entry-level software engineering role.
    Machine Learning Engineer Intern Aug 2025 – Oct 2025
    """
    resume = _resume(text)
    cand = infer_from_text(text, today=TODAY)
    assert cand.recommended_search == "early"
    assert "intern" in cand.bands and "early" in cand.bands
    intern = Job(external_id="1", source="t", title="Software Engineering Intern", company="Amazon")
    new_grad = Job(external_id="2", source="t", title="New Grad Backend Engineer", company="Stripe")
    senior = Job(external_id="3", source="t", title="Senior Staff Engineer", company="X")
    assert eligible_for_profile(intern, "auto", resume)
    assert eligible_for_profile(new_grad, "auto", resume)
    assert not eligible_for_profile(senior, "auto", resume)


def test_experienced_resume_targets_mid_not_internships():
    text = "Software Engineer Acme June 2018 - Present Built python services."
    resume = _resume(text)
    cand = infer_from_text(text, today=TODAY)
    assert cand.recommended_search in {"mid", "senior"}
    intern = Job(external_id="1", source="t", title="Software Engineering Intern", company="Amazon")
    mid = Job(external_id="2", source="t", title="Software Engineer, Backend", company="Stripe")
    assert not eligible_for_profile(intern, "auto", resume)
    assert eligible_for_profile(mid, "auto", resume)


def test_profile_graduation_year_overrides_resume_noise():
    text = "Worked on a 2019 class project. Expected something else."
    cand = infer_from_text(text, Profile(graduation_year="May 2028"), TODAY)
    assert cand.graduation_year == 2028
    assert cand.in_school
