"""Composite fixtures and setup helpers.

The harness restarts the service before every test, so each test begins against an
empty laboratory and every piece of state below is built from scratch through the
published endpoints. Nothing here reaches around the API.

Two layers are offered:

* plain helper functions that take the client and return the created body, for tests
  that need to pin unusual field values while they build state;
* pytest fixtures that chain those helpers into the states the workflow reaches —
  a validated method, an accepted case, a queued request, an assigned request, a
  request in technical review, a released request, a reported case.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import LabApiClient
from .constants import CLOCK_START_UTC
from . import factories as f
from .test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)


# ─── Client ───────────────────────────────────────────

@pytest.fixture
def api() -> LabApiClient:
    """A client pointed at the service under test."""
    return LabApiClient()


# ─── Logical clock (PRD §2.5) ─────────────────────────

def set_clock(api: LabApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock to an instant."""
    return get_success_data(api.set_clock(current_utc, DIRECTOR_HEADERS))


@pytest.fixture
def clock(api: LabApiClient):
    """A handle that moves the logical clock and remembers where it stands."""

    class Clock:
        def __init__(self) -> None:
            self.now = CLOCK_START_UTC

        def set(self, current_utc: str) -> str:
            set_clock(api, current_utc)
            self.now = current_utc
            return current_utc

        def advance_days(self, days: int) -> str:
            return self.set(f.shift_days(self.now, days))

        def advance_minutes(self, minutes: int) -> str:
            return self.set(f.shift_minutes(self.now, minutes))

        def advance_seconds(self, seconds: int) -> str:
            return self.set(f.shift_seconds(self.now, seconds))

    return Clock()


# ─── Registry helpers ─────────────────────────────────

