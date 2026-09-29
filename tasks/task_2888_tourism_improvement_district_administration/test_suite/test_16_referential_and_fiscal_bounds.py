"""Bounds that guard the petition, the term, a reversal and an abatement.

Each test drives one rule to the cent or to the day: the three-property floor on
the petition pool, the standing an exempt property loses along with its place in
the denominator, the two closed doors of the renewal window, the single reversal a
payment allows, and the ceiling on what a hearing officer may grant.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT,
    ERR_BUSINESS_EXEMPT,
    ERR_PETITION_POOL_TOO_SMALL,
    ERR_REMITTANCE_ALREADY_REVERSED,
    ERR_RENEWAL_WINDOW_NOT_OPEN,
    ERR_TRANSPARENCY_REQUIREMENTS_UNMET,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import (
    ADMIN,
    HEARING_OFFICER,
    HEARING_OFFICER_USER_ID,
    operator_headers,
)


# --------------------------------------------------------------------------
# The three-property floor on the petition pool
# --------------------------------------------------------------------------
def _tidepool_district_of_three_properties(api):
    """A second district of three properties: two core properties worth 50,000,000
    and 30,000,000, and one perimeter property worth 20,000,000."""
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(api, name="Tidepool Commons Tourism Improvement District")
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Tidepool Lodge",
            boundary_zone="ZONE_CORE",
            classification="FULL_SERVICE",
            room_count=150,
            prior_year_gross_room_revenue_cents=50000000,
            operator_contact_email="ops@tidepoollodge.example",
        ),
        "t1_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Anemone Suites",
            boundary_zone="ZONE_CORE",
            classification="LIMITED_SERVICE",
            room_count=90,
            prior_year_gross_room_revenue_cents=30000000,
            operator_contact_email="ops@anemonesuites.example",
        ),
        "t2_id",
    )
    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Kelp Cottages",
            boundary_zone="ZONE_PERIMETER",
            classification="SHORT_TERM_RENTAL",
            room_count=20,
            prior_year_gross_room_revenue_cents=20000000,
            operator_contact_email="ops@kelpcottages.example",
        ),
        "t3_id",
    )
    return ctx


def test_a_tally_at_full_support_is_still_refused_by_a_pool_of_two(api):
    """Both signers carry the whole assessable basis, so support stands at 1.0000 on
    both measurements, and the tally is still refused because the third property has
    been exempted out of the pool.  The refusal is not the failing branch: the drive
    stays OPEN and the district stays in circulation.  Adding a third assessable
    property makes the identical tally qualify, on support recomputed against the
    live pool rather than the snapshot the drive opened with.

    PRD 3.2: "Tallying is also refused with ERR_PETITION_POOL_TOO_SMALL when the
    district's eligible assessable pool holds fewer than three businesses."

    PRD 3.2: "The denominator is therefore the assessable set as of the recompute
    instant, not as of drive open."

    Design: Corner/errors/a_qualifying_tally_is_still_refused_while_the_assessable_pool_holds_fewer_than_three_businesses
    """
    ctx = _tidepool_district_of_three_properties(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "t1_id")
    fx.sign(api, ctx, "t2_id")

    exempted = validate_success(
        api.revise_lodging_business(
            ctx.t3_id,
            f.revision_payload(exempt_status="GOVERNMENT_OWNED"),
            headers=ADMIN,
        )
    )
    assert_fields(exempted, status="EXEMPT", exempt_status="GOVERNMENT_OWNED")

    shrunken = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        shrunken,
        status="PETITION_CIRCULATING",
        assessable_business_count=2,
        assessable_basis_cents=80000000,
    )
    at_full_support = validate_success(api.get_petition_drive(ctx.pd_id, headers=ADMIN))
    assert_fields(
        at_full_support,
        status="OPEN",
        valid_signature_count=2,
        signed_basis_cents=80000000,
        assessable_count_snapshot=2,
        assessable_basis_snapshot_cents=80000000,
    )
    assert_ratio_four_dp(at_full_support["weighted_support_pct"], 1.0000, "weighted_support_pct")
    assert_ratio_four_dp(at_full_support["headcount_support_pct"], 1.0000, "headcount_support_pct")
    assert_ratio_four_dp(at_full_support["required_weighted_pct"], 0.6000, "required_weighted_pct")
    assert_ratio_four_dp(at_full_support["required_headcount_pct"], 0.0000, "required_headcount_pct")

    validate_error(
        api.tally_petition_drive(ctx.pd_id, headers=ADMIN),
        ERR_PETITION_POOL_TOO_SMALL,
        expected_status=409,
    )

    unmoved = validate_success(api.get_petition_drive(ctx.pd_id, headers=ADMIN))
    assert_fields(unmoved, status="OPEN", short_reason="NONE")
    assert_null_fields(unmoved, "tallied_at")
    still_circulating = validate_success(api.get_district(ctx.d_id))
    assert_fields(still_circulating, status="PETITION_CIRCULATING")

    fx.add_business(
        api,
        ctx,
        f.lodging_business_payload(
            ctx.d_id,
            legal_name="Barnacle Rooms",
            boundary_zone="ZONE_PERIMETER",
            classification="BOUTIQUE",
            room_count=30,
            prior_year_gross_room_revenue_cents=20000000,
            operator_contact_email="ops@barnaclerooms.example",
        ),
        "t4_id",
    )
    restored = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        restored, assessable_business_count=3, assessable_basis_cents=100000000
    )

    qualified = fx.tally(api, ctx)
    assert_fields(
        qualified,
        status="QUALIFIED",
        short_reason="NONE",
        valid_signature_count=2,
        signed_basis_cents=80000000,
        assessable_count_snapshot=3,
        assessable_basis_snapshot_cents=100000000,
    )
    assert_ratio_four_dp(qualified["weighted_support_pct"], 0.8000, "weighted_support_pct")
    assert_ratio_four_dp(qualified["headcount_support_pct"], 0.6667, "headcount_support_pct")
    assert_instant_equals(qualified["tallied_at"], "2026-08-01T00:00:00Z", "tallied_at")


# --------------------------------------------------------------------------
# Exemption as a bar on signing and a smaller denominator
# --------------------------------------------------------------------------
def test_an_exempted_property_may_not_sign_and_leaves_the_denominator_behind(api):
    """Exempting the perimeter cottages does two things at once: it refuses their own
    signature, and it lifts the unchanged signature of the core hotel from 0.6000 to
    0.6316 by shrinking the basis it is measured against.

    PRD 3.2: "A signer whose exempt_status is anything other than NONE, or whose
    status is EXEMPT, holds no petition standing and is refused with
    ERR_BUSINESS_EXEMPT."

    PRD 3.2: "the assessable set is the district's lodging businesses whose status is
    ASSESSABLE, whose exempt_status is NONE, and whose boundary_zone is a member of
    the district's included_zones".

    Design: Corner/errors/an_exempt_property_holds_no_petition_standing_and_shrinks_the_support_denominator
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")

    before = validate_success(api.get_petition_drive(ctx.pd_id, headers=ADMIN))
    assert_ratio_four_dp(before["weighted_support_pct"], 0.6000, "weighted_support_pct")

    exempted = validate_success(
        api.revise_lodging_business(
            ctx.b4_id,
            f.revision_payload(exempt_status="GOVERNMENT_OWNED"),
            headers=ADMIN,
        )
    )
    assert_fields(
        exempted,
        status="EXEMPT",
        exempt_status="GOVERNMENT_OWNED",
        boundary_zone="ZONE_PERIMETER",
    )

    validate_error(
        api.sign_petition(
            ctx.pd_id,
            f.signature_payload(ctx.b4_id),
            headers=operator_headers(ctx.b4_id),
        ),
        ERR_BUSINESS_EXEMPT,
        expected_status=409,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        district, assessable_business_count=3, assessable_basis_cents=95000000
    )

    signatures, meta = validate_paginated(
        api.list_drive_signatures(ctx.pd_id, headers=ADMIN)
    )
    assert meta["total_count"] == 1, (
        "the refused signature must not have been recorded, got %r" % (meta,)
    )
    assert_fields(signatures[0], status="VALID", disqualification_reason="NONE")

    qualified = fx.tally(api, ctx)
    assert_fields(
        qualified,
        status="QUALIFIED",
        short_reason="NONE",
        valid_signature_count=1,
        signed_basis_cents=60000000,
        assessable_count_snapshot=3,
        assessable_basis_snapshot_cents=95000000,
    )
    assert_ratio_four_dp(qualified["weighted_support_pct"], 0.6316, "weighted_support_pct")
    assert_ratio_four_dp(qualified["headcount_support_pct"], 0.3333, "headcount_support_pct")


