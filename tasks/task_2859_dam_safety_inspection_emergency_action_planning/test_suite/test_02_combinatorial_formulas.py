"""Formulas whose intermediate roundings and once-only conditionals are contractual."""

import pytest

from test_helpers import (
    assert_cents,
    assert_instant,
    assert_score,
)
from test_helpers import factories as f
from test_helpers.constants import (
    CATEGORY_EROSION,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    ENTRY_CIVIL_PENALTY,
    ENTRY_PERMIT_REVIEW_FEE,
    HAZARD_SIGNIFICANT,
    ORDER_DEFAULTED,
    ORDER_TYPE_COMPLIANCE,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_CONSTRUCTION,
    SAFETY_CONDITIONALLY_SATISFACTORY,
    SEVERITY_MODERATE,
    DEFICIENCY_ESCALATED,
)


# ---------------------------------------------------------------------------
# Per-day rounding of the civil penalty ladder
# ---------------------------------------------------------------------------
@pytest.fixture()
def moderate_order(program, base):
    """A SIGNIFICANT-hazard COMPLIANCE_ORDER left unanswered ten days past deadline."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T09:30:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        narrative="Upstream slope riprap displaced over a 40-foot run.",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_EROSION,
                severity=SEVERITY_MODERATE,
                description="Riprap loss on the upstream face between stations 1+10 and 1+50.",
            )
        ],
    )
    program.accept_inspection(inspection["id"], base.engineer_b_headers)
    deficiency = program.deficiencies_for(base.dam_id, severity=SEVERITY_MODERATE)[0]
    order = program.issue_order(
        deficiency["id"],
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=67,
    )
    program.set_clock("2026-10-21T13:00:00Z")
    return {"order": order, "deficiency": deficiency}


def test_response_allowance_floors_before_it_clamps_and_pins_the_daily_rate(
    program, base, moderate_order
):
    """Severity and hazard class fix both the deadline and the rate at issue time.

    PRD 3.4: "That base is multiplied by the hazard compression factor — 0.5 for a `HIGH`-hazard dam, 0.75 for `SIGNIFICANT`, and 1.0 for both `LOW` and `UNCLASSIFIED` — and the product is rounded **down** to a whole number of days."

    Design: Difficulty/combinatorial_formula/civil_penalty_per_day_rounding_diverges_from_sum_then_round
    """
    order = program.get_order(moderate_order["order"]["id"])
    # MODERATE base 90 days x 0.75 = 67.5, floored to 67, and 67 is exactly what
    # staff requested, so the intersection changes nothing.
    assert order["effective_response_days"] == 67
    assert_instant(
        order["compliance_deadline_at"],
        "2026-10-11T13:00:00Z",
        "compliance_deadline_at",
    )
    # MODERATE daily base 5000 cents x the SIGNIFICANT factor of 1.25.
    assert_cents(order["daily_penalty_rate_cents"], 6250, "daily_penalty_rate_cents")

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_SIGNIFICANT
    assert_score(dam["current_consequence_score"], 6.60, "current_consequence_score")


def test_penalty_rounds_each_overdue_day_separately_rather_than_the_final_sum(
    program, base, moderate_order
):
    """Rounding once per day is a different number from rounding the summed accrual.

    PRD 3.4: "Rounding once per day is part of the contract: summing unrounded day amounts and rounding at the end produces a different figure."

    Design: Difficulty/combinatorial_formula/civil_penalty_per_day_rounding_diverges_from_sum_then_round
    """
    result = program.sweep()
    assert result["defaulted_order_count"] == 1
    assert_cents(result["penalty_cents_assessed"], 65314, "penalty_cents_assessed")

    order = program.get_order(moderate_order["order"]["id"])
    assert order["status"] == ORDER_DEFAULTED
    assert_instant(order["defaulted_at"], "2026-10-21T13:00:00Z", "defaulted_at")
    # Seven days at 6250 plus three days of 6250 x 1.15 = 7187.5 rounded half up to
    # 7188 each: 43750 + 21564. Rounding the unrounded sum would give 65313.
    assert_cents(order["assessed_penalty_cents"], 65314, "assessed_penalty_cents")
    assert order["assessed_penalty_cents"] != 65313

    deficiencies = program.deficiencies_for(base.dam_id)
    assert [d["status"] for d in deficiencies] == [DEFICIENCY_ESCALATED]

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 65314, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT


def test_accepted_periodic_visit_rebases_the_schedule_on_the_new_interval(
    program, base, moderate_order
):
    """The accepted periodic visit, not the registration date, becomes the baseline.

    PRD 3.3: "`next_inspection_due_at` is that baseline advanced by the hazard class's interval in whole calendar months — 12 months at `HIGH`, 24 at `SIGNIFICANT`, 60 at `LOW` and 60 while `UNCLASSIFIED` — preserving the day of month."

    Design: Difficulty/combinatorial_formula/civil_penalty_per_day_rounding_diverges_from_sum_then_round
    """
    dam = program.get_dam(base.dam_id)
    assert_instant(
        dam["next_inspection_due_at"], "2028-08-05T09:30:00Z", "next_inspection_due_at"
    )
    assert dam["inspection_overdue"] is False
    assert dam["safety_status"] == SAFETY_CONDITIONALLY_SATISFACTORY


# ---------------------------------------------------------------------------
# Volume credit decided once on the pre-credit total
# ---------------------------------------------------------------------------
@pytest.fixture()
def delinquent_high_hazard_owner(program, base):
    """A HIGH-hazard dam whose owner is already delinquent when they apply."""
    program.classify_high(base.dam_id, base.engineer_a_id)
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=30000,
        memo="Carried-over penalty from a prior program year.",
    )
    return base


def test_permit_fee_components_are_built_in_the_declared_order(
    program, delinquent_high_hazard_owner
):
    """Base tier, review percentage with hazard uplift, then the delinquency surcharge.

    PRD 3.6: "**Third**, if the owner's `delinquency_status` is `DELINQUENT` at the moment of application, a surcharge of 15 percent of that subtotal, rounded half up to whole cents, is charged as `delinquency_surcharge_cents`; a current owner is charged 0."

    Design: Difficulty/combinatorial_formula/permit_volume_credit_decided_once_on_pre_credit_total
    """
    base = delinquent_high_hazard_owner
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="Raise the spillway crest and add a labyrinth weir.",
        estimated_project_cost_cents=40_000_000,
    )
    # 40,000,000 sits in the second tier.
    assert_cents(permit["base_fee_cents"], 100000, "base_fee_cents")
    # 40,000,000 x 0.75 percent x the HIGH uplift of 1.25, under the 750000 cap.
    assert_cents(
        permit["engineering_review_fee_cents"], 375000, "engineering_review_fee_cents"
    )
    # 15 percent of the 475000 subtotal.
    assert_cents(
        permit["delinquency_surcharge_cents"], 71250, "delinquency_surcharge_cents"
    )
    assert permit["status"] == PERMIT_SUBMITTED
    assert permit["revision_count"] == 0


def test_volume_credit_is_decided_once_and_never_withdrawn(
    program, delinquent_high_hazard_owner
):
    """The credit is tested against the pre-credit total, not against the net total.

    PRD 3.6: "The credit is never re-evaluated after being applied, so a permit whose total lands below the 500,000-cent credit threshold once the credit is deducted keeps the credit anyway."

    Design: Difficulty/combinatorial_formula/permit_volume_credit_decided_once_on_pre_credit_total
    """
    base = delinquent_high_hazard_owner
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="Raise the spillway crest and add a labyrinth weir.",
        estimated_project_cost_cents=40_000_000,
    )
    # Pre-credit total 546250 is at or above 500000, so the credit is 10 percent
    # of it, and the resulting 491625 total keeps that credit.
    assert_cents(permit["volume_credit_cents"], 54625, "volume_credit_cents")
    assert_cents(permit["total_fee_cents"], 491625, "total_fee_cents")
    assert permit["total_fee_cents"] < 500_000
    assert permit["total_fee_cents"] != 546250


def test_the_whole_total_is_posted_as_a_single_permit_review_fee_charge(
    program, delinquent_high_hazard_owner
):
    """Application posts one ledger charge for the whole computed total.

    PRD 3.6: "The whole `total_fee_cents` is posted to the owner's ledger at application time as a single `PERMIT_REVIEW_FEE` entry, and the owner's balance and delinquency flag are recomputed immediately (§3.8)."

    Design: Difficulty/combinatorial_formula/permit_volume_credit_decided_once_on_pre_credit_total
    """
    base = delinquent_high_hazard_owner
    program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="Raise the spillway crest and add a labyrinth weir.",
        estimated_project_cost_cents=40_000_000,
    )

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 2
    fee_row = rows[1]
    assert fee_row["entry_type"] == ENTRY_PERMIT_REVIEW_FEE
    assert_cents(fee_row["amount_cents"], 491625, "amount_cents")
    assert fee_row["sequence_no"] == 2
    assert_cents(fee_row["balance_after_cents"], 521625, "balance_after_cents")

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 521625, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT
    assert owner["delinquency_status"] != DELINQUENCY_CURRENT
