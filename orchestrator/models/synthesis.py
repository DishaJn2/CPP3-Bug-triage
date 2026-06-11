from pydantic import BaseModel, Field
from typing import List


class SynthesisOutput(BaseModel):
    unified_severity: str = Field(description="P0, P1, P2, or P3")
    affected_components: List[str] = Field(default_factory=list)
    root_cause: str
    recommended_actions: List[str] = Field(default_factory=list)
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    used_fallback: bool = False


class CandidateScore(BaseModel):
    ticket_id: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    similarity_label: str
    similarity_reason: str
    similarity_matching_fields: List[str] = Field(default_factory=list)