# --------------------------------------------------------------------------
# The two closed doors of the renewal window
# --------------------------------------------------------------------------
def test_the_renewal_window_admits_the_hundred_and_eightieth_day_and_nothing_outside_it(api):
    """The term runs one year from 2026-08-01, so the window is the half-open range
    from 2027-02-02 up to 2027-08-01.  One day earlier is 181 whole days out and
    refused, the opening day is accepted, and a day past expiration is refused again.
    The lifecycle attempt in the middle shows the transparency gate reported ahead of
    the window, because it sits higher on the ladder.

    PRD 3.2: "Opening a renewal drive instead requires the district to be inside its
    renewal window: the logical clock must be no more than 180 whole days before the
    district's expiration_date and must not be at or past it. Outside that half-open
    window the request is refused with ERR_RENEWAL_WINDOW_NOT_OPEN."

    PRD 3.2: "For a renewal drive, required_weighted_pct is copied from
    renewal_threshold_pct and required_headcount_pct from
    renewal_headcount_threshold_pct, so that both tests bind."

    Design: Corner/errors/the_renewal_window_opens_exactly_one_hundred_eighty_days_before_expiration_and_shuts_at_it
    """
    ctx = fx.active_district(api)
    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="ACTIVE", term_years=1)
    assert_instant_equals(district["expiration_date"], "2027-08-01T00:00:00Z", "expiration_date")

    fx.set_clock(api, "2027-02-01T00:00:00Z")
    validate_error(
        api.create_petition_drive(
            f.petition_drive_payload(ctx.d_id, "RENEWAL", "2027-07-01T00:00:00Z"),
            headers=ADMIN,
        ),
        ERR_RENEWAL_WINDOW_NOT_OPEN,
        expected_status=409,
    )
    validate_error(
        api.advance_district_lifecycle(
            ctx.d_id,
            f.lifecycle_advance_payload("RENEWAL_PENDING", "2027-02-01T00:00:00Z"),
            headers=ADMIN,
        ),
        ERR_TRANSPARENCY_REQUIREMENTS_UNMET,
        expected_status=409,
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), status="ACTIVE")

    fx.set_clock(api, "2027-02-02T00:00:00Z")
    drive = validate_success(
        api.create_petition_drive(
            f.petition_drive_payload(ctx.d_id, "RENEWAL", "2027-07-01T00:00:00Z"),
            headers=ADMIN,
        ),
        expected_status=201,
    )
    assert_fields(
        drive,
        drive_type="RENEWAL",
        status="OPEN",
        assessable_count_snapshot=4,
        assessable_basis_snapshot_cents=100000000,
        valid_signature_count=0,
        signed_basis_cents=0,
        short_reason="NONE",
    )
    assert_ratio_four_dp(drive["required_weighted_pct"], 0.6500, "required_weighted_pct")
    assert_ratio_four_dp(drive["required_headcount_pct"], 0.7500, "required_headcount_pct")
    assert_instant_equals(drive["opened_on"], "2027-02-02T00:00:00Z", "opened_on")
    assert_fields(validate_success(api.get_district(ctx.d_id)), status="ACTIVE")

    fx.set_clock(api, "2027-08-02T00:00:00Z")
    validate_error(
        api.create_petition_drive(
            f.petition_drive_payload(ctx.d_id, "RENEWAL", "2027-09-01T00:00:00Z"),
            headers=ADMIN,
        ),
        ERR_RENEWAL_WINDOW_NOT_OPEN,
        expected_status=409,
    )

    drives, meta = validate_paginated(
        api.list_district_petition_drives(ctx.d_id, headers=ADMIN)
    )
    assert meta["total_count"] == 2, (
        "only the formation drive and the one accepted renewal drive may exist, got %r"
        % (meta,)
    )
    renewals = [row for row in drives if row["drive_type"] == "RENEWAL"]
    assert [row["id"] for row in renewals] == [drive["id"]], (
        "exactly the accepted renewal drive must be listed, got %r" % (renewals,)
    )


