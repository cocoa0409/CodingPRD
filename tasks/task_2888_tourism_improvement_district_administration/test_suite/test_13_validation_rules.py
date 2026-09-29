"""Individual validation rules, each observed refusing and then permitting.

Every test here pins one rule and walks both sides of it: the request that the
rule refuses, and the neighbouring request the rule was never meant to touch.
Where a rule is scoped to a key, the scope is exercised too, so a refusal that
came from over-broad matching would be caught as a false negative on the sibling
call rather than as a pass.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
    ERR_DISPUTE_ALREADY_OPEN,
    ERR_DUPLICATE_SIGNATURE,
    ERR_EXPENDITURE_CATEGORY_NOT_PERMITTED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOTICE_TOO_LATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OPERATOR_IDENTITY_UNKNOWN,
    ERR_PROGRAM_BUDGET_EXCEEDED,
    ERR_UNAUTHENTICATED,
    ERR_WORK_PLAN_NOT_APPROVED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import (
    ADMIN,
    BOARD_MEMBER,
    BOARD_MEMBER_2,
    DMO_LIAISON,
    NO_HEADERS,
    UNKNOWN_OPERATOR,
    operator_headers,
)


# --------------------------------------------------------------------------
# Uniqueness of a signature, scoped to the VALID ones
# --------------------------------------------------------------------------
def test_a_second_signature_from_the_same_property_leaves_the_tallies_alone(api):
    """The refused duplicate adds no second 60000000 to the drive, so weighted
    support stays at 0.6000 rather than climbing past unity.

    PRD 3.2: "at most one VALID signature may exist for a given drive-and-property
    pair, a second attempt yielding ERR_DUPLICATE_SIGNATURE".

    Design: Corner/validations/a_second_signature_from_the_same_business_is_refused_as_a_duplicate
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")

    validate_error(
        api.sign_petition(ctx.pd_id, f.signature_payload(ctx.b1_id), headers=ADMIN),
        ERR_DUPLICATE_SIGNATURE,
        expected_status=409,
    )

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, valid_signature_count=1, signed_basis_cents=60000000)
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.6000, "weighted_support_pct")

    signatures, meta = validate_paginated(api.list_drive_signatures(ctx.pd_id, headers=ADMIN))
    assert len(signatures) == 1, (
        "the refused duplicate must not have been recorded, found %d signatures" % len(signatures)
    )
    assert meta["total_count"] == 1, (
        "total_count was %r, expected the one accepted signature" % meta["total_count"]
    )


