"""Endpoint surfaces: the create-read-list shapes and the computed reads.

These tests exercise operations for their own sake rather than for a rule they
enforce: what a creation writes, what a filter narrows, what a fan-out action
touches and leaves alone, and what a derived read reduces a whole district to.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DISTRICT_NOT_ACTIVE
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import ADMIN, ADMIN_USER_ID


def _statement(api, statement_id):
    return validate_success(api.get_assessment_statement(statement_id, headers=ADMIN))


# --------------------------------------------------------------------------
# The transparency create-read-list surface
# --------------------------------------------------------------------------
def test_three_transparency_records_are_read_back_and_filtered_independently(api):
    """Three records of the three declared types are created on one district, read
    back at their declared defaults, and the district collection narrows to one row
    by type and to all three by status.

    PRD 3.9: "The record is created in SCHEDULED with noticed_on, completed_on,
    published_on and document_reference all null, and with engaged_by_user_id taken
    from the acting X-User-ID - the identity that will later be barred from advancing
    a financial audit."

    PRD 2.3: "Filter parameters offered by individual list operations - for example
    status, filing_status, payment_status, boundary_zone, drive_type, record_type,
    dispute_type, channel, fiscal_year and lodging_business_id - narrow the result
    set before pagination is applied, so total_count always reflects the filtered set
    rather than the whole collection."

    Design: Corner/endpoints/transparency_records_are_created_read_back_and_filtered_by_type_and_status
    """
    ctx = fx.active_district(api)
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    for record_type, key in (
        ("PUBLIC_MEETING", "tr_meeting"),
        ("ANNUAL_REPORT", "tr_report"),
        ("FINANCIAL_AUDIT", "tr_audit"),
    ):
        created = fx.schedule_transparency_record(
            api,
            ctx,
            key=key,
            record_type=record_type,
            fiscal_year=2027,
            scheduled_for="2026-09-15T00:00:00Z",
            required_by="2026-10-31T00:00:00Z",
        )
        assert_fields(created, status="SCHEDULED", version=1, record_type=record_type)

    audit = validate_success(api.get_transparency_record(ctx.tr_audit))
    assert_fields(
        audit,
        record_type="FINANCIAL_AUDIT",
        fiscal_year=2027,
        engaged_by_user_id=ADMIN_USER_ID,
    )
    assert_null_fields(
        audit, "noticed_on", "completed_on", "published_on", "document_reference"
    )
    assert_instant_equals(audit["scheduled_for"], "2026-09-15T00:00:00Z", "scheduled_for")
    assert_instant_equals(audit["required_by"], "2026-10-31T00:00:00Z", "required_by")

    meetings, meeting_meta = validate_paginated(
        api.list_district_transparency_records(
            ctx.d_id, headers=ADMIN, params={"record_type": "PUBLIC_MEETING"}
        )
    )
    assert meeting_meta["total_count"] == 1, (
        "the record_type filter must narrow to one row, total_count was %r"
        % meeting_meta["total_count"]
    )
    assert [record["id"] for record in meetings] == [ctx.tr_meeting], (
        "expected only the public meeting, got %r" % ([r["id"] for r in meetings],)
    )

    scheduled, scheduled_meta = validate_paginated(
        api.list_district_transparency_records(
            ctx.d_id, headers=ADMIN, params={"status": "SCHEDULED"}
        )
    )
    assert scheduled_meta["total_count"] == 3, (
        "all three records are SCHEDULED, total_count was %r"
        % scheduled_meta["total_count"]
    )
    assert len(scheduled) == 3, "expected three rows, got %d" % len(scheduled)

    assert_fields(
        validate_success(api.get_district(ctx.d_id)), transparency_standing="COMPLIANT"
    )


# --------------------------------------------------------------------------
# The one action that can kill a district
# --------------------------------------------------------------------------
def test_a_short_formation_tally_fails_the_district_and_closes_every_later_door(api):
    """With only the smallest property signed the drive scores 0.0500, lands short on
    the weighted test, and takes the district itself to a terminal state from which
    even a well-formed assessment period is refused.

    PRD 3.2: "On the failing branch the drive moves OPEN to SHORT_OF_THRESHOLD, which
    is terminal, and short_reason records which test failed: the revenue-weighted test
    is evaluated first, so short_reason is WEIGHTED_BELOW_THRESHOLD whenever
    weighted_support_pct is below required_weighted_pct."

    PRD 3.1: "A district that is FORMATION_FAILED, EXPIRED or DISESTABLISHED rejects
    the creation of assessment periods, annual work plans, marketing programs,
    transparency records and petition drives, in all five cases with
    ERR_DISTRICT_NOT_ACTIVE."

    Design: Corner/endpoints/a_short_formation_tally_fails_the_district_and_closes_every_later_door
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b4_id")

    drive = fx.tally(api, ctx)
    assert_fields(
        drive,
        status="SHORT_OF_THRESHOLD",
        short_reason="WEIGHTED_BELOW_THRESHOLD",
        signed_basis_cents=5000000,
        assessable_basis_snapshot_cents=100000000,
        assessable_count_snapshot=4,
    )
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.0500, "weighted_support_pct")
    assert_ratio_four_dp(drive["headcount_support_pct"], 0.2500, "headcount_support_pct")
    assert_ratio_four_dp(drive["required_headcount_pct"], 0.0000, "required_headcount_pct")
    assert_instant_equals(drive["tallied_at"], "2026-08-01T00:00:00Z", "tallied_at")

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="FORMATION_FAILED")
    assert_null_fields(district, "formed_on", "expiration_date")

    validate_error(
        api.create_assessment_period(f.assessment_period_payload(ctx.d_id), headers=ADMIN),
        ERR_DISTRICT_NOT_ACTIVE,
        expected_status=409,
    )


