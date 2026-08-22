"""Medication stock lots: receipt, inventory actions, the twice-rounded days-of-supply
figure, emergency-stock readiness, lot selection and the quarantine cascade."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _two_single_unit_epinephrine_lots():
    school = create_school(name="Bell High", building_code="BEL03")
    lot_one = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-BEL-1",
                         is_stock_protocol=True, initial_quantity=1)
    lot_two = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-BEL-2",
                         is_stock_protocol=True, initial_quantity=1,
                         expiration_date="2027-07-31T00:00:00Z")
    return school, lot_one, lot_two


def test_each_lot_rounds_its_own_days_of_supply_before_the_building_sums_them(api, admin_headers):
    """PRD §3.5: "A lot's own `days_of_supply` is its `quantity_available` divided by that figure
    for its medication, rounded half up to two decimal places **first**."
    PRD §3.5: "The order of rounding is load-bearing and must not be reordered: two epinephrine
    lots holding one unit each contribute 3.33 and 3.33 for a building figure of 6.66, whereas
    summing the raw quotients first and rounding once would wrongly give 6.67."

    Design: Difficulty/combinatorial_formula/days_of_supply_rounds_each_lot_before_summing
    """
    school, lot_one, lot_two = _two_single_unit_epinephrine_lots()

    first = validate_success(api.get_stock_lot(lot_one["id"], admin_headers))
    second = validate_success(api.get_stock_lot(lot_two["id"], admin_headers))
    assert first["days_of_supply"] == pytest.approx(3.33, abs=0.001)
    assert second["days_of_supply"] == pytest.approx(3.33, abs=0.001)

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["epinephrine_days_of_supply"] == pytest.approx(6.66, abs=0.001)
    assert building["epinephrine_days_of_supply"] != pytest.approx(6.67, abs=0.001)


def test_a_medication_with_no_qualifying_lot_reads_zero_days_of_supply(api, admin_headers):
    """PRD §3.5: "The building's figure for a medication is then the sum of those already-rounded
    per-lot terms across the building's lots of that medication that are `AVAILABLE` and whose
    `expiration_date` is strictly later than the clock, with that sum rounded half up to two
    decimal places once more."
    PRD §3.5: "When no lot qualifies the result is 0.00, never null."

    Design: Difficulty/combinatorial_formula/days_of_supply_rounds_each_lot_before_summing
    """
    school, _, _ = _two_single_unit_epinephrine_lots()

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["albuterol_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    assert building["stock_protocol_status"] == "DEPLETED", "a zero albuterol unit total depletes the protocol"


def _quarantine_scenario():
    """A READY building at FULL posture holding one PREPARED emergency albuterol dose."""
    ctx = setup_stock_school(
        epinephrine_units=10, albuterol_units=36,
        school_overrides={"name": "Franklin Elementary", "building_code": "FRA07"},
        student_overrides={"full_name": "Ivan Poll", "grade_level": 5,
                           "date_of_birth": "2015-07-21T00:00:00Z",
                           "allergy_severity": "ANAPHYLAXIS"})
    assert ctx["school"]["stock_protocol_status"] == "READY"
    assert ctx["school"]["coverage_posture"] == "FULL"
    set_clock(MONDAY_0900)
    visit = open_visit(ctx["student"]["id"], ctx["school"]["id"], ctx["nurse"]["id"],
                       complaint_code="MEDICATION")
    assess_visit(visit["id"], ctx["nurse"]["id"], "Audible wheeze, rescue inhaler required")
    ctx["visit"] = visit
    ctx["record"] = prepare_stock_dose(visit["id"], "ALBUTEROL", ctx["nurse"]["id"], units=2)
    return ctx


def test_quarantining_a_lot_voids_its_prepared_dose_and_releases_the_reservation(api, admin_headers):
    """PRD §3.5: "Hop 1 sets the lot to `QUARANTINED`."
    PRD §3.5: "Hop 2 follows because the lot is quarantined: every administration record drawing on
    it that is still `PREPARED` moves to `VOIDED`, and consequently each of those reservations is
    released back to the lot — `units` moving from `quantity_reserved` to `quantity_on_hand` —
    while each parent encounter's `pending_administration_count` is decremented by one."

    Design: Difficulty/transitive_cascade/lot_quarantine_four_hop_cascade
    """
    ctx = _quarantine_scenario()
    lot_id = ctx["albuterol_lot"]["id"]

    before = validate_success(api.get_stock_lot(lot_id, admin_headers))
    assert before["quantity_on_hand"] == 34
    assert before["days_of_supply"] == pytest.approx(28.33, abs=0.001)

    quarantined = validate_success(api.lot_inventory_action(
        lot_id, {"action": "QUARANTINE", "expected_lot_version": before["version"],
                 "reason_code": "Manufacturer recall notice"}, admin_headers))
    assert quarantined["status"] == "QUARANTINED"

    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert record["status"] == "VOIDED"

    lot = validate_success(api.get_stock_lot(lot_id, admin_headers))
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_on_hand"] == 36
    assert lot["received_total"] == 36, "received_total never moves across the cascade"
    assert_lot_unit_conservation(lot)

    visit = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert visit["pending_administration_count"] == 0


def test_quarantine_drops_the_days_of_supply_the_protocol_status_and_the_posture(api, admin_headers):
    """PRD §3.5: "Hop 3 follows because the lot has left `AVAILABLE` and therefore stops
    contributing to the building's days of supply: `epinephrine_days_of_supply` and
    `albuterol_days_of_supply` are recomputed and then `stock_protocol_status` is recomputed from
    them."
    PRD §3.5: "Hop 4 follows because that status may now read `DEPLETED`: `coverage_posture` is
    recomputed and can drop from `FULL` to `LIMITED`, which in turn tightens the gate on new
    encounters at that building."

    Design: Difficulty/transitive_cascade/lot_quarantine_four_hop_cascade
    """
    ctx = _quarantine_scenario()
    lot_id = ctx["albuterol_lot"]["id"]
    before = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert before["coverage_posture"] == "FULL"

    inventory_action(lot_id, "QUARANTINE", reason_code="Manufacturer recall notice")

    building = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert building["albuterol_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    assert building["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert building["stock_protocol_status"] == "DEPLETED"
    assert building["coverage_posture"] == "LIMITED"


def test_quarantine_and_restore_close_the_loop_on_a_lot(api, admin_headers):
    """PRD §3.5: "`QUARANTINE` moves a lot from `AVAILABLE` or `DEPLETED` to `QUARANTINED`."
    PRD §3.5: "`RESTORE` moves a `QUARANTINED` lot back to `AVAILABLE`, and requires the lot's
    `expiration_date` to still be strictly later than the clock — closing the cycle `AVAILABLE` →
    `QUARANTINED` → `AVAILABLE`."
    PRD §3.5: "Every inventory action increments the lot's `version`, and every one re-runs the
    lot's own days of supply, the building's days-of-supply figures, the protocol status and the
    posture."

    Design: Corner/state_machines/lot_quarantine_restore_cycle_returns_lot_to_available
    """
    school = create_school(name="Kestrel Elementary", building_code="KES39")
    lot = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-KES-1",
                     is_stock_protocol=True, initial_quantity=10)
    assert lot["status"] == "AVAILABLE"
    assert lot["days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert lot["version"] == 1

    quarantined = validate_success(api.lot_inventory_action(
        lot["id"], {"action": "QUARANTINE", "expected_lot_version": lot["version"],
                    "reason_code": "Temperature excursion"}, admin_headers))
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["version"] == 2
    mid = validate_success(api.get_school(school["id"], admin_headers))
    assert mid["epinephrine_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    assert mid["stock_protocol_status"] == "DEPLETED"

    restored = validate_success(api.lot_inventory_action(
        lot["id"], {"action": "RESTORE", "expected_lot_version": quarantined["version"]},
        admin_headers))
    assert restored["status"] == "AVAILABLE"
    assert restored["version"] == 3
    assert restored["days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert restored["received_total"] == 10
    assert restored["quantity_on_hand"] == 10

    after = validate_success(api.get_school(school["id"], admin_headers))
    assert after["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)


def test_only_available_lots_feed_the_buildings_days_of_supply(api, admin_headers):
    """PRD §3.5: "The building's figure for a medication is then the sum of those already-rounded
    per-lot terms across the building's lots of that medication that are `AVAILABLE` and whose
    `expiration_date` is strictly later than the clock, with that sum rounded half up to two
    decimal places once more."
    PRD §3.5: "Quarantined, depleted and expired lots contribute nothing, and a lot expiring
    exactly at the clock instant is excluded."

    Design: Corner/calculations/days_of_supply_input_set_excludes_quarantined_lots
    """
    school = create_school(name="Pinecrest Elementary", building_code="PIN44")
    big = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-PIN-BIG",
                     is_stock_protocol=True, initial_quantity=10)
    small = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-PIN-SML",
                       is_stock_protocol=True, initial_quantity=5,
                       expiration_date="2027-07-31T00:00:00Z")
    assert big["days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert small["days_of_supply"] == pytest.approx(16.67, abs=0.001)

    both = validate_success(api.get_school(school["id"], admin_headers))
    assert both["epinephrine_days_of_supply"] == pytest.approx(50.0, abs=0.001)

    quarantined = inventory_action(small["id"], "QUARANTINE", reason_code="Packaging damage")
    one = validate_success(api.get_school(school["id"], admin_headers))
    assert one["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)

    inventory_action(small["id"], "RESTORE", expected_lot_version=quarantined["version"])
    back = validate_success(api.get_school(school["id"], admin_headers))
    assert back["epinephrine_days_of_supply"] == pytest.approx(50.0, abs=0.001)
    assert back["albuterol_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    assert back["stock_protocol_status"] == "DEPLETED"


def test_thirty_days_of_supply_is_ready_while_a_single_discarded_unit_degrades_it(api, admin_headers):
    """PRD §3.5: "Otherwise, if the epinephrine unit total is strictly less than
    `required_stock_units`, or if the smaller of the building's two days-of-supply figures is
    strictly below 30.00, the status is `DEGRADED`."
    PRD §3.5: "Comparisons use the two-decimal rounded figures and the readiness edge is inclusive:
    exactly 30.00 days is `READY`, while 29.99 is `DEGRADED`."

    Design: Corner/calculations/stock_protocol_status_ready_boundary_exactly_30_days
    """
    ctx = setup_stock_school(
        epinephrine_units=10, albuterol_units=36,
        school_overrides={"name": "Quarry Elementary", "building_code": "QRY45"},
        student_overrides={"full_name": "Quinn Ash", "grade_level": 4,
                           "date_of_birth": "2016-06-06T00:00:00Z",
                           "allergy_severity": "ANAPHYLAXIS"})
    albuterol = ctx["albuterol_lot"]
    assert albuterol["days_of_supply"] == pytest.approx(30.0, abs=0.001)

    at_boundary = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert at_boundary["albuterol_days_of_supply"] == pytest.approx(30.0, abs=0.001)
    assert at_boundary["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert at_boundary["required_stock_units"] == 1
    assert at_boundary["stock_protocol_status"] == "READY"
    assert at_boundary["coverage_posture"] == "FULL"

    discarded = validate_success(api.lot_inventory_action(
        albuterol["id"], {"action": "DISCARD", "expected_lot_version": albuterol["version"],
                          "units": 1, "reason_code": "Dropped canister"}, admin_headers))
    assert discarded["quantity_on_hand"] == 35
    assert discarded["quantity_wasted"] == 1
    assert discarded["received_total"] == 36, "a discard never moves the total"
    assert discarded["days_of_supply"] == pytest.approx(29.17, abs=0.001)

    below = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert below["albuterol_days_of_supply"] == pytest.approx(29.17, abs=0.001)
    assert below["stock_protocol_status"] == "DEGRADED"
    assert below["coverage_posture"] == "FULL", "only DEPLETED downgrades a FULL base posture"


def test_lot_selection_ranks_by_expiry_then_quantity_then_creation_order(api, admin_headers):
    """PRD §3.5: "Candidates are ranked first-expiring-first-out, by `expiration_date` ascending.
    Ties are broken by `quantity_available` ascending, and any remaining tie by `created_at`
    ascending; the random `id` is never consulted at any level, including the final tie-break, so
    the order is a deterministic total order."

    Design: Corner/calculations/stock_lot_selection_ranks_expiration_then_quantity_then_created_at
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Oakspring Elementary", "building_code": "OAK43"},
        student_overrides={"full_name": "Ola Bergman", "grade_level": 5,
                           "date_of_birth": "2015-02-02T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]})
    school_id, nurse_id, student_id = base["school"]["id"], base["nurse"]["id"], base["student"]["id"]
    late = create_lot(school_id, medication_code="ALBUTEROL", lot_number="ALB-LATE",
                      initial_quantity=5, expiration_date="2027-01-01T00:00:00Z")
    early_a = create_lot(school_id, medication_code="ALBUTEROL", lot_number="ALB-EARLY-A",
                         initial_quantity=10, expiration_date="2026-12-01T00:00:00Z")
    early_b = create_lot(school_id, medication_code="ALBUTEROL", lot_number="ALB-EARLY-B",
                         initial_quantity=10, expiration_date="2026-12-01T00:00:00Z")
    order = create_ready_order(student_id, nurse_id, valid_until="2026-11-30T00:00:00Z")
    set_clock(MONDAY_0900)
    visit = open_visit(student_id, school_id, nurse_id, complaint_code="MEDICATION")
    assess_visit(visit["id"], nurse_id, "Scheduled dose")

    resp = api.create_administration_record(
        {"visit_id": visit["id"], "authorization_id": order["id"], "units": 1,
         "expected_authorization_version": order_version(order["id"])},
        make_nurse_headers(nurse_id))
    record = validate_success(resp, 201)

    assert record["lot_id"] == early_a["id"], "earliest expiry, then the first of the two tied rows"
    assert record["lot_id"] != early_b["id"]
    assert record["lot_id"] != late["id"]

    chosen = validate_success(api.get_stock_lot(early_a["id"], admin_headers))
    assert (chosen["quantity_on_hand"], chosen["quantity_reserved"]) == (9, 1)
    untouched = validate_success(api.get_stock_lot(early_b["id"], admin_headers))
    assert (untouched["quantity_on_hand"], untouched["quantity_reserved"]) == (10, 0)
    spare = validate_success(api.get_stock_lot(late["id"], admin_headers))
    assert (spare["quantity_on_hand"], spare["quantity_reserved"]) == (5, 0)


def test_receiving_an_already_expired_lot_is_refused(api, admin_headers):
    """PRD §3.5: "A district administrator receives a lot into a building by naming the
    `school_id`, the `medication_code`, the manufacturer's `lot_number`, whether this is
    undesignated emergency stock via `is_stock_protocol`, an `initial_quantity` of at least 1, and
    an `expiration_date`, which must be strictly later than the logical clock — a lot received
    already at or past its expiry is refused with `ERR_LOT_EXPIRED` at ladder position 39."

    Design: Corner/errors/error_lot_expired_on_create_with_past_expiration_date
    """
    school = create_school(name="Ledger Elementary", building_code="LDG76")

    resp = api.create_stock_lot(
        {"school_id": school["id"], "medication_code": "EPINEPHRINE", "lot_number": "EPI-OLD-1",
         "is_stock_protocol": True, "initial_quantity": 8,
         "expiration_date": "2026-07-01T00:00:00Z"},
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED.value, 409)

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["epinephrine_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    _, meta = validate_paginated(api.list_stock_lots(admin_headers, {"school_id": school["id"]}))
    assert meta["total_count"] == 0


def test_restoring_a_lot_that_never_left_available_is_refused(api, admin_headers):
    """PRD §3.5: "`RESTORE` moves a `QUARANTINED` lot back to `AVAILABLE`, and requires the lot's
    `expiration_date` to still be strictly later than the clock — closing the cycle `AVAILABLE` →
    `QUARANTINED` → `AVAILABLE`."
    PRD §3.5: "A `QUARANTINE` or `RESTORE` attempted on a lot in a state that does not admit it,
    and any action at all on an `EXPIRED` lot, is refused with `ERR_LOT_INVALID_STATE` at ladder
    position 11; an inventory action targeting a lot whose expiration has passed is refused with
    `ERR_LOT_EXPIRED`."

    Design: Corner/errors/error_lot_invalid_state_on_restore_of_an_available_lot
    """
    school = create_school(name="Marden Elementary", building_code="MRD77")
    lot = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-MRD-1",
                     is_stock_protocol=True, initial_quantity=6)

    resp = api.lot_inventory_action(
        lot["id"], {"action": "RESTORE", "expected_lot_version": lot["version"]}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert unchanged["status"] == "AVAILABLE"
    assert unchanged["version"] == 1
    assert unchanged["quantity_on_hand"] == 6
    assert unchanged["received_total"] == 6


def test_discarding_more_units_than_the_lot_holds_is_refused(api, admin_headers):
    """PRD §3.5: "`DISCARD` moves `units` from `quantity_on_hand` to `quantity_wasted` leaving
    `received_total` untouched, and a lot whose `quantity_on_hand` reaches exactly 0 moves
    `AVAILABLE` → `DEPLETED`; a discard that would drive `quantity_on_hand` below zero is refused
    with `ERR_INSUFFICIENT_STOCK` at ladder position 49."

    Design: Corner/errors/error_insufficient_stock_on_discard_below_zero
    """
    school = create_school(name="Norwood Elementary", building_code="NRW78")
    lot = create_lot(school["id"], medication_code="ALBUTEROL", lot_number="ALB-NRW-1",
                     is_stock_protocol=True, initial_quantity=5)

    resp = api.lot_inventory_action(
        lot["id"], {"action": "DISCARD", "expected_lot_version": lot["version"], "units": 10,
                    "reason_code": "Attempted over-discard"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, 409)

    unchanged = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert unchanged["quantity_on_hand"] == 5
    assert unchanged["quantity_wasted"] == 0
    assert unchanged["received_total"] == 5
    assert unchanged["version"] == 1
    assert unchanged["status"] == "AVAILABLE"
    assert_lot_unit_conservation(unchanged)


def test_a_stale_lot_version_is_refused_while_the_fresh_one_succeeds(api, admin_headers):
    """PRD §2.6: "A `POST /health-office/medication-stock-lots/{id}/inventory-action` request must
    carry `expected_lot_version`, holding the client's last observed `version` of the target
    `MedicationStockLot`. If the lot's current `version` differs, the action is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412)."
    PRD §3.5: "`RECEIVE` adds `units` to both `received_total` and `quantity_on_hand`, and returns
    a `DEPLETED` lot to `AVAILABLE`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_rejects_inventory_action
    """
    school = create_school(name="Loom Elementary", building_code="LOM72")
    lot = create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-LOM-1",
                     is_stock_protocol=True, initial_quantity=4)
    stale_version = lot["version"]

    received = validate_success(api.lot_inventory_action(
        lot["id"], {"action": "RECEIVE", "expected_lot_version": stale_version, "units": 6},
        admin_headers))
    assert received["received_total"] == 10
    assert received["quantity_on_hand"] == 10
    assert received["days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert received["version"] == 2

    refused = api.lot_inventory_action(
        lot["id"], {"action": "QUARANTINE", "expected_lot_version": stale_version,
                    "reason_code": "Stale-version quarantine attempt"}, admin_headers)
    validate_error(refused, ApiErrorId.ERR_STALE_LOT_VERSION.value, 412)

    still_available = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert still_available["status"] == "AVAILABLE"
    assert still_available["version"] == 2
    assert validate_success(api.get_school(school["id"], admin_headers))[
        "epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)

    fresh = validate_success(api.lot_inventory_action(
        lot["id"], {"action": "QUARANTINE", "expected_lot_version": received["version"],
                    "reason_code": "Recall confirmed"}, admin_headers))
    assert fresh["status"] == "QUARANTINED"
    assert fresh["version"] == 3
    assert validate_success(api.get_school(school["id"], admin_headers))[
        "epinephrine_days_of_supply"] == pytest.approx(0.0, abs=0.001)


def test_derived_stock_fields_are_visible_within_the_same_request_cycle(api, admin_headers):
    """PRD §3.5: "On receipt, `received_total` and `quantity_on_hand` are both set to the initial
    quantity, `quantity_reserved`, `quantity_administered` and `quantity_wasted` are all 0, and the
    lot's `status` is `AVAILABLE`."
    PRD §2.11: "Derived fields are never stale."
    PRD §3.5: "This status is recomputed immediately after either the days-of-supply calculation or
    the stock requirement runs, on every lot transition, and at the daily checkpoint — and the
    posture is recomputed immediately after it."

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_request_cycle
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Nimbus Elementary", "building_code": "NMB74"},
        student_overrides={"full_name": "Nia Falk", "grade_level": 4,
                           "date_of_birth": "2016-11-21T00:00:00Z",
                           "allergy_severity": "ANAPHYLAXIS"})
    school_id = base["school"]["id"]
    create_lot(school_id, medication_code="ALBUTEROL", lot_number="ALB-NMB-1",
               is_stock_protocol=True, initial_quantity=36)
    before = validate_success(api.get_school(school_id, admin_headers))
    assert before["stock_protocol_status"] == "DEPLETED", "no epinephrine units are held yet"

    resp = api.create_stock_lot(
        {"school_id": school_id, "medication_code": "EPINEPHRINE", "lot_number": "EPI-NMB-1",
         "is_stock_protocol": True, "initial_quantity": 10,
         "expiration_date": "2027-06-30T00:00:00Z"}, admin_headers)
    created = validate_success(resp, 201)
    assert created["days_of_supply"] == pytest.approx(33.33, abs=0.001), \
        "the create response already carries the derived figure"
    assert created["status"] == "AVAILABLE"
    assert created["received_total"] == 10

    after = validate_success(api.get_school(school_id, admin_headers))
    assert after["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert after["albuterol_days_of_supply"] == pytest.approx(30.0, abs=0.001)
    assert after["stock_protocol_status"] == "READY"
    assert after["coverage_posture"] == "FULL"


def test_a_checkpoint_with_nothing_overdue_still_recomputes_the_building(api, admin_headers):
    """PRD §2.5: "It optionally narrows to one building via `school_id`, and it reports `epoch`
    together with seven identifier arrays: `expired_action_plan_ids`, `expired_authorization_ids`,
    `expired_lot_ids`, `expired_disclosure_ids`, `promoted_screening_ids`,
    `voided_administration_ids` and `recomputed_school_ids`."
    PRD §2.5: "The sweep expires action plans whose review date has arrived, expires medication
    orders whose validity window has closed, expires stock lots whose expiration instant has
    arrived, expires approved but unreleased disclosure requests, promotes overdue rescreens to
    referral, and then re-runs the coverage ratio, the stock requirement, the days-of-supply
    figures, the stock protocol status, the building posture and each student's observed risk
    score."

    Design: Corner/endpoints/daily_checkpoint_returns_epoch_and_recomputed_school_ids
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Dunes Elementary", "building_code": "DUN58"},
        student_overrides={"full_name": "Dov Aren", "grade_level": 4,
                           "date_of_birth": "2016-08-08T00:00:00Z"})
    school_id = base["school"]["id"]
    lot = create_lot(school_id, medication_code="EPINEPHRINE", lot_number="EPI-DUN-1",
                     is_stock_protocol=True, initial_quantity=10)

    result = validate_success(api.run_daily_checkpoint({"school_id": school_id}, admin_headers))

    assert "epoch" in result
    assert result["expired_action_plan_ids"] == []
    assert result["expired_authorization_ids"] == []
    assert result["expired_lot_ids"] == []
    assert result["expired_disclosure_ids"] == []
    assert result["promoted_screening_ids"] == []
    assert result["voided_administration_ids"] == []
    assert school_id in result["recomputed_school_ids"]

    assert validate_success(api.get_stock_lot(lot["id"], admin_headers))["status"] == "AVAILABLE"
    building = validate_success(api.get_school(school_id, admin_headers))
    assert building["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert building["albuterol_days_of_supply"] == pytest.approx(0.0, abs=0.001)
    assert building["stock_protocol_status"] == "DEPLETED"
    assert building["coverage_posture"] == "LIMITED"
