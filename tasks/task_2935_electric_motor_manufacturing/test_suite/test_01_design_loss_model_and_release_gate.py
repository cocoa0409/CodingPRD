"""Motor design arithmetic, the two class verdicts and the release gate."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import ERR_DESIGN_CLASS_SHORTFALL, ERR_ROUND_LIMIT_EXCEEDED


def test_design_loss_budget_combines_four_lookup_tables_before_summing(api):
    """Four lookup tables and two reference ratios build one loss budget.

    PRD 3.2: "`total_predicted_loss_w` is then the sum of those five *already
    rounded* components, in that order. The rounding happens before the
    summation, never after; adding the raw products and rounding the total once
    produces a different, wrong figure."

    Design: Difficulty/combinatorial_formula/design_loss_budget_five_factor_component_rounding
    """
    payload = F.motor_design_payload()

    design = validate_success(api.create_motor_design(payload, U.DESIGN_ENGINEER), 201)

    assert design["total_predicted_loss_w"] == 479.7
    assert design["predicted_efficiency_pct"] == 93.99
    assert design["guaranteed_efficiency_pct"] == 93.09
    assert design["design_estimate_class"] == "IE4"
    assert design["predicted_class"] == "IE3"
    A.assert_design_loss_model(design, payload)
    assert design["status"] == "DRAFT"
    assert design["revision_index"] == 0
    assert design["review_round"] == 0
    assert design["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    A.assert_common_fields(design, expected_version=1)


def test_grade_stack_copper_and_rotor_route_all_move_the_loss_budget(api):
    """No single input decides the budget: four changes move 479.7 W to 388.8 W.

    PRD 3.2: "Nothing about the loss total is determined by a single factor:
    pole count, lamination grade, winding layout, rotor route, stack length and
    copper mass all move it, which is why the class verdict must always be read
    from the computed figures rather than assumed from the material choices."

    Design: Difficulty/combinatorial_formula/design_loss_budget_five_factor_component_rounding
    """
    baseline_payload = F.motor_design_payload()
    premium_payload = F.premium_motor_design_payload()

    baseline = validate_success(
        api.create_motor_design(baseline_payload, U.DESIGN_ENGINEER), 201
    )
    premium = validate_success(
        api.create_motor_design(premium_payload, U.DESIGN_ENGINEER), 201
    )

    assert baseline["total_predicted_loss_w"] == 479.7
    assert premium["total_predicted_loss_w"] == 388.8
    assert premium["predicted_efficiency_pct"] == 95.07
    assert premium["guaranteed_efficiency_pct"] == 94.33
    assert premium["design_estimate_class"] == "IE5"
    assert premium["predicted_class"] == "IE4"
    A.assert_design_loss_model(premium, premium_payload)
    assert premium["status"] == "DRAFT"
    assert premium["revision_index"] == 0
    assert premium["review_round"] == 0
    assert premium["created_by_user_id"] == U.USER_DESIGN_ENGINEER


def test_release_gate_reads_the_guaranteed_verdict_not_the_estimate(api, plant):
    """93.99 estimates IE4, 93.09 only guarantees IE3, and IE3 is the gate.

    PRD 3.2: "Because the derate shifts the classified figure downward,
    identical inputs can land the estimate verdict a full class above the
    guaranteed verdict — a design that estimates `IE4` may only guarantee `IE3`
    — and it is the **guaranteed** verdict, `predicted_class`, that gates
    release."

    Design: Difficulty/dual_variant_calc/design_estimate_vs_guaranteed_class_divergence_on_release_gate
    """
    payload = F.motor_design_payload(target_efficiency_class="IE3")
    plant.add_design(payload)
    plant.submit_design()

    released = plant.decide_design("APPROVE")

    assert released["total_predicted_loss_w"] == 479.7
    assert released["predicted_efficiency_pct"] == 93.99
    assert released["guaranteed_efficiency_pct"] == 93.09
    assert released["design_estimate_class"] == "IE4"
    assert released["predicted_class"] == "IE3"
    assert released["status"] == "RELEASED"
    assert released["released_at"] == F.CLOCK_START
    assert released["released_by_user_id"] == U.USER_DESIGN_REVIEWER


def test_target_class_above_the_guaranteed_verdict_is_refused_on_approve(api, plant):
    """A twin design targeting IE4 is refused although its estimate reads IE4.

    PRD 3.3: "A design whose guaranteed class ranks below its declared target is
    refused with `ERR_DESIGN_CLASS_SHORTFALL` (HTTP 422) — the estimate verdict
    is irrelevant to this gate."

    Design: Difficulty/dual_variant_calc/design_estimate_vs_guaranteed_class_divergence_on_release_gate
    """
    plant.add_design(F.motor_design_payload(target_efficiency_class="IE3"))
    plant.submit_design()
    twin = plant.add_design(
        F.motor_design_payload(
            model_code="WM-132M-7K5-IE4T", target_efficiency_class="IE4"
        )
    )
    plant.submit_design(twin)
    assert twin["design_estimate_class"] == "IE4"
    assert twin["predicted_class"] == "IE3"

    refused = api.record_review_decision(
        twin["id"], F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
    )

    validate_error(refused, ERR_DESIGN_CLASS_SHORTFALL, 422)
    stored = plant.get_design(twin)
    assert stored["status"] == "IN_REVIEW"
    assert stored["released_at"] is None
    assert stored["design_estimate_class"] == "IE4"
    assert stored["predicted_class"] == "IE3"


def test_request_changes_returns_the_design_to_draft_and_counts_both_counters(
    api, plant
):
    """One rejection advances the round counter and the revision index together.

    PRD 3.3: "`REQUEST_CHANGES` moves the design `IN_REVIEW → DRAFT` and, in
    addition to the round counter, increments `revision_index` by 1."

    Design: Difficulty/non_linear_state_machine/design_request_changes_revision_cycle_hits_review_round_limit
    """
    plant.add_design(F.motor_design_payload(target_efficiency_class="IE3"))
    plant.submit_design()

    returned = plant.decide_design(
        "REQUEST_CHANGES", review_notes="Raise slot fill; recheck core loss."
    )

    assert returned["status"] == "DRAFT"
    assert returned["revision_index"] == 1
    assert returned["review_round"] == 1
    assert returned["released_at"] is None


def test_fourth_review_decision_is_refused_at_the_review_round_ceiling(api, plant):
    """Two cycles share one counter, so the fourth decision hits the ceiling.

    PRD 3.3: "Every decision, without exception, increments `review_round` by 1
    and advances the design's `version`; and every decision is barred once
    `review_round` has already reached 3, since the round counter must be
    strictly below the maximum of 3 review rounds — an attempt at or above that
    ceiling is refused with `ERR_ROUND_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/design_request_changes_revision_cycle_hits_review_round_limit
    """
    plant.add_design(F.motor_design_payload(target_efficiency_class="IE3"))
    design_id = plant.design["id"]
    plant.submit_design()

    returned = plant.decide_design("REQUEST_CHANGES")
    assert (returned["status"], returned["revision_index"], returned["review_round"]) == (
        "DRAFT",
        1,
        1,
    )
    plant.submit_design()
    released = plant.decide_design("APPROVE")
    assert (released["status"], released["revision_index"], released["review_round"]) == (
        "RELEASED",
        1,
        2,
    )
    assert released["released_by_user_id"] == U.USER_DESIGN_REVIEWER
    reopened = plant.open_revision()
    assert (reopened["status"], reopened["revision_index"], reopened["review_round"]) == (
        "REVISION_OPEN",
        2,
        2,
    )
    plant.submit_design()
    rereleased = plant.decide_design("APPROVE")
    assert (
        rereleased["status"],
        rereleased["revision_index"],
        rereleased["review_round"],
    ) == ("RELEASED", 2, 3)
    reopened_again = plant.open_revision()
    assert reopened_again["status"] == "REVISION_OPEN"
    assert reopened_again["revision_index"] == 3
    resubmitted = plant.submit_design()
    assert resubmitted["status"] == "IN_REVIEW"

    refused = api.record_review_decision(
        design_id, F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
    )

    validate_error(refused, ERR_ROUND_LIMIT_EXCEEDED, 422)
    stored = plant.get_design()
    assert stored["status"] == "IN_REVIEW"
    assert stored["review_round"] == 3
    assert stored["revision_index"] == 3