def register_analyst(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a bench examiner and return the Analyst body."""
    return get_success_data(
        api.create_analyst(f.analyst_payload(**kwargs), DIRECTOR_HEADERS), 201
    )


def create_method(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create a method and leave it in draft."""
    return get_success_data(
        api.create_method(f.method_payload(**kwargs), QUALITY_MANAGER_HEADERS), 201
    )


def validate_method(
    api: LabApiClient,
    method_id: str,
    validation_study_item_count: int = 24,
    precision_cv_pct: float = 2.50,
    expires_at_utc: str = "2027-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """Put a method into service until the stated expiry."""
    return get_success_data(
        api.validate_method(
            method_id,
            f.method_validation_payload(
                validation_study_item_count=validation_study_item_count,
                precision_cv_pct=precision_cv_pct,
                expires_at_utc=expires_at_utc,
            ),
            QUALITY_MANAGER_HEADERS,
        )
    )


def create_validated_method(
    api: LabApiClient,
    expires_at_utc: str = "2027-08-01T00:00:00Z",
    validation_study_item_count: int = 24,
    precision_cv_pct: float = 2.50,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a method and put it straight into service."""
    method = create_method(api, **kwargs)
    return validate_method(
        api,
        method["id"],
        validation_study_item_count=validation_study_item_count,
        precision_cv_pct=precision_cv_pct,
        expires_at_utc=expires_at_utc,
    )


def register_vendor(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a reference laboratory."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(**kwargs), DIRECTOR_HEADERS), 201
    )


# ─── Case intake helpers (PRD §3.1) ───────────────────

def submit_case(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Submit a case at the front counter."""
    return get_success_data(
        api.create_case(f.case_payload(**kwargs), TECHNICIAN_HEADERS), 201
    )


def log_evidence(api: LabApiClient, case_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Log one exhibit onto a submitted case."""
    return get_success_data(
        api.create_evidence_item(
            f.evidence_item_payload(case_id, **kwargs), TECHNICIAN_HEADERS
        ),
        201,
    )


def accept_case(api: LabApiClient, case_id: str) -> Dict[str, Any]:
    """Accept a case into the laboratory."""
    return get_success_data(
        api.accept_case(case_id, f.case_acceptance_payload(), TECHNICIAN_HEADERS)
    )


def accepted_case_with_items(
    api: LabApiClient,
    item_types: Optional[List[str]] = None,
    **case_kwargs: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Submit a case, log its exhibits, and accept it.

    Returns the accepted Case body and the list of EvidenceItem bodies.
    """
    case = submit_case(api, **case_kwargs)
    items = [
        log_evidence(api, case["id"], item_type=item_type)
        for item_type in (item_types or ["BIOLOGICAL"])
    ]
    accepted = accept_case(api, case["id"])
    return accepted, items


# ─── Casework helpers (PRD §3.3 - §3.6) ───────────────

def raise_request(
    api: LabApiClient,
    case_id: str,
    evidence_item_id: str,
    method_id: str,
    item_count: int = 1,
) -> Dict[str, Any]:
    """Raise an examination request against one exhibit and one method."""
    return get_success_data(
        api.create_examination_request(
            f.examination_request_payload(
                case_id, evidence_item_id, method_id, item_count=item_count
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )


def read_request(api: LabApiClient, request_id: str) -> Dict[str, Any]:
    """Read an examination request as the case manager."""
    return get_success_data(api.get_examination_request(request_id, CASE_MANAGER_HEADERS))


def assign_request(
    api: LabApiClient,
    request_id: str,
    analyst_id: str,
    expected_version: Optional[int] = None,
    assignment_reason: Any = None,
) -> Dict[str, Any]:
    """Place an examiner on a request, reading the current version when none is given."""
    if expected_version is None:
        expected_version = read_request(api, request_id)["version"]
    payload = f.assignment_payload(analyst_id, expected_version)
    if assignment_reason is not None:
        payload["assignment_reason"] = assignment_reason
    return get_success_data(
        api.create_assignment(request_id, payload, CASE_MANAGER_HEADERS), 201
    )


def auto_assign_request(api: LabApiClient, request_id: str) -> Dict[str, Any]:
    """Let the balancer choose the examiner."""
    return get_success_data(api.auto_assign(request_id, CASE_MANAGER_HEADERS), 201)


def start_analysis(api: LabApiClient, request_id: str, analyst_id: str) -> Dict[str, Any]:
    """Check the exhibit out and open the bench work."""
    return get_success_data(
        api.start_analysis(request_id, make_analyst_headers(analyst_id))
    )


def complete_analysis(
    api: LabApiClient,
    request_id: str,
    analyst_id: str,
    actual_hours: float = 4.00,
    evidence_consumed: Any = None,
) -> Dict[str, Any]:
    """Log the hours worked and send the request into technical review."""
    payload: Dict[str, Any] = {"actual_hours": actual_hours}
    if evidence_consumed is not None:
        payload["evidence_consumed"] = evidence_consumed
    return get_success_data(
        api.complete_analysis(request_id, payload, make_analyst_headers(analyst_id))
    )


def technical_review(
    api: LabApiClient,
    request_id: str,
    reviewer_analyst_id: str,
    decision: str = "AGREE",
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a peer's technical review."""
    return get_success_data(
        api.technical_review(
            request_id,
            f.technical_review_payload(decision, rationale),
            make_analyst_headers(reviewer_analyst_id),
        ),
        201,
    )


def administrative_review(
    api: LabApiClient,
    request_id: str,
    decision: str = "APPROVE",
    rationale: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record the coordinator's administrative review."""
    return get_success_data(
        api.administrative_review(
            request_id,
            f.administrative_review_payload(decision, rationale),
            headers or CASE_MANAGER_HEADERS,
        ),
        201,
    )


def disagreement_resolution(
    api: LabApiClient,
    request_id: str,
    decision: str = "UPHOLD_ANALYST",
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the quality manager's resolution of a technical disagreement."""
    return get_success_data(
        api.disagreement_resolution(
            request_id,
            f.disagreement_resolution_payload(decision, rationale),
            QUALITY_MANAGER_HEADERS,
        ),
        201,
    )


def carry_to_tech_review(
    api: LabApiClient,
    request_id: str,
    analyst_id: str,
    actual_hours: float = 4.00,
    evidence_consumed: Any = None,
) -> Dict[str, Any]:
    """Start and finish the bench work so the request sits in technical review."""
    start_analysis(api, request_id, analyst_id)
    return complete_analysis(
        api,
        request_id,
        analyst_id,
        actual_hours=actual_hours,
        evidence_consumed=evidence_consumed,
    )


def release_request(
    api: LabApiClient,
    request_id: str,
    analyst_id: str,
    reviewer_analyst_id: str,
    actual_hours: float = 4.00,
) -> Dict[str, Any]:
    """Take an assigned request all the way to released."""
    carry_to_tech_review(api, request_id, analyst_id, actual_hours=actual_hours)
    technical_review(api, request_id, reviewer_analyst_id, "AGREE")
    administrative_review(api, request_id, "APPROVE")
    return read_request(api, request_id)


def report_case(api: LabApiClient, case_id: str) -> Dict[str, Any]:
    """Report a case whose casework has all been released."""
    return get_success_data(
        api.report_case(case_id, f.case_report_payload(), CASE_MANAGER_HEADERS)
    )


# ─── Outsourcing helpers (PRD §3.7) ───────────────────

def award_engagement(
    api: LabApiClient,
    request_id: str,
    vendor_id: str,
    window_start_utc: str = "2026-08-05T00:00:00Z",
    window_end_utc: str = "2026-08-15T00:00:00Z",
    rush_flag: Any = None,
) -> Dict[str, Any]:
    """Send a queued request out to a reference laboratory."""
    payload = f.vendor_engagement_payload(
        vendor_id, window_start_utc=window_start_utc, window_end_utc=window_end_utc
    )
    if rush_flag is not None:
        payload["rush_flag"] = rush_flag
    return get_success_data(
        api.create_vendor_engagement(request_id, payload, CASE_MANAGER_HEADERS), 201
    )


def ship_engagement(api: LabApiClient, engagement_id: str) -> Dict[str, Any]:
    """Confirm the exhibit has left for the vendor."""
    return get_success_data(
        api.confirm_shipment(engagement_id, f.shipment_payload(), CASE_MANAGER_HEADERS)
    )


def return_engagement(
    api: LabApiClient, engagement_id: str, final_invoice_cents: int
) -> Dict[str, Any]:
    """Record the vendor's return and its invoice."""
    return get_success_data(
        api.record_return(
            engagement_id,
            f.record_return_payload(final_invoice_cents),
            CASE_MANAGER_HEADERS,
        )
    )


# ─── Quality helpers (PRD §3.8) ───────────────────────

def open_nonconformance(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Open a quality finding."""
    return get_success_data(
        api.create_nonconformance(
            f.nonconformance_payload(**kwargs), QUALITY_MANAGER_HEADERS
        ),
        201,
    )


def submit_root_cause(api: LabApiClient, nonconformance_id: str, **kwargs: Any) -> Dict[str, Any]:
    """File the root cause and corrective action plan."""
    return get_success_data(
        api.submit_root_cause(
            nonconformance_id, f.root_cause_payload(**kwargs), CASE_MANAGER_HEADERS
        )
    )


def decide_capa(
    api: LabApiClient, nonconformance_id: str, decision: str = "APPROVE"
) -> Dict[str, Any]:
    """Approve or reject a corrective action plan."""
    return get_success_data(
        api.capa_decision(
            nonconformance_id,
            f.capa_decision_payload(decision),
            QUALITY_MANAGER_HEADERS,
        )
    )


def close_nonconformance(api: LabApiClient, nonconformance_id: str) -> Dict[str, Any]:
    """Verify and close an approved corrective action."""
    return get_success_data(
        api.verify_close_nonconformance(
            nonconformance_id, f.closure_payload(), QUALITY_MANAGER_HEADERS
        )
    )


def resolve_nonconformance(api: LabApiClient, nonconformance_id: str) -> Dict[str, Any]:
    """Walk a finding from open to closed."""
    submit_root_cause(api, nonconformance_id)
    decide_capa(api, nonconformance_id, "APPROVE")
    return close_nonconformance(api, nonconformance_id)


def assign_proficiency_test(api: LabApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Book a proficiency test for an examiner on a method."""
    return get_success_data(
        api.create_proficiency_test(
            f.proficiency_test_payload(**kwargs), QUALITY_MANAGER_HEADERS
        ),
        201,
    )


def submit_proficiency_test(
    api: LabApiClient, proficiency_test_id: str, analyst_id: str
) -> Dict[str, Any]:
    """Submit a proficiency test as the examiner who sat it."""
    return get_success_data(
        api.submit_proficiency_test(
            proficiency_test_id, make_analyst_headers(analyst_id)
        )
    )


def score_proficiency_test(
    api: LabApiClient, proficiency_test_id: str, score_pct: float
) -> Dict[str, Any]:
    """Score a submitted proficiency test."""
    return get_success_data(
        api.score_proficiency_test(
            proficiency_test_id, f.score_payload(score_pct), QUALITY_MANAGER_HEADERS
        )
    )


def sit_proficiency_test(
    api: LabApiClient,
    analyst_id: str,
    method_id: str,
    score_pct: float,
    test_cycle: Optional[str] = None,
    due_utc: str = "2026-08-31T00:00:00Z",
) -> Dict[str, Any]:
    """Book, submit and score one proficiency test in a single step."""
    test = assign_proficiency_test(
        api,
        analyst_id=analyst_id,
        method_id=method_id,
        test_cycle=test_cycle,
        due_utc=due_utc,
    )
    submit_proficiency_test(api, test["id"], analyst_id)
    return score_proficiency_test(api, test["id"], score_pct)


# ─── Testimony helpers (PRD §3.9) ─────────────────────

def schedule_court_event(
    api: LabApiClient, request_id: str, analyst_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Book a testimony block for the examiner who owns the released casework."""
    return get_success_data(
        api.create_court_event(
            f.court_event_payload(request_id, analyst_id, **kwargs), CASE_MANAGER_HEADERS
        ),
        201,
    )


# ─── State-progression fixtures ───────────────────────

@pytest.fixture
def analyst(api: LabApiClient) -> Dict[str, Any]:
    """A qualified biology examiner with a forty-hour week and no training load."""
    return register_analyst(
        api,
        full_name="Dana Okonkwo",
        disciplines=["BIOLOGY"],
        competency_level=3,
        weekly_capacity_hours=40.00,
    )


@pytest.fixture
def reviewer_analyst(api: LabApiClient) -> Dict[str, Any]:
    """A second biology examiner, available to review a peer's casework."""
    return register_analyst(
        api,
        full_name="Priya Raman",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
    )


@pytest.fixture
def draft_method(api: LabApiClient) -> Dict[str, Any]:
    """A biology method that has been written up but not yet put into service."""
    return create_method(
        api, discipline="BIOLOGY", standard_hours_per_item=3.00, min_competency_level=1
    )


@pytest.fixture
def validated_method(api: LabApiClient) -> Dict[str, Any]:
    """A biology method in service, three hours per item, expiring well after the clock."""
    return create_validated_method(
        api,
        discipline="BIOLOGY",
        standard_hours_per_item=3.00,
        min_competency_level=1,
    )


@pytest.fixture
def submitted_case(api: LabApiClient) -> Dict[str, Any]:
    """A burglary case sitting at the front counter with no exhibits logged yet."""
    return submit_case(api, offense_category="BURGLARY")


@pytest.fixture
def accepted_case(api: LabApiClient) -> Dict[str, Any]:
    """A burglary case accepted into the laboratory with one sealed biological exhibit.

    Returns ``{"case": ..., "item": ...}``.
    """
    case, items = accepted_case_with_items(api, offense_category="BURGLARY")
    return {"case": case, "item": items[0]}


@pytest.fixture
def queued_request(api: LabApiClient, validated_method, accepted_case) -> Dict[str, Any]:
    """A one-item biology request queued against an accepted case.

    Returns ``{"case", "item", "method", "request"}``.
    """
    request = raise_request(
        api,
        accepted_case["case"]["id"],
        accepted_case["item"]["id"],
        validated_method["id"],
        item_count=1,
    )
    return {
        "case": accepted_case["case"],
        "item": accepted_case["item"],
        "method": validated_method,
        "request": request,
    }


@pytest.fixture
def assigned_request(api: LabApiClient, queued_request, analyst) -> Dict[str, Any]:
    """A queued request with an examiner placed on it.

    Returns the queued-request bundle plus ``{"analyst", "assignment", "request"}``.
    """
    assignment = assign_request(
        api,
        queued_request["request"]["id"],
        analyst["id"],
        expected_version=queued_request["request"]["version"],
    )
    bundle = dict(queued_request)
    bundle.update(
        {
            "analyst": analyst,
            "assignment": assignment,
            "request": read_request(api, queued_request["request"]["id"]),
        }
    )
    return bundle


@pytest.fixture
def request_in_analysis(api: LabApiClient, assigned_request) -> Dict[str, Any]:
    """An assigned request whose exhibit is checked out and whose bench work is open."""
    start_analysis(
        api, assigned_request["request"]["id"], assigned_request["analyst"]["id"]
    )
    bundle = dict(assigned_request)
    bundle["request"] = read_request(api, assigned_request["request"]["id"])
    return bundle


@pytest.fixture
def request_in_tech_review(api: LabApiClient, assigned_request) -> Dict[str, Any]:
    """A request whose bench work is finished and which awaits a peer's technical review."""
    carry_to_tech_review(
        api,
        assigned_request["request"]["id"],
        assigned_request["analyst"]["id"],
        actual_hours=4.00,
    )
    bundle = dict(assigned_request)
    bundle["request"] = read_request(api, assigned_request["request"]["id"])
    return bundle


@pytest.fixture
def request_in_admin_review(
    api: LabApiClient, request_in_tech_review, reviewer_analyst
) -> Dict[str, Any]:
    """A request a peer has agreed with, waiting on the coordinator's administrative review."""
    technical_review(
        api, request_in_tech_review["request"]["id"], reviewer_analyst["id"], "AGREE"
    )
    bundle = dict(request_in_tech_review)
    bundle["reviewer"] = reviewer_analyst
    bundle["request"] = read_request(api, request_in_tech_review["request"]["id"])
    return bundle


@pytest.fixture
def released_request(api: LabApiClient, request_in_admin_review) -> Dict[str, Any]:
    """A request the coordinator has approved and released."""
    administrative_review(api, request_in_admin_review["request"]["id"], "APPROVE")
    bundle = dict(request_in_admin_review)
    bundle["request"] = read_request(api, request_in_admin_review["request"]["id"])
    bundle["case"] = get_success_data(
        api.get_case(request_in_admin_review["case"]["id"], CASE_MANAGER_HEADERS)
    )
    return bundle


@pytest.fixture
def reported_case(api: LabApiClient, released_request) -> Dict[str, Any]:
    """A case whose only request has been released and which has now been reported."""
    bundle = dict(released_request)
    bundle["case"] = report_case(api, released_request["case"]["id"])
    return bundle


@pytest.fixture
def active_vendor(api: LabApiClient) -> Dict[str, Any]:
    """A biology-accredited reference laboratory with room and budget to spare."""
    return register_vendor(
        api,
        accredited_disciplines=["BIOLOGY"],
        concurrent_case_capacity=5,
        unit_price_cents=50000,
        contract_ceiling_cents=10000000,
    )