# --------------------------------------------------------------------------
# Uniqueness of a dispute, scoped to the statement-and-ground pair
# --------------------------------------------------------------------------
def test_the_dispute_slot_is_keyed_on_the_ground_and_freed_by_a_withdrawal(api):
    """A second CALCULATION_ERROR dispute is refused while the first is live, an
    EXEMPT_PROPERTY dispute on the same statement is admitted alongside it, and
    withdrawing the first frees its slot for a fresh row.

    PRD 3.6: "At most one non-terminal dispute may exist per statement-and-ground
    pair: a second CALCULATION_ERROR dispute on a statement that already has one
    live is refused with ERR_DISPUTE_ALREADY_OPEN, while an EXEMPT_PROPERTY dispute
    on the same statement is admissible alongside it."

    PRD 3.6: "Its lodging_business_id is copied from the referenced statement and is
    never supplied by the client, so a dispute can never be attributed to a property
    other than the one billed."

    Design: Corner/validations/a_withdrawn_dispute_frees_its_type_slot_while_the_other_type_was_never_blocked
    """
    ctx = fx.statements_filed(api)
    first = fx.file_dispute(api, ctx, key="dsp1_id")
    assert_fields(first, status="SUBMITTED", dispute_type="CALCULATION_ERROR")

    operator = operator_headers(ctx.b1_id)
    validate_error(
        api.create_dispute(f.dispute_payload(ctx.st1_id), headers=operator),
        ERR_DISPUTE_ALREADY_OPEN,
        expected_status=409,
    )

    exempt = validate_success(
        api.create_dispute(
            f.dispute_payload(
                ctx.st1_id,
                dispute_type="EXEMPT_PROPERTY",
                claimed_adjustment_cents=824500,
                dispute_note="the property is government owned",
            ),
            headers=operator,
        ),
        expected_status=201,
    )
    assert_fields(
        exempt,
        status="SUBMITTED",
        version=1,
        lodging_business_id=ctx.b1_id,
        claimed_adjustment_cents=824500,
    )

    withdrawn = validate_success(
        api.advance_dispute(
            ctx.dsp1_id,
            f.proceeding_payload("WITHDRAW", "settled with the district directly"),
            headers=operator,
        )
    )
    assert_fields(withdrawn, status="WITHDRAWN")

    refiled = validate_success(
        api.create_dispute(f.dispute_payload(ctx.st1_id), headers=operator),
        expected_status=201,
    )
    assert refiled["id"] != ctx.dsp1_id, (
        "the refiled dispute must be a new row, not the withdrawn %r" % ctx.dsp1_id
    )
    assert_fields(
        refiled, status="SUBMITTED", version=1, appeal_count=0, granted_adjustment_cents=0
    )
    assert_null_fields(refiled, "resolved_by_user_id", "resolution_note")

    disputes, _ = validate_paginated(
        api.list_statement_disputes(ctx.st1_id, headers=operator)
    )
    identifiers = {dispute["id"] for dispute in disputes}
    assert ctx.dsp1_id in identifiers, (
        "the withdrawn dispute must be retained, not deleted; got %r" % (identifiers,)
    )
    assert refiled["id"] in identifiers, (
        "the refiled dispute must be listed; got %r" % (identifiers,)
    )

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement, effective_assessment_cents=824500, payment_status="UNPAID"
    )


# --------------------------------------------------------------------------
# The top five rungs of the ladder, on one endpoint
# --------------------------------------------------------------------------
def test_one_filing_endpoint_walks_the_ladder_from_authentication_down_to_existence(api):
    """The same request is sent five times against an identifier that does not
    exist, each call repairing exactly one defect, and the reported failure walks
    down the ladder instead of jumping to the body or the path.

    PRD 2.8: "When several rules could reject the same request, the outcome is
    determined by a fixed priority ladder, evaluated from the top and stopping at
    the first rule that fails."

    PRD 2.1: "If the supplied X-User-ID matches no existing lodging business at all,
    the request is rejected with ERR_OPERATOR_IDENTITY_UNKNOWN (HTTP 403) before any
    path identifier is looked up."

    Design: Corner/validations/statement_filing_priority_ladder_returns_401_403_403_400_then_404
    """
    ctx = fx.period_with_statements(api)
    absent = NON_EXISTENT_UUID
    complete = f.filing_payload(2000, 41225000)
    missing_revenue = {"reported_room_nights": 2000}

    validate_error(
        api.file_statement(absent, missing_revenue, headers=NO_HEADERS),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.file_statement(absent, missing_revenue, headers=BOARD_MEMBER),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.file_statement(absent, missing_revenue, headers=UNKNOWN_OPERATOR),
        ERR_OPERATOR_IDENTITY_UNKNOWN,
        expected_status=403,
    )
    validate_error(
        api.file_statement(absent, missing_revenue, headers=ADMIN),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.file_statement(absent, complete, headers=ADMIN),
        ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
        expected_status=404,
    )

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, filing_status="NOT_FILED", provisional_assessment_cents=0)


