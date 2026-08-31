"""In-kind intake, the inspection fork, the acceptance cascade and cycle counts."""

from test_helpers import (
    ApiErrorId,
    adjust_inventory,
    assert_inventory_position,
    assert_pct_equals,
    assert_unit_conservation,
    create_active_school,
    create_active_site,
    create_backpack,
    create_batch,
    create_collecting_cycle,
    create_event,
    create_inspected_batch,
    create_pencil,
    create_published_spec,
    create_registration,
    create_supply_item,
    make_site_coordinator_headers,
    move_batch,
    move_cycle,
    move_event,
    read_position,
    read_registration,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
    waitlist_registration,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]


def _accept_cascade_scenario():
    """ACTIVE school with a 4-pencil + 1-backpack kit, a COLLECTING cycle holding one
    backpack and no pencils, a PUBLISHED two-seat event with two WAITLISTED students
    verified a day apart, and an INSPECTED five-unit pencil batch waiting at an ACTIVE
    site."""
    school = create_active_school()
    pencil = create_pencil()
    backpack = create_backpack()
    create_published_spec(school["id"], [(pencil["id"], 4), (backpack["id"], 1)])
    cycle = create_collecting_cycle()
    backpack_position = adjust_inventory(cycle["id"], backpack["id"], 1)
    site = create_active_site(cycle["id"])
    event = create_event(school["id"], cycle["id"], seat_capacity=2)
    event = validate_success(move_event(event["id"], school["id"], "PUBLISHED"))

    first = create_registration(
        event["id"], school["id"], student_reference="S-001", guardian_name="G One"
    )
    verify_registration(first["id"], event["id"], school["id"])
    set_clock("2026-08-02T00:00:00Z")
    second = create_registration(
        event["id"], school["id"], student_reference="S-002", guardian_name="G Two"
    )
    verify_registration(second["id"], event["id"], school["id"])
    waitlist_registration(first["id"], event["id"], school["id"])
    waitlist_registration(second["id"], event["id"], school["id"])

    batch = create_inspected_batch(
        site["id"], pencil["id"], qty_declared=5, condition="NEW", sealed=True
    )
    return {
        "school": school,
        "pencil": pencil,
        "backpack": backpack,
        "cycle": cycle,
        "site": site,
        "event": event,
        "first": first,
        "second": second,
        "batch": batch,
        "backpack_position": backpack_position,
    }


