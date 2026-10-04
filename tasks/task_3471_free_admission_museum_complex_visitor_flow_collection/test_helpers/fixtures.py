"""Composite setup helpers.

The server restarts before every test, so each test rebuilds its world from
scratch through the public endpoints. The helpers below collapse the recurring
multi-step preambles (an ON_SALE exhibition is fund + museum + exhibition +
open-sale; an ACTIVE loan is object + propose + accept + accepted OUTBOUND
report + activate; a CONFIRMED reservation is museum + program + confirmed
docents + reserve).

Conventions:
  * Every helper asserts success via get_success_data() and fails with a
    "Setup failed: ..." message that names the step.
  * Identity threading is mandatory: calls gated on ownership build headers
    from the resource's own ids (make_member_headers(member["id"]),
    make_docent_headers(docent["id"]), the curator's recorded X-User-ID),
    never from the shared TEST_USERS fallbacks.
  * No helper touches the logical clock unless its name or an explicit
    argument says so. The startup default is 2026-09-01T00:00:00Z (PRD §2.4),
    and at least one test asserts behavior with the clock never set at all.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import (
    ADMIT_GRACE_SLOTS,
    CLOCK_STARTUP_DEFAULT_UTC,
    DEFAULT_MEMBER_PRESALE_OPENS_AT,
    DEFAULT_MONDAY,
    DEFAULT_PUBLIC_SALE_OPENS_AT,
    ENTRY_DAY_START_HOUR_UTC,
    SLOT_MINUTES,
)
from .test_users import (
    COMMITTEE_CHAIR_USER_ID,
    CURATOR_USER_ID,
    make_borrower_rep_headers,
    make_committee_chair_headers,
    make_curator_headers,
    make_docent_headers,
    make_exhibition_manager_headers,
    make_finance_officer_headers,
    make_loans_officer_headers,
    make_member_headers,
    make_platform_admin_headers,
    make_program_coordinator_headers,
    make_public_headers,
    make_registrar_headers,
    make_scholar_headers,
    make_security_screener_headers,
    make_visitor_services_headers,
)
from .types import (
    CoverageType,
    FundStatus,
    FundType,
    ReportKind,
    ReportOutcome,
    ReviewOutcome,
    ResearchOutcome,
)

Json = Dict[str, Any]

_USER_SEQ = 0


def _fresh_user_id(prefix: str) -> str:
    """A fresh opaque caller id (e.g. a new visitor or organizer) per call."""
    global _USER_SEQ
    _USER_SEQ += 1
    return f"{prefix}-{_USER_SEQ:04d}"


def _created(response, what: str) -> Json:
    assert response.status_code == 201, (
        f"Setup failed creating {what}: expected 201, got "
        f"{response.status_code}: {response.text}"
    )
    return get_success_data(response)


def _ok(response, what: str) -> Json:
    assert 200 <= response.status_code < 300, (
        f"Setup failed on {what}: got {response.status_code}: {response.text}"
    )
    return get_success_data(response)


# ── Logical clock (PRD §2.4) ─────────────────────────────────────────────────
def set_clock(current_utc: str) -> Json:
    """Set the server logical clock; returns the echoed {"current_utc": ...}."""
    return _ok(
        api_client.set_clock(current_utc, headers=make_platform_admin_headers()),
        f"set_clock({current_utc})",
    )


def reset_clock() -> Json:
    """Re-pin the clock to the startup default 2026-09-01T00:00:00Z."""
    return set_clock(CLOCK_STARTUP_DEFAULT_UTC)


def slot_datetime(visit_date: str, slot_index: int, minute_offset: int = 5) -> str:
    """A clock reading that lands inside the given quarter-hour entry slot.

    Slot 0 begins at 10:00 UTC and slots run fifteen minutes (PRD §2.4), so
    slot 4 with the default offset is 11:05:00Z. An admission is allowed while
    the current slot is at most ADMIT_GRACE_SLOTS past the reserved slot.
    """
    day = datetime.fromisoformat(visit_date)
    instant = day + timedelta(
        hours=ENTRY_DAY_START_HOUR_UTC,
        minutes=SLOT_MINUTES * slot_index + minute_offset,
    )
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Museums (PRD §3.1) ───────────────────────────────────────────────────────
def create_museum(**overrides: Any) -> Json:
    """Create a museum; defaults are a walk-in museum (requires_timed_pass
    False) with generous quotas. Returns the museum."""
    resp = api_client.create_museum(
        factories.create_museum_payload(**overrides),
        headers=make_platform_admin_headers(),
    )
    return _created(resp, "museum")


def create_timed_museum(
    quarter_hour_pass_quota: int = 5,
    daily_pass_quota: int = 20,
    screening_rate_per_quarter_hour: int = 4,
    **overrides: Any,
) -> Json:
    """Create a timed-entry museum (requires_timed_pass True) with the given
    quota triple. Returns the museum."""
    return create_museum(
        requires_timed_pass=True,
        quarter_hour_pass_quota=quarter_hour_pass_quota,
        daily_pass_quota=daily_pass_quota,
        screening_rate_per_quarter_hour=screening_rate_per_quarter_hour,
        **overrides,
    )


def close_museum_day(museum_id: str, closure_date: str) -> Json:
    """Emergency-close the museum on a date; cascades that day's RESERVED
    passes to EXPIRED. Returns the updated museum."""
    return _ok(
        api_client.close_museum_day(museum_id, closure_date, headers=make_platform_admin_headers()),
        f"close-day for museum {museum_id} on {closure_date}",
    )


def get_museum(museum_id: str) -> Json:
    return _ok(
        api_client.get_museum(museum_id, headers=make_platform_admin_headers()),
        f"read museum {museum_id}",
    )


# ── Timed entry passes (PRD §3.1) ────────────────────────────────────────────
def reserve_pass(
    museum_id: str,
    creator_user_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Reserve a pass as a Public caller. The response's created_by_user_id is
    the caller's X-User-ID; cancel with
    make_public_headers(pass_dict["created_by_user_id"])."""
    user_id = creator_user_id or _fresh_user_id("visitor")
    resp = api_client.create_timed_entry_pass(
        museum_id,
        factories.create_timed_entry_pass_payload(**overrides),
        headers=make_public_headers(user_id),
    )
    return _created(resp, f"timed entry pass at museum {museum_id}")


