"""The fleet readiness doctrine: the service_status verdict and its boundary.

A vehicle is service ready only when all four predicates hold at once —
charge at least 80, cleanliness at least 70, calibration signed off, and the
software version equal to its target.  Both numeric comparisons are
inclusive on the low side.
"""

from test_helpers import constants as c
from test_helpers.fixtures import (
    active_territory_with_depot,
    read_vehicle,
    serve_vehicle,
)


class TestReadinessBoundary:
    """A vehicle sitting exactly on a numeric boundary still passes it."""

    def test_vehicle_at_charge_boundary_reads_available(self, api):
        """Charge exactly 80 and cleanliness exactly 70 satisfy both predicates.

        PRD 2.5: "Boundary behaviour is inclusive on both numeric predicates — a
        vehicle sitting exactly at 80 percent charge, or exactly at a cleanliness
        score of 70, is treated as satisfying that predicate and is therefore
        eligible to be reported `AVAILABLE`."
        PRD 3.2: "Because the vehicle is now staged rather than in service, its
        readiness verdict is recomputed — and a vehicle that is fully charged,
        clean, calibrated and on the mandated software becomes `AVAILABLE` the
        moment it is staged, provided it is not roadside-blocked."

        Design: Difficulty/dual_variant_calc/if_match_service_status_boundary_variants
        """
        stack = active_territory_with_depot(api)
        vehicle = serve_vehicle(
            api,
            stack["depot"]["id"],
            stack["territory"]["id"],
            "VIN-BOUND-80",
            battery_pct=80,
            cleanliness_score=70,
        )
        assert vehicle["battery_pct"] == 80
        assert vehicle["cleanliness_score"] == 70
        assert vehicle["calib_valid"] is True
        assert vehicle["software_version"] == vehicle["target_software_version"]
        assert vehicle["status"] == c.VEHICLE_AT_DEPOT
        assert vehicle["service_status"] == c.SERVICE_AVAILABLE, (
            "a vehicle exactly at 80 percent charge and cleanliness 70 must be AVAILABLE; "
            f"got {vehicle['service_status']}"
        )

    def test_vehicle_one_percent_below_charge_boundary_reads_unavailable(self, api):
        """Charge 79 fails the predicate even with everything else ready.

        PRD 2.5: "Four readiness predicates are evaluated on the vehicle's own
        current values, and the vehicle is *service ready* only when all four
        hold simultaneously: `battery_pct` is at least 80, `cleanliness_score`
        is at least 70, `calib_valid` is true, and `software_version` equals
        `target_software_version`."

        Design: Difficulty/dual_variant_calc/if_match_service_status_boundary_variants
        """
        stack = active_territory_with_depot(api)
        vehicle = serve_vehicle(
            api,
            stack["depot"]["id"],
            stack["territory"]["id"],
            "VIN-BOUND-79",
            battery_pct=79,
            cleanliness_score=70,
        )
        assert vehicle["battery_pct"] == 79
        assert vehicle["cleanliness_score"] == 70, (
            "cleanliness is held constant so charge is the only differing predicate"
        )
        assert vehicle["status"] == c.VEHICLE_AT_DEPOT
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE

    def test_vehicle_one_point_below_cleanliness_boundary_reads_unavailable(self, api):
        """Cleanliness 69 fails the predicate even at comfortable charge.

        PRD 2.5: "Boundary behaviour is inclusive on both numeric predicates — a
        vehicle sitting exactly at 80 percent charge, or exactly at a cleanliness
        score of 70, is treated as satisfying that predicate and is therefore
        eligible to be reported `AVAILABLE`."

        Design: Difficulty/dual_variant_calc/if_match_service_status_boundary_variants
        """
        stack = active_territory_with_depot(api)
        vehicle = serve_vehicle(
            api,
            stack["depot"]["id"],
            stack["territory"]["id"],
            "VIN-BOUND-69",
            battery_pct=90,
            cleanliness_score=69,
        )
        assert vehicle["cleanliness_score"] == 69
        assert vehicle["battery_pct"] == 90
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE


class TestReadinessPredicates:
    """Each predicate can single-handedly hold a vehicle out of service."""

    def test_software_mismatch_alone_blocks_availability(self, api):
        """A stale onboard release alone resolves the verdict UNAVAILABLE.

        PRD 2.5: "Four readiness predicates are evaluated on the vehicle's own
        current values, and the vehicle is *service ready* only when all four
        hold simultaneously: `battery_pct` is at least 80, `cleanliness_score`
        is at least 70, `calib_valid` is true, and `software_version` equals
        `target_software_version`."

        Design: Corner/calculations/if_match_service_status_software_mismatch_unavailable
        """
        stack = active_territory_with_depot(api)
        vehicle = serve_vehicle(
            api,
            stack["depot"]["id"],
            stack["territory"]["id"],
            "VIN-SW-STALE",
            battery_pct=90,
            cleanliness_score=90,
            software_version="sw-2026.0",
            target_software_version="sw-2026.1",
        )
        assert vehicle["battery_pct"] == 90
        assert vehicle["cleanliness_score"] == 90
        assert vehicle["calib_valid"] is True
        assert vehicle["software_version"] == "sw-2026.0"
        assert vehicle["target_software_version"] == "sw-2026.1"
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE, (
            "the software equality check alone must block availability"
        )

    def test_freshly_registered_vehicle_can_never_read_available(self, api):
        """A DRAFT vehicle is UNAVAILABLE because AVAILABLE requires AT_DEPOT.

        PRD 2.5: "any other combination — including `DRAFT`, `ROADSIDE` and
        `SUSPENDED` — yields `UNAVAILABLE`. Because reaching `AVAILABLE`
        requires `status` to be `AT_DEPOT`, a freshly registered or suspended
        vehicle can never read `AVAILABLE`."

        Design: Corner/calculations/if_match_service_status_software_mismatch_unavailable
        """
        stack = active_territory_with_depot(api)
        from test_helpers.fixtures import register_vehicle

        vehicle = register_vehicle(
            api,
            stack["territory"]["id"],
            vin="VIN-DRAFT-1",
            battery_pct=100,
            cleanliness_score=100,
            calib_valid=True,
        )
        assert vehicle["status"] == c.VEHICLE_DRAFT
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE
        assert read_vehicle(api, vehicle["id"])["service_status"] == c.SERVICE_UNAVAILABLE