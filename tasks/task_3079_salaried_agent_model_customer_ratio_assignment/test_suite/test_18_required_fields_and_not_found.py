"""Corner tests — required fields, enum sealing and entity-scoped 404 identifiers (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    create_survey,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_agent_create_without_a_salary_is_rejected_as_a_bad_request():
    """PRD §2.1: "A request whose shape is invalid — a required input missing, an enum member outside its declared set, or a survey `score` outside the inclusive range 1 to 5 — is refused with `ERR_INVALID_REQUEST` (HTTP 400) before any state is touched."

    Design: Corner/entities/agent_create_missing_base_salary_returns_invalid_request
    """
    region = create_region()

    resp = api_client.create_agent(
        {"region_id": region["id"], "full_name": "Ada Lead", "agent_kind": "LEAD",
         "home_zip": "98101"},
        PLATFORM_ADMIN,
    )
    data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert data["error_id"] == "ERR_INVALID_REQUEST", data
    assert data["error_id"] != "ERR_GEOGRAPHY_MISMATCH", data

    listed = get_success_data(api_client.list_agents(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


def test_client_create_without_a_need_kind_is_rejected_while_benefit_defaults_apply():
    """PRD §3.3: "An `OperationsCoordinator` registers one with a `full_name`, a system-unique `email`, a `service_area_code`, and a `need_kind` of either `BUY` or `SELL`."
    PRD §3.2: "supplying `region_id`, `full_name`, `agent_kind`, `home_zip`, `base_salary_cents`, and optionally `benefits_cents` and `expense_allowance_cents`, which default to 0".

    Design: Corner/entities/client_create_omitting_need_kind_is_rejected_as_invalid_request
    """
    region = create_region()
    agent = create_lead_agent(region["id"])
    assert agent["benefits_cents"] == 0, agent

    resp = api_client.create_client(
        {"full_name": "No Kind Buyer", "email": "nokind@x.com", "service_area_code": "98101"},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert data["error_id"] == "ERR_INVALID_REQUEST", data

    listed = get_success_data(api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


def test_out_of_enum_need_kind_and_agent_kind_are_both_rejected():
    """PRD §2.1: "A request whose shape is invalid — a required input missing, an enum member outside its declared set, or a survey `score` outside the inclusive range 1 to 5 — is refused with `ERR_INVALID_REQUEST` (HTTP 400) before any state is touched."

    Design: Corner/entities/client_create_with_an_out_of_enum_need_kind_returns_invalid_request
    """
    region = create_region()

    client_resp = api_client.create_client(
        {"full_name": "Hedger", "email": "hedger@x.com", "service_area_code": "98101",
         "need_kind": "RENT"},
        OPERATIONS_COORDINATOR,
    )
    client_data = validate_error(client_resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert client_data["error_id"] == "ERR_INVALID_REQUEST", client_data

    agent_resp = api_client.create_agent(
        {"region_id": region["id"], "full_name": "Solo Agent", "agent_kind": "PARTNER",
         "home_zip": "98101", "base_salary_cents": 8_000_000},
        PLATFORM_ADMIN,
    )
    agent_data = validate_error(agent_resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert agent_data["error_id"] == "ERR_INVALID_REQUEST", agent_data


def test_an_out_of_enum_create_leaves_no_rows_behind():
    """PRD §2.1: "is refused with `ERR_INVALID_REQUEST` (HTTP 400) before any state is touched".

    Design: Corner/entities/client_create_with_an_out_of_enum_need_kind_returns_invalid_request
    """
    region = create_region()
    api_client.create_client(
        {"full_name": "Hedger", "email": "hedger@x.com", "service_area_code": "98101",
         "need_kind": "RENT"},
        OPERATIONS_COORDINATOR,
    )
    api_client.create_agent(
        {"region_id": region["id"], "full_name": "Solo Agent", "agent_kind": "PARTNER",
         "home_zip": "98101", "base_salary_cents": 8_000_000},
        PLATFORM_ADMIN,
    )

    clients = get_success_data(api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    agents = get_success_data(api_client.list_agents(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    client_rows = clients if isinstance(clients, list) else clients.get("data", [])
    agent_rows = agents if isinstance(agents, list) else agents.get("data", [])
    assert client_rows == [], client_rows
    assert agent_rows == [], agent_rows


def test_agent_home_zip_outside_the_region_is_a_geography_mismatch():
    """PRD §3.2: "An agent's home must sit inside its region: if `home_zip` is not a member of the parent region's `service_area_codes`, the hire is refused with `ERR_GEOGRAPHY_MISMATCH` (HTTP 409)."

    Design: Corner/entities/agent_create_rejects_home_zip_outside_the_region_service_area
    """
    region = create_region(service_area_codes=["98101", "98102"])

    resp = api_client.create_agent(
        {"region_id": region["id"], "full_name": "Out Of Area", "agent_kind": "LEAD",
         "home_zip": "97001", "base_salary_cents": 8_000_000},
        PLATFORM_ADMIN,
    )
    data = validate_error(resp, ApiErrorId.ERR_GEOGRAPHY_MISMATCH)
    assert data["error_id"] == "ERR_GEOGRAPHY_MISMATCH", data


def test_agent_create_against_an_unknown_region_reports_region_not_found():
    """PRD §2.8: "It confirms the parent identifier first and only then the child; the first identifier that does not resolve aborts the request with the matching `404` error and the later segments are never examined."

    Design: Corner/entities/agent_create_rejects_home_zip_outside_the_region_service_area
    """
    region = create_region(service_area_codes=["98101", "98102"])

    resp = api_client.create_agent(
        {"region_id": "00000000-0000-4000-8000-000000000000", "full_name": "No Region",
         "agent_kind": "LEAD", "home_zip": "98101", "base_salary_cents": 8_000_000},
        PLATFORM_ADMIN,
    )
    data = validate_error(resp, ApiErrorId.ERR_REGION_NOT_FOUND)
    assert data["error_id"] == "ERR_REGION_NOT_FOUND", data

    listed = get_success_data(api_client.list_agents(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


def test_each_resource_path_carries_its_own_not_found_identifier():
    """PRD §2.8: "a member of the family surfaced inside a client-scoped transaction read — `ERR_AGENT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_REGION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND` — is returned as the first failure the path provokes".

    Design: Corner/errors/entity_scoped_not_found_ids_are_distinct_across_the_path_family
    """
    create_region(service_area_codes=["98101"])
    missing = "00000000-0000-4000-8000-000000000001"

    pairs = [
        (api_client.get_agent(missing, PLATFORM_ADMIN), "ERR_AGENT_NOT_FOUND"),
        (api_client.get_client(missing, PLATFORM_ADMIN), "ERR_CLIENT_NOT_FOUND"),
        (api_client.get_listing_agreement(missing, PLATFORM_ADMIN), "ERR_LISTING_NOT_FOUND"),
        (api_client.get_referral(missing, PLATFORM_ADMIN), "ERR_REFERRAL_NOT_FOUND"),
        (api_client.get_survey(missing, PLATFORM_ADMIN), "ERR_SURVEY_NOT_FOUND"),
        (api_client.get_region(missing, PLATFORM_ADMIN), "ERR_REGION_NOT_FOUND"),
    ]
    for response, expected in pairs:
        assert response.status_code == 404, (expected, response.status_code, response.text)
        data = validate_error(response, expected)
        assert data["error_id"] == expected, (expected, data)


def test_a_not_found_read_does_not_disturb_the_real_region():
    """PRD §2.8: "the first identifier that does not resolve aborts the request with the matching `404` error and the later segments are never examined".

    Design: Corner/errors/entity_scoped_not_found_ids_are_distinct_across_the_path_family
    """
    region = create_region(service_area_codes=["98101"])
    api_client.get_agent("00000000-0000-4000-8000-000000000001", PLATFORM_ADMIN)
    api_client.get_survey("00000000-0000-4000-8000-000000000005", PLATFORM_ADMIN)

    still_there = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert still_there["id"] == region["id"], still_there


def test_survey_system_fields_override_the_claimed_body_values():
    """PRD §3.9: "A survey created with a score is born `RESPONDED` with `bonus_eligible` true. A survey created without one is `DISPATCHED` with `bonus_eligible` false, and it enters the dispatch ageing process."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix and no embedded meaning".

    Design: Corner/entities/survey_create_extra_field_response_status_and_score_are_ignored_input
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Closed Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 75_000_000)
    close_transaction(tx["id"])

    resp = api_client.create_survey(
        tx["id"],
        {"agent_id": lead["id"], "response_status": "RESPONDED",
         "bonus_eligible": True, "version": 99},
        TRANSACTION_COORDINATOR,
    )
    assert resp.status_code == 201, resp.text
    survey = validate_success(resp, expected_status=201)

    assert survey["response_status"] == "DISPATCHED", survey
    assert survey["bonus_eligible"] is False, survey
    assert survey["version"] == 1, survey
    assert survey.get("score") is None, survey


def test_a_dispatched_survey_is_readable_and_listed_by_its_transaction():
    """PRD §3.9: "A survey created without one is `DISPATCHED` with `bonus_eligible` false, and it enters the dispatch ageing process."

    Design: Corner/entities/survey_create_extra_field_response_status_and_score_are_ignored_input
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Closed Buyer", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 75_000_000)
    close_transaction(tx["id"])
    survey = create_survey(tx["id"], lead["id"])

    fetched = get_success_data(api_client.get_survey(survey["id"], PLATFORM_ADMIN))
    assert fetched["id"] == survey["id"], fetched

    listed = get_success_data(api_client.list_surveys(
        PLATFORM_ADMIN, params={"transaction_id": tx["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 1, rows