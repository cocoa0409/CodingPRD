"""Composite setup helpers that walk the live API to a wanted state.

Every test starts against an empty deployment whose logical clock reads
2026-09-01T00:00:00Z, so each test rebuilds all of its preconditions through
the public API - nothing is seeded server side, and no helper ever reads
wall-clock time; time moves only through the clock endpoint.

Setup calls use the lenient success reader, so a broken precondition surfaces
as "Setup step failed" rather than as a confusing assertion error deep in a
test.

Composite fixtures return a context dict keyed by entity name
("jurisdiction", "client", "intake", "case", "item", "authorization",
"analysis", "petition", "claim", "provider", "referral", "initiative",
"records_request") so a test can read any intermediate artifact.

Identity discipline: the recommender (IntakeSpecialist) and the decider
(ManagingAttorney) always carry DIFFERENT opaque X-User-IDs (segregation of
duties, PRD section 3.2); the Client role is entity-backed, so any
ownership-gated Client call is made with make_client_headers(client.id).
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import api_client
from .test_users import (
    INTAKE_SPECIALIST_ID,
    MANAGING_ATTORNEY_ID,
    STAFF_ATTORNEY_ID,
    TEST_USERS,
    make_client_headers,
    make_intake_specialist_headers,
    make_managing_attorney_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SPECIALIST = TEST_USERS["intake_specialist_headers"]
DECIDER = TEST_USERS["managing_attorney_headers"]
ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]
ADVOCATE = TEST_USERS["client_services_advocate_headers"]
POLICY = TEST_USERS["policy_director_headers"]


# =============================================================================
# Tier 1 - primitives: clock, sweeps, plain creates, reads, single advances
# =============================================================================

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Reposition the logical clock. Returns the reported clock payload."""
    return get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), ADMIN))


def run_contact_overdue_sweep() -> Dict[str, Any]:
    """Run the contact-overdue checkpoint across every non-CLOSED case."""
    return get_success_data(api_client.run_contact_overdue_sweep(ADMIN))


def create_jurisdiction(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_jurisdiction(
        f.create_jurisdiction_payload(**overrides), ADMIN
    ))


def create_client(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_client(
        f.create_client_payload(**overrides), SPECIALIST
    ))


def create_intake_request(
    client_id: str, jurisdiction_id: str, as_client_self_submit: bool = False, **overrides: Any
) -> Dict[str, Any]:
    """Create an intake request. When as_client_self_submit is True the call
    is made by the owning Client (client_id == X-User-ID)."""
    headers = make_client_headers(client_id) if as_client_self_submit else SPECIALIST
    return get_success_data(api_client.create_intake_request(
        f.create_intake_request_payload(client_id, jurisdiction_id, **overrides), headers
    ))


def get_intake_request(request_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_intake_request(request_id, headers or SPECIALIST))


def get_case(case_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_case(case_id, headers or ATTORNEY))


def get_evidence_item(item_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_evidence_item(item_id, headers or ANALYST))


def get_testing_authorization(
    authorization_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api_client.get_testing_authorization(authorization_id, headers or ATTORNEY))


def get_reentry_provider(provider_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_reentry_provider(provider_id, headers or ADVOCATE))


def list_rows(response) -> tuple:
    """(data_list, meta) for any list endpoint."""
    return validate_paginated(response)


# ── Intake transitions ───────────────────────────────────────────────────────

def advance_intake(
    request_id: str,
    event: Any,
    recommendation: Optional[Any] = None,
    specialist_id: str = INTAKE_SPECIALIST_ID,
) -> Dict[str, Any]:
    return get_success_data(api_client.advance_intake_request(
        request_id,
        f.intake_advance_payload(event, recommendation),
        make_intake_specialist_headers(specialist_id),
    ))


