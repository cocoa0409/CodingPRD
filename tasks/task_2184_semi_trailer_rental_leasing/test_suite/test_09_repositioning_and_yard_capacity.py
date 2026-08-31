"""Repositioning the fleet: move cost under both variants, the closed inbound
capacity window, and the conservation identity across dispatch and abort."""


from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    add_branch,
    add_east_branch,
    add_trailer,
    make_branch_manager_headers,
    read_branch,
    read_relocation_order,
    read_trailer,
    relocation_order_payload,
    setup_pending_chargeback,
    setup_reference_data,
    setup_relocation_approved,
    setup_relocation_in_transit,
    setup_relocation_requested,
    setup_agreement_active,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]

_TWENTY_FIVE_POINT_ITEMS = [
    {"severity": "MODERATE", "quantity": 2, "unit_cost_cents": 30000,
     "description": "roof panel"},
    {"severity": "MINOR", "quantity": 3, "unit_cost_cents": 10000,
     "description": "scuff"},
]


def test_a_short_move_is_priced_at_the_minimum_charge(api):
    """PRD §3.9: "The cost is finally floored: it is whichever is greater, 40000
    cents or the subtotal plus the surcharge."
    PRD §3.9: "A subtotal is formed by adding a flat base dispatch fee of 15000
    cents to that mileage charge and then adding the deadhead distance multiplied
    by 130 cents per mile."

    Design: Corner/calculations/relocation_minimum_charge_floor_applies_on_short_move
    """
    ctx = setup_reference_data()
    add_east_branch(ctx)

    order = validate_success(
        api.create_relocation_order(
            relocation_order_payload(ctx["trailer_id"], ctx["east_branch_id"],
                                     planned_depart_date="2026-09-03",
                                     planned_arrive_date="2026-09-04",
                                     planned_miles=50),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    assert order["estimated_cost_cents"] == 40000, (
        "15000 dispatch plus 13000 of band cost is 28000, below the floor"
    )
    assert order["origin_branch_id"] == ctx["branch_id"]
    assert order["status"] == "REQUESTED"
    assert order.get("actual_cost_cents") is None


def test_the_fuel_surcharge_trigger_is_strictly_above_five_hundred_miles(api):
    """PRD §3.9: "A fuel surcharge of seven percent of that subtotal, rounded
    half-up to whole cents, is added when — and only when — the loaded miles plus
    the deadhead miles is strictly greater than 500; the threshold is strict, so
    exactly 500 combined miles attracts no surcharge and 501 does."
    PRD §3.9: "The mileage charge is a marginal waterfall, not an average rate: the
    first 250 miles are charged at 260 cents per mile; miles beyond 250 and up to
    600 are charged at 215 cents per mile; and miles beyond 600 are charged at 185
    cents per mile."

    Design: Corner/calculations/relocation_fuel_surcharge_strictly_above_500_combined_miles
    """
    ctx = setup_reference_data()
    add_east_branch(ctx)
    second = add_trailer(ctx, "second", unit_number="T-1002", hub_miles=52000)

    at_threshold = validate_success(
        api.create_relocation_order(
            relocation_order_payload(ctx["trailer_id"], ctx["east_branch_id"],
                                     planned_depart_date="2026-09-03",
                                     planned_arrive_date="2026-09-05",
                                     planned_miles=500),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    over_threshold = validate_success(
        api.create_relocation_order(
            relocation_order_payload(second["id"], ctx["east_branch_id"],
                                     planned_depart_date="2026-09-03",
                                     planned_arrive_date="2026-09-05",
                                     planned_miles=501),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )

    assert at_threshold["estimated_cost_cents"] == 133750, "500 miles attracts no surcharge"
    assert over_threshold["estimated_cost_cents"] == 143343, "501 miles adds 9378 of surcharge"
    assert over_threshold["estimated_cost_cents"] - at_threshold["estimated_cost_cents"] == 9593
    assert at_threshold["planned_miles"] == 500
    assert over_threshold["planned_miles"] == 501


def test_the_actual_move_cost_diverges_from_the_planned_estimate(api):
    """PRD §3.9: "The **estimated planned** variant runs at order creation and
    writes `estimated_cost_cents`. It prices `planned_miles` as the loaded distance
    and treats the deadhead distance as 0, and the number it writes is never
    revised afterwards."
    PRD §3.9: "Because deadhead counts toward the surcharge threshold as well as
    toward the subtotal, an actual move can cross the 500-mile surcharge threshold
    even when its loaded miles alone would not, so the actual cost can exceed the
    estimate by more than the loaded-mileage difference alone would suggest."

    Design: Corner/cross_cutting_complexity_layers/relocation_estimated_and_actual_cost_variants_diverge
    """
    scn = setup_relocation_in_transit()
    assert scn["order_estimate"] == 118700

    order = validate_success(
        api.complete_relocation_order(
            scn["order_id"],
            {"actual_miles": 520, "deadhead_miles": 45,
             "actual_arrive_date": "2026-09-13"},
            make_branch_manager_headers(scn["east_branch_id"]),
        )
    )
    assert order["status"] == "COMPLETED"
    assert order["actual_cost_cents"] == 153973
    assert order["actual_cost_cents"] != scn["order_estimate"]

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["current_branch_id"] == scn["east_branch_id"]
    assert trailer["availability_status"] == "AVAILABLE"
    assert read_branch(scn["east_branch_id"])["on_hand_count"] == 1
    assert read_branch(scn["branch_id"])["on_hand_count"] == 0


def test_a_rejected_move_can_never_be_dispatched(api):
    """PRD §3.9: "Putting the unit on the road moves the order `APPROVED →
    IN_TRANSIT`; an order in any other status is rejected with
    `ERR_RELOCATION_NOT_APPROVED`."
    PRD §3.9: "Refusing the move instead records the supplied `reason` into
    `reject_reason` and moves the order `REQUESTED → REJECTED`, under the same
    `ERR_RELOCATION_NOT_REQUESTED` guard; a rejection touches no trailer and no
    yard counter, and increments the order's `version` by 1."

    Design: Corner/state_machines/rejected_relocation_is_terminal_and_cannot_dispatch
    """
    scn = setup_relocation_requested()

    rejected = validate_success(
        api.reject_relocation_order(
            scn["order_id"], {"reason": "no space in the receiving yard"},
            make_branch_manager_headers(scn["east_branch_id"]),
        )
    )
    assert rejected["status"] == "REJECTED"

    response = api.dispatch_relocation_order(scn["order_id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_RELOCATION_NOT_APPROVED.value)

    stored = read_relocation_order(scn["order_id"])
    assert stored["reject_reason"] == "no space in the receiving yard"
    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"
    assert read_branch(scn["branch_id"])["on_hand_count"] == 1


def test_approving_an_already_approved_move_is_rejected(api):
    """PRD §3.9: "Approval moves the order `REQUESTED → APPROVED`; an order in any
    other status is rejected with `ERR_RELOCATION_NOT_REQUESTED`, and a
    `BranchManager` caller whose `X-User-ID` is not the order's
    `destination_branch_id` is rejected with `ERR_NOT_RESOURCE_OWNER` — only the
    yard being asked to absorb the unit may accept it."

    Design: Corner/errors/approve_an_already_approved_relocation_reports_not_requested
    """
    scn = setup_relocation_approved()
    version_after_approval = scn["order"]["version"]

    response = api.approve_relocation_order(
        scn["order_id"], make_branch_manager_headers(scn["east_branch_id"])
    )
    validate_error(response, ApiErrorId.ERR_RELOCATION_NOT_REQUESTED.value)

    stored = read_relocation_order(scn["order_id"])
    assert stored["status"] == "APPROVED"
    assert stored["version"] == version_after_approval


def test_completing_a_move_that_was_never_dispatched_is_rejected(api):
    """PRD §3.9: "Landing the unit moves the order `IN_TRANSIT → COMPLETED`; an
    order in any other status is rejected with `ERR_RELOCATION_NOT_IN_TRANSIT`."

    Design: Corner/errors/complete_an_approved_relocation_reports_not_in_transit
    """
    scn = setup_relocation_approved()

    response = api.complete_relocation_order(
        scn["order_id"],
        {"actual_miles": 520, "deadhead_miles": 45, "actual_arrive_date": "2026-09-13"},
        make_branch_manager_headers(scn["east_branch_id"]),
    )
    validate_error(response, ApiErrorId.ERR_RELOCATION_NOT_IN_TRANSIT.value)

    stored = read_relocation_order(scn["order_id"])
    assert stored["status"] == "APPROVED"
    assert stored.get("actual_cost_cents") is None
    assert read_trailer(scn["trailer_id"])["current_branch_id"] == scn["branch_id"]
    assert read_branch(scn["branch_id"])["on_hand_count"] == 1


def _out_of_service_unit_named_against_its_own_yard():
    """A unit driven out of service by damage while still standing at the yard a
    caller then names as the destination of a move."""
    scn = setup_pending_chargeback(line_items=_TWENTY_FIVE_POINT_ITEMS)
    assert read_trailer(scn["trailer_id"])["service_status"] == "OOS_DAMAGE"
    return scn


def test_the_in_service_check_outranks_the_destination_yard_check(api):
    """PRD §2.9: "Domain rules, in this relative order: the named trailer being in
    service (`ERR_TRAILER_OUT_OF_SERVICE`); the named trailer's federal inspection
    outlasting the contract (`ERR_DOT_INSPECTION_EXPIRED`); a qualifying
    certificate of insurance existing (`ERR_INSURANCE_INVALID`); that certificate
    carrying a sufficient limit (`ERR_INSURANCE_LIMIT_INSUFFICIENT`); the trailer's
    occupancy window being free (`ERR_TRAILER_WINDOW_CONFLICT`); the destination
    yard having inbound room (`ERR_BRANCH_YARD_CAPACITY_EXCEEDED`); the trailer
    standing at the expected yard (`ERR_TRAILER_BRANCH_MISMATCH`); the trailer's
    availability being acceptable for the operation (`ERR_TRAILER_NOT_AVAILABLE`);
    the candidate pool being adequate (`ERR_NO_ELIGIBLE_TRAILER` or
    `ERR_INSUFFICIENT_AVAILABILITY`); the lessee's outstanding balance being within
    its limit (`ERR_CREDIT_LIMIT_EXCEEDED`); and the lessee's underwriting score
    being within tolerance (`ERR_RISK_SCORE_TOO_HIGH`)."

    Design: Difficulty/priority_pair_validation_conflict/relocation_create_safety_check_outranks_branch_mismatch_referential_check
    """
    scn = _out_of_service_unit_named_against_its_own_yard()

    response = api.create_relocation_order(
        relocation_order_payload(scn["trailer_id"], scn["branch_id"]),
        make_branch_manager_headers(scn["branch_id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_TRAILER_OUT_OF_SERVICE.value)
    assert error["error_id"] != ApiErrorId.ERR_TRAILER_BRANCH_MISMATCH.value

    rows, _ = validate_paginated(
        api.list_relocation_orders(ADMIN, params={"trailer_id": scn["trailer_id"]})
    )
    assert rows == [], "the refused request wrote no order"


def test_a_serviceable_unit_named_against_its_own_yard_reports_the_mismatch(api):
    """PRD §3.9: "The named unit must be in service — a unit whose `service_status`
    is anything other than `SERVICEABLE` is rejected with
    `ERR_TRAILER_OUT_OF_SERVICE` — and the destination must actually be somewhere
    else: naming the yard the unit already stands in as the destination is rejected
    with `ERR_TRAILER_BRANCH_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/relocation_create_safety_check_outranks_branch_mismatch_referential_check
    """
    ctx = setup_reference_data()
    assert read_trailer(ctx["trailer_id"])["service_status"] == "SERVICEABLE"

    response = api.create_relocation_order(
        relocation_order_payload(ctx["trailer_id"], ctx["branch_id"]),
        make_branch_manager_headers(ctx["branch_id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRAILER_BRANCH_MISMATCH.value)

    rows, _ = validate_paginated(
        api.list_relocation_orders(ADMIN, params={"trailer_id": ctx["trailer_id"]})
    )
    assert rows == []


def _approved_move_on_a_unit_that_then_goes_on_rent():
    """An approved move standing on a unit that a contract then takes out on hire."""
    ctx = setup_reference_data()
    add_east_branch(ctx)
    order = validate_success(
        api_client.create_relocation_order(
            relocation_order_payload(ctx["trailer_id"], ctx["east_branch_id"]),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    ctx["order"] = order
    ctx["order_id"] = order["id"]
    validate_success(
        api_client.approve_relocation_order(
            order["id"], make_branch_manager_headers(ctx["east_branch_id"])
        )
    )
    return setup_agreement_active(ctx=ctx, checkout_date="2026-08-20")


def test_dispatch_is_refused_while_the_unit_is_out_with_a_customer(api):
    """PRD §3.9: "The unit's `availability_status` must be exactly `AVAILABLE`,
    with anything else rejected as `ERR_TRAILER_NOT_AVAILABLE`, and its
    `service_status` must be `SERVICEABLE`, with anything else rejected as
    `ERR_TRAILER_OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/relocation_dispatch_gated_by_trailer_availability_dimension
    """
    scn = _approved_move_on_a_unit_that_then_goes_on_rent()
    assert read_trailer(scn["trailer_id"])["availability_status"] == "ON_RENT"

    response = api.dispatch_relocation_order(scn["order_id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_TRAILER_NOT_AVAILABLE.value)

    assert read_relocation_order(scn["order_id"])["status"] == "APPROVED", (
        "a refused dispatch leaves the order where it stood"
    )


def test_the_same_dispatch_succeeds_once_the_unit_is_back_in_the_yard(api):
    """PRD §3.9: "Dispatch moves the trailer `AVAILABLE → IN_TRANSIT` while
    deliberately leaving `current_branch_id` at the origin — the unit is still
    booked to the yard that owns it until it lands — and lowers `on_hand_count` at
    `origin_branch_id` by one."

    Design: Difficulty/cross_entity_state_dependency/relocation_dispatch_gated_by_trailer_availability_dimension
    """
    scn = _approved_move_on_a_unit_that_then_goes_on_rent()
    validate_error(
        api.dispatch_relocation_order(scn["order_id"], ADMIN),
        ApiErrorId.ERR_TRAILER_NOT_AVAILABLE.value,
    )

    validate_success(
        api.return_agreement_unit(
            scn["unit_id"],
            {"return_branch_id": scn["branch_id"], "return_hub_miles": 42000,
             "return_date": "2026-09-03"},
            make_branch_manager_headers(scn["branch_id"]),
        )
    )

    order = validate_success(api.dispatch_relocation_order(scn["order_id"], ADMIN))
    assert order["status"] == "IN_TRANSIT"

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["availability_status"] == "IN_TRANSIT"
    assert trailer["current_branch_id"] == scn["branch_id"], (
        "the unit stays booked to the yard that owns it until it lands"
    )
    assert read_branch(scn["branch_id"])["on_hand_count"] == 0
    assert read_branch(scn["east_branch_id"])["on_hand_count"] == 0


def _narrow_yard_with_three_inbound_requests():
    """A one-space yard already holding an approved arrival on 2026-09-05, plus a
    touching request on 09-09 and a disjoint request on 09-10."""
    ctx = setup_reference_data()
    add_branch(ctx, "narrow", code="NRW-01", name="Narrow Yard", region="CENTRAL",
               yard_capacity=1)
    second = add_trailer(ctx, "second", unit_number="T-1002", hub_miles=52000)
    third = add_trailer(ctx, "third", unit_number="T-1003", hub_miles=63000)

    first_order = validate_success(
        api_client.create_relocation_order(
            relocation_order_payload(ctx["trailer_id"], ctx["narrow_id"],
                                     planned_depart_date="2026-09-03",
                                     planned_arrive_date="2026-09-05"),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    validate_success(
        api_client.approve_relocation_order(
            first_order["id"], make_branch_manager_headers(ctx["narrow_id"])
        )
    )
    touching = validate_success(
        api_client.create_relocation_order(
            relocation_order_payload(second["id"], ctx["narrow_id"],
                                     planned_depart_date="2026-09-07",
                                     planned_arrive_date="2026-09-09"),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    disjoint = validate_success(
        api_client.create_relocation_order(
            relocation_order_payload(third["id"], ctx["narrow_id"],
                                     planned_depart_date="2026-09-08",
                                     planned_arrive_date="2026-09-10"),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    ctx["first_order_id"] = first_order["id"]
    ctx["touching_order_id"] = touching["id"]
    ctx["disjoint_order_id"] = disjoint["id"]
    return ctx


def test_two_inbound_windows_touching_at_one_date_exceed_the_yard_capacity(api):
    """PRD §2.11: "A relocation order occupies its destination yard over the range
    beginning one calendar day before its `planned_arrive_date` and ending three
    calendar days after its `planned_arrive_date`, with both endpoints included.
    Two such windows that merely touch at a single shared endpoint *do* collide."
    PRD §3.9: "If the destination yard's `on_hand_count`, plus that count of
    colliding committed orders, plus the one unit now being accepted, would exceed
    the destination's `yard_capacity`, approval is rejected with
    `ERR_BRANCH_YARD_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/branch_inbound_closed_window_collides_on_touching_endpoints
    """
    ctx = _narrow_yard_with_three_inbound_requests()

    response = api.approve_relocation_order(
        ctx["touching_order_id"], make_branch_manager_headers(ctx["narrow_id"])
    )
    validate_error(response, ApiErrorId.ERR_BRANCH_YARD_CAPACITY_EXCEEDED.value)

    assert read_relocation_order(ctx["touching_order_id"])["status"] == "REQUESTED"
    assert read_relocation_order(ctx["first_order_id"])["status"] == "APPROVED"


def test_a_disjoint_inbound_window_is_admitted_at_the_same_yard(api):
    """PRD §3.9: "Each order occupies an inbound window at its destination running
    from one calendar day before its `planned_arrive_date` through three calendar
    days after it, with both endpoints included; as section 2.11 states, two such
    windows that merely touch at a single shared date do collide."
    PRD §3.9: "A successful approval leaves the order holding its inbound window
    and increments the order's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/branch_inbound_closed_window_collides_on_touching_endpoints
    """
    ctx = _narrow_yard_with_three_inbound_requests()
    validate_error(
        api.approve_relocation_order(
            ctx["touching_order_id"], make_branch_manager_headers(ctx["narrow_id"])
        ),
        ApiErrorId.ERR_BRANCH_YARD_CAPACITY_EXCEEDED.value,
    )

    order = validate_success(
        api.approve_relocation_order(
            ctx["disjoint_order_id"], make_branch_manager_headers(ctx["narrow_id"])
        )
    )
    assert order["status"] == "APPROVED", (
        "the 09-09 through 09-13 window does not touch the 09-04 through 09-08 window"
    )
    assert read_relocation_order(ctx["first_order_id"])["status"] == "APPROVED"
    assert read_branch(ctx["narrow_id"])["on_hand_count"] == 0


def _three_unit_yard_with_an_approved_move():
    """Three units standing at one yard, one of them carrying an approved move to a
    second yard with room to spare."""
    ctx = setup_reference_data()
    add_branch(ctx, "narrow", code="NRW-01", name="Narrow Yard", region="CENTRAL",
               yard_capacity=5)
    add_trailer(ctx, "second", unit_number="T-1002", hub_miles=52000)
    add_trailer(ctx, "third", unit_number="T-1003", hub_miles=63000)

    order = validate_success(
        api_client.create_relocation_order(
            relocation_order_payload(ctx["trailer_id"], ctx["narrow_id"],
                                     planned_depart_date="2026-09-03",
                                     planned_arrive_date="2026-09-05"),
            make_branch_manager_headers(ctx["branch_id"]),
        ),
        201,
    )
    validate_success(
        api_client.approve_relocation_order(
            order["id"], make_branch_manager_headers(ctx["narrow_id"])
        )
    )
    ctx["order_id"] = order["id"]
    return ctx


def test_dispatch_debits_the_origin_yard_and_abort_credits_it_back(api):
    """PRD §2.10: "A dispatch debits exactly one unit from the origin yard's
    on-hand count and credits exactly one to the in-transit bucket; an abort
    reverses both movements exactly, restoring the identity with no drift."
    PRD §3.9: "The trailer returns `IN_TRANSIT → AVAILABLE` with its
    `current_branch_id` still at `origin_branch_id`, and `on_hand_count` at the
    origin yard rises by one, exactly reversing the debit the dispatch took."

    Design: Difficulty/compensating_invariant/relocation_abort_conserves_global_fleet_position_count
    """
    ctx = _three_unit_yard_with_an_approved_move()
    assert read_branch(ctx["branch_id"])["on_hand_count"] == 3

    validate_success(
        api.dispatch_relocation_order(
            ctx["order_id"], make_branch_manager_headers(ctx["branch_id"])
        )
    )
    assert read_branch(ctx["branch_id"])["on_hand_count"] == 2
    assert read_branch(ctx["narrow_id"])["on_hand_count"] == 0

    order = validate_success(
        api.abort_relocation_order(
            ctx["order_id"], {"reason": "driver rejected the load"},
            make_branch_manager_headers(ctx["branch_id"]),
        )
    )
    assert order["status"] == "CANCELLED"
    assert read_branch(ctx["branch_id"])["on_hand_count"] == 3
    assert read_branch(ctx["narrow_id"])["on_hand_count"] == 0


def test_the_fleet_position_identity_holds_across_dispatch_and_abort(api):
    """PRD §2.10: "The system maintains a fleet-position identity that must hold
    before a dispatch, while a unit is on the road, and after an abort: the sum of
    `on_hand_count` across all yards, plus the number of trailers whose
    availability is `IN_TRANSIT`, plus the number of trailers whose availability is
    `ON_RENT` or `ON_LEASE`, equals the number of trailers whose availability is
    anything other than `RETIRED` or `SOLD`."
    PRD §3.9: "It moves the order `IN_TRANSIT → CANCELLED` under the same
    `ERR_RELOCATION_NOT_IN_TRANSIT` guard, records the supplied `reason` into
    `cancel_reason`, and leaves `actual_cost_cents` null — an aborted move is never
    priced."

    Design: Difficulty/compensating_invariant/relocation_abort_conserves_global_fleet_position_count
    """
    from test_helpers import assert_fleet_position_identity

    ctx = _three_unit_yard_with_an_approved_move()

    def snapshot():
        branches, _ = validate_paginated(api.list_branches(ADMIN, params={"limit": 100}))
        trailers, _ = validate_paginated(api.list_trailers(ADMIN, params={"limit": 100}))
        return branches, trailers

    branches, trailers = snapshot()
    assert_fleet_position_identity(branches, trailers, 3)

    validate_success(
        api.dispatch_relocation_order(
            ctx["order_id"], make_branch_manager_headers(ctx["branch_id"])
        )
    )
    branches, trailers = snapshot()
    assert_fleet_position_identity(branches, trailers, 3)

    validate_success(
        api.abort_relocation_order(
            ctx["order_id"], {"reason": "driver rejected the load"},
            make_branch_manager_headers(ctx["branch_id"]),
        )
    )
    branches, trailers = snapshot()
    assert_fleet_position_identity(branches, trailers, 3)

    order = read_relocation_order(ctx["order_id"])
    assert order["status"] == "CANCELLED"
    assert order.get("actual_cost_cents") is None
    assert order.get("actual_miles") is None

    trailer = read_trailer(ctx["trailer_id"])
    assert trailer["availability_status"] == "AVAILABLE"
    assert trailer["current_branch_id"] == ctx["branch_id"]
