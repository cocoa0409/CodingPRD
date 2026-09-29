"""Every branch, constant and rounding step of the money arithmetic.

The assessment body has three method branches and one shared cap, the waterfall
has three debts and one overflow, the sweep has two rates, and the budget has
five per-category rollups.  Each test here pins one of those computations on
inputs chosen so that a wrong constant, a wrong branch or a wrong rounding mode
produces a different integer.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_REMITTANCE_EXCEEDS_TOTAL_DUE,
    ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
    assert_waterfall_allocation,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    AUDITOR_USER_ID,
    BOARD_MEMBER,
    BOARD_MEMBER_2,
    BOARD_MEMBER_2_USER_ID,
    operator_headers,
)

#: The three Cove Reach properties, billed per occupied room night.
COVE_REACH_ROLL = [
    (
        "b1_id",
        dict(
            legal_name="Cove Reach Grand",
            boundary_zone="ZONE_CORE",
            classification="FULL_SERVICE",
            room_count=400,
            prior_year_gross_room_revenue_cents=60000000,
            operator_contact_email="ops@covereachgrand.example",
        ),
    ),
    (
        "b2_id",
        dict(
            legal_name="Cove Reach Boutique",
            boundary_zone="ZONE_PERIMETER",
            classification="BOUTIQUE",
            room_count=60,
            prior_year_gross_room_revenue_cents=15000000,
            operator_contact_email="ops@covereachboutique.example",
        ),
    ),
    (
        "b3_id",
        dict(
            legal_name="Cove Reach Inn",
            boundary_zone="ZONE_CORE",
            classification="LIMITED_SERVICE",
            room_count=100,
            prior_year_gross_room_revenue_cents=25000000,
            operator_contact_email="ops@covereachinn.example",
        ),
    ),
]

#: The three Summit Ridge properties, billed on a flat fee per classification.
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


def _active_district_with_a_generated_period(api, name, assessment_method, roll):
    """Carry a district on the named assessment method from proposal to an OPEN
    period whose statements have been generated.

    ``roll`` is a sequence of ``(key, business inputs)`` pairs; the first entry
    signs the formation drive, so it must hold at least the formation threshold
    of the roll's revenue on its own.
    """
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(api, name=name, assessment_method=assessment_method)
    for key, inputs in roll:
        fx.add_business(api, ctx, f.lodging_business_payload(ctx.d_id, **inputs), key)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.tally(api, ctx)
    fx.certify(api, ctx)
    fx.advance_district(api, ctx, "ACTIVE")
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)
    return ctx


def _file(api, ctx, statement_key, nights, revenue_cents):
    """File a statement as the district administrator, which the PRD permits on
    the operator's behalf, and return the updated statement."""
    return validate_success(
        api.file_statement(
            ctx[statement_key], f.filing_payload(nights, revenue_cents), headers=ADMIN
        )
    )


def _statement(api, statement_id):
    return validate_success(api.get_assessment_statement(statement_id, headers=ADMIN))


