"""The two variants of a measurement, and how they diverge on identical data.

Two measurements in this system are computed twice from the same stored row.  An
assessment has a provisional variant that reads the property's live zone and
classification and a final variant that reads the period-start snapshots, and a
petition drive has a revenue-weighted support variant and a headcount support
variant.  Each pair shares one arithmetic body and separates only on which
inputs feed it.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_ratio_four_dp
from test_helpers.test_users import ADMIN, AUDITOR, AUDITOR_USER_ID


# --------------------------------------------------------------------------
# Chain: a statement filed after its property was reclassified mid period
# --------------------------------------------------------------------------
def _reclassified_then_audited(api):
    """Build one filed-and-audited statement whose property was moved from
    FULL_SERVICE to BOUTIQUE after the period opened.

    The reclassification touches the classification only, so the property keeps
    its ZONE_CORE zone and the period-start snapshot keeps FULL_SERVICE.
    """
    ctx = fx.active_district(api)
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)
    validate_success(
        api.revise_lodging_business(
            ctx.b1_id, f.revision_payload(classification="BOUTIQUE"), headers=ADMIN
        )
    )
    fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    fx.audit_statement(
        api,
        ctx,
        "st1_id",
        audited_room_nights=2000,
        audited_gross_room_revenue_cents=41225000,
        headers=AUDITOR,
    )
    return ctx


def test_provisional_reads_the_live_classification_and_final_reads_the_snapshot(api):
    """A mid-period reclassification makes the two variants return different
    integers from byte-identical reported figures.

    PRD 3.3: "Because a mid-period classification or zone revision moves the live
    values away from the period-start snapshot, the two variants return different
    integers from byte-identical reported data."

    The provisional variant runs at filing against the live BOUTIQUE
    classification, giving 41225000 x 0.0200 x 0.90 = 742050.  The final variant
    runs at audit against the FULL_SERVICE snapshot, giving 41225000 x 0.0200 x
    1.00 = 824500.  Neither figure is touched by the 150-cent-per-night floor of
    300000 or by the 2500000 ceiling.

    Design: Difficulty/dual_variant_calc/assessment_provisional_and_final_diverge_after_mid_period_reclassification
    """
    ctx = _reclassified_then_audited(api)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        provisional_assessment_cents=742050,
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
        total_due_cents=824500,
        filing_status="AUDITED",
    )
    assert statement["final_assessment_cents"] - statement["provisional_assessment_cents"] == 82450


def test_period_start_snapshots_are_not_rewritten_by_a_later_revision(api):
    """The statement's three period-start snapshots keep the values the property
    held when the period opened, while the property itself carries the new one.

    PRD 3.3: "captures three period-start snapshots that are the whole reason the
    two assessment variants can disagree: zone_at_period_start copies the
    property's boundary_zone, classification_at_period_start copies its
    classification, and assessment_method_at_period_start copies the district's
    assessment_method, pinning which formula branch both variants will use."

    Design: Difficulty/dual_variant_calc/assessment_provisional_and_final_diverge_after_mid_period_reclassification
    """
    ctx = _reclassified_then_audited(api)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        zone_at_period_start="ZONE_CORE",
        classification_at_period_start="FULL_SERVICE",
        assessment_method_at_period_start="PCT_OF_ROOM_REVENUE",
    )

    business = validate_success(api.get_lodging_business(ctx.b1_id, headers=ADMIN))
    assert_fields(business, classification="BOUTIQUE", boundary_zone="ZONE_CORE")


def test_both_variants_run_off_the_same_reported_and_audited_figures(api):
    """The divergence is not a data difference: both variants see 2000 nights on
    41225000 cents, and the audit substitutes exactly those same numbers.

    PRD 3.3: "takes audited_gross_room_revenue_cents as the revenue basis when
    that is not null and otherwise reported_gross_room_revenue_cents, takes
    audited_room_nights as the nights basis when that is not null and otherwise
    reported_room_nights, uses granted_adjustment_cents as the adjustment
    basis, and writes its output to final_assessment_cents."

    Design: Difficulty/dual_variant_calc/assessment_provisional_and_final_diverge_after_mid_period_reclassification
    """
    ctx = _reclassified_then_audited(api)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        reported_room_nights=2000,
        reported_gross_room_revenue_cents=41225000,
        audited_room_nights=2000,
        audited_gross_room_revenue_cents=41225000,
        granted_adjustment_cents=0,
        audited_by_user_id=AUDITOR_USER_ID,
    )
    assert statement["provisional_assessment_cents"] != statement["final_assessment_cents"]


# --------------------------------------------------------------------------
# Chain: a renewal drive carried by revenue but sunk by headcount
# --------------------------------------------------------------------------
def _tallied_renewal_drive(api):
    """Open a renewal drive inside the renewal window, sign it with the largest
    and the smallest property, and tally it.

    The district's term is one year from 2026-08-01, so the renewal window runs
    from 2027-02-02 up to 2027-08-01 and the clock is placed at 2027-03-01.
    """
    ctx = fx.active_district(api)
    fx.set_clock(api, "2027-03-01T00:00:00Z")
    fx.open_renewal_drive(api, ctx, "2027-06-01T00:00:00Z")
    fx.sign(api, ctx, "b1_id", drive_key="renewal_pd_id")
    fx.sign(api, ctx, "b4_id", drive_key="renewal_pd_id")
    ctx.renewal_drive = fx.tally(api, ctx, drive_key="renewal_pd_id")
    return ctx


def test_renewal_drive_clears_the_weighted_test_and_fails_the_headcount_test(api):
    """Two of four properties, holding 65 of 100 million cents of assessable
    revenue, satisfy the 0.6500 revenue threshold and miss the 0.7500 headcount
    threshold on exactly the same signature set.

    PRD 3.2: "These are the two variants of one measurement, and they diverge
    sharply on the same data: the revenue-weighted variant lets a single large
    property carry a drive on its own, while the headcount variant is indifferent
    to property size, which is precisely why a renewal drive can pass the revenue
    test and still fail on headcount."

    Design: Difficulty/dual_variant_calc/petition_revenue_weighted_passes_while_headcount_variant_fails_renewal
    """
    ctx = _tallied_renewal_drive(api)

    drive = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(
        drive,
        assessable_basis_snapshot_cents=100000000,
        assessable_count_snapshot=4,
        signed_basis_cents=65000000,
        valid_signature_count=2,
    )
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.6500, "weighted_support_pct")
    assert_ratio_four_dp(drive["headcount_support_pct"], 0.5000, "headcount_support_pct")
    assert_fields(drive, status="SHORT_OF_THRESHOLD", short_reason="HEADCOUNT_BELOW_MINIMUM")


def test_renewal_drive_snapshots_both_thresholds_so_both_tests_bind(api):
    """A renewal drive takes its headcount requirement from the district instead
    of pinning it to zero, which is what lets the headcount test bind at all.

    PRD 3.2: "For a renewal drive, required_weighted_pct is copied from
    renewal_threshold_pct and required_headcount_pct from
    renewal_headcount_threshold_pct, so that both tests bind."

    Design: Difficulty/dual_variant_calc/petition_revenue_weighted_passes_while_headcount_variant_fails_renewal
    """
    ctx = _tallied_renewal_drive(api)

    drive = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(drive, drive_type="RENEWAL")
    assert_ratio_four_dp(drive["required_weighted_pct"], 0.6500, "required_weighted_pct")
    assert_ratio_four_dp(drive["required_headcount_pct"], 0.7500, "required_headcount_pct")
    assert drive["weighted_support_pct"] >= drive["required_weighted_pct"]
    assert drive["headcount_support_pct"] < drive["required_headcount_pct"]


def test_short_of_threshold_renewal_leaves_the_district_exactly_where_it_was(api):
    """The failing branch of a renewal tally moves the drive and nothing else, so
    the district keeps the status it held before the tally.

    PRD 3.2: "a RENEWAL drive leaves the district exactly where it was".

    Design: Difficulty/dual_variant_calc/petition_revenue_weighted_passes_while_headcount_variant_fails_renewal
    """
    ctx = _tallied_renewal_drive(api)

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="ACTIVE")
