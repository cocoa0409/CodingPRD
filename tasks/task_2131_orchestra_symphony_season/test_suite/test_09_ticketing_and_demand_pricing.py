"""Single-ticket demand pricing, holds, payment and the concert version guard."""

from test_helpers import (
    BOX_OFFICE,
    ApiErrorId,
    assert_price_quote,
    build_on_sale_world,
    build_renewal_window_world,
    create_patron,
    create_patron_at_level,
    create_section,
    create_venue,
    current_concert_version,
    hold_tickets,
    inventory_for,
    pay_tickets,
    read_concert,
    read_patron,
    read_ticket_order,
    run_ops,
    validate_error,
    validate_paginated,
    validate_success,
)


def _quote(api, concert_id, section_id, seat_count=1, patron_id=None):
    params = {"seat_section_id": section_id, "seat_count": seat_count}
    if patron_id:
        params["patron_id"] = patron_id
    data = validate_success(api.get_price_quote(concert_id, BOX_OFFICE, params=params))
    assert_price_quote(data)
    return data


# --------------------------------------------------------------------------
# Demand band boundaries and the floor/ceiling clamp
# --------------------------------------------------------------------------
def test_empty_section_quotes_the_low_band_at_zero_fill(api):
    """PRD 3.7: "`fill_bp` is seats taken multiplied by 10,000, divided by the
    element's `capacity`, and truncated downward to a whole number of basis points;
    when no seats are taken it is 0."
    PRD 3.7: "The `demand_band` follows from `fill_bp` by inclusive thresholds
    evaluated from the top: at least 8000 basis points — eighty percent full — is
    `PEAK`; otherwise at least 5000 is `HIGH`; otherwise at least 2000 is
    `MODERATE`; otherwise `LOW`."
    PRD 3.7: "Each band carries a multiplier in basis points: `LOW` discounts to
    9000, `MODERATE` leaves the price alone at 10000, `HIGH` lifts it to 11500 and
    `PEAK` to 13000."

    Design: Difficulty/boundary_precision_check/demand_band_low_on_zero_taken_seats
    """
    world = build_on_sale_world()

    quote = _quote(api, world.concert["id"], world.section["id"])

    assert quote["fill_bp"] == 0
    assert quote["demand_band"] == "LOW"
    assert quote["unit_price_cents"] == 8100, "9000 raw unit taken to the 9000bp LOW band"


def test_price_quote_returns_the_whole_computed_read_contract(api):
    """PRD 3.7: "The response reports `unit_price_cents`, `demand_band`, `fill_bp`,
    `donor_discount_bp`, `seat_count` and `amount_due_cents`."
    PRD 3.7: "The **donor-adjusted price** is the demand-adjusted price multiplied
    by 10000 less the patron's donor discount, divided by 10,000, rounded half up;
    the discount in basis points is 0 for `NONE`, 250 for `FRIEND`, 500 for
    `SUSTAINER`, 1000 for `BENEFACTOR` and 1500 for `LAUREATE`, and it is 0
    whenever no patron is identified at all."

    Design: Difficulty/boundary_precision_check/demand_band_low_on_zero_taken_seats
    """
    world = build_on_sale_world()

    quote = _quote(api, world.concert["id"], world.section["id"], seat_count=1)

    assert quote["donor_discount_bp"] == 0, "no patron_id was supplied"
    assert quote["seat_count"] == 1
    assert quote["unit_price_cents"] == 8100
    assert quote["amount_due_cents"] == 8100

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["available_count"] == 100, "a quote never reserves anything"


def test_laureate_quote_is_lifted_back_up_to_the_price_floor(api):
    """PRD 3.7: "Finally the result is clamped against a floor and a ceiling derived
    from the raw unit and nothing else: the floor is the raw unit multiplied by
    8500, divided by 10,000, rounded half up — eighty-five percent of the section
    price — and the ceiling is the raw unit multiplied by 12000, divided by 10,000,
    rounded half up — one hundred and twenty percent of it."
    PRD 3.7: "The `unit_price_cents` charged is the donor-adjusted price raised to
    the floor if it fell below it, then lowered to the ceiling if it rose above it;
    the clamp is applied last, after every other step."

    Design: Difficulty/combinatorial_formula/single_ticket_price_floor_and_ceiling_clamps_bind
    """
    world = build_on_sale_world(
        section_specs=[{"name": "ORCHESTRA", "capacity": 100,
                        "price_multiplier_bp": 15000, "donor_priority_rank": 1,
                        "min_renewal_priority_score": 480}]
    )
    laureate = create_patron_at_level(
        "LAUREATE", full_name="Lena Ostrow", email="lena-floor@patron.test"
    )
    assert read_patron(laureate["id"])["donor_level"] == "LAUREATE"

    quote = _quote(api, world.concert["id"], world.section["id"],
                   patron_id=laureate["id"])

    assert quote["demand_band"] == "LOW"
    assert quote["donor_discount_bp"] == 1500
    assert quote["unit_price_cents"] == 7650, (
        "the LAUREATE price of 6885 is raised to 8500bp of the 9000 raw unit"
    )