# --------------------------------------------------------------------------
# One reversal per payment, and no silent second
# --------------------------------------------------------------------------
def test_a_payment_may_be_reversed_once_and_the_second_attempt_credits_nothing(api):
    """Three hundred thousand cents are paid against the limited-service statement
    and then reversed, returning every bucket to its pre-payment value.  The second
    reversal of the same record is refused rather than quietly repeated, and the
    money reads identically on both sides of that refusal.

    PRD 3.4: "The named record must belong to the statement named in the path, must
    still be APPLIED, and its statement's filing_status must not be CERTIFIED; a
    second attempt on the same record is refused with
    ERR_REMITTANCE_ALREADY_REVERSED".

    PRD 2.12: "A reversal subtracts exactly the four per-bucket amounts recorded on
    the remittance row rather than re-running the allocation backwards, so the
    identity holds regardless of the order in which payments and reversals arrive."

    Design: Corner/errors/a_remittance_may_be_reversed_once_and_the_second_reversal_is_refused
    """
    ctx = fx.statements_filed(api)
    applied = fx.remit(api, ctx, "st2_id", "b2_id", 300000, key="rem_st2")
    assert_fields(
        applied,
        status="APPLIED",
        amount_cents=300000,
        applied_to_interest_cents=0,
        applied_to_penalty_cents=0,
        applied_to_principal_cents=300000,
        applied_to_credit_cents=0,
    )

    part_paid = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        part_paid, principal_paid_cents=300000, total_due_cents=40000, payment_status="PARTIALLY_PAID"
    )

    reversed_row = fx.reverse(api, ctx, "st2_id", remittance_key="rem_st2")
    assert_fields(reversed_row, status="REVERSED", amount_cents=300000)
    assert_instant_equals(reversed_row["reversed_on"], "2026-08-01T00:00:00Z", "reversed_on")
    version_after_reversal = reversed_row["version"]

    restored = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        restored,
        interest_paid_cents=0,
        penalty_paid_cents=0,
        principal_paid_cents=0,
        credit_balance_cents=0,
        total_due_cents=340000,
        payment_status="UNPAID",
    )
    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, collected_to_date_cents=0)

    validate_error(
        api.reverse_remittance(
            ctx.st2_id,
            f.remittance_reversal_payload(ctx.rem_st2, "second attempt at the same record"),
            headers=ADMIN,
        ),
        ERR_REMITTANCE_ALREADY_REVERSED,
        expected_status=409,
    )

    unmoved = validate_success(api.get_remittance(ctx.rem_st2, headers=ADMIN))
    assert_fields(unmoved, status="REVERSED", version=version_after_reversal)
    unchanged = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        unchanged, principal_paid_cents=0, total_due_cents=340000, payment_status="UNPAID"
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=0)

    rows, meta = validate_paginated(
        api.list_statement_remittances(ctx.st2_id, headers=ADMIN)
    )
    assert meta["total_count"] == 1, (
        "the refused reversal must not have added a row, got %r" % (meta,)
    )
    assert rows[0]["id"] == ctx.rem_st2, (
        "the single row must be the reversed payment, got %r" % (rows[0],)
    )


