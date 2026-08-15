"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.

Identity threading: Applicant is entity-backed by PropertyOwner, so every
ownership-gated call (application create/resubmit/withdraw/fee-payments,
appeals, hardship reviews) uses make_applicant_headers(owner["id"]). Staff
calls that must later satisfy segregation of duties (PRD §3.4) thread a
specific operator id via make_staff_headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_district_payload,
    create_guideline_set_payload,
    create_hearing_payload,
    create_meeting_payload,
    create_owner_payload,
    create_property_payload,
    create_violation_payload,
    resubmit_payload,
    verified_item,
    work_item,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_staff_headers,
)

STAFF = TEST_USERS["staff_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]
COUNCIL = TEST_USERS["council_headers"]
OFFICER = TEST_USERS["officer_headers"]


# --- Clock (PRD §2.5) ---------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, STAFF))


# --- Tier 1: single-entity creation --------------------------------------------

def create_district(**overrides):
    return get_success_data(
        api_client.create_district(create_district_payload(**overrides), STAFF), 201
    )


def create_guideline_set(district_id, **overrides):
    """Create a DRAFT guideline set for the district."""
    return get_success_data(
        api_client.create_guideline_set(
            district_id, create_guideline_set_payload(**overrides), STAFF
        ),
        201,
    )


def create_adopted_guideline_set(district_id, **overrides):
    """Create + adopt a guideline set (adoption stamps adopted_at)."""
    gs = create_guideline_set(district_id, **overrides)
    return get_success_data(api_client.adopt_guideline_set(gs["id"], STAFF))


def create_owner(**overrides):
    return get_success_data(
        api_client.create_owner(create_owner_payload(**overrides), STAFF), 201
    )


def create_property(owner_id, **overrides):
    return get_success_data(
        api_client.create_property(create_property_payload(owner_id, **overrides), STAFF),
        201,
    )


def create_meeting(**overrides):
    return get_success_data(
        api_client.create_meeting(create_meeting_payload(**overrides), STAFF), 201
    )


def create_violation(property_id, **overrides):
    """Open a violation case; the property's open_violation_count rises by one."""
    return get_success_data(
        api_client.create_violation(create_violation_payload(property_id, **overrides), OFFICER),
        201,
    )


def issue_notice(violation_id):
    return get_success_data(api_client.issue_notice(violation_id, OFFICER))


def create_notice_issued_violation(property_id, **overrides):
    """Create a violation and issue its notice (starts penalty accrual)."""
    violation = create_violation(property_id, **overrides)
    return issue_notice(violation["id"])


# --- Tier 1: application lifecycle steps -----------------------------------------

def submit_application(property_id, owner_id, **overrides):
    """Submit an application as its owning applicant (PRD §3.2)."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(property_id, owner_id, **overrides),
            make_applicant_headers(owner_id),
        ),
        201,
    )


def begin_review(application_id, staff_headers=None):
    return get_success_data(
        api_client.begin_review(application_id, staff_headers or STAFF)
    )


def return_incomplete(application_id, deficiency_notes="Missing materials"):
    return get_success_data(
        api_client.return_incomplete(
            application_id, {"deficiency_notes": deficiency_notes}, STAFF
        )
    )


def resubmit(application_id, owner_id, items, **overrides):
    """Applicant resubmits revised work items (ownership-gated)."""
    return get_success_data(
        api_client.resubmit_application(
            application_id,
            resubmit_payload(items, **overrides),
            make_applicant_headers(owner_id),
        )
    )


def accept_application(application_id, verified_items, staff_id="staff-1"):
    """Staff accepts completeness with a known operator id so segregation of
    duties at decision time is deterministic (PRD §3.4)."""
    return get_success_data(
        api_client.accept_completeness(
            application_id,
            {"verified_work_items": verified_items},
            make_staff_headers(staff_id),
        )
    )


def decide_by_staff(application_id, payload, staff_id="staff-2"):
    return get_success_data(
        api_client.decide_application(application_id, payload, make_staff_headers(staff_id))
    )


def decide_by_commissioner(application_id, payload):
    return get_success_data(
        api_client.decide_application(application_id, payload, COMMISSIONER)
    )


def pay_fee(application_id, owner_id, amount_cents):
    """Record a fee payment by the owning applicant (PRD §3.5)."""
    return get_success_data(
        api_client.record_fee_payment(
            application_id, {"amount_cents": amount_cents},
            make_applicant_headers(owner_id),
        ),
        201,
    )


def pay_assessed_fee(application_id, owner_id):
    """Pay the exact outstanding assessed balance (the intended final
    installment, PRD §3.5)."""
    app = get_success_data(api_client.get_application(application_id, STAFF))
    return pay_fee(application_id, owner_id, app["fee_balance_cents"])


# --- Tier 1: hearings --------------------------------------------------------------

def schedule_hearing(application_id, meeting_id, notice_posted_at="2026-08-10T00:00:00Z"):
    return get_success_data(
        api_client.create_hearing(
            create_hearing_payload(
                application_id, meeting_id, notice_posted_at=notice_posted_at
            ),
            STAFF,
        ),
        201,
    )


def open_hearing(hearing_id):
    return get_success_data(api_client.open_hearing(hearing_id, COMMISSIONER))


def continue_hearing(hearing_id):
    return get_success_data(api_client.continue_hearing(hearing_id, COMMISSIONER))


def get_meeting(meeting_id):
    return get_success_data(api_client.get_meeting(meeting_id, STAFF))


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, STAFF))


def get_property(property_id):
    return get_success_data(api_client.get_property(property_id, STAFF))


def get_violation(violation_id):
    return get_success_data(api_client.get_violation(violation_id, OFFICER))


def get_district(district_id):
    return get_success_data(api_client.get_district(district_id, STAFF))


def get_delay_for_application(application_id):
    """Fetch the single demolition delay linked to an approved demolition."""
    data, meta = validate_paginated(
        api_client.list_demolition_delays(STAFF, params={"application_id": application_id})
    )
    assert len(data) == 1, (
        f"expected exactly one demolition delay for application {application_id}, "
        f"got {len(data)}"
    )
    return data[0]


# --- Tier 2: composite lifecycle states -----------------------------------------

def setup_staff_track_accepted(
    *,
    with_district=False,
    verified_cost_cents=200000,
    category="SITE_WORK",
    staff_id="staff-1",
    property_overrides=None,
    application_overrides=None,
):
    """Owner + property + application walked through begin-review and
    accept-completeness to ACCEPTED on the STAFF track (default verified cost
    far below the commission threshold, PRD §3.3).

    Returns ctx: owner, property, district (or None), submitted (application at
    SUBMITTED), application (ACCEPTED).
    """
    district = create_district() if with_district else None
    owner = create_owner()
    prop_overrides = dict(property_overrides or {})
    if district is not None:
        prop_overrides.setdefault("district_id", district["id"])
    prop = create_property(owner["id"], **prop_overrides)
    app_overrides = {"work_items": [work_item(category, "declared", verified_cost_cents)]}
    app_overrides.update(application_overrides or {})
    submitted = submit_application(prop["id"], owner["id"], **app_overrides)
    begin_review(submitted["id"])
    accepted = accept_application(
        submitted["id"], [verified_item(category, verified_cost_cents)], staff_id
    )
    return {
        "district": district,
        "owner": owner,
        "property": prop,
        "submitted": submitted,
        "application": accepted,
    }


def setup_commission_track_accepted(
    *,
    verified_cost_cents=1100000,
    category="ADDITION",
    application_type="ADDITION",
    staff_id="staff-1",
    property_overrides=None,
    application_overrides=None,
):
    """Owner + property + application ACCEPTED on the COMMISSION track
    (default: verified cost at or above the 1,000,000-cent threshold,
    PRD §3.3). Same ctx shape as setup_staff_track_accepted."""
    district = create_district()
    owner = create_owner()
    prop_overrides = {"district_id": district["id"]}
    prop_overrides.update(property_overrides or {})
    prop = create_property(owner["id"], **prop_overrides)
    app_overrides = {
        "application_type": application_type,
        "is_visible_from_public_way": True,
        "work_items": [work_item(category, "declared", verified_cost_cents)],
    }
    app_overrides.update(application_overrides or {})
    submitted = submit_application(prop["id"], owner["id"], **app_overrides)
    begin_review(submitted["id"])
    accepted = accept_application(
        submitted["id"], [verified_item(category, verified_cost_cents)], staff_id
    )
    return {
        "district": district,
        "owner": owner,
        "property": prop,
        "submitted": submitted,
        "application": accepted,
    }


def setup_hearing_scheduled(
    *,
    meeting_date="2026-09-01T00:00:00Z",
    agenda_capacity=2,
    notice_posted_at="2026-08-10T00:00:00Z",
    **accept_kwargs,
):
    """COMMISSION-track ACCEPTED application + meeting + SCHEDULED hearing.
    ctx adds meeting and hearing; the application is HEARING_SCHEDULED."""
    ctx = setup_commission_track_accepted(**accept_kwargs)
    meeting = create_meeting(meeting_date=meeting_date, agenda_capacity=agenda_capacity)
    hearing = schedule_hearing(
        ctx["application"]["id"], meeting["id"], notice_posted_at=notice_posted_at
    )
    ctx["meeting"] = meeting
    ctx["hearing"] = hearing
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_hearing_open(**kwargs):
    """SCHEDULED hearing opened by the commissioner; the application is
    HEARING_OPEN and the comment period is closed (PRD §3.4)."""
    ctx = setup_hearing_scheduled(**kwargs)
    ctx["hearing"] = open_hearing(ctx["hearing"]["id"])
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_staff_approved(
    *,
    outcome="APPROVE",
    conditions=None,
    pay=False,
    staff_accept="staff-1",
    staff_decide="staff-2",
    **accept_kwargs,
):
    """STAFF-track application decided by a different staff user than the
    acceptor (segregation of duties, PRD §3.4). ctx adds decision (the decide
    response data). With pay=True the assessed fee is fully paid."""
    ctx = setup_staff_track_accepted(staff_id=staff_accept, **accept_kwargs)
    payload = {"outcome": outcome}
    if conditions is not None:
        payload["conditions"] = conditions
    ctx["decision"] = decide_by_staff(ctx["application"]["id"], payload, staff_decide)
    ctx["application"] = ctx["decision"]
    if pay:
        pay_assessed_fee(ctx["application"]["id"], ctx["owner"]["id"])
        ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_staff_denied(
    *,
    decide_clock=None,
    rationale=("S2",),
    staff_accept="staff-1",
    staff_decide="staff-2",
    **accept_kwargs,
):
    """STAFF-track application DENIED. decide_clock, when given, pins the
    logical clock first so decided_at (the appeal-window anchor, PRD §3.6) is
    deterministic."""
    ctx = setup_staff_track_accepted(staff_id=staff_accept, **accept_kwargs)
    if decide_clock is not None:
        set_clock(decide_clock)
    ctx["decision"] = decide_by_staff(
        ctx["application"]["id"],
        {"outcome": "DENY", "denial_rationale_sections": list(rationale)},
        staff_decide,
    )
    ctx["application"] = ctx["decision"]
    return ctx


def setup_after_the_fact_pending(
    *,
    assessed_value_cents=8000000,
    declared_cost_cents=300000,
    category="ADDITION",
    begin=True,
):
    """Violation NOTICE_ISSUED, then an after-the-fact application linking it:
    the violation flips to AFTER_THE_FACT_PENDING (PRD §3.8). ctx: owner,
    property, violation (refreshed), application."""
    owner = create_owner()
    prop = create_property(owner["id"], assessed_value_cents=assessed_value_cents)
    violation = create_notice_issued_violation(prop["id"])
    application = submit_application(
        prop["id"],
        owner["id"],
        application_type=category,
        is_visible_from_public_way=True,
        after_the_fact=True,
        violation_id=violation["id"],
        work_items=[work_item(category, "as built", declared_cost_cents)],
    )
    if begin:
        begin_review(application["id"])
    return {
        "owner": owner,
        "property": prop,
        "violation": get_violation(violation["id"]),
        "application": application,
    }


def setup_approved_demolition(
    *,
    tier="LOCAL",
    approve_clock="2026-08-01T00:00:00Z",
    contributing_status="NON_CONTRIBUTING",
    assessed_value_cents=6000000,
    declared_cost_cents=500000,
    property_overrides=None,
):
    """A DEMOLITION application approved at an opened commission hearing
    (DEMOLITION is always COMMISSION track, PRD §3.3): the property advances
    to DEMOLITION_PENDING and a demolition delay is created ACTIVE (PRD §3.7).
    ctx: district, owner, property, application (APPROVED), meeting, hearing,
    delay."""
    if approve_clock is not None:
        set_clock(approve_clock)
    district = create_district(significance_tier=tier)
    owner = create_owner()
    prop_overrides = {
        "district_id": district["id"],
        "contributing_status": contributing_status,
        "assessed_value_cents": assessed_value_cents,
    }
    prop_overrides.update(property_overrides or {})
    prop = create_property(owner["id"], **prop_overrides)
    submitted = submit_application(
        prop["id"],
        owner["id"],
        application_type="DEMOLITION",
        is_visible_from_public_way=True,
        work_items=[work_item("DEMOLITION", "raze", declared_cost_cents)],
    )
    begin_review(submitted["id"])
    accepted = accept_application(
        submitted["id"], [verified_item("DEMOLITION", declared_cost_cents)], "staff-1"
    )
    meeting = create_meeting()
    hearing = schedule_hearing(accepted["id"], meeting["id"])
    open_hearing(hearing["id"])
    decided = decide_by_commissioner(accepted["id"], {"outcome": "APPROVE"})
    delay = get_delay_for_application(accepted["id"])
    return {
        "district": district,
        "owner": owner,
        "property": prop,
        "submitted": submitted,
        "application": decided,
        "meeting": meeting,
        "hearing": hearing,
        "delay": delay,
    }


def setup_certificate_issued(
    *,
    conditions=None,
    issue_clock="2026-08-01T00:00:00Z",
    **approved_kwargs,
):
    """STAFF-track application approved (conditions optional), fee fully paid,
    certificate issued (PRD §3.9). ctx adds certificate."""
    if issue_clock is not None:
        set_clock(issue_clock)
    outcome = "APPROVE_WITH_CONDITIONS" if conditions else "APPROVE"
    ctx = setup_staff_approved(outcome=outcome, conditions=conditions, pay=True,
                               **approved_kwargs)
    certificate = get_success_data(
        api_client.create_certificate(
            {"application_id": ctx["application"]["id"]}, STAFF
        ),
        201,
    )
    ctx["certificate"] = certificate
    return ctx
