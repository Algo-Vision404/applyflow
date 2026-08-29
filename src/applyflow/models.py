from __future__ import annotations

from pydantic import BaseModel, Field


class Job(BaseModel):
    id: int | None = None
    external_id: str
    source: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    apply_url: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    ats: str = ""
    posted_at: str = ""
    score: int = 0
    career_level: str = ""
    tailored_path: str = ""

    def apply_target(self) -> str:
        return self.apply_url or self.url


class Application(BaseModel):
    id: int
    job_id: int
    status: str
    method: str = ""
    notes: str = ""
    created_at: str = ""
    title: str = ""
    company: str = ""
    source: str = ""


class Resume(BaseModel):
    path: str
    text: str
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    graduation_year: str = ""
    experience_months: int = 0
    internships: int = 0
    stage: str = ""
    timeline: str = ""
    school: str = ""
    linkedin: str = ""
    github: str = ""
    first_name: str = ""
    last_name: str = ""