# --------------------------------------------------------------------------
# The per-occupied-room-night branch
# --------------------------------------------------------------------------
def test_the_per_night_branch_ignores_revenue_and_lands_on_the_period_ceiling(api):
    """Three rows on a PER_OCCUPIED_ROOM_NIGHT district bill 300 cents a night
    times the class multiplier: the largest gross of 3000000 is cut to the 2500000
    ceiling, and no row equals two percent of its reported revenue.

    PRD 3.3: "Under PER_OCCUPIED_ROOM_NIGHT, the gross figure is the nights basis
    multiplied by 300 cents per occupied room night and then by the same class
    multiplier for the class basis, rounded half up to a whole cent. No floor
    applies on this branch."

    Design: Corner/calculations/per_occupied_room_night_branch_ignores_revenue_and_binds_the_period_cap
    """
    ctx = _active_district_with_a_generated_period(
        api,
        "Cove Reach Tourism Improvement District",
        "PER_OCCUPIED_ROOM_NIGHT",
        COVE_REACH_ROLL,
    )

    full_service = _file(api, ctx, "st1_id", 10000, 60000000)
    assert_fields(
        full_service,
        assessment_method_at_period_start="PER_OCCUPIED_ROOM_NIGHT",
        provisional_assessment_cents=2500000,
        effective_assessment_cents=2500000,
        total_due_cents=2500000,
    )

    boutique = _file(api, ctx, "st2_id", 700, 15000000)
    assert_fields(boutique, provisional_assessment_cents=189000)

    limited_service = _file(api, ctx, "st3_id", 1000, 25000000)
    assert_fields(limited_service, provisional_assessment_cents=255000)

    for statement, revenue_cents in (
        (full_service, 60000000),
        (boutique, 15000000),
        (limited_service, 25000000),
    ):
        two_percent = revenue_cents * 2 // 100
        assert statement["provisional_assessment_cents"] != two_percent, (
            f"{statement['id']} was billed {two_percent}, which is two percent of "
            "its reported revenue, so the percentage branch ran"
        )


# --------------------------------------------------------------------------
# The tiered-by-classification branch
# --------------------------------------------------------------------------
def test_the_tiered_branch_multiplies_a_flat_fee_by_the_zone_factor_alone(api):
    """A row reporting zero nights and zero revenue is still billed 218750,
    because on this branch the bill is the flat fee for the class times the zone
    factor and nothing else.

    PRD 3.3: "Under TIERED_BY_CLASSIFICATION, the gross figure is the flat fee for
    the class basis multiplied by the zone factor for the zone basis, rounded half
    up to a whole cent. The flat fees are 500000 cents for FULL_SERVICE, 300000
    cents for LIMITED_SERVICE, 350000 cents for BOUTIQUE and 150000 cents for
    SHORT_TERM_RENTAL. The zone factors are 1.0000 for ZONE_CORE, 0.6250 for
    ZONE_PERIMETER and 0.0000 for OUTSIDE. Neither the revenue basis nor the
    nights basis participates on this branch."

    Design: Corner/calculations/tiered_by_classification_branch_multiplies_the_flat_fee_by_the_zone_factor
    """
    ctx = _active_district_with_a_generated_period(
        api,
        "Summit Ridge Tourism Improvement District",
        "TIERED_BY_CLASSIFICATION",
        SUMMIT_RIDGE_ROLL,
    )

    core_full_service = _file(api, ctx, "st1_id", 5000, 60000000)
    assert_fields(
        core_full_service,
        assessment_method_at_period_start="TIERED_BY_CLASSIFICATION",
        provisional_assessment_cents=500000,
    )

    perimeter_boutique = _file(api, ctx, "st2_id", 0, 0)
    assert_fields(
        perimeter_boutique,
        reported_room_nights=0,
        reported_gross_room_revenue_cents=0,
        provisional_assessment_cents=218750,
    )

    perimeter_short_term = _file(api, ctx, "st3_id", 900, 15000000)
    assert_fields(perimeter_short_term, provisional_assessment_cents=93750)

    for statement in (core_full_service, perimeter_boutique, perimeter_short_term):
        assert statement["provisional_assessment_cents"] < 2500000, (
            f"{statement['id']} was billed "
            f"{statement['provisional_assessment_cents']}, which the 2500000 "
            "ceiling should never have had to touch"
        )


