"""Small typed records the fixtures hand back to tests.

These carry nothing but identifiers and the versions a test needs in order to
satisfy the two optimistic-concurrency guards, so that a test never has to
reach back into a raw response body just to find a primary key.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]
JsonList = List[Any]
Headers = Dict[str, str]


@dataclass
class UserIdentity:
    """One operator: an ``X-User-ID`` paired with the role it acts under."""

    user_id: str
    role: str


@dataclass
class CommitteeScenario:
    """A chartered advisory committee with its seated roster."""

    committee_id: str
    chair_member_id: str
    member_ids: List[str] = field(default_factory=list)
    chair: Optional[UserIdentity] = None


@dataclass
class ProgramScenario:
    """A program of study together with everything built underneath it."""

    program_id: str
    cip_code: str
    version: int
    director: UserIdentity
    reviewer: UserIdentity
    registrar: Optional[UserIdentity] = None
    fiscal_officer: Optional[UserIdentity] = None
    secondary_course_id: Optional[str] = None
    postsecondary_course_id: Optional[str] = None
    credential_id: Optional[str] = None
    educator_id: Optional[str] = None
    committee: Optional[CommitteeScenario] = None
    clna_meeting_ids: List[str] = field(default_factory=list)
    endorsement_meeting_id: Optional[str] = None

    @property
    def chair(self) -> Optional[UserIdentity]:
        return self.committee.chair if self.committee else None

    @property
    def committee_id(self) -> Optional[str]:
        return self.committee.committee_id if self.committee else None

    @property
    def member_ids(self) -> List[str]:
        return list(self.committee.member_ids) if self.committee else []


@dataclass
class GrantScenario:
    """A recorded federal grant award and the officer who owns it."""

    grant_id: str
    fiscal_year: int
    allocation_cents: int
    version: int
    fiscal_officer: UserIdentity
