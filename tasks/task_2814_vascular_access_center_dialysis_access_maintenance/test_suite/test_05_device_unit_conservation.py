"""Consumable stock: reservation headroom and the conservation invariant.

A lot's units move along two different paths -- consumption takes them off the shelf,
release only gives back the promise -- and the headroom that gates a reservation is
inclusive at both ends, so these scenarios pin the arithmetic of each.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated

CONSUMPTION_CLOCK = "2026-08-01T14:30:00Z"


def _full_sheath_lot_reserved_to_the_boundary(api):
    """A three-unit sheath lot whose entire headroom is taken by one reservation."""
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(api, "SHEATH", received_quantity=3)
    usage = fx.reserve_units(api, bundle["procedure_id"], lot, 3, bundle["operator_headers"])
    return bundle, lot, usage


def test_01_a_reservation_of_the_entire_headroom_is_accepted_at_the_boundary(api):
    """Three units against a headroom of three: the boundary is inclusive.

    The PRD states: "Otherwise the headroom — `quantity_on_hand` minus
    `quantity_reserved` — must be at least the requested `quantity`, boundary inclusive,
    and a request larger than that single lot's headroom is refused with
    `ERR_INSUFFICIENT_DEVICE_STOCK`."

    It also states: "On success a device usage is created with `state` of `RESERVED`,
    `wasted_quantity` 0, `consumed_at` and `released_at` null; the lot's
    `quantity_reserved` increases by the reserved `quantity`, its `quantity_on_hand` is
    untouched, and its `version` increments."

    Design: Difficulty/boundary_precision_check/device_lot_headroom_is_inclusive_and_a_full_lot_stays_available
    """
    _bundle, lot, usage = _full_sheath_lot_reserved_to_the_boundary(api)

    assert usage["state"] == "RESERVED"
    assert usage["quantity"] == 3
    assert usage["wasted_quantity"] == 0
    assert usage["consumed_at"] is None
    assert usage["released_at"] is None

    reserved = fx.read_lot(api, lot["id"])
    assert reserved["received_quantity"] == 3
    assert reserved["quantity_on_hand"] == 3
    assert reserved["quantity_reserved"] == 3
    assert reserved["status"] == "AVAILABLE"
    assert reserved["version"] == lot["version"] + 1
    assertions.assert_lot_headroom(reserved, 0)


def test_02_exhausted_headroom_is_reported_as_depletion_without_depleting_the_lot(api):
    """A further unit is refused for stock, not for a stale version, and nothing changes.

    The PRD states: "A lot whose `status` is `DEPLETED`, or whose headroom is exactly 0,
    is refused with `ERR_LOT_DEPLETED`."

    The refused request declares the lot version it just observed, so the
    expected-version check passes and the stock rule is what fires. Exhausted headroom
    is not depletion: three units are still physically on hand, so the lot stays
    `AVAILABLE` and its version does not move.

    Design: Difficulty/boundary_precision_check/device_lot_headroom_is_inclusive_and_a_full_lot_stays_available
    """
    bundle, lot, usage = _full_sheath_lot_reserved_to_the_boundary(api)
    reserved = fx.read_lot(api, lot["id"])

    refused = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": lot["id"],
            "quantity": 1,
            "expected_device_lot_version": reserved["version"],
        },
        bundle["operator_headers"],
    )
    validate_error(refused, "ERR_LOT_DEPLETED", 409)

    _items, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert meta["total_count"] == 1

    settled = fx.read_lot(api, lot["id"])
    assert settled["status"] == "AVAILABLE"
    assert settled["quantity_on_hand"] == 3
    assert settled["quantity_reserved"] == 3
    assert settled["version"] == reserved["version"]

    unchanged = fx.read_usage(api, usage["id"])
    assert unchanged["state"] == "RESERVED"
    assert unchanged["consumed_at"] is None
    assert unchanged["released_at"] is None


def _lot_with_two_committed_cases(api):
    """A ten-unit balloon lot promised to two cases -- three units and four units.

    The first case is driven as far as recovery with two qualifying observations, so a
    single discharge call can consume its reservation; the second is left SCHEDULED so
    that a cancellation can release its own.
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    fx.seed_reading_pair(api, access["id"], center["facility_id"])

    referrals = []
    for _ in range(2):
        referral = fx.seed_referral(
            api, access["id"], center["facility_id"], missed_treatment_count=0
        )
        referrals.append(fx.triage(api, referral["id"]))

    first = fx.book_case(
        api, referrals[0]["id"], center["room_id"], center["operator_id"],
        referrals[0]["version"], "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        sedation_level="MODERATE", sedation_rn_id=center["nurse_id"],
    )
    second = fx.book_case(
        api, referrals[1]["id"], center["room_id"], center["operator_id"],
        referrals[1]["version"], "2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z",
        sedation_level="MODERATE", sedation_rn_id=center["nurse_id"],
    )

    lot = fx.seed_lot(api, "BALLOON", received_quantity=10)
    usage_one = fx.reserve_units(api, first["id"], lot, 3)
    usage_two = fx.reserve_units(api, second["id"], fx.read_lot(api, lot["id"]), 4)

    bundle = dict(center)
    bundle["procedure_id"] = first["id"]
    fx.set_clock(api, "2026-08-01T13:00:00Z")
    fx.start_case(api, bundle)
    fx.move_to_recovery(api, bundle, "2026-08-01T14:00:00Z")
    fx.chart_discharge_ready_observations(api, bundle)

    return center, access, referrals, (first, second), lot, (usage_one, usage_two), bundle


