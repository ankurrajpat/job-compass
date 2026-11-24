"""Validated contracts for the agent, API, and model-selected tools."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Preferences(Strict):
    skills: list[str] = Field(default_factory=list, max_length=20)
    target_role: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=80)
    remote_only: bool = False

class Remember(Strict):
    skills: list[str] | None = Field(default=None, max_length=20)
    target_role: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=80)
    remote_only: bool | None = None

class Search(Strict):
    query: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=80)
    remote_only: bool = False
    limit: int = Field(default=5, ge=1, le=8)

class Details(Strict):
    job_ids: list[str] = Field(min_length=1, max_length=8)

class Pick(Strict):
    job_id: str
    reason: str = Field(min_length=1, max_length=500)
    gaps: list[str] = Field(default_factory=list, max_length=6)

class Answer(Strict):
    summary: str = Field(min_length=1, max_length=1200)
    recommendations: list[Pick] = Field(default_factory=list, max_length=5)
    follow_up: str = Field(default="", max_length=400)

class Chat(Strict):
    message: str = Field(min_length=1, max_length=2000)
