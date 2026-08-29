from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


APP_DIR = Path(os.environ.get("APPLYFLOW_HOME", Path.home() / ".applyflow"))
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_DIR = APP_DIR / "resume"
DB_PATH = APP_DIR / "applyflow.db"


class Board(BaseModel):
    kind: str  # greenhouse | lever | ashby
    token: str
    label: str = ""


class Profile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    github: str = ""
    work_authorization: str = ""
    salary_expectation: str = ""
    school: str = ""
    graduation_year: str = ""
    career_level: str = "auto"  # intern | early | auto | any
    needs_sponsorship: str = ""  # yes | no | ""
    cover_letter_template: str = (
        "Hi {company} team,\n\n"
        "I am applying for the {title} role. My background includes {skills}.\n\n"
        "I would welcome the chance to discuss how I can help.\n\n"
        "Best,\n{full_name}\n{email}\n{phone}"
    )
    resume_path: str = ""
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    boards: list[Board] = Field(default_factory=list)
    min_score: int = 25
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    usajobs_key: str = ""
    usajobs_email: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "us"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def resume_file(self) -> Path | None:
        if self.resume_path:
            path = Path(self.resume_path)
            if path.exists():
                return path
        if RESUME_DIR.exists():
            files = [p for p in sorted(RESUME_DIR.glob("*")) if p.is_file()]
            if files:
                return files[0]
        return None


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def load_profile() -> Profile:
    ensure_app_dir()
    if not PROFILE_PATH.exists():
        profile = Profile()
        _apply_env_overrides(profile)
        return profile
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = Profile.model_validate(data)
    _apply_env_overrides(profile)
    return profile


def save_profile(profile: Profile) -> None:
    ensure_app_dir()
    PROFILE_PATH.write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _apply_env_overrides(profile: Profile) -> None:
    mapping: dict[str, str] = {
        "smtp_host": "APPLYFLOW_SMTP_HOST",
        "smtp_user": "APPLYFLOW_SMTP_USER",
        "smtp_password": "APPLYFLOW_SMTP_PASSWORD",
        "smtp_from": "APPLYFLOW_SMTP_FROM",
        "usajobs_key": "APPLYFLOW_USAJOBS_KEY",
        "usajobs_email": "APPLYFLOW_USAJOBS_EMAIL",
        "adzuna_app_id": "APPLYFLOW_ADZUNA_APP_ID",
        "adzuna_app_key": "APPLYFLOW_ADZUNA_APP_KEY",
        "adzuna_country": "APPLYFLOW_ADZUNA_COUNTRY",
    }
    for field, env_name in mapping.items():
        value = os.environ.get(env_name)
        if value:
            setattr(profile, field, value)
    port = os.environ.get("APPLYFLOW_SMTP_PORT")
    if port:
        profile.smtp_port = int(port)


def update_profile(**kwargs: Any) -> Profile:
    profile = load_profile()
    for key, value in kwargs.items():
        if value is None or not hasattr(profile, key):
            continue
        setattr(profile, key, value)
    save_profile(profile)
    return profile
