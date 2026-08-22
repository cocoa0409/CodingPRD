"""Harbor services: berth reservations, the aggregate capacity test, and the
wash rack — plus the two independent axes a hull carries."""
from test_helpers import (
    ApiErrorId,
    cancel_fleeting_assignment,
    complete_cleaning_order,
    create_barge,
    create_cleaning_order,
    create_commodity,
    create_compatibility_rule,
    create_fleeting_assignment,
    create_fleeting_assignment_payload,
    create_fleeting_berth,
    make_harbor_agent_headers,
    read_barge,
    read_berth,
    read_cleaning_order,
    read_fleeting_assignment,
    release_fleeting_assignment,
    set_clock,
    start_cleaning_order,
    validate_error,
    validate_paginated,
    validate_success,
)

HARBOR = make_harbor_agent_headers()


def _hull_with_prior_fertilizer_cargo():
    """CORN and UAN32 registered, FERTILIZER -> GRAIN needing STEAM_CERT, and a
    DIRTY hull whose last cargo was UAN32."""
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    uan = create_commodity(code="UAN32", commodity_group="FERTILIZER",
                           residue_class="TOXIC", hazard_flag=True, stowage_factor=0.85)
    create_compatibility_rule("FERTILIZER", "GRAIN",
                              required_cleaning_level="STEAM_CERT", prohibited=False)
    barge = create_barge(hull_number="BL-2001", cleanliness_status="DIRTY",
                         last_cargo_commodity_id=uan["id"])
    return corn, uan, barge


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / the hull's two independent axes
# ---------------------------------------------------------------------------
def test_passing_wash_advances_cleanliness_while_the_hull_stays_idle(api):
    """PRD §3.4: "**On a pass**, the order moves `IN_PROGRESS → COMPLETED` — a
    terminal state — and `fee_cents` is fixed from the performed level: `NONE`
    costs nothing, a `SWEEP` costs 45,000 cents, a `WASH` costs 180,000 cents,
    and a `STEAM_CERT` costs 420,000 cents."
    PRD §3.4: "A hull that was `OUT_OF_SERVICE` returns to `IDLE`; a hull that
    was already `IDLE` stays `IDLE`, because the two axes are independent and a
    passing wash advances cleanliness without moving the hull anywhere."

    Design: Difficulty/non_linear_state_machine/barge_cleanliness_axis_advances_while_operational_axis_holds_then_reverses
    """
    corn, _uan, barge = _hull_with_prior_fertilizer_cargo()
    order = create_cleaning_order(barge["id"], corn["id"])
    assert order["required_cleaning_level"] == "STEAM_CERT", (
        "the FERTILIZER -> GRAIN rule requires a steam certificate")
    start_cleaning_order(order["id"])

    completed = complete_cleaning_order(
        order["id"], performed_level="STEAM_CERT", certificate_number="CERT-77",
        inspection_passed=True)
    assert completed["status"] == "COMPLETED"
    assert completed["fee_cents"] == 420_000, (
        f"a STEAM_CERT costs 420000 cents, got {completed['fee_cents']}")

    hull = read_barge(barge["id"])
    assert hull["cleanliness_status"] == "STEAM_CERTIFIED", (
        "the passing verdict advances the cleanliness axis")
    assert hull["operational_status"] == "IDLE", (
        "an already-IDLE hull stays IDLE — the operational axis does not move")
    assert hull["last_cleaning_certificate_number"] == "CERT-77"