# --------------------------------------------------------------------------
# The one rounding step inside the percentage branch
# --------------------------------------------------------------------------
def test_a_perimeter_limited_service_row_rounds_a_half_cent_upwards(api):
    """1600800 times 0.0125 times 0.85 is exactly 17008.5, and the stored figure
    must be 17009, which truncation and round-half-even both miss.

    PRD 2.6: "Every rounding step in this specification uses round half up: a
    value exactly on the halfway mark rounds away from zero. Monetary results
    round to a whole cent."

    Design: Corner/calculations/perimeter_limited_service_assessment_lands_on_a_half_cent_and_rounds_up
    """
    ctx = fx.active_district(api)
    reclassified = validate_success(
        api.revise_lodging_business(
            ctx.b3_id, f.revision_payload(classification="LIMITED_SERVICE"), headers=ADMIN
        )
    )
    assert_fields(reclassified, classification="LIMITED_SERVICE", boundary_zone="ZONE_PERIMETER")

    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)

    statement = validate_success(
        api.file_statement(
            ctx.st3_id, f.filing_payload(100, 1600800), headers=operator_headers(ctx.b3_id)
        )
    )
    assert_fields(
        statement,
        zone_at_period_start="ZONE_PERIMETER",
        classification_at_period_start="LIMITED_SERVICE",
        provisional_assessment_cents=17009,
        effective_assessment_cents=17009,
        total_due_cents=17009,
    )
    assert statement["provisional_assessment_cents"] != 17008, (
        "17008 is the truncated and the round-half-even answer, not the "
        "round-half-up one"
    )


# --------------------------------------------------------------------------
# Which rows the generation pass reads
# --------------------------------------------------------------------------
def test_generation_skips_the_exempt_row_then_backfills_it_and_refuses_a_third_run(api):
    """Exempting one property narrows the generated set to three, returning it to
    the set backfills exactly one statement without duplicating the other three,
    and a third run that would generate nothing is refused.

    PRD 3.3: "At most one statement may exist per period-and-property pair, so a
    re-run generates only the eligible properties still missing one; a re-run on
    which no eligible property is missing a statement, and where generated_count
    would therefore be 0, is refused outright with
    ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD."

    Design: Corner/calculations/generation_skips_the_exempt_property_then_backfills_it_and_refuses_a_third_run
    """
    ctx = fx.active_district(api)
    exempted = validate_success(
        api.revise_lodging_business(
            ctx.b4_id, f.revision_payload(exempt_status="GOVERNMENT_OWNED"), headers=ADMIN
        )
    )
    assert_fields(exempted, status="EXEMPT", exempt_status="GOVERNMENT_OWNED")
    assert_fields(
        validate_success(api.get_district(ctx.d_id)),
        assessable_basis_cents=95000000,
        assessable_business_count=3,
    )

    fx.open_period(api, ctx)
    first_run = fx.generate_statements(api, ctx)
    assert_fields(
        first_run, assessment_period_id=ctx.ap_id, generated_count=3, skipped_count=1
    )
    assert len(first_run["statement_ids"]) == 3, (
        f"the first run reported {len(first_run['statement_ids'])} statement ids, "
        "expected 3"
    )
    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)),
        statement_count=3,
    )

    restored = validate_success(
        api.revise_lodging_business(
            ctx.b4_id, f.revision_payload(exempt_status="NONE"), headers=ADMIN
        )
    )
    assert_fields(restored, status="ASSESSABLE", exempt_status="NONE")
    assert_fields(
        validate_success(api.get_district(ctx.d_id)),
        assessable_basis_cents=100000000,
        assessable_business_count=4,
    )

    second_run = fx.generate_statements(api, ctx)
    assert_fields(second_run, generated_count=1, skipped_count=3)
    assert len(second_run["statement_ids"]) == 1, (
        f"the backfill reported {len(second_run['statement_ids'])} statement ids, "
        "expected 1"
    )
    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)),
        statement_count=4,
    )

    backfilled, meta = validate_paginated(
        api.list_period_statements(
            ctx.ap_id, headers=ADMIN, params={"lodging_business_id": ctx.b4_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"the roll's newest property holds {meta['total_count']} statements of "
        "this period, expected exactly 1"
    )
    assert_fields(
        backfilled[0],
        zone_at_period_start="ZONE_PERIMETER",
        classification_at_period_start="SHORT_TERM_RENTAL",
        assessment_method_at_period_start="PCT_OF_ROOM_REVENUE",
    )

    validate_error(
        api.generate_statements(ctx.ap_id, headers=ADMIN),
        ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD,
        expected_status=409,
    )
    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)),
        statement_count=4,
    )