# --------------------------------------------------------------------------
# One fan-out action, and what it leaves alone
# --------------------------------------------------------------------------
def _swept_period_with_one_statement_already_settled(api):
    """A swept period of four statements in which only the second still owes money:
    the first was paid in full before the sweep and the last two were never filed."""
    ctx = fx.statements_filed(api)
    fx.remit(api, ctx, "st1_id", "b1_id", 824500, method="WIRE", key="rem_a")
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.set_clock(api, "2026-11-26T00:00:00Z")
    fx.sweep_period(api, ctx)
    return ctx


def test_the_sweep_charges_only_the_statement_that_still_owes_money(api):
    """One empty-bodied call fans out across four statements and changes exactly one:
    the settled statement, and the two that were never filed, are all passed over.

    PRD 3.5: "The sweep considers only the statements of that period whose
    payment_status is UNPAID or PARTIALLY_PAID and whose total_due_cents is greater
    than zero. Statements that are PAID_IN_FULL, that are REFUND_DUE, or that already
    stand DELINQUENT are skipped and receive no second set of charges."

    PRD 3.5: "The delinquency stamp on the statement increments the owning property's
    delinquency_strike_count by one and re-derives its compliance_standing from the new
    count: zero strikes is GOOD, exactly one strike is WATCH, and two or more strikes
    is SUSPENDED."

    Design: Corner/endpoints/the_delinquency_sweep_touches_only_the_statements_that_still_owe_money
    """
    ctx = _swept_period_with_one_statement_already_settled(api)

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(
        period,
        status="DELINQUENCY_SWEPT",
        billed_total_cents=1164500,
        collected_total_cents=824500,
    )

    charged = _statement(api, ctx.st2_id)
    assert_fields(
        charged,
        payment_status="DELINQUENT",
        delinquency_stage="NOTICE",
        penalty_cents=34000,
        interest_cents=170,
        total_due_cents=374170,
    )

    settled = _statement(api, ctx.st1_id)
    assert_fields(
        settled,
        payment_status="PAID_IN_FULL",
        penalty_cents=0,
        interest_cents=0,
        delinquency_stage="NONE",
    )

    for key in ("st3_id", "st4_id"):
        untouched = _statement(api, ctx[key])
        assert_fields(
            untouched,
            payment_status="UNPAID",
            penalty_cents=0,
            interest_cents=0,
            delinquency_stage="NONE",
            total_due_cents=0,
        )

    assert_fields(
        validate_success(api.get_district(ctx.d_id)), delinquent_charges_cents=34170
    )
    assert_fields(
        validate_success(api.get_lodging_business(ctx.b2_id, headers=ADMIN)),
        delinquency_strike_count=1,
        compliance_standing="WATCH",
    )
    assert_fields(
        validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN)),
        delinquency_strike_count=0,
        compliance_standing="GOOD",
    )
    assert_fields(
        validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN)),
        status="VALID",
    )


# --------------------------------------------------------------------------
# The derived read that stores nothing
# --------------------------------------------------------------------------
def test_the_financial_summary_derives_every_figure_from_the_statements(api):
    """One read reduces four statements, one payment and one sweep to the ten
    published figures, and the outstanding total is the sum of what the statements
    owe rather than billed less collected.

    PRD 3.1: "For transparency purposes the district also publishes a computed
    financial summary, derived on read from the statements themselves and never
    stored. Narrowed optionally by fiscal_year, it reports district_id, fiscal_year,
    billed_total_cents, collected_to_date_cents, delinquent_charges_cents,
    outstanding_total_cents, credit_total_cents, statement_count,
    delinquent_statement_count and lodging_tax_match_committed_cents."

    PRD 3.4: "total_due_cents becomes the sum of effective_assessment_cents,
    penalty_cents and interest_cents, less the sum of principal_paid_cents,
    penalty_paid_cents and interest_paid_cents, floored at zero."

    Design: Corner/endpoints/the_financial_summary_derives_every_figure_and_stores_none_of_them
    """
    ctx = _swept_period_with_one_statement_already_settled(api)

    summary = validate_success(
        api.get_district_financial_summary(ctx.d_id, params={"fiscal_year": 2027})
    )
    assert_fields(
        summary,
        district_id=ctx.d_id,
        fiscal_year=2027,
        billed_total_cents=1164500,
        collected_to_date_cents=824500,
        delinquent_charges_cents=34170,
        outstanding_total_cents=374170,
        credit_total_cents=0,
        statement_count=4,
        delinquent_statement_count=1,
        lodging_tax_match_committed_cents=0,
    )

    difference = summary["billed_total_cents"] - summary["collected_to_date_cents"]
    assert difference == 340000, (
        "billed less collected should be the unpaid principal 340000, got %r" % difference
    )
    assert summary["outstanding_total_cents"] != difference, (
        "outstanding_total_cents must sum the statements' total_due_cents, which "
        "carries the 34170 of sweep charges that billed less collected does not"
    )