def submit_supplement(
    request_id: str, supplement_notes: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """MORE_INFO_REQUESTED -> SCREENING. Caller may be the owning Client
    (make_client_headers(client_id)) or an IntakeSpecialist."""
    return get_success_data(api_client.submit_intake_supplement(
        request_id, f.submit_supplement_payload(supplement_notes), headers or SPECIALIST
    ))


def decide_intake(
    request_id: str,
    decision: Any,
    decider_id: str = MANAGING_ATTORNEY_ID,
    assigned_attorney_id: Optional[str] = STAFF_ATTORNEY_ID,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.decide_intake_request(
        request_id,
        f.decide_payload(
            decision,
            assigned_attorney_id=assigned_attorney_id,
            rejection_reason=rejection_reason,
        ),
        make_managing_attorney_headers(decider_id),
    ))


def activate_waitlist_next() -> Dict[str, Any]:
    return get_success_data(api_client.activate_waitlist_next(DECIDER))


# ── Case transitions / updates / contact ─────────────────────────────────────

def advance_case(case_id: str, event: Any, headers: Optional[Dict[str, str]] = None, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_case(
        case_id, f.case_advance_payload(event, **fields), headers or ATTORNEY
    ))


def update_case(
    case_id: str, expected_case_version: int, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(api_client.update_case(
        case_id, f.case_update_payload(expected_case_version, **fields), ATTORNEY
    ))


def log_contact(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.log_case_contact(
        case_id, f.log_contact_payload(**overrides), ADVOCATE
    ))


# ── Evidence items ───────────────────────────────────────────────────────────

def create_evidence_item(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_evidence_item(
        f.create_evidence_item_payload(case_id, **overrides), ANALYST
    ))


def advance_evidence_item(item_id: str, event: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_evidence_item(
        item_id, f.evidence_advance_payload(event), ANALYST
    ))


def walk_item_to_custody_confirmed(item_id: str) -> Dict[str, Any]:
    """IDENTIFIED -> SEARCHING -> LOCATED -> CUSTODY_CONFIRMED."""
    advance_evidence_item(item_id, "START_SEARCH")
    advance_evidence_item(item_id, "MARK_LOCATED")
    return advance_evidence_item(item_id, "CONFIRM_CUSTODY")


# ── Records requests ─────────────────────────────────────────────────────────

def create_records_request(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_records_request(
        f.create_records_request_payload(case_id, **overrides), ANALYST
    ))


def advance_records_request(request_id: str, event: Any, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_records_request(
        request_id, f.records_advance_payload(event, **fields), ANALYST
    ))


def respond_records_request(
    request_id: str,
    disposition: Any,
    items_revealed: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Record the agency's response; each reveal applies in array order."""
    return advance_records_request(
        request_id, "RECORD_RESPONSE", disposition=disposition, items_revealed=items_revealed
    )


# ── Testing authorizations ───────────────────────────────────────────────────

def create_testing_authorization(
    case_id: str, evidence_item_id: str, kind: Any = "AGREEMENT", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(api_client.create_testing_authorization(
        f.create_testing_authorization_payload(case_id, evidence_item_id, kind, **overrides),
        ATTORNEY,
    ))


def advance_testing_authorization(authorization_id: str, event: Any, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_testing_authorization(
        authorization_id, f.authorization_advance_payload(event, **fields), ATTORNEY
    ))


def amend_testing_authorization(
    authorization_id: str, expected_testing_authorization_version: int, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(api_client.amend_testing_authorization(
        authorization_id,
        f.amendment_payload(expected_testing_authorization_version, **fields),
        ATTORNEY,
    ))


def sign_agreement(authorization_id: str) -> Dict[str, Any]:
    """AGREEMENT path to effectiveness: DRAFTED -> PROPOSED -> SIGNED."""
    advance_testing_authorization(authorization_id, "PROPOSE")
    return advance_testing_authorization(authorization_id, "SIGN")


def grant_motion(authorization_id: str) -> Dict[str, Any]:
    """MOTION path to effectiveness: DRAFTED -> FILED -> GRANTED."""
    advance_testing_authorization(authorization_id, "FILE")
    return advance_testing_authorization(authorization_id, "RECORD_RULING", ruling="GRANTED")


# ── Lab analyses ─────────────────────────────────────────────────────────────

def create_lab_analysis(
    evidence_item_id: str, authorization_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(api_client.create_lab_analysis(
        f.create_lab_analysis_payload(evidence_item_id, authorization_id, **overrides), ATTORNEY
    ))


def advance_lab_analysis(
    analysis_id: str, event: Any, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(api_client.advance_lab_analysis(
        analysis_id, f.lab_advance_payload(event, **fields), headers or ATTORNEY
    ))


def ship_sample(analysis_id: str) -> Dict[str, Any]:
    return advance_lab_analysis(analysis_id, "SHIP_SAMPLE", headers=ANALYST)


def record_result(
    analysis_id: str,
    outcome: Any = "EXCLUSIONARY",
    actual_consumed_ng: int = 1,
    profile_obtained: bool = True,
) -> Dict[str, Any]:
    """SAMPLE_SHIPPED -> RESULT_RECORDED; settles the sample ledger.
    actual_consumed_ng must be supplied (1..reserved_sample_ng): the PRD
    declares no GET /lab-analyses/{id} endpoint, so the caller - which created
    the analysis - is the authority on the reserved mass."""
    return advance_lab_analysis(
        analysis_id,
        "RECORD_RESULT",
        headers=ANALYST,
        outcome=outcome,
        actual_consumed_ng=actual_consumed_ng,
        profile_obtained=profile_obtained,
    )


def record_expert_interpretation(
    analysis_id: str,
    expert_name: str = "Dr. Elena Voss",
    expert_interpretation: Any = "SUPPORTS_INNOCENCE",
) -> Dict[str, Any]:
    return advance_lab_analysis(
        analysis_id,
        "RECORD_EXPERT_INTERPRETATION",
        expert_name=expert_name,
        expert_interpretation=expert_interpretation,
    )


def run_database_comparison(
    analysis_id: str,
    comparison_result: Any = "HIT",
    database_name: str = "STATE_OFFENDER_DB",
    matched_subject_name: Optional[str] = None,
) -> Dict[str, Any]:
    if matched_subject_name is None and str(comparison_result) == "HIT":
        matched_subject_name = "John Doe"
    return advance_lab_analysis(
        analysis_id,
        "RUN_DATABASE_COMPARISON",
        database_name=database_name,
        comparison_result=comparison_result,
        matched_subject_name=matched_subject_name,
    )


def cancel_lab_analysis(analysis_id: str) -> Dict[str, Any]:
    return advance_lab_analysis(analysis_id, "CANCEL", headers=ANALYST)


# ── Legal petitions ──────────────────────────────────────────────────────────

def create_legal_petition(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_legal_petition(
        f.create_legal_petition_payload(case_id, **overrides), ATTORNEY
    ))


def advance_legal_petition(petition_id: str, event: Any, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_legal_petition(
        petition_id, f.petition_advance_payload(event, **fields), ATTORNEY
    ))


def file_petition(petition_id: str) -> Dict[str, Any]:
    return advance_legal_petition(petition_id, "FILE")


def record_petition_decision(
    petition_id: str, decision: Any, vacates_conviction: Optional[bool] = None
) -> Dict[str, Any]:
    return advance_legal_petition(
        petition_id, "RECORD_DECISION", decision=decision, vacates_conviction=vacates_conviction
    )


# ── Compensation claims ──────────────────────────────────────────────────────

def create_compensation_claim(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_compensation_claim(
        f.create_compensation_claim_payload(case_id, **overrides), ATTORNEY
    ))


def advance_compensation_claim(claim_id: str, event: Any, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_compensation_claim(
        claim_id, f.claim_advance_payload(event, **fields), ATTORNEY
    ))


def file_claim(claim_id: str) -> Dict[str, Any]:
    return advance_compensation_claim(claim_id, "FILE")


def record_claim_decision(claim_id: str, decision: Any) -> Dict[str, Any]:
    return advance_compensation_claim(claim_id, "RECORD_DECISION", decision=decision)


def record_claim_payment(claim_id: str, paid_amount_cents: int) -> Dict[str, Any]:
    return advance_compensation_claim(claim_id, "RECORD_PAYMENT", paid_amount_cents=paid_amount_cents)


# ── Reentry providers & referrals ────────────────────────────────────────────

def create_reentry_provider(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_reentry_provider(
        f.create_reentry_provider_payload(**overrides), ADVOCATE
    ))


def create_reentry_referral(case_id: str, provider_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_reentry_referral(
        f.create_reentry_referral_payload(case_id, provider_id, **overrides), ADVOCATE
    ))


def advance_reentry_referral(referral_id: str, event: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_reentry_referral(
        referral_id, f.referral_advance_payload(event), ADVOCATE
    ))


# ── Policy initiatives ───────────────────────────────────────────────────────

def create_policy_initiative(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_policy_initiative(
        f.create_policy_initiative_payload(jurisdiction_id, **overrides), POLICY
    ))


def advance_policy_initiative(initiative_id: str, event: Any) -> Dict[str, Any]:
    return get_success_data(api_client.advance_policy_initiative(
        initiative_id, f.policy_advance_payload(event), POLICY
    ))


# =============================================================================
# Tier 2 - intake pipeline: jurisdiction + client + request walked to a state
# =============================================================================

def setup_intake_pipeline(
    *,
    jurisdiction_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
    intake_overrides: Optional[Dict[str, Any]] = None,
    jurisdiction_id: Optional[str] = None,
    client_id: Optional[str] = None,
    recommendation: Optional[Any] = None,
    decision: Optional[Any] = None,
    specialist_id: str = INTAKE_SPECIALIST_ID,
    decider_id: str = MANAGING_ATTORNEY_ID,
    assigned_attorney_id: Optional[str] = STAFF_ATTORNEY_ID,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Jurisdiction + client + intake request, then as far down the screening
    pipeline as requested: None -> RECEIVED; recommendation=... -> SCREENING,
    BEGIN_SCREENING, RECOMMEND; decision=... -> DECISION_PENDING, decide.

    Pass jurisdiction_id / client_id to reuse standing reference data instead
    of creating fresh rows - multi-case and multi-request worlds (subresource
    isolation, waitlist ranking, pattern thresholds) share one jurisdiction
    this way.

    The recommender and the decider always carry distinct X-User-IDs.
    Returns {"jurisdiction", "client", "intake"} (intake re-read at the end),
    plus "case" when the decision was ACCEPTED. Reused jurisdiction/client
    slots carry None - only their ids are known.
    """
    if decision is not None and recommendation is None:
        raise ValueError("decision requires recommendation (decide is legal only from DECISION_PENDING)")
    if client_id is not None and jurisdiction_id is None:
        raise ValueError("client_id reuse requires jurisdiction_id")
    jurisdiction: Optional[Dict[str, Any]] = None
    if jurisdiction_id is None:
        jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
        jurisdiction_id = jurisdiction["id"]
    client: Optional[Dict[str, Any]] = None
    if client_id is None:
        client = create_client(**(client_overrides or {}))
        client_id = client["id"]
    intake = create_intake_request(client_id, jurisdiction_id, **(intake_overrides or {}))
    ctx: Dict[str, Any] = {
        "jurisdiction": jurisdiction,
        "client": client,
        "intake": intake,
    }
    if recommendation is not None:
        advance_intake(intake["id"], "BEGIN_SCREENING", specialist_id=specialist_id)
        intake = advance_intake(
            intake["id"], "RECOMMEND", recommendation=recommendation, specialist_id=specialist_id
        )
        ctx["intake"] = intake
    if decision is not None:
        intake = decide_intake(
            intake["id"],
            decision,
            decider_id=decider_id,
            assigned_attorney_id=assigned_attorney_id,
            rejection_reason=rejection_reason,
        )
        ctx["intake"] = intake
        if decision == "ACCEPTED" or getattr(decision, "value", None) == "ACCEPTED":
            ctx["case"] = get_case(intake["accepted_case_id"])
    return ctx


def setup_accepted_case(**kwargs: Any) -> Dict[str, Any]:
    """Full intake -> screening -> RECOMMEND ACCEPT -> decide ACCEPTED chain.
    Returns ctx whose "case" is the freshly minted OPEN Case."""
    kwargs["recommendation"] = "ACCEPT"
    kwargs["decision"] = "ACCEPTED"
    return setup_intake_pipeline(**kwargs)


def setup_waitlisted_request(**kwargs: Any) -> Dict[str, Any]:
    """One request parked in WAITLISTED: RECOMMEND WAITLIST + decide
    WAITLISTED, freezing waitlist_priority_score from the variant the
    request's expedited_review flag selects. Reuses an existing
    jurisdiction/client when jurisdiction_id / client_id are supplied -
    waitlist ranking tests park several requests under one jurisdiction."""
    kwargs["recommendation"] = "WAITLIST"
    kwargs["decision"] = "WAITLISTED"
    return setup_intake_pipeline(**kwargs)


# =============================================================================
# Context extenders - grow an existing ctx (for multi-item / hybrid worlds)
# =============================================================================

def add_evidence_item(
    ctx: Dict[str, Any],
    location: str = "CUSTODY_CONFIRMED",
    **item_overrides: Any,
) -> Dict[str, Any]:
    """Register another evidence item on ctx's case and walk its location
    dimension; stores it under ctx["item"] (the prior item stays reachable
    via ctx.setdefault("items", ...) history)."""
    ctx.setdefault("items", []).append(ctx["item"]) if "item" in ctx else None
    item = create_evidence_item(ctx["case"]["id"], **item_overrides)
    if location not in ("IDENTIFIED", "SEARCHING", "LOCATED", "CUSTODY_CONFIRMED"):
        raise ValueError(f"unsupported walk target {location!r}")
    if location in ("SEARCHING", "LOCATED", "CUSTODY_CONFIRMED"):
        item = advance_evidence_item(item["id"], "START_SEARCH")
    if location in ("LOCATED", "CUSTODY_CONFIRMED"):
        item = advance_evidence_item(item["id"], "MARK_LOCATED")
    if location == "CUSTODY_CONFIRMED":
        item = advance_evidence_item(item["id"], "CONFIRM_CUSTODY")
    ctx["item"] = item
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def advance_case_to(ctx: Dict[str, Any], event: Any, **fields: Any) -> Dict[str, Any]:
    """Advance ctx's case through one lifecycle event and re-read it."""
    advance_case(ctx["case"]["id"], event, **fields)
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def add_effective_authorization(
    ctx: Dict[str, Any], kind: Any = "AGREEMENT", **authorization_overrides: Any
) -> Dict[str, Any]:
    """Create a testing authorization on ctx's (case, item) and drive it to
    effectiveness (AGREEMENT signed / MOTION granted). The case must be in
    INVESTIGATION or TESTING and the item CUSTODY_CONFIRMED."""
    authorization = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], kind, **authorization_overrides
    )
    if getattr(kind, "value", kind) == "MOTION":
        authorization = grant_motion(authorization["id"])
    else:
        authorization = sign_agreement(authorization["id"])
    ctx["authorization"] = authorization
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    return ctx


def add_lab_analysis(ctx: Dict[str, Any], **analysis_overrides: Any) -> Dict[str, Any]:
    """Schedule a lab analysis on ctx's item under ctx's authorization;
    requires the case in TESTING. Stores it under ctx["analysis"]."""
    analysis = create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"], **analysis_overrides
    )
    ctx["analysis"] = analysis
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    return ctx


def record_result_on_ctx(
    ctx: Dict[str, Any],
    outcome: Any = "EXCLUSIONARY",
    actual_consumed_ng: Optional[int] = None,
    profile_obtained: bool = True,
) -> Dict[str, Any]:
    """Ship and record the result of ctx's current analysis; defaults to
    consuming the full reservation."""
    analysis = ctx["analysis"]
    ship_sample(analysis["id"])
    consumed = (
        actual_consumed_ng
        if actual_consumed_ng is not None
        else analysis["reserved_sample_ng"]
    )
    ctx["analysis"] = record_result(
        analysis["id"],
        outcome=outcome,
        actual_consumed_ng=consumed,
        profile_obtained=profile_obtained,
    )
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


# =============================================================================
# Tier 3 - case progression: investigation, custody, authorization, testing,
# litigation, exoneration
# =============================================================================

def setup_case_in_investigation(**kwargs: Any) -> Dict[str, Any]:
    """Accepted case advanced OPEN -> INVESTIGATION."""
    ctx = setup_accepted_case(**kwargs)
    advance_case(ctx["case"]["id"], "BEGIN_INVESTIGATION")
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_with_item(
    *,
    item_overrides: Optional[Dict[str, Any]] = None,
    location: str = "CUSTODY_CONFIRMED",
    begin_investigation: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Accepted case (INVESTIGATION by default) plus one evidence item walked
    along the location dimension to `location` (IDENTIFIED, SEARCHING,
    LOCATED, or CUSTODY_CONFIRMED)."""
    ctx = (
        setup_case_in_investigation(**kwargs)
        if begin_investigation
        else setup_accepted_case(**kwargs)
    )
    item = create_evidence_item(ctx["case"]["id"], **(item_overrides or {}))
    target = location
    if target not in ("IDENTIFIED", "SEARCHING", "LOCATED", "CUSTODY_CONFIRMED"):
        raise ValueError(f"location must be IDENTIFIED/SEARCHING/LOCATED/CUSTODY_CONFIRMED, got {target!r}")
    if target in ("SEARCHING", "LOCATED", "CUSTODY_CONFIRMED"):
        item = advance_evidence_item(item["id"], "START_SEARCH")
    if target in ("LOCATED", "CUSTODY_CONFIRMED"):
        item = advance_evidence_item(item["id"], "MARK_LOCATED")
    if target == "CUSTODY_CONFIRMED":
        item = advance_evidence_item(item["id"], "CONFIRM_CUSTODY")
    ctx["item"] = item
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_effective_authorization(
    *,
    kind: Any = "AGREEMENT",
    item_overrides: Optional[Dict[str, Any]] = None,
    authorization_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Case in INVESTIGATION with a CUSTODY_CONFIRMED item and a testing
    authorization already effective: AGREEMENT signed / MOTION granted."""
    ctx = setup_case_with_item(item_overrides=item_overrides, **kwargs)
    authorization = create_testing_authorization(
        ctx["case"]["id"], ctx["item"]["id"], kind, **(authorization_overrides or {})
    )
    if getattr(kind, "value", kind) == "MOTION":
        authorization = grant_motion(authorization["id"])
    else:
        authorization = sign_agreement(authorization["id"])
    ctx["authorization"] = authorization
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    return ctx


def setup_case_in_testing(
    *,
    kind: Any = "AGREEMENT",
    item_overrides: Optional[Dict[str, Any]] = None,
    authorization_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Custody-confirmed item + effective authorization, then
    INVESTIGATION -> TESTING."""
    ctx = setup_effective_authorization(
        kind=kind,
        item_overrides=item_overrides,
        authorization_overrides=authorization_overrides,
        **kwargs,
    )
    advance_case(ctx["case"]["id"], "BEGIN_TESTING")
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_lab_analysis_scheduled(
    *,
    analysis_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Case in TESTING with one lab analysis in SCHEDULED (sample reserved)."""
    ctx = setup_case_in_testing(**kwargs)
    analysis = create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"], **(analysis_overrides or {})
    )
    ctx["analysis"] = analysis
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    return ctx


def setup_lab_result_recorded(
    *,
    analysis_overrides: Optional[Dict[str, Any]] = None,
    outcome: Any = "EXCLUSIONARY",
    actual_consumed_ng: Optional[int] = None,
    profile_obtained: bool = True,
    db_hit: bool = False,
    matched_subject_name: str = "John Doe",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Case in TESTING with one analysis carried to RESULT_RECORDED. With
    db_hit=True a database comparison HIT fires the exculpatory cascade on
    the owning case before returning."""
    ctx = setup_lab_analysis_scheduled(analysis_overrides=analysis_overrides, **kwargs)
    analysis = ctx["analysis"]
    ship_sample(analysis["id"])
    consumed = (
        actual_consumed_ng
        if actual_consumed_ng is not None
        else analysis["reserved_sample_ng"]
    )
    analysis = record_result(
        analysis["id"],
        outcome=outcome,
        actual_consumed_ng=consumed,
        profile_obtained=profile_obtained,
    )
    if db_hit:
        analysis = run_database_comparison(
            analysis["id"], comparison_result="HIT", matched_subject_name=matched_subject_name
        )
    ctx["analysis"] = analysis
    ctx["item"] = get_evidence_item(ctx["item"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_in_litigation(
    *,
    db_hit: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A recorded lab result, then TESTING -> LITIGATION. With db_hit=True the
    case's exculpatory_evidence_flag is already set on arrival."""
    ctx = setup_lab_result_recorded(db_hit=db_hit, **kwargs)
    advance_case(ctx["case"]["id"], "BEGIN_LITIGATION")
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_exonerated_case(
    *,
    petition_overrides: Optional[Dict[str, Any]] = None,
    exoneration_clock: Optional[str] = None,
    db_hit: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Case in LITIGATION -> petition FILED -> RECORD_DECISION GRANTED with
    vacates_conviction=true, firing the exoneration cascade. When
    exoneration_clock is given the logical clock is moved there first, which
    pins exoneration_date (and with it the verified-years compensation
    derivation)."""
    ctx = setup_case_in_litigation(db_hit=db_hit, **kwargs)
    petition = create_legal_petition(ctx["case"]["id"], **(petition_overrides or {}))
    file_petition(petition["id"])
    if exoneration_clock is not None:
        set_clock(exoneration_clock)
    petition = record_petition_decision(petition["id"], "GRANTED", vacates_conviction=True)
    ctx["petition"] = petition
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


# =============================================================================
# Tier 4 - records pipeline and pattern-evidence accumulation
# =============================================================================

def setup_submitted_records_request(
    case_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Records request carried DRAFT -> SUBMITTED, ready for a response."""
    request = create_records_request(case_id, **overrides)
    return advance_records_request(request["id"], "SUBMIT")


def setup_case_with_records_reveal(
    *,
    jurisdiction_id: Optional[str] = None,
    client_id: Optional[str] = None,
    jurisdiction_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
    intake_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    records_overrides: Optional[Dict[str, Any]] = None,
    reveal_disposition: Any = "DESTROYED",
    response_disposition: Any = "FULFILLED",
    specialist_id: str = INTAKE_SPECIALIST_ID,
    decider_id: str = MANAGING_ATTORNEY_ID,
) -> Dict[str, Any]:
    """One accepted case (stays OPEN) whose lone evidence item (walked to
    SEARCHING) is hit by a records response revealing it with
    `reveal_disposition`: DESTROYED drives the case's destroyed_evidence_count
    to 1 and re-derives EVIDENCE_PRESERVATION pattern counts; MISSING moves
    the item to REPORTED_MISSING; LOCATED resurfaces it. Pass a shared
    jurisdiction_id to accumulate several qualifying cases for one
    initiative."""
    ctx = setup_accepted_case(
        jurisdiction_id=jurisdiction_id,
        client_id=client_id,
        jurisdiction_overrides=jurisdiction_overrides,
        client_overrides=client_overrides,
        intake_overrides=intake_overrides,
        specialist_id=specialist_id,
        decider_id=decider_id,
    )
    item = create_evidence_item(ctx["case"]["id"], **(item_overrides or {}))
    item = advance_evidence_item(item["id"], "START_SEARCH")
    request = setup_submitted_records_request(ctx["case"]["id"], **(records_overrides or {}))
    request = respond_records_request(
        request["id"],
        response_disposition,
        items_revealed=[f.revealed_item(item["id"], reveal_disposition)],
    )
    ctx["item"] = get_evidence_item(item["id"])
    ctx["records_request"] = request
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_with_destroyed_evidence(**kwargs: Any) -> Dict[str, Any]:
    """The DESTROYED pinning of setup_case_with_records_reveal: one case with
    destroyed_evidence_count == 1 via the records-response cascade."""
    kwargs["reveal_disposition"] = "DESTROYED"
    return setup_case_with_records_reveal(**kwargs)


def setup_policy_initiative(
    jurisdiction_id: str,
    begin_research: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Policy initiative in PROPOSED (or RESEARCHING when begin_research)."""
    initiative = create_policy_initiative(jurisdiction_id, **overrides)
    if begin_research:
        initiative = advance_policy_initiative(initiative["id"], "BEGIN_RESEARCH")
    return initiative


# =============================================================================
# Tier 5 - post-exoneration lifecycle shortcuts
# =============================================================================

def setup_release_ready_case(
    *,
    scheduled_release_date: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """EXONERATED case whose release checklist is fully checked:
    release_readiness == READY."""
    ctx = setup_exonerated_case(**kwargs)
    fields: Dict[str, Any] = {
        "housing_arranged": True,
        "id_documents_ready": True,
        "transportation_arranged": True,
    }
    if scheduled_release_date is not None:
        fields["scheduled_release_date"] = scheduled_release_date
    advance_case(ctx["case"]["id"], "UPDATE_RELEASE_CHECKLIST", **fields)
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_compensation_claim_filed(
    *,
    claim_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """EXONERATED case + compensation claim carried DRAFT -> FILED."""
    ctx = setup_exonerated_case(**kwargs)
    claim = create_compensation_claim(ctx["case"]["id"], **(claim_overrides or {}))
    ctx["claim"] = file_claim(claim["id"])
    return ctx


def setup_compensation_claim_approved(
    *,
    claim_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """FILED claim approved: final_award_cents (FINAL_VERIFIED) is computed."""
    ctx = setup_compensation_claim_filed(claim_overrides=claim_overrides, **kwargs)
    ctx["claim"] = record_claim_decision(ctx["claim"]["id"], "APPROVED")
    return ctx


def setup_reentry_referral_pending(
    *,
    provider_overrides: Optional[Dict[str, Any]] = None,
    referral_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """EXONERATED case + provider + one referral in PENDING (slot occupied)."""
    ctx = setup_exonerated_case(**kwargs)
    provider = create_reentry_provider(**(provider_overrides or {}))
    referral = create_reentry_referral(
        ctx["case"]["id"], provider["id"], **(referral_overrides or {})
    )
    ctx["provider"] = provider
    ctx["referral"] = referral
    return ctx