# --------------------------------------------------------------------------
# The budget rollups, sitting exactly on two ceilings
# --------------------------------------------------------------------------
def test_the_plan_rollups_sit_exactly_on_the_admin_and_contingency_ceilings(api):
    """A 1000000-cent budget with 150000 of administration and 100000 of
    contingency lands exactly on both caps, which inclusive comparisons must
    accept, and the forecast aggregates the two filed statements alone.

    PRD 3.7: "assessment_revenue_forecast_cents is the sum of
    effective_assessment_cents over every assessment statement belonging to a
    period of the plan's district whose period_label begins with the characters FY
    followed by the plan's fiscal_year, counting only statements whose
    filing_status is FILED, AMENDED, AUDITED or CERTIFIED - a statement still
    NOT_FILED contributes nothing."

    Design: Corner/calculations/plan_rollups_sit_exactly_on_the_admin_and_contingency_caps_at_approval
    """
    ctx = fx.statements_filed(api)
    fx.draft_work_plan(api, ctx)
    fx.sponsor_work_plan(api, ctx, headers=BOARD_MEMBER)

    approved = validate_success(
        api.board_action(
            ctx.wp_id,
            f.board_action_payload("APPROVE", "approved at the August board meeting"),
            headers=BOARD_MEMBER_2,
        )
    )
    assert_fields(
        approved,
        status="APPROVED",
        total_budget_cents=1000000,
        administration_cents=150000,
        contingency_reserve_cents=100000,
        sales_and_marketing_cents=650000,
        destination_events_cents=100000,
        capital_improvement_cents=0,
        assessment_revenue_forecast_cents=1164500,
        approver_user_id=BOARD_MEMBER_2_USER_ID,
        revision_count=0,
        committed_program_cents=0,
    )
    assert_ratio_four_dp(approved["funding_ratio"], 1.1645, "funding_ratio")
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00Z", "approved_at")


def _only_the_first_statement_filed(api):
    """An OPEN period holding four statements of which only the core full-service
    property's is filed, so the other three carry a zero balance and the sweep
    passes over them."""
    ctx = fx.period_with_statements(api)
    fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    return ctx


# --------------------------------------------------------------------------
# The three debts of the waterfall, in order
# --------------------------------------------------------------------------
def test_a_payment_fills_interest_then_penalty_then_principal_and_nothing_else(api):
    """A 500-cent payment against a swept statement lands 412 on interest and 88
    on penalty, leaving principal untouched, and the row keeps reporting its
    enforcement state rather than reverting to merely part paid.

    PRD 3.4: "The allocation of a payment is a strict cascade over three debts and
    one overflow, and each bucket is filled to its outstanding balance before a
    single cent reaches the next."

    PRD 3.4: "DELINQUENT is tested before PARTIALLY_PAID, so a part-paid statement
    that has been swept keeps reporting its enforcement state rather than
    reverting to a merely part-paid one."

    Design: Corner/calculations/remittance_waterfall_fills_interest_then_penalty_then_principal_in_that_order
    """
    ctx = _only_the_first_statement_filed(api)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.set_clock(api, "2026-11-26T00:00:00Z")
    fx.sweep_period(api, ctx)

    swept = _statement(api, ctx.st1_id)
    assert_fields(
        swept,
        penalty_cents=82450,
        interest_cents=412,
        total_due_cents=907362,
        delinquency_stage="NOTICE",
        payment_status="DELINQUENT",
    )

    token = validate_success(
        api.submit_remittance(
            ctx.st1_id,
            f.remittance_payload(500, "2026-11-26T00:00:00Z", "ACH"),
            headers=operator_headers(ctx.b1_id),
        ),
        expected_status=201,
    )
    assert_waterfall_allocation(token, interest=412, penalty=88, principal=0, credit=0)

    part_paid = _statement(api, ctx.st1_id)
    assert_fields(
        part_paid,
        interest_paid_cents=412,
        penalty_paid_cents=88,
        principal_paid_cents=0,
        total_due_cents=906862,
        payment_status="DELINQUENT",
    )

    remainder = validate_success(
        api.submit_remittance(
            ctx.st1_id,
            f.remittance_payload(906862, "2026-11-26T00:00:00Z", "ACH"),
            headers=operator_headers(ctx.b1_id),
        ),
        expected_status=201,
    )
    assert_waterfall_allocation(
        remainder, interest=0, penalty=82362, principal=824500, credit=0
    )

    retired = _statement(api, ctx.st1_id)
    assert_fields(
        retired,
        interest_paid_cents=412,
        penalty_paid_cents=82450,
        principal_paid_cents=824500,
        credit_balance_cents=0,
        total_due_cents=0,
        payment_status="PAID_IN_FULL",
        delinquency_stage="NOTICE",
    )

    validate_error(
        api.submit_remittance(
            ctx.st1_id,
            f.remittance_payload(500001, "2026-11-26T00:00:00Z", "ACH"),
            headers=operator_headers(ctx.b1_id),
        ),
        ERR_REMITTANCE_EXCEEDS_TOTAL_DUE,
        expected_status=409,
    )

    assert_fields(
        validate_success(api.get_district(ctx.d_id)),
        collected_to_date_cents=907362,
        delinquent_charges_cents=82862,
    )