def test_peak_band_quote_is_cut_down_to_the_price_ceiling(api):
    """PRD 3.7: "The **raw unit** is the season's `base_ticket_price_cents`
    multiplied by the section's `price_multiplier_bp`, divided by 10,000, rounded
    half up — the section multiplier is applied and rounded *first*, before
    anything else touches the number."
    PRD 3.7: "The `unit_price_cents` charged is the donor-adjusted price raised to
    the floor if it fell below it, then lowered to the ceiling if it rose above it;
    the clamp is applied last, after every other step."
    PRD 3.7: "The same arithmetic described above runs against the inventory **as
    it stands before this order's seats are held**, and its results are frozen onto
    the order as `quoted_unit_price_cents`, `amount_due_cents` and
    `demand_band_at_hold`; later demand movement never re-prices an existing hold."

    Design: Difficulty/combinatorial_formula/single_ticket_price_floor_and_ceiling_clamps_bind
    """
    world = build_on_sale_world(
        section_specs=[{"name": "ORCHESTRA", "capacity": 100,
                        "price_multiplier_bp": 15000, "donor_priority_rank": 1,
                        "min_renewal_priority_score": 480}]
    )
    buyer = create_patron(full_name="Noel Vance", email="noel-ceiling@patron.test")

    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"],
                         seat_count=80)
    assert order["quoted_unit_price_cents"] == 8100, "priced against the empty section"
    assert order["amount_due_cents"] == 648000
    assert order["demand_band_at_hold"] == "LOW"

    quote = _quote(api, world.concert["id"], world.section["id"], seat_count=2,
                   patron_id=buyer["id"])
    assert quote["fill_bp"] == 8000
    assert quote["demand_band"] == "PEAK"
    assert quote["unit_price_cents"] == 10800, (
        "the PEAK price of 11700 is cut to 12000bp of the 9000 raw unit"
    )


def test_seventy_nine_seats_taken_stays_one_notch_below_the_peak_boundary(api):
    """PRD 3.7: "The `demand_band` follows from `fill_bp` by inclusive thresholds
    evaluated from the top: at least 8000 basis points — eighty percent full — is
    `PEAK`; otherwise at least 5000 is `HIGH`; otherwise at least 2000 is
    `MODERATE`; otherwise `LOW`."
    PRD 3.7: "The **demand-adjusted price** is that raw unit multiplied by the
    band's multiplier, divided by 10,000, rounded half up."

    Design: Corner/calculations/demand_band_high_one_seat_below_the_peak_boundary
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-high@patron.test")

    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"],
                         seat_count=79)

    quote = _quote(api, world.concert["id"], world.section["id"])
    assert quote["fill_bp"] == 7900
    assert quote["demand_band"] == "HIGH"
    assert quote["unit_price_cents"] == 10350, "9000 raw unit at the 11500bp HIGH band"

    assert read_ticket_order(order["id"])["quoted_unit_price_cents"] == 8100, (
        "the hold was priced from the empty section and then frozen"
    )
    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["available_count"] == 21


def test_expired_hold_leaves_the_pricing_input_set(api):
    """PRD 2.9: "Orders in `EXPIRED` or `REFUNDED` status and packages in `LAPSED`
    status contribute nothing to either count."
    PRD 3.7: "The inputs are exactly one inventory element — the one whose
    `seat_section_id` matches the requested section on the requested concert —
    together with the season's `base_ticket_price_cents`, the section's
    `price_multiplier_bp`, and optionally the patron's `donor_level`."
    PRD 2.13: "A held order becomes expired at the first checkpoint whose new epoch
    value has reached or passed that stamp."

    Design: Corner/calculations/expired_hold_is_excluded_from_the_fill_input_set
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-expire@patron.test")
    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"],
                         seat_count=30)

    before = _quote(api, world.concert["id"], world.section["id"])
    assert before["fill_bp"] == 3000
    assert before["demand_band"] == "MODERATE"
    assert before["unit_price_cents"] == 9000

    run_ops(world.season["id"])
    run_ops(world.season["id"])

    assert read_ticket_order(order["id"])["status"] == "EXPIRED"
    after = _quote(api, world.concert["id"], world.section["id"])
    assert after["fill_bp"] == 0
    assert after["demand_band"] == "LOW"
    assert after["unit_price_cents"] == 8100


