"""
Composite setup builders.

The harness relaunches the API server before every individual test, so every
builder below starts from an empty database and constructs its preconditions
using nothing but the endpoints the PRD declares. Builders are plain functions
rather than pytest fixtures so a test can compose exactly the state its rule
needs — a state progression, an entity hierarchy, a full-lifecycle shortcut, an
accumulation targeted at a threshold, or a terminal row.

All setup calls go through get_success_data(), which is lenient about the exact
2xx status but produces a clear message when a precondition fails.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_START_DATE, CLOCK_START_INSTANT
from .factories import (
    accept_poa_payload,
    activate_action,
    add_days,
    approve_application_action,
    benefit_application_payload,
    claim_payload,
    clock_payload,
    complete_appointment_action,
    complete_prep_action,
    compute_report_payload,
    condition,
    decision_review_payload,
    discharge_document_payload,
    evidence_item_payload,
    exam_appointment_payload,
    exam_site_payload,
    file_claim_action,
    hold_discrepancy_action,
    instant,
    issue_action,
    mark_ready_action,
    open_evidence_development_action,
    outcome_report_payload,
    outreach_event_payload,
    poa_payload,
    receive_evidence_action,
    record_decision_payload,
    representative_payload,
    state_program_payload,
    submit_for_review_action,
    verify_document_action,
    veteran_payload,
)
from .test_users import (
    INTAKE_CLERK_HEADERS,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_county_officer_headers,
    make_veteran_client_headers,
)

# ─── Tier 1: the logical clock and single rows ─────────


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the server's logical clock to a supplied instant."""
    return get_success_data(
        api.set_clock(clock_payload(current_utc), SYSTEM_ADMIN_HEADERS)
    )


def set_clock_date(api: ApiClient, day: str, time_of_day: str = "00:00:00") -> Dict[str, Any]:
    """Move the clock to midnight (or a named time) of a calendar date."""
    return set_clock(api, instant(day, time_of_day))


def register_representative(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a roster row, which lands in PENDING accreditation status."""
    return get_success_data(
        api.create_representative(representative_payload(**kwargs), SYSTEM_ADMIN_HEADERS)
    )


def activate_representative(api: ApiClient, representative_id: str) -> Dict[str, Any]:
    """Drive PENDING to ACTIVE."""
    return get_success_data(
        api.representative_accreditation(
            representative_id, activate_action(), SYSTEM_ADMIN_HEADERS
        )
    )


def create_active_representative(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register and activate one representative, returning the ACTIVE row."""
    rep = register_representative(api, **kwargs)
    return activate_representative(api, rep["id"])


def create_active_representatives(
    api: ApiClient, count: int, **kwargs: Any
) -> List[Dict[str, Any]]:
    """A batch of ACTIVE representatives, created in order."""
    return [create_active_representative(api, **kwargs) for _ in range(count)]


def create_veteran(api: ApiClient, headers: Optional[Dict] = None, **kwargs: Any) -> Dict[str, Any]:
    """Open one intake record."""
    return get_success_data(
        api.create_veteran(veteran_payload(**kwargs), headers or INTAKE_CLERK_HEADERS)
    )


def read_veteran(api: ApiClient, veteran_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_veteran(veteran_id, headers or INTAKE_CLERK_HEADERS)
    )


def veteran_version(api: ApiClient, veteran_id: str) -> int:
    """The veteran's current version, for the optimistic-concurrency write."""
    return read_veteran(api, veteran_id)["version"]


def read_representative(api: ApiClient, representative_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_representative(representative_id, SYSTEM_ADMIN_HEADERS))


def read_claim(api: ApiClient, claim_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_claim(claim_id, headers or SYSTEM_ADMIN_HEADERS))


def read_exam_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exam_site(site_id, SYSTEM_ADMIN_HEADERS))


def read_state_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_state_program(program_id, SYSTEM_ADMIN_HEADERS))


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_state_benefit_application(application_id, SYSTEM_ADMIN_HEADERS)
    )


def read_decision_review(api: ApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_decision_review(review_id, SYSTEM_ADMIN_HEADERS))


def read_outcome_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_outcome_report(report_id, STATE_AUDITOR_HEADERS))


def read_caseload(api: ApiClient, representative_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_representative_caseload(representative_id, SYSTEM_ADMIN_HEADERS)
    )


def read_claim_evidence(api: ApiClient, claim_id: str, officer_headers: Dict) -> List[Dict[str, Any]]:
    """The claim's evidence file, the only discovery channel for synthesized items."""
    return get_success_data(api.list_claim_evidence_items(claim_id, officer_headers))