def reserve_member_pass(museum_id: str, member: Json, **overrides: Any) -> Json:
    """Reserve a pass as the holder member: X-User-ID == holder_member_id ==
    member["id"]."""
    payload = factories.create_timed_entry_pass_payload(
        holder_member_id=member["id"], **overrides
    )
    resp = api_client.create_timed_entry_pass(
        museum_id, payload, headers=make_member_headers(member["id"])
    )
    return _created(resp, f"member pass at museum {museum_id}")


def admit_pass(pass_id: str) -> Json:
    """Admit a pass holder through screening (SecurityScreener)."""
    return _ok(
        api_client.admit_timed_entry_pass(pass_id, headers=make_security_screener_headers()),
        f"admit pass {pass_id}",
    )


def cancel_pass(pass_dict: Json) -> Json:
    """Cancel a RESERVED pass as its Public creator."""
    return _ok(
        api_client.cancel_timed_entry_pass(
            pass_dict["id"],
            headers=make_public_headers(pass_dict["created_by_user_id"]),
        ),
        f"cancel pass {pass_dict['id']}",
    )


# ── Members (PRD §3.2) ───────────────────────────────────────────────────────
def create_member(registrar_user_id: Optional[str] = None, **overrides: Any) -> Json:
    """Register a member (Public self-registration by default). expires_on is
    computed from the logical clock at creation plus the term in calendar
    months — set the clock first when a test needs a specific join date."""
    resp = api_client.create_member(
        factories.create_member_payload(**overrides),
        headers=make_public_headers(registrar_user_id or _fresh_user_id("signup")),
    )
    return _created(resp, "member")


def get_member(member_id: str) -> Json:
    """Read a member as themself (Member is entity-backed)."""
    return _ok(
        api_client.get_member(member_id, headers=make_member_headers(member_id)),
        f"read member {member_id}",
    )


# ── Funds & expenditures (PRD §3.7) ──────────────────────────────────────────
def create_fund(
    fund_type: str = FundType.TRUST.value,
    appropriation_cents: int = 1_000_000,
    **overrides: Any,
) -> Json:
    resp = api_client.create_fund(
        factories.create_fund_payload(
            fund_type=fund_type, appropriation_cents=appropriation_cents, **overrides
        ),
        headers=make_platform_admin_headers(),
    )
    return _created(resp, f"{fund_type} fund")


