"""Depot bay utilisation, posture escalation and bay-window geometry.

A depot's posture is a function of how full its bay pool is at the logical
clock: reserved slots count from the instant their window opens, the
percentage is floored before any comparison, and the congestion threshold is
inclusive.  Bay windows are half-open, so a slot starting exactly at another
slot's end is admitted while one starting a second earlier collides.
"""

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.api_errors import ERR_BAY_SLOT_CONFLICT, ERR_POSTURE_LOCKDOWN
from test_helpers.assertions import get_success_data, validate_error
from test_helpers.fixtures import (
    active_territory_with_depot,
    read_depot,
    read_vehicle,
    register_vehicle,
)
from test_helpers.test_users import DEPOT, FLEET


_CLIENT = None


def _client():
    """A module-level client; the server address comes from the environment."""
    global _CLIENT
    if _CLIENT is None:
        from test_helpers.api_client import ApiClient

        _CLIENT = ApiClient()
    return _CLIENT


def _cycle(depot_id, vehicle_id, service_kind=c.KIND_CHARGE):
    """Create an unscheduled cycle for a vehicle under a depot."""
    return get_success_data(
        _client().create_cycle(
            depot_id,
            f.create_cycle_payload(vehicle_id=vehicle_id, service_kind=service_kind),
            headers=DEPOT,
        ),
        expected_status=201,
    )


def _reserve(depot_id, service_type, bay_index, vehicle_id, cycle_id,
             start_utc=c.BASE_INSTANT, duration_seconds=1800):
    """Reserve one bay slot on a depot for a cycle."""
    return get_success_data(
        _client().create_bay_slot(
            depot_id,
            f.create_bay_slot_payload(
                service_type=service_type,
                bay_index=bay_index,
                start_utc=start_utc,
                duration_seconds=duration_seconds,
                vehicle_id=vehicle_id,
                cycle_id=cycle_id,
            ),
            headers=DEPOT,
        ),
        expected_status=201,
    )


