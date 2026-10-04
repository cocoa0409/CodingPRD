"""Corner tests — endpoint pagination, role denials and path ownership (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_associate_agent,
    create_client,
    assign_client,
    create_listing,
    publish_listing,
    make_listing_agent_headers,
    make_associate_agent_headers,
    set_clock,
    NON_EXISTENT_UUID,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_client_list_paginates_and_reports_the_whole_filtered_total():
    """PRD §2.3: "`limit` caps how many items are returned and defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside that band is refused."
    PRD §2.3: "List responses repeat `limit`, `offset`, `total_count` and `has_more` inside the `meta` object so a caller can page without a second counting call."

    Design: Corner/entities/clients_list_paginates_with_total_count_and_agent_filter
    """
    region = create_region(service_area_codes=["98101", "98102", "98103"])
    agent = create_lead_agent(region["id"], home_zip="98101")
    alpha = create_client(full_name="Alpha Buyer", email="alpha@x.com", service_area_code="98101")
    create_client(full_name="Beta Buyer", email="beta@x.com", service_area_code="98102")
    create_client(full_name="Gamma Seller", email="gamma@x.com", service_area_code="98103",
                  need_kind="SELL")
    assign_client(alpha["id"])

    first_page = api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, rows
    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is True, meta
    assert meta["limit"] == 2, meta
    assert meta["offset"] == 0, meta


def test_client_list_filters_narrow_the_returned_set():
    """PRD §2.3: "`offset` states how many items to skip and defaults to 0."

    Design: Corner/entities/clients_list_paginates_with_total_count_and_agent_filter
    """
    region = create_region(service_area_codes=["98101", "98102", "98103"])
    agent = create_lead_agent(region["id"], home_zip="98101")
    alpha = create_client(full_name="Alpha Buyer", email="alpha@x.com", service_area_code="98101")
    create_client(full_name="Beta Buyer", email="beta@x.com", service_area_code="98102")
    create_client(full_name="Gamma Seller", email="gamma@x.com", service_area_code="98103",
                  need_kind="SELL")
    assign_client(alpha["id"])

    second_page = api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"], "limit": 2, "offset": 2},
    )
    page_rows, page_meta = validate_paginated(second_page)
    assert len(page_rows) == 1, page_rows
    assert page_meta["has_more"] is False, page_meta

    by_agent = api_client.list_clients(PLATFORM_ADMIN, params={"assigned_agent_id": agent["id"]})
    agent_rows, _agent_meta = validate_paginated(by_agent)
    assert len(agent_rows) == 1, agent_rows
    assert agent_rows[0]["full_name"] == "Alpha Buyer", agent_rows

    by_area = api_client.list_clients(PLATFORM_ADMIN, params={"service_area_code": "98103"})
    area_rows, _area_meta = validate_paginated(by_area)
    assert len(area_rows) == 1, area_rows
    assert area_rows[0]["full_name"] == "Gamma Seller", area_rows


def test_tour_read_with_an_unknown_id_reports_the_tour_not_found_identifier():
    """PRD §5: "`ERR_TOUR_NOT_FOUND`".
    PRD §2.8: "a member of the family surfaced inside a client-scoped transaction read — `ERR_AGENT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_REGION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`".

    Design: Corner/entities/tour_get_with_an_unknown_id_returns_tour_not_found
    """
    resp = api_client.get_tour("00000000-0000-4000-8000-000000000000", PLATFORM_ADMIN)
    assert resp.status_code == 404, resp.text
    data = validate_error(resp, ApiErrorId.ERR_TOUR_NOT_FOUND)
    assert data["error_id"] == "ERR_TOUR_NOT_FOUND", data
    assert data["error_id"] != "ERR_NOT_FOUND", data


def test_operations_coordinator_cannot_create_a_region():
    """PRD §2.1: "Where the caller's role is not entitled to the requested operation, the platform answers `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`PlatformAdmin` seeds regions and agents, flips agent employment status, runs the periodic checkpoint and moves the logical clock."

    Design: Corner/rbac/operations_coordinator_cannot_create_regions_returns_forbidden
    """
    resp = api_client.create_region(
        {"name": "Puget Sound", "service_area_codes": ["98101"],
         "traditional_commission_pct": 0.025, "target_client_ratio": 2.0},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert data["error_id"] == "ERR_FORBIDDEN", data
    assert data["error_id"] != "ERR_UNAUTHENTICATED", data


def test_a_forbidden_region_create_writes_nothing():
    """PRD §2.1: "The entitlement matrix is tight."

    Design: Corner/rbac/operations_coordinator_cannot_create_regions_returns_forbidden
    """
    api_client.create_region(
        {"name": "Puget Sound", "service_area_codes": ["98101"],
         "traditional_commission_pct": 0.025, "target_client_ratio": 2.0},
        OPERATIONS_COORDINATOR,
    )
    resp = api_client.get_region("00000000-0000-4000-8000-000000000000", PLATFORM_ADMIN)
    assert resp.status_code == 404, resp.text


def test_a_listing_agent_cannot_list_another_agents_client():
    """PRD §2.1: "for listing operations specifically the acting agent must own the client the request names — an agent may only reach clients whose `assigned_agent_id` equals its own `id`."

    Design: Corner/rbac/lead_agent_cannot_create_a_listing_for_another_agents_client
    """
    region = create_region(target_client_ratio=8.0)
    owner = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    other = create_lead_agent(region["id"], full_name="Ben Lead", home_zip="98102")
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    version = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))["version"]

    resp = api_client.create_listing_agreement(
        {"client_id": seller["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.0125, "service_tier": "FULL_SERVICE",
         "expected_region_version": version},
        make_listing_agent_headers(other["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert data["error_id"] == "ERR_FORBIDDEN", data


def test_the_owning_listing_agent_succeeds_where_the_other_was_denied():
    """PRD §2.1: "an agent may only reach clients whose `assigned_agent_id` equals its own `id`".

    Design: Corner/rbac/lead_agent_cannot_create_a_listing_for_another_agents_client
    """
    region = create_region(target_client_ratio=8.0)
    owner = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    version = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))["version"]

    listing = create_listing(seller["id"], owner["id"], region["id"],
                             expected_region_version=version)
    assert listing["status"] == "DRAFT", listing


def test_an_associate_cannot_publish_a_listing():
    """PRD §2.1: "`ListingAgent` authors and steers listing agreements."
    PRD §2.1: "`AssociateAgent` confirms, completes and no-shows tours."

    Design: Corner/rbac/associate_agent_cannot_publish_a_listing_returns_forbidden
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    associate = create_associate_agent(region["id"], home_zip="98102")
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    listing = create_listing(seller["id"], lead["id"], region["id"])

    resp = api_client.publish_listing(listing["id"], make_associate_agent_headers(associate["id"]))
    data = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert data["error_id"] == "ERR_FORBIDDEN", data

    unchanged = get_success_data(api_client.get_listing_agreement(listing["id"], PLATFORM_ADMIN))
    assert unchanged["status"] == "DRAFT", unchanged


