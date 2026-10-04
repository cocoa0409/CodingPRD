"""Territory expansion gates, concurrency guards, segregation of duties and
the shapes a freshly registered resource is required to carry.
"""

from test_helpers import constants as c
from test_helpers.api_errors import (
    ERR_CROSS_TERRITORY,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    active_territory_with_depot,
    create_territory,
    read_territory,
    register_vehicle,
    set_clock,
)
from test_helpers.test_users import DEPOT, FLEET, MAPPING, PLANNER, SAFETY


class TestVehicleRegistrationShape:
    """A freshly registered vehicle is server-minted, not client-steered."""

    def test_create_ignores_client_supplied_system_fields(self, api):
        """status, verdict, credit and version come back minted by the server.

        PRD 3.2: "A new vehicle comes up in `DRAFT` status with `service_status`
        `UNAVAILABLE`, `credit_cents` 0, `is_roadside_blocked` false,
        `current_depot_id` null, and `delay_ops_runs` 0."
        PRD 2.4: "The `version` field is a system-managed integer that starts at
        1 on creation and increments by exactly 1 on every mutation a resource
        undergoes."

        Design: Corner/entities/if_match_vehicle_create_ignores_input_system_fields
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        vehicle = register_vehicle(
            api, territory["id"], vin="VIN-0001", battery_pct=90,
            cleanliness_score=90,
            status=c.VEHICLE_IN_SERVICE, service_status=c.SERVICE_AVAILABLE,
            credit_cents=999, version=42,
        )
        assert vehicle["status"] == c.VEHICLE_DRAFT
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE
        assert vehicle["credit_cents"] == 0
        assert vehicle["is_roadside_blocked"] is False
        assert vehicle["current_depot_id"] is None
        assert vehicle["version"] == 1

    def test_optional_defaults_are_applied_on_omission(self, api):
        """Omitting cleanliness_score and calib_valid applies their defaults.

        PRD 3.2: "A `FleetOperations` operator registers a vehicle with a `vin`,
        an initial `battery_pct`, an optional `cleanliness_score`, an optional
        `calib_valid`, its `software_version`, and the fleet-mandated
        `target_software_version`."

        Design: Corner/entities/if_match_vehicle_optional_defaults_applied
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        vehicle = register_vehicle(api, territory["id"], vin="VIN-DEF-1", battery_pct=90)
        assert vehicle["cleanliness_score"] == c.DEFAULT_CLEANLINESS_SCORE
        assert vehicle["calib_valid"] is False
        assert vehicle["service_status"] == c.SERVICE_UNAVAILABLE

    def test_missing_required_field_is_a_malformed_request(self, api):
        """Omitting the required battery_pct is a 400, not a 409.

        PRD 2.11: "Genuine malformed input — an absent required field or a value
        of the wrong type — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/if_match_vehicle_missing_required_field_invalid_request
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        resp = api.create_vehicle(
            territory["id"],
            {"vin": "VIN-0001", "software_version": "sw-2026.1",
             "target_software_version": "sw-2026.1"},
            headers=FLEET,
        )
        validate_error(resp, ERR_INVALID_REQUEST, 400)
        rows = get_success_data(api.list_territory_vehicles(territory["id"], headers=FLEET))
        assert rows == []


class TestVehicleUniqueness:
    """A vin is unique within its territory, not across the fleet."""

    def test_duplicate_vin_in_territory_is_refused(self, api):
        """A second registration of the same vin in one territory collides.

        PRD 2.11: "A vehicle's `vin` is unique within its territory, so a second
        registration of the same `vin` under the same `territory_id` collides and
        is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

        Design: Corner/entities/if_match_vehicle_duplicate_vin_rejected
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        register_vehicle(api, territory["id"], vin="VIN-0001")
        resp = api.create_vehicle(
            territory["id"],
            {"vin": "VIN-0001", "battery_pct": 90, "cleanliness_score": 90,
             "software_version": "sw-2026.1", "target_software_version": "sw-2026.1"},
            headers=FLEET,
        )
        validate_error(resp, ERR_DUPLICATE_RESOURCE, 409)

    def test_the_same_vin_is_accepted_in_a_different_territory(self, api):
        """The uniqueness key includes the territory.

        PRD 2.11: "A vehicle's `vin` is unique within its territory, so a second
        registration of the same `vin` under the same `territory_id` collides and
        is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

        Design: Corner/entities/if_match_vehicle_duplicate_vin_rejected
        """
        set_clock(api)
        first = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO",
                                 mapped_pct=100, validation_hours=120)
        register_vehicle(api, first["id"], vin="VIN-0001")
        second = create_territory(api, name="Tucson", region_code="TUC-METRO",
                                  mapped_pct=100, validation_hours=120)
        other = register_vehicle(api, second["id"], vin="VIN-0001")
        assert other["vin"] == "VIN-0001"
        assert len(get_success_data(api.list_territory_vehicles(first["id"], headers=FLEET))) == 1


