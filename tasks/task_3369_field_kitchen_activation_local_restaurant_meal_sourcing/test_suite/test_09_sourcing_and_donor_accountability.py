"""Local sourcing, donor fund conservation and the accountability report."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_and_deliver_purchase,
    create_incident,
    create_ingredient_purchase,
    create_partner_kitchen,
    create_supplier,
    get_accountability,
    get_incident_row,
    get_kitchen_version,
    get_meal_order_row,
    get_purchase_row,
    get_supplier_row,
    setup_active_incident,
    setup_allocated_commitment,
    setup_contracted_partner_kitchen,
    setup_delivered_meal_order,
    setup_supplier_with_delivered_purchase,
    transition_donor_commitment,
    transition_ingredient_purchase,
    transition_partner_kitchen,
    validate_error,
    validate_paginated,
)

PLANNER = TEST_USERS["production_planner_headers"]
SOURCING = TEST_USERS["sourcing_officer_headers"]
DONOR = TEST_USERS["donor_liaison_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_confirmation_is_refused_only_while_the_producer_is_suspended(api):
    """PRD §2.5: "Producer not suspended — the `Supplier` referenced by an
    `IngredientPurchase` does not have `status` of `SUSPENDED` (`PROSPECT`,
    `APPROVED` and `PREFERRED` all pass). Failure yields
    `ERR_SUPPLIER_NOT_APPROVED` (HTTP 409)."
    PRD §3.6: "Moving an order from `REQUESTED` to `CONFIRMED` is refused only
    when the linked producer is `SUSPENDED`, and the attempt is then rejected
    with `ERR_SUPPLIER_NOT_APPROVED`."
    PRD §3.6: "An order that never left the starting line can simply be
    abandoned: `REQUESTED` to `CANCELLED` recomputes the producer's
    `reliability_score` and standing."
    PRD §3.6: "First, the producer is `SUSPENDED` whenever `reliability_score`
    is below 40 — a low score overrides everything else."

    Design: Corner/state_machines/ingredient_purchase_confirm_requires_approved_supplier
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier = create_supplier(incident["id"])
    abandoned = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"]
    )
    second = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="black beans", quantity_kg=500, unit_price_cents_per_kg=500,
    )

    transition_ingredient_purchase(abandoned["id"], "CANCELLED")
    row = get_supplier_row(incident["id"], supplier["id"])
    assert row["status"] == "SUSPENDED"
    assert row["reliability_score"] == 25

    refused = api_client.transition_ingredient_purchase(
        second["id"], {"to_state": "CONFIRMED"}, SOURCING
    )
    validate_error(refused, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)
    assert get_purchase_row(second["id"])["status"] == "REQUESTED"


def test_sourcing_order_cannot_skip_the_confirmation_step(api):
    """PRD §3.6: "A new order starts in `REQUESTED` with `requested_at` stamped"
    PRD §2.5: "Transition reachability — the entity named in the path is in a
    state whose outgoing transitions include the requested `to_state`"

    Design: Corner/state_machines/ingredient_purchase_confirm_requires_approved_supplier
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier = create_supplier(incident["id"])
    purchase = create_ingredient_purchase(incident["id"], supplier["id"], kitchen["id"])

    refused = api_client.transition_ingredient_purchase(
        purchase["id"], {"to_state": "DELIVERED"}, SOURCING
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert purchase["status"] == "REQUESTED"
    assert purchase["amount_cents"] == 300_000


def test_unresolved_foreign_key_is_reported_before_any_business_rule(api):
    """PRD §2.9: "Every foreign-key identifier — `incident_id`, `assessment_id`,
    `partner_kitchen_id`, `supplier_id`, `field_kitchen_id`,
    `distribution_run_id`, `distribution_site_id` — is checked against the
    corresponding entity before any business rule runs, and an unresolved
    identifier yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/referenced_entity_not_found_rejected
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": "3f1c9d77-0a52-4c1e-9a6f-2b7d5e8c4a10",
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 500,
            "scheduled_start": "2026-09-01T08:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": 1,
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)
    assert get_incident_row(incident["id"])["spent_cents"] == 0


