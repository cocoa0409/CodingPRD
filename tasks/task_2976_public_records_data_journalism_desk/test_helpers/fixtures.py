"""Composite setup helpers.

The harness restarts the server before every individual test, so every test
begins against an empty database and has to build all of its own preconditions
through the endpoints of PRD S4. These helpers are those chains, factored so a
test body contains only the trigger and the assertions.

Two disciplines are load-bearing here:

* **Fresh parent versions.** PRD S2.8 requires ``expected_desk_version`` on a
  records-request create and ``expected_investigation_version`` on an
  analysis-run create, and both parents' ``version`` moves under many of the
  chains below. Every helper therefore *re-reads* the parent immediately before
  the guarded create rather than caching a version from earlier in the chain.
* **Phased chains.** A bundled helper never performs a hop that would invalidate
  an earlier hop of its own. In particular a right-of-reply record has to exist
  *before* ``lock-findings`` runs, because PRD S3.8 makes that transition the
  only thing that moves the record ``DRAFT -> NOTICE_ELIGIBLE``, and attempts are
  only accepted from ``NOTICE_ELIGIBLE`` onward; so
  :func:`publishable_investigation` opens the subject record, then locks, then
  documents attempts.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from . import test_users as U

# --------------------------------------------------------------------------
# Tier 0: the logical clock
# --------------------------------------------------------------------------


def set_clock(api, instant: str) -> str:
    """Set the logical clock and return the ``current_utc`` it answers with."""
    data = get_success_data(api.set_clock(instant, U.editor_headers()))
    return data["current_utc"]


# --------------------------------------------------------------------------
# Tier 1: desk, agency and the records-request state progression
# --------------------------------------------------------------------------


def create_desk(api, **overrides: Any) -> Dict[str, Any]:
    """Register a desk (PRD S3.1)."""
    return get_success_data(
        api.create_desk(F.desk_payload(**overrides), U.editor_headers())
    )


def read_desk(api, desk_id: str) -> Dict[str, Any]:
    """Read a desk -- PRD S3.1 calls this "the sanctioned way" to get a version."""
    return get_success_data(api.get_desk(desk_id, U.editor_headers()))


def desk_version(api, desk_id: str) -> int:
    """The desk's current ``version``, read fresh (PRD S2.8)."""
    return read_desk(api, desk_id)["version"]


def create_agency(api, **overrides: Any) -> Dict[str, Any]:
    """Register the standard statutory profile (PRD S3.1)."""
    return get_success_data(
        api.create_agency(F.agency_payload(**overrides), U.coordinator_headers())
    )


