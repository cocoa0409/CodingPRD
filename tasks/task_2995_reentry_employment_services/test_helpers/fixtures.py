"""
Composite fixtures for the Reentry Employment Services API.

The harness restarts the server before every individual test, so each test
begins against an empty database and must build every precondition it needs.
The Builder below owns those multi-step chains.

Each Builder method is a self-contained phase: it establishes one state and
never re-runs a step that an earlier phase already consumed, so calling two
phases in sequence cannot invalidate the precondition the first one created.
Every setup call goes through get_success_data(), which raises a clear
"Setup step failed with HTTP ..." error rather than letting a broken
precondition surface as a confusing assertion deep inside a test.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CASE_ACTIVE,
    CLOCK_BOOT_INSTANT,
    DECISION_APPROVED,
    OFFER_RESPONSE_ACCEPTED,
    PARTNERSHIP_ACTIVE,
    PARTNERSHIP_ENGAGED,
)
from .test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    NO_AUTH,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
    participant_headers,
)

# The instant every test's logical clock starts from unless the test moves it.
DEFAULT_CLOCK = "2026-08-01T08:00:00.000Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# The five vital documents a standard participant must gather, and the four of
# them a release-ready participant has confirmed. Four of five verified puts
# doc_completeness_pct at exactly 80.0, which is the inclusive documentation
# boundary of the release-readiness predicate.
STANDARD_REQUIRED_DOCUMENT_TYPES = [
    "STATE_ID",
    "SSN_CARD",
    "BIRTH_CERTIFICATE",
    "WORK_HISTORY",
    "MEDICAID_APPLICATION",
]
STANDARD_VERIFIED_DOCUMENT_TYPES = [
    "STATE_ID",
    "SSN_CARD",
    "BIRTH_CERTIFICATE",
    "WORK_HISTORY",
]


class Clock:
    """The logical clock, which every temporal rule in this API reads."""

    def __init__(self, api: ApiClient):
        self._api = api
        self.current = CLOCK_BOOT_INSTANT

    def set(self, instant: str) -> str:
        response = self._api.set_clock(instant, NO_AUTH)
        get_success_data(response)
        self.current = instant
        return instant


class Builder:
    """Multi-step precondition builders, one method per reusable state."""

    def __init__(self, api: ApiClient, clock: Clock):
        self.api = api
        self.clock = clock

    # -- Grants -------------------------------------------------------------

    def grant(
        self,
        authorized_cents: int = 100000,
        per_participant_cap_cents: int = 50000,
        retention_benchmark_pct: float = 50.0,
        **overrides,
    ) -> Dict[str, Any]:
        """A funder grant, opened by the analyst who records the money."""
        payload = f.grant_payload(
            authorized_cents=authorized_cents,
            per_participant_cap_cents=per_participant_cap_cents,
            retention_benchmark_pct=retention_benchmark_pct,
            **overrides,
        )
        return get_success_data(self.api.create_grant(payload, FUNDER_ANALYST), 201)

    def grant_version(self, grant_id: str) -> int:
        """The grant's current `version`, for the support-request OCC guard."""
        return get_success_data(self.api.get_grant(grant_id, FUNDER_ANALYST))["version"]

    # -- Employer partnerships ---------------------------------------------

    def partnership(self, **overrides) -> Dict[str, Any]:
        """A partnership registered as a PROSPECT and nothing more."""
        return get_success_data(
            self.api.create_partnership(f.partnership_payload(**overrides), EMPLOYER_LIAISON),
            201,
        )

    def partnership_engaged(self, **overrides) -> Dict[str, Any]:
        """A partnership advanced to ENGAGED."""
        partnership = self.partnership(**overrides)
        return get_success_data(
            self.api.set_partnership_status(
                partnership["id"],
                f.partnership_status_payload(PARTNERSHIP_ENGAGED),
                EMPLOYER_LIAISON,
            )
        )

    def partnership_active(
        self, bond_coverage_cents: Optional[int] = 500000, **overrides
    ) -> Dict[str, Any]:
        """
        A partnership open for business.

        Bonding is recorded before the status ladder is walked, because the
        bonding write is refused once a partnership reaches SUSPENDED or
        TERMINATED and is legal from PROSPECT onwards.
        """
        overrides.setdefault("wotc_certified", True)
        overrides.setdefault("excluded_record_categories", [])
        partnership = self.partnership(**overrides)
        if bond_coverage_cents is not None:
            get_success_data(
                self.api.record_bonding_agreement(
                    partnership["id"],
                    f.bonding_agreement_payload(bond_coverage_cents, DEFAULT_CLOCK_DATE),
                    EMPLOYER_LIAISON,
                )
            )
        get_success_data(
            self.api.set_partnership_status(
                partnership["id"],
                f.partnership_status_payload(PARTNERSHIP_ENGAGED),
                EMPLOYER_LIAISON,
            )
        )
        return get_success_data(
            self.api.set_partnership_status(
                partnership["id"],
                f.partnership_status_payload(PARTNERSHIP_ACTIVE),
                EMPLOYER_LIAISON,
            )
        )

    # -- Job openings -------------------------------------------------------

    def job_opening(self, partnership_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_job_opening(
                f.job_opening_payload(partnership_id, **overrides), EMPLOYER_LIAISON
            ),
            201,
        )

    def opening_version(self, opening_id: str) -> int:
        """The opening's current `version`, for the placement OCC guard."""
        return get_success_data(self.api.get_job_opening(opening_id, CASE_MANAGER))[
            "version"
        ]

    # -- Participants -------------------------------------------------------

    def participant(self, **overrides) -> Dict[str, Any]:
        """A freshly enrolled participant sitting in PRE_RELEASE."""
        return get_success_data(
            self.api.create_participant(f.participant_payload(**overrides), CASE_MANAGER),
            201,
        )

    def participant_version(self, participant_id: str) -> int:
        """The participant's current `version`, for the release-plan OCC guard."""
        return get_success_data(
            self.api.get_participant(participant_id, CASE_MANAGER)
        )["version"]

    def participant_assessed(
        self,
        housing: int = 3,
        transportation: int = 2,
        health: int = 1,
        work_history: int = 4,
        documentation: int = 2,
        **overrides,
    ) -> Dict[str, Any]:
        """A participant carrying a barrier score but no release plan yet."""
        participant = self.participant(**overrides)
        return get_success_data(
            self.api.record_assessment(
                participant["id"],
                f.assessment_payload(
                    housing, transportation, health, work_history, documentation
                ),
                CASE_MANAGER,
            )
        )

    def verify_documents(
        self, participant_id: str, document_types: List[str]
    ) -> Dict[str, Any]:
        """Confirm each named vital document, one write per document."""
        latest: Dict[str, Any] = {}
        for document_type in document_types:
            latest = get_success_data(
                self.api.verify_document(
                    participant_id,
                    f.document_verification_payload(document_type),
                    CASE_MANAGER,
                )
            )
        return latest

    def release_plan_draft(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """
        Store one release-plan revision, leaving the plan in DRAFT.

        The participant's version is read immediately before the write, because
        every preceding phase advanced it.
        """
        version = self.participant_version(participant_id)
        return get_success_data(
            self.api.put_release_plan(
                participant_id, f.release_plan_payload(version, **overrides), CASE_MANAGER
            )
        )

    def release_plan_approved(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Store a revision and have the director approve it."""
        self.release_plan_draft(participant_id, **overrides)
        return get_success_data(
            self.api.approve_release_plan(participant_id, PROGRAM_DIRECTOR)
        )

    def participant_release_ready(
        self, verify_types: Optional[List[str]] = None, **overrides
    ) -> Dict[str, Any]:
        """
        A participant who satisfies the whole readiness predicate: documentation
        at or above 80.0, a barrier score recorded, an approved plan, and no
        suspension.

        By default four of the five required documents are confirmed, which is
        exactly 80.0 — the inclusive boundary, so the participant does advance.
        """
        participant = self.participant_assessed(**overrides)
        self.verify_documents(
            participant["id"],
            list(verify_types)
            if verify_types is not None
            else list(STANDARD_VERIFIED_DOCUMENT_TYPES),
        )
        return self.release_plan_approved(participant["id"])

    def participant_released(
        self, verify_types: Optional[List[str]] = None, **overrides
    ) -> Dict[str, Any]:
        """
        A participant who has walked out of the facility and sits in POST_RELEASE,
        which is the stage from which placements become reachable.
        """
        participant = self.participant_release_ready(verify_types, **overrides)
        return get_success_data(
            self.api.record_release(
                participant["id"],
                f.release_payload(self.clock.current[:10]),
                CASE_MANAGER,
            )
        )

    def participant_zero_barrier_draft(self, **overrides) -> Dict[str, Any]:
        """
        A participant assessed at zero in every domain, carrying a DRAFT plan.

        An all-zero assessment yields a `barrier_score` of 0.0, which is the
        input the match arithmetic's maximum barrier-fit component needs.
        """
        participant = self.participant_assessed(0, 0, 0, 0, 0, **overrides)
        return self.release_plan_draft(participant["id"])

    # -- Supervision cases --------------------------------------------------

    def supervision_case(
        self, participant_id: str, officer_headers=SUPERVISION_OFFICER, **overrides
    ) -> Dict[str, Any]:
        """A supervision case born in PENDING_CONTACT."""
        payload = f.supervision_case_payload(
            participant_id, officer_headers["X-User-ID"], **overrides
        )
        return get_success_data(
            self.api.create_supervision_case(payload, officer_headers), 201
        )

    def supervision_case_active(
        self, participant_id: str, officer_headers=SUPERVISION_OFFICER, **overrides
    ) -> Dict[str, Any]:
        """A supervision case advanced to ACTIVE, the only constraining state."""
        case = self.supervision_case(participant_id, officer_headers, **overrides)
        return get_success_data(
            self.api.set_supervision_case_status(
                case["id"], f.case_status_payload(CASE_ACTIVE), officer_headers
            )
        )

    def case_authorized(
        self,
        participant_id: str,
        start_minute: int = 480,
        end_minute: int = 1020,
        officer_headers=SUPERVISION_OFFICER,
        **overrides,
    ) -> Dict[str, Any]:
        """
        An ACTIVE supervision case whose work authorisation is APPROVED with a
        daily window. A window of 480 to 1020 authorises 08:00 to 17:00 UTC.
        """
        case = self.supervision_case_active(participant_id, officer_headers, **overrides)
        return get_success_data(
            self.api.decide_work_authorization(
                case["id"],
                f.work_authorization_payload(DECISION_APPROVED, start_minute, end_minute),
                officer_headers,
            )
        )

    # -- Placements and shifts ---------------------------------------------

    def placement_offered(
        self,
        participant_id: str,
        job_opening_id: str,
        grant_id: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """
        An outstanding offer.

        The opening's version is read immediately before the create, because
        the placement write is optimistic-concurrency guarded on the opening and
        every earlier placement on it advanced that version.
        """
        version = self.opening_version(job_opening_id)
        payload = f.placement_payload(
            participant_id, job_opening_id, version, grant_id, **overrides
        )
        return get_success_data(self.api.create_placement(payload, CASE_MANAGER), 201)

    def placement_active(
        self,
        participant_id: str,
        job_opening_id: str,
        grant_id: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """
        A live employment relationship. Only the participant may accept their own
        offer, so the acceptance is sent under the participant's own identifier.
        """
        placement = self.placement_offered(
            participant_id, job_opening_id, grant_id, **overrides
        )
        return get_success_data(
            self.api.respond_to_offer(
                placement["id"],
                f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
                participant_headers(participant_id),
            )
        )

    def work_shift(
        self, placement_id: str, starts_at: str, ends_at: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_work_shift(
                placement_id, f.work_shift_payload(starts_at, ends_at), CASE_MANAGER
            ),
            201,
        )

    # -- Readiness sessions -------------------------------------------------

    def readiness_session(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_readiness_session(
                f.readiness_session_payload(**overrides), CASE_MANAGER
            ),
            201,
        )

    def enrollment(
        self,
        session_id: str,
        participant_id: str,
        disclosure_script_reviewed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_enrollment(
                session_id,
                f.enrollment_payload(participant_id, disclosure_script_reviewed),
                CASE_MANAGER,
            ),
            201,
        )

    # -- Support requests ---------------------------------------------------

    def support_request(
        self,
        participant_id: str,
        grant_id: str,
        line_items: Optional[List[Dict[str, Any]]] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """
        A submitted supportive-services request.

        The grant's version is read immediately before the create, because the
        request write is optimistic-concurrency guarded on the grant and every
        earlier request advanced that version.
        """
        version = self.grant_version(grant_id)
        payload = f.support_request_payload(
            participant_id, grant_id, version, line_items, **overrides
        )
        return get_success_data(
            self.api.create_support_request(payload, CASE_MANAGER), 201
        )

    def support_request_approved(
        self,
        participant_id: str,
        grant_id: str,
        line_items: Optional[List[Dict[str, Any]]] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """
        A request the director has approved.

        Review is barred to whoever submitted the request, so the submitting case
        manager and the reviewing director are necessarily distinct operators.
        """
        request = self.support_request(participant_id, grant_id, line_items, **overrides)
        return get_success_data(
            self.api.review_support_request(
                request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
            )
        )


@pytest.fixture
def api() -> ApiClient:
    """The endpoint client, pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> Clock:
    """
    The logical clock, parked at a fixed instant.

    Every temporal rule in this API reads this clock instead of the wall clock,
    so a test that asserts on a window, an elapse or a sweep must know exactly
    where the clock sits. The default instant sits inside the 08:00-to-17:00
    work window the supervision fixtures approve.
    """
    handle = Clock(api)
    handle.set(DEFAULT_CLOCK)
    return handle


@pytest.fixture
def build(api: ApiClient, clock: Clock) -> Builder:
    """Multi-step precondition builders for this API."""
    return Builder(api, clock)