class TestCrossTerritoryStaging:
    """A staged depot must belong to the vehicle's own territory."""

    def test_staging_at_a_foreign_depot_is_refused(self, api):
        """The depot's territory must match the vehicle's territory.

        PRD 2.11: "A separate consistency rule applies to any request whose body
        references a resource belonging to a territory other than the one named
        in the path. Such a reference is rejected with `ERR_CROSS_TERRITORY`
        (HTTP 409)."
        PRD 2.11: "The clearest instance is staging a vehicle: the `depot_id`
        supplied to a staging request must name a depot whose `territory_id`
        equals the vehicle's own `territory_id`, and a mismatch is rejected with
        `ERR_CROSS_TERRITORY`."

        Design: Corner/errors/if_match_cross_territory_staging_rejected
        """
        set_clock(api)
        first = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO",
                                 mapped_pct=100, validation_hours=120)
        second = create_territory(api, name="Tucson", region_code="TUC-METRO",
                                  mapped_pct=100, validation_hours=120)
        foreign_depot = get_success_data(
            api.create_depot(
                second["id"],
                {"name": "Depot B", "charge_positions": 2, "cleaning_positions": 2,
                 "calib_positions": 2, "software_positions": 2},
                headers=PLANNER,
            ),
            expected_status=201,
        )
        vehicle = register_vehicle(api, first["id"], vin="VIN-0001")

        resp = api.stage_vehicle(
            vehicle["id"], {"depot_id": foreign_depot["id"]}, headers=FLEET
        )
        validate_error(resp, ERR_CROSS_TERRITORY, 409)

    def test_the_foreign_staging_attempt_leaves_the_vehicle_draft(self, api):
        """The refused staging writes neither status nor current_depot_id.

        PRD 2.11: "the `depot_id` supplied to a staging request must name a depot
        whose `territory_id` equals the vehicle's own `territory_id`, and a
        mismatch is rejected with `ERR_CROSS_TERRITORY`."

        Design: Corner/errors/if_match_cross_territory_staging_rejected
        """
        set_clock(api)
        first = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO",
                                 mapped_pct=100, validation_hours=120)
        second = create_territory(api, name="Tucson", region_code="TUC-METRO",
                                  mapped_pct=100, validation_hours=120)
        foreign_depot = get_success_data(
            api.create_depot(
                second["id"],
                {"name": "Depot B", "charge_positions": 2, "cleaning_positions": 2,
                 "calib_positions": 2, "software_positions": 2},
                headers=PLANNER,
            ),
            expected_status=201,
        )
        vehicle = register_vehicle(api, first["id"], vin="VIN-0001")
        api.stage_vehicle(vehicle["id"], {"depot_id": foreign_depot["id"]}, headers=FLEET)

        after = get_success_data(api.get_vehicle(vehicle["id"], headers=FLEET))
        assert after["status"] == c.VEHICLE_DRAFT
        assert after["current_depot_id"] is None

    def test_staging_at_a_depot_of_the_same_territory_succeeds(self, api):
        """The identical call against an own-territory depot is accepted.

        PRD 3.2: "the vehicle moves from either `DRAFT` or `IN_SERVICE` into
        `AT_DEPOT`, recording that depot as its `current_depot_id`."

        Design: Corner/errors/if_match_cross_territory_staging_rejected
        """
        set_clock(api)
        stack = active_territory_with_depot(api)
        vehicle = register_vehicle(api, stack["territory"]["id"], vin="VIN-0002")
        staged = get_success_data(
            api.stage_vehicle(
                vehicle["id"], {"depot_id": stack["depot"]["id"]}, headers=FLEET
            )
        )
        assert staged["status"] == c.VEHICLE_AT_DEPOT
        assert staged["current_depot_id"] == stack["depot"]["id"]


