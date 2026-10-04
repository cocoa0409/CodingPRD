"""Activation lifecycle: opening, assessment evidence, wind-down, closure."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assessment,
    create_distribution_site,
    create_donor_commitment,
    create_field_kitchen,
    create_distribution_run,
    create_incident,
    get_field_kitchen_row,
    get_incident_row,
    get_run,
    setup_active_incident,
    setup_operational_field_kitchen,
    transition_donor_commitment,
    transition_field_kitchen,
    transition_incident,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["field_coordinator_headers"]
SAFETY = TEST_USERS["food_safety_officer_headers"]
DONOR = TEST_USERS["donor_liaison_headers"]


def test_activation_opens_in_monitoring_with_usd_and_version_one(api):
    """PRD §3.1: "A new activation opens in `MONITORING` with its `version` at 1."
    PRD §3.1: "`currency_code`, an ISO 4217 code that defaults to `USD` and
    governs every monetary field of the activation"

    Design: Corner/entities/incident_create_defaults_and_server_minted_system_fields
    """
    data = validate_success(
        api.create_incident(
            {
                "name": "Central Valley Floods",
                "country_code": "US",
                "disaster_type": "FLOOD",
                "severity_level": 4,
                "target_daily_meals": 12000,
                "funding_ceiling_cents": 5000000,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["status"] == "MONITORING", f"expected MONITORING, got {data['status']}"
    assert data["currency_code"] == "USD"
    assert data["version"] == 1
    assert data["activated_at"] is None
    assert data["wind_down_started_at"] is None
    assert data["closed_at"] is None
    assert data["spent_cents"] == 0
    assert data["committed_cents"] == 0
    assert data["delivered_meal_total"] == 0


def test_activation_rejects_undeclared_disaster_type(api):
    """PRD §3.1: "a `disaster_type` drawn from `EARTHQUAKE`, `FLOOD`,
    `HURRICANE`, `WILDFIRE`, `CONFLICT` or `EPIDEMIC`"

    Design: Corner/entities/incident_create_invalid_enum_returns_400
    """
    response = api.create_incident(
        {
            "name": "Bay Wildfire",
            "country_code": "US",
            "disaster_type": "TSUNAMI",
            "severity_level": 4,
            "target_daily_meals": 12000,
            "funding_ceiling_cents": 5000000,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    accepted = validate_success(
        api.create_incident(
            {
                "name": "Bay Wildfire",
                "country_code": "US",
                "disaster_type": "WILDFIRE",
                "severity_level": 4,
                "target_daily_meals": 12000,
                "funding_ceiling_cents": 5000000,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert accepted["disaster_type"] == "WILDFIRE"


def test_assessment_earlier_than_activation_is_rejected(api):
    """PRD §3.1: "that instant may not be earlier than the activation's
    `created_at`, or the request is rejected with
    `ERR_ASSESSMENT_BEFORE_ACTIVATION`."

    Design: Corner/validations/assessment_before_incident_creation_rejected
    """
    incident = create_incident()
    rejected = api.create_assessment(
        {
            "incident_id": incident["id"],
            "assessed_at": "2026-08-31T00:00:00Z",
            "population_affected": 40000,
            "estimated_daily_meal_need": 9000,
            "access_constraint": "LIMITED",
            "water_available": False,
            "power_available": True,
            "partner_kitchens_identified": 2,
        },
        COORD,
    )
    validate_error(rejected, ApiErrorId.ERR_ASSESSMENT_BEFORE_ACTIVATION)

    accepted = validate_success(
        api.create_assessment(
            {
                "incident_id": incident["id"],
                "assessed_at": "2026-09-01T06:00:00Z",
                "population_affected": 40000,
                "estimated_daily_meal_need": 9000,
                "access_constraint": "LIMITED",
                "water_available": False,
                "power_available": True,
                "partner_kitchens_identified": 2,
            },
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED"


def test_wind_down_demobilizes_sited_kitchens_and_reescalates(api):
    """PRD §3.1: "A `PlatformAdmin` may move it from `ACTIVE` to `WINDING_DOWN`,
    but only when no batch of this activation is in `IN_PRODUCTION` or
    `QUALITY_HOLD`"
    PRD §3.1: "If the situation deteriorates again, a `PlatformAdmin` may
    re-escalate from `WINDING_DOWN` back to `ACTIVE`, provided a fresh
    assessment exists: at least one assessment of this activation must be in
    `SUBMITTED` with an `assessed_at` strictly after the stored
    `wind_down_started_at`."

    Design: Corner/state_machines/incident_winding_down_reverts_to_active_on_later_assessment
    """
    incident, assessment = setup_active_incident()
    kitchen = create_field_kitchen(incident["id"], assessment["id"])

    wound = transition_incident(incident["id"], "WINDING_DOWN", ADMIN)
    assert wound["status"] == "WINDING_DOWN"
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "DEMOBILIZED"

    api_client.set_current_utc("2026-09-03T00:00:00Z", ADMIN)
    api_client.create_assessment(
        {
            "incident_id": incident["id"],
            "assessed_at": "2026-09-03T00:00:00Z",
            "population_affected": 45000,
            "estimated_daily_meal_need": 11000,
            "access_constraint": "RESTRICTED",
            "water_available": False,
            "power_available": False,
            "partner_kitchens_identified": 1,
        },
        COORD,
    )
    restored = transition_incident(incident["id"], "ACTIVE", ADMIN)
    assert restored["status"] == "ACTIVE"
    assert restored["wind_down_started_at"] is None
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "SITED"


def test_closing_activation_cascades_sites_and_commitments(api):
    """PRD §3.1: "A `PlatformAdmin` may move an activation from `WINDING_DOWN`
    to `CLOSED` only when every field kitchen of the activation is
    `DEMOBILIZED` and every delivery run of the activation is `COMPLETED` or
    `ABORTED`."
    PRD §3.1: "Closing stamps `closed_at` and cascades: every receiving site of
    the activation whose `status` is `REGISTERED`, `ACTIVE` or `SERVICE_ALERT`
    is set to `CLOSED`, and every donor commitment of the activation whose
    `status` is `ALLOCATED` or `PARTIALLY_DISBURSED` is set to `CLOSED`."

    Design: Corner/state_machines/incident_close_cascades_sites_and_commitments_to_closed
    """
    incident, assessment = setup_active_incident()
    create_distribution_site(incident["id"])
    commitment = create_donor_commitment(incident["id"], amount_cents=2000000)
    transition_donor_commitment(commitment["id"], "RECEIVED")
    commitment = transition_donor_commitment(commitment["id"], "ALLOCATED")
    assert commitment["status"] == "ALLOCATED"

    kitchen = create_field_kitchen(incident["id"], assessment["id"])
    run = validate_success(
        api.create_distribution_run(
            {
                "incident_id": incident["id"],
                "field_kitchen_id": kitchen["id"],
                "driver_name": "Ana Ruiz",
                "driver_phone": "+15550100",
                "driver_safety_training_completed": True,
                "vehicle_type": "VAN",
                "planned_date": "2026-09-01T07:00:00Z",
                "window_start": "2026-09-01T07:00:00Z",
                "window_end": "2026-09-01T19:00:00Z",
                "fuel_cost_cents": 6000,
                "handling_cost_cents": 4000,
            },
            TEST_USERS["logistics_coordinator_headers"],
        ),
        expected_status=201,
    )
    api.transition_distribution_run(
        run["id"], {"to_state": "ABORTED", "abort_reason": "STAND_DOWN"},
        TEST_USERS["logistics_coordinator_headers"],
    )

    transition_incident(incident["id"], "WINDING_DOWN", ADMIN)
    # the wind-down already demobilized the kitchen that was still SITED
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "DEMOBILIZED"
    closed = transition_incident(incident["id"], "CLOSED", ADMIN)

    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    sites, _ = validate_paginated(
        api.list_incident_distribution_sites(incident["id"], ADMIN, {"limit": 50})
    )
    assert sites[0]["status"] == "CLOSED"
    commitments, _ = validate_paginated(
        api.list_incident_donor_commitments(incident["id"], ADMIN, {"limit": 50})
    )
    assert commitments[0]["status"] == "CLOSED"


def test_cleared_kitchen_cannot_go_operational_while_activation_winds_down(api):
    """PRD §3.2: "Moving from `FOOD_SAFETY_CLEARED` to `OPERATIONAL` requires
    that the parent activation is `ACTIVE`, and failure yields
    `ERR_INCIDENT_NOT_ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/field_kitchen_operational_gated_by_parent_incident_state
    """
    incident, assessment = setup_active_incident()
    kitchen = create_field_kitchen(incident["id"], assessment["id"])
    transition_field_kitchen(kitchen["id"], "UTILITIES_PENDING")
    transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)

    transition_incident(incident["id"], "WINDING_DOWN", ADMIN)
    blocked = api_client.transition_field_kitchen(
        kitchen["id"], {"to_state": "OPERATIONAL"}, COORD
    )
    validate_error(blocked, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)
    assert get_field_kitchen_row(kitchen["id"])["site_status"] == "FOOD_SAFETY_CLEARED"


def test_cleared_kitchen_goes_operational_once_activation_is_reescalated(api):
    """PRD §3.2: "Moving from `FOOD_SAFETY_CLEARED` to `OPERATIONAL` requires
    that the parent activation is `ACTIVE`"
    PRD §3.1: "If the situation deteriorates again, a `PlatformAdmin` may
    re-escalate from `WINDING_DOWN` back to `ACTIVE`, provided a fresh
    assessment exists: at least one assessment of this activation must be in
    `SUBMITTED` with an `assessed_at` strictly after the stored
    `wind_down_started_at`."

    Design: Difficulty/cross_entity_state_dependency/field_kitchen_operational_gated_by_parent_incident_state
    """
    incident, assessment = setup_active_incident()
    kitchen = create_field_kitchen(incident["id"], assessment["id"])
    transition_field_kitchen(kitchen["id"], "UTILITIES_PENDING")
    transition_field_kitchen(kitchen["id"], "FOOD_SAFETY_CLEARED", SAFETY)
    transition_incident(incident["id"], "WINDING_DOWN", ADMIN)

    api_client.set_current_utc("2026-09-03T00:00:00Z", ADMIN)
    create_assessment(incident["id"], assessed_at="2026-09-03T00:00:00Z")
    transition_incident(incident["id"], "ACTIVE", ADMIN)

    operated = transition_field_kitchen(kitchen["id"], "OPERATIONAL")
    assert operated["site_status"] == "OPERATIONAL"
    assert get_incident_row(incident["id"])["status"] == "ACTIVE"


def test_demobilization_aborts_the_kitchens_planned_runs(api):
    """PRD §3.2: "A `FieldCoordinator` may move a site from `OPERATIONAL` to
    `DEMOBILIZED` only when the parent activation is in `WINDING_DOWN` or
    `CLOSED`."
    PRD §3.2: "Demobilization stamps `demobilized_at` and aborts every delivery
    run of that kitchen that is still `PLANNED`, setting `abort_reason` to
    `KITCHEN_DEMOBILIZED`"

    Design: Difficulty/cross_entity_state_dependency/field_kitchen_operational_gated_by_parent_incident_state
    """
    incident, _, kitchen = setup_operational_field_kitchen()
    run = create_distribution_run(incident["id"], kitchen["id"])
    transition_incident(incident["id"], "WINDING_DOWN", ADMIN)

    demobilized = transition_field_kitchen(kitchen["id"], "DEMOBILIZED")
    assert demobilized["site_status"] == "DEMOBILIZED"
    assert demobilized["demobilized_at"] is not None
    aborted = get_run(run["id"])
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "KITCHEN_DEMOBILIZED"
