"""Provider-neutral model interface plus a scripted model and a Gemini (Vertex AI) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol

from pydantic import BaseModel

from investigation.models import Claim
from investigation.prompts import SYSTEM_RULES, build_prompt


class ProviderError(RuntimeError):
    """The model could not produce a usable decision."""


@dataclass(frozen=True)
class ModelView:
    """Everything a model may see when it chooses the next step."""

    phase: Literal["classify", "investigate", "define"]
    question: str
    scope_summary: str
    evidence: tuple[str, ...]
    tools_left: int
    last_error: str | None
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassifyDecision:
    question_class: str


@dataclass(frozen=True)
class ToolDecision:
    tool: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FinishDecision:
    claims: tuple[Claim, ...]
    stop_reason: str


@dataclass(frozen=True)
class LookupDecision:
    topics: tuple[str, ...]


Decision = ClassifyDecision | ToolDecision | FinishDecision | LookupDecision


class ModelClient(Protocol):
    name: str

    def decide(self, view: ModelView) -> Decision: ...


class ScriptedClient:
    """Replays a fixed list of decisions; used to test control flow without a model."""

    name = "scripted"

    def __init__(self, decisions: list[Decision | Exception]) -> None:
        self._decisions = list(decisions)
        self.views: list[ModelView] = []

    def decide(self, view: ModelView) -> Decision:
        self.views.append(view)
        if not self._decisions:
            raise ProviderError("The scripted model has no decisions left")
        decision = self._decisions.pop(0)
        if isinstance(decision, Exception):
            raise decision
        return decision


class _ClaimOut(BaseModel):
    level: str
    fact: Optional[str] = None
    key: Optional[str] = None
    evidence_id: Optional[str] = None
    text: Optional[str] = None


class _StepOut(BaseModel):
    action: Literal["classify", "call_tool", "finish", "lookup"]
    question_class: Optional[str] = None
    tool: Optional[str] = None
    dimension: Optional[str] = None
    topics: list[str] = []
    stop_reason: Optional[str] = None
    claims: list[_ClaimOut] = []


class GeminiClient:
    """Gemini on Vertex AI using Application Default Credentials; no key is stored."""

    def __init__(
        self,
        project: str,
        *,
        model: str = "gemini-3-flash-preview",
        location: str = "global",
        client: object | None = None,
    ) -> None:
        if client is None:
            from google import genai

            client = genai.Client(vertexai=True, project=project, location=location)
        self._client = client
        self.model = model
        self.name = f"gemini:{model}"
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.thinking_tokens = 0
        self.usage_missing = False

    def decide(self, view: ModelView) -> Decision:
        from google.genai import types

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=build_prompt(view),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_RULES,
                    response_mime_type="application/json",
                    response_schema=_StepOut,
                    temperature=0,
                    max_output_tokens=8192,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW
                    ),
                ),
            )
            usage = response.usage_metadata
            self.calls += 1
            prompt = getattr(usage, "prompt_token_count", None)
            answer = getattr(usage, "candidates_token_count", None)
            if prompt is None or answer is None:
                self.usage_missing = True
            self.input_tokens += prompt or 0
            self.output_tokens += answer or 0
            self.thinking_tokens += getattr(usage, "thoughts_token_count", None) or 0
            step = _StepOut.model_validate_json(response.text)
        except Exception as error:
            raise ProviderError(f"{type(error).__name__}: {str(error)[:300]}") from error
        return _to_decision(step)


def _to_decision(step: _StepOut) -> Decision:
    if step.action == "classify":
        return ClassifyDecision(step.question_class or "")
    if step.action == "call_tool":
        arguments = {"dimension": step.dimension} if step.dimension else {}
        return ToolDecision(step.tool or "", arguments)
    if step.action == "lookup":
        return LookupDecision(tuple(step.topics))
    claims = tuple(
        Claim(
            claim.text or "",
            claim.level,  # type: ignore[arg-type]
            (claim.evidence_id,) if claim.evidence_id else (),
            claim.fact,  # type: ignore[arg-type]
            claim.key,
        )
        for claim in step.claims
    )
    return FinishDecision(claims, step.stop_reason or "")