def create_trust_fund(appropriation_cents: int = 1_000_000, **overrides: Any) -> Json:
    return create_fund(fund_type=FundType.TRUST.value, appropriation_cents=appropriation_cents, **overrides)


def create_federal_fund(appropriation_cents: int = 1_000_000, **overrides: Any) -> Json:
    return create_fund(fund_type=FundType.FEDERAL.value, appropriation_cents=appropriation_cents, **overrides)


def get_fund(fund_id: str) -> Json:
    return _ok(
        api_client.get_fund(fund_id, headers=make_finance_officer_headers()),
        f"read fund {fund_id}",
    )


def post_expenditure(
    fund_id: str,
    amount_cents: int = 1000,
    activity_type: str = "OPERATIONS",
    **overrides: Any,
) -> Json:
    resp = api_client.create_expenditure(
        fund_id,
        factories.create_expenditure_payload(
            amount_cents=amount_cents, activity_type=activity_type, **overrides
        ),
        headers=make_finance_officer_headers(),
    )
    return _created(resp, f"expenditure on fund {fund_id}")


def void_expenditure(expenditure_id: str) -> Json:
    return _ok(
        api_client.void_expenditure(expenditure_id, headers=make_finance_officer_headers()),
        f"void expenditure {expenditure_id}",
    )


def freeze_fund(fund_id: str) -> Json:
    return _ok(
        api_client.set_fund_status(
            fund_id, FundStatus.FROZEN.value, headers=make_platform_admin_headers()
        ),
        f"freeze fund {fund_id}",
    )


def unfreeze_fund(fund_id: str) -> Json:
    return _ok(
        api_client.set_fund_status(
            fund_id, FundStatus.ACTIVE.value, headers=make_platform_admin_headers()
        ),
        f"unfreeze fund {fund_id}",
    )


# ── Exhibitions & tickets (PRD §3.2) ─────────────────────────────────────────
def create_exhibition(museum_id: str, revenue_fund_id: str, **overrides: Any) -> Json:
    """Create a DRAFT exhibition under the museum, routed to a TRUST fund."""
    resp = api_client.create_exhibition(
        museum_id,
        factories.create_exhibition_payload(revenue_fund_id, **overrides),
        headers=make_exhibition_manager_headers(),
    )
    return _created(resp, f"exhibition at museum {museum_id}")


def open_sale(exhibition_id: str) -> Json:
    return _ok(
        api_client.open_exhibition_sale(exhibition_id, headers=make_exhibition_manager_headers()),
        f"open-sale exhibition {exhibition_id}",
    )


def close_exhibition(exhibition_id: str) -> Json:
    return _ok(
        api_client.close_exhibition(exhibition_id, headers=make_exhibition_manager_headers()),
        f"close exhibition {exhibition_id}",
    )


