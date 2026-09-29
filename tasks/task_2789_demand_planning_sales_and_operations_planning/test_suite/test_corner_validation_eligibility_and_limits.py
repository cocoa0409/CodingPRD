"""Breadth over the cross-entity eligibility gates and the bounded counters: which
referenced row makes a write legal, which lifecycle state permits which adjustment
type, and where the reopen, revision and swing ceilings actually bite.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    adjustment_resubmit_payload,
    consensus_adjustment_payload,
    cycle_transition_payload,
    item_lifecycle_payload,
    supply_plan_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    PLANNER,
    SUPPLY,
    advance_cycle_to,
    approve_promotion,
    build_supply_plan,
    create_adjustment,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    read_adjustment,
    read_cycle,
    read_forecast,
    read_item,
    resubmit_adjustment,
    review_adjustment,
    transition_cycle,
    transition_item,
)


def test_a_draft_promotion_cannot_be_cited_until_it_has_been_approved():
    """Citing a promotion that has not cleared review is refused outright, and the
    identical request succeeds once approval lands — at which point the two rounded
    percentage terms net to the applied delta.

    PRD: "A `PROMOTION` adjustment's `promotion_id` must reference a promotion that
    is `APPROVED` **and** whose item is the same item as the target forecast line's;
    a promotion that is still `DRAFT`, one that has been cancelled, or one attached
    to a different item is rejected with `ERR_PROMOTION_NOT_APPROVED`."

    Design: Corner/validations/promotion_adjustment_citing_draft_promotion_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-PROMO", financial_commitment_cents=0)
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=1000
    )
    promotion = create_promotion(
        item["id"], customer["id"], lift_pct=10, cannibalization_pct=2
    )
    assert promotion["status"] == "DRAFT"

    payload = consensus_adjustment_payload(
        forecast["id"],
        forecast["version"],
        "PROMOTION",
        0,
        promotion_id=promotion["id"],
        rationale="citing a promotion still awaiting review",
    )
    validate_error(
        api_client.create_consensus_adjustment(payload, PLANNER),
        ApiErrorId.ERR_PROMOTION_NOT_APPROVED.value,
        422,
    )

    untouched = read_forecast(forecast["id"])
    assert untouched["status"] == "BASELINE"
    assert untouched["consensus_units"] == 1000
    assert untouched["version"] == forecast["version"]

    approve_promotion(promotion["id"])
    accepted = validate_success(
        api_client.create_consensus_adjustment(payload, PLANNER), 201
    )
    assert accepted["applied_delta_units"] == 80
    assert accepted["status"] == "PROPOSED"

    carried = read_forecast(forecast["id"])
    assert carried["status"] == "UNDER_CONSENSUS"
    assert carried["consensus_units"] == 1000


def test_the_permitted_adjustment_types_swap_over_between_two_lifecycle_states():
    """Each type is refused on exactly the state the other one requires, so the same
    two requests that fail against one item succeed against the other, and both
    refusals leave their target line untouched.

    PRD: "A `NEW_ITEM_PLAN` adjustment is permitted only when the target line's item
    is in `PRELAUNCH` or `RAMP`, and a `SALES_INTELLIGENCE` adjustment is forbidden
    on an item in `PRELAUNCH`; either misuse is rejected with
    `ERR_ADJUSTMENT_TYPE_NOT_PERMITTED`."

    Design: Corner/validations/adjustment_type_permitted_set_tracks_item_lifecycle_in_both_directions
    """
    family = create_family()
    mature = create_item(family["id"], sku="SKU-MAT")
    prelaunch = create_item(
        family["id"], sku="SKU-PRE", lifecycle_state="PRELAUNCH", npi_ramp_pct=100
    )
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-TYPE", financial_commitment_cents=0)
    mature_line = create_forecast(
        cycle["id"], mature["id"], customer["id"], level_units=1000
    )
    prelaunch_line = create_forecast(
        cycle["id"], prelaunch["id"], customer["id"], level_units=1000
    )
    assert mature_line["baseline_units"] == 1000
    assert prelaunch_line["baseline_units"] == 1000

    validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                mature_line["id"],
                mature_line["version"],
                "NEW_ITEM_PLAN",
                100,
                rationale="launch plan against a mature product",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_ADJUSTMENT_TYPE_NOT_PERMITTED.value,
        422,
    )
    validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                prelaunch_line["id"],
                prelaunch_line["version"],
                "SALES_INTELLIGENCE",
                100,
                rationale="field intelligence on an unlaunched product",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_ADJUSTMENT_TYPE_NOT_PERMITTED.value,
        422,
    )

    assert read_forecast(mature_line["id"])["status"] == "BASELINE"
    assert read_forecast(prelaunch_line["id"])["status"] == "BASELINE"

    on_mature = create_adjustment(
        mature_line["id"],
        mature_line["version"],
        "SALES_INTELLIGENCE",
        100,
        rationale="field intelligence on a mature product",
    )
    assert on_mature["applied_delta_units"] == 100

    on_prelaunch = create_adjustment(
        prelaunch_line["id"],
        prelaunch_line["version"],
        "NEW_ITEM_PLAN",
        100,
        rationale="launch plan against an unlaunched product",
    )
    assert on_prelaunch["applied_delta_units"] == 100


