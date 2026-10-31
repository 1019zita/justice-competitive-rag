"""Dynamic Legal Issue Spotting: raw facts to grounded legal questions."""

from .models import (
    CaseFactStructure,
    DynamicCaseInput,
    IssueSpottingConfig,
    IssueSpottingResult,
    LegalIssue,
)
from .service import spot_issues

__all__ = [
    "CaseFactStructure",
    "DynamicCaseInput",
    "IssueSpottingConfig",
    "IssueSpottingResult",
    "LegalIssue",
    "spot_issues",
]
