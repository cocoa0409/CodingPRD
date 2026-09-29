"""Composite setup builders.

The harness restarts the service before every individual test, so each test
starts from an empty database and must build all of its preconditions through
the declared endpoints.  These builders are the shared vocabulary for that:
one thin function per write, plus a few composites that walk the canonical
vendor -> application -> request -> review chain to a chosen state and return
every identifier they minted.

Every builder acts as an explicitly named role, so identity threading is
visible at the call site rather than hidden.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_DEFAULT,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DISPOSITION_ACCEPT,
    ELEMENT_STUDENT_NAME,
    HARD_DELETE,
    TRIAGE_ACCEPT_FOR_REVIEW,
)
from .test_users import (
    make_admin_headers,
    make_analyst_headers,
    make_teacher_headers,
    make_telemetry_headers,
    make_vendor_liaison_headers,
)
from .types import ReviewChain

Json = Dict[str, Any]
Headers = Dict[str, str]


def _admin(headers: Optional[Headers]) -> Headers:
    return headers if headers is not None else make_admin_headers()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str = CLOCK_DEFAULT, headers=None) -> Json:
    """Move the logical clock.  Stores nothing and implies no sweep."""
    return get_success_data(api.set_clock(instant, _admin(headers)))


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


def register_vendor(api: ApiClient, headers=None, **overrides: Any) -> Json:
    """Register a vendor and return its row."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(**overrides), _admin(headers)), 201
    )


def read_vendor(api: ApiClient, vendor_id: str, headers=None) -> Json:
    return get_success_data(api.get_vendor(vendor_id, _admin(headers)))


def suspend_vendor(api: ApiClient, vendor_id: str, headers=None, **overrides) -> Json:
    return get_success_data(
        api.suspend_vendor(vendor_id, f.suspension_payload(**overrides), _admin(headers))
    )


def reinstate_vendor(api: ApiClient, vendor_id: str, headers=None, **overrides) -> Json:
    return get_success_data(
        api.reinstate_vendor(vendor_id, dict(overrides), _admin(headers))
    )


# ---------------------------------------------------------------------------
# Subprocessor
# ---------------------------------------------------------------------------


def disclose_subprocessor(
    api: ApiClient, vendor_id: str, headers=None, **overrides: Any
) -> Json:
    """Disclose a subprocessor for a vendor."""
    return get_success_data(
        api.create_subprocessor(
            f.subprocessor_payload(vendor_id, **overrides), _admin(headers)
        ),
        201,
    )