def create_agency_from(api, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Register an agency from a fully built payload."""
    return get_success_data(api.create_agency(payload, U.coordinator_headers()))


def desk_and_agency(
    api,
    desk_overrides: Optional[Dict[str, Any]] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The universal setup pair: one desk and one agency."""
    desk = create_desk(api, **(desk_overrides or {}))
    agency = create_agency(api, **(agency_overrides or {}))
    return desk, agency


def draft_request(
    api,
    desk_id: str,
    agency_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a records request, reading a fresh desk version first (PRD S2.8)."""
    payload = F.records_request_payload(
        desk_id, agency_id, desk_version(api, desk_id), **overrides
    )
    return get_success_data(
        api.create_records_request(payload, headers or U.coordinator_headers())
    )


def submitted_request(
    api, desk_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A request in ``AWAITING_AGENCY_RESPONSE`` with both deadlines stamped."""
    request = draft_request(api, desk_id, agency_id, **overrides)
    return get_success_data(
        api.submit_records_request(request["id"], U.coordinator_headers())
    )


def fee_determined_request(
    api,
    desk_id: str,
    agency_id: str,
    search_hours: float = 3.5,
    billed_page_count: int = 120,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A submitted request whose fee has been determined and committed."""
    request = submitted_request(api, desk_id, agency_id, **(request_overrides or {}))
    return get_success_data(
        api.determine_fee(
            request["id"],
            F.fee_determination_payload(search_hours, billed_page_count),
            U.coordinator_headers(),
        )
    )


def released_request(
    api, desk_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A request in ``RELEASED`` -- the state a dataset delivery requires."""
    request = submitted_request(api, desk_id, agency_id, **overrides)
    return get_success_data(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(C.OUTCOME_RELEASED_FULL),
            U.coordinator_headers(),
        )
    )


def partially_released_request(
    api, desk_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A request in ``PARTIALLY_RELEASED`` -- appealable and deliverable."""
    request = submitted_request(api, desk_id, agency_id, **overrides)
    return get_success_data(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(C.OUTCOME_RELEASED_PARTIAL),
            U.coordinator_headers(),
        )
    )


def denied_request(api, desk_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    """A request in ``DENIED`` -- appealable on the denial ground (PRD S3.5)."""
    request = submitted_request(api, desk_id, agency_id, **overrides)
    return get_success_data(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(C.OUTCOME_DENIED),
            U.coordinator_headers(),
        )
    )


def file_appeal(
    api, request_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File an appeal on an already-ripe request (PRD S3.5)."""
    return get_success_data(
        api.create_appeal(F.appeal_payload(request_id, **overrides), U.legal_headers())
    )


def appealed_request(
    api, desk_id: str, agency_id: str, filing_fee_cents: int = 4500
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A denied request with an appeal in ``FILED``; returns ``(request, appeal)``."""
    request = denied_request(api, desk_id, agency_id)
    appeal = file_appeal(api, request["id"], filing_fee_cents=filing_fee_cents)
    request = get_success_data(
        api.get_records_request(request["id"], U.coordinator_headers())
    )
    return request, appeal


# --------------------------------------------------------------------------
# Tier 2: investigation and the dataset lifecycle
# --------------------------------------------------------------------------


def create_investigation(
    api,
    desk_id: str,
    publication_mode: str = C.MODE_FULL_DATA_RELEASE,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open an investigation with its publication mode declared (PRD S3.7)."""
    return get_success_data(
        api.create_investigation(
            F.investigation_payload(desk_id, publication_mode, **overrides),
            U.editor_headers(),
        )
    )


def read_investigation(api, investigation_id: str) -> Dict[str, Any]:
    """Read an investigation -- how PRD S2.8 says to get a fresh version."""
    return get_success_data(
        api.get_investigation(investigation_id, U.editor_headers())
    )


def investigation_version(api, investigation_id: str) -> int:
    """The investigation's current ``version``, read fresh (PRD S2.8)."""
    return read_investigation(api, investigation_id)["version"]


def register_dataset(
    api,
    request_id: str,
    investigation_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a dataset in ``RAW`` against its records request (PRD S3.6)."""
    payload = F.dataset_payload(
        request_id,
        investigation_id if investigation_id is not None else F.OMIT,
        **overrides,
    )
    return get_success_data(api.create_dataset(payload, U.reporter_headers()))


def delivered_dataset(
    api,
    request_id: str,
    investigation_id: Optional[str] = None,
    record_count: int = 500,
    delivered_format: str = C.FORMAT_CSV,
    **overrides: Any,
) -> Dict[str, Any]:
    """A dataset in ``CLEANING`` with its record count and retention stamped.

    The parent request must already be ``RELEASED`` or ``PARTIALLY_RELEASED``:
    PRD S3.6 refuses any earlier delivery with ``ERR_SOURCE_REQUEST_UNRESOLVED``.
    """
    dataset = register_dataset(api, request_id, investigation_id, **overrides)
    return get_success_data(
        api.deliver_dataset(
            dataset["id"],
            F.delivery_payload(delivered_format, record_count),
            U.reporter_headers(),
        )
    )


def document_field(
    api, dataset_id: str, field_name: str, **overrides: Any
) -> Dict[str, Any]:
    """Document one column of a dataset (PRD S3.6)."""
    return get_success_data(
        api.create_field_definition(
            dataset_id,
            F.field_definition_payload(field_name, **overrides),
            U.reporter_headers(),
        )
    )


def document_fields(
    api, dataset_id: str, specs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Document a list of columns, each spec being kwargs for the builder.

    Each spec must carry ``field_name``; everything else is optional.
    """
    created = []
    for spec in specs:
        spec = dict(spec)
        name = spec.pop("field_name")
        created.append(document_field(api, dataset_id, name, **spec))
    return created


def suppress_field(api, dataset_id: str, field_definition_id: str, **overrides: Any) -> Dict[str, Any]:
    """Suppress a documented column ahead of release (PRD S3.6)."""
    return get_success_data(
        api.suppress_field(
            dataset_id,
            F.field_suppression_payload(field_definition_id, **overrides),
            U.reporter_headers(),
        )
    )


DEFAULT_FIELD_SPECS: List[Dict[str, Any]] = [
    {"field_name": "permit_holder_zip", "reidentification_risk": 4},
    {"field_name": "permit_type", "reidentification_risk": 2},
]


def clean_locked_dataset(
    api,
    request_id: str,
    investigation_id: Optional[str] = None,
    record_count: int = 500,
    field_specs: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A dataset in ``CLEAN_LOCKED`` -- the only allocable state (PRD S3.7).

    ``expected_field_count`` is set to the number of documented columns so the
    documentation completes, which PRD S3.6 requires before the cleaning lock.
    """
    specs = field_specs if field_specs is not None else DEFAULT_FIELD_SPECS
    overrides.setdefault("expected_field_count", len(specs))
    dataset = delivered_dataset(
        api, request_id, investigation_id, record_count, **overrides
    )
    document_fields(api, dataset["id"], specs)
    return get_success_data(
        api.lock_cleaning(
            dataset["id"], F.cleaning_lock_payload(), U.reporter_headers()
        )
    )


def quarantined_dataset(
    api,
    request_id: str,
    investigation_id: Optional[str] = None,
    record_count: int = 500,
    **overrides: Any,
) -> Dict[str, Any]:
    """A dataset driven all the way to ``QUARANTINED`` (PRD S3.6)."""
    dataset = clean_locked_dataset(
        api, request_id, investigation_id, record_count, **overrides
    )
    return get_success_data(
        api.quarantine_dataset(
            dataset["id"], F.quarantine_payload(), U.editor_headers()
        )
    )


def read_dataset(api, dataset_id: str) -> Dict[str, Any]:
    """Read a dataset."""
    return get_success_data(api.get_dataset(dataset_id, U.reporter_headers()))


# --------------------------------------------------------------------------
# Tier 3: analysis runs and their two independent dimensions
# --------------------------------------------------------------------------


def create_run(
    api,
    investigation_id: str,
    compute_cost_cents: int = 12000,
    labor_hours: float = 3.5,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record an analysis run, reading a fresh investigation version first."""
    payload = F.analysis_run_payload(
        investigation_id,
        investigation_version(api, investigation_id),
        compute_cost_cents,
        labor_hours,
        **overrides,
    )
    return get_success_data(
        api.create_analysis_run(payload, headers or U.reporter_headers())
    )


def approved_run(
    api, investigation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A run whose ``code_review_status`` is ``APPROVED``.

    The peer reviewer is a *different* opaque identity from the author, which
    PRD S2.1 requires: a review from the author's own id is refused with
    ``ERR_SEGREGATION_OF_DUTIES``.
    """
    run = create_run(api, investigation_id, **overrides)
    return get_success_data(
        api.submit_peer_review(
            run["id"],
            F.peer_review_payload(C.REVIEW_APPROVED),
            U.peer_reviewer_headers(),
        )
    )


def allocated_run(api, investigation_id: str, **overrides: Any) -> Dict[str, Any]:
    """A run whose ``cost_allocation_status`` is ``ALLOCATED``.

    Requires at least one ``CLEAN_LOCKED`` dataset on the investigation, which
    PRD S3.7 makes a precondition (``ERR_NO_ALLOCABLE_INPUTS`` otherwise).
    """
    run = create_run(api, investigation_id, **overrides)
    return get_success_data(api.allocate_cost(run["id"], U.reporter_headers()))


def approved_and_allocated_run(
    api, investigation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A run that is both ``APPROVED`` and ``ALLOCATED`` (PRD S3.7 readiness).

    The two dimensions are advanced on the *same* run and in that order; PRD
    S3.7 states the peer review "leave[s] ``cost_allocation_status`` completely
    untouched", so neither hop undoes the other.
    """
    run = create_run(api, investigation_id, **overrides)
    get_success_data(
        api.submit_peer_review(
            run["id"],
            F.peer_review_payload(C.REVIEW_APPROVED),
            U.peer_reviewer_headers(),
        )
    )
    return get_success_data(api.allocate_cost(run["id"], U.reporter_headers()))


def read_run(api, run_id: str) -> Dict[str, Any]:
    """Read an analysis run."""
    return get_success_data(api.get_analysis_run(run_id, U.reporter_headers()))


# --------------------------------------------------------------------------
# Tier 4: findings, experts and the verification partition
# --------------------------------------------------------------------------


def create_finding(
    api, investigation_id: str, run_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Assert a finding in ``UNVERIFIED`` (PRD S3.8)."""
    return get_success_data(
        api.create_finding(
            F.finding_payload(investigation_id, run_id, **overrides),
            U.reporter_headers(),
        )
    )


def doc_matched_finding(
    api, investigation_id: str, run_id: str, matched_page: int = 14, **overrides: Any
) -> Dict[str, Any]:
    """A finding in ``DOC_MATCHED`` -- the only state an expert may review."""
    finding = create_finding(api, investigation_id, run_id, **overrides)
    return get_success_data(
        api.match_document(
            finding["id"],
            F.document_match_payload(matched_page),
            U.reporter_headers(),
        )
    )


def create_reviewer(api, **overrides: Any) -> Dict[str, Any]:
    """Register an expert reviewer (PRD S3.8)."""
    return get_success_data(
        api.create_expert_reviewer(
            F.expert_reviewer_payload(**overrides), U.editor_headers()
        )
    )


def assign_review(
    api,
    reviewer_id: str,
    finding_id: str,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Assign a document-matched finding to an expert (PRD S3.8)."""
    return get_success_data(
        api.create_review_assignment(
            F.review_assignment_payload(
                reviewer_id, finding_id, window_start, window_end, **overrides
            ),
            U.editor_headers(),
        )
    )


def verdict_on_finding(
    api,
    finding_id: str,
    verdict: str = C.VERDICT_CONFIRMED,
    reviewer: Optional[Dict[str, Any]] = None,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-05T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Register/assign/verdict in one chain.

    Returns ``(reviewer, assignment, assignment_after_verdict)``. The verdict is
    submitted with the reviewer's *own* id as ``X-User-ID``, which PRD S2.1
    requires of an ``ExpertReviewer`` caller.
    """
    reviewer = reviewer or create_reviewer(api)
    assignment = assign_review(
        api, reviewer["id"], finding_id, window_start, window_end
    )
    completed = get_success_data(
        api.submit_verdict(
            assignment["id"],
            F.verdict_payload(verdict),
            U.expert_reviewer_headers(reviewer["id"]),
        )
    )
    return reviewer, assignment, completed


def confirmed_finding(
    api, investigation_id: str, run_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A finding driven all the way to ``SME_CONFIRMED`` (PRD S3.8)."""
    finding = doc_matched_finding(api, investigation_id, run_id, **overrides)
    verdict_on_finding(api, finding["id"], C.VERDICT_CONFIRMED)
    return get_success_data(api.get_finding(finding["id"], U.reporter_headers()))


def read_finding(api, finding_id: str) -> Dict[str, Any]:
    """Read a finding."""
    return get_success_data(api.get_finding(finding_id, U.reporter_headers()))


# --------------------------------------------------------------------------
# Tier 5: readiness, the editorial lock and the publication ladder
# --------------------------------------------------------------------------

# The notice instants of the PRD S3.9 worked example: "with notice_sent_at at
# 2026-08-20T09:00:00Z, ... 2026-08-23T09:00:00Z gives exactly 72.000 hours and
# passes".
NOTICE_SENT_AT = "2026-08-20T09:00:00Z"
NOTICE_PLUS_72H = "2026-08-23T09:00:00Z"
NOTICE_JUST_UNDER_72H = "2026-08-23T08:59:59Z"


def ready_investigation(
    api,
    publication_mode: str = C.MODE_FULL_DATA_RELEASE,
    record_count: int = 500,
    field_specs: Optional[List[Dict[str, Any]]] = None,
    desk_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive an investigation to ``analysis_readiness == READY`` (PRD S3.7).

    The hop order is forced by the readiness definition: the finding must reach
    ``SME_CONFIRMED`` and the *current* run must end up both ``APPROVED`` and
    ``ALLOCATED``, so the run's two dimensions are advanced last -- creating a
    fresh run at any later point would drop readiness back to ``NOT_READY``.

    Returns a bundle of every row the caller may need to assert against.
    """
    desk, agency = desk_and_agency(api, desk_overrides=desk_overrides)
    request = released_request(api, desk["id"], agency["id"])
    investigation = create_investigation(api, desk["id"], publication_mode)
    dataset = clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=record_count,
        field_specs=field_specs,
    )
    run = create_run(api, investigation["id"])
    finding = doc_matched_finding(api, investigation["id"], run["id"])
    reviewer, assignment, _ = verdict_on_finding(
        api, finding["id"], C.VERDICT_CONFIRMED
    )
    get_success_data(
        api.submit_peer_review(
            run["id"],
            F.peer_review_payload(C.REVIEW_APPROVED),
            U.peer_reviewer_headers(),
        )
    )
    get_success_data(api.allocate_cost(run["id"], U.reporter_headers()))
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "investigation": read_investigation(api, investigation["id"]),
        "dataset": read_dataset(api, dataset["id"]),
        "run": read_run(api, run["id"]),
        "finding": read_finding(api, finding["id"]),
        "reviewer": reviewer,
        "assignment": assignment,
    }


def create_subject_record(
    api, investigation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a right-of-reply record in ``DRAFT`` (PRD S3.9)."""
    return get_success_data(
        api.create_subject_response_request(
            F.subject_response_request_payload(investigation_id, **overrides),
            U.coordinator_headers(),
        )
    )


def record_attempt(
    api, subject_request_id: str, deliverable: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Document one attempt to reach the subject (PRD S3.9)."""
    return get_success_data(
        api.record_attempt(
            subject_request_id,
            F.attempt_payload(deliverable=deliverable, **overrides),
            U.coordinator_headers(),
        )
    )


def read_subject_record(api, subject_request_id: str) -> Dict[str, Any]:
    """Read a right-of-reply record."""
    return get_success_data(
        api.get_subject_response_request(subject_request_id, U.coordinator_headers())
    )


def lock_findings(api, investigation_id: str) -> Dict[str, Any]:
    """Lock the investigation's findings (PRD S3.8)."""
    return get_success_data(api.lock_findings(investigation_id, U.editor_headers()))


def locked_investigation(
    api,
    publication_mode: str = C.MODE_FULL_DATA_RELEASE,
    subject_count: int = 0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A ``FINDINGS_LOCKED`` investigation, optionally with subject records.

    Any right-of-reply records are opened *before* the lock, because PRD S3.8
    makes the lock the transition that moves them ``DRAFT -> NOTICE_ELIGIBLE``;
    opening them afterwards would leave them stranded in ``DRAFT``.
    """
    bundle = ready_investigation(api, publication_mode, **kwargs)
    investigation_id = bundle["investigation"]["id"]
    subjects = [
        create_subject_record(
            api, investigation_id, subject_name=f"Named Subject {index + 1}"
        )
        for index in range(subject_count)
    ]
    bundle["subjects"] = [
        read_subject_record(api, subject["id"]) for subject in subjects
    ]
    bundle["locked"] = lock_findings(api, investigation_id)
    bundle["investigation"] = read_investigation(api, investigation_id)
    return bundle


def notify_subject(
    api, subject_request_id: str, attempts: int = 2
) -> Dict[str, Any]:
    """Send notice and document ``attempts`` deliverable attempts (PRD S3.9).

    Every attempt is ``deliverable`` true, so the record stays in
    ``NOTICE_SENT``: PRD S3.9 turns a second *undeliverable* attempt into
    ``UNREACHABLE``, which is a different gate story.
    """
    for _ in range(attempts):
        record_attempt(api, subject_request_id, deliverable=True)
    return read_subject_record(api, subject_request_id)


def publishable_investigation(
    api,
    publication_mode: str = C.MODE_FULL_DATA_RELEASE,
    record_count: int = 500,
    field_specs: Optional[List[Dict[str, Any]]] = None,
    subject_count: int = 1,
    notice_at: str = NOTICE_SENT_AT,
    publish_at: str = NOTICE_PLUS_72H,
) -> Dict[str, Any]:
    """Everything the publication ladder of PRD S3.9 needs, in phase order.

    Phases: build a ready investigation, open the right-of-reply records, lock
    the findings so those records become notice-eligible, park the clock at
    ``notice_at`` and document two attempts per record, then advance the clock to
    ``publish_at`` so the elapsed notice is at least the 72 hours PRD S3.9
    requires. The clock is deliberately moved *after* the attempts rather than
    before: the notice instant is stamped from the clock at the first attempt.
    """
    set_clock(api, notice_at)
    bundle = locked_investigation(
        api,
        publication_mode,
        subject_count=subject_count,
        record_count=record_count,
        field_specs=field_specs,
    )
    for subject in bundle["subjects"]:
        notify_subject(api, subject["id"], attempts=2)
    set_clock(api, publish_at)
    bundle["subjects"] = [
        read_subject_record(api, subject["id"]) for subject in bundle["subjects"]
    ]
    bundle["investigation"] = read_investigation(api, bundle["investigation"]["id"])
    return bundle


# --------------------------------------------------------------------------
# Tier 6: secure enclaves and desk security posture
# --------------------------------------------------------------------------


def create_enclave(api, **overrides: Any) -> Dict[str, Any]:
    """Register a secure reading room (PRD S3.9)."""
    return get_success_data(
        api.create_secure_enclave(F.secure_enclave_payload(**overrides), U.legal_headers())
    )


def book_session(
    api,
    enclave_id: str,
    dataset_id: str,
    start_at: str = "2026-08-20T09:00:00Z",
    end_at: str = "2026-08-20T11:00:00Z",
    document_count: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a supervised reading session (PRD S3.9)."""
    return get_success_data(
        api.create_enclave_session(
            F.enclave_session_payload(
                enclave_id, dataset_id, start_at, end_at, document_count, **overrides
            ),
            U.legal_headers(),
        )
    )


def close_session(api, session_id: str, documents_returned_count: int) -> Dict[str, Any]:
    """Close a session with every document accounted for (PRD S3.9)."""
    return get_success_data(
        api.close_enclave_session(
            session_id,
            F.session_closure_payload(documents_returned_count),
            U.legal_headers(),
        )
    )


def enclave_ready_dataset(api, **enclave_overrides: Any) -> Dict[str, Any]:
    """An enclave plus a ``CLEAN_LOCKED`` dataset that may be booked against it.

    PRD S3.9 admits only a ``CLEAN_LOCKED`` or ``QUARANTINED`` dataset into a
    session, so the dataset is driven to ``CLEAN_LOCKED`` here.
    """
    desk, agency = desk_and_agency(api)
    request = released_request(api, desk["id"], agency["id"])
    investigation = create_investigation(api, desk["id"])
    dataset = clean_locked_dataset(api, request["id"], investigation["id"])
    enclave = create_enclave(api, **enclave_overrides)
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "investigation": investigation,
        "dataset": dataset,
        "enclave": enclave,
    }


def drive_desk_to_lockdown(api, desk_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record a source-exposure incident, forcing ``LOCKDOWN`` (PRD S2.9).

    PRD S2.9 evaluates the posture in order and "if
    ``source_exposure_incident_count`` is at least 1 the posture is
    ``LOCKDOWN``", so one incident of any severity is enough.
    """
    return get_success_data(
        api.create_source_exposure_incident(
            desk_id,
            F.source_exposure_incident_payload(**overrides),
            U.editor_headers(),
        )
    )


def drive_desk_to_restricted(
    api, desk_id: str, agency_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Deny an appeal so the desk lands on ``RESTRICTED`` (PRD S2.9, S3.5).

    Returns ``(desk, request)``. The denial cascade of PRD S3.5 authorises
    litigation on the request, which raises ``litigation_exposure_count`` to 1
    and -- with no source incident recorded -- makes the posture ``RESTRICTED``.
    """
    request, appeal = appealed_request(api, desk_id, agency_id)
    get_success_data(
        api.decide_appeal(
            appeal["id"],
            F.appeal_decision_payload(C.APPEAL_DENIED),
            U.coordinator_headers(),
        )
    )
    return read_desk(api, desk_id), get_success_data(
        api.get_records_request(request["id"], U.coordinator_headers())
    )


def cleared_investigation(api, investigation_id: str) -> Dict[str, Any]:
    """Grant legal clearance, driving the investigation to ``CLEARED``."""
    return get_success_data(
        api.grant_legal_clearance(
            investigation_id, F.legal_clearance_payload(), U.legal_headers()
        )
    )