def test_second_drawdown_above_the_commitment_face_value_is_refused(api):
    """PRD §2.11: "A disbursement that would push `disbursed_cents` above
    `amount_cents` is rejected with `ERR_DISBURSEMENT_EXCEEDS_COMMITMENT`
    (HTTP 422)."

    Design: Corner/validations/disbursement_exceeds_commitment_rejected
    """
    incident, commitment = setup_allocated_commitment(amount_cents=1_000_000)
    drawn = transition_donor_commitment(
        commitment["id"], "PARTIALLY_DISBURSED", disbursement_cents=400_000
    )
    assert drawn["disbursed_cents"] == 400_000

    refused = api_client.transition_donor_commitment(
        commitment["id"],
        {"to_state": "PARTIALLY_DISBURSED", "disbursement_cents": 700_000},
        DONOR,
    )
    validate_error(refused, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_COMMITMENT)

    commitments, _ = validate_paginated(
        api_client.list_incident_donor_commitments(incident["id"], DONOR, {"limit": 50})
    )
    assert commitments[0]["disbursed_cents"] == 400_000
    assert commitments[0]["remaining_cents"] == 600_000


def test_empty_delivery_set_reports_zero_rather_than_dividing_by_zero(api):
    """PRD §3.8: "`local_sourcing_pct` is the numerator multiplied by 100 and
    divided by the denominator, rounded half up, or 0 when the denominator is
    0."
    PRD §3.8: "`cost_per_meal_cents` is the denominator divided by
    `delivered_meal_total`, rounded half up, or 0 when `delivered_meal_total` is
    0."

    Design: Difficulty/boundary_precision_check/accountability_report_empty_delivery_set_returns_zero_not_an_error
    """
    incident = create_incident()
    report = get_accountability(incident["id"])
    assert report["local_sourcing_pct"] == 0
    assert report["cost_per_meal_cents"] == 0
    assert report["delivered_meal_total"] == 0
    assert report["incident_id"] == incident["id"]


def test_empty_delivery_set_flags_below_target_and_spends_nothing(api):
    """PRD §3.8: "The `donor_report_flag` is `BELOW_LOCAL_SOURCING_TARGET` when
    `local_sourcing_pct` is below 30, and `ON_TARGET` otherwise; the 30 percent
    figure is the share of delivered-meal spend the operation expects to be
    matched by local supplier purchases."

    Design: Difficulty/boundary_precision_check/accountability_report_empty_delivery_set_returns_zero_not_an_error
    """
    incident = create_incident()
    report = get_accountability(incident["id"])
    assert report["donor_report_flag"] == "BELOW_LOCAL_SOURCING_TARGET"
    assert report["spent_cents"] == 0
    assert report["committed_cents"] == 0
    assert get_incident_row(incident["id"])["spent_cents"] == 0