# --------------------------------------------------------------------------
# Holding and paying
# --------------------------------------------------------------------------
def test_a_well_formed_hold_freezes_its_price_and_epoch_stamp(api):
    """PRD 3.7: "The same arithmetic described above runs against the inventory **as
    it stands before this order's seats are held**, and its results are frozen onto
    the order as `quoted_unit_price_cents`, `amount_due_cents` and
    `demand_band_at_hold`; later demand movement never re-prices an existing hold."
    PRD 3.7: "The order's `hold_expires_at_ops_run` is set to the season's current
    `ops_run_index` plus 2, and the concert's `version` is incremented by one —
    which is precisely what makes a second hold created from the same observed
    version fail the concurrency check."
    PRD 2.9: "`available_count` is the element's `capacity` less its `held_count`
    less its `sold_count`."

    Design: Corner/validations/valid_ticket_order_passes_every_check
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-valid@patron.test")

    response = api.create_ticket_order(
        {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 2,
            "expected_concert_version": current_concert_version(world.concert["id"]),
        },
        BOX_OFFICE,
    )
    order = validate_success(response, 201)

    assert order["status"] == "HELD"
    assert order["quoted_unit_price_cents"] == 8100
    assert order["amount_due_cents"] == 16200
    assert order["demand_band_at_hold"] == "LOW"
    assert order["hold_expires_at_ops_run"] == 2

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 2
    assert element["available_count"] == 98


def test_paying_an_already_paid_order_is_refused(api):
    """PRD 3.7: "It requires the order to be in `HELD`, else
    `ERR_TICKET_ORDER_NOT_HELD`, and it requires the concert's
    `performance_status` to still be `SCHEDULED` — an order against a cancelled
    concert cannot be paid and is refused with `ERR_CONCERT_ALREADY_CANCELLED`."
    PRD 3.7: "On the inventory element the seats move from `held_count` to
    `sold_count`, and `fill_bp`, `demand_band`, `seats_held_count` and
    `seats_sold_count` are all recomputed."

    Design: Corner/state_machines/pay_ticket_order_twice_returns_not_held
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-paid@patron.test")
    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"])
    pay_tickets(order["id"])

    response = api.pay_ticket_order(order["id"], BOX_OFFICE, use_credit=False)
    validate_error(response, ApiErrorId.ERR_TICKET_ORDER_NOT_HELD.value, 409)

    settled = read_ticket_order(order["id"])
    assert settled["status"] == "PAID"
    assert settled["amount_paid_cents"] == 8100
    assert read_patron(buyer["id"])["lifetime_cash_in_cents"] == 8100

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["sold_count"] == 1
    assert element["available_count"] == 99