def read_screens(api: ApiClient, veteran_id: str) -> List[Dict[str, Any]]:
    """The veteran's append-only screen history."""
    return get_success_data(
        api.list_veteran_eligibility_screens(veteran_id, INTAKE_CLERK_HEADERS)
    )


# ─── Tier 2: intake, verification and screening ────────


def submit_discharge_document(
    api: ApiClient, veteran_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Submit separation paperwork, which lands in PENDING_VERIFICATION."""
    return get_success_data(
        api.create_discharge_document(
            veteran_id,
            discharge_document_payload(**kwargs),
            headers or INTAKE_CLERK_HEADERS,
        )
    )


def verify_discharge_document(
    api: ApiClient, document_id: str, officer_headers: Dict
) -> Dict[str, Any]:
    """Verify a submitted document, which establishes character of service."""
    return get_success_data(
        api.review_discharge_document(
            document_id, verify_document_action(), officer_headers
        )
    )


def hold_discharge_document(
    api: ApiClient, document_id: str, officer_headers: Dict, reason: str = "Dates disagree"
) -> Dict[str, Any]:
    return get_success_data(
        api.review_discharge_document(
            document_id, hold_discrepancy_action(reason), officer_headers
        )
    )


def screen_veteran(api: ApiClient, veteran_id: str, officer_headers: Dict) -> Dict[str, Any]:
    """Take one eligibility screen, which takes no request body at all."""
    return get_success_data(api.screen_veteran(veteran_id, officer_headers))


def create_verified_veteran(
    api: ApiClient,
    officer_headers: Dict,
    document_kwargs: Optional[Dict[str, Any]] = None,
    **veteran_kwargs: Any,
) -> Dict[str, Any]:
    """
    A veteran whose discharge_doc_status reads VERIFIED.

    Returns {"veteran": ..., "document": ...} with both rows re-read after the
    verification so their derived fields are current.
    """
    veteran = create_veteran(api, **veteran_kwargs)
    document = submit_discharge_document(
        api, veteran["id"], **(document_kwargs or {})
    )
    document = verify_discharge_document(api, document["id"], officer_headers)
    return {"veteran": read_veteran(api, veteran["id"]), "document": document}


def create_screened_veteran(
    api: ApiClient,
    officer_headers: Dict,
    document_kwargs: Optional[Dict[str, Any]] = None,
    **veteran_kwargs: Any,
) -> Dict[str, Any]:
    """
    A veteran in SCREENED with one screen on file.

    Returns {"veteran": ..., "document": ..., "screen": ...}.
    """
    built = create_verified_veteran(
        api, officer_headers, document_kwargs=document_kwargs, **veteran_kwargs
    )
    screen = screen_veteran(api, built["veteran"]["id"], officer_headers)
    return {
        "veteran": read_veteran(api, built["veteran"]["id"]),
        "document": built["document"],
        "screen": screen,
    }


# ─── Tier 2: designations ──────────────────────────────


def offer_designation(
    api: ApiClient,
    veteran_id: str,
    representative_id: str,
    headers: Optional[Dict] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Offer a designation, which commits nothing and counts nothing."""
    return get_success_data(
        api.create_power_of_attorney(
            poa_payload(veteran_id, representative_id, **kwargs),
            headers or INTAKE_CLERK_HEADERS,
        )
    )


def accept_designation(
    api: ApiClient, poa_id: str, veteran_id: str, expected_version: Optional[int] = None
) -> Dict[str, Any]:
    """The veteran accepts, supplying their last observed version."""
    version = (
        expected_version if expected_version is not None else veteran_version(api, veteran_id)
    )
    return get_success_data(
        api.accept_power_of_attorney(
            poa_id,
            accept_poa_payload(version),
            make_veteran_client_headers(veteran_id),
        )
    )


def create_active_designation(
    api: ApiClient,
    veteran_id: str,
    representative_id: str,
    headers: Optional[Dict] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Offer and accept in one step, leaving the designation ACTIVE."""
    poa = offer_designation(api, veteran_id, representative_id, headers, **kwargs)
    return accept_designation(api, poa["id"], veteran_id)


def create_represented_veteran(
    api: ApiClient,
    designee: Optional[Dict[str, Any]] = None,
    document_kwargs: Optional[Dict[str, Any]] = None,
    **veteran_kwargs: Any,
) -> Dict[str, Any]:
    """
    The standard preamble for claim work.

    Builds an ACTIVE representative who is both the designee on the veteran's
    ACTIVE designation and the officer preparing the claim, a verified and
    screened veteran, and the accepted designation between them.

    Returns {"designee", "officer_headers", "veteran", "document", "screen",
    "poa", "veteran_headers"}.
    """
    rep = designee or create_active_representative(api)
    officer_headers = make_county_officer_headers(rep["id"])
    built = create_screened_veteran(
        api, officer_headers, document_kwargs=document_kwargs, **veteran_kwargs
    )
    veteran = built["veteran"]
    poa = create_active_designation(api, veteran["id"], rep["id"])
    return {
        "designee": read_representative(api, rep["id"]),
        "officer_headers": officer_headers,
        "veteran": read_veteran(api, veteran["id"]),
        "veteran_headers": make_veteran_client_headers(veteran["id"]),
        "document": built["document"],
        "screen": built["screen"],
        "poa": poa,
    }


def fill_designation_ceiling(
    api: ApiClient, representative_id: str, count: int
) -> List[Dict[str, Any]]:
    """
    Accept `count` designations against one representative.

    Each designation needs its own veteran, because "a veteran can have at most
    one ACTIVE designation at a time".
    """
    accepted: List[Dict[str, Any]] = []
    for _ in range(count):
        veteran = create_veteran(api)
        accepted.append(
            create_active_designation(api, veteran["id"], representative_id)
        )
    return accepted


# ─── Tier 3: the claim lifecycle ───────────────────────


def create_draft_claim(
    api: ApiClient,
    veteran_id: str,
    poa_id: str,
    officer_headers: Dict,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Open a claim, which the server sets to DRAFT."""
    return get_success_data(
        api.create_claim(claim_payload(veteran_id, poa_id, **kwargs), officer_headers)
    )


def open_evidence_development(
    api: ApiClient, claim_id: str, officer_headers: Dict
) -> Dict[str, Any]:
    """Drive DRAFT to EVIDENCE_DEVELOPMENT as the preparer."""
    return get_success_data(
        api.claim_transition(
            claim_id, open_evidence_development_action(), officer_headers
        )
    )


def request_evidence(
    api: ApiClient, claim_id: str, officer_headers: Dict, **kwargs: Any
) -> Dict[str, Any]:
    """Request one piece of evidence, which lands in REQUESTED."""
    return get_success_data(
        api.create_evidence_item(claim_id, evidence_item_payload(**kwargs), officer_headers)
    )


def receive_evidence(
    api: ApiClient, item_id: str, officer_headers: Dict
) -> Dict[str, Any]:
    """Receive a requested item, which recomputes its weight_points."""
    return get_success_data(
        api.evidence_item_status(item_id, receive_evidence_action(), officer_headers)
    )


def add_received_evidence(
    api: ApiClient, claim_id: str, officer_headers: Dict, **kwargs: Any
) -> Dict[str, Any]:
    """Request and receive one item in a single step."""
    item = request_evidence(api, claim_id, officer_headers, **kwargs)
    return receive_evidence(api, item["id"], officer_headers)


def create_claim_in_evidence_development(
    api: ApiClient, context: Optional[Dict[str, Any]] = None, **claim_kwargs: Any
) -> Dict[str, Any]:
    """
    A claim sitting in EVIDENCE_DEVELOPMENT with its whole preamble.

    Returns the representation context extended with {"claim": ...}.
    """
    ctx = dict(context or create_represented_veteran(api))
    claim = create_draft_claim(
        api, ctx["veteran"]["id"], ctx["poa"]["id"], ctx["officer_headers"], **claim_kwargs
    )
    ctx["claim"] = open_evidence_development(api, claim["id"], ctx["officer_headers"])
    return ctx


def load_claim_above_threshold(
    api: ApiClient, claim_id: str, officer_headers: Dict
) -> List[Dict[str, Any]]:
    """
    Received evidence that carries a single-condition claim past 80.00 percent.

    A nexus letter at AT_LEAST_AS_LIKELY_AS_NOT scores 25.88 points and a
    service treatment record scores 20.00, so the pair earns 45.88 of the 55
    required points for one claimed condition.
    """
    first = add_received_evidence(
        api,
        claim_id,
        officer_headers,
        evidence_type="NEXUS_LETTER",
        nexus_opinion_strength="AT_LEAST_AS_LIKELY_AS_NOT",
    )
    second = add_received_evidence(
        api, claim_id, officer_headers, evidence_type="SERVICE_TREATMENT_RECORD"
    )
    return [first, second]


def submit_for_peer_review(
    api: ApiClient, claim_id: str, reviewer_id: str, officer_headers: Dict
) -> Dict[str, Any]:
    """Drive EVIDENCE_DEVELOPMENT to PEER_REVIEW, naming an independent reviewer."""
    return get_success_data(
        api.claim_transition(
            claim_id, submit_for_review_action(reviewer_id), officer_headers
        )
    )


def create_claim_in_peer_review(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    reviewer: Optional[Dict[str, Any]] = None,
    load_evidence: bool = True,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    A claim sitting in PEER_REVIEW with an independent reviewer nominated.

    Returns the context extended with {"claim", "reviewer", "reviewer_headers",
    "evidence"}.
    """
    ctx = create_claim_in_evidence_development(api, context, **claim_kwargs)
    ctx["reviewer"] = reviewer or create_active_representative(api)
    ctx["reviewer_headers"] = make_county_officer_headers(ctx["reviewer"]["id"])
    if load_evidence:
        ctx["evidence"] = load_claim_above_threshold(
            api, ctx["claim"]["id"], ctx["officer_headers"]
        )
    ctx["claim"] = submit_for_peer_review(
        api, ctx["claim"]["id"], ctx["reviewer"]["id"], ctx["officer_headers"]
    )
    return ctx


def mark_claim_ready(api: ApiClient, claim_id: str, reviewer_headers: Dict) -> Dict[str, Any]:
    """Drive PEER_REVIEW to READY_TO_FILE as the reviewer."""
    return get_success_data(
        api.claim_transition(claim_id, mark_ready_action(), reviewer_headers)
    )


def create_claim_ready_to_file(
    api: ApiClient, context: Optional[Dict[str, Any]] = None, **claim_kwargs: Any
) -> Dict[str, Any]:
    """A claim sitting in READY_TO_FILE."""
    ctx = create_claim_in_peer_review(api, context, **claim_kwargs)
    ctx["claim"] = mark_claim_ready(api, ctx["claim"]["id"], ctx["reviewer_headers"])
    return ctx


def file_claim(
    api: ApiClient, claim_id: str, officer_headers: Dict, filed_on: str = CLOCK_START_DATE
) -> Dict[str, Any]:
    """Drive READY_TO_FILE to FILED as the preparer."""
    return get_success_data(
        api.claim_transition(claim_id, file_claim_action(filed_on), officer_headers)
    )


def create_filed_claim(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    filed_on: str = CLOCK_START_DATE,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """A claim sitting in FILED."""
    ctx = create_claim_ready_to_file(api, context, **claim_kwargs)
    ctx["claim"] = file_claim(api, ctx["claim"]["id"], ctx["officer_headers"], filed_on)
    return ctx


def record_decision(
    api: ApiClient, claim_id: str, officer_headers: Dict, **kwargs: Any
) -> Dict[str, Any]:
    """Record the adjudicated decision on a filed claim."""
    return get_success_data(
        api.record_decision(claim_id, record_decision_payload(**kwargs), officer_headers)
    )


def create_decided_claim(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    decision_outcome: str = "GRANTED",
    awarded_rating_pct: int = 30,
    decided_on: str = CLOCK_START_DATE,
    filed_on: str = CLOCK_START_DATE,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """A claim sitting in DECIDED, with the veteran re-read afterwards."""
    ctx = create_filed_claim(api, context, filed_on=filed_on, **claim_kwargs)
    ctx["claim"] = record_decision(
        api,
        ctx["claim"]["id"],
        ctx["officer_headers"],
        decision_outcome=decision_outcome,
        awarded_rating_pct=awarded_rating_pct,
        decided_on=decided_on,
    )
    ctx["veteran"] = read_veteran(api, ctx["veteran"]["id"])
    return ctx


def add_decided_claim_to_context(
    api: ApiClient,
    ctx: Dict[str, Any],
    decision_outcome: str = "GRANTED",
    awarded_rating_pct: int = 30,
    decided_on: str = CLOCK_START_DATE,
    filed_on: str = CLOCK_START_DATE,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    Take a second claim of the same veteran all the way to DECIDED.

    Reuses the veteran, designation, preparer and reviewer already in `ctx`, so
    the combined rating is built from two decided claims of one veteran.
    """
    claim = create_draft_claim(
        api,
        ctx["veteran"]["id"],
        ctx["poa"]["id"],
        ctx["officer_headers"],
        **claim_kwargs,
    )
    open_evidence_development(api, claim["id"], ctx["officer_headers"])
    load_claim_above_threshold(api, claim["id"], ctx["officer_headers"])
    submit_for_peer_review(
        api, claim["id"], ctx["reviewer"]["id"], ctx["officer_headers"]
    )
    mark_claim_ready(api, claim["id"], ctx["reviewer_headers"])
    file_claim(api, claim["id"], ctx["officer_headers"], filed_on)
    return record_decision(
        api,
        claim["id"],
        ctx["officer_headers"],
        decision_outcome=decision_outcome,
        awarded_rating_pct=awarded_rating_pct,
        decided_on=decided_on,
    )


# ─── Tier 3: examination sites and appointments ────────


def create_exam_site(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Configure a contract examination facility."""
    return get_success_data(
        api.create_exam_site(exam_site_payload(**kwargs), SYSTEM_ADMIN_HEADERS)
    )


def book_appointment(
    api: ApiClient,
    claim_id: str,
    site_id: str,
    starts_at: str,
    ends_at: str,
    officer_headers: Dict,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Book one examination, which adds exactly one slot to the site."""
    return get_success_data(
        api.create_exam_appointment(
            exam_appointment_payload(claim_id, site_id, starts_at, ends_at, **kwargs),
            officer_headers,
        )
    )


def complete_appointment(
    api: ApiClient,
    appointment_id: str,
    officer_headers: Dict,
    completed_on: str = CLOCK_START_DATE,
) -> Dict[str, Any]:
    """Log the preparation session and then close the examination out."""
    get_success_data(
        api.exam_appointment_status(
            appointment_id, complete_prep_action(), officer_headers
        )
    )
    return get_success_data(
        api.exam_appointment_status(
            appointment_id, complete_appointment_action(completed_on), officer_headers
        )
    )


def create_claim_with_appointment(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    starts_at: str = instant("2026-09-01", "09:00:00"),
    ends_at: str = instant("2026-09-01", "10:00:00"),
    site_kwargs: Optional[Dict[str, Any]] = None,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    A claim in EVIDENCE_DEVELOPMENT with one SCHEDULED examination booked.

    Returns the context extended with {"claim", "site", "appointment"}.
    """
    ctx = create_claim_in_evidence_development(api, context, **claim_kwargs)
    ctx["site"] = create_exam_site(api, **(site_kwargs or {}))
    ctx["appointment"] = book_appointment(
        api,
        ctx["claim"]["id"],
        ctx["site"]["id"],
        starts_at,
        ends_at,
        ctx["officer_headers"],
    )
    ctx["site"] = read_exam_site(api, ctx["site"]["id"])
    return ctx


# ─── Tier 3: decision reviews ──────────────────────────


def create_decision_review(
    api: ApiClient, claim_id: str, officer_headers: Dict, **kwargs: Any
) -> Dict[str, Any]:
    """Record the counselling session, which lands in COUNSELED."""
    return get_success_data(
        api.create_decision_review(
            decision_review_payload(claim_id, **kwargs), officer_headers
        )
    )


def create_counseled_review(
    api: ApiClient, context: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """A decided claim with one COUNSELED review hanging off it."""
    ctx = context if context is not None else create_decided_claim(api)
    ctx["review"] = create_decision_review(
        api, ctx["claim"]["id"], ctx["officer_headers"], **kwargs
    )
    return ctx


# ─── Tier 4: programs, applications and the pool ───────


def create_state_program(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Configure a state benefit program for one fiscal year."""
    return get_success_data(
        api.create_state_program(state_program_payload(**kwargs), SYSTEM_ADMIN_HEADERS)
    )


def file_benefit_application(
    api: ApiClient,
    veteran_id: str,
    program: Dict[str, Any],
    headers: Optional[Dict] = None,
    expected_program_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """File an application against a program's pool at its current version."""
    version = (
        expected_program_version
        if expected_program_version is not None
        else read_state_program(api, program["id"])["version"]
    )
    payload = benefit_application_payload(
        veteran_id, program["id"], program["fiscal_year"], version, **kwargs
    )
    return get_success_data(
        api.create_state_benefit_application(payload, headers or INTAKE_CLERK_HEADERS)
    )


def approve_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    """Adjudicate an application favourably, which commits money to the pool."""
    return get_success_data(
        api.application_determination(
            application_id, approve_application_action(), STATE_AUDITOR_HEADERS
        )
    )


def issue_application(
    api: ApiClient, application_id: str, issued_on: str = CLOCK_START_DATE
) -> Dict[str, Any]:
    """Move the disbursement dimension from PENDING to ISSUED."""
    return get_success_data(
        api.application_disbursement(
            application_id, issue_action(issued_on), SYSTEM_ADMIN_HEADERS
        )
    )


def create_rated_veteran(
    api: ApiClient,
    awarded_rating_pct: int = 30,
    context: Optional[Dict[str, Any]] = None,
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    A veteran carrying a non-zero combined_rating_pct from one decided claim.

    This is the shortcut every state-benefit test needs, because the exemption
    rate and the program rating floor both read the veteran's combined rating.
    """
    return create_decided_claim(
        api,
        context,
        decision_outcome="GRANTED",
        awarded_rating_pct=awarded_rating_pct,
        **claim_kwargs,
    )


def create_submitted_application(
    api: ApiClient,
    program_kwargs: Optional[Dict[str, Any]] = None,
    application_kwargs: Optional[Dict[str, Any]] = None,
    awarded_rating_pct: int = 30,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A rated veteran, a configured program and one SUBMITTED application.

    Returns the claim context extended with {"program", "application"}.
    """
    ctx = create_rated_veteran(api, awarded_rating_pct, context)
    ctx["program"] = create_state_program(api, **(program_kwargs or {}))
    ctx["application"] = file_benefit_application(
        api, ctx["veteran"]["id"], ctx["program"], **(application_kwargs or {})
    )
    return ctx


def create_approved_application(
    api: ApiClient,
    program_kwargs: Optional[Dict[str, Any]] = None,
    application_kwargs: Optional[Dict[str, Any]] = None,
    awarded_rating_pct: int = 30,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An APPROVED application whose award is already committed to the pool."""
    ctx = create_submitted_application(
        api, program_kwargs, application_kwargs, awarded_rating_pct, context
    )
    ctx["application"] = approve_application(api, ctx["application"]["id"])
    ctx["program"] = read_state_program(api, ctx["program"]["id"])
    return ctx


# ─── Tier 4: outreach ──────────────────────────────────


def plan_outreach_event(
    api: ApiClient,
    representative_id: str,
    starts_at: str,
    ends_at: str,
    headers: Optional[Dict] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Plan one event on a representative's travel calendar."""
    return get_success_data(
        api.create_outreach_event(
            outreach_event_payload(representative_id, starts_at, ends_at, **kwargs),
            headers or SYSTEM_ADMIN_HEADERS,
        )
    )


# ─── Tier 5: quarterly reporting ───────────────────────


def open_outcome_report(
    api: ApiClient, officer_headers: Dict, fiscal_quarter: str = "2026Q2"
) -> Dict[str, Any]:
    """Open the report, which lands in OPEN with no weighting basis."""
    return get_success_data(
        api.create_outcome_report(outcome_report_payload(fiscal_quarter), officer_headers)
    )


def compute_outcome_report(
    api: ApiClient,
    report_id: str,
    officer_headers: Dict,
    weighting_basis: str = "CLAIM_WEIGHTED",
) -> Dict[str, Any]:
    """Score the closed quarter under a weighting basis."""
    return get_success_data(
        api.compute_outcome_report(
            report_id, compute_report_payload(weighting_basis), officer_headers
        )
    )


def create_computed_report(
    api: ApiClient,
    officer_headers: Dict,
    fiscal_quarter: str = "2026Q2",
    weighting_basis: str = "CLAIM_WEIGHTED",
    clock_after_quarter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    A report scored once, with the clock moved past the quarter's last day.

    Computing requires the clock date to be strictly later than the last
    calendar day of the labelled quarter.
    """
    report = open_outcome_report(api, officer_headers, fiscal_quarter)
    if clock_after_quarter is not None:
        set_clock_date(api, clock_after_quarter)
    return compute_outcome_report(api, report["id"], officer_headers, weighting_basis)


def create_submitted_report(
    api: ApiClient,
    officer_headers: Dict,
    fiscal_quarter: str = "2026Q2",
    weighting_basis: str = "CLAIM_WEIGHTED",
    clock_after_quarter: Optional[str] = None,
) -> Dict[str, Any]:
    """A report sitting in SUBMITTED, certified by the acting officer."""
    report = create_computed_report(
        api, officer_headers, fiscal_quarter, weighting_basis, clock_after_quarter
    )
    return get_success_data(api.submit_outcome_report(report["id"], officer_headers))


CLOCK_START = CLOCK_START_INSTANT
