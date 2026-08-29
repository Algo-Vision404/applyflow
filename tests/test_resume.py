from pathlib import Path

from applyflow.resume import _has_skill, extract_text


def test_extract_text_from_txt(tmp_path: Path):
    path = tmp_path / "resume.txt"
    path.write_text("Jane Doe\npython django\njane@example.com\n", encoding="utf-8")
    text = extract_text(path)
    assert "Jane Doe" in text
    assert "python" in text


def test_short_skill_tokens_use_word_boundaries():
    text = "software engineer building platforms with python"
    assert _has_skill(text, "python")
    assert not _has_skill(text, "go")
    assert not _has_skill(text, "r")


def test_detected_skills_follow_resume_order():
    from applyflow.resume import _detected_skills

    skills = _detected_skills("Built django APIs in python and react")
    assert skills.index("django") < skills.index("python") < skills.index("react")
