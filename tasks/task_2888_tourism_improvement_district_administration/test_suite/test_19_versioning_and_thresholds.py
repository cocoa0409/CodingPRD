"""Optimistic concurrency on the two amendment writes, and the lien threshold.

The two amendment endpoints are the only writes in this API that ask the caller
to declare the version it last observed, and both of them go stale silently: a
granted dispute moves a statement's version without changing its state, and a
funding-ratio recompute moves a plan's version without any administrator
writing to it.  Each test here holds a number that was correct when it was read,
watches it be refused, re-reads the row and succeeds with the fresh number.  The
last test pins the enforcement threshold that reads the same money twice.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_STATEMENT_VERSION,
    ERR_STALE_WORK_PLAN_VERSION,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import ADMIN, operator_headers


# --------------------------------------------------------------------------
# A statement version moved by somebody else's decision
# --------------------------------------------------------------------------
def test_a_statement_version_gone_stale_behind_a_granted_dispute_is_refused_then_accepted(api):
    """Nothing the operator can see has changed: the statement is still FILED, still
    inside its filing window and still its own.  Only a hearing officer's granted
    adjustment has moved the version, so the amendment carrying the version the
    filing returned is refused at 412 and the same amendment carrying the re-read
    version is accepted.

    PRD 2.7: "The request must carry expected_statement_version, a non-optional
    field holding the client's last observed version of the target assessment
    statement. If that number does not equal the statement's current stored version,
    the amendment is rejected with ERR_STALE_STATEMENT_VERSION (HTTP 412). A granted
    dispute resolution or a preceding amendment bumps the statement's version
    without producing any state change the operator can see from the outside."

    Design: Corner/cross_cutting_complexity_layers/a_stale_statement_version_is_refused_and_the_current_one_succeeds
    """
    ctx = fx.period_with_statements(api)
    filed = fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    assert_fields(
        filed, filing_status="FILED", provisional_assessment_cents=824500, version=2
    )

    fx.file_dispute(api, ctx)
    fx.open_dispute_review(api, ctx)
    fx.resolve_dispute(api, ctx, granted_adjustment_cents=82450)
    adjusted = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        adjusted,
        filing_status="FILED",
        granted_adjustment_cents=82450,
        effective_assessment_cents=742050,
        version=3,
    )
    assert_null_fields(adjusted, "final_assessment_cents")

    stale = f.statement_amendment_payload(
        filed["version"], 1950, 40000000, "September folio corrections"
    )
    validate_error(
        api.amend_statement(ctx.st1_id, stale, headers=operator_headers(ctx.b1_id)),
        ERR_STALE_STATEMENT_VERSION,
        expected_status=412,
    )
    refused = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        refused,
        filing_status="FILED",
        reported_gross_room_revenue_cents=41225000,
        amendment_count=0,
        version=3,
    )

    current = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert current["version"] == 3, (
        "the re-read version must be the one the resolution left, got %r"
        % (current["version"],)
    )
    amended = validate_success(
        api.amend_statement(
            ctx.st1_id,
            f.statement_amendment_payload(
                current["version"], 1950, 40000000, "September folio corrections"
            ),
            headers=operator_headers(ctx.b1_id),
        )
    )
    assert_fields(
        amended,
        filing_status="AMENDED",
        amendment_count=1,
        version=4,
        provisional_assessment_cents=800000,
        granted_adjustment_cents=82450,
        effective_assessment_cents=717550,
    )

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, billed_total_cents=717550)


# --------------------------------------------------------------------------
# A plan version moved by an automatic transition
# --------------------------------------------------------------------------
_RESIZED_BUDGET = [
    f.expenditure_line("SALES_AND_MARKETING", 600000, "paid search and group sales, trimmed"),
    f.expenditure_line("ADMINISTRATION", 140000, "district staff and audit fees"),
    f.expenditure_line("CONTINGENCY_RESERVE", 90000, "statutory reserve"),
    f.expenditure_line("DESTINATION_EVENTS", 120000, "harbour festival"),
]


def test_a_work_plan_version_gone_stale_behind_the_amendment_pending_flip_is_refused_then_accepted(api):
    """Two downward statement amendments drag the forecast under the funding floor,
    and the plan moves itself to AMENDMENT_PENDING with nobody writing to it.  The
    administrator's rescue amendment, carrying the version the approval returned, is
    refused at 412 and the identical lines carrying the re-read version are accepted,
    which returns the plan to APPROVED at a ratio of 0.9300.

    PRD 2.7: "The request must carry expected_work_plan_version, holding the client's
    last observed version of the target annual work plan. A mismatch against the
    plan's current stored version is rejected with ERR_STALE_WORK_PLAN_VERSION (HTTP
    412). The automatic move into AMENDMENT_PENDING driven by a funding-ratio
    recompute is the usual reason the number moves between the read and the write."

    PRD 3.7: "On success the plan's status becomes APPROVED — which is how an
    AMENDMENT_PENDING plan returns to good standing once its ratio again reaches
    0.9000 — its version increments by one".

    Design: Corner/cross_cutting_complexity_layers/a_stale_work_plan_version_is_refused_and_the_current_one_succeeds
    """
    ctx = fx.statements_filed(api)
    approved = fx.approved_work_plan(api, ctx)
    assert_fields(
        approved,
        status="APPROVED",
        total_budget_cents=1000000,
        assessment_revenue_forecast_cents=1164500,
    )
    assert_ratio_four_dp(approved["funding_ratio"], 1.1645, "funding_ratio")

    validate_success(
        api.amend_statement(
            ctx.st1_id,
            f.statement_amendment_payload(
                ctx.st1_filed["version"], 2000, 31000000, "group block cancelled"
            ),
            headers=operator_headers(ctx.b1_id),
        )
    )
    holding = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(holding, status="APPROVED", assessment_revenue_forecast_cents=960000)
    assert_ratio_four_dp(holding["funding_ratio"], 0.96, "funding_ratio")

    validate_success(
        api.amend_statement(
            ctx.st2_id,
            f.statement_amendment_payload(
                ctx.st2_filed["version"], 600, 15500000, "banquet revenue removed"
            ),
            headers=operator_headers(ctx.b2_id),
        )
    )
    pending = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        pending,
        status="AMENDMENT_PENDING",
        total_budget_cents=1000000,
        assessment_revenue_forecast_cents=883500,
        revision_count=0,
    )
    assert_ratio_four_dp(pending["funding_ratio"], 0.8835, "funding_ratio")
    assert pending["version"] > approved["version"], (
        "the automatic flip must have moved the plan's version past the one the "
        "approval returned, got %r after %r"
        % (pending["version"], approved["version"])
    )

    stale = f.work_plan_amendment_payload(
        approved["version"], _RESIZED_BUDGET, "budget resized to the revised forecast"
    )
    validate_error(
        api.amend_work_plan(ctx.wp_id, stale, headers=ADMIN),
        ERR_STALE_WORK_PLAN_VERSION,
        expected_status=412,
    )
    refused = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        refused,
        status="AMENDMENT_PENDING",
        total_budget_cents=1000000,
        sales_and_marketing_cents=650000,
        revision_count=0,
        version=pending["version"],
    )

    revised = validate_success(
        api.amend_work_plan(
            ctx.wp_id,
            f.work_plan_amendment_payload(
                refused["version"],
                _RESIZED_BUDGET,
                "budget resized to the revised forecast",
            ),
            headers=ADMIN,
        )
    )
    assert_fields(
        revised,
        status="APPROVED",
        total_budget_cents=950000,
        sales_and_marketing_cents=600000,
        administration_cents=140000,
        contingency_reserve_cents=90000,
        destination_events_cents=120000,
        assessment_revenue_forecast_cents=883500,
        revision_count=1,
        version=refused["version"] + 1,
    )
    assert_ratio_four_dp(revised["funding_ratio"], 0.93, "funding_ratio")


# --------------------------------------------------------------------------
# version counts writes, not changes
# --------------------------------------------------------------------------
def test_three_revisions_of_one_property_advance_its_version_on_every_write(api):
    """The clock never moves, so updated_at is identical across all three writes and
    cannot tell them apart; only version does, and it advances on the third revision
    as well, which rewrites room_count to the value it already held.

    PRD 2.5: "version (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every subsequent mutation of that record."

    PRD 3.1: "Revising a property accepts any subset of boundary_zone,
    classification, room_count, prior_year_gross_room_revenue_cents, exempt_status,
    remittance_frequency and operator_contact_email, plus the flag close_out."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_to_the_same_row
    """
    ctx = fx.district_with_roll(api)
    created = validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN))
    assert_fields(created, version=1, status="ASSESSABLE", room_count=200)

    first = validate_success(
        api.revise_lodging_business(
            ctx.b1_id, f.revision_payload(classification="LIMITED_SERVICE"), headers=ADMIN
        )
    )
    assert_fields(first, version=2, classification="LIMITED_SERVICE", status="ASSESSABLE")

    second = validate_success(
        api.revise_lodging_business(
            ctx.b1_id,
            f.revision_payload(prior_year_gross_room_revenue_cents=58000000),
            headers=ADMIN,
        )
    )
    assert_fields(
        second,
        version=3,
        prior_year_gross_room_revenue_cents=58000000,
        status="ASSESSABLE",
    )
    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, assessable_basis_cents=98000000, assessable_business_count=4)

    third = validate_success(
        api.revise_lodging_business(
            ctx.b1_id, f.revision_payload(room_count=200), headers=ADMIN
        )
    )
    assert_fields(third, version=4, room_count=200, status="ASSESSABLE")

    # PRD 2.5 fixes the shape of created_at/updated_at but never states that either
    # is stamped from the logical clock (every field that is -- filed_at, signed_at,
    # opened_on -- says so explicitly in section 3), so the concrete instant they
    # carry is not uniquely derivable and is not asserted here.  The version counter,
    # which section 2.5 does pin down, carries this test.
    for record in (first, second, third):
        assert_common_fields(record)


# --------------------------------------------------------------------------
# The lien threshold, read twice in one sweep
# --------------------------------------------------------------------------
def _lien_ridge_district(api):
    """A core-only district of three properties whose two payers assess exactly
    1,000,000 and exactly 999,999 cents, with the third too small to matter."""
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(
        api, name="Lien Ridge Tourism Improvement District", included_zones=["ZONE_CORE"]
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Ridgeline Grand",
            classification="FULL_SERVICE",
            room_count=100,
            prior_year_gross_room_revenue_cents=50000000,
            operator_contact_email="ops@ridgelinegrand.example",
        ),
        "b1_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Summit House",
            classification="FULL_SERVICE",
            room_count=80,
            prior_year_gross_room_revenue_cents=49999950,
            operator_contact_email="ops@summithouse.example",
        ),
        "b2_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Ridge Cabins",
            classification="LIMITED_SERVICE",
            room_count=10,
            prior_year_gross_room_revenue_cents=100000,
            operator_contact_email="ops@ridgecabins.example",
        ),
        "b3_id",
    )
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.sign(api, ctx, "b2_id")
    fx.tally(api, ctx)
    fx.certify(api, ctx)
    fx.advance_district(api, ctx, "ACTIVE")
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)
    return ctx


def test_one_sweep_refers_the_statement_on_the_threshold_and_only_notices_the_one_below(api):
    """Two statements of one period are swept by one call, one cent apart: 1,000,000
    outstanding is referred for a lien and 999,999 is merely noticed, while both round
    to the same penalty and the same interest, so nothing but the threshold can
    account for the difference in stage.

    PRD 3.5: "delinquency_stage, which begins at NONE, becomes LIEN_REFERRED when
    either the outstanding amount is at least 1000000 cents or the owning property's
    compliance_standing already stood SUSPENDED when the sweep began, before this
    sweep's own strike increment; otherwise it becomes NOTICE."

    PRD 3.5: "penalty_cents becomes the outstanding amount multiplied by a penalty
    rate of 0.10, rounded half up to a whole cent. interest_cents becomes the
    outstanding amount multiplied by a daily interest rate of 0.0005 and then by the
    number of days late, rounded half up to a whole cent."

    Design: Corner/cross_cutting_complexity_layers/the_lien_referral_threshold_binds_at_exactly_one_million_outstanding_cents
    """
    ctx = _lien_ridge_district(api)
    assert_fields(ctx.generation_summary, generated_count=3, skipped_count=0)

    on_threshold = fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 50000000)
    below = fx.file_statement(api, ctx, "st2_id", "b2_id", 1500, 49999950)
    assert_fields(on_threshold, effective_assessment_cents=1000000)
    assert_fields(below, effective_assessment_cents=999999)
    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, billed_total_cents=1999999, statement_count=3)

    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.set_clock(api, "2026-11-26T00:00:00Z")
    swept = fx.sweep_period(api, ctx)
    assert_fields(swept, status="DELINQUENCY_SWEPT")

    referred = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        referred,
        payment_status="DELINQUENT",
        delinquency_stage="LIEN_REFERRED",
        penalty_cents=100000,
        interest_cents=500,
        total_due_cents=1100500,
    )
    noticed = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        noticed,
        payment_status="DELINQUENT",
        delinquency_stage="NOTICE",
        penalty_cents=100000,
        interest_cents=500,
        total_due_cents=1100499,
    )
    unfiled = validate_success(api.get_assessment_statement(ctx.st3_id, headers=ADMIN))
    assert_fields(
        unfiled,
        filing_status="NOT_FILED",
        payment_status="UNPAID",
        delinquency_stage="NONE",
        total_due_cents=0,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, delinquent_charges_cents=201000)
    for key in ("b1_id", "b2_id"):
        business = validate_success(api.get_lodging_business(ctx[key], headers=ADMIN))
        assert_fields(business, delinquency_strike_count=1, compliance_standing="WATCH")

    signatures, meta = validate_paginated(
        api.list_drive_signatures(ctx.pd_id, headers=ADMIN)
    )
    assert meta["total_count"] == 2, (
        "the two signatures must survive a sweep that suspends nobody, got %r" % (meta,)
    )
    assert [row["status"] for row in signatures] == ["VALID", "VALID"], (
        "no signature may be disqualified while both signers stand at WATCH, got %r"
        % (signatures,)
    )