# --------------------------------------------------------------------------
# A program funded by a plan that has not been approved
# --------------------------------------------------------------------------
def test_a_program_cannot_be_funded_by_a_plan_still_in_board_review(api):
    """The refusal is decided on the plan row alone: the identical creation request
    is accepted the moment a second board member approves that plan.

    PRD 3.8: "The funding plan's status must be APPROVED; a DRAFT, BOARD_REVIEW,
    AMENDMENT_PENDING or CLOSED plan funds nothing and creation is refused with
    ERR_WORK_PLAN_NOT_APPROVED."

    Design: Corner/validations/a_program_cannot_be_funded_by_a_plan_still_in_board_review
    """
    ctx = fx.statements_filed(api)
    fx.draft_work_plan(api, ctx)
    fx.sponsor_work_plan(api, ctx, headers=BOARD_MEMBER)

    payload = f.marketing_program_payload(ctx.wp_id)
    validate_error(
        api.create_marketing_program(payload, headers=DMO_LIAISON),
        ERR_WORK_PLAN_NOT_APPROVED,
        expected_status=409,
    )

    refused_plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(refused_plan, status="BOARD_REVIEW", committed_program_cents=0)
    programs, meta = validate_paginated(
        api.list_plan_marketing_programs(ctx.wp_id, headers=ADMIN)
    )
    assert programs == [], "the refused creation must have left no program row"
    assert meta["total_count"] == 0, (
        "total_count was %r, expected no programs at all" % meta["total_count"]
    )

    approved = fx.approve_work_plan(api, ctx, headers=BOARD_MEMBER_2)
    assert_fields(approved, status="APPROVED")
    assert_ratio_four_dp(approved["funding_ratio"], 1.1645, "funding_ratio")

    program = validate_success(
        api.create_marketing_program(payload, headers=DMO_LIAISON), expected_status=201
    )
    assert_fields(program, status="PLANNED", committed_cents=62000)
    assert_fields(
        validate_success(api.get_work_plan(ctx.wp_id)), committed_program_cents=62000
    )


# --------------------------------------------------------------------------
# The fourteen-day notice boundary, from one pinned clock
# --------------------------------------------------------------------------
def test_a_notice_exactly_fourteen_days_ahead_is_accepted_and_thirteen_is_not(api):
    """From a clock pinned at 2026-08-01 a record targeted at 2026-08-15 is exactly
    fourteen whole days out and may be noticed, while one targeted a day earlier may
    not.

    PRD 3.9: "NOTICED is accepted from SCHEDULED and requires the logical clock to
    be at least 14 whole days before scheduled_for. Exactly 14 whole days ahead is
    accepted and 13 is not; a notice posted any nearer to the meeting is refused
    with ERR_MEETING_NOTICE_TOO_LATE, since a late notice is no notice."

    Design: Corner/validations/notice_exactly_fourteen_days_ahead_is_accepted_and_thirteen_is_not
    """
    ctx = fx.active_district(api)
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.schedule_transparency_record(
        api,
        ctx,
        key="tr_report",
        record_type="ANNUAL_REPORT",
        scheduled_for="2026-08-15T00:00:00Z",
        required_by="2026-10-01T00:00:00Z",
    )
    fx.schedule_transparency_record(
        api,
        ctx,
        key="tr_meeting",
        record_type="PUBLIC_MEETING",
        scheduled_for="2026-08-14T00:00:00Z",
        required_by="2026-10-01T00:00:00Z",
    )

    validate_error(
        api.advance_transparency_record(
            ctx.tr_meeting, f.advance_transparency_payload("NOTICED"), headers=ADMIN
        ),
        ERR_MEETING_NOTICE_TOO_LATE,
        expected_status=409,
    )

    meeting = validate_success(api.get_transparency_record(ctx.tr_meeting))
    assert_fields(meeting, status="SCHEDULED")
    assert_null_fields(meeting, "noticed_on")

    report = validate_success(
        api.advance_transparency_record(
            ctx.tr_report, f.advance_transparency_payload("NOTICED"), headers=ADMIN
        )
    )
    assert_fields(report, status="NOTICED")
    assert_instant_equals(report["noticed_on"], "2026-08-01T00:00:00Z", "noticed_on")

    assert_fields(
        validate_success(api.get_district(ctx.d_id)), transparency_standing="COMPLIANT"
    )