def test_referenced_entity_from_another_activation_is_refused(api):
    """PRD §2.9: "A batch placed against a kitchen from a different activation,
    a stop added to a run from a different activation, or a dispatch pointed at
    a run serving a different incident is rejected with
    `ERR_CROSS_INCIDENT_REFERENCE` (HTTP 422)."

    Design: Corner/validations/cross_incident_reference_rejected
    """
    first_incident, first_assessment = setup_active_incident()
    second_incident, _ = setup_active_incident(name="Bay Wildfire")
    kitchen = create_partner_kitchen(first_incident["id"])
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "VETTING")
    kitchen = transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )

    refused = api_client.create_meal_order(
        {
            "incident_id": second_incident["id"],
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
    validate_error(refused, ApiErrorId.ERR_CROSS_INCIDENT_REFERENCE)
    assert get_incident_row(second_incident["id"])["spent_cents"] == 0




def test_payment_that_promotes_the_producer_auto_confirms_its_pending_orders(api):
    """PRD §3.6: "if the recomputation lifts the producer into `PREFERRED`,
    every other order of that producer still sitting in `REQUESTED` is set to
    `CONFIRMED` automatically, on the reasoning that a producer the operation
    trusts enough to prefer does not need each of its orders individually
    cleared."
    PRD §3.6: "Second, if the producer is not suspended, it is `PREFERRED`
    whenever `cash_flow_received_cents` is at least 500,000 and
    `reliability_score` is at least 70."

    Design: Difficulty/transitive_cascade/supplier_payment_promotes_producer_and_autoconfirms_pending_orders
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier = create_supplier(incident["id"])
    first = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"]
    )
    second = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="black beans", quantity_kg=500, unit_price_cents_per_kg=500,
    )
    pending = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="cooking oil", quantity_kg=400, unit_price_cents_per_kg=300,
    )

    confirm_and_deliver_purchase(first["id"])
    transition_ingredient_purchase(first["id"], "PAID")
    confirm_and_deliver_purchase(second["id"])
    transition_ingredient_purchase(second["id"], "PAID")

    row = get_supplier_row(incident["id"], supplier["id"])
    assert row["status"] == "PREFERRED"
    assert row["cash_flow_received_cents"] == 550_000
    assert row["reliability_score"] == 70
    assert get_purchase_row(pending["id"])["status"] == "CONFIRMED"


def test_orders_created_after_the_promotion_are_not_swept(api):
    """PRD §3.6: "Payment carries the only second-hop cascade in the sourcing
    flow: if the recomputation lifts the producer into `PREFERRED`, every other
    order of that producer still sitting in `REQUESTED` is set to `CONFIRMED`
    automatically"
    PRD §3.6: "A new order starts in `REQUESTED` with `requested_at` stamped"

    Design: Difficulty/transitive_cascade/supplier_payment_promotes_producer_and_autoconfirms_pending_orders
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier = create_supplier(incident["id"])
    first = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"]
    )
    second = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="black beans", quantity_kg=500, unit_price_cents_per_kg=500,
    )
    confirm_and_deliver_purchase(first["id"])
    transition_ingredient_purchase(first["id"], "PAID")
    confirm_and_deliver_purchase(second["id"])

    paid = transition_ingredient_purchase(second["id"], "PAID")
    assert paid["status"] == "PAID"

    later = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="dried lentils", quantity_kg=100, unit_price_cents_per_kg=200,
    )
    assert later["status"] == "REQUESTED"
    assert get_supplier_row(incident["id"], supplier["id"])["status"] == "PREFERRED"


def test_reversing_a_payment_restores_the_producers_unreceived_balance(api):
    """PRD §3.6: "Cash already released can be clawed back: moving an order from
    `PAID` to `DISPUTED` — the compensating action of the payment — decrements
    the producer's `cash_flow_received_cents` by exactly the order's
    `amount_cents`, returning that balance to its pre-payment value, and
    recomputes the producer's standing together with the activation's
    `spent_cents` and `local_sourcing_pct`."

    Design: Difficulty/compensating_invariant/supplier_cash_reversal_restores_pre_payment_balance
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier, purchase = setup_supplier_with_delivered_purchase(
        incident["id"], kitchen["id"]
    )
    assert get_supplier_row(incident["id"], supplier["id"])["cash_flow_received_cents"] == 0

    transition_ingredient_purchase(purchase["id"], "PAID")
    after_paid = get_supplier_row(incident["id"], supplier["id"])
    assert after_paid["cash_flow_received_cents"] == 300_000

    transition_ingredient_purchase(
        purchase["id"], "DISPUTED", dispute_reason="QUANTITY_SHORTFALL"
    )
    after_reversal = get_supplier_row(incident["id"], supplier["id"])
    assert after_reversal["cash_flow_received_cents"] == 0
    assert get_purchase_row(purchase["id"])["amount_cents"] == 300_000


def test_a_disputed_payment_leaves_the_activation_with_no_spend(api):
    """PRD §2.11: "the `amount_cents` of every `IngredientPurchase` whose
    `status` is `DELIVERED` or `PAID`"
    PRD §3.6: "decrements the producer's `cash_flow_received_cents` by exactly
    the order's `amount_cents`, returning that balance to its pre-payment value"

    Design: Difficulty/compensating_invariant/supplier_cash_reversal_restores_pre_payment_balance
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier, purchase = setup_supplier_with_delivered_purchase(
        incident["id"], kitchen["id"]
    )
    assert get_incident_row(incident["id"])["spent_cents"] == 300_000

    transition_ingredient_purchase(purchase["id"], "PAID")
    assert get_incident_row(incident["id"])["spent_cents"] == 300_000

    transition_ingredient_purchase(
        purchase["id"], "DISPUTED", dispute_reason="QUANTITY_SHORTFALL"
    )
    assert get_incident_row(incident["id"])["spent_cents"] == 0
    assert get_supplier_row(incident["id"], supplier["id"])["cash_flow_received_cents"] == 0