def test_only_an_unlaunched_sibling_in_the_same_family_may_inherit_the_shelf_space():
    """Three nominations fail for three different reasons — wrong family, the item
    itself, and a sibling that has already matured — and every failure leaves the
    predecessor mature with no successor recorded.

    PRD: "Nominating the item itself, an item from another family, or an item that
    is already `MATURE`, `RUNOUT`, `DISCONTINUED` or `CANCELLED_NPI` is rejected
    with `ERR_SUCCESSOR_NOT_ELIGIBLE`."

    Design: Corner/validations/successor_item_in_other_family_rejected
    """
    family_one = create_family(family_code="FAM-ONE", name="Family One")
    family_two = create_family(
        family_code="FAM-TWO",
        name="Family Two",
        accountable_planner_user_id="planner-2",
    )
    running_out = create_item(family_one["id"], sku="SKU-OLD", on_hand_units=0)
    successor = create_item(
        family_one["id"], sku="SKU-NEW", lifecycle_state="PRELAUNCH", npi_ramp_pct=100
    )
    peer = create_item(family_one["id"], sku="SKU-PEER")
    foreign = create_item(
        family_two["id"],
        sku="SKU-FOREIGN",
        lifecycle_state="PRELAUNCH",
        npi_ramp_pct=100,
    )

    for nominee in (foreign["id"], running_out["id"], peer["id"]):
        validate_error(
            api_client.transition_item_lifecycle(
                running_out["id"],
                item_lifecycle_payload(
                    "RUNOUT",
                    runout_end_month="2026-09",
                    successor_item_id=nominee,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_SUCCESSOR_NOT_ELIGIBLE.value,
            422,
        )
        still_mature = read_item(running_out["id"])
        assert still_mature["lifecycle_state"] == "MATURE"
        assert still_mature["successor_item_id"] is None

    accepted = transition_item(
        running_out["id"],
        "RUNOUT",
        runout_end_month="2026-09",
        successor_item_id=successor["id"],
    )
    assert accepted["lifecycle_state"] == "RUNOUT"
    assert accepted["successor_item_id"] == successor["id"]
    assert accepted["runout_end_month"] == "2026-09"

    listing = api_client.list_items(
        ADMIN, params={"successor_item_id": successor["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == running_out["id"]


def test_an_item_with_no_forecast_line_at_all_cannot_be_planned():
    """An empty demand side is not a vacuous success: the item nobody forecast is
    refused while its sibling plans normally, so the cycle ends with one plan and one
    plan's worth of value.

    PRD: "The demand side must be settled: at least one forecast line must exist for
    that cycle-and-item pair, and every such line must be in either
    `CONSENSUS_LOCKED` or `RUNOUT_TRUNCATED`."

    Design: Corner/validations/supply_plan_create_with_no_forecast_at_all_returns_forecast_not_locked
    """
    family = create_family()
    planned = create_item(family["id"], sku="SKU-PLANNED")
    orphan = create_item(family["id"], sku="SKU-ORPHAN")
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=14)
    cycle = create_cycle(cycle_code="CY-ORPHAN", financial_commitment_cents=0)
    create_forecast(cycle["id"], planned["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    validate_error(
        api_client.create_supply_plan(
            supply_plan_payload(cycle["id"], orphan["id"]), SUPPLY
        ),
        ApiErrorId.ERR_FORECAST_NOT_LOCKED.value,
        422,
    )

    sibling = build_supply_plan(cycle["id"], planned["id"])
    assert sibling["gross_requirement_units"] == 1000
    assert sibling["constrained_units"] == 1330
    assert sibling["constraint_type"] == "NONE"

    listing = api_client.list_supply_plans(
        SUPPLY, params={"cycle_id": cycle["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["item_id"] == planned["id"]
    assert read_cycle(cycle["id"])["plan_value_cents"] == 1330000


def test_the_third_reopen_is_refused_and_leaves_the_cycle_where_it_stood():
    """Two reopens are available and the third is not, and because the refusal is a
    guard rather than a partial cascade the cycle keeps its phase, its counter and
    its version token.

    PRD: "The cycle must be in `EXECUTIVE_REVIEW`, and its `reopen_count` must be
    below two; a third attempt is rejected with `ERR_REOPEN_LIMIT_REACHED`."

    Design: Corner/validations/reopen_beyond_max_reopens_rejected
    """
    cycle = create_cycle(cycle_code="CY-REOPEN", financial_commitment_cents=0)
    assert cycle["reopen_count"] == 0

    advance_cycle_to(cycle["id"], "EXECUTIVE_REVIEW")
    first = transition_cycle(
        cycle["id"], "DEMAND_REVIEW", EXEC, reopen_reason="first look again"
    )
    assert first["status"] == "DEMAND_REVIEW"
    assert first["reopen_count"] == 1

    advance_cycle_to(cycle["id"], "EXECUTIVE_REVIEW")
    second = transition_cycle(
        cycle["id"], "DEMAND_REVIEW", EXEC, reopen_reason="second look again"
    )
    assert second["reopen_count"] == 2

    exhausted = advance_cycle_to(cycle["id"], "EXECUTIVE_REVIEW")
    assert exhausted["status"] == "EXECUTIVE_REVIEW"

    validate_error(
        api_client.transition_planning_cycle(
            cycle["id"],
            cycle_transition_payload("DEMAND_REVIEW", reopen_reason="one too many"),
            EXEC,
        ),
        ApiErrorId.ERR_REOPEN_LIMIT_REACHED.value,
        422,
    )

    unchanged = read_cycle(cycle["id"])
    assert unchanged["status"] == "EXECUTIVE_REVIEW"
    assert unchanged["reopen_count"] == 2
    assert unchanged["version"] == exhausted["version"]


def test_the_fourth_resubmission_is_refused_and_the_row_keeps_its_third_round():
    """Three revision round trips are available and the fourth is not, and the
    refused resubmission leaves the row's counter, its delta and its rationale
    exactly as the third round left them.

    PRD: "the row's `revision_round` must be below three, otherwise
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/validations/resubmit_beyond_max_revision_rounds_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-REVISION", financial_commitment_cents=0)
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=1000
    )

    adjustment = create_adjustment(
        forecast["id"], forecast["version"], "SALES_INTELLIGENCE", 100
    )
    assert adjustment["revision_round"] == 0

    for round_number, delta, wording in (
        (1, 110, "round one"),
        (2, 120, "round two"),
        (3, 130, "round three"),
    ):
        review_adjustment(adjustment["id"], "REQUEST_REVISION", review_note="again")
        resubmitted = resubmit_adjustment(
            adjustment["id"],
            read_forecast(forecast["id"])["version"],
            delta_units=delta,
            rationale=wording,
        )
        assert resubmitted["revision_round"] == round_number
        assert resubmitted["applied_delta_units"] == delta
        assert resubmitted["status"] == "PROPOSED"

    review_adjustment(adjustment["id"], "REQUEST_REVISION", review_note="one more")
    validate_error(
        api_client.resubmit_consensus_adjustment(
            adjustment["id"],
            adjustment_resubmit_payload(
                read_forecast(forecast["id"])["version"],
                delta_units=140,
                rationale="round four",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_REVISION_LIMIT_REACHED.value,
        422,
    )

    frozen = read_adjustment(adjustment["id"])
    assert frozen["status"] == "REVISION_REQUESTED"
    assert frozen["revision_round"] == 3
    assert frozen["applied_delta_units"] == 130
    assert frozen["rationale"] == "round three"
    assert read_forecast(forecast["id"])["consensus_units"] == 1000


def test_a_delta_exactly_on_the_quarter_of_the_baseline_is_accepted():
    """The ceiling is a rounded quarter of the baseline rather than of the consensus,
    so the delta one unit above it is refused, the delta exactly on it is taken, and
    endorsing it moves the consensus while leaving the baseline where it was.

    PRD: "A single adjustment's `applied_delta_units`, taken in absolute value, may
    not exceed a quarter of the target line's `baseline_units` — computed as
    `baseline_units` multiplied by twenty-five, divided by one hundred, rounded half
    up to a whole number of units."

    Design: Corner/validations/adjustment_swing_at_exactly_25_percent_of_baseline_passes
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-SWING", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=400)
    assert forecast["baseline_units"] == 400

    validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                forecast["id"],
                forecast["version"],
                "SALES_INTELLIGENCE",
                101,
                rationale="one unit past the quarter",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_ADJUSTMENT_SWING_EXCEEDED.value,
        422,
    )
    assert read_forecast(forecast["id"])["version"] == forecast["version"]

    on_the_line = create_adjustment(
        forecast["id"],
        forecast["version"],
        "SALES_INTELLIGENCE",
        100,
        rationale="exactly a quarter of the baseline",
    )
    assert on_the_line["applied_delta_units"] == 100

    review_adjustment(on_the_line["id"], "ENDORSE")
    rolled = read_forecast(forecast["id"])
    assert rolled["consensus_units"] == 500
    assert rolled["endorsed_adjustment_count"] == 1
    assert rolled["baseline_units"] == 400