# --------------------------------------------------------------------------
# An aggregate ceiling over sibling programs
# --------------------------------------------------------------------------
def test_committed_program_spend_may_equal_but_not_exceed_the_marketing_line(api):
    """Two programs summing to exactly the 650000 marketing line are both accepted
    and a third of a single cent is refused, so the ceiling is read over the
    siblings rather than per request.

    PRD 3.8: "the sum of committed_cents over the plan's non-cancelled programs must
    not exceed the plan's sales_and_marketing_cents, exceeding it with
    ERR_PROGRAM_BUDGET_EXCEEDED".

    Design: Corner/validations/committed_program_spend_may_equal_but_not_exceed_the_marketing_line
    """
    ctx = fx.statements_filed(api)
    plan = fx.approved_work_plan(api, ctx)
    assert_fields(plan, sales_and_marketing_cents=650000, committed_program_cents=0)

    first = fx.create_program(
        api, ctx, key="mp_a", name="Autumn Group Sales Push", committed_cents=400000
    )
    assert_fields(first, status="PLANNED", committed_cents=400000)
    assert_fields(
        validate_success(api.get_work_plan(ctx.wp_id)), committed_program_cents=400000
    )

    second = fx.create_program(
        api,
        ctx,
        key="mp_b",
        name="Winter Paid Search",
        channel="PAID_SEARCH",
        committed_cents=250000,
    )
    assert_fields(second, status="PLANNED", committed_cents=250000)
    assert_fields(
        validate_success(api.get_work_plan(ctx.wp_id)), committed_program_cents=650000
    )

    validate_error(
        api.create_marketing_program(
            f.marketing_program_payload(
                ctx.wp_id,
                name="One Cent Too Far",
                channel="TRADE_SHOW",
                committed_cents=1,
            ),
            headers=DMO_LIAISON,
        ),
        ERR_PROGRAM_BUDGET_EXCEEDED,
        expected_status=409,
    )

    assert_fields(
        validate_success(api.get_work_plan(ctx.wp_id)), committed_program_cents=650000
    )
    programs, meta = validate_paginated(
        api.list_plan_marketing_programs(ctx.wp_id, headers=ADMIN)
    )
    assert len(programs) == 2, (
        "the refused creation must have left exactly two programs, found %d" % len(programs)
    )
    assert meta["total_count"] == 2, (
        "total_count was %r, expected the two accepted programs" % meta["total_count"]
    )


# --------------------------------------------------------------------------
# A category permitted only under one assessment method
# --------------------------------------------------------------------------
CAPITAL_LINES = [
    f.expenditure_line("SALES_AND_MARKETING", 700000, "paid search and group sales"),
    f.expenditure_line("ADMINISTRATION", 100000, "district staff"),
    f.expenditure_line("CAPITAL_IMPROVEMENT", 200000, "wayfinding signage on the promenade"),
]

SUMMIT_RIDGE_ROLL = [
    (
        "b1_id",
        dict(
            legal_name="Summit Ridge Lodge",
            boundary_zone="ZONE_CORE",
            classification="FULL_SERVICE",
            room_count=300,
            prior_year_gross_room_revenue_cents=60000000,
            operator_contact_email="ops@summitridgelodge.example",
        ),
    ),
    (
        "b2_id",
        dict(
            legal_name="Summit Ridge Chalet",
            boundary_zone="ZONE_PERIMETER",
            classification="BOUTIQUE",
            room_count=40,
            prior_year_gross_room_revenue_cents=25000000,
            operator_contact_email="ops@summitridgechalet.example",
        ),
    ),
    (
        "b3_id",
        dict(
            legal_name="Summit Ridge Cabins",
            boundary_zone="ZONE_PERIMETER",
            classification="SHORT_TERM_RENTAL",
            room_count=20,
            prior_year_gross_room_revenue_cents=15000000,
            operator_contact_email="ops@summitridgecabins.example",
        ),
    ),
]


def _active_tiered_district(api):
    """A second, independent district carried to ACTIVE on the
    TIERED_BY_CLASSIFICATION method, so that a plan may be drafted against it."""
    ctx = fx.create_district(
        api,
        name="Summit Ridge Tourism Improvement District",
        assessment_method="TIERED_BY_CLASSIFICATION",
    )
    for key, inputs in SUMMIT_RIDGE_ROLL:
        fx.add_business(api, ctx, f.lodging_business_payload(ctx.d_id, **inputs), key)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.tally(api, ctx)
    fx.certify(api, ctx)
    fx.advance_district(api, ctx, "ACTIVE")
    return ctx