def test_fleeting_moves_the_operational_axis_and_leaves_cleanliness_alone(api):
    """PRD §3.4: "The berth's `occupied_barge_count` increments by one, the hull
    moves `IDLE → FLEETED` on its operational axis while its
    `cleanliness_status` is left completely untouched, and the `version` of both
    the hull and the berth increments alongside the new reservation."
    PRD §3.4: "On admission the reservation is created in status `RESERVED` and
    a provisional `estimated_fee_cents` is computed from the planned interval:
    take the elapsed seconds from `start_at` to `end_at`, divide by the 86,400
    seconds in a day, round the quotient up to a whole day, take the greater of
    that figure and one day, multiply by the berth's `daily_fee_cents_per_barge`,
    and add the berth's one-time `switch_fee_cents`."

    Design: Difficulty/non_linear_state_machine/barge_cleanliness_axis_advances_while_operational_axis_holds_then_reverses
    """
    corn, _uan, barge = _hull_with_prior_fertilizer_cargo()
    berth = create_fleeting_berth(capacity_barges=4, daily_fee_cents_per_barge=15_000,
                                  switch_fee_cents=60_000)
    order = create_cleaning_order(barge["id"], corn["id"])
    start_cleaning_order(order["id"])
    complete_cleaning_order(order["id"], performed_level="STEAM_CERT",
                            certificate_number="CERT-77", inspection_passed=True)

    reservation = create_fleeting_assignment(
        barge["id"], berth["id"], start_at="2026-08-18T00:00:00Z",
        end_at="2026-08-20T00:00:00Z")
    assert reservation["status"] == "RESERVED"
    assert reservation["estimated_fee_cents"] == 90_000, (
        f"two planned days at 15000 plus a 60000 switch fee, "
        f"got {reservation['estimated_fee_cents']}")
    assert reservation["fee_cents"] == 0, "no real money is fixed until release"

    hull = read_barge(barge["id"])
    assert hull["operational_status"] == "FLEETED", "the reservation moves the first axis"
    assert hull["cleanliness_status"] == "STEAM_CERTIFIED", (
        "the certificate the hull holds is left completely untouched")
    assert read_berth(berth["id"])["occupied_barge_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / berth aggregate occupancy
# ---------------------------------------------------------------------------
def _berth_exactly_full():
    """A capacity-2 berth carrying two overlapping RESERVED intervals."""
    set_clock("2026-08-17T00:00:00Z")
    berth = create_fleeting_berth(capacity_barges=2, daily_fee_cents_per_barge=15_000,
                                  switch_fee_cents=60_000)
    hulls = [create_barge(hull_number=f"BL-600{n}") for n in (1, 2, 3)]
    first = create_fleeting_assignment(
        hulls[0]["id"], berth["id"], start_at="2026-08-18T00:00:00Z",
        end_at="2026-08-20T00:00:00Z")
    second = create_fleeting_assignment(
        hulls[1]["id"], berth["id"], start_at="2026-08-18T12:00:00Z",
        end_at="2026-08-21T00:00:00Z")
    return berth, hulls, first, second


def test_berth_refuses_the_reservation_that_lifts_occupancy_past_capacity(api):
    """PRD §3.4: "Admission to a berth is an **aggregate head-count test, not a
    pairwise overlap test** — any number of reservations may overlap so long as
    the berth is never over-subscribed at any instant."
    PRD §3.4: "If the greatest occupancy over those instants exceeds the berth's
    `capacity_barges`, the reservation is refused with
    `ERR_BERTH_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/fleeting_berth_aggregate_occupancy_over_half_open_intervals
    """
    berth, hulls, first, second = _berth_exactly_full()
    assert first["estimated_fee_cents"] == 90_000
    assert second["estimated_fee_cents"] == 105_000, (
        f"an interval of two and a half days rounds up to three, "
        f"got {second['estimated_fee_cents']}")

    validate_error(api.create_fleeting_assignment(
        create_fleeting_assignment_payload(
            hulls[2]["id"], berth["id"], start_at="2026-08-19T00:00:00Z",
            end_at="2026-08-19T12:00:00Z"), HARBOR),
        ApiErrorId.ERR_BERTH_CAPACITY_EXCEEDED.value)

    assert read_berth(berth["id"])["occupied_barge_count"] == 2, (
        "the refused reservation must not touch the berth's occupancy")
    assert read_barge(hulls[2]["id"])["operational_status"] == "IDLE", (
        "the refused hull stays IDLE")


def test_berth_admits_a_reservation_starting_on_an_exclusive_end_instant(api):
    """PRD §3.4: "Intervals are closed on the left and open on the right, so a
    reservation ending exactly at the instant under test does not occupy the
    berth at that instant."
    PRD §3.1: "Its `occupied_barge_count` starts at 0 and tracks, at every
    instant, the number of reservations on the berth that are still in
    `RESERVED` status."

    Design: Difficulty/resource_temporal_overlap/fleeting_berth_aggregate_occupancy_over_half_open_intervals
    """
    berth, hulls, _first, _second = _berth_exactly_full()

    third = validate_success(api.create_fleeting_assignment(
        create_fleeting_assignment_payload(
            hulls[2]["id"], berth["id"], start_at="2026-08-20T00:00:00Z",
            end_at="2026-08-20T12:00:00Z"), HARBOR), 201)
    assert third["status"] == "RESERVED", (
        "the first interval is right-open and frees the berth at its own end instant")
    assert third["estimated_fee_cents"] == 75_000, (
        f"half a day rounds up to one billable day plus the switch fee, "
        f"got {third['estimated_fee_cents']}")
    assert read_berth(berth["id"])["occupied_barge_count"] == 3, (
        "occupancy counts every RESERVED row on the berth")


# ---------------------------------------------------------------------------
# Queue B — fleeting lifecycle
# ---------------------------------------------------------------------------
def test_cancelling_a_reservation_bills_nothing_and_frees_the_berth(api):
    """PRD §3.4: "Cancelling a reservation is the same shape with the opposite
    money: it moves `RESERVED → CANCELLED`, leaves both `fee_cents` and
    `billable_days` at 0 forever — a cancelled reservation is never billable
    under any circumstance — decrements the berth's `occupied_barge_count` by
    one, returns the hull `FLEETED → IDLE` when it is not `IN_TOW`, and
    increments `version`."

    Design: Corner/state_machines/fleeting_assignment_cancel_leaves_nothing_billable_and_frees_the_berth
    """
    berth = create_fleeting_berth(capacity_barges=2)
    barge = create_barge(hull_number="BL-9801")
    reservation = create_fleeting_assignment(barge["id"], berth["id"])
    assert read_berth(berth["id"])["occupied_barge_count"] == 1
    assert read_barge(barge["id"])["operational_status"] == "FLEETED"

    cancelled = cancel_fleeting_assignment(reservation["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_cents"] == 0, "a cancelled reservation is never billable"
    assert cancelled["billable_days"] == 0
    assert cancelled["estimated_fee_cents"] == 90_000, (
        "the provisional figure is retained for the record")
    assert read_berth(berth["id"])["occupied_barge_count"] == 0, (
        "occupancy returns to its pre-reservation value")
    assert read_barge(barge["id"])["operational_status"] == "IDLE"


def test_releasing_an_already_released_reservation_is_refused(api):
    """PRD §3.4: "The reservation must stand in `RESERVED`, or the call is
    refused with `ERR_FLEETING_ASSIGNMENT_INVALID_STATE`."
    PRD §3.4: "Release moves the reservation `RESERVED → RELEASED` and fixes the
    real money: `billable_days` is the elapsed seconds from `start_at` to
    `released_at` divided by 86,400, rounded up to a whole day, with a floor of
    one day; `fee_cents` is `billable_days` multiplied by the berth's
    `daily_fee_cents_per_barge` plus the berth's `switch_fee_cents`."

    Design: Corner/state_machines/release_an_already_released_fleeting_assignment_returns_invalid_state
    """
    berth = create_fleeting_berth(capacity_barges=2)
    barge = create_barge(hull_number="BL-9901")
    reservation = create_fleeting_assignment(barge["id"], berth["id"])
    release_fleeting_assignment(reservation["id"], "2026-08-19T00:00:00Z")

    validate_error(api.release_fleeting_assignment(
        reservation["id"], {"released_at": "2026-08-19T06:00:00Z"}, HARBOR),
        ApiErrorId.ERR_FLEETING_ASSIGNMENT_INVALID_STATE.value)

    stored = read_fleeting_assignment(reservation["id"])
    assert stored["billable_days"] == 1, "the first release fixed one billable day"
    assert stored["fee_cents"] == 75_000, (
        f"the refused second release must not double-charge, got {stored['fee_cents']}")
    assert read_berth(berth["id"])["occupied_barge_count"] == 0


def test_billable_days_round_up_from_the_exact_day_boundary(api):
    """PRD §3.4: "Release moves the reservation `RESERVED → RELEASED` and fixes
    the real money: `billable_days` is the elapsed seconds from `start_at` to
    `released_at` divided by 86,400, rounded up to a whole day, with a floor of
    one day; `fee_cents` is `billable_days` multiplied by the berth's
    `daily_fee_cents_per_barge` plus the berth's `switch_fee_cents`."

    Design: Corner/calculations/fleeting_billable_day_ceiling_at_exactly_twenty_four_hours
    """
    berth = create_fleeting_berth(capacity_barges=4, daily_fee_cents_per_barge=15_000,
                                  switch_fee_cents=60_000)
    first_hull = create_barge(hull_number="BL-7001")
    second_hull = create_barge(hull_number="BL-7002")
    first = create_fleeting_assignment(
        first_hull["id"], berth["id"], start_at="2026-08-18T00:00:00Z",
        end_at="2026-08-19T00:00:00Z")
    second = create_fleeting_assignment(
        second_hull["id"], berth["id"], start_at="2026-08-18T00:00:00Z",
        end_at="2026-08-19T00:00:00Z")
    assert first["estimated_fee_cents"] == 75_000
    assert second["estimated_fee_cents"] == 75_000

    exact = release_fleeting_assignment(first["id"], "2026-08-19T00:00:00Z")
    assert exact["billable_days"] == 1, (
        f"exactly 24 hours is one billable day, got {exact['billable_days']}")
    assert exact["fee_cents"] == 75_000

    over = release_fleeting_assignment(second["id"], "2026-08-19T00:01:00Z")
    assert over["billable_days"] == 2, (
        f"one minute past 24 hours rounds up to two days, got {over['billable_days']}")
    assert over["fee_cents"] == 90_000, (
        "the switch fee is still charged exactly once")
    assert read_berth(berth["id"])["occupied_barge_count"] == 0


def test_release_before_the_reservation_starts_is_refused(api):
    """PRD §3.4: "Releasing the hull requires a `released_at` instant, which
    must be at or after the reservation's `start_at` or the call is refused with
    `ERR_UNLOAD_SEQUENCE_INVALID`."

    Design: Corner/calculations/release_before_the_reservation_starts_returns_sequence_invalid
    """
    berth = create_fleeting_berth(capacity_barges=4)
    barge = create_barge(hull_number="BL-7101")
    reservation = create_fleeting_assignment(
        barge["id"], berth["id"], start_at="2026-08-18T00:00:00Z",
        end_at="2026-08-19T00:00:00Z")

    validate_error(api.release_fleeting_assignment(
        reservation["id"], {"released_at": "2026-08-17T23:00:00Z"}, HARBOR),
        ApiErrorId.ERR_UNLOAD_SEQUENCE_INVALID.value)

    stored = read_fleeting_assignment(reservation["id"])
    assert stored["status"] == "RESERVED"
    assert stored["billable_days"] == 0
    assert stored["fee_cents"] == 0
    assert read_berth(berth["id"])["occupied_barge_count"] == 1


def test_fleeting_a_hull_that_is_already_fleeted_is_refused(api):
    """PRD §3.4: "The hull must stand in `operational_status` `IDLE`; a hull
    that is already `FLEETED`, `IN_TOW` or `OUT_OF_SERVICE` is refused with
    `ERR_BARGE_NOT_AVAILABLE`."

    Design: Corner/validations/fleeting_a_hull_that_is_already_fleeted_returns_barge_not_available
    """
    first_berth = create_fleeting_berth(harbor_name="Cairo Harbor", capacity_barges=4)
    second_berth = create_fleeting_berth(
        harbor_name="Memphis Harbor", river_mile=736.0, capacity_barges=4,
        daily_fee_cents_per_barge=12_000, switch_fee_cents=50_000)
    barge = create_barge(hull_number="BL-D001")
    first = create_fleeting_assignment(barge["id"], first_berth["id"])

    validate_error(api.create_fleeting_assignment(
        create_fleeting_assignment_payload(
            barge["id"], second_berth["id"], start_at="2026-08-18T00:00:00Z",
            end_at="2026-08-19T00:00:00Z"), HARBOR),
        ApiErrorId.ERR_BARGE_NOT_AVAILABLE.value)

    assert read_berth(second_berth["id"])["occupied_barge_count"] == 0
    assert read_berth(first_berth["id"])["occupied_barge_count"] == 1
    rows, meta = validate_paginated(api.list_fleeting_assignments(
        HARBOR, params={"barge_id": barge["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


# ---------------------------------------------------------------------------
# Queue B — the wash rack
# ---------------------------------------------------------------------------
def test_failed_inspection_parks_the_hull_and_the_rework_pass_clears_it(api):
    """PRD §3.4: "**On a failure**, the order moves `IN_PROGRESS →
    FAILED_INSPECTION`, `fee_cents` stays at 0 because a failed inspection is
    not billable, the hull's `cleanliness_status` is left exactly as it was
    since a failed inspection grants no certificate, and the hull is driven
    `IDLE → OUT_OF_SERVICE` on its operational axis."
    PRD §3.4: "Moving the order onto the rack advances it `ORDERED →
    IN_PROGRESS`, and the same operation is also how an order that failed
    inspection returns to the rack, advancing `FAILED_INSPECTION → IN_PROGRESS`
    — the failed order is re-worked rather than replaced by a fresh one."
    PRD §3.1: "When no rule exists for the pair, the required level defaults to
    `WASH` and the sequence is not prohibited."

    Design: Corner/state_machines/cleaning_order_failed_inspection_reverts_and_parks_the_hull
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    coal = create_commodity(code="BITCOAL", commodity_group="COAL",
                            residue_class="DUSTY", hazard_flag=False, stowage_factor=0.9)
    barge = create_barge(hull_number="BL-9501", cleanliness_status="DIRTY",
                         last_cargo_commodity_id=coal["id"])
    order = create_cleaning_order(barge["id"], corn["id"])
    assert order["required_cleaning_level"] == "WASH", (
        "no COAL -> GRAIN rule exists, so the default WASH level applies")
    start_cleaning_order(order["id"])

    failed = complete_cleaning_order(order["id"], performed_level="WASH",
                                     certificate_number="C-FAIL",
                                     inspection_passed=False)
    assert failed["status"] == "FAILED_INSPECTION"
    assert failed["fee_cents"] == 0, "a failed inspection is not billable"
    hull = read_barge(barge["id"])
    assert hull["operational_status"] == "OUT_OF_SERVICE"
    assert hull["cleanliness_status"] == "DIRTY", (
        "a failed inspection grants no certificate")

    restarted = start_cleaning_order(order["id"])
    assert restarted["status"] == "IN_PROGRESS", (
        "the same order returns to the rack rather than being replaced")

    passed = complete_cleaning_order(order["id"], performed_level="WASH",
                                     certificate_number="C-PASS",
                                     inspection_passed=True)
    assert passed["status"] == "COMPLETED"
    assert passed["fee_cents"] == 180_000
    hull = read_barge(barge["id"])
    assert hull["operational_status"] == "IDLE", (
        "a hull that was OUT_OF_SERVICE returns to IDLE")
    assert hull["cleanliness_status"] == "WASHED"
    assert hull["last_cleaning_certificate_number"] == "C-PASS"


def test_completing_an_order_that_was_never_started_is_refused(api):
    """PRD §3.4: "Closing the order carries the surveyor's verdict and three
    inputs: the `performed_level` actually worked, one of `NONE`, `SWEEP`,
    `WASH` or `STEAM_CERT`; the `certificate_number` issued; and the boolean
    `inspection_passed`. The order must stand in `IN_PROGRESS`."
    PRD §3.4: "At creation the server resolves `required_cleaning_level` for the
    pair formed by the hull's prior cargo group and the target commodity's
    group, exactly as §3.1 describes, and the order is born in status `ORDERED`
    with `fee_cents` at 0."

    Design: Corner/state_machines/complete_cleaning_order_that_was_never_started_returns_invalid_state
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    barge = create_barge(hull_number="BL-9601")
    order = create_cleaning_order(barge["id"], corn["id"])

    validate_error(api.complete_cleaning_order(
        order["id"],
        {"performed_level": "SWEEP", "certificate_number": "C-1",
         "inspection_passed": True},
        HARBOR),
        ApiErrorId.ERR_CLEANING_ORDER_INVALID_STATE.value)

    stored = read_cleaning_order(order["id"])
    assert stored["status"] == "ORDERED"
    assert stored["fee_cents"] == 0
    assert read_barge(barge["id"])["cleanliness_status"] == "WASHED", (
        "the refused completion leaves the cleanliness axis untouched")


def test_hull_with_no_prior_cargo_needs_no_cleaning_level(api):
    """PRD §3.1: "If the hull has never carried cargo — that is, its
    `last_cargo_commodity_id` is null — the required level resolves to `NONE`
    and the sequence is never prohibited."
    PRD §3.4: "The hull's `cleanliness_status` is set from the performed level
    through a fixed mapping in which `NONE` yields `DIRTY`, `SWEEP` yields
    `SWEPT`, `WASH` yields `WASHED` and `STEAM_CERT` yields `STEAM_CERTIFIED`,
    and the hull's `last_cleaning_certificate_number` is set from the supplied
    `certificate_number`."

    Design: Corner/state_machines/null_prior_cargo_resolves_required_cleaning_level_to_none
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    barge = create_barge(hull_number="BL-9701")
    order = create_cleaning_order(barge["id"], corn["id"])
    assert order["required_cleaning_level"] == "NONE", (
        "a hull that never carried cargo short-circuits the matrix")
    start_cleaning_order(order["id"])

    completed = complete_cleaning_order(order["id"], performed_level="NONE",
                                        certificate_number="C-NONE",
                                        inspection_passed=True)
    assert completed["status"] == "COMPLETED"
    assert completed["fee_cents"] == 0, "a NONE level costs nothing"
    assert read_barge(barge["id"])["cleanliness_status"] == "DIRTY", (
        "performed level NONE maps to DIRTY on the cleanliness axis")
