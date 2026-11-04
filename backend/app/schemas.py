from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pain_point: str = Field(min_length=10, max_length=3000)
    context: str = Field(default="", max_length=2000)


class AgentBlueprint(BaseModel):
    architecture: Literal["undetermined", "single_agent", "multi_agent", "rule_based"]
    roles: list[str]
    workflow: list[str]
    tools: list[str]


class StarterPack(BaseModel):
    pain_point: str
    goal: str
    assumptions: list[str]
    agent_recommended: bool | None
    agent_blueprint: AgentBlueprint
    next_steps: list[str] = Field(min_length=1)


class GenerateResponse(BaseModel):
    request_id: UUID
    provider: Literal["mock"]
    is_mock: Literal[True]
    notice: str
    starter_pack: StarterPack


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
