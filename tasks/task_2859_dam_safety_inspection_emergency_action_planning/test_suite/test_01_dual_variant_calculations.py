"""Two-variant calculations: screening vs certified score, preview vs assessment."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ORDER_TYPE_COMPLIANCE,
    assert_cents,
    assert_instant,
    assert_penalty_preview_shape,
    assert_score,
)
from test_helpers import factories as f
from test_helpers.constants import (
    ASSESSMENT_CERTIFIED,
    CATEGORY_SEEPAGE,
    HAZARD_HIGH,
    HAZARD_SIGNIFICANT,
    HAZARD_UNCLASSIFIED,
    ORDER_DEFAULTED,
    SAFETY_POOR,
    SEVERITY_SERIOUS,
)


# ---------------------------------------------------------------------------
# Fast-travel assessment: screening 30.00 / SIGNIFICANT, certified 45.00 / HIGH
# ---------------------------------------------------------------------------
@pytest.fixture()
def fast_travel_assessment(program, base):
    """A DRAFT assessment whose travel-time band diverges the two score variants."""
    return program.create_assessment(f.assessment_a2(base.dam_id), base.engineer_a_id)


def test_screening_variant_forces_the_multiplier_and_drops_the_economic_term(
    program, base, fast_travel_assessment
):
    """The same assessment row carries two different scores and two different classes.

    PRD 3.2: "In the **screening variant**, computed at filing and stored in `screening_score`, the multiplier is forced to 1.0 no matter what the travel time is, and the economic component is forced to 0 because the inundation area has not yet been engineer-verified; every other term is identical."

    Design: Difficulty/dual_variant_calc/screening_vs_certified_consequence_score_diverges_and_reclassifies_dam
    """
    filed = fast_travel_assessment
    # 12 PAR x 2.0 x 1.0 = 24.00 plus 4 structures x 1.5 = 6.00, economic term
    # forced to 0: 30.00 at intake, which maps to SIGNIFICANT.
    assert_score(filed["screening_score"], 30.00, "screening_score")
    assert filed["recommended_hazard_class"] == HAZARD_SIGNIFICANT
    assert filed["certified_score"] is None
    assert filed["certified_hazard_class"] is None

    certified = program.certify_assessment(filed["id"], base.engineer_a_id)
    # 12 PAR x 2.0 x 1.5 = 36.00, 6.00 of structures, floor(300/100) = 3 economic.
    assert_score(certified["certified_score"], 45.00, "certified_score")
    assert certified["certified_hazard_class"] == HAZARD_HIGH
    assert certified["status"] == ASSESSMENT_CERTIFIED
    assert_instant(certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at")
    assert_score(certified["screening_score"], 30.00, "screening_score")
    assert round(certified["certified_score"] - certified["screening_score"], 2) == 15.00


def test_certification_reclassifies_the_dam_onto_the_high_hazard_interval(
    program, base, fast_travel_assessment
):
    """The certified variant, not the screening one, is what reclassifies the dam.

    PRD 3.2: "Because link 1 replaced the classification source, the dam's `hazard_class` is set to the new `certified_hazard_class`, its `current_consequence_score` to the new `certified_score`, its `eap_required` flag is recomputed, and its `next_inspection_due_at` and `inspection_overdue` are recomputed on the new class's interval."

    Design: Difficulty/dual_variant_calc/screening_vs_certified_consequence_score_diverges_and_reclassifies_dam
    """
    before = program.get_dam(base.dam_id)
    assert before["hazard_class"] == HAZARD_UNCLASSIFIED

    program.certify_assessment(fast_travel_assessment["id"], base.engineer_a_id)

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_HIGH
    assert_score(dam["current_consequence_score"], 45.00, "current_consequence_score")
    assert dam["eap_required"] is True
    # No accepted periodic inspection, so the baseline is registered_at 2019-04-15
    # advanced by the HIGH interval of 12 calendar months.
    assert_instant(
        dam["next_inspection_due_at"], "2020-04-15T00:00:00Z", "next_inspection_due_at"
    )
    assert dam["inspection_overdue"] is True
    assert dam["version"] == before["version"] + 1


# ---------------------------------------------------------------------------
# Preview vs final assessment on the same defaulted order
# ---------------------------------------------------------------------------
@pytest.fixture()
def defaulting_order(program, base):
    """A HIGH-hazard COMPLIANCE_ORDER with a filed response, ten days past deadline."""
    program.classify_high(base.dam_id, base.engineer_a_id)
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
        condition_rating=SAFETY_POOR,
        narrative="Downstream slope seepage with active piping at the left abutment.",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_SEEPAGE,
                severity=SEVERITY_SERIOUS,
                description="Concentrated seepage exiting the downstream slope at station 2+40.",
            )
        ],
    )
    program.accept_inspection(inspection["id"], base.engineer_b_headers)
    deficiency = program.deficiencies_for(base.dam_id, severity=SEVERITY_SERIOUS)[0]
    order = program.issue_order(
        deficiency["id"],
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=60,
    )
    program.file_order_response(order["id"], base.owner_id)
    program.set_clock("2026-09-06T13:00:00Z")
    return order


def test_penalty_preview_reports_the_raw_accrual_without_cap_or_abatement(
    api, program, defaulting_order
):
    """The preview is the uncapped, unabated variant of the same accrual.

    PRD 3.4: "The preview applies **no cap and no abatement** and returns exactly `order_id`, `overdue_days`, `daily_penalty_rate_cents`, `provisional_penalty_cents` and `response_filed` (true exactly when `response_filed_at` is non-null)."

    Design: Difficulty/dual_variant_calc/provisional_penalty_preview_exceeds_final_assessed_penalty_after_abatement
    """
    order = program.get_order(defaulting_order["id"])
    # SERIOUS base 45 days x 0.5 for a HIGH-hazard dam = 22.5, floored to 22, which
    # is smaller than the 60 days requested.
    assert order["effective_response_days"] == 22
    assert_instant(
        order["compliance_deadline_at"],
        "2026-08-27T13:00:00Z",
        "compliance_deadline_at",
    )
    assert_cents(order["daily_penalty_rate_cents"], 20000, "daily_penalty_rate_cents")

    preview = validate_success(
        api.get_penalty_preview(defaulting_order["id"], program.admin)
    )
    assert_penalty_preview_shape(preview)
    assert preview["order_id"] == defaulting_order["id"]
    assert preview["overdue_days"] == 10
    # Seven days at factor 1.0 plus three days at 1.15: 140000 + 69000.
    assert_cents(
        preview["provisional_penalty_cents"], 209000, "provisional_penalty_cents"
    )
    assert preview["response_filed"] is True


def test_default_assessment_abates_the_previewed_accrual_by_a_quarter(
    program, base, defaulting_order
):
    """The assessed variant is strictly smaller than the previewed one.

    PRD 3.4: "Then, if `response_filed_at` is non-null, a good-faith abatement of 25 percent of the capped total, rounded half up to whole cents, is subtracted from it."

    Design: Difficulty/dual_variant_calc/provisional_penalty_preview_exceeds_final_assessed_penalty_after_abatement
    """
    program.sweep()

    order = program.get_order(defaulting_order["id"])
    assert order["status"] == ORDER_DEFAULTED
    # 209000 raw accrual, well under the 5,000,000 cap, less 52250 of abatement.
    assert_cents(order["assessed_penalty_cents"], 156750, "assessed_penalty_cents")
    assert order["response_filed_at"] is not None

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 156750, "fee_balance_cents")
