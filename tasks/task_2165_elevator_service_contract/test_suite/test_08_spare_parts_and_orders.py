"""Spare parts, obsolescence chains, order pricing and the lead-time cascade."""
from test_helpers import (
    ApiErrorId,
    add_part,
    add_window,
    assert_part_order,
    assert_spare_part,
    build_supersession_chain,
    car_version,
    create_part_order_payload,
    obsolete_part,
    order_part,
    plan_and_approve_project,
    read_car,
    read_part,
    read_part_order,
    read_project,
    read_window,
    set_clock,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_expedite_surcharge_is_keyed_on_the_subtotal_tier(api):
    """PRD §3.6: "Step two selects a freight tier **keyed on that subtotal alone** —
    never on the eventual total — where a subtotal below 100,000 cents is the small
    tier, a subtotal from 100,000 cents up to but not including 500,000 cents is the
    medium tier, and a subtotal of 500,000 cents or more is the large tier. Step
    three computes `expedite_surcharge_cents`: when `expedite` is true it is the
    subtotal multiplied by the tier's rate — 20 percent in the small tier, 15
    percent in the medium tier, 10 percent in the large tier — rounded half up to a
    whole cent; when `expedite` is false it is 0. Step four computes
    `total_cost_cents` as `subtotal_cents` plus `expedite_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/part_order_expedite_tier_keyed_on_subtotal_not_total
    """
    program = setup_program(
        ["CAR-E1"],
        building_name="Epsilon Court",
        building_address="6 Eps St",
        building_manager_user_id="bm-e",
        contractor_user_id="sc-e",
        term_end_date="2027-12-31",
    )
    part = add_part("DO-4501", 45_000, 20, "COMPONENT", "Door operator relay")
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order = validate_success(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(),
                part["id"],
                car_version(program.car_id()),
                quantity=2,
                expedite=True,
            ),
            program.contractor_headers,
        ),
        201,
    )
    assert_part_order(order)
    assert order["subtotal_cents"] == 90_000
    assert order["expedite_surcharge_cents"] == 18_000, (
        "a 90,000-cent subtotal sits in the small tier and draws 20 percent"
    )
    assert order["expedite_surcharge_cents"] != 13_500, (
        "the tier must not be keyed on the 108,000-cent total"
    )
    assert order["total_cost_cents"] == 108_000


def test_expedited_order_lead_time_and_promised_date(api):
    """PRD §3.6: "Step five computes `lead_time_days_applied`: take the effective
    part's `lead_time_days`, subtract **seven days** if `expedite` is true, add **ten
    days for every hop** recorded in `substitution_hops`, and then take whichever is
    larger — that figure or a floor of **three days**. Step six computes
    `promised_date` as the calendar date of the current logical clock advanced by
    `lead_time_days_applied` whole days."
    PRD §3.6: "An order whose requested part was `ACTIVE` has `substitution_hops` 0,
    an `effective_part_id` equal to its `part_id`, no substitution penalty in its
    lead time, is created in `ORDERED`, and fires no window cascade at all."

    Design: Difficulty/combinatorial_formula/part_order_expedite_tier_keyed_on_subtotal_not_total
    """
    program = setup_program(
        ["CAR-E1"],
        building_name="Epsilon Court",
        building_address="6 Eps St",
        building_manager_user_id="bm-e",
        contractor_user_id="sc-e",
        term_end_date="2027-12-31",
    )
    part = add_part("DO-4501", 45_000, 20, "COMPONENT", "Door operator relay")
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order = order_part(program, program.car_id(), part["id"], quantity=2, expedite=True)
    assert order["lead_time_days_applied"] == 13, "20 baseline days less 7 expedited days"
    assert order["promised_date"] == "2026-09-14"
    assert order["substitution_hops"] == 0
    assert order["effective_part_id"] == part["id"]
    assert order["status"] == "ORDERED"
    assert read_car(program.car_id())["open_part_order_count"] == 1