def test_section_from_another_hall_is_refused(api):
    """PRD 3.7: "The chosen section must belong to the concert's hall, else
    `ERR_SEAT_SECTION_VENUE_MISMATCH`, and the element's `available_count` must be
    at least `seat_count`, else `ERR_INSUFFICIENT_SEATS`."

    Design: Corner/validations/ticket_order_with_section_from_another_venue_returns_venue_mismatch
    """
    world = build_on_sale_world()
    other_hall = create_venue(name="Studio B")
    foreign_section = create_section(other_hall["id"], name="STUDIO", capacity=40,
                                     price_multiplier_bp=9000, donor_priority_rank=5)
    buyer = create_patron(full_name="Noel Vance", email="noel-hall@patron.test")

    response = api.create_ticket_order(
        {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": foreign_section["id"],
            "seat_count": 1,
            "expected_concert_version": current_concert_version(world.concert["id"]),
        },
        BOX_OFFICE,
    )
    validate_error(response, ApiErrorId.ERR_SEAT_SECTION_VENUE_MISMATCH.value, 422)

    concert = read_concert(world.concert["id"])
    assert len(concert["section_inventory"]) == 1
    assert concert["section_inventory"][0]["seat_section_id"] == world.section["id"]

    _, meta = validate_paginated(
        api.list_ticket_orders(BOX_OFFICE, params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 0


def test_asking_for_more_seats_than_the_section_holds_is_refused(api):
    """PRD 2.6: "**Seat availability.** For every concert affected, the
    `available_count` on the relevant section inventory element must be at least
    the number of seats being claimed — `seat_count` for a ticket order, and
    `seat_count` on every concert of a package. A shortfall yields
    `ERR_INSUFFICIENT_SEATS` with HTTP 409."

    Design: Corner/validations/ticket_order_over_section_capacity_returns_insufficient_seats
    """
    world = build_on_sale_world(
        section_specs=[{"name": "ORCHESTRA", "capacity": 10,
                        "price_multiplier_bp": 15000, "donor_priority_rank": 1}]
    )
    buyer = create_patron(full_name="Noel Vance", email="noel-cap@patron.test")

    response = api.create_ticket_order(
        {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 11,
            "expected_concert_version": current_concert_version(world.concert["id"]),
        },
        BOX_OFFICE,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SEATS.value, 409)

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["available_count"] == 10
    assert element["held_count"] == 0


# --------------------------------------------------------------------------
# Ladder precedence: sale state outranks capacity
# --------------------------------------------------------------------------
def test_premature_ticket_order_reports_the_sale_state_not_the_capacity(api):
    """PRD 3.7: "The concert's `sale_status` must be `PUBLIC_ONSALE`; a concert not
    yet or no longer publicly on sale is refused with `ERR_CONCERT_NOT_ON_SALE`."
    PRD 2.6: "Availability is the **last** thing checked, so a request that is both
    unaffordable in seats and defective in some earlier respect always reports the
    earlier defect."

    Design: Difficulty/priority_pair_validation_conflict/ticket_order_sale_state_beats_seat_capacity
    """
    world = build_renewal_window_world()
    assert world.concert["sale_status"] == "RENEWAL_ONLY"
    buyer = create_patron(full_name="Noel Vance", email="noel-early@patron.test")

    response = api.create_ticket_order(
        {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 999,
            "expected_concert_version": current_concert_version(world.concert["id"]),
        },
        BOX_OFFICE,
    )
    error = validate_error(response, ApiErrorId.ERR_CONCERT_NOT_ON_SALE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SEATS.value, (
        "999 seats in a 100-seat section also breaks the last rung, which never runs"
    )


def test_refused_premature_ticket_order_holds_nothing(api):
    """PRD 2.6: "Every write request is evaluated against a fixed ladder of checks,
    and the ladder is strictly ordered: the first check that fails determines the
    response, and no later check is evaluated."
    PRD 2.9: "The conserved quantity that follows is simple and absolute: for every
    inventory element, `capacity` always equals `available_count` plus `held_count`
    plus `sold_count`."

    Design: Difficulty/priority_pair_validation_conflict/ticket_order_sale_state_beats_seat_capacity
    """
    world = build_renewal_window_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-early2@patron.test")

    validate_error(
        api.create_ticket_order(
            {
                "concert_id": world.concert["id"],
                "patron_id": buyer["id"],
                "seat_section_id": world.section["id"],
                "seat_count": 999,
                "expected_concert_version": current_concert_version(
                    world.concert["id"]
                ),
            },
            BOX_OFFICE,
        ),
        ApiErrorId.ERR_CONCERT_NOT_ON_SALE.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_ticket_orders(BOX_OFFICE, params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 0

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 0
    assert element["available_count"] == 100


# --------------------------------------------------------------------------
# Optimistic concurrency on the concert
# --------------------------------------------------------------------------
def test_second_hold_from_a_stale_concert_version_is_rejected(api):
    """PRD 2.12: "If that value does not equal the concert's current `version`, the
    request is rejected with `ERR_STALE_CONCERT_VERSION` and HTTP 412."
    PRD 2.12: "A second hold on the same concert is an ordinary product operation,
    so nothing else would reject it."
    PRD 3.7: "The order's `hold_expires_at_ops_run` is set to the season's current
    `ops_run_index` plus 2, and the concert's `version` is incremented by one —
    which is precisely what makes a second hold created from the same observed
    version fail the concurrency check."

    Design: Corner/cross_cutting_layers/occ_stale_concert_version_on_second_hold_returns_412
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-occ@patron.test")
    observed_version = current_concert_version(world.concert["id"])

    def order_payload(version):
        return {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 1,
            "expected_concert_version": version,
        }

    validate_success(
        api.create_ticket_order(order_payload(observed_version), BOX_OFFICE), 201
    )

    stale = api.create_ticket_order(order_payload(observed_version), BOX_OFFICE)
    validate_error(stale, ApiErrorId.ERR_STALE_CONCERT_VERSION.value, 412)

    refreshed_version = current_concert_version(world.concert["id"])
    assert refreshed_version == observed_version + 1

    retried = validate_success(
        api.create_ticket_order(order_payload(refreshed_version), BOX_OFFICE), 201
    )
    assert retried["status"] == "HELD"

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 2, "only the two accepted holds took seats"

    _, meta = validate_paginated(
        api.list_ticket_orders(BOX_OFFICE, params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 2
