"""Production batches: creation gates, cost buildup and provisional settlement."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_meal_order,
    create_incident,
    create_partner_kitchen,
    get_incident_row,
    get_kitchen_version,
    get_meal_order_row,
    make_kitchen_operator_headers,
    setup_active_incident,
    setup_contracted_partner_kitchen,
    setup_placed_meal_order,
    transition_partner_kitchen,
    transition_meal_order,
    validate_error,
    TEST_USERS,
)

PARTNER = TEST_USERS["partnership_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_cost_buildup_pins_the_discount_on_the_pre_discount_subtotal(api):
    """PRD §3.4: "First, `subtotal_cents` is the `ordered_meals` multiplied by
    the restaurant's `per_meal_price_cents`."
    PRD §3.4: "Third, `logistics_fee_cents` is 3 percent of `subtotal_cents`,
    rounded half up."
    PRD §3.4: "Fifth, `volume_discount_cents` is the discount base multiplied
    by the tier rate, rounded half up, where the `BULK` rate is 0.08, the
    `STANDARD` rate is 0.05 and the `SMALL` rate is 0.00."

    Design: Difficulty/combinatorial_formula/meal_order_cost_buildup_pinned_evaluation_order
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    order = create_meal_order(incident["id"], kitchen["id"], ordered_meals=1000)
    assert order["subtotal_cents"] == 1_500_000
    assert order["logistics_fee_cents"] == 45_000
    assert order["volume_discount_cents"] == 77_250
    assert order["provisional_cost_cents"] == 1_467_750


def test_provisional_total_is_subtotal_plus_fee_minus_discount(api):
    """PRD §3.4: "Sixth, the batch total is `subtotal_cents` plus
    `logistics_fee_cents` minus `volume_discount_cents`. Seventh, that total is
    pinned as `provisional_cost_cents`."

    Design: Difficulty/combinatorial_formula/meal_order_cost_buildup_pinned_evaluation_order
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    order = create_meal_order(incident["id"], kitchen["id"], ordered_meals=1000)
    assert order["provisional_cost_cents"] == (
        order["subtotal_cents"]
        + order["logistics_fee_cents"]
        - order["volume_discount_cents"]
    )
    assert order["status"] == "PLACED"


def test_tier_selector_is_inclusive_at_eight_hundred_thousand_cents(api):
    """PRD §3.4: "The tier boundaries are exact: a subtotal of 800,000 selects
    `STANDARD` while 799,999 selects `SMALL`, and 2,000,000 selects `BULK`
    while 1,999,999 selects `STANDARD`."

    Design: Corner/calculations/meal_order_buildup_tier_boundary_at_exactly_800000
    """
    incident, kitchen = setup_contracted_partner_kitchen(per_meal_price_cents=1000)
    larger = create_meal_order(
        incident["id"], kitchen["id"], ordered_meals=800,
        scheduled_start="2026-09-01T08:00:00Z",
    )
    smaller = create_meal_order(
        incident["id"], kitchen["id"], ordered_meals=799,
        scheduled_start="2026-09-01T14:00:00Z",
    )

    assert larger["subtotal_cents"] == 800_000
    assert larger["logistics_fee_cents"] == 24_000
    assert larger["volume_discount_cents"] == 41_200
    assert larger["provisional_cost_cents"] == 782_800

    assert smaller["subtotal_cents"] == 799_000
    assert smaller["volume_discount_cents"] == 0
    assert smaller["provisional_cost_cents"] == 822_970
    assert smaller["provisional_cost_cents"] > larger["provisional_cost_cents"]


def test_placing_a_batch_increments_the_restaurant_version(api):
    """PRD §3.4: "The restaurant's `version` is incremented by 1, which is
    precisely why the next planner to place a batch against that kitchen needs
    a fresh `expected_partner_kitchen_version`."

    Design: Difficulty/combinatorial_formula/meal_order_cost_buildup_pinned_evaluation_order
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    before = get_kitchen_version(kitchen["id"])
    create_meal_order(incident["id"], kitchen["id"], ordered_meals=500)
    after = get_kitchen_version(kitchen["id"])
    assert after == before + 1


def test_meal_order_is_immediately_readable_with_the_same_version(api):
    """PRD §2.4: "`version` is a system-managed integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of the resource."

    Design: Corner/consistency_model/created_meal_order_is_immediately_readable_with_same_version
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    created = create_meal_order(incident["id"], kitchen["id"], ordered_meals=1000)
    read = get_meal_order_row(created["id"])
    assert read["version"] == created["version"]
    assert read["provisional_cost_cents"] == created["provisional_cost_cents"]
    assert read["provisional_cost_cents"] == 1_467_750
    assert read["status"] == "PLACED"


def test_placed_batch_cannot_jump_straight_to_delivered(api):
    """PRD §2.5: "Transition reachability — the entity named in the path is in a
    state whose outgoing transitions include the requested `to_state`"
    PRD §3.4: "A new batch starts in `PLACED`, is stamped with `placed_at`, and
    leaves `distribution_run_id` unset until the batch is dispatched."

    Design: Corner/state_machines/meal_order_invalid_transition_from_placed_to_delivered
    """
    incident, kitchen, order = setup_placed_meal_order()
    refused = api_client.transition_meal_order(
        order["id"], {"to_state": "DELIVERED"}, TEST_USERS["logistics_coordinator_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert get_meal_order_row(order["id"])["status"] == "PLACED"


def test_cancelling_the_only_placed_batch_releases_the_reservation(api):
    """PRD §3.5: "A `ProductionPlanner` may move a batch from `PLACED` to
    `CANCELLED`, supplying a `cancel_reason`; the move recomputes the
    activation's `spent_cents` so the reservation is released."

    Design: Corner/cross_cutting_complexity_layers/incident_spent_cents_reconciles_after_order_cancellation
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    order = create_meal_order(incident["id"], kitchen["id"], ordered_meals=500)
    assert get_incident_row(incident["id"])["spent_cents"] == 772_500

    cancelled = transition_meal_order(order["id"], "CANCELLED", cancel_reason="STAND_DOWN")
    assert cancelled["status"] == "CANCELLED"
    assert get_incident_row(incident["id"])["spent_cents"] == 0


