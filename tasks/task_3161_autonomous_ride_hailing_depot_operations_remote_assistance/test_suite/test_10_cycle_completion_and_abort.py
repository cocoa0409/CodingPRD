"""Service-cycle completion preconditions and the compensating invariant.

An aborted cycle delivers none of the four service effects, so a vehicle that
enters a cycle short of readiness comes out no better equipped than it went
in.  A completion, by contrast, is conditional on evidence rather than
assertion.
"""

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CALIBRATION_SIGNOFF_REQUIRED,
    ERR_VEHICLE_NOT_SERVICE_READY,
)
from test_helpers.assertions import get_success_data, validate_error
from test_helpers.fixtures import (
    create_depot,
    create_territory,
    read_vehicle,
    register_vehicle,
    set_clock,
    stage_vehicle,
)
from test_helpers.test_users import DEPOT, FLEET


def _depot_with_bays(api, **positions):
    """An ACTIVE-hosted territory and a depot with the given bay mix."""
    set_clock(api)
    territory = create_territory(
        api, name="Phoenix Metro", region_code="PHX-METRO",
        mapped_pct=100, validation_hours=120,
    )
    depot = create_depot(api, territory["id"], **positions)
    return territory, depot


def _cycle(api, depot_id, vehicle_id, service_kind):
    return get_success_data(
        api.create_cycle(
            depot_id,
            f.create_cycle_payload(vehicle_id=vehicle_id, service_kind=service_kind),
            headers=DEPOT,
        ),
        expected_status=201,
    )


def _reserve(api, depot_id, service_type, vehicle_id, cycle_id, start_utc):
    return get_success_data(
        api.create_bay_slot(
            depot_id,
            f.create_bay_slot_payload(
                service_type=service_type, bay_index=1, start_utc=start_utc,
                duration_seconds=1800, vehicle_id=vehicle_id, cycle_id=cycle_id,
            ),
            headers=DEPOT,
        ),
        expected_status=201,
    )


def _schedule(api, depot_id, cycle_id, slot_id):
    return get_success_data(
        api.schedule_cycle(depot_id, cycle_id, {"bay_slot_id": slot_id}, headers=DEPOT)
    )


class TestAbortCompensatingInvariant:
    """An aborted cycle leaves the vehicle's readiness tuple exactly as it was."""

    def test_aborted_clean_cycle_preserves_the_readiness_tuple(self, api):
        """The aborted cycle's compensating action produces zero drift.

        PRD 3.2: "A cycle that cannot finish is aborted instead: aborting takes
        an `IN_PROGRESS` cycle to `ABORTED`, releases its bay slot to
        `RELEASED`, and recomputes the vehicle's readiness — but note that an
        aborted cycle delivers none of the four service effects, so a vehicle
        whose cycle is aborted comes out no better equipped than it went in."
        PRD 3.2: "Completion of a `CLEAN` cycle sets the vehicle's
        `cleanliness_score` to the `cleanliness_score` supplied in the completion
        request."

        Design: Difficulty/compensating_invariant/if_match_cycle_abort_preserves_readiness_invariant
        """
        territory, depot = _depot_with_bays(
            api, charge_positions=1, cleaning_positions=1,
            calib_positions=0, software_positions=0,
        )
        vehicle = register_vehicle(
            api, territory["id"], vin="VIN-ABORT-1", battery_pct=50,
            cleanliness_score=40, software_version="sw-2026.0",
            target_software_version="sw-2026.1",
        )
        stage_vehicle(api, vehicle["id"], depot["id"])

        charge_cycle = _cycle(api, depot["id"], vehicle["id"], c.KIND_CHARGE)
        charge_slot = _reserve(api, depot["id"], c.KIND_CHARGE, vehicle["id"],
                               charge_cycle["id"], c.BASE_INSTANT)
        _schedule(api, depot["id"], charge_cycle["id"], charge_slot["id"])
        get_success_data(api.start_cycle(depot["id"], charge_cycle["id"], headers=DEPOT))
        get_success_data(
            api.complete_cycle(depot["id"], charge_cycle["id"], {}, headers=DEPOT)
        )
        charged = read_vehicle(api, vehicle["id"])
        assert charged["battery_pct"] == 100, "the completed CHARGE effect stands"

        clean_cycle = _cycle(api, depot["id"], vehicle["id"], c.KIND_CLEAN)
        clean_slot = _reserve(api, depot["id"], c.KIND_CLEAN, vehicle["id"],
                              clean_cycle["id"], "2026-06-01T01:00:00Z")
        _schedule(api, depot["id"], clean_cycle["id"], clean_slot["id"])
        pre = read_vehicle(api, vehicle["id"])

        get_success_data(api.start_cycle(depot["id"], clean_cycle["id"], headers=DEPOT))
        aborted = get_success_data(api.abort_cycle(depot["id"], clean_cycle["id"], headers=DEPOT))
        assert aborted["status"] == c.CYCLE_ABORTED
        assert get_success_data(api.get_bay_slot(clean_slot["id"], headers=DEPOT))["status"] == c.SLOT_RELEASED

        after = read_vehicle(api, vehicle["id"])
        assert after["battery_pct"] == 100
        assert after["cleanliness_score"] == 40, (
            "the aborted CLEAN cycle delivers none of its service effect"
        )
        assert after["calib_valid"] is False
        assert after["software_version"] == "sw-2026.0"
        assert after["service_status"] == pre["service_status"] == c.SERVICE_UNAVAILABLE

        resp = api.return_vehicle_to_service(vehicle["id"], headers=FLEET)
        validate_error(resp, ERR_VEHICLE_NOT_SERVICE_READY, 409)

    def test_abort_delivers_none_of_the_four_service_effects(self, api):
        """The aborted cycle leaves every service-kind field untouched.

        PRD 3.2: "aborting takes an `IN_PROGRESS` cycle to `ABORTED`, releases
        its bay slot to `RELEASED`, and recomputes the vehicle's readiness — but
        note that an aborted cycle delivers none of the four service effects."
        PRD 3.2: "Completion of a `SOFTWARE` cycle sets the vehicle's
        `software_version` to its own `target_software_version`."

        Design: Difficulty/compensating_invariant/if_match_cycle_abort_preserves_readiness_invariant
        """
        territory, depot = _depot_with_bays(
            api, charge_positions=0, cleaning_positions=0,
            calib_positions=0, software_positions=2,
        )
        vehicle = register_vehicle(
            api, territory["id"], vin="VIN-ABORT-2", battery_pct=90,
            cleanliness_score=90, calib_valid=True,
            software_version="sw-2026.0", target_software_version="sw-2026.1",
        )
        stage_vehicle(api, vehicle["id"], depot["id"])
        software_cycle = _cycle(api, depot["id"], vehicle["id"], c.KIND_SOFTWARE)
        slot = _reserve(api, depot["id"], c.KIND_SOFTWARE, vehicle["id"],
                        software_cycle["id"], c.BASE_INSTANT)
        _schedule(api, depot["id"], software_cycle["id"], slot["id"])
        get_success_data(api.start_cycle(depot["id"], software_cycle["id"], headers=DEPOT))
        get_success_data(api.abort_cycle(depot["id"], software_cycle["id"], headers=DEPOT))

        after = read_vehicle(api, vehicle["id"])
        assert after["software_version"] == "sw-2026.0"
        assert after["software_version"] != after["target_software_version"]
        assert after["service_status"] == c.SERVICE_UNAVAILABLE, (
            "the software mismatch still blocks availability"
        )