class TestExpansionRequestOCC:
    """Submitting an expansion is guarded against the territory's version."""

    def test_stale_territory_version_is_refused(self, api):
        """A version recorded before a weather tick no longer matches.

        PRD 2.9: "Submitting a service-area expansion request carries
        `expected_territory_version`, which must equal the target territory's
        current `version`. If mapping ticks, exclusion-zone activation, or any
        other mutation has advanced the territory's `version` since the client
        last observed it, the submission is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/if_match_expansion_submit_stale_territory_version
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=50, validation_hours=0,
        )
        recorded_version = territory["version"]
        # Advance the territory's version through a mutation the PRD attaches
        # no precondition to: PRD 2.8 states that "recording a tier refreshes
        # the territory's own `version`".  A mapping tick would not serve here
        # — PRD 3.1 accepts a tick only while the posture is PENDING, and this
        # territory is MAPPING at mapped_pct 50.
        get_success_data(
            api.weather_tier_tick(
                territory["id"], {"window_code": c.WINDOW_MIDDAY, "tier": 1},
                headers=SAFETY,
            )
        )
        resp = api.create_expansion_request(
            territory["id"],
            {"target_region_code": "PHX-NORTH",
             "expected_territory_version": recorded_version},
            headers=PLANNER,
        )
        validate_error(resp, ERR_STALE_VERSION, 412)

    def test_a_freshly_read_version_succeeds_and_snapshots_coverage(self, api):
        """Re-reading and resubmitting records the coverage at that instant.

        PRD 3.1: "Submission records a `mapped_pct_at_submit` snapshot of the
        territory's coverage at that instant, leaves `rule_version_at_approval`
        null, opens the request in `SUBMITTED` status, and advances the
        territory's own `version`."

        Design: Corner/cross_cutting_complexity_layers/if_match_expansion_submit_stale_territory_version
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=50, validation_hours=0,
        )
        # A mutation the PRD attaches no precondition to advances the territory's
        # version: PRD 2.8 states "recording a tier refreshes the territory's
        # own `version`".  The client then re-reads, so the freshly observed
        # version matches and the coverage snapshot is taken live.
        get_success_data(
            api.weather_tier_tick(
                territory["id"], {"window_code": c.WINDOW_MIDDAY, "tier": 1},
                headers=SAFETY,
            )
        )
        live = read_territory(api, territory["id"])
        assert live["mapped_pct"] == 50

        expansion = validate_success(
            api.create_expansion_request(
                territory["id"],
                {"target_region_code": "PHX-NORTH",
                 "expected_territory_version": live["version"]},
                headers=PLANNER,
            ),
            expected_status=201,
        )
        assert expansion["status"] == c.EXPANSION_SUBMITTED
        assert expansion["mapped_pct_at_submit"] == 50
        assert expansion["rule_version_at_approval"] is None