def test_03_consumption_takes_the_units_off_the_shelf_as_well_as_out_of_reserve(api):
    """A reservation touches only the reserve; the discharge moves both counters.

    The PRD states: "On **consumption** — which happens when the case is discharged or
    aborted — `consumed_at` is set to the clock and both `quantity_on_hand` and
    `quantity_reserved` fall by the usage's `quantity`; on the abort branch the usage's
    `wasted_quantity` is additionally set equal to its `quantity`, because devices
    opened for a case that was abandoned in the room cannot go back on the shelf."

    The discharge branch therefore leaves `wasted_quantity` at 0, and the second case's
    four units are still outstanding, so the lot reads seven on hand against four
    reserved.

    Design: Difficulty/compensating_invariant/device_unit_conservation_survives_one_consumption_and_one_release
    """
    _center, access, referrals, _procedures, lot, usages, bundle = _lot_with_two_committed_cases(api)

    before = fx.read_lot(api, lot["id"])
    assert before["received_quantity"] == 10
    assert before["quantity_on_hand"] == 10
    assert before["quantity_reserved"] == 7
    assert before["status"] == "AVAILABLE"

    fx.set_clock(api, CONSUMPTION_CLOCK)
    discharged = fx.discharge(api, bundle)
    assert discharged["clinical_status"] == "DISCHARGED"

    consumed = fx.read_usage(api, usages[0]["id"])
    assert consumed["state"] == "CONSUMED"
    assert consumed["wasted_quantity"] == 0
    assertions.assert_instant_equals(consumed["consumed_at"], CONSUMPTION_CLOCK, "consumed_at")
    assert consumed["released_at"] is None

    after = fx.read_lot(api, lot["id"])
    assert after["quantity_on_hand"] == 7
    assert after["quantity_reserved"] == 4
    assert after["received_quantity"] == 10
    assert after["status"] == "AVAILABLE"
    assertions.assert_device_unit_conservation(
        after, [consumed, fx.read_usage(api, usages[1]["id"])]
    )

    # The pending second reservation does not disturb the discharge cascade.
    assert fx.read_referral(api, referrals[0]["id"])["status"] == "COMPLETED"
    settled_access = fx.read_access(api, access["id"])
    assert settled_access["status"] == "IN_USE"
    assert settled_access["angioplasty_count"] == 1
    assert settled_access["intervention_burden_score"] == 2
    assertions.assert_burden_score(settled_access)


def test_04_release_gives_back_the_promise_and_not_the_units(api):
    """Cancelling the second case zeroes the reserve while the shelf stays at seven.

    The PRD states: "On **release** — cancellation, quarantine, the expiry sweep, or the
    facility-posture chain — `released_at` is set to the clock and only
    `quantity_reserved` falls."

    An implementation that mirrors the consumption would report eleven units on hand
    against a received quantity of ten. The received quantity itself is the anchor of
    the invariant and is untouched by all five writes the lot has now taken: its
    creation, the two reservations, the consumption and the release.

    Design: Difficulty/compensating_invariant/device_unit_conservation_survives_one_consumption_and_one_release
    """
    _center, _access, referrals, procedures, lot, usages, bundle = _lot_with_two_committed_cases(api)

    fx.set_clock(api, CONSUMPTION_CLOCK)
    fx.discharge(api, bundle)
    cancelled = fx.cancel_case(
        api,
        procedures[1]["id"],
        fx.COORDINATOR,
        cancel_note="patient deferred, units back to the shelf",
    )
    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "COORDINATOR_CANCEL"

    released = fx.read_usage(api, usages[1]["id"])
    assert released["state"] == "RELEASED"
    assert released["wasted_quantity"] == 0
    assertions.assert_instant_equals(released["released_at"], CONSUMPTION_CLOCK, "released_at")
    assert released["consumed_at"] is None

    settled = fx.read_lot(api, lot["id"])
    assert settled["quantity_on_hand"] == 7
    assert settled["quantity_reserved"] == 0
    assert settled["received_quantity"] == 10
    assert settled["status"] == "AVAILABLE"
    assert settled["version"] == 5
    assertions.assert_lot_headroom(settled, 7)
    assertions.assert_device_unit_conservation(
        settled, [fx.read_usage(api, usages[0]["id"]), released]
    )

    # The coordinator cancellation path hands the referral back for rebooking.
    assert fx.read_referral(api, referrals[1]["id"])["status"] == "TRIAGED"