# --------------------------------------------------------------------------
# The overflow, at exactly the tolerance
# --------------------------------------------------------------------------
def test_an_overpayment_exactly_at_the_tolerance_is_banked_as_credit(api):
    """Against a 240000 balance a payment of exactly 740000 is accepted, and the
    500000 that overflows every debt is preserved as credit rather than discarded.

    PRD 3.4: "Overpayment is tolerated but bounded - amount_cents may exceed the
    statement's total_due_cents by at most 500000 cents, and a payment exceeding
    that tolerance is refused with ERR_REMITTANCE_EXCEEDS_TOTAL_DUE rather than
    banked."

    PRD 3.4: "REFUND_DUE is tested before PAID_IN_FULL, so a fully retired
    statement holding credit reports the refund rather than the settlement."

    Design: Corner/calculations/overpayment_exactly_at_the_tolerance_overflows_into_credit_and_flags_refund_due
    """
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st2_id", "b2_id", 100000, method="ACH", key="rem_a")

    part_paid = _statement(api, ctx.st2_id)
    assert_fields(
        part_paid,
        effective_assessment_cents=340000,
        principal_paid_cents=100000,
        total_due_cents=240000,
        payment_status="PARTIALLY_PAID",
    )

    overflowing = validate_success(
        api.submit_remittance(
            ctx.st2_id,
            f.remittance_payload(740000, "2026-08-01T00:00:00Z", "WIRE"),
            headers=operator_headers(ctx.b2_id),
        ),
        expected_status=201,
    )
    assert_waterfall_allocation(
        overflowing, interest=0, penalty=0, principal=240000, credit=500000
    )

    refund_due = _statement(api, ctx.st2_id)
    assert_fields(
        refund_due,
        principal_paid_cents=340000,
        credit_balance_cents=500000,
        interest_paid_cents=0,
        penalty_paid_cents=0,
        total_due_cents=0,
        payment_status="REFUND_DUE",
    )
    assert_fields(
        validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=840000
    )