class TestDepotOccupancyBoundary:
    """The congestion threshold is inclusive and applied to a floored percent."""

    def test_four_of_five_reserved_bays_read_eighty_and_congested(self, api):
        """Four reserved bays out of five sit exactly on the 80 percent gate.

        PRD 2.6: "The pool size is the sum of `charge_positions`,
        `cleaning_positions`, `calib_positions`, and `software_positions` for
        that depot. `occupancy_pct` is the occupied count divided by the pool
        size, multiplied by 100, floored to a whole integer, and capped at 100."
        PRD 2.6: "Posture then follows three ordered outcomes: at exactly 100
        percent occupancy the depot is `LOCKDOWN`; otherwise at 80 percent
        occupancy or above it is `CONGESTED`; otherwise it is `OPEN`."
        PRD 2.6: "Note that a slot counts from the moment its window opens even
        if the cycle that owns it has not yet begun, so a depot can read as
        crowded purely on the strength of reservations."

        Design: Difficulty/boundary_precision_check/if_match_depot_occupancy_pct_boundary
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 2, "cleaning_positions": 1,
                                  "calib_positions": 1, "software_positions": 1}
        )
        territory, depot_a = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-OCC-1")
        cycle = _cycle(depot_a["id"], vehicle["id"], c.KIND_CHARGE)
        for service_type, bay_index in [
            (c.KIND_CHARGE, 1), (c.KIND_CHARGE, 2),
            (c.KIND_CLEAN, 1), (c.KIND_CALIBRATION, 1),
        ]:
            _reserve(depot_a["id"], service_type, bay_index, vehicle["id"], cycle["id"])

        read = read_depot(api, depot_a["id"])
        assert read["occupancy_pct"] == 80, (
            f"4 of 5 bays must floor to exactly 80, got {read['occupancy_pct']}"
        )
        assert read["posture"] == c.DEPOT_CONGESTED, (
            f"80 percent is at or above the congestion threshold, got {read['posture']}"
        )

    def test_ten_percent_occupancy_reads_open(self, api):
        """A depot with one of ten bays taken stays OPEN.

        PRD 2.6: "Posture then follows three ordered outcomes: at exactly 100
        percent occupancy the depot is `LOCKDOWN`; otherwise at 80 percent
        occupancy or above it is `CONGESTED`; otherwise it is `OPEN`."

        Design: Difficulty/boundary_precision_check/if_match_depot_occupancy_pct_boundary
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 4, "cleaning_positions": 2,
                                  "calib_positions": 2, "software_positions": 2}
        )
        territory, depot_b = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-OCC-2")
        cycle = _cycle(depot_b["id"], vehicle["id"], c.KIND_CHARGE)
        _reserve(depot_b["id"], c.KIND_CHARGE, 1, vehicle["id"], cycle["id"])

        read = read_depot(api, depot_b["id"])
        assert read["occupancy_pct"] == 10
        assert read["posture"] == c.DEPOT_OPEN

    def test_full_bay_pool_reads_lockdown(self, api):
        """A depot at exactly 100 percent occupancy is LOCKDOWN.

        PRD 2.6: "Posture then follows three ordered outcomes: at exactly 100
        percent occupancy the depot is `LOCKDOWN`; otherwise at 80 percent
        occupancy or above it is `CONGESTED`; otherwise it is `OPEN`."

        Design: Difficulty/boundary_precision_check/if_match_depot_occupancy_pct_boundary
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 2, "cleaning_positions": 1,
                                  "calib_positions": 1, "software_positions": 1}
        )
        territory, depot_a = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-OCC-3")
        cycle = _cycle(depot_a["id"], vehicle["id"], c.KIND_CHARGE)
        for service_type, bay_index in [
            (c.KIND_CHARGE, 1), (c.KIND_CHARGE, 2),
            (c.KIND_CLEAN, 1), (c.KIND_CALIBRATION, 1), (c.KIND_SOFTWARE, 1),
        ]:
            _reserve(depot_a["id"], service_type, bay_index, vehicle["id"], cycle["id"])

        read = read_depot(api, depot_a["id"])
        assert read["occupancy_pct"] == 100
        assert read["posture"] == c.DEPOT_LOCKDOWN


class TestLockdownBlocksCycleStart:
    """A sealed depot refuses a new cycle start."""

    def test_lockdown_depot_refuses_a_scheduled_cycle_start(self, api):
        """The otherwise-valid scheduled cycle is refused with ERR_POSTURE_LOCKDOWN.

        PRD 3.2: "And the depot must not be sealed: a depot in `LOCKDOWN`
        posture refuses the start with `ERR_POSTURE_LOCKDOWN` (HTTP 409)."
        PRD 2.6: "A depot in `LOCKDOWN` refuses new cycle starts with
        `ERR_POSTURE_LOCKDOWN`."

        Design: Difficulty/cross_entity_state_dependency/if_match_cycle_start_requires_depot_not_lockdown
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 1}
        )
        territory, depot_s = stack["territory"], stack["depot"]
        v1 = register_vehicle(api, territory["id"], vin="VIN-LOCK-1")
        v2 = register_vehicle(api, territory["id"], vin="VIN-LOCK-2")
        cy1 = _cycle(depot_s["id"], v1["id"], c.KIND_SOFTWARE)
        cy2 = _cycle(depot_s["id"], v2["id"], c.KIND_SOFTWARE)
        sl1 = _reserve(depot_s["id"], c.KIND_SOFTWARE, 1, v1["id"], cy1["id"])
        get_success_data(
            api.schedule_cycle(depot_s["id"], cy1["id"], {"bay_slot_id": sl1["id"]}, headers=DEPOT)
        )
        _reserve(depot_s["id"], c.KIND_SOFTWARE, 1, v2["id"], cy2["id"],
                 start_utc="2026-06-01T02:00:00Z")

        read = read_depot(api, depot_s["id"])
        assert read["occupancy_pct"] == 100
        assert read["posture"] == c.DEPOT_LOCKDOWN

        cycle_read = get_success_data(api.get_cycle(cy1["id"], headers=DEPOT))
        assert cycle_read["is_scheduled"] is True
        assert cycle_read["status"] == c.CYCLE_STAGED

        resp = api.start_cycle(depot_s["id"], cy1["id"], headers=DEPOT)
        validate_error(resp, ERR_POSTURE_LOCKDOWN, 409)

    def test_roomy_depot_accepts_the_same_scheduled_cycle_start(self, api):
        """With the depot below lockdown the identical start succeeds.

        PRD 3.2: "When all three pass, the cycle moves from `STAGED` to
        `IN_PROGRESS`, its reserved bay slot moves to `ACTIVE`, and the depot's
        occupancy is recomputed."

        Design: Difficulty/cross_entity_state_dependency/if_match_cycle_start_requires_depot_not_lockdown
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 2}
        )
        territory, depot_s = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-LOCK-3")
        cycle = _cycle(depot_s["id"], vehicle["id"], c.KIND_SOFTWARE)
        slot = _reserve(depot_s["id"], c.KIND_SOFTWARE, 1, vehicle["id"], cycle["id"])
        get_success_data(
            api.schedule_cycle(depot_s["id"], cycle["id"], {"bay_slot_id": slot["id"]}, headers=DEPOT)
        )
        assert read_depot(api, depot_s["id"])["posture"] == c.DEPOT_OPEN

        started = get_success_data(api.start_cycle(depot_s["id"], cycle["id"], headers=DEPOT))
        assert started["status"] == c.CYCLE_IN_PROGRESS
        assert get_success_data(api.get_bay_slot(slot["id"], headers=DEPOT))["status"] == c.SLOT_ACTIVE


class TestBayWindowGeometry:
    """Bay windows are half-open: [start_utc, end_utc)."""

    def test_window_starting_inside_an_existing_slot_collides(self, api):
        """A reservation beginning 31 minutes into a one-hour slot is refused.

        PRD 3.2: "Two slots on the same depot, the same service type and the
        same `bay_index` may never overlap: a reservation whose half-open window
        intersects an existing `RESERVED` or `ACTIVE` slot on that bay is
        rejected with `ERR_BAY_SLOT_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/if_match_bayslot_half_open_window_conflict
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 1}
        )
        territory, depot_c = stack["territory"], stack["depot"]
        v1 = register_vehicle(api, territory["id"], vin="VIN-HO-1")
        v2 = register_vehicle(api, territory["id"], vin="VIN-HO-2")
        cx1 = _cycle(depot_c["id"], v1["id"], c.KIND_SOFTWARE)
        cx2 = _cycle(depot_c["id"], v2["id"], c.KIND_SOFTWARE)
        s1 = _reserve(depot_c["id"], c.KIND_SOFTWARE, 1, v1["id"], cx1["id"],
                      duration_seconds=3600)
        assert s1["end_utc"] == "2026-06-01T01:00:00Z"

        resp = api.create_bay_slot(
            depot_c["id"],
            f.create_bay_slot_payload(
                service_type=c.KIND_SOFTWARE, bay_index=1,
                start_utc="2026-06-01T00:31:00Z", duration_seconds=3600,
                vehicle_id=v2["id"], cycle_id=cx2["id"],
            ),
            headers=DEPOT,
        )
        validate_error(resp, ERR_BAY_SLOT_CONFLICT, 409)

    def test_window_starting_exactly_at_the_previous_end_is_admitted(self, api):
        """A reservation beginning exactly at the prior slot's end is legal.

        PRD 3.2: "because the sharing of a half-open interval means a slot
        starting exactly at another slot's `end_utc` is legal while one starting
        a second earlier is not."

        Design: Difficulty/resource_temporal_overlap/if_match_bayslot_half_open_window_conflict
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 1}
        )
        territory, depot_c = stack["territory"], stack["depot"]
        v1 = register_vehicle(api, territory["id"], vin="VIN-HO-3")
        v2 = register_vehicle(api, territory["id"], vin="VIN-HO-4")
        cx1 = _cycle(depot_c["id"], v1["id"], c.KIND_SOFTWARE)
        cx2 = _cycle(depot_c["id"], v2["id"], c.KIND_SOFTWARE)
        s1 = _reserve(depot_c["id"], c.KIND_SOFTWARE, 1, v1["id"], cx1["id"],
                      duration_seconds=3600)

        s2 = _reserve(depot_c["id"], c.KIND_SOFTWARE, 1, v2["id"], cx2["id"],
                      start_utc="2026-06-01T01:00:00Z", duration_seconds=3600)
        assert s2["status"] == c.SLOT_RESERVED
        assert s2["start_utc"] == "2026-06-01T01:00:00Z"
        assert s1["end_utc"] == s2["start_utc"], "the shared edge belongs to the later window"

    def test_window_starting_one_second_early_collides(self, api):
        """One second before the previous end is still an intersection.

        PRD 3.2: "because the sharing of a half-open interval means a slot
        starting exactly at another slot's `end_utc` is legal while one starting
        a second earlier is not."

        Design: Difficulty/resource_temporal_overlap/if_match_bayslot_half_open_window_conflict
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 1}
        )
        territory, depot_c = stack["territory"], stack["depot"]
        v1 = register_vehicle(api, territory["id"], vin="VIN-HO-5")
        v2 = register_vehicle(api, territory["id"], vin="VIN-HO-6")
        cx1 = _cycle(depot_c["id"], v1["id"], c.KIND_SOFTWARE)
        cx2 = _cycle(depot_c["id"], v2["id"], c.KIND_SOFTWARE)
        _reserve(depot_c["id"], c.KIND_SOFTWARE, 1, v1["id"], cx1["id"], duration_seconds=3600)

        resp = api.create_bay_slot(
            depot_c["id"],
            f.create_bay_slot_payload(
                service_type=c.KIND_SOFTWARE, bay_index=1,
                start_utc="2026-06-01T00:59:59Z", duration_seconds=60,
                vehicle_id=v2["id"], cycle_id=cx2["id"],
            ),
            headers=DEPOT,
        )
        validate_error(resp, ERR_BAY_SLOT_CONFLICT, 409)


class TestBayReleaseRestoresOccupancy:
    """Reserving and releasing a bay conserves the depot's occupancy."""

    def test_release_returns_occupancy_to_its_pre_reservation_value(self, api):
        """Two reserved bays of two read LOCKDOWN; releasing one restores OPEN.

        PRD 3.2: "A technician may also release a reservation, taking it from
        `RESERVED` to `RELEASED`, which frees the window immediately."
        PRD 2.6: "The occupied count is the number of distinct `service_type` and
        `bay_index` pairings across that depot's bay slots whose `status` is
        either `RESERVED` or `ACTIVE` and whose window already contains the
        reference instant."

        Design: Difficulty/compensating_invariant/if_match_bayslot_release_restores_occupancy_invariant
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 0, "cleaning_positions": 0,
                                  "calib_positions": 0, "software_positions": 2}
        )
        territory, depot_n = stack["territory"], stack["depot"]
        v1 = register_vehicle(api, territory["id"], vin="VIN-INV-1")
        v2 = register_vehicle(api, territory["id"], vin="VIN-INV-2")
        cz1 = _cycle(depot_n["id"], v1["id"], c.KIND_SOFTWARE)
        cz2 = _cycle(depot_n["id"], v2["id"], c.KIND_SOFTWARE)
        _reserve(depot_n["id"], c.KIND_SOFTWARE, 1, v1["id"], cz1["id"])

        pre = read_depot(api, depot_n["id"])
        assert pre["occupancy_pct"] == 50
        assert pre["posture"] == c.DEPOT_OPEN

        sl2 = _reserve(depot_n["id"], c.KIND_SOFTWARE, 2, v2["id"], cz2["id"])
        mid = read_depot(api, depot_n["id"])
        assert mid["occupancy_pct"] == 100
        assert mid["posture"] == c.DEPOT_LOCKDOWN

        get_success_data(api.release_bay_slot(depot_n["id"], sl2["id"], headers=DEPOT))
        after = read_depot(api, depot_n["id"])
        assert after["occupancy_pct"] == pre["occupancy_pct"] == 50
        assert after["posture"] == pre["posture"] == c.DEPOT_OPEN

    def test_release_drops_a_congested_depot_back_to_open(self, api):
        """Four of five reserved bays (CONGESTED) fall to three (OPEN).

        PRD 2.6: "Movement between `OPEN` and `CONGESTED` is symmetric in the
        threshold — the depot returns to `OPEN` the moment `occupancy_pct` falls
        back below 80."

        Design: Difficulty/compensating_invariant/if_match_bayslot_release_restores_occupancy_invariant
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 2, "cleaning_positions": 1,
                                  "calib_positions": 1, "software_positions": 1}
        )
        territory, depot = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-INV-3")
        cycle = _cycle(depot["id"], vehicle["id"], c.KIND_CHARGE)
        slots = [
            _reserve(depot["id"], service_type, bay_index, vehicle["id"], cycle["id"])
            for service_type, bay_index in [
                (c.KIND_CHARGE, 1), (c.KIND_CHARGE, 2),
                (c.KIND_CLEAN, 1), (c.KIND_CALIBRATION, 1),
            ]
        ]
        assert read_depot(api, depot["id"])["posture"] == c.DEPOT_CONGESTED

        get_success_data(api.release_bay_slot(depot["id"], slots[-1]["id"], headers=DEPOT))
        after = read_depot(api, depot["id"])
        assert after["occupancy_pct"] == 60
        assert after["posture"] == c.DEPOT_OPEN


class TestReservedSlotsCountTowardPosture:
    """Occupancy counts reservations, not only started cycles."""

    def test_reserved_only_depot_reads_eighty_percent_congested(self, api):
        """Four merely reserved bays of five already read CONGESTED.

        PRD 2.6: "The occupied count is the number of distinct `service_type` and
        `bay_index` pairings across that depot's bay slots whose `status` is
        either `RESERVED` or `ACTIVE` and whose window already contains the
        reference instant — the window being half-open, meaning a slot counts
        from its `start_utc` up to but not including its `end_utc`."
        PRD 2.6: "Note that a slot counts from the moment its window opens even
        if the cycle that owns it has not yet begun, so a depot can read as
        crowded purely on the strength of reservations."

        Design: Corner/calculations/if_match_depot_posture_counts_reserved_slots
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 2, "cleaning_positions": 1,
                                  "calib_positions": 1, "software_positions": 1}
        )
        territory, depot = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-RES-1")
        cycle = _cycle(depot["id"], vehicle["id"], c.KIND_CHARGE)
        slots = [
            _reserve(depot["id"], service_type, bay_index, vehicle["id"], cycle["id"])
            for service_type, bay_index in [
                (c.KIND_CHARGE, 1), (c.KIND_CHARGE, 2),
                (c.KIND_CLEAN, 1), (c.KIND_CALIBRATION, 1),
            ]
        ]
        assert all(slot["status"] == c.SLOT_RESERVED for slot in slots)

        read = read_depot(api, depot["id"])
        assert read["occupancy_pct"] == 80
        assert read["posture"] == c.DEPOT_CONGESTED

        cycles = get_success_data(api.list_depot_cycles(depot["id"], headers=DEPOT))
        assert all(cycle_row["status"] != c.CYCLE_IN_PROGRESS for cycle_row in cycles), (
            "no cycle has started, yet the reservations alone drive the posture"
        )

    def test_freeing_a_reservation_lowers_the_posture_again(self, api):
        """Releasing one of the four reservations drops the depot to OPEN.

        PRD 2.6: "Slots in `COMPLETED` or `RELEASED` status, and slots whose
        windows lie entirely in the future, do not count."

        Design: Corner/calculations/if_match_depot_posture_counts_reserved_slots
        """
        stack = active_territory_with_depot(
            api, depot_overrides={"charge_positions": 2, "cleaning_positions": 1,
                                  "calib_positions": 1, "software_positions": 1}
        )
        territory, depot = stack["territory"], stack["depot"]
        vehicle = register_vehicle(api, territory["id"], vin="VIN-RES-2")
        cycle = _cycle(depot["id"], vehicle["id"], c.KIND_CHARGE)
        slots = [
            _reserve(depot["id"], service_type, bay_index, vehicle["id"], cycle["id"])
            for service_type, bay_index in [
                (c.KIND_CHARGE, 1), (c.KIND_CHARGE, 2),
                (c.KIND_CLEAN, 1), (c.KIND_CALIBRATION, 1),
            ]
        ]
        get_success_data(api.release_bay_slot(depot["id"], slots[0]["id"], headers=DEPOT))

        read = read_depot(api, depot["id"])
        assert read["occupancy_pct"] == 60
        assert read["posture"] == c.DEPOT_OPEN
        assert get_success_data(api.get_bay_slot(slots[0]["id"], headers=DEPOT))["status"] == c.SLOT_RELEASED


class TestCycleCompletionIsImmediatelyVisible:
    """A cycle completion is reflected with no lag or reconcile step."""

    def test_charge_completion_makes_the_vehicle_available_at_once(self, api):
        """The very next vehicle read already reflects battery and verdict.

        PRD 3.2: "Completing a cycle whose `service_kind` is `CHARGE` sets the
        vehicle's `battery_pct` to 100."
        PRD 3.2: "In every case the cycle's bay slot moves to `COMPLETED` and its
        window is released back to the pool, the vehicle's readiness verdict is
        recomputed under section 2.5 — which is what can finally make it
        `AVAILABLE` — and the depot's occupancy is recomputed under section 2.6."

        Design: Corner/consistency_model/if_match_cycle_complete_side_effects_visible_in_same_response
        """
        stack = active_territory_with_depot(api)
        territory, depot = stack["territory"], stack["depot"]
        vehicle = register_vehicle(
            api, territory["id"], vin="VIN-SYNC-1", battery_pct=50,
            cleanliness_score=90, calib_valid=True,
        )
        get_success_data(
            api.stage_vehicle(vehicle["id"], {"depot_id": depot["id"]}, headers=FLEET)
        )
        cycle = _cycle(depot["id"], vehicle["id"], c.KIND_CHARGE)
        slot = _reserve(depot["id"], c.KIND_CHARGE, 1, vehicle["id"], cycle["id"])
        get_success_data(
            api.schedule_cycle(depot["id"], cycle["id"], {"bay_slot_id": slot["id"]}, headers=DEPOT)
        )
        get_success_data(api.start_cycle(depot["id"], cycle["id"], headers=DEPOT))
        before = read_vehicle(api, vehicle["id"])
        assert before["battery_pct"] == 50
        assert before["service_status"] == c.SERVICE_UNAVAILABLE

        completed = get_success_data(
            api.complete_cycle(depot["id"], cycle["id"], {}, headers=DEPOT)
        )
        assert completed["status"] == c.CYCLE_COMPLETED

        after = read_vehicle(api, vehicle["id"])
        assert after["battery_pct"] == 100
        assert after["service_status"] == c.SERVICE_AVAILABLE
        assert after["version"] == 3, (
            f"created at version 1, staged at 2, cycle completion at 3; got {after['version']}"
        )

    def test_charge_completion_releases_the_bay_slot(self, api):
        """The completing cycle's bay slot moves to COMPLETED in the same call.

        PRD 3.2: "In every case the cycle's bay slot moves to `COMPLETED` and its
        window is released back to the pool."

        Design: Corner/consistency_model/if_match_cycle_complete_side_effects_visible_in_same_response
        """
        stack = active_territory_with_depot(api)
        territory, depot = stack["territory"], stack["depot"]
        vehicle = register_vehicle(
            api, territory["id"], vin="VIN-SYNC-2", battery_pct=50,
            cleanliness_score=90, calib_valid=True,
        )
        get_success_data(
            api.stage_vehicle(vehicle["id"], {"depot_id": depot["id"]}, headers=FLEET)
        )
        cycle = _cycle(depot["id"], vehicle["id"], c.KIND_CHARGE)
        slot = _reserve(depot["id"], c.KIND_CHARGE, 1, vehicle["id"], cycle["id"])
        get_success_data(
            api.schedule_cycle(depot["id"], cycle["id"], {"bay_slot_id": slot["id"]}, headers=DEPOT)
        )
        get_success_data(api.start_cycle(depot["id"], cycle["id"], headers=DEPOT))

        get_success_data(api.complete_cycle(depot["id"], cycle["id"], {}, headers=DEPOT))
        assert get_success_data(api.get_bay_slot(slot["id"], headers=DEPOT))["status"] == c.SLOT_COMPLETED
        assert read_depot(api, depot["id"])["occupancy_pct"] == 0