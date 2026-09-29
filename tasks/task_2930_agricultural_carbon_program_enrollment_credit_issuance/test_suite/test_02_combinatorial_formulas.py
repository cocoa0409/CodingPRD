"""Multi-term formulas whose terms cannot be collapsed.

The additionality score, the per-acre waterfall and the issuance split each
combine several independently derived terms in a pinned order, and dropping or
reordering any one term still yields a plausible-looking number.
"""

from test_helpers.assertions import (
    assert_acres,
    assert_cents,
    assert_credits,
    assert_pct,
    assert_tonnes,
)
from test_helpers.constants import (
    ENROLLMENT_SCREENING,
    EVIDENCE_FARM_RECORD,
    METHOD_MODEL,
    PAYMENT_ACCRUED,
    PAYMENT_MODEL_PER_ACRE,
    PRACTICE_REDUCED_TILLAGE,
    RISK_TIER_MEDIUM,
)

WIDE_FIELD = {
    "field_name": "Wide Section",
    "boundary_max_x": 4001,
    "gross_acres": 2010.00,
    "county_code": "NE-055",
}
EDGE_FIELD = {
    "field_name": "Edge Tract",
    "boundary_max_x": 7100,
    "gross_acres": 3560.00,
    "county_code": "KS-045",
}


def test_additionality_score_combines_all_four_terms(scenario):
    """Weighted prior adoption, the telemetry exemption, the documented-year bonus and
    the post-rounding clamp combine to 92.00 on the reference evidence base.

    PRD §3.3: "The score is then assembled from a base of 100: subtract one and a half
    points for each percentage point of `prior_adoption_pct`; subtract a flat 20 points
    when a telemetry gap exists and nothing when it does not; and add two points for
    each documented year, counting at most as many documented years as the lookback
    length."

    Design: Difficulty/combinatorial_formula/additionality_score_four_term_combination
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.create_enrollment()

    enrollment = scenario.submit_enrollment()

    assert_pct(enrollment["prior_adoption_pct"], 12.00)
    assert enrollment["documented_years"] == 5
    assert_pct(enrollment["additionality_score"], 92.00)
    assert enrollment["status"] == ENROLLMENT_SCREENING
    # 87.50 would mean the remote-sensing acres were weighted 1.0 instead of 0.8;
    # 72.00 that the telemetry-gap penalty fired despite the 2024 telemetry row;
    # 90.00 that the documented-year bonus was capped at min_documented_years.
    assert enrollment["additionality_score"] not in (87.50, 72.00, 90.00)


def test_additionality_ignores_records_outside_the_window_and_other_practices(scenario):
    """A large adopted record filed for a different practice in a crop year outside the
    inclusive lookback window enters neither the weighted term nor the depth term.

    PRD §3.3: "The input set is every historical practice record whose `field_id` is the
    enrolled field, whose `practice_code` equals the enrollment's `practice_code`, and
    whose `crop_year` falls inside that window."

    Design: Difficulty/combinatorial_formula/additionality_score_four_term_combination
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.file_history(
        2020, practice_code=PRACTICE_REDUCED_TILLAGE, adopted=True,
        evidence_source=EVIDENCE_FARM_RECORD, acres=900.00,
        observed_emissions_per_acre=0.2000,
    )
    scenario.create_enrollment()

    enrollment = scenario.submit_enrollment()

    assert_pct(enrollment["prior_adoption_pct"], 12.00)
    assert enrollment["documented_years"] == 5
    assert_pct(enrollment["additionality_score"], 92.00)


def test_per_acre_payment_rounds_each_band_line_before_summing(scenario):
    """2000.50 acres at 1234.50 cents per acre yields 617250 + 1712869 + 525, a total
    one cent above the figure obtained by rounding a single raw sum.

    PRD §3.9: "**The rounding order is pinned:** round each of the three band lines to
    whole cents, half up, *first*, and *then* add the three rounded lines together to
    get `gross_amount_cents`."

    Design: Difficulty/combinatorial_formula/per_acre_payment_three_band_pinned_rounding
    """
    scenario.active_enrollment(
        field_overrides=WIDE_FIELD,
        enrollment_overrides={"enrolled_acres": 2000.50, "per_acre_rate_cents": 1234.50},
        per_acre=True,
        history_adopted_acres=(400.10, 1000.25),
    )

    payment = scenario.accrue_payment(2026)

    assert payment["payment_model"] == PAYMENT_MODEL_PER_ACRE
    assert_acres(payment["payable_acres"], 2000.50)
    assert payment["credit_batch_id"] is None
    assert_cents(payment["gross_amount_cents"], 2330644)
    # 2330643 is the figure produced by summing the raw band products and rounding once.
    assert payment["gross_amount_cents"] != 2330643


