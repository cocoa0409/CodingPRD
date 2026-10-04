"""Delivery schedule negotiation and delay compensation (PRD §2.7, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_customer_headers,
    api_client,
    create_delivery_negotiation_payload, counter_negotiation_payload,
    create_program, create_customer, add_aircraft, setup_aircraft,
    setup_negotiation, counter_negotiation, drive_negotiation_to_round,
    assert_delivery_negotiation,
)


def test_goodwill_variant_with_watch_customer_rejected(api, delivery_manager_headers):
    """PRD §3.9: "`GOODWILL` pays a flat base of 1000000 cents plus 100000 cents per day
    late with no cap, and it is reserved for customers whose `credit_standing` is `GOOD`:
    proposing or countering in the `GOODWILL` variant for a customer of any other standing
    is rejected with `ERR_GOODWILL_REQUIRES_GOOD_CREDIT` (HTTP 422)."

    Design: Corner/validations/goodwill_variant_with_watch_customer_rejected
    """
    program = create_program()
    customer = create_customer(airline_code="AL2", name="Air Two", credit_standing="WATCH")
    aircraft = add_aircraft(program["id"], customer["id"], line_number=1014)
    resp = api_client.create_delivery_negotiation(
        aircraft["id"],
        create_delivery_negotiation_payload(
            proposed_delivery_date="2026-10-11", compensation_variant="GOODWILL"
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GOODWILL_REQUIRES_GOOD_CREDIT)


def test_negotiation_wrong_turn_rejected(api, delivery_manager_headers):
    """PRD §3.9: "Countering is strictly turn-taking. A `PROPOSED` negotiation awaits the
    `Customer`; a `COUNTERED` one awaits the `DeliveryManager`; a move by the wrong side is
    rejected `ERR_NEGOTIATION_ACTOR_TURN` (HTTP 403)."

    Design: Corner/validations/negotiation_wrong_turn_rejected
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1017)
    negotiation = setup_negotiation(aircraft["id"])
    assert negotiation["status"] == "PROPOSED"
    # PROPOSED awaits the Customer; the DeliveryManager's turn is not yet — even with a
    # fresh OCC version.
    resp = api_client.counter_negotiation(
        negotiation["id"],
        counter_negotiation_payload(
            negotiation["version"], proposed_delivery_date="2026-10-12"
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ACTOR_TURN)


def test_negotiation_round_limit_auto_expires(api, delivery_manager_headers):
    """PRD §3.9: "The negotiation allows at most six rounds: a counter attempted when
    `round_number` is already 6 is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422),
    does not advance the round, and the attempt itself pushes the negotiation into
    `EXPIRED`."

    Design: Corner/validations/negotiation_round_limit_auto_expires
    """
    _program, customer, aircraft = setup_aircraft(line_number=1018)
    negotiation = setup_negotiation(aircraft["id"], proposed_delivery_date="2026-10-11")
    negotiation = drive_negotiation_to_round(negotiation, customer["id"], target_round=6)
    assert negotiation["round_number"] == 6, "five legal counters advanced rounds 1 -> 6"
    assert negotiation["status"] == "COUNTERED", "round 6 awaits the DeliveryManager"

    resp = api_client.counter_negotiation(
        negotiation["id"],
        counter_negotiation_payload(
            negotiation["version"], proposed_delivery_date="2026-10-17"
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)

    negotiations, _meta = validate_paginated(
        api_client.list_delivery_negotiations(aircraft["id"], delivery_manager_headers)
    )
    assert negotiations[0]["status"] == "EXPIRED", "the rejected attempt itself expires the negotiation"
    assert negotiations[0]["round_number"] == 6, "the round does not advance"


def test_negotiation_agree_twice_rejected(api, admin_headers):
    """PRD §3.9: "Agreement writes the standing `proposed_delivery_date` onto the aircraft's
    `scheduled_delivery_date` and locks `compensation_cents` at its current value. `AGREED`
    and `EXPIRED` are both terminal — and recall from §3.8 that a failed flight test expires
    every live negotiation of the aircraft outright."
    PRD §3.9: "Agreement ends the game in the responder's hands: the `Customer` agrees to a
    standing airframer proposal (`PROPOSED` → `AGREED`), or the `DeliveryManager` agrees to
    a customer counter (`COUNTERED` → `AGREED`), under the same turn rule."

    Design: Corner/state_machines/negotiation_agree_twice_rejected
    """
    _program, customer, aircraft = setup_aircraft(line_number=1008)
    negotiation = setup_negotiation(aircraft["id"], proposed_delivery_date="2026-10-11")

    negotiation = validate_success(
        api_client.agree_negotiation(
            negotiation["id"], make_customer_headers(customer["id"])
        )
    )
    assert negotiation["status"] == "AGREED"
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], admin_headers))
    assert aircraft["scheduled_delivery_date"] == "2026-10-11"

    resp = api_client.agree_negotiation(
        negotiation["id"], make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], admin_headers))
    assert aircraft["scheduled_delivery_date"] == "2026-10-11", (
        "the rejected second agree changes nothing"
    )