def review_subprocessor(
    api: ApiClient,
    subprocessor_id: str,
    disposition: str,
    analyst_headers: Headers,
    **overrides: Any,
) -> Json:
    """Record an analyst disposition on a disclosed subprocessor."""
    return get_success_data(
        api.review_subprocessor(
            subprocessor_id,
            f.subprocessor_review_payload(disposition, **overrides),
            analyst_headers,
        )
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def register_application(
    api: ApiClient, vendor_id: str, headers=None, **overrides: Any
) -> Json:
    """Register an application against a vendor."""
    return get_success_data(
        api.create_application(
            f.application_payload(vendor_id, **overrides), _admin(headers)
        ),
        201,
    )


def read_application(api: ApiClient, application_id: str, headers=None) -> Json:
    return get_success_data(api.get_application(application_id, _admin(headers)))


def application_version(api: ApiClient, application_id: str, headers=None) -> int:
    """Read the application's current optimistic-concurrency token."""
    return read_application(api, application_id, headers)["version"]


def attest_integration(
    api: ApiClient, application_id: str, headers=None, **overrides: Any
) -> Json:
    """Record the district's single sign-on and accessibility outcome."""
    return get_success_data(
        api.attest_integration(
            application_id, f.attestation_payload(**overrides), _admin(headers)
        )
    )


# ---------------------------------------------------------------------------
# Teacher and analyst
# ---------------------------------------------------------------------------


def enroll_teacher(api: ApiClient, headers=None, **overrides: Any) -> Json:
    """Enroll a teacher and return the row."""
    return get_success_data(
        api.create_teacher(f.teacher_payload(**overrides), _admin(headers)), 201
    )


def read_teacher(api: ApiClient, teacher_id: str, headers=None) -> Json:
    return get_success_data(api.get_teacher(teacher_id, _admin(headers)))


def enroll_analyst(
    api: ApiClient, credential_level: str = CREDENTIAL_SENIOR, headers=None, **overrides
) -> Json:
    """Enroll a privacy analyst and return the row."""
    return get_success_data(
        api.create_analyst(
            f.analyst_payload(credential_level, **overrides), _admin(headers)
        ),
        201,
    )


def read_analyst(api: ApiClient, analyst_id: str, headers=None) -> Json:
    return get_success_data(api.get_analyst(analyst_id, _admin(headers)))


# ---------------------------------------------------------------------------
# Application request
# ---------------------------------------------------------------------------


def draft_request(
    api: ApiClient,
    application_id: str,
    teacher_id: str,
    teacher_headers: Headers,
    **overrides: Any,
) -> Json:
    """A teacher drafts a request for an application."""
    return get_success_data(
        api.create_request(
            f.request_payload(application_id, teacher_id, **overrides), teacher_headers
        ),
        201,
    )


def read_request(api: ApiClient, request_id: str, headers=None) -> Json:
    return get_success_data(api.get_request(request_id, _admin(headers)))


def submit_request(
    api: ApiClient, request_id: str, teacher_headers: Headers, **overrides: Any
) -> Json:
    """The teacher submits or resubmits, overwriting the named draft fields."""
    return get_success_data(
        api.submit_request(request_id, f.submit_payload(**overrides), teacher_headers)
    )


def triage_request(
    api: ApiClient,
    request_id: str,
    disposition: str = TRIAGE_ACCEPT_FOR_REVIEW,
    headers=None,
    **overrides: Any,
) -> Json:
    """The privacy office triages a submitted request."""
    return get_success_data(
        api.triage_request(
            request_id, f.triage_payload(disposition, **overrides), _admin(headers)
        )
    )


# ---------------------------------------------------------------------------
# Data practice review
# ---------------------------------------------------------------------------


def open_review(
    api: ApiClient,
    source_request_id: str,
    assigned_analyst_id: str,
    headers=None,
    **overrides: Any,
) -> Json:
    """Open a review against a triaged request."""
    return get_success_data(
        api.create_review(
            f.review_payload(source_request_id, assigned_analyst_id, **overrides),
            _admin(headers),
        ),
        201,
    )


def read_review(api: ApiClient, review_id: str, headers=None) -> Json:
    return get_success_data(api.get_review(review_id, _admin(headers)))


def review_version(api: ApiClient, review_id: str, headers=None) -> int:
    """Read the review's current optimistic-concurrency token."""
    return read_review(api, review_id, headers)["version"]


def issue_findings(
    api: ApiClient,
    review_id: str,
    findings_count: int,
    assignee_headers: Headers,
    **overrides: Any,
) -> Json:
    """The assigned analyst issues a round of findings."""
    return get_success_data(
        api.issue_findings(
            review_id, f.findings_payload(findings_count, **overrides), assignee_headers
        )
    )


def submit_remediation(
    api: ApiClient,
    review_id: str,
    resolved_findings_count: int,
    liaison_headers: Headers,
    **overrides: Any,
) -> Json:
    """The vendor's own liaison answers the outstanding findings."""
    return get_success_data(
        api.submit_remediation(
            review_id,
            f.remediation_payload(resolved_findings_count, **overrides),
            liaison_headers,
        )
    )


def decide_review(
    api: ApiClient,
    review_id: str,
    disposition: str,
    decider_headers: Headers,
    **overrides: Any,
) -> Json:
    """A LEAD analyst who is not the assignee records the terminal decision."""
    return get_success_data(
        api.decide_review(
            review_id, f.decision_payload(disposition, **overrides), decider_headers
        )
    )


def reassign_review(
    api: ApiClient, review_id: str, assigned_analyst_id: str, headers=None, **overrides
) -> Json:
    """Move a screening review to a different analyst."""
    return get_success_data(
        api.reassign_review(
            review_id,
            f.reassign_payload(assigned_analyst_id, **overrides),
            _admin(headers),
        )
    )


# ---------------------------------------------------------------------------
# Data element commitment
# ---------------------------------------------------------------------------


def propose_commitment(
    api: ApiClient,
    review_id: str,
    element_code: str,
    author_headers: Headers,
    expected_review_version: Optional[int] = None,
    **overrides: Any,
) -> Json:
    """Attach a commitment to an open review.

    When no concurrency token is supplied the review is re-read first, which is
    exactly what the PRD requires of the next writer after each create bumps
    the review's version.
    """
    token = (
        expected_review_version
        if expected_review_version is not None
        else review_version(api, review_id)
    )
    return get_success_data(
        api.create_commitment(
            f.commitment_payload(review_id, element_code, token, **overrides),
            author_headers,
        ),
        201,
    )


def read_commitment(api: ApiClient, commitment_id: str, headers=None) -> Json:
    return get_success_data(api.get_commitment(commitment_id, _admin(headers)))


def decide_commitment(
    api: ApiClient,
    commitment_id: str,
    disposition: str,
    analyst_headers: Headers,
    **overrides: Any,
) -> Json:
    """An analyst other than the review's assignee accepts or rejects a row."""
    return get_success_data(
        api.decide_commitment(
            commitment_id,
            f.commitment_decision_payload(disposition, **overrides),
            analyst_headers,
        )
    )


# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------


def publish_entry(
    api: ApiClient,
    application_id: str,
    review_id: str,
    effective_from: str,
    expires_at: str,
    headers=None,
    **overrides: Any,
) -> Json:
    """Publish an approved application for a bounded authorization window."""
    return get_success_data(
        api.create_catalog_entry(
            f.catalog_entry_payload(
                application_id, review_id, effective_from, expires_at, **overrides
            ),
            _admin(headers),
        ),
        201,
    )


def read_entry(api: ApiClient, entry_id: str, headers=None) -> Json:
    return get_success_data(api.get_catalog_entry(entry_id, _admin(headers)))


def revoke_entry(
    api: ApiClient, entry_id: str, revoked_reason: str, headers=None, **overrides
) -> Json:
    return get_success_data(
        api.revoke_catalog_entry(
            entry_id, f.revoke_payload(revoked_reason, **overrides), _admin(headers)
        )
    )


def reauthorize_entry(
    api: ApiClient,
    entry_id: str,
    expires_at: str,
    application_id: str,
    expected_application_version: Optional[int] = None,
    headers=None,
    **overrides: Any,
) -> Json:
    """Reauthorize an entry, re-reading the application token when omitted."""
    token = (
        expected_application_version
        if expected_application_version is not None
        else application_version(api, application_id)
    )
    return get_success_data(
        api.reauthorize_catalog_entry(
            entry_id, f.reauthorize_payload(expires_at, token, **overrides), _admin(headers)
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Compliance sweep
# ---------------------------------------------------------------------------


def run_sweep(api: ApiClient, headers=None) -> Json:
    """Run the nightly sweep and return its five counters."""
    return get_success_data(api.run_sweep(_admin(headers)))


# ---------------------------------------------------------------------------
# Telemetry detection
# ---------------------------------------------------------------------------


def observe_detection(
    api: ApiClient,
    observed_domain: str,
    observed_at: str,
    application_id: Optional[str] = None,
    headers=None,
    **overrides: Any,
) -> Json:
    """A collector mints one observation.  Exclusive to the TelemetryAgent."""
    agent = headers if headers is not None else make_telemetry_headers()
    return get_success_data(
        api.create_detection(
            f.detection_payload(
                observed_domain, observed_at, application_id, **overrides
            ),
            agent,
        ),
        201,
    )


def read_detection(api: ApiClient, detection_id: str, headers=None) -> Json:
    return get_success_data(api.get_detection(detection_id, _admin(headers)))


def triage_detection(
    api: ApiClient, detection_id: str, disposition: str, headers=None, **overrides: Any
) -> Json:
    """Triage a detection once; a second attempt is refused by the service."""
    return get_success_data(
        api.triage_detection(
            detection_id,
            f.detection_triage_payload(disposition, **overrides),
            _admin(headers),
        )
    )


# ---------------------------------------------------------------------------
# Vendor incident
# ---------------------------------------------------------------------------


def report_incident(
    api: ApiClient, vendor_id: str, detected_at: str, headers=None, **overrides: Any
) -> Json:
    """Report a vendor privacy incident."""
    return get_success_data(
        api.create_incident(
            f.incident_payload(vendor_id, detected_at, **overrides), _admin(headers)
        ),
        201,
    )


def read_incident(api: ApiClient, incident_id: str, headers=None) -> Json:
    return get_success_data(api.get_incident(incident_id, _admin(headers)))


def contain_incident(
    api: ApiClient, incident_id: str, contained_at: Optional[str] = None, headers=None
) -> Json:
    return get_success_data(
        api.contain_incident(
            incident_id, f.containment_payload(contained_at), _admin(headers)
        )
    )


def send_notification(
    api: ApiClient, incident_id: str, notified_party_count: int, headers=None
) -> Json:
    return get_success_data(
        api.send_notification(
            incident_id, f.notification_payload(notified_party_count), _admin(headers)
        )
    )


def resolve_incident(
    api: ApiClient, incident_id: str, disposition: str, headers=None, **overrides
) -> Json:
    return get_success_data(
        api.resolve_incident(
            incident_id, f.resolution_payload(disposition, **overrides), _admin(headers)
        )
    )


# ---------------------------------------------------------------------------
# Composite chains
# ---------------------------------------------------------------------------


def screening_review_chain(
    api: ApiClient,
    clock: str = CLOCK_DEFAULT,
    vendor: Optional[Dict[str, Any]] = None,
    application: Optional[Dict[str, Any]] = None,
    request: Optional[Dict[str, Any]] = None,
    review: Optional[Dict[str, Any]] = None,
    teacher: Optional[Dict[str, Any]] = None,
    assignee_level: str = CREDENTIAL_SENIOR,
    assignee_capacity: int = 1200,
    decider_level: str = CREDENTIAL_LEAD,
    independent_level: str = CREDENTIAL_SENIOR,
    attest: bool = True,
    attestation: Optional[Dict[str, Any]] = None,
) -> ReviewChain:
    """Walk vendor -> application -> teacher -> request -> review to SCREENING.

    Three analysts are enrolled with distinct identifiers so the segregation of
    duties rungs are exercisable: the assignee who authors findings, a LEAD who
    can record the terminal decision, and an independent analyst who can
    disposition commitments.
    """
    set_clock(api, clock)
    v = register_vendor(api, **(vendor or {}))
    liaison = make_vendor_liaison_headers(v["id"])
    app = register_application(api, v["id"], **(application or {}))
    if attest:
        attest_integration(api, app["id"], **(attestation or {}))
    t = enroll_teacher(api, **(teacher or {}))
    teacher_headers = make_teacher_headers(t["id"])
    assignee = enroll_analyst(
        api, assignee_level, review_capacity_minutes=assignee_capacity
    )
    decider = enroll_analyst(api, decider_level)
    independent = enroll_analyst(api, independent_level)

    req = draft_request(api, app["id"], t["id"], teacher_headers, **(request or {}))
    submit_request(api, req["id"], teacher_headers)
    triage_request(api, req["id"], TRIAGE_ACCEPT_FOR_REVIEW)
    r = open_review(api, req["id"], assignee["id"], **(review or {}))

    return ReviewChain(
        vendor_id=v["id"],
        application_id=app["id"],
        teacher_id=t["id"],
        request_id=req["id"],
        review_id=r["id"],
        assignee_id=assignee["id"],
        liaison_headers=liaison,
        teacher_headers=teacher_headers,
        assignee_headers=make_analyst_headers(assignee["id"]),
        decider_id=decider["id"],
        decider_headers=make_analyst_headers(decider["id"]),
        independent_id=independent["id"],
        independent_headers=make_analyst_headers(independent["id"]),
        review_row=r,
    )


CommitmentSpec = Tuple[str, int, str]

DEFAULT_COMMITMENTS: Sequence[CommitmentSpec] = (
    (ELEMENT_STUDENT_NAME, 365, HARD_DELETE),
)


def attach_commitments(
    api: ApiClient,
    chain: ReviewChain,
    specs: Sequence[CommitmentSpec] = DEFAULT_COMMITMENTS,
    accept: bool = True,
) -> List[Json]:
    """Author one commitment per spec and optionally accept each of them.

    Each create re-reads the review's version first, because every create
    advances that version and the next writer needs the fresh token.
    """
    rows: List[Json] = []
    for element_code, retention_days, deletion_method in specs:
        row = propose_commitment(
            api,
            chain.review_id,
            element_code,
            chain.liaison_headers,
            retention_days=retention_days,
            deletion_method=deletion_method,
        )
        if accept:
            row = decide_commitment(
                api, row["id"], DISPOSITION_ACCEPT, chain.independent_headers
            )
        rows.append(row)
        chain.commitment_ids.append(row["id"])
    return rows


def decided_review_chain(
    api: ApiClient,
    disposition: str = "CLEAR",
    commitments: Sequence[CommitmentSpec] = DEFAULT_COMMITMENTS,
    accept_commitments: bool = True,
    findings_count: int = 0,
    **chain_kwargs: Any,
) -> ReviewChain:
    """Walk the chain all the way to a decided review.

    A findings round is mandatory before any decision, so one is issued with
    the supplied count; the default count of zero leaves
    `unresolved_findings_count` at zero, which is what a CLEAR requires.
    """
    chain = screening_review_chain(api, **chain_kwargs)
    attach_commitments(api, chain, commitments, accept=accept_commitments)
    issue_findings(api, chain.review_id, findings_count, chain.assignee_headers)
    chain.review_row = decide_review(
        api, chain.review_id, disposition, chain.decider_headers
    )
    return chain


def published_entry_chain(
    api: ApiClient,
    effective_from: str,
    expires_at: str,
    authorized_grade_band_low: int = 7,
    authorized_grade_band_high: int = 8,
    **chain_kwargs: Any,
) -> ReviewChain:
    """Walk the chain to a cleared review and publish one catalog entry.

    The entry is published by the privacy office admin, who carries no
    segregation-of-duties restriction, so the analysts stay available for
    whatever the test itself needs them for.
    """
    chain = decided_review_chain(api, **chain_kwargs)
    entry = publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        effective_from,
        expires_at,
        authorized_grade_band_low=authorized_grade_band_low,
        authorized_grade_band_high=authorized_grade_band_high,
    )
    chain.entry_id = entry["id"]
    return chain
