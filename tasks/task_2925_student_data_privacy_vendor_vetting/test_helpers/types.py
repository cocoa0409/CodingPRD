"""Lightweight typed aliases and setup-context records.

These are plain dataclasses used to carry the identifiers a composite fixture
minted so a test can name them by attribute instead of digging through nested
dictionaries.  Nothing here talks to the API.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Json = Dict[str, Any]
Headers = Dict[str, str]


@dataclass
class VendorContext:
    """A registered vendor plus the liaison headers that act for it."""

    vendor_id: str
    liaison_headers: Headers
    breach_notification_hours: int
    row: Json = field(default_factory=dict)


@dataclass
class ApplicationContext:
    """An application and the vendor that owns it."""

    application_id: str
    vendor_id: str
    category: str
    grade_band_low: int
    grade_band_high: int
    row: Json = field(default_factory=dict)


@dataclass
class TeacherContext:
    """An enrolled teacher plus the headers that act as that teacher."""

    teacher_id: str
    headers: Headers
    employee_number: str
    row: Json = field(default_factory=dict)


@dataclass
class AnalystContext:
    """An enrolled analyst plus the headers that act as that analyst."""

    analyst_id: str
    headers: Headers
    credential_level: str
    review_capacity_minutes: int
    row: Json = field(default_factory=dict)


@dataclass
class ReviewChain:
    """Every identifier minted while walking a review to a chosen state.

    Composite fixtures return this so a test can reach any hop of the chain
    (vendor, application, teacher, request, analysts, review, commitments,
    catalog entry) without re-deriving it.
    """

    vendor_id: str
    application_id: str
    teacher_id: str
    request_id: str
    review_id: str
    assignee_id: str
    liaison_headers: Headers
    teacher_headers: Headers
    assignee_headers: Headers
    decider_id: Optional[str] = None
    decider_headers: Optional[Headers] = None
    independent_id: Optional[str] = None
    independent_headers: Optional[Headers] = None
    commitment_ids: List[str] = field(default_factory=list)
    entry_id: Optional[str] = None
    review_row: Json = field(default_factory=dict)