def test_batch_cannot_be_accepted_before_it_has_been_inspected(api):
    """PRD §3.3: "A batch move that is not declared from the batch's current `status`
    is rejected with `ERR_INVALID_BATCH_STATE`."
    PRD §3.3: "The batch is created in `RECEIVED` with `qty_accepted` at 0,
    `qty_rejected` at 0 and `hold_reason` null."

    Design: Corner/state_machines/batch_cannot_be_accepted_before_inspection
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    batch = create_batch(site["id"], pencil["id"], qty_declared=10, condition="NEW", sealed=True)

    response = move_batch(batch["id"], "ACCEPTED", headers=WL, qty_rejected=0)
    validate_error(response, ApiErrorId.ERR_INVALID_BATCH_STATE.value, expected_status=409)

    reread = validate_success(api.get_donation_batch(batch["id"], WL))
    assert reread["status"] == "RECEIVED"
    assert reread["qty_accepted"] == 0

    rows, _ = validate_paginated(
        api.list_inventory_positions(
            WL, params={"drive_cycle_id": cycle["id"], "supply_item_id": pencil["id"]}
        )
    )
    assert all(row["on_hand_qty"] == 0 for row in rows), "a rejected acceptance credits nothing"


def test_hygiene_item_acceptance_requires_sealed_new_stock(api):
    """PRD §3.3: "A hygiene item that arrived unsealed, or sealed but merely
    `GENTLY_USED` or `DAMAGED`, is rejected with `ERR_UNSAFE_ITEM_CONDITION`."

    Design: Corner/state_machines/hygiene_item_acceptance_requires_sealed_new_stock
    """
    cycle = create_collecting_cycle()
    sanitizer = create_supply_item(
        sku="SAN-08",
        name="Hand sanitizer",
        category="HYGIENE",
        unit_cost_cents=320,
        bulk_pack_size=8,
        hygiene_sealed_required=True,
    )
    site = create_active_site(cycle["id"])
    batch = create_inspected_batch(
        site["id"], sanitizer["id"], qty_declared=20, condition="GENTLY_USED", sealed=False
    )

    response = move_batch(batch["id"], "ACCEPTED", headers=WL, qty_rejected=0)
    validate_error(response, ApiErrorId.ERR_UNSAFE_ITEM_CONDITION.value, expected_status=422)

    assert validate_success(api.get_donation_batch(batch["id"], WL))["status"] == "INSPECTED"
    assert validate_success(api.get_collection_site(site["id"], PD))["accepted_item_count"] == 0


def test_donation_intake_is_rejected_once_the_cycle_leaves_collecting(api):
    """PRD §3.3: "Intake is phase-gated: the governing drive cycle must be in
    `COLLECTING`, and a batch recorded against a cycle in any other phase is rejected
    with `ERR_CYCLE_PHASE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/donation_intake_requires_collecting_drive_cycle
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    validate_success(move_cycle(cycle["id"], "SORTING"))

    response = api.create_donation_batch(
        {
            "collection_site_id": site["id"],
            "supply_item_id": pencil["id"],
            "qty_declared": 10,
            "condition": "NEW",
            "sealed": True,
        },
        make_site_coordinator_headers(site["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_PHASE_INVALID.value, expected_status=409)

    assert validate_success(api.get_collection_site(site["id"], PD))["operational_status"] == "ACTIVE"


def test_the_same_intake_is_accepted_while_the_cycle_is_still_collecting(api):
    """PRD §3.3: "Intake is phase-gated: the governing drive cycle must be in
    `COLLECTING`, and a batch recorded against a cycle in any other phase is rejected
    with `ERR_CYCLE_PHASE_INVALID`."
    PRD §3.3: "The batch is created in `RECEIVED` with `qty_accepted` at 0,
    `qty_rejected` at 0 and `hold_reason` null."

    Design: Difficulty/cross_entity_state_dependency/donation_intake_requires_collecting_drive_cycle
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    coordinator = make_site_coordinator_headers(site["id"])
    payload = {
        "collection_site_id": site["id"],
        "supply_item_id": pencil["id"],
        "qty_declared": 10,
        "condition": "NEW",
        "sealed": True,
    }

    accepted = validate_success(api.create_donation_batch(payload, coordinator), expected_status=201)
    assert accepted["status"] == "RECEIVED"

    validate_success(move_cycle(cycle["id"], "SORTING"))
    rejected = api.create_donation_batch(payload, coordinator)
    validate_error(rejected, ApiErrorId.ERR_CYCLE_PHASE_INVALID.value, expected_status=409)

    rows, _ = validate_paginated(
        api.list_donation_batches(WL, params={"collection_site_id": site["id"]})
    )
    assert len(rows) == 1, "only the COLLECTING-phase intake may persist"


def test_quarantine_credits_nothing_and_remediation_clears_the_hold(api):
    """PRD §3.3: "It records that `hold_reason` and credits **nothing** to inventory."
    PRD §3.3: "It recomputes `in_transit_qty` upward as the batch rejoins the
    expectation set, clears `hold_reason` back to null, and increments the batch's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/donation_batch_quarantine_remediate_accept_branch
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    position = adjust_inventory(cycle["id"], pencil["id"], 5)
    batch = create_inspected_batch(
        site["id"], pencil["id"], qty_declared=10, condition="GENTLY_USED", sealed=False
    )

    quarantined = validate_success(
        move_batch(batch["id"], "QUARANTINED", headers=WL, hold_reason="mixed unbranded stock")
    )
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["hold_reason"] == "mixed unbranded stock"

    after_hold = validate_success(api.get_inventory_position(position["id"], WL))
    assert after_hold["on_hand_qty"] == 5, "quarantine credits nothing to on-hand stock"
    assert_unit_conservation(after_hold)

    remediated = validate_success(move_batch(batch["id"], "REMEDIATED", headers=WL))
    assert remediated["status"] == "REMEDIATED"
    assert remediated["hold_reason"] is None


def test_remediated_batch_rejoins_the_accept_path_and_credits_inventory(api):
    """PRD §3.3: "Hop one sets the batch's `qty_accepted` to its `qty_declared` minus
    the supplied `qty_rejected` and moves its `status` to `ACCEPTED`."
    PRD §3.3: "Hop two, caused by hop one, finds the inventory position for the
    cycle-and-item pair — creating it if none exists yet — and then adds `qty_accepted`
    to `on_hand_qty`, adds the full `qty_declared` to `accepted_donated_qty`, adds
    `qty_rejected` to `damaged_qty`, and recomputes `in_transit_qty`."

    Design: Difficulty/non_linear_state_machine/donation_batch_quarantine_remediate_accept_branch
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    position = adjust_inventory(cycle["id"], pencil["id"], 5)
    batch = create_inspected_batch(
        site["id"], pencil["id"], qty_declared=10, condition="GENTLY_USED", sealed=False
    )
    validate_success(
        move_batch(batch["id"], "QUARANTINED", headers=WL, hold_reason="mixed unbranded stock")
    )
    validate_success(move_batch(batch["id"], "REMEDIATED", headers=WL))

    accepted = validate_success(move_batch(batch["id"], "ACCEPTED", headers=WL, qty_rejected=2))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["qty_accepted"] == 8, "10 declared minus 2 rejected"

    reread = validate_success(api.get_inventory_position(position["id"], WL))
    assert_inventory_position(reread)
    assert reread["on_hand_qty"] == 13, "5 already on hand plus the 8 accepted units"
    assert reread["damaged_qty"] == 2
    assert reread["accepted_donated_qty"] == 10, "the declared figure, not the accepted one"
    assert_unit_conservation(reread)


def test_batch_acceptance_credits_stock_the_cycle_and_the_site(api):
    """PRD §3.3: "Hop one sets the batch's `qty_accepted` to its `qty_declared` minus
    the supplied `qty_rejected` and moves its `status` to `ACCEPTED`."
    PRD §3.3: "Hop three, caused by hop two, recomputes the cycle's
    `total_items_on_hand` and adds `qty_accepted` to the site's `accepted_item_count`."

    Design: Difficulty/transitive_cascade/batch_acceptance_five_hop_cascade_promotes_one_waitlisted_student
    """
    scene = _accept_cascade_scenario()

    accepted = validate_success(
        move_batch(scene["batch"]["id"], "ACCEPTED", headers=WL, qty_rejected=1)
    )
    assert accepted["qty_accepted"] == 4, "5 declared minus 1 rejected"

    site = validate_success(api.get_collection_site(scene["site"]["id"], PD))
    assert site["accepted_item_count"] == 4

    cycle = validate_success(api.get_drive_cycle(scene["cycle"]["id"], PD))
    assert cycle["total_items_on_hand"] == 0, (
        "every credited unit was immediately reserved by the promotion sweep"
    )

    pencil_position = read_position(scene["cycle"]["id"], scene["pencil"]["id"])
    assert_unit_conservation(pencil_position)
    assert pencil_position["accepted_donated_qty"] == 5
    assert pencil_position["damaged_qty"] == 1


def test_batch_acceptance_promotes_only_the_earliest_verified_waitlisted_student(api):
    """PRD §3.3: "On each event touched by hop four, registrations sitting in
    `WAITLISTED` are promoted to `CONFIRMED` in order of `verified_at` ascending, with
    `created_at` ascending as the tie-break, and the sweep continues only while two
    conditions both hold: the event's `confirmed_count` is strictly less than its
    `seat_capacity`, and every line of the published needs list has an `on_hand_qty` at
    least equal to that line's `qty_per_student`."
    PRD §3.3: "Each promotion reserves its units — for every line, subtract
    `qty_per_student` from `on_hand_qty` and add it to `reserved_qty` — and then
    refreshes the event's `confirmed_count` and `waitlist_count` along with the
    school's `students_served_interim_count` and `impact_index_interim`."

    Design: Difficulty/transitive_cascade/batch_acceptance_five_hop_cascade_promotes_one_waitlisted_student
    """
    scene = _accept_cascade_scenario()

    validate_success(move_batch(scene["batch"]["id"], "ACCEPTED", headers=WL, qty_rejected=1))

    first = read_registration(scene["first"]["id"])
    second = read_registration(scene["second"]["id"])
    assert first["eligibility_status"] == "CONFIRMED", "the earliest verified student is promoted"
    assert second["eligibility_status"] == "WAITLISTED", "stock only covered one kit"
    assert first["reserved_unit_count"] == 5, "4 pencils plus 1 backpack"

    event = validate_success(api.get_distribution_event(scene["event"]["id"], PD))
    assert event["confirmed_count"] == 1
    assert event["waitlist_count"] == 1
    assert_pct_equals(event["provisional_fill_pct"], 0.00, "provisional_fill_pct")

    backpack_position = validate_success(
        api.get_inventory_position(scene["backpack_position"]["id"], WL)
    )
    assert backpack_position["on_hand_qty"] == 0
    assert backpack_position["reserved_qty"] == 1
    assert_unit_conservation(backpack_position)

    school = validate_success(api.get_school(scene["school"]["id"], PD))
    assert school["students_served_interim_count"] == 1


def test_first_cycle_count_creates_the_position_lazily(api):
    """PRD §3.3: "Physical counts drift, so a `WarehouseLead` may post a cycle-count
    adjustment naming a `drive_cycle_id`, a `supply_item_id`, a signed
    `delta_on_hand_qty`, an optional signed `delta_damaged_qty`, and a `reason`
    explaining the correction; the position is created if it does not yet exist."
    PRD §3.3: "The adjustment adds `delta_on_hand_qty` to `on_hand_qty`, adds
    `delta_damaged_qty` to `damaged_qty`, and adds the sum of those two deltas to
    `adjustment_qty` so that the conservation identity continues to hold."

    Design: Corner/entities/inventory_position_is_created_lazily_by_first_adjustment
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()

    position = validate_success(
        api.adjust_inventory_position(
            {
                "drive_cycle_id": cycle["id"],
                "supply_item_id": pencil["id"],
                "delta_on_hand_qty": 12,
                "reason": "opening count",
            },
            WL,
        )
    )
    assert_inventory_position(position)
    assert position["on_hand_qty"] == 12
    assert position["adjustment_qty"] == 12
    assert position["reserved_qty"] == 0
    assert position["distributed_qty"] == 0
    assert position["damaged_qty"] == 0
    assert_unit_conservation(position)

    cycle_after = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert cycle_after["total_items_on_hand"] == 12

    rows, _ = validate_paginated(
        api.list_inventory_positions(WL, params={"drive_cycle_id": cycle["id"]})
    )
    assert len(rows) == 1


def test_adjustment_response_already_shows_the_recomputed_position(api):
    """PRD §3.3: "On success the cycle's `total_items_on_hand` is recomputed, every
    `PUBLISHED` distribution event touching the item has its `provisional_fill_pct`
    recomputed and its waitlist promoted by exactly the sweep described as hop five
    above, and both the position's `version` and the cycle's `version` are incremented
    by 1."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created
    and is incremented by exactly 1 on every mutation of that resource, whether the
    mutation was requested directly or was produced as a downstream effect of some
    other operation."

    Design: Corner/consistency_model/adjustment_cascade_is_visible_in_the_same_response
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    position = adjust_inventory(cycle["id"], pencil["id"], 10)

    second = validate_success(
        api.adjust_inventory_position(
            {
                "drive_cycle_id": cycle["id"],
                "supply_item_id": pencil["id"],
                "delta_on_hand_qty": 15,
                "reason": "second count",
            },
            WL,
        )
    )
    assert second["id"] == position["id"]
    assert second["on_hand_qty"] == 25, "the response itself must already show the new total"
    assert second["adjustment_qty"] == 25
    assert second["version"] == 2, "created at version 1, incremented once by the second count"

    cycle_after = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert cycle_after["total_items_on_hand"] == 25
