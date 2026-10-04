"""Listing envelopes, lookups and the not-found error vocabulary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_incident,
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SOURCING = TEST_USERS["sourcing_officer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
COORD = TEST_USERS["field_coordinator_headers"]
PARTNER = TEST_USERS["partnership_lead_headers"]


def test_activation_list_reports_the_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses carry four fields inside the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.3: "`has_more` is true when further items remain beyond the returned
    page."

    Design: Corner/entities/incident_listing_pagination_envelope_and_has_more
    """
    create_incident()
    create_incident(name="Bay Wildfire", disaster_type="WILDFIRE", severity_level=3)

    rows, meta = validate_paginated(
        api_client.list_incidents(ADMIN, {"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(rows) == 1


def test_total_count_is_recomputed_on_every_read(api):
    """PRD §2.3: "`total_count` is the number of items the query matches in
    total, ignoring pagination"

    Design: Corner/cross_cutting_complexity_layers/incident_list_pagination_consistency_under_mutation
    """
    create_incident()
    create_incident(name="Bay Wildfire", disaster_type="WILDFIRE", severity_level=3)
    _, before = validate_paginated(api_client.list_incidents(ADMIN, {"limit": 1, "offset": 0}))
    assert before["total_count"] == 2

    create_incident(
        name="Delta Storm", disaster_type="HURRICANE", severity_level=5,
        target_daily_meals=20000, funding_ceiling_cents=8000000,
    )
    rows_after, after = validate_paginated(
        api_client.list_incidents(ADMIN, {"limit": 1, "offset": 0})
    )
    assert after["total_count"] == 3
    assert len(rows_after) == 1
    assert rows_after[0]["id"] is not None


def test_unknown_meal_order_id_reports_its_own_not_found_error(api):
    """PRD §2.5: "Failure yields `ERR_INCIDENT_NOT_FOUND`,
    `ERR_FIELD_KITCHEN_NOT_FOUND`, `ERR_PARTNER_KITCHEN_NOT_FOUND`,
    `ERR_MEAL_ORDER_NOT_FOUND`, `ERR_DISTRIBUTION_RUN_NOT_FOUND` or
    `ERR_DISTRIBUTION_STOP_NOT_FOUND` according to the entity addressed"
    PRD §2.5: "Path-identifier existence — every `{id}` in the path resolves to
    a row of the addressed entity"

    Design: Corner/entities/meal_order_get_not_found_returns_404
    """
    refused = api_client.get_meal_order(NON_EXISTENT_UUID, PLANNER)
    validate_error(refused, ApiErrorId.ERR_MEAL_ORDER_NOT_FOUND)


def test_incident_and_generic_resource_paths_use_different_error_ids(api):
    """PRD §2.5: "Failure yields `ERR_INCIDENT_NOT_FOUND`,
    `ERR_FIELD_KITCHEN_NOT_FOUND`, `ERR_PARTNER_KITCHEN_NOT_FOUND`,
    `ERR_MEAL_ORDER_NOT_FOUND`, `ERR_DISTRIBUTION_RUN_NOT_FOUND` or
    `ERR_DISTRIBUTION_STOP_NOT_FOUND` according to the entity addressed, and
    `ERR_RESOURCE_NOT_FOUND` for an unresolved assessment, supplier, ingredient
    purchase, distribution site or donor commitment (all HTTP 404)."

    Design: Corner/errors/incident_and_resource_not_found_are_distinct_errors
    """
    refused_incident = api_client.get_incident(NON_EXISTENT_UUID, ADMIN)
    validate_error(refused_incident, ApiErrorId.ERR_INCIDENT_NOT_FOUND)

    refused_purchase = api_client.get_ingredient_purchase(NON_EXISTENT_UUID, SOURCING)
    validate_error(refused_purchase, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    assert refused_incident.json()["data"]["error_id"] != refused_purchase.json()["data"]["error_id"]


def test_run_and_stop_paths_each_carry_their_own_not_found_error(api):
    """PRD §2.5: "Failure yields `ERR_INCIDENT_NOT_FOUND`,
    `ERR_FIELD_KITCHEN_NOT_FOUND`, `ERR_PARTNER_KITCHEN_NOT_FOUND`,
    `ERR_MEAL_ORDER_NOT_FOUND`, `ERR_DISTRIBUTION_RUN_NOT_FOUND` or
    `ERR_DISTRIBUTION_STOP_NOT_FOUND` according to the entity addressed"

    Design: Corner/errors/distribution_run_and_stop_not_found_errors
    """
    refused_run = api_client.get_distribution_run(NON_EXISTENT_UUID, LOGISTICS)
    validate_error(refused_run, ApiErrorId.ERR_DISTRIBUTION_RUN_NOT_FOUND)

    refused_stop = api_client.get_distribution_stop(NON_EXISTENT_UUID, LOGISTICS)
    validate_error(refused_stop, ApiErrorId.ERR_DISTRIBUTION_STOP_NOT_FOUND)


def test_transitions_against_unknown_kitchens_report_the_entity_specific_error(api):
    """PRD §2.5: "Path-identifier existence — every `{id}` in the path resolves
    to a row of the addressed entity, validated left to right in path order, so
    the first unresolved identifier in the path decides the error."

    Design: Corner/errors/field_kitchen_and_partner_kitchen_not_found_errors
    """
    refused_kitchen = api_client.transition_field_kitchen(
        NON_EXISTENT_UUID, {"to_state": "UTILITIES_PENDING"}, COORD
    )
    validate_error(refused_kitchen, ApiErrorId.ERR_FIELD_KITCHEN_NOT_FOUND)

    refused_restaurant = api_client.transition_partner_kitchen(
        NON_EXISTENT_UUID, {"dimension": "CONTRACT", "to_state": "VETTING"}, PARTNER
    )
    validate_error(refused_restaurant, ApiErrorId.ERR_PARTNER_KITCHEN_NOT_FOUND)


def test_distribution_site_create_requires_its_site_name(api):
    """PRD §3.7: "a `LogisticsCoordinator` registers each one with an
    `incident_id`, a `site_name`, a `site_type` drawn from `SHELTER`,
    `HOSPITAL`, `NEIGHBORHOOD`, `SCHOOL` or `COMMUNITY_CENTER`"

    Design: Corner/entities/distribution_site_create_missing_required_site_name_returns_400
    """
    incident = create_incident()
    refused = api_client.create_distribution_site(
        {
            "incident_id": incident["id"],
            "site_type": "SHELTER",
            "population_served": 300,
            "daily_meal_request": 600,
            "access_constraint": "OPEN",
        },
        LOGISTICS,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST)


def test_last_page_reports_has_more_false(api):
    """PRD §2.3: "The `offset` parameter sets how many items to skip and
    defaults to 0."
    PRD §2.3: "`has_more` is true when further items remain beyond the returned
    page."

    Design: Corner/entities/incident_listing_pagination_envelope_and_has_more
    """
    create_incident()
    api_client.set_current_utc("2026-09-02T00:00:00Z", ADMIN)
    create_incident(name="Bay Wildfire", disaster_type="WILDFIRE", severity_level=3)

    rows, meta = validate_paginated(
        api_client.list_incidents(ADMIN, {"limit": 1, "offset": 1})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] != ""