def test_second_order_above_the_ceiling_is_refused_while_the_first_is_below(api):
    """PRD §2.11: "Placing a batch that would push `spent_cents` above the
    ceiling is rejected with `ERR_FUNDING_CEILING_EXCEEDED` (HTTP 422)."
    PRD §2.11: "The measure used for that check is the incident's
    `spent_cents`, which aggregates three streams"

    Design: Corner/validations/funding_ceiling_aggregate_breach_on_second_order
    """
    # the ceiling is an incident-level input: the kitchen helper only forwards
    # kitchen-level overrides, so the activation is created explicitly
    incident, _ = setup_active_incident(funding_ceiling_cents=1_000_000)
    _, kitchen = setup_contracted_partner_kitchen(incident["id"])
    first = create_meal_order(
        incident["id"], kitchen["id"], ordered_meals=500,
        scheduled_start="2026-09-01T08:00:00Z",
    )
    assert first["provisional_cost_cents"] == 772_500

    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 500,
            "scheduled_start": "2026-09-01T14:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": get_kitchen_version(kitchen["id"]),
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_FUNDING_CEILING_EXCEEDED)
    assert get_incident_row(incident["id"])["spent_cents"] == 772_500


def test_dietary_tags_must_cover_the_populations_requirements(api):
    """PRD §3.4: "the batch's `dietary_tags` must cover every tag in the
    incident's `population_dietary_requirements`, and a batch that would leave
    part of the affected population without a meal it can eat is rejected with
    `ERR_DIETARY_REQUIREMENT_UNMET`."

    Design: Corner/validations/dietary_requirement_unmet_rejected
    """
    incident = create_incident(population_dietary_requirements=["HALAL"])
    kitchen = create_partner_kitchen(incident["id"])
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "VETTING")
    kitchen = transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )

    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 500,
            "scheduled_start": "2026-09-01T08:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": get_kitchen_version(kitchen["id"]),
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_DIETARY_REQUIREMENT_UNMET)
    assert get_incident_row(incident["id"])["spent_cents"] == 0


def test_contract_state_precondition_outranks_the_funding_ceiling(api):
    """PRD §2.5: "When two conditions hold at once, the lower-numbered rule
    wins and its error identifier is the one returned; a later rule is never
    consulted once an earlier one has failed."
    PRD §3.4: "the restaurant must be in `contract_status` `CONTRACTED`, or the
    create is rejected with `ERR_PARTNER_KITCHEN_NOT_CONTRACTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_funding_ceiling_on_meal_order_creation
    """
    incident = create_incident(funding_ceiling_cents=100_000)
    kitchen = create_partner_kitchen(incident["id"])
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "VETTING")
    transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    operator = make_kitchen_operator_headers(kitchen["id"])
    transition_partner_kitchen(kitchen["id"], "PRODUCTION", "PRODUCING", headers=operator)
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")

    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 1000,
            "scheduled_start": "2026-09-01T08:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": get_kitchen_version(kitchen["id"]),
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_PARTNER_KITCHEN_NOT_CONTRACTED)
    assert get_incident_row(incident["id"])["spent_cents"] == 0


def test_funding_ceiling_error_surfaces_once_the_state_violation_is_gone(api):
    """PRD §2.11: "Placing a batch that would push `spent_cents` above the
    ceiling is rejected with `ERR_FUNDING_CEILING_EXCEEDED` (HTTP 422)."
    PRD §3.3: "Reinstatement runs from `SUSPENDED` back to `CONTRACTED` and
    requires `vetting_score` of at least 60"

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_funding_ceiling_on_meal_order_creation
    """
    incident = create_incident(funding_ceiling_cents=100_000)
    kitchen = create_partner_kitchen(incident["id"])
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "VETTING")
    transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    operator = make_kitchen_operator_headers(kitchen["id"])
    transition_partner_kitchen(kitchen["id"], "PRODUCTION", "PRODUCING", headers=operator)
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")

    api_client.set_current_utc("2026-09-01T20:00:00Z", ADMIN)
    transition_partner_kitchen(kitchen["id"], "PRODUCTION", "IDLE", headers=operator)
    transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )

    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 1000,
            "scheduled_start": "2026-09-01T08:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": get_kitchen_version(kitchen["id"]),
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_FUNDING_CEILING_EXCEEDED)
    assert get_incident_row(incident["id"])["spent_cents"] == 0