def setup_exhibition_on_sale(
    fee_cents: int = 1000,
    daily_ticket_quota: int = 5,
    member_presale_opens_at: str = DEFAULT_MEMBER_PRESALE_OPENS_AT,
    public_sale_opens_at: str = DEFAULT_PUBLIC_SALE_OPENS_AT,
    appropriation_cents: int = 100_000_000,
    advance_clock_to: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """TRUST fund + museum + exhibition moved to ON_SALE. When
    advance_clock_to is given, the logical clock is set there last, so
    purchases land in the intended sale window. Returns
    {"fund": ..., "museum": ..., "exhibition": ...}."""
    fund = create_trust_fund(appropriation_cents=appropriation_cents)
    museum = create_museum()
    exhibition = create_exhibition(
        museum["id"],
        fund["id"],
        fee_cents=fee_cents,
        daily_ticket_quota=daily_ticket_quota,
        member_presale_opens_at=member_presale_opens_at,
        public_sale_opens_at=public_sale_opens_at,
        **overrides,
    )
    exhibition = open_sale(exhibition["id"])
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return {"fund": fund, "museum": museum, "exhibition": exhibition}


def purchase_ticket(
    exhibition_id: str,
    member: Optional[Json] = None,
    buyer_user_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Purchase a ticket. With member=..., the call runs as that member
    (X-User-ID == member_id == member["id"]) and locks member pricing; without
    it, the call runs as a Public buyer at the full fee."""
    if member is not None:
        payload = factories.purchase_ticket_payload(member_id=member["id"], **overrides)
        headers = make_member_headers(member["id"])
    else:
        payload = factories.purchase_ticket_payload(**overrides)
        headers = make_public_headers(buyer_user_id or _fresh_user_id("buyer"))
    resp = api_client.purchase_ticket(exhibition_id, payload, headers=headers)
    return _created(resp, f"ticket for exhibition {exhibition_id}")


def refund_ticket(ticket_id: str) -> Json:
    return _ok(
        api_client.refund_ticket(ticket_id, headers=make_visitor_services_headers()),
        f"refund ticket {ticket_id}",
    )


def redeem_ticket(ticket_id: str) -> Json:
    """Redeem a ticket at the exhibition entrance (SecurityScreener)."""
    return _ok(
        api_client.redeem_ticket(ticket_id, headers=make_security_screener_headers()),
        f"redeem ticket {ticket_id}",
    )


# ── Docents, programs, reservations (PRD §3.3) ──────────────────────────────
def create_docent(certification_level: str = "BASIC", active: bool = True, **overrides: Any) -> Json:
    resp = api_client.create_docent(
        factories.create_docent_payload(
            certification_level=certification_level, active=active, **overrides
        ),
        headers=make_program_coordinator_headers(),
    )
    return _created(resp, "docent")


def create_program(museum_id: str, **overrides: Any) -> Json:
    """Create a SCHEDULED weekly education program under the museum."""
    resp = api_client.create_education_program(
        museum_id,
        factories.create_education_program_payload(**overrides),
        headers=make_program_coordinator_headers(),
    )
    return _created(resp, f"education program at museum {museum_id}")


def assign_docent(program_id: str, docent_id: str, service_date: str = DEFAULT_MONDAY) -> Json:
    resp = api_client.create_docent_assignment(
        program_id,
        factories.create_docent_assignment_payload(docent_id, service_date),
        headers=make_program_coordinator_headers(),
    )
    return _created(resp, f"docent assignment on program {program_id}")


def confirm_assignment(assignment: Json) -> Json:
    """The docent confirms their own assignment: X-User-ID ==
    assignment["docent_id"] (entity-backed ownership)."""
    return _ok(
        api_client.confirm_docent_assignment(
            assignment["id"], headers=make_docent_headers(assignment["docent_id"])
        ),
        f"confirm assignment {assignment['id']}",
    )


def setup_program_with_docents(
    museum: Optional[Json] = None,
    num_docents: int = 1,
    confirm: bool = True,
    service_date: str = DEFAULT_MONDAY,
    certification_level: str = "BASIC",
    **program_overrides: Any,
) -> Json:
    """Museum + SCHEDULED program + num_docents docents assigned to
    service_date (and, when confirm=True, each confirmed by its own docent).
    Returns {"museum", "program", "docents", "assignments"}."""
    museum = museum or create_museum()
    program = create_program(museum["id"], **program_overrides)
    docents: List[Json] = []
    assignments: List[Json] = []
    for _ in range(num_docents):
        docent = create_docent(certification_level=certification_level)
        assignment = assign_docent(program["id"], docent["id"], service_date)
        if confirm:
            assignment = confirm_assignment(assignment)
        docents.append(docent)
        assignments.append(assignment)
    return {
        "museum": museum,
        "program": program,
        "docents": docents,
        "assignments": assignments,
    }


def create_school_reservation(
    museum_id: str,
    program_id: str,
    organizer_user_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Create a school group reservation as a Public organizer; lands stored as
    CONFIRMED or WAITLISTED per the pinned creation evaluation (PRD §3.3).
    Cancel with make_public_headers(reservation["created_by_user_id"])."""
    user_id = organizer_user_id or _fresh_user_id("teacher")
    resp = api_client.create_school_reservation(
        factories.create_school_reservation_payload(museum_id, program_id, **overrides),
        headers=make_public_headers(user_id),
    )
    return _created(resp, f"school reservation on program {program_id}")


def cancel_reservation(reservation: Json) -> Json:
    """Cancel as the organizing Public caller recorded in created_by_user_id."""
    return _ok(
        api_client.cancel_school_reservation(
            reservation["id"],
            headers=make_public_headers(reservation["created_by_user_id"]),
        ),
        f"cancel reservation {reservation['id']}",
    )


def setup_confirmed_reservation(
    headcount: int = 10,
    num_docents: int = 2,
    service_date: str = DEFAULT_MONDAY,
    docent_ratio: int = 5,
    **program_overrides: Any,
) -> Json:
    """Program whose staffing covers the group, then the reservation; it lands
    CONFIRMED. Returns the program fixture dict plus "reservation"."""
    built = setup_program_with_docents(
        num_docents=num_docents,
        confirm=True,
        service_date=service_date,
        docent_ratio=docent_ratio,
        **program_overrides,
    )
    reservation = create_school_reservation(
        built["museum"]["id"],
        built["program"]["id"],
        headcount=headcount,
        visit_date=service_date,
    )
    assert reservation["status"] == "CONFIRMED", (
        f"Setup failed: expected CONFIRMED reservation, got {reservation['status']}"
    )
    built["reservation"] = reservation
    return built


# ── Collection objects & loans (PRD §3.4, §3.5) ─────────────────────────────
def create_object(**overrides: Any) -> Json:
    """Accession an object directly (Registrar), standing IN_COLLECTION."""
    resp = api_client.create_collection_object(
        factories.create_collection_object_payload(**overrides),
        headers=make_registrar_headers(),
    )
    return _created(resp, "collection object")


def get_object(object_id: str) -> Json:
    return _ok(
        api_client.get_collection_object(object_id, headers=make_registrar_headers()),
        f"read object {object_id}",
    )


def create_proposed_loan(object_id: str, **overrides: Any) -> Json:
    """Open negotiation: loan born PROPOSED with negotiated_round 1, version 1."""
    resp = api_client.create_loan_agreement(
        object_id,
        factories.create_loan_agreement_payload(**overrides),
        headers=make_loans_officer_headers(),
    )
    return _created(resp, f"loan on object {object_id}")


def counter_loan(loan: Json, as_borrower: bool = True, **term_overrides: Any) -> Json:
    """Counter the current terms. BorrowerRep counters PROPOSED -> COUNTERED;
    LoansOfficer counters COUNTERED -> PROPOSED. OCC carries the loan's
    current version from the given snapshot."""
    headers = make_borrower_rep_headers() if as_borrower else make_loans_officer_headers()
    resp = api_client.counter_loan_agreement(
        loan["id"],
        factories.counter_loan_payload(loan["version"], **term_overrides),
        headers=headers,
    )
    return _ok(resp, f"counter loan {loan['id']}")


def accept_loan(loan: Json, as_borrower: bool = True) -> Json:
    """Accept current terms (BorrowerRep from PROPOSED, LoansOfficer from
    COUNTERED), locking the FINAL premium. OCC carries the snapshot version."""
    headers = make_borrower_rep_headers() if as_borrower else make_loans_officer_headers()
    resp = api_client.accept_loan_agreement(
        loan["id"], loan["version"], headers=headers
    )
    return _ok(resp, f"accept loan {loan['id']}")


def create_agreed_loan(object_id: str, **overrides: Any) -> Json:
    """Propose then borrower-accept. Default terms (INSURANCE, declared
    50,000,000, no courier) clear every accept gate. Returns the AGREED loan."""
    loan = create_proposed_loan(object_id, **overrides)
    agreed = accept_loan(loan, as_borrower=True)
    assert agreed["status"] == "AGREED", (
        f"Setup failed: expected AGREED loan, got {agreed['status']}"
    )
    return agreed


def file_condition_report(
    loan_id: str,
    report_kind: str = ReportKind.OUTBOUND.value,
    damage_noted: bool = False,
    as_borrower: bool = False,
    **overrides: Any,
) -> Json:
    headers = make_borrower_rep_headers() if as_borrower else make_loans_officer_headers()
    resp = api_client.create_condition_report(
        loan_id,
        factories.create_condition_report_payload(
            report_kind=report_kind, damage_noted=damage_noted, **overrides
        ),
        headers=headers,
    )
    return _created(resp, f"{report_kind} condition report on loan {loan_id}")


def decide_condition_report(report_id: str, outcome: str = ReportOutcome.ACCEPTED.value) -> Json:
    return _ok(
        api_client.decide_condition_report(
            report_id, outcome, headers=make_loans_officer_headers()
        ),
        f"decide condition report {report_id} -> {outcome}",
    )


def activate_loan(loan_id: str) -> Json:
    return _ok(
        api_client.activate_loan_agreement(loan_id, headers=make_loans_officer_headers()),
        f"activate loan {loan_id}",
    )


def close_loan(loan_id: str) -> Json:
    return _ok(
        api_client.close_loan_agreement(loan_id, headers=make_loans_officer_headers()),
        f"close loan {loan_id}",
    )


def create_active_loan(object_id: str, **loan_overrides: Any) -> Json:
    """Full outbound half of the loan cycle: AGREED + an ACCEPTED OUTBOUND
    report + activate. Returns {"loan", "outbound_report"}; the object now
    stands OUT_ON_LOAN."""
    loan = create_agreed_loan(object_id, **loan_overrides)
    report = file_condition_report(loan["id"], report_kind=ReportKind.OUTBOUND.value)
    decide_condition_report(report["id"], ReportOutcome.ACCEPTED.value)
    loan = activate_loan(loan["id"])
    assert loan["status"] == "ACTIVE", (
        f"Setup failed: expected ACTIVE loan, got {loan['status']}"
    )
    return {"loan": loan, "outbound_report": report}


def create_closed_loan(
    object_id: str,
    damage_noted: bool = False,
    **loan_overrides: Any,
) -> Json:
    """The full loan cycle through close. The accepted RETURN report's
    damage_noted selects the object's landing state: False -> IN_COLLECTION,
    True -> UNDER_CONSERVATION. Returns {"loan", "outbound_report",
    "return_report", "object"}."""
    built = create_active_loan(object_id, **loan_overrides)
    loan = built["loan"]
    return_report = file_condition_report(
        loan["id"], report_kind=ReportKind.RETURN.value, damage_noted=damage_noted
    )
    decide_condition_report(return_report["id"], ReportOutcome.ACCEPTED.value)
    loan = close_loan(loan["id"])
    assert loan["status"] == "CLOSED", (
        f"Setup failed: expected CLOSED loan, got {loan['status']}"
    )
    return {
        "loan": loan,
        "outbound_report": built["outbound_report"],
        "return_report": return_report,
        "object": get_object(object_id),
    }


def setup_object_on_active_loan(
    object_overrides: Optional[Json] = None,
    **loan_overrides: Any,
) -> Json:
    """Object + ACTIVE loan in one call. Returns {"object", "loan",
    "outbound_report"}."""
    obj = create_object(**(object_overrides or {}))
    built = create_active_loan(obj["id"], **loan_overrides)
    return {"object": obj, **built}


# ── Collection reviews (PRD §3.6) ────────────────────────────────────────────
def create_acquisition_review(
    fund_id: str,
    curator_user_id: str = CURATOR_USER_ID,
    **overrides: Any,
) -> Json:
    """Open a DRAFT acquisition review as the curator; the creator's X-User-ID
    is recorded for the later submit-ownership check, so keep the same id."""
    resp = api_client.create_collection_review(
        factories.create_acquisition_review_payload(fund_id, **overrides),
        headers=make_curator_headers(curator_user_id),
    )
    return _created(resp, "acquisition review")


def create_deaccession_review(
    object_id: str,
    curator_user_id: str = CURATOR_USER_ID,
    **overrides: Any,
) -> Json:
    """Open a DRAFT deaccession review as the curator."""
    resp = api_client.create_collection_review(
        factories.create_deaccession_review_payload(object_id, **overrides),
        headers=make_curator_headers(curator_user_id),
    )
    return _created(resp, "deaccession review")


def submit_review(review: Json, curator_user_id: str = CURATOR_USER_ID) -> Json:
    """Submit a DRAFT review; only the creating curator's X-User-ID is
    accepted. Pass the same curator_user_id used at creation."""
    return _ok(
        api_client.submit_collection_review(
            review["id"], headers=make_curator_headers(curator_user_id)
        ),
        f"submit review {review['id']}",
    )


def decide_review(
    review: Json,
    outcome: str = ReviewOutcome.APPROVED.value,
    chair_user_id: str = COMMITTEE_CHAIR_USER_ID,
) -> Json:
    """Committee chair decision; OCC carries the review snapshot's version and
    segregation of duties requires chair_user_id != the recorded submitter."""
    return _ok(
        api_client.decide_collection_review(
            review["id"], outcome, review["version"],
            headers=make_committee_chair_headers(chair_user_id),
        ),
        f"decide review {review['id']} -> {outcome}",
    )


def execute_review(review_id: str, actual_cost_cents: Optional[int] = None) -> Json:
    return _ok(
        api_client.execute_collection_review(
            review_id,
            factories.execute_review_payload(actual_cost_cents),
            headers=make_registrar_headers(),
        ),
        f"execute review {review_id}",
    )


def create_submitted_acquisition_review(
    fund_id: str,
    curator_user_id: str = CURATOR_USER_ID,
    **overrides: Any,
) -> Json:
    review = create_acquisition_review(fund_id, curator_user_id=curator_user_id, **overrides)
    return submit_review(review, curator_user_id=curator_user_id)


def create_submitted_deaccession_review(
    object_id: str,
    curator_user_id: str = CURATOR_USER_ID,
    **overrides: Any,
) -> Json:
    review = create_deaccession_review(object_id, curator_user_id=curator_user_id, **overrides)
    return submit_review(review, curator_user_id=curator_user_id)


def create_approved_acquisition_review(
    fund_id: str,
    estimated_cost_cents: int = 1000,
    curator_user_id: str = CURATOR_USER_ID,
    chair_user_id: str = COMMITTEE_CHAIR_USER_ID,
    **overrides: Any,
) -> Json:
    """Acquisition review taken DRAFT -> SUBMITTED -> APPROVED; it sits
    unexecuted, encumbering the fund's committed availability by
    estimated_cost_cents."""
    review = create_submitted_acquisition_review(
        fund_id,
        curator_user_id=curator_user_id,
        estimated_cost_cents=estimated_cost_cents,
        **overrides,
    )
    approved = decide_review(
        review, ReviewOutcome.APPROVED.value, chair_user_id=chair_user_id
    )
    assert approved["status"] == "APPROVED", (
        f"Setup failed: expected APPROVED review, got {approved['status']}"
    )
    return approved


def setup_approved_deaccession_review(
    object_id: str,
    disposal_method: str = "TRANSFER",
    cultural_property_review_completed: bool = False,
    curator_user_id: str = CURATOR_USER_ID,
    chair_user_id: str = COMMITTEE_CHAIR_USER_ID,
    **overrides: Any,
) -> Json:
    """Deaccession review taken through approval; the object now stands
    PENDING_DEACCESSION."""
    review = create_submitted_deaccession_review(
        object_id,
        curator_user_id=curator_user_id,
        disposal_method=disposal_method,
        cultural_property_review_completed=cultural_property_review_completed,
        **overrides,
    )
    approved = decide_review(
        review, ReviewOutcome.APPROVED.value, chair_user_id=chair_user_id
    )
    assert approved["status"] == "APPROVED", (
        f"Setup failed: expected APPROVED deaccession review, got {approved['status']}"
    )
    return approved


def setup_fund_with_committed_pressure(
    appropriation_cents: int,
    posted_cents: int,
    approved_estimated_cents: int,
    fund_type: str = FundType.TRUST.value,
    curator_user_id: str = "cur-fx",
    chair_user_id: str = "chair-fx",
) -> Json:
    """Fund + one POSTED expenditure + one APPROVED-unexecuted acquisition.
    settled = appropriation - posted; committed = settled - approved estimate.
    Returns {"fund", "expenditure", "review"}."""
    fund = create_fund(fund_type=fund_type, appropriation_cents=appropriation_cents)
    expenditure = post_expenditure(fund["id"], amount_cents=posted_cents)
    review = create_approved_acquisition_review(
        fund["id"],
        estimated_cost_cents=approved_estimated_cents,
        curator_user_id=curator_user_id,
        chair_user_id=chair_user_id,
    )
    return {"fund": fund, "expenditure": expenditure, "review": review}


# ── Research access (PRD §3.8) ───────────────────────────────────────────────
def create_research_request(
    object_id: str,
    scholar_user_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    resp = api_client.create_research_access_request(
        factories.create_research_access_request_payload(object_id, **overrides),
        headers=make_scholar_headers(scholar_user_id or _fresh_user_id("scholar")),
    )
    return _created(resp, f"research access request on object {object_id}")


def decide_research_request(
    request_id: str,
    outcome: str = ResearchOutcome.APPROVED.value,
) -> Json:
    return _ok(
        api_client.decide_research_access_request(
            request_id, outcome, headers=make_registrar_headers()
        ),
        f"decide research request {request_id} -> {outcome}",
    )
