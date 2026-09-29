"""Requests that violate two rules at once, and which rule gets to answer.

The priority ladder is evaluated from the top and stops at the first rule that
fails, so a request breaking two rules always reports the higher one.  Each test
here builds a state in which two named rules are simultaneously violated, then
repairs the higher one so that the lower one is observed reporting on its own.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADMIN_SHARE_EXCEEDED,
    ERR_BUSINESS_OUTSIDE_BOUNDARY,
    ERR_FILING_WINDOW_CLOSED,
    ERR_PETITION_WINDOW_CLOSED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STATEMENT_ALREADY_CERTIFIED,
)
from test_helpers.assertions import assert_fields, assert_null_fields
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    AUDITOR_2,
    BOARD_MEMBER,
    BOARD_MEMBER_2,
    BOARD_MEMBER_USER_ID,
    operator_headers,
)


# --------------------------------------------------------------------------
# Rung 7 state guard over rung 10 temporal window, with rung 8 satisfied
# --------------------------------------------------------------------------
def _certified_and_filed_statements_in_a_closed_period(api):
    """Carry one statement all the way to CERTIFIED inside a CLOSED period while a
    second statement of the same period stops at FILED."""
    ctx = fx.statements_filed(api)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.audit_statement(api, ctx, "st1_id", headers=AUDITOR)
    validate_success(
        api.audit_certify_statement(ctx.st1_id, f.certify_statement_payload(), headers=AUDITOR_2)
    )
    return ctx


def test_certification_outranks_the_closed_filing_window_on_an_amendment(api):
    """An amendment of a CERTIFIED statement in a CLOSED period carries a correct
    expected_statement_version, so only the state guard and the temporal window
    are in play, and the state guard answers.

    PRD 2.8: "State preconditions ... the specific guards
    ERR_STATEMENT_ALREADY_CERTIFIED, ERR_DISTRICT_NOT_ACTIVE,
    ERR_PERIOD_NOT_CLOSED, ERR_WORK_PLAN_NOT_APPROVED,
    ERR_DMO_AGREEMENT_NOT_EXECUTED, ERR_PROGRAM_SPEND_FROZEN and
    ERR_CLAIMS_PENDING_VERIFICATION sit at the same rung".

    Design: Difficulty/priority_pair_validation_conflict/certified_statement_beats_closed_filing_window_with_occ_already_satisfied
    """
    ctx = _certified_and_filed_statements_in_a_closed_period(api)

    certified = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(certified, filing_status="CERTIFIED")

    response = api.amend_statement(
        ctx.st1_id,
        f.statement_amendment_payload(certified["version"], 2100, 42000000),
        headers=operator_headers(ctx.b1_id),
    )
    validate_error(response, ERR_STATEMENT_ALREADY_CERTIFIED, expected_status=409)

    unchanged = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        unchanged,
        filing_status="CERTIFIED",
        reported_room_nights=2000,
        amendment_count=0,
    )


def test_the_closed_filing_window_answers_once_certification_is_out_of_the_way(api):
    """The sibling statement of the same CLOSED period is only FILED, so with the
    state guard removed the temporal window reports on its own.

    PRD 3.3: "A period that is CLOSED or DELINQUENCY_SWEPT, or a clock already
    past due_date, is refused with ERR_FILING_WINDOW_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/certified_statement_beats_closed_filing_window_with_occ_already_satisfied
    """
    ctx = _certified_and_filed_statements_in_a_closed_period(api)

    filed = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(filed, filing_status="FILED")

    response = api.amend_statement(
        ctx.st2_id,
        f.statement_amendment_payload(filed["version"], 700, 21000000),
        headers=operator_headers(ctx.b2_id),
    )
    validate_error(response, ERR_FILING_WINDOW_CLOSED, expected_status=409)

    unchanged = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        unchanged,
        filing_status="FILED",
        reported_room_nights=600,
        amendment_count=0,
    )


# --------------------------------------------------------------------------
# Rung 9 separation of duties over rung 12 structural cap
# --------------------------------------------------------------------------
ADMIN_HEAVY_LINES = [
    f.expenditure_line("SALES_AND_MARKETING", 600000, "autumn campaign"),
    f.expenditure_line("ADMINISTRATION", 300000, "district administration"),
    f.expenditure_line("CONTINGENCY_RESERVE", 100000, "reserve"),
]


def _sponsored_plan_breaching_the_admin_cap(api):
    """Draft and sponsor a 1000000-cent plan whose 300000 of administration is
    twice the 150000 the cap allows."""
    ctx = fx.statements_filed(api)
    fx.draft_work_plan(api, ctx, expenditure_lines=ADMIN_HEAVY_LINES)
    fx.sponsor_work_plan(api, ctx, headers=BOARD_MEMBER)
    return ctx


def test_the_sponsor_approving_its_own_plan_reports_the_separation_failure(api):
    """The sponsor's own approval of a plan that also breaches the administration
    cap reports the separation of duties rather than the cap.

    PRD 2.8: "Because these sit above every temporal, referential, constraint and
    fiscal rule, an approval attempted by the plan's own sponsor reports the
    separation failure even when the plan's category mix would also have failed a
    cap."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_administration_share_cap_on_plan_approval
    """
    ctx = _sponsored_plan_breaching_the_admin_cap(api)

    sponsored = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        sponsored,
        status="BOARD_REVIEW",
        sponsor_user_id=BOARD_MEMBER_USER_ID,
        administration_cents=300000,
        total_budget_cents=1000000,
    )

    response = api.board_action(ctx.wp_id, f.board_action_payload("APPROVE"), headers=BOARD_MEMBER)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(plan, status="BOARD_REVIEW")
    assert_null_fields(plan, "approver_user_id", "approved_at")


def test_the_administration_cap_answers_once_a_second_board_member_approves(api):
    """With a different board member acting, the separation rule is satisfied and
    the 0.15 administration cap reports on its own.

    PRD 3.7: "The administration cap is total_budget_cents multiplied by 0.15,
    rounded half up to a whole cent. The ADMINISTRATION amount must be at or
    below that cap, and exceeding it yields ERR_ADMIN_SHARE_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_administration_share_cap_on_plan_approval
    """
    ctx = _sponsored_plan_breaching_the_admin_cap(api)

    response = api.board_action(
        ctx.wp_id, f.board_action_payload("APPROVE"), headers=BOARD_MEMBER_2
    )
    validate_error(response, ERR_ADMIN_SHARE_EXCEEDED, expected_status=409)

    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(plan, status="BOARD_REVIEW", administration_cents=300000)
    assert_null_fields(plan, "approver_user_id", "approved_at")


# --------------------------------------------------------------------------
# Rung 10 temporal window over rung 11 referential boundary rule
# --------------------------------------------------------------------------
def _cliffside_drive_with_a_property_pushed_out_of_boundary(api):
    """Open a formation drive over three properties and then shrink the district's
    boundary so that the perimeter property no longer belongs to it."""
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(api, name="Cliffside Tourism Improvement District")
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Cliffside Grand Hotel",
            room_count=100,
            prior_year_gross_room_revenue_cents=50000000,
        ),
        "b1_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Seawall Inn",
            classification="LIMITED_SERVICE",
            room_count=80,
            prior_year_gross_room_revenue_cents=30000000,
        ),
        "b2_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Terrace Boutique",
            boundary_zone="ZONE_PERIMETER",
            classification="BOUTIQUE",
            room_count=60,
            prior_year_gross_room_revenue_cents=20000000,
        ),
        "b3_id",
    )
    fx.open_formation_drive(api, ctx)
    validate_success(
        api.revise_district_boundary(
            ctx.d_id, f.boundary_revision_payload(["ZONE_CORE"]), headers=ADMIN
        )
    )
    return ctx


def test_a_signer_outside_the_boundary_is_refused_while_the_window_is_open(api):
    """Inside the drive's window the only rule left to break is the boundary rule,
    so the referential failure is what the signer sees.

    PRD 3.2: "The signer must belong to the same district as the drive, must have
    a boundary_zone that is a member of the district's included_zones, and must
    have status ASSESSABLE; a failure of any of those three is
    ERR_BUSINESS_OUTSIDE_BOUNDARY."

    Design: Difficulty/priority_pair_validation_conflict/closed_petition_window_beats_outside_boundary_signer
    """
    ctx = _cliffside_drive_with_a_property_pushed_out_of_boundary(api)
    fx.set_clock(api, "2026-08-15T00:00:00Z")

    response = api.sign_petition(ctx.pd_id, f.signature_payload(ctx.b3_id), headers=ADMIN)
    validate_error(response, ERR_BUSINESS_OUTSIDE_BOUNDARY, expected_status=409)

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, status="OPEN", valid_signature_count=0, signed_basis_cents=0)


def test_the_closed_petition_window_outranks_the_boundary_rule(api):
    """Once the clock passes closes_at the very same signature attempt reports the
    temporal failure instead, because temporal rules sit above referential ones.

    PRD 2.8: rung 10 is "Temporal windows — ERR_PETITION_WINDOW_CLOSED,
    ERR_RENEWAL_WINDOW_NOT_OPEN, ERR_MEETING_NOTICE_TOO_LATE,
    ERR_CLAIM_OUTSIDE_BOOKING_WINDOW and ERR_FILING_WINDOW_CLOSED" and rung 11 is
    "Referential rules — ERR_BUSINESS_OUTSIDE_BOUNDARY, ERR_BUSINESS_EXEMPT,
    ERR_DUPLICATE_SIGNATURE, ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD,
    ERR_DISPUTE_ALREADY_OPEN and ERR_REMITTANCE_ALREADY_REVERSED."

    Design: Difficulty/priority_pair_validation_conflict/closed_petition_window_beats_outside_boundary_signer
    """
    ctx = _cliffside_drive_with_a_property_pushed_out_of_boundary(api)
    fx.set_clock(api, "2026-09-02T00:00:00Z")

    response = api.sign_petition(ctx.pd_id, f.signature_payload(ctx.b3_id), headers=ADMIN)
    validate_error(response, ERR_PETITION_WINDOW_CLOSED, expected_status=409)

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, status="OPEN", valid_signature_count=0, signed_basis_cents=0)
    assert drive["weighted_support_pct"] == 0.0