# --------------------------------------------------------------------------
# The grace deadline, on the day and one day after
# --------------------------------------------------------------------------
def test_the_sweep_is_refused_on_the_grace_deadline_and_charges_one_day_after_it(api):
    """A clock landing exactly on 2026-11-25 cannot sweep at all, and the identical
    call one day later charges interest for exactly one day.

    PRD 3.5: "the logical clock must be strictly past the grace deadline, which is
    the period's due_date advanced by grace_days whole days: a clock landing
    exactly on the grace deadline is not yet delinquent and the sweep is refused at
    the state rung with ERR_INVALID_STATE_TRANSITION."

    PRD 3.5: "The number of days late is the count of whole days from the grace
    deadline to the logical clock, and it is at least 1 whenever the statement is
    swept at all, since the clock is strictly past the deadline."

    Design: Corner/calculations/sweep_at_exactly_the_grace_deadline_is_refused_and_one_day_later_charges_one_day
    """
    ctx = _only_the_first_statement_filed(api)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    closed = fx.close_period(api, ctx)
    assert_fields(closed, status="CLOSED", grace_days=10)
    assert_instant_equals(closed["due_date"], "2026-11-15T00:00:00Z", "due_date")

    fx.set_clock(api, "2026-11-25T00:00:00Z")
    validate_error(
        api.sweep_delinquency(ctx.ap_id, headers=ADMIN),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )

    assert_fields(
        validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN)), status="CLOSED"
    )
    assert_fields(
        _statement(api, ctx.st1_id),
        payment_status="UNPAID",
        penalty_cents=0,
        interest_cents=0,
        delinquency_stage="NONE",
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), delinquent_charges_cents=0)
    assert_fields(
        validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN)),
        delinquency_strike_count=0,
        compliance_standing="GOOD",
    )

    fx.set_clock(api, "2026-11-26T00:00:00Z")
    swept_period = validate_success(api.sweep_delinquency(ctx.ap_id, headers=ADMIN))
    assert_fields(swept_period, status="DELINQUENCY_SWEPT")

    assert_fields(
        _statement(api, ctx.st1_id),
        interest_cents=412,
        penalty_cents=82450,
        payment_status="DELINQUENT",
        delinquency_stage="NOTICE",
    )
    assert_fields(
        validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN)),
        delinquency_strike_count=1,
        compliance_standing="WATCH",
    )
    assert_fields(
        validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN)),
        status="VALID",
        disqualification_reason="NONE",
    )


# --------------------------------------------------------------------------
# The reallocation step, after an audit revises downwards
# --------------------------------------------------------------------------
def test_an_audit_revising_downwards_migrates_the_excess_principal_into_credit(api):
    """A statement settled at 824500 is audited down to 742050, and the 82450 of
    principal that is now excess moves into credit instead of vanishing, leaving
    the district's collected total untouched.

    PRD 3.4: "The overpaid amount is principal_paid_cents less
    effective_assessment_cents; when that is greater than zero, the excess is added
    to credit_balance_cents and principal_paid_cents is reduced to equal
    effective_assessment_cents. The cents migrate rather than vanish, which is what
    keeps the conserved identity true after a dispute is granted."

    PRD 3.3: "The audit stores the audited figures, records audited_by_user_id from
    the acting X-User-ID, computes the final variant of the assessment into
    final_assessment_cents, sets effective_assessment_cents to that figure".

    Design: Corner/calculations/audited_downward_revision_migrates_the_overpaid_principal_into_credit
    """
    ctx = _only_the_first_statement_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 824500, method="WIRE", key="rem_a")

    settled = _statement(api, ctx.st1_id)
    assert_fields(
        settled,
        payment_status="PAID_IN_FULL",
        principal_paid_cents=824500,
        credit_balance_cents=0,
        total_due_cents=0,
    )

    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)

    audited = validate_success(
        api.audit_certify_statement(
            ctx.st1_id,
            f.audit_payload(
                audited_gross_room_revenue_cents=37102500,
                audit_note="resort fees removed from the revenue basis",
            ),
            headers=AUDITOR,
        )
    )
    assert_fields(
        audited,
        filing_status="AUDITED",
        audited_gross_room_revenue_cents=37102500,
        final_assessment_cents=742050,
        effective_assessment_cents=742050,
        principal_paid_cents=742050,
        credit_balance_cents=82450,
        total_due_cents=0,
        payment_status="REFUND_DUE",
        audited_by_user_id=AUDITOR_USER_ID,
    )
    assert_null_fields(audited, "audited_room_nights")

    assert_fields(
        validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=824500
    )