def test_accountability_ratio_excludes_disputed_and_undelivered_orders(api):
    """PRD §3.8: "The local-sourcing numerator is the sum of `amount_cents` over
    the activation's sourcing orders in `DELIVERED` or `PAID` status; orders
    still in `REQUESTED` or `CONFIRMED`, and orders in `DISPUTED` or
    `CANCELLED`, are excluded, because money that has not reached a producer
    does not count as having reached the local economy."
    PRD §3.8: "The denominator is the sum of `final_cost_cents` over the
    activation's batches in `DELIVERED` status, and `delivered_meal_total` is
    the sum of `accepted_meals` over those same batches"

    Design: Corner/calculations/local_sourcing_ratio_excludes_disputed_and_undelivered_rows
    """
    incident, kitchen, run, order = setup_delivered_meal_order(
        ordered_meals=1000, produced_meals=1000, rejected_meals=40,
        quality_check_score=88,
    )
    supplier = create_supplier(incident["id"])
    paid = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"]
    )
    disputed = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="black beans", quantity_kg=1000, unit_price_cents_per_kg=500,
    )
    confirm_and_deliver_purchase(paid["id"])
    transition_ingredient_purchase(paid["id"], "PAID")
    confirm_and_deliver_purchase(disputed["id"])
    transition_ingredient_purchase(
        disputed["id"], "DISPUTED", dispute_reason="QUANTITY_SHORTFALL"
    )

    assert get_meal_order_row(order["id"])["final_cost_cents"] == 1_368_000
    report = get_accountability(incident["id"])
    # numerator 300000 over denominator 1368000 -> 21.93 -> 22
    assert report["local_sourcing_pct"] == 22
    assert report["cost_per_meal_cents"] == 1425
    assert report["delivered_meal_total"] == 960
    assert report["donor_report_flag"] == "BELOW_LOCAL_SOURCING_TARGET"
    assert get_supplier_row(incident["id"], supplier["id"])["cash_flow_received_cents"] == 300_000


def test_reliability_score_tracks_delivered_and_disputed_counts(api):
    """PRD §3.6: "The `reliability_score` is 50, plus 10 for each delivered
    order, minus 25 for each disputed order, clamped to the range 0 to 100 — so
    a producer with three settled deliveries and no disputes scores 80, and a
    producer with one delivery and one dispute scores 35."

    Design: Corner/calculations/supplier_reliability_thresholds_suspend_producer
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier = create_supplier(incident["id"])
    first = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"]
    )
    second = create_ingredient_purchase(
        incident["id"], supplier["id"], kitchen["id"],
        item_description="black beans", quantity_kg=500, unit_price_cents_per_kg=500,
    )
    confirm_and_deliver_purchase(first["id"])

    confirm_and_deliver_purchase(second["id"])
    two_delivered = get_supplier_row(incident["id"], supplier["id"])
    assert two_delivered["reliability_score"] == 70
    assert two_delivered["status"] == "APPROVED"

    transition_ingredient_purchase(
        second["id"], "DISPUTED", dispute_reason="QUANTITY_SHORTFALL"
    )
    after_dispute = get_supplier_row(incident["id"], supplier["id"])
    assert after_dispute["reliability_score"] == 35
    assert after_dispute["status"] == "SUSPENDED"


def test_a_settled_order_cannot_be_reconfirmed(api):
    """PRD §3.6: "The move from `CONFIRMED` to `DELIVERED` has no precondition
    beyond role and state"
    PRD §2.5: "Transition reachability — the entity named in the path is in a
    state whose outgoing transitions include the requested `to_state`"

    Design: Corner/calculations/supplier_reliability_thresholds_suspend_producer
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    supplier, purchase = setup_supplier_with_delivered_purchase(
        incident["id"], kitchen["id"]
    )
    refused = api_client.transition_ingredient_purchase(
        purchase["id"], {"to_state": "CONFIRMED"}, SOURCING
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert get_purchase_row(purchase["id"])["status"] == "DELIVERED"