# --------------------------------------------------------------------------
# What a hearing officer may grant
# --------------------------------------------------------------------------
def test_a_grant_may_equal_the_assessment_but_not_exceed_it_by_a_cent(api):
    """The operator is free to claim 340,001 cents against a 340,000-cent statement,
    and the claim is docketed without complaint.  Only the grant is bounded: one cent
    over the effective assessment is refused, and the exact figure abates the
    statement in full.  Because nothing was ever paid, the retired statement reads
    PAID_IN_FULL rather than REFUND_DUE.

    PRD 3.6: "Three bounds govern the granted figure: it must be at least 1, it must
    not exceed the dispute's own claimed_adjustment_cents, and it must not exceed the
    statement's current effective_assessment_cents — the third bound failing with
    ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT."

    PRD 3.4: "effective_assessment_cents becomes final_assessment_cents when that is
    not null, and otherwise becomes provisional_assessment_cents less
    granted_adjustment_cents, floored at zero."

    Design: Corner/errors/a_granted_adjustment_may_equal_but_not_exceed_the_effective_assessment
    """
    ctx = fx.statements_filed(api)
    docketed_claim = fx.file_dispute(
        api,
        ctx,
        statement_key="st2_id",
        business_key="b2_id",
        key="dsp2_id",
        claimed_adjustment_cents=340001,
        dispute_note="the whole assessment is contested",
    )
    assert_fields(docketed_claim, status="SUBMITTED", claimed_adjustment_cents=340001)
    under_review = fx.open_dispute_review(api, ctx, dispute_key="dsp2_id")
    assert_fields(under_review, status="UNDER_REVIEW")
    version_under_review = under_review["version"]

    validate_error(
        api.resolve_dispute(
            ctx.dsp2_id,
            f.resolution_payload(
                "ADJUSTED",
                granted_adjustment_cents=340001,
                resolution_note="one cent past the assessment",
            ),
            headers=HEARING_OFFICER,
        ),
        ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT,
        expected_status=409,
    )

    still_open = validate_success(api.get_dispute(ctx.dsp2_id, headers=ADMIN))
    assert_fields(still_open, status="UNDER_REVIEW", version=version_under_review)
    assert_null_fields(still_open, "resolved_by_user_id")
    untouched = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        untouched,
        granted_adjustment_cents=0,
        effective_assessment_cents=340000,
        total_due_cents=340000,
        payment_status="UNPAID",
    )

    resolved = fx.resolve_dispute(
        api, ctx, dispute_key="dsp2_id", granted_adjustment_cents=340000
    )
    assert_fields(
        resolved,
        status="RESOLVED_ADJUSTED",
        granted_adjustment_cents=340000,
        resolved_by_user_id=HEARING_OFFICER_USER_ID,
    )

    abated = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(
        abated,
        granted_adjustment_cents=340000,
        effective_assessment_cents=0,
        total_due_cents=0,
        principal_paid_cents=0,
        credit_balance_cents=0,
        payment_status="PAID_IN_FULL",
    )
    _, meta = validate_paginated(api.list_statement_remittances(ctx.st2_id, headers=ADMIN))
    assert meta["total_count"] == 0, (
        "an abatement is not a payment, got %r" % (meta,)
    )
    assert_fields(
        validate_success(api.get_lodging_business(ctx.b2_id, headers=ADMIN)),
        status="ASSESSABLE",
        exempt_status="NONE",
    )
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=0)