def test_obsolete_part_order_substitutes_and_shifts_the_linked_window(api):
    """PRD §3.6: "An order whose requested part was `OBSOLETE` with a successor has an
    `effective_part_id` different from its `part_id`, takes the successor's price and
    lead time in place of the requested part's, carries a `substitution_hops` of at
    least 1 with ten days of penalty per hop, is created in `SUBSTITUTED`, and does
    fire the window cascade."
    PRD §3.6: "Otherwise the shortfall is the whole number of days from the window's
    start date forward to `promised_date`, and the candidate placement is the
    window's `window_start` and `window_end` each advanced by that identical
    whole-day offset, which preserves `duration_minutes` exactly."
    PRD §3.6: "If the shifted placement is clear, `window_start` and `window_end`
    take the new values, the window stays `SCHEDULED`, and `reschedule_count` is
    still incremented by 1."

    Design: Difficulty/transitive_cascade/obsolete_part_substitution_shifts_window_then_flags_project_at_risk
    """
    program = setup_program(
        ["CAR-K1"],
        building_name="Kappa Mill",
        building_address="10 Kappa Dr",
        building_manager_user_id="bm-k",
        contractor_user_id="sc-k",
        term_end_date="2026-09-30",
    )
    project = plan_and_approve_project(
        program,
        title="Controller modernization",
        budget_cents=9_000_000,
        target_completion_date="2026-09-25",
    )
    window = add_window(
        program,
        program.car_id(),
        "2026-09-20T08:00:00Z",
        "2026-09-22T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    legacy = add_part("CTRL-100", 250_000, 14, "COMPONENT", "Legacy controller board")
    successor = add_part("CTRL-200", 300_000, 21, "COMPONENT", "Successor controller board")
    obsolete_part(legacy["id"], successor["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order = order_part(
        program,
        program.car_id(),
        legacy["id"],
        quantity=2,
        window_id=window["id"],
    )
    stored_part = read_part(legacy["id"])
    assert stored_part["lifecycle_state"] == "OBSOLETE"
    assert stored_part["superseded_by_part_id"] == successor["id"]

    assert order["status"] == "SUBSTITUTED"
    assert order["effective_part_id"] == successor["id"]
    assert order["substitution_hops"] == 1
    assert order["subtotal_cents"] == 600_000
    assert order["expedite_surcharge_cents"] == 0
    assert order["total_cost_cents"] == 600_000
    assert order["lead_time_days_applied"] == 31, "21 successor days plus 10 per hop"
    assert order["promised_date"] == "2026-10-02"

    shifted = read_window(window["id"])
    assert shifted["window_start"].startswith("2026-10-02T08:00:00")
    assert shifted["window_end"].startswith("2026-10-04T08:00:00")
    assert shifted["reschedule_count"] == 1
    assert shifted["status"] == "SCHEDULED"
    assert shifted["duration_minutes"] == 2880


def test_the_shifted_window_flags_the_project_at_risk(api):
    """PRD §3.6: "That project's `target_completion_date` is recomputed as the latest
    `window_end` date across its windows in `SCHEDULED`, `COMPLETED` or
    `RESCHEDULE_REQUIRED`, and if the recomputed date is later than the governing
    contract's `term_end_date` while the project is in `APPROVED` or `IN_PROGRESS`,
    the project is flagged `AT_RISK`."
    PRD §3.5: "The car's `scheduled_downtime_minutes` is, at all times, the sum of
    `duration_minutes` over that car's windows whose `status` is `SCHEDULED` or
    `COMPLETED`."

    Design: Difficulty/transitive_cascade/obsolete_part_substitution_shifts_window_then_flags_project_at_risk
    """
    program = setup_program(
        ["CAR-K1"],
        building_name="Kappa Mill",
        building_address="10 Kappa Dr",
        building_manager_user_id="bm-k",
        contractor_user_id="sc-k",
        term_end_date="2026-09-30",
    )
    project = plan_and_approve_project(
        program,
        title="Controller modernization",
        budget_cents=9_000_000,
        target_completion_date="2026-09-25",
    )
    window = add_window(
        program,
        program.car_id(),
        "2026-09-20T08:00:00Z",
        "2026-09-22T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    legacy = add_part("CTRL-100", 250_000, 14, "COMPONENT", "Legacy controller board")
    successor = add_part("CTRL-200", 300_000, 21, "COMPONENT", "Successor controller board")
    obsolete_part(legacy["id"], successor["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order_part(
        program, program.car_id(), legacy["id"], quantity=2, window_id=window["id"]
    )

    stored_project = read_project(project["id"])
    assert stored_project["target_completion_date"] == "2026-10-04"
    assert stored_project["status"] == "AT_RISK", (
        "the recomputed completion date falls past the contract's term_end_date"
    )
    assert read_car(program.car_id())["scheduled_downtime_minutes"] == 2880


def test_ordering_a_discontinued_part_is_refused(api):
    """PRD §3.6: "When a replacement is *omitted*, the part is instead driven to
    `DISCONTINUED` — from `ACTIVE` directly, or from `OBSOLETE`, in which case its
    `superseded_by_part_id` is cleared back to null — `obsoleted_at` is stamped, and
    every subsequent order naming it is refused outright with
    `ERR_PART_DISCONTINUED`. `DISCONTINUED` is terminal."

    Design: Difficulty/cross_entity_state_dependency/part_order_blocked_by_discontinued_catalog_part_state
    """
    program = setup_program(
        ["CAR-P1"],
        building_name="Pi Works",
        building_address="16 Pi Way",
        building_manager_user_id="bm-p",
        contractor_user_id="sc-p",
        term_end_date="2027-12-31",
    )
    part = add_part("GOV-900", 120_000, 30, "COMPONENT", "Discontinued governor")
    obsolete_part(part["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    stored_part = read_part(part["id"])
    assert_spare_part(stored_part)
    assert stored_part["lifecycle_state"] == "DISCONTINUED"
    assert stored_part["superseded_by_part_id"] is None

    validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), part["id"], car_version(program.car_id()), quantity=1
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_PART_DISCONTINUED.value,
    )


def test_the_discontinued_part_rejection_writes_no_order(api):
    """PRD §3.6: "if the part the walk lands on is `DISCONTINUED` the order is refused
    with `ERR_PART_DISCONTINUED`."
    PRD §3.6: "Either way, creating the order increments the car's
    `open_part_order_count` by 1 and increments the car's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/part_order_blocked_by_discontinued_catalog_part_state
    """
    program = setup_program(
        ["CAR-P1"],
        building_name="Pi Works",
        building_address="16 Pi Way",
        building_manager_user_id="bm-p",
        contractor_user_id="sc-p",
        term_end_date="2027-12-31",
    )
    part = add_part("GOV-900", 120_000, 30, "COMPONENT", "Discontinued governor")
    obsolete_part(part["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    version_before = car_version(program.car_id())

    validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), part["id"], version_before, quantity=1
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_PART_DISCONTINUED.value,
    )

    car = read_car(program.car_id())
    assert car["open_part_order_count"] == 0
    assert car["version"] == version_before, "a refused order must not bump the car"

    rows, meta = validate_paginated(
        api.list_part_orders(program.admin_headers, {"car_id": program.car_id()})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_an_obsoleted_part_is_reverse_reachable_from_its_successor(api, admin_headers):
    """PRD §3.6: "When a replacement *is* supplied, the part moves
    `ACTIVE → OBSOLETE`: `superseded_by_part_id` is set to the replacement and
    `obsoleted_at` is stamped from the logical clock, and every subsequent order
    naming the retired part quietly resolves forward along the successor chain."
    PRD §2.11: "catalog parts by `superseded_by_part_id`, `lifecycle_state` and
    `part_class`"

    Design: Corner/entities/spare_part_self_reference_reverse_lookup_lists_predecessor
    """
    old = add_part("P-OLD", 90_000, 12, "WEAR_ITEM", "Legacy sheave")
    new = add_part("P-NEW", 110_000, 9, "WEAR_ITEM", "Replacement sheave")
    obsolete_part(old["id"], new["id"])

    rows, meta = validate_paginated(
        api.list_parts(admin_headers, {"superseded_by_part_id": new["id"]})
    )
    assert meta["total_count"] == 1, f"expected 1 predecessor, got {meta['total_count']}"
    assert len(rows) == 1
    assert rows[0]["id"] == old["id"]

    stored_old = read_part(old["id"])
    assert stored_old["lifecycle_state"] == "OBSOLETE"
    assert stored_old["obsoleted_at"] is not None

    stored_new = read_part(new["id"])
    assert stored_new["lifecycle_state"] == "ACTIVE"
    assert stored_new["superseded_by_part_id"] is None


def test_a_shift_onto_a_sibling_window_sets_reschedule_required(api):
    """PRD §3.6: "If the shifted placement would collide, the shift is refused rather
    than forced: `window_start` and `window_end` stay exactly where they were, the
    window's `status` becomes `RESCHEDULE_REQUIRED`, its `reschedule_count` is
    incremented by 1, its `duration_minutes` drops out of the car's
    `scheduled_downtime_minutes` because a window awaiting rescheduling no longer
    occupies the car, and the car's `version` is incremented by 1."
    PRD §3.6: "That candidate is then tested against the same per-car interval rule
    of §3.5, consulting the car's other windows in `SCHEDULED` or `COMPLETED`."

    Design: Corner/state_machines/part_lead_time_shift_onto_a_sibling_window_sets_reschedule_required
    """
    program = setup_program(
        ["CAR-SF"],
        building_name="SM Fifteen",
        building_address="15 SM St",
        building_manager_user_id="bm-sf",
        contractor_user_id="sc-sf",
        term_end_date="2027-12-31",
    )
    car_id = program.car_id()
    blocker = add_window(
        program, car_id, "2026-10-02T08:00:00Z", "2026-10-04T08:00:00Z", "REPAIR"
    )
    gated = add_window(
        program, car_id, "2026-09-20T08:00:00Z", "2026-09-22T08:00:00Z", "REPAIR"
    )
    obsolete = add_part("P-OBS", 250_000, 14, "COMPONENT", "Obsolete drive")
    successor = add_part("P-SUC", 300_000, 21, "COMPONENT", "Successor drive")
    obsolete_part(obsolete["id"], successor["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order = order_part(
        program, car_id, obsolete["id"], quantity=2, window_id=gated["id"]
    )
    assert order["promised_date"] == "2026-10-02"
    assert order["status"] == "SUBSTITUTED"
    assert order["substitution_hops"] == 1

    frozen = read_window(gated["id"])
    assert frozen["status"] == "RESCHEDULE_REQUIRED"
    assert frozen["window_start"].startswith("2026-09-20T08:00:00")
    assert frozen["window_end"].startswith("2026-09-22T08:00:00")
    assert frozen["reschedule_count"] == 1

    untouched = read_window(blocker["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["window_start"].startswith("2026-10-02T08:00:00")

    assert read_car(car_id)["scheduled_downtime_minutes"] == 2880, (
        "a RESCHEDULE_REQUIRED window no longer occupies the car"
    )


def test_receiving_a_part_order_frees_the_car_counter(api):
    """PRD §3.6: "Receipt closes the order out. A `ServiceContractor` records it
    against an order in `ORDERED` or in `SUBSTITUTED`, driving it to `RECEIVED`,
    decrementing the car's `open_part_order_count` by 1 and incrementing the car's
    `version` by 1."
    PRD §3.6: "Step one computes `subtotal_cents` as the effective part's
    `unit_price_cents` multiplied by `quantity`."

    Design: Corner/state_machines/part_order_receive_closes_the_order_and_frees_the_car_counter
    """
    program = setup_program(
        ["CAR-SG"],
        building_name="SM Sixteen",
        building_address="16 SM St",
        building_manager_user_id="bm-sg",
        contractor_user_id="sc-sg",
        term_end_date="2027-12-31",
    )
    part = add_part("SG-1", 20_000, 5, "WEAR_ITEM", "Door gib")
    order = order_part(program, program.car_id(), part["id"], quantity=4)
    assert order["subtotal_cents"] == 80_000
    assert order["expedite_surcharge_cents"] == 0
    assert order["total_cost_cents"] == 80_000
    assert order["lead_time_days_applied"] == 5
    assert order["promised_date"] == "2026-08-06"
    assert read_car(program.car_id())["open_part_order_count"] == 1

    received = validate_success(
        api.receive_part_order(order["id"], program.contractor_headers)
    )
    assert received["status"] == "RECEIVED"
    assert read_car(program.car_id())["open_part_order_count"] == 0


def test_a_two_hop_supersession_walk_adds_twenty_lead_days(api):
    """PRD §3.6: "First the supersession chain is resolved. Beginning from the
    requested part with a hop count of zero, the server repeatedly follows
    `superseded_by_part_id` for as long as the part it is looking at is `OBSOLETE`
    and has a successor recorded, counting one hop each time it moves."
    PRD §3.6: "Step five computes `lead_time_days_applied`: take the effective part's
    `lead_time_days`, subtract **seven days** if `expedite` is true, add **ten days
    for every hop** recorded in `substitution_hops`, and then take whichever is
    larger — that figure or a floor of **three days**."
    PRD §2.11: "part orders by `car_id`, `part_id`, `effective_part_id`, `window_id`
    and `status`"

    Design: Corner/calculations/supersession_walk_of_two_hops_adds_twenty_lead_days
    """
    program = setup_program(
        ["CAR-K3"],
        building_name="Calc Three",
        building_address="3 Calc St",
        building_manager_user_id="bm-k3",
        contractor_user_id="sc-k3",
        term_end_date="2027-12-31",
    )
    gen1 = add_part("K3-P1", 250_000, 14, "COMPONENT", "Gen 1 board")
    gen2 = add_part("K3-P2", 200_000, 12, "COMPONENT", "Gen 2 board")
    gen3 = add_part("K3-P3", 100_000, 10, "COMPONENT", "Gen 3 board")
    obsolete_part(gen2["id"], gen3["id"])
    obsolete_part(gen1["id"], gen2["id"])
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    order = order_part(program, program.car_id(), gen1["id"], quantity=1)
    assert order["effective_part_id"] == gen3["id"]
    assert order["substitution_hops"] == 2
    assert order["subtotal_cents"] == 100_000
    assert order["expedite_surcharge_cents"] == 0
    assert order["total_cost_cents"] == 100_000
    assert order["lead_time_days_applied"] == 30, "10 baseline days plus 10 per hop"
    assert order["promised_date"] == "2026-10-01"
    assert order["status"] == "SUBSTITUTED"

    rows, meta = validate_paginated(
        api.list_part_orders(program.admin_headers, {"effective_part_id": gen3["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_four_hop_supersession_walk_is_refused(api):
    """PRD §3.6: "If the walk would take more than **three** hops the order is refused
    with `ERR_SUPERSESSION_CHAIN_TOO_DEEP`; if the part the walk lands on is
    `DISCONTINUED` the order is refused with `ERR_PART_DISCONTINUED`."
    PRD §3.6: "Either way, creating the order increments the car's
    `open_part_order_count` by 1 and increments the car's `version` by 1."

    Design: Corner/calculations/supersession_walk_deeper_than_three_hops_is_rejected
    """
    program = setup_program(
        ["CAR-K4"],
        building_name="Calc Four",
        building_address="4 Calc St",
        building_manager_user_id="bm-k4",
        contractor_user_id="sc-k4",
        term_end_date="2027-12-31",
    )
    chain = build_supersession_chain("K4", 5, unit_price_cents=100_000, lead_time_days=10)

    validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), chain[0]["id"], car_version(program.car_id()), quantity=1
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_SUPERSESSION_CHAIN_TOO_DEEP.value,
    )

    assert read_car(program.car_id())["open_part_order_count"] == 0
    rows, meta = validate_paginated(
        api.list_part_orders(program.admin_headers, {"car_id": program.car_id()})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_expedited_lead_time_clamps_at_the_three_day_floor(api):
    """PRD §3.6: "Step five computes `lead_time_days_applied`: take the effective
    part's `lead_time_days`, subtract **seven days** if `expedite` is true, add **ten
    days for every hop** recorded in `substitution_hops`, and then take whichever is
    larger — that figure or a floor of **three days**. Step six computes
    `promised_date` as the calendar date of the current logical clock advanced by
    `lead_time_days_applied` whole days."
    PRD §3.6: "Step three computes `expedite_surcharge_cents`: when `expedite` is
    true it is the subtotal multiplied by the tier's rate — 20 percent in the small
    tier, 15 percent in the medium tier, 10 percent in the large tier — rounded half
    up to a whole cent; when `expedite` is false it is 0."

    Design: Corner/calculations/expedited_order_lead_time_clamps_at_the_minimum_floor
    """
    program = setup_program(
        ["CAR-K5"],
        building_name="Calc Five",
        building_address="5 Calc St",
        building_manager_user_id="bm-k5",
        contractor_user_id="sc-k5",
        term_end_date="2027-12-31",
    )
    part = add_part("K5-FAST", 30_000, 5, "WEAR_ITEM", "Roller guide")

    order = order_part(program, program.car_id(), part["id"], quantity=1, expedite=True)
    assert order["subtotal_cents"] == 30_000
    assert order["expedite_surcharge_cents"] == 6_000
    assert order["total_cost_cents"] == 36_000
    assert order["lead_time_days_applied"] == 3, "5 less 7 clamps up to the three-day floor"
    assert order["promised_date"] == "2026-08-04"
    assert order["status"] == "ORDERED"


def test_an_oil_and_grease_contract_may_only_order_lubrication_parts(api):
    """PRD §3.6: "Scope is checked against the part the walk landed on, not the one
    the contractor named: on an `OIL_AND_GREASE` contract, an effective part whose
    `part_class` is anything other than `LUBRICATION` is outside the covered scope
    and the order is refused with `ERR_SCOPE_EXCLUDES_REPAIR`. A `FULL_MAINTENANCE`
    contract may order any class."

    Design: Corner/validations/oil_and_grease_contract_cannot_order_a_component_part
    """
    program = setup_program(
        ["CAR-V4"],
        building_name="Val Four",
        building_address="4 Val St",
        building_manager_user_id="bm-v4",
        contractor_user_id="sc-v4",
        scope_type="OIL_AND_GREASE",
        monthly_base_fee_cents=200_000,
        callback_response_minutes=90,
        entrapment_response_minutes=45,
        term_end_date="2027-12-31",
    )
    component = add_part("V4-COMP", 180_000, 15, "COMPONENT", "Selector board")
    lubricant = add_part("V4-LUBE", 8_000, 4, "LUBRICATION", "Rail lubricant")
    observed_version = car_version(program.car_id())

    validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), component["id"], observed_version, quantity=1
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_SCOPE_EXCLUDES_REPAIR.value,
    )

    accepted = validate_success(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), lubricant["id"], observed_version, quantity=3
            ),
            program.contractor_headers,
        ),
        201,
    )
    assert accepted["subtotal_cents"] == 24_000
    assert accepted["promised_date"] == "2026-08-05"
    assert read_car(program.car_id())["open_part_order_count"] == 1


def test_zero_quantity_is_reported_before_the_stale_car_version(api):
    """PRD §2.7: "First, the quantity check on a part order runs *before* the
    stale-version check, so an order carrying both a zero `quantity` and a stale
    `expected_car_version` reports `ERR_INVALID_QUANTITY`, not
    `ERR_STALE_CAR_VERSION`."
    PRD §2.7: "**Order quantity.** A part order's `quantity` must be at least 1; a
    zero or negative quantity is refused with `ERR_INVALID_QUANTITY` (422) before
    any pricing or supersession work is attempted."

    Design: Corner/validations/zero_quantity_beats_the_occ_version_check_on_part_orders
    """
    program = setup_program(
        ["CAR-V3"],
        building_name="Val Three",
        building_address="3 Val St",
        building_manager_user_id="bm-v3",
        contractor_user_id="sc-v3",
        term_end_date="2027-12-31",
    )
    part = add_part("V3-P", 15_000, 6, "WEAR_ITEM", "Guide shoe")
    stale_version = car_version(program.car_id()) - 1

    error = validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), part["id"], stale_version, quantity=0
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_INVALID_QUANTITY.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_CAR_VERSION.value, (
        "the quantity check runs before the stale-version check"
    )
    assert read_car(program.car_id())["open_part_order_count"] == 0


def test_a_stale_car_version_blocks_a_second_part_order(api):
    """PRD §2.8: "Creating a part order must carry `expected_car_version`, a
    non-optional field holding the `version` of the target `ElevatorCar` as the
    client last observed it."
    PRD §2.8: "If `expected_car_version` does not equal the car's current `version`,
    the request is rejected with `ERR_STALE_CAR_VERSION` and HTTP 412."
    PRD §3.6: "Either way, creating the order increments the car's
    `open_part_order_count` by 1 and increments the car's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_car_version_blocks_a_second_part_order
    """
    program = setup_program(
        ["CAR-CC3"],
        building_name="Cc Three",
        building_address="3 Cc St",
        building_manager_user_id="bm-c3x",
        contractor_user_id="sc-c3x",
        term_end_date="2027-12-31",
    )
    part = add_part("CC3-P", 15_000, 6, "WEAR_ITEM", "Door restrictor")
    observed_version = car_version(program.car_id())

    first = validate_success(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), part["id"], observed_version, quantity=2
            ),
            program.contractor_headers,
        ),
        201,
    )
    assert first["subtotal_cents"] == 30_000
    assert first["promised_date"] == "2026-08-07"
    assert read_car(program.car_id())["version"] == observed_version + 1

    validate_error(
        api.create_part_order(
            create_part_order_payload(
                program.car_id(), part["id"], observed_version, quantity=5
            ),
            program.contractor_headers,
        ),
        ApiErrorId.ERR_STALE_CAR_VERSION.value,
    )

    assert read_car(program.car_id())["open_part_order_count"] == 1
    rows, meta = validate_paginated(
        api.list_part_orders(program.admin_headers, {"car_id": program.car_id()})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert read_part_order(first["id"])["status"] == "ORDERED"
