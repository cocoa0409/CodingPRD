"""Batch production, the quality fork, rework and final settlement."""
from test_helpers import (
    ApiErrorId,
    api_client,
    advance_meal_order_to_quality_hold,
    create_meal_order,
    get_kitchen,
    get_kitchen_version,
    get_meal_order_row,
    make_kitchen_operator_headers,
    setup_delivered_meal_order,
    setup_placed_meal_order,
    transition_meal_order,
    transition_partner_kitchen,
    validate_error,
    TEST_USERS,
)

SAFETY = TEST_USERS["food_safety_officer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_quality_hold_forks_back_to_rework_while_rework_count_is_below_two(api):
    """PRD §3.5: "The batch returns from `QUALITY_HOLD` to `IN_PRODUCTION` for
    rework, which is permitted only while `rework_count` is below 2 — the
    counter starts at 0 on every new batch — and the move increments
    `rework_count` by 1"
    PRD §3.5: "a batch may make that round trip at most twice."

    Design: Difficulty/non_linear_state_machine/meal_order_quality_rework_cycle_and_rejection_branch
    """
    incident, kitchen, order = setup_placed_meal_order()
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 1000)
    first = transition_meal_order(
        order["id"], "IN_PRODUCTION", headers=SAFETY, quality_check_score=62
    )
    assert first["rework_count"] == 1
    assert first["status"] == "IN_PRODUCTION"

    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 1000)
    second = transition_meal_order(
        order["id"], "IN_PRODUCTION", headers=SAFETY, quality_check_score=70
    )
    assert second["rework_count"] == 2
    assert second["status"] == "IN_PRODUCTION"


def test_third_quality_hold_is_forced_to_rejection_regardless_of_score(api):
    """PRD §3.5: "A batch whose `quality_check_score` is 59 or below is rejected
    outright, and so is any batch whose `rework_count` has already reached 2
    regardless of its score."
    PRD §3.5: "Rejection moves the batch from `QUALITY_HOLD` to `REJECTED`, sets
    `rejected_meals` equal to `produced_meals`, sets `accepted_meals` to 0"

    Design: Difficulty/non_linear_state_machine/meal_order_quality_rework_cycle_and_rejection_branch
    """
    incident, kitchen, order = setup_placed_meal_order()
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 1000)
    transition_meal_order(order["id"], "IN_PRODUCTION", headers=SAFETY, quality_check_score=62)
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 1000)
    transition_meal_order(order["id"], "IN_PRODUCTION", headers=SAFETY, quality_check_score=70)
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 1000)

    rejected = transition_meal_order(
        order["id"], "REJECTED", headers=SAFETY, quality_check_score=65
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rework_count"] == 2
    assert rejected["accepted_meals"] == 0
    assert rejected["rejected_meals"] == 1000


def test_rejected_batch_is_terminal_for_further_transitions(api):
    """PRD §3.5: "`DELIVERED`, `REJECTED` and `CANCELLED` are all terminal for a
    batch."
    PRD §2.5: "Terminal-state guard — the entity named in the path is not in a
    terminal state. Failure yields `ERR_ENTITY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/meal_order_terminal_lockdown_rejects_further_transitions
    """
    incident, kitchen, order = setup_placed_meal_order()
    advance_meal_order_to_quality_hold(order["id"], kitchen["id"], 500)
    transition_meal_order(order["id"], "REJECTED", headers=SAFETY, quality_check_score=40)

    refused = api_client.transition_meal_order(
        order["id"], {"to_state": "READY", "quality_check_score": 95}, SAFETY
    )
    validate_error(refused, ApiErrorId.ERR_ENTITY_TERMINAL)
    assert get_meal_order_row(order["id"])["status"] == "REJECTED"


def test_final_settlement_prices_accepted_meals_with_the_quality_multiplier(api):
    """PRD §3.5: "The billable count is `accepted_meals`. The base amount is
    that count multiplied by the restaurant's `per_meal_price_cents`."
    PRD §3.5: "`final_cost_cents` is the base amount multiplied by the
    multiplier, rounded half up once."

    Design: Difficulty/dual_variant_calc/meal_settlement_provisional_vs_final_on_delivery
    """
    incident, kitchen, run, order = setup_delivered_meal_order(
        ordered_meals=1000, produced_meals=1000, rejected_meals=40,
        quality_check_score=88,
    )
    # accepted 960 at 1500 cents = 1,440,000; multiplier 0.95 for a score of 88
    assert order["accepted_meals"] == 960
    assert order["final_cost_cents"] == 1_368_000
    assert order["status"] == "DELIVERED"


def test_provisional_and_final_variants_diverge_by_the_fee_and_discount(api):
    """PRD §3.5: "The provisional variant is pinned once, when the batch is
    created, and it is simply the batch total produced by the cost buildup in
    3.4"
    PRD §3.5: "Because the final variant prices accepted meals only, a batch
    with any rejected meals settles strictly below an otherwise identical batch
    with none"

    Design: Difficulty/dual_variant_calc/meal_settlement_provisional_vs_final_on_delivery
    """
    incident, kitchen, run, order = setup_delivered_meal_order(
        ordered_meals=1000, produced_meals=1000, rejected_meals=40,
        quality_check_score=88,
    )
    assert order["provisional_cost_cents"] == 1_467_750
    assert order["final_cost_cents"] == 1_368_000
    assert order["final_cost_cents"] == order["provisional_cost_cents"] - 99_750
    assert order["final_cost_cents"] < order["provisional_cost_cents"]


def test_quality_score_weights_the_most_recent_window_rows_five_and_four(api):
    """PRD §3.5: "The score is a weighted mean over the restaurant's five most
    recent batches whose status is `DELIVERED` or `REJECTED`"
    PRD §3.5: "The weighted sum of the batches' `quality_check_score` values is
    divided by the sum of the weights used, rounded half up, and clamped to the
    range 0 to 100."

    Design: Corner/calculations/partner_kitchen_quality_score_weighted_window_and_tie_break
    """
    incident, kitchen, run, delivered = setup_delivered_meal_order(
        ordered_meals=500, produced_meals=500, quality_check_score=88,
        rejected_meals=None, scheduled_start="2026-09-01T08:00:00Z",
    )
    rejected = create_meal_order(
        incident["id"], kitchen["id"], ordered_meals=500,
        menu_name="Frijoles Negros", scheduled_start="2026-09-01T13:00:00Z",
    )
    transition_meal_order(rejected["id"], "IN_PRODUCTION")
    advance_meal_order_to_quality_hold(rejected["id"], kitchen["id"], 500)
    transition_meal_order(rejected["id"], "REJECTED", headers=SAFETY, quality_check_score=40)

    assert get_meal_order_row(delivered["id"])["status"] == "DELIVERED"
    assert get_meal_order_row(rejected["id"])["status"] == "REJECTED"
    # (88*5 + 40*4) / 9 = 66.67 -> 67
    row = get_kitchen(kitchen["id"])
    assert row["quality_score"] == 67
    assert row["meals_produced_total"] == 1000


def test_production_start_requires_a_contracted_kitchen(api):
    """PRD §3.5: "the move requires the linked restaurant to be `CONTRACTED`
    with a `production_status` of `IDLE` or `PRODUCING` — a kitchen that is at
    capacity or cooling down cannot take on new work."

    Design: Difficulty/cross_entity_state_dependency/meal_order_production_gated_by_partner_kitchen_contract_state
    """
    incident, kitchen, order = setup_placed_meal_order()
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")

    refused = api_client.transition_meal_order(
        order["id"], {"to_state": "IN_PRODUCTION"}, PLANNER
    )
    validate_error(refused, ApiErrorId.ERR_PARTNER_KITCHEN_NOT_CONTRACTED)
    assert get_meal_order_row(order["id"])["status"] == "PLACED"


def test_production_starts_once_the_kitchen_is_contracted_again(api):
    """PRD §3.5: "the move requires the linked restaurant to be `CONTRACTED`
    with a `production_status` of `IDLE` or `PRODUCING`"
    PRD §3.3: "Reinstatement runs from `SUSPENDED` back to `CONTRACTED` and
    requires `vetting_score` of at least 60"

    Design: Difficulty/cross_entity_state_dependency/meal_order_production_gated_by_partner_kitchen_contract_state
    """
    incident, kitchen, order = setup_placed_meal_order()
    operator = make_kitchen_operator_headers(kitchen["id"])
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")

    api_client.set_current_utc("2026-09-01T20:00:00Z", ADMIN)
    transition_partner_kitchen(kitchen["id"], "PRODUCTION", "IDLE", headers=operator)
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72)

    started = transition_meal_order(order["id"], "IN_PRODUCTION")
    assert started["status"] == "IN_PRODUCTION"
    assert get_kitchen(kitchen["id"])["contract_status"] == "CONTRACTED"


