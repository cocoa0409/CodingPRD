"""Lightweight type aliases used across the helpers and the test suite.

These are documentation-grade aliases only: the API speaks plain JSON, so the
suite works with dictionaries and these names simply record intent.
"""

from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]
Headers = Dict[str, str]
Envelope = Dict[str, Any]
PagedResult = Tuple[List[Json], Json]

# Resource-shaped aliases (all plain dictionaries at runtime).
Program = Json
Overlay = Json
Borrower = Json
CreditEvent = Json
LoanFile = Json
IncomeWorksheet = Json
StatementMonth = Json
ValuationOrder = Json
AppraisalReview = Json
FeeItem = Json
ExceptionRequest = Json
PostCloseAudit = Json
AuditFinding = Json
SecuritizationPool = Json