class TestCycleCompletionPreconditions:
    """Completion is conditional on evidence rather than assertion."""

    def test_calibration_without_signoff_is_refused(self, api):
        """A CALIBRATION cycle needs signed_off true to complete.

        PRD 3.2: "A `CALIBRATION` cycle may not be completed unless the request
        carries `signed_off` set to true; a completion without it is rejected
        with `ERR_CALIBRATION_SIGNOFF_REQUIRED` (HTTP 400)."
        PRD 3.2: "Completion of a `CALIBRATION` cycle sets the vehicle's
        `calib_valid` to the `signed_off` value supplied in the request."

        Design: Corner/state_machines/if_match_cycle_complete_calibration_requires_signoff
        """
        territory, depot = _depot_with_bays(api)
        vehicle = register_vehicle(api, territory["id"], vin="VIN-CAL-1", battery_pct=90,
                                   cleanliness_score=90)
        stage_vehicle(api, vehicle["id"], depot["id"])
        cycle = _cycle(api, depot["id"], vehicle["id"], c.KIND_CALIBRATION)
        slot = _reserve(api, depot["id"], c.KIND_CALIBRATION, vehicle["id"],
                        cycle["id"], c.BASE_INSTANT)
        _schedule(api, depot["id"], cycle["id"], slot["id"])
        get_success_data(api.start_cycle(depot["id"], cycle["id"], headers=DEPOT))

        resp = api.complete_cycle(
            depot["id"], cycle["id"], {"signed_off": False}, headers=DEPOT
        )
        validate_error(resp, ERR_CALIBRATION_SIGNOFF_REQUIRED, 400)

        assert get_success_data(api.get_cycle(cycle["id"], headers=DEPOT))["status"] == c.CYCLE_IN_PROGRESS
        assert read_vehicle(api, vehicle["id"])["calib_valid"] is False

    def test_calibration_with_signoff_completes_and_flips_the_flag(self, api):
        """The same cycle completes when the request carries signed_off true.

        PRD 3.2: "Completion of a `CALIBRATION` cycle sets the vehicle's
        `calib_valid` to the `signed_off` value supplied in the request."

        Design: Corner/state_machines/if_match_cycle_complete_calibration_requires_signoff
        """
        territory, depot = _depot_with_bays(api)
        vehicle = register_vehicle(api, territory["id"], vin="VIN-CAL-2", battery_pct=90,
                                   cleanliness_score=90)
        stage_vehicle(api, vehicle["id"], depot["id"])
        cycle = _cycle(api, depot["id"], vehicle["id"], c.KIND_CALIBRATION)
        slot = _reserve(api, depot["id"], c.KIND_CALIBRATION, vehicle["id"],
                        cycle["id"], c.BASE_INSTANT)
        _schedule(api, depot["id"], cycle["id"], slot["id"])
        get_success_data(api.start_cycle(depot["id"], cycle["id"], headers=DEPOT))

        completed = get_success_data(
            api.complete_cycle(depot["id"], cycle["id"], {"signed_off": True}, headers=DEPOT)
        )
        assert completed["status"] == c.CYCLE_COMPLETED
        after = read_vehicle(api, vehicle["id"])
        assert after["calib_valid"] is True
        assert after["service_status"] == c.SERVICE_AVAILABLE