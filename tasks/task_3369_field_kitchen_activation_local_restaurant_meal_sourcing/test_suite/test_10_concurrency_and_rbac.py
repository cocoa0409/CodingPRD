"""Optimistic concurrency on guarded writes and the role/ownership gates."""
from test_helpers import (
    ApiErrorId,
    add_stop,
    api_client,
    build_user_headers,
    create_meal_order,
    get_kitchen_version,
    get_run,
    make_kitchen_operator_headers,
    setup_contracted_partner_kitchen,
    setup_operational_field_kitchen,
    setup_placed_meal_order,
    setup_planned_run_with_sites,
    setup_two_partner_kitchens,
    transition_distribution_run,
    validate_error,
    TEST_USERS,
)

PLANNER = TEST_USERS["production_planner_headers"]
PARTNER = TEST_USERS["partnership_lead_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
COORD = TEST_USERS["field_coordinator_headers"]


def test_meal_order_create_with_a_stale_kitchen_version_is_rejected(api):
    """PRD §2.6: "If the kitchen's version has advanced since the client last
    read it — because another writer changed its contract or production
    dimension, or because a cascade touched it — the client's view of the
    kitchen's remaining capacity is stale and the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412). The batch is not created."

    Design: Corner/cross_cutting_complexity_layers/stale_partner_kitchen_version_on_meal_order_create
    """
    incident, kitchen = setup_contracted_partner_kitchen()
    stale_version = get_kitchen_version(kitchen["id"])
    accepted = create_meal_order(incident["id"], kitchen["id"], ordered_meals=500)

    refused = api_client.create_meal_order(
        {
            "incident_id": incident["id"],
            "partner_kitchen_id": kitchen["id"],
            "menu_name": "Arroz con Pollo",
            "dietary_tags": ["VEGETARIAN"],
            "ordered_meals": 500,
            "scheduled_start": "2026-09-01T14:00:00Z",
            "production_hours": 4,
            "expected_partner_kitchen_version": stale_version,
        },
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION)
    assert accepted["status"] == "PLACED"
    assert get_kitchen_version(kitchen["id"]) > stale_version


def test_stop_create_with_a_stale_run_version_is_rejected(api):
    """PRD §2.6: "If the run's version has advanced since the client last read
    it — because another writer added a stop or recorded a stop outcome — the
    client's view of the run's remaining load capacity is stale and the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412). The stop is not added."

    Design: Corner/cross_cutting_complexity_layers/stale_distribution_run_version_on_stop_create
    """
    incident, _, run, sites = setup_planned_run_with_sites(2)
    transition_distribution_run(run["id"], "LOADING", loaded_meals=10)
    stale_version = get_run(run["id"])["version"]
    accepted = add_stop(run["id"], sites[0]["id"], 1, 10)

    refused = api_client.create_distribution_stop(
        {
            "distribution_run_id": run["id"],
            "distribution_site_id": sites[1]["id"],
            "stop_sequence": 2,
            "planned_meals": 0,
            "expected_distribution_run_version": stale_version,
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION)
    assert accepted["status"] == "PENDING"
    assert get_run(run["id"])["version"] > stale_version


def test_request_without_auth_headers_is_rejected(api):
    """PRD §2.1: "If either header is absent the request is rejected with
    `ERR_MISSING_AUTH_HEADER` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_return_401
    """
    refused = api_client.create_incident(
        {
            "name": "Central Valley Floods",
            "country_code": "US",
            "disaster_type": "FLOOD",
            "severity_level": 4,
            "target_daily_meals": 12000,
            "funding_ceiling_cents": 5000000,
        },
        {},
    )
    validate_error(refused, ApiErrorId.ERR_MISSING_AUTH_HEADER)


def test_role_outside_the_endpoints_declared_set_is_rejected(api):
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the roles
    the targeted endpoint declares, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/role_not_permitted_on_incident_creation_returns_403
    """
    refused = api_client.create_incident(
        {
            "name": "Central Valley Floods",
            "country_code": "US",
            "disaster_type": "FLOOD",
            "severity_level": 4,
            "target_daily_meals": 12000,
            "funding_ceiling_cents": 5000000,
        },
        COORD,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_kitchen_operator_cannot_drive_another_kitchens_batch(api):
    """PRD §2.1: "a `KitchenOperator` may only act on a batch whose
    `partner_kitchen_id` equals its own `X-User-ID`"
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/kitchen_operator_cannot_act_on_another_kitchens_meal_order
    """
    incident, first_kitchen, second_kitchen = setup_two_partner_kitchens()
    order = create_meal_order(incident["id"], first_kitchen["id"], ordered_meals=500)

    refused = api_client.transition_meal_order(
        order["id"],
        {"to_state": "IN_PRODUCTION"},
        make_kitchen_operator_headers(second_kitchen["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    accepted = api_client.transition_meal_order(
        order["id"],
        {"to_state": "IN_PRODUCTION"},
        make_kitchen_operator_headers(first_kitchen["id"]),
    )
    assert accepted.json()["data"]["status"] == "IN_PRODUCTION"


def test_inspection_endpoint_is_exclusive_to_the_food_safety_officer(api):
    """PRD §2.1: "A `FoodSafetyOfficer` owns inspections, food-safety
    suspensions and the quality verdict on a batch."
    PRD §2.1: "If `X-User-Role` carries a value that is not one of the roles the
    targeted endpoint declares, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/inspection_is_exclusive_to_the_food_safety_officer
    """
    incident, assessment, field_kitchen = setup_operational_field_kitchen()
    refused = api_client.inspect_field_kitchen(
        field_kitchen["id"],
        {
            "power_source": "GENERATOR",
            "water_source": "TRUCKED",
            "refrigeration_hours_available": 12,
            "daily_capacity_meals": 500,
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert refused.json()["data"]["error_id"] == "ERR_UNAUTHORIZED_ROLE"


def test_ownership_gate_applies_only_to_the_entity_backed_role(api):
    """PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `FieldCoordinator`,
    `FoodSafetyOfficer`, `PartnershipLead`, `ProductionPlanner`,
    `SourcingOfficer`, `LogisticsCoordinator` or `DonorLiaison`, `X-User-ID` is
    an opaque operator identifier that is not tied to any persisted entity."

    Design: Corner/rbac/kitchen_operator_cannot_act_on_another_kitchens_meal_order
    """
    incident, kitchen, order = setup_placed_meal_order()
    planner_headers = build_user_headers("opaque-planner-9", "ProductionPlanner")
    accepted = api_client.transition_meal_order(
        order["id"], {"to_state": "IN_PRODUCTION"}, planner_headers
    )
    assert accepted.json()["data"]["status"] == "IN_PRODUCTION"
    assert accepted.json()["data"]["id"] == order["id"]