def test_per_acre_payment_applies_the_tenure_holdback_after_the_waterfall(scenario):
    """With five years of the commitment still to run the holdback is 20.00 per cent, and
    the net figure is an exact integer subtraction that the enrollment then accrues.

    PRD §3.9: "`holdback_cents` is `gross_amount_cents` multiplied by `holdback_pct`,
    divided by 100, rounded half up to whole cents, and `net_amount_cents` is
    `gross_amount_cents` minus `holdback_cents` — an exact integer subtraction."

    Design: Difficulty/combinatorial_formula/per_acre_payment_three_band_pinned_rounding
    """
    scenario.active_enrollment(
        field_overrides=WIDE_FIELD,
        enrollment_overrides={"enrolled_acres": 2000.50, "per_acre_rate_cents": 1234.50},
        per_acre=True,
        history_adopted_acres=(400.10, 1000.25),
    )

    payment = scenario.accrue_payment(2026)

    assert_pct(payment["holdback_pct"], 20.00)
    assert_cents(payment["holdback_cents"], 466129)
    assert_cents(payment["net_amount_cents"], 1864515)
    assert payment["status"] == PAYMENT_ACCRUED
    assert_cents(scenario.reload_enrollment()["accrued_payment_cents"], 1864515)


def test_issuance_tiers_on_gross_credits_before_the_batch_is_booked(scenario):
    """A gross of 1005 credits sits just above the medium-tier floor while the 864 credits
    actually issued sit below it, so the tier must be read from the gross figure.

    PRD §3.7: "The tier basis is the grower's `lifetime_credits_issued` **as it stands
    before this issuance** plus `gross_credits`. It uses `gross_credits`, not
    `issued_credits`."

    Design: Difficulty/combinatorial_formula/issuance_split_pinned_evaluation_order
    """
    scenario.verified_run(
        run_method=METHOD_MODEL,
        field_overrides=EDGE_FIELD,
        enrollment_overrides={"enrolled_acres": 3550.00},
        history_adopted_acres=(710.00, 1775.00),
        packet_overrides={"reported_acres": 3550.00},
        verification_overrides={"sample_pct": 20.00},
    )
    assert_tonnes(scenario.run["net_removals_t"], 1005.928)

    batch = scenario.issue()

    assert_credits(batch["gross_credits"], 1005)
    assert batch["risk_tier"] == RISK_TIER_MEDIUM
    assert_pct(batch["buffer_pct"], 14.00)
    assert_credits(batch["buffer_credits"], 141)
    assert_credits(batch["issued_credits"], 864)
    assert batch["gross_credits"] == batch["buffer_credits"] + batch["issued_credits"]
    # 181 and 824 are the figures produced by re-deriving the tier from issued_credits.
    assert (batch["buffer_credits"], batch["issued_credits"]) != (181, 824)


def test_issuance_assigns_serials_and_advances_every_ledger(scenario):
    """The serial range opens at the pool's cursor and closes on the issued count, and the
    pool, the grower and the enrollment all move by the split figures.

    PRD §3.7: "`serial_start` is the buffer pool's current `next_serial_number`, and
    `serial_end` is `serial_start` plus `issued_credits` minus one, both inclusive."

    Design: Difficulty/combinatorial_formula/issuance_split_pinned_evaluation_order
    """
    scenario.verified_run(
        run_method=METHOD_MODEL,
        field_overrides=EDGE_FIELD,
        enrollment_overrides={"enrolled_acres": 3550.00},
        history_adopted_acres=(710.00, 1775.00),
        packet_overrides={"reported_acres": 3550.00},
        verification_overrides={"sample_pct": 20.00},
    )

    batch = scenario.issue()

    assert batch["serial_start"] == 1
    assert batch["serial_end"] == 864
    pool = scenario.buffer_pool()
    assert_credits(pool["balance_credits"], 141)
    assert_credits(pool["contributed_total"], 141)
    assert pool["next_serial_number"] == 865
    assert_credits(pool["outstanding_issued_credits"], 864)
    assert_credits(scenario.reload_grower()["lifetime_credits_issued"], 864)
    assert_credits(scenario.reload_enrollment()["credits_issued_total"], 864)