def test_the_owning_listing_agent_publishes_the_same_listing():
    """PRD §3.6: "Publishing the listing is the agent's act of taking it live".

    Design: Corner/rbac/associate_agent_cannot_publish_a_listing_returns_forbidden
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    create_associate_agent(region["id"], home_zip="98102")
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    listing = create_listing(seller["id"], lead["id"], region["id"])

    published = publish_listing(listing["id"], lead["id"])
    assert published["status"] == "ACTIVE", published
    assert published["posted_at"] is not None, published


def test_client_scoped_close_rejects_a_transaction_from_another_client():
    """PRD §2.8: "a transaction that exists but does not belong to the client named in the path is reported with `ERR_TRANSACTION_NOT_FOUND`, indistinguishable from a transaction that does not exist at all."

    Design: Corner/endpoints/client_scoped_close_rejects_a_transaction_belonging_to_another_client
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    client_a = create_client(full_name="Owner Client", service_area_code="98101")
    client_b = create_client(full_name="Other Client", service_area_code="98102")
    assign_client(client_a["id"])
    assign_client(client_b["id"])

    tx_a = get_success_data(api_client.open_transaction(client_a["id"], {}, TRANSACTION_COORDINATOR))
    get_success_data(api_client.set_coordination(
        tx_a["id"], {"coordination_status": "REVIEW", "contract_price_cents": 70_000_000}, TRANSACTION_COORDINATOR,
    ))
    tx_b = get_success_data(api_client.open_transaction(client_b["id"], {}, TRANSACTION_COORDINATOR))
    get_success_data(api_client.set_coordination(
        tx_b["id"], {"coordination_status": "REVIEW", "contract_price_cents": 80_000_000}, TRANSACTION_COORDINATOR,
    ))

    mismatch = api_client.close_client_transaction(client_a["id"], tx_b["id"], TRANSACTION_COORDINATOR)
    data = validate_error(mismatch, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)
    assert data["error_id"] == "ERR_TRANSACTION_NOT_FOUND", data

    matched = api_client.close_client_transaction(client_a["id"], tx_a["id"], TRANSACTION_COORDINATOR)
    assert matched.status_code == 200, matched.text
    closed = get_success_data(api_client.get_transaction(tx_a["id"], PLATFORM_ADMIN))
    assert closed["coordination_status"] == "CLOSED", closed
    unmatched = get_success_data(api_client.get_transaction(tx_b["id"], PLATFORM_ADMIN))
    assert unmatched["coordination_status"] == "REVIEW", unmatched