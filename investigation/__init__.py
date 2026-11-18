"""Bounded, read-only revenue investigation primitives."""

from investigation.context import resolve_scope
from investigation.evidence import EvidenceRecord, EvidenceRegistry
from investigation.facts import render_claim
from investigation.models import (
    Claim,
    ClarificationRequest,
    DashboardContext,
    InvestigationReport,
    ResolvedScope,
)
from investigation.orchestrator import (
    Budgets,
    InvestigationResult,
    investigate,
    trace_to_json,
)
from investigation.providers import GeminiClient, ScriptedClient
from investigation.tools import InvestigationTools
from investigation.validator import ValidationResult, validate_evidence, validate_report

__all__ = [
    "Budgets",
    "GeminiClient",
    "InvestigationResult",
    "ScriptedClient",
    "investigate",
    "trace_to_json",
    "Claim",
    "ClarificationRequest",
    "DashboardContext",
    "EvidenceRecord",
    "EvidenceRegistry",
    "InvestigationReport",
    "InvestigationTools",
    "ResolvedScope",
    "ValidationResult",
    "render_claim",
    "resolve_scope",
    "validate_evidence",
    "validate_report",
]