class TestExpansionApprovalGates:
    """Approval pins the rule set and applies the road-type validation gate."""

    def test_approval_pins_the_approved_rule_version(self, api):
        """The pinned value is the highest approved rule_version in the territory.

        PRD 3.1: "A `SafetyReviewer` approving an expansion pins the territory's
        rule set by setting `rule_version_at_approval` to the highest
        `rule_version` among that territory's `APPROVED` area rules, or to 0 when
        the territory has no approved rule at all."

        Design: Corner/cross_cutting_complexity_layers/if_match_expansion_submit_stale_territory_version
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        rule = get_success_data(
            api.create_area_rule(
                territory["id"], {"route_class": c.ROUTE_ARTERIAL, "allowed": True},
                headers=MAPPING,
            ),
            expected_status=201,
        )
        assert rule["rule_version"] == 1
        approved = get_success_data(api.approve_area_rule(territory["id"], rule["id"], headers=SAFETY))
        assert approved["rule_version"] == 2, "approval increments the rule version by one"

        live = read_territory(api, territory["id"])
        expansion = get_success_data(
            api.create_expansion_request(
                territory["id"],
                {"target_region_code": "PHX-NORTH",
                 "expected_territory_version": live["version"]},
                headers=PLANNER,
            ),
            expected_status=201,
        )
        decided = get_success_data(api.approve_expansion(expansion["id"], headers=SAFETY))
        assert decided["status"] == c.EXPANSION_APPROVED
        assert decided["rule_version_at_approval"] == 2

    def test_approval_pins_zero_when_no_rule_is_approved(self, api):
        """With no approved rule in the territory the pinned value is zero.

        PRD 3.1: "or to 0 when the territory has no approved rule at all."

        Design: Corner/cross_cutting_complexity_layers/if_match_expansion_submit_stale_territory_version
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        live = read_territory(api, territory["id"])
        expansion = get_success_data(
            api.create_expansion_request(
                territory["id"],
                {"target_region_code": "PHX-NORTH",
                 "expected_territory_version": live["version"]},
                headers=PLANNER,
            ),
            expected_status=201,
        )
        decided = get_success_data(api.approve_expansion(expansion["id"], headers=SAFETY))
        assert decided["rule_version_at_approval"] == 0


class TestSegregationOfDuties:
    """A peer role's exclusive operation is denied with ERR_UNAUTHORIZED."""

    def test_depot_technician_cannot_create_a_territory(self, api):
        """Territory creation is TerritoryPlanner-exclusive.

        PRD 2.1: "A request whose role is well-formed but not permitted for the
        operation being attempted is rejected with `ERR_UNAUTHORIZED` (HTTP 403);
        this is how a peer role's exclusive operation is denied."
        PRD 2.1: "`TerritoryPlanner` creates territories and depots, plans and
        dispatches deployment waves, publishes demand curves, and submits
        service-area expansion requests."

        Design: Corner/rbac/if_match_depot_technician_cannot_create_territory
        """
        set_clock(api)
        resp = api.create_territory(
            {"name": "Phoenix Metro", "region_code": "PHX-METRO"}, headers=DEPOT
        )
        validate_error(resp, ERR_UNAUTHORIZED, 403)

    def test_the_same_body_from_the_planner_creates_the_territory(self, api):
        """The identical request from the owning role succeeds.

        PRD 2.1: "`TerritoryPlanner` creates territories and depots, plans and
        dispatches deployment waves, publishes demand curves, and submits
        service-area expansion requests."

        Design: Corner/rbac/if_match_depot_technician_cannot_create_territory
        """
        set_clock(api)
        created = validate_success(
            api.create_territory(
                {"name": "Phoenix Metro", "region_code": "PHX-METRO"}, headers=PLANNER
            ),
            expected_status=201,
        )
        assert created["region_code"] == "PHX-METRO"

    def test_a_role_outside_the_enumeration_is_unauthenticated(self, api):
        """A malformed role value is rejected before permission is examined.

        PRD 2.1: "The role value must be one of the six declared roles, spelled
        exactly ... A request that omits either header, that supplies a malformed
        value, or that names a role outside this enumeration is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/if_match_depot_technician_cannot_create_territory
        """
        set_clock(api)
        resp = api.create_territory(
            {"name": "Phoenix Metro", "region_code": "PHX-METRO"},
            headers={"X-User-ID": "ghost-1", "X-User-Role": "ChiefFleetOfficer"},
        )
        validate_error(resp, "ERR_UNAUTHENTICATED", 401)


class TestLivenessProbe:
    """The liveness probe returns a fixed object envelope and nothing else."""

    def test_health_returns_the_standard_object_envelope(self, api):
        """The probe answers in the standard success envelope.

        PRD 2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body:"
        PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD 2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD 2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/endpoints/if_match_health_returns_object_envelope
        """
        set_clock(api)
        resp = api.health(headers=FLEET)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert isinstance(body["meta"]["api_request_timestamp"], str) and body["meta"]["api_request_timestamp"]
        assert isinstance(body["data"], dict), "an object response carries an object in data"