def test_a_capital_line_is_permitted_on_a_pct_district_and_refused_on_a_tiered_one(api):
    """Two plans carrying identical expenditure lines are approved against two
    districts that differ only in assessment method, and only the percentage-of-
    revenue district may carry the capital improvement line.

    PRD 3.7: "A CAPITAL_IMPROVEMENT line is permitted only when the district's
    assessment_method is PCT_OF_ROOM_REVENUE; under either other method its presence
    yields ERR_EXPENDITURE_CATEGORY_NOT_PERMITTED."

    PRD 3.7: "Creation computes total_budget_cents as the sum of the line amounts,
    then the five per-category rollups administration_cents,
    contingency_reserve_cents, sales_and_marketing_cents, destination_events_cents
    and capital_improvement_cents, each being the amount of the corresponding line or
    0 when that category is absent."

    Design: Corner/validations/capital_improvement_is_permitted_on_a_pct_district_and_refused_on_a_tiered_one
    """
    pct = fx.statements_filed(api)
    fx.draft_work_plan(api, pct, expenditure_lines=CAPITAL_LINES)
    fx.sponsor_work_plan(api, pct, headers=BOARD_MEMBER)

    tiered = _active_tiered_district(api)
    assert_fields(
        validate_success(api.get_district(tiered.d_id)),
        assessment_method="TIERED_BY_CLASSIFICATION",
        status="ACTIVE",
    )
    fx.draft_work_plan(api, tiered, expenditure_lines=CAPITAL_LINES)
    fx.sponsor_work_plan(api, tiered, headers=BOARD_MEMBER)

    validate_error(
        api.board_action(
            tiered.wp_id, f.board_action_payload("APPROVE"), headers=BOARD_MEMBER_2
        ),
        ERR_EXPENDITURE_CATEGORY_NOT_PERMITTED,
        expected_status=409,
    )
    refused = validate_success(api.get_work_plan(tiered.wp_id))
    assert_fields(refused, status="BOARD_REVIEW", capital_improvement_cents=200000)
    assert_null_fields(refused, "approver_user_id", "approved_at")

    approved = validate_success(
        api.board_action(pct.wp_id, f.board_action_payload("APPROVE"), headers=BOARD_MEMBER_2)
    )
    assert_fields(
        approved,
        status="APPROVED",
        capital_improvement_cents=200000,
        total_budget_cents=1000000,
        administration_cents=100000,
        sales_and_marketing_cents=700000,
        contingency_reserve_cents=0,
    )
    assert_ratio_four_dp(approved["funding_ratio"], 1.1645, "funding_ratio")


# --------------------------------------------------------------------------
# Ownership read after existence
# --------------------------------------------------------------------------
def test_an_operator_probing_an_absent_statement_gets_a_404_before_any_403(api):
    """The same operator gets a 404 for an identifier that resolves to nothing and a
    403 for one that resolves to somebody else's statement, so ownership is decided
    only once existence has produced a row to read.

    PRD 2.1: "Ownership is deliberately evaluated after existence, so that a
    genuinely absent resource still yields a 404 rather than leaking, through a 403,
    the fact that the resource exists and belongs to somebody else."

    PRD 2.8: "because ownership sits below existence, an operator probing for another
    property's statement identifiers learns only that they do not exist as far as it
    is concerned - a 404, never a 403."

    Design: Corner/validations/operator_ownership_is_checked_after_existence_so_a_missing_statement_returns_404
    """
    ctx = fx.period_with_statements(api)
    intruder = operator_headers(ctx.b2_id)
    payload = f.filing_payload(2000, 41225000)

    validate_error(
        api.file_statement(NON_EXISTENT_UUID, payload, headers=intruder),
        ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.file_statement(ctx.st1_id, payload, headers=intruder),
        ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, filing_status="NOT_FILED", provisional_assessment_cents=0)