def test_occ_negotiation_counter_with_stale_version(api, delivery_manager_headers):
    """PRD §2.7: "Countering a delivery negotiation requires
    `expected_negotiation_version` equal to the negotiation's current `version`. A mismatch
    is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because the other party may
    have moved the negotiation to a new round with a new date and compensation basis that
    the current writer has not observed."
    PRD §3.9: "The counter payload carries a fresh `proposed_delivery_date`, a fresh
    `compensation_variant`, and `expected_negotiation_version`; per §2.7 the staleness check
    fires right after the negotiation loads and before the turn and business checks,
    rejecting a stale base with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_negotiation_counter_with_stale_version
    """
    _program, customer, aircraft = setup_aircraft(line_number=1026)
    negotiation = setup_negotiation(aircraft["id"], proposed_delivery_date="2026-10-11")
    stale_version = negotiation["version"]
    negotiation = counter_negotiation(
        negotiation, customer["id"], proposed_delivery_date="2026-10-12"
    )
    assert negotiation["status"] == "COUNTERED"
    assert negotiation["round_number"] == 2
    assert negotiation["version"] == stale_version + 1

    # COUNTERED awaits the DeliveryManager, so the turn would be legal — only the stale
    # version (rung 4) can fire, ahead of every state and business check.
    resp = api_client.counter_negotiation(
        negotiation["id"],
        counter_negotiation_payload(
            stale_version, proposed_delivery_date="2026-10-13"
        ),
        delivery_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    negotiations, _meta = validate_paginated(
        api_client.list_delivery_negotiations(aircraft["id"], delivery_manager_headers)
    )
    assert negotiations[0]["status"] == "COUNTERED"
    assert negotiations[0]["round_number"] == 2


def test_contractual_compensation_cap_binds_at_ten_percent_of_price(api, delivery_manager_headers):
    """PRD §3.9: "`CONTRACTUAL_LIQUIDATED` pays 250000 cents per day late, capped at ten
    percent of the aircraft's `contract_price_cents` with the cap itself rounded half-up to
    integer cents — the compensation is the smaller of the per-diem total and the cap."
    PRD §3.9: "`days_late` is the whole-day difference between the `proposed_delivery_date`
    and the aircraft's `contracted_delivery_date`, floored at zero, so an on-time or early
    proposal carries no penalty."

    Design: Corner/calculations/contractual_compensation_cap_binds_at_ten_percent_of_price
    """
    program = create_program()
    customer = create_customer()
    aircraft = add_aircraft(
        program["id"], customer["id"], line_number=1013,
        contract_price_cents=10000000,
    )
    negotiation = validate_success(
        api_client.create_delivery_negotiation(
            aircraft["id"],
            create_delivery_negotiation_payload(
                proposed_delivery_date="2026-10-11",
                compensation_variant="CONTRACTUAL_LIQUIDATED",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    assert_delivery_negotiation(negotiation)
    assert negotiation["days_late"] == 10
    # per-diem 10 x 250000 = 2500000 exceeds the cap round(0.10 x 10000000) = 1000000.
    assert negotiation["compensation_cents"] == 1000000


def test_delay_compensation_contractual_capped_vs_goodwill_uncapped(api, delivery_manager_headers):
    """PRD §3.9: "`CONTRACTUAL_LIQUIDATED` pays 250000 cents per day late, capped at ten
    percent of the aircraft's `contract_price_cents` with the cap itself rounded half-up to
    integer cents — the compensation is the smaller of the per-diem total and the cap.
    `GOODWILL` pays a flat base of 1000000 cents plus 100000 cents per day late with no cap"
    PRD §3.9: "`days_late` is the whole-day difference between the `proposed_delivery_date`
    and the aircraft's `contracted_delivery_date`, floored at zero, so an on-time or early
    proposal carries no penalty."

    Design: Difficulty/dual_variant_calc/delay_compensation_contractual_capped_vs_goodwill_uncapped
    """
    program = create_program()
    customer = create_customer()  # GOOD standing: both variants are legal for it
    aircraft_one = add_aircraft(program["id"], customer["id"], line_number=1001)
    aircraft_two = add_aircraft(program["id"], customer["id"], line_number=1002)

    contractual = validate_success(
        api_client.create_delivery_negotiation(
            aircraft_one["id"],
            create_delivery_negotiation_payload(
                proposed_delivery_date="2026-10-21",
                compensation_variant="CONTRACTUAL_LIQUIDATED",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    goodwill = validate_success(
        api_client.create_delivery_negotiation(
            aircraft_two["id"],
            create_delivery_negotiation_payload(
                proposed_delivery_date="2026-10-21", compensation_variant="GOODWILL"
            ),
            delivery_manager_headers,
        ),
        201,
    )
    assert contractual["days_late"] == 20
    assert goodwill["days_late"] == 20
    # Contractual: 20 x 250000 = 5000000, cap round(0.10 x 5000000000) = 500000000 loose.
    assert contractual["compensation_cents"] == 5000000
    # Goodwill: 1000000 + 20 x 100000 = 3000000, uncapped.
    assert goodwill["compensation_cents"] == 3000000
    assert contractual["compensation_cents"] - goodwill["compensation_cents"] == 2000000


def test_delay_compensation_variants_diverge_on_zero_days_late(api, delivery_manager_headers):
    """PRD §3.9: "`days_late` is the whole-day difference between the
    `proposed_delivery_date` and the aircraft's `contracted_delivery_date`, floored at zero,
    so an on-time or early proposal carries no penalty."
    PRD §3.9: "`GOODWILL` pays a flat base of 1000000 cents plus 100000 cents per day late
    with no cap"

    Design: Difficulty/dual_variant_calc/delay_compensation_contractual_capped_vs_goodwill_uncapped
    """
    program = create_program()
    customer = create_customer()
    aircraft_one = add_aircraft(program["id"], customer["id"], line_number=1003)
    aircraft_two = add_aircraft(program["id"], customer["id"], line_number=1004)

    contractual = validate_success(
        api_client.create_delivery_negotiation(
            aircraft_one["id"],
            create_delivery_negotiation_payload(
                proposed_delivery_date="2026-09-20",
                compensation_variant="CONTRACTUAL_LIQUIDATED",
            ),
            delivery_manager_headers,
        ),
        201,
    )
    goodwill = validate_success(
        api_client.create_delivery_negotiation(
            aircraft_two["id"],
            create_delivery_negotiation_payload(
                proposed_delivery_date="2026-09-20", compensation_variant="GOODWILL"
            ),
            delivery_manager_headers,
        ),
        201,
    )
    # Proposal before the contracted 2026-10-01: days_late floors at zero.
    assert contractual["days_late"] == 0
    assert goodwill["days_late"] == 0
    assert contractual["compensation_cents"] == 0, "no penalty for an early proposal"
    assert goodwill["compensation_cents"] == 1000000, "the flat base stands at zero days late"


def test_negotiation_counter_rounds_cycle_and_reprice(api):
    """PRD §3.9: "A successful counter replaces the standing date and variant, recomputes
    `days_late` and `compensation_cents`, increments `round_number` by one, and advances the
    negotiation's `version` — which is exactly what leaves the other party's next counter
    stale unless it re-reads."
    PRD §3.9: "`CONTRACTUAL_LIQUIDATED` pays 250000 cents per day late, capped at ten
    percent of the aircraft's `contract_price_cents` with the cap itself rounded half-up to
    integer cents — the compensation is the smaller of the per-diem total and the cap.
    `GOODWILL` pays a flat base of 1000000 cents plus 100000 cents per day late with no cap"

    Design: Difficulty/non_linear_state_machine/negotiation_counter_rounds_cycle_and_reprice
    """
    _program, customer, aircraft = setup_aircraft(line_number=3001)
    negotiation = setup_negotiation(
        aircraft["id"],
        proposed_delivery_date="2026-10-11",
        compensation_variant="CONTRACTUAL_LIQUIDATED",
    )
    assert negotiation["status"] == "PROPOSED"
    assert negotiation["round_number"] == 1
    # 10 days late, contractual: 10 x 250000 = 2500000 (cap 500000000 not binding).
    assert negotiation["compensation_cents"] == 2500000

    negotiation = counter_negotiation(
        negotiation, customer["id"],
        proposed_delivery_date="2026-10-06", compensation_variant="GOODWILL",
    )
    assert negotiation["status"] == "COUNTERED"
    assert negotiation["round_number"] == 2
    # 5 days late, goodwill: 1000000 + 5 x 100000 = 1500000.
    assert negotiation["compensation_cents"] == 1500000

    negotiation = counter_negotiation(
        negotiation, customer["id"],
        proposed_delivery_date="2026-10-21",
        compensation_variant="CONTRACTUAL_LIQUIDATED",
    )
    assert negotiation["status"] == "PROPOSED", "COUNTERED -> PROPOSED on the airframer counter"
    assert negotiation["round_number"] == 3
    # 20 days late, contractual: 20 x 250000 = 5000000.
    assert negotiation["compensation_cents"] == 5000000


def test_negotiation_counter_alternates_turns_and_advances_version(api):
    """PRD §3.9: "A `PROPOSED` negotiation awaits the `Customer`; a `COUNTERED` one awaits
    the `DeliveryManager`; a move by the wrong side is rejected `ERR_NEGOTIATION_ACTOR_TURN`
    (HTTP 403)."
    PRD §3.9: "A successful counter replaces the standing date and variant, recomputes
    `days_late` and `compensation_cents`, increments `round_number` by one, and advances the
    negotiation's `version` — which is exactly what leaves the other party's next counter
    stale unless it re-reads."

    Design: Difficulty/non_linear_state_machine/negotiation_counter_rounds_cycle_and_reprice
    """
    _program, customer, aircraft = setup_aircraft(line_number=3010)
    negotiation = setup_negotiation(aircraft["id"], proposed_delivery_date="2026-10-11")
    assert negotiation["status"] == "PROPOSED"
    first_version = negotiation["version"]

    negotiation = counter_negotiation(
        negotiation, customer["id"], proposed_delivery_date="2026-10-12"
    )
    assert negotiation["status"] == "COUNTERED"
    assert negotiation["round_number"] == 2
    assert negotiation["version"] == first_version + 1

    negotiation = counter_negotiation(
        negotiation, customer["id"], proposed_delivery_date="2026-10-13"
    )
    assert negotiation["status"] == "PROPOSED"
    assert negotiation["round_number"] == 3
    assert negotiation["version"] == first_version + 2