def test_overlapping_production_window_is_rejected(api):
    """PRD §3.4: "Creating a batch is rejected with `ERR_KITCHEN_WINDOW_CONFLICT`
    if another batch of the same kitchen in `PLACED`, `IN_PRODUCTION`,
    `QUALITY_HOLD`, `READY` or `DISPATCHED` status occupies a half-open window
    that intersects the new one."

    Design: Difficulty/resource_temporal_overlap/partner_kitchen_production_windows_are_half_open_with_adjacency_allowed
    """
    incident, kitchen, order = setup_placed_meal_order(
        ordered_meals=500, scheduled_start="2026-09-01T08:00:00Z", producing=True
    )
    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 500,
            "scheduled_start": "2026-09-01T11:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": get_kitchen_version(kitchen["id"]),
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_KITCHEN_WINDOW_CONFLICT)


def test_adjacent_window_sharing_the_endpoint_is_accepted(api):
    """PRD §3.4: "The production window is the half-open interval running from
    `scheduled_start` up to but not including `scheduled_start` plus
    `production_hours`."

    Design: Difficulty/resource_temporal_overlap/partner_kitchen_production_windows_are_half_open_with_adjacency_allowed
    """
    incident, kitchen, order = setup_placed_meal_order(
        ordered_meals=500, scheduled_start="2026-09-01T08:00:00Z", producing=True
    )
    adjacent = create_meal_order(
        incident["id"], kitchen["id"], ordered_meals=500,
        scheduled_start="2026-09-01T12:00:00Z", production_hours=4,
    )
    # the PRD fixes the three-fractional-digit form only for the four
    # system-managed properties (2.4); the echo form of a client-supplied
    # instant is not stated, so only acceptance is asserted here
    assert adjacent["status"] == "PLACED"


