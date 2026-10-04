"""Corner tests — listing fee boundaries, listing system fields and region OCC (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    create_listing,
    publish_listing,
    make_listing_agent_headers,
    set_clock,
    region_version,
    agent_version,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


# --- §3.6 fee ceiling, price floor, client mismatch -------------------------

def test_listing_fee_rate_at_the_ceiling_is_admitted():
    """PRD §3.6: "a `list_fee_rate_pct` above the flat fee ceiling of 0.015 is refused with `ERR_LIST_FEE_RATE_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/listing_agreement_above_the_flat_fee_ceiling_returns_list_fee_rate_exceeded
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"],
                             list_price_cents=60_000_000, list_fee_rate_pct=0.015)
    # 60000000 * 0.015 = 900000
    assert listing["gross_listing_fee_cents"] == 900_000, listing


def test_listing_fee_rate_above_the_ceiling_is_refused_and_writes_nothing():
    """PRD §3.6: "a `list_fee_rate_pct` above the flat fee ceiling of 0.015 is refused with `ERR_LIST_FEE_RATE_EXCEEDED` (HTTP 409)".

    Design: Corner/validations/listing_agreement_above_the_flat_fee_ceiling_returns_list_fee_rate_exceeded
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    version = region_version(region["id"])

    resp = api_client.create_listing_agreement(
        {"client_id": seller["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.016, "service_tier": "FULL_SERVICE",
         "expected_region_version": version},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_LIST_FEE_RATE_EXCEEDED)
    assert data["error_id"] == "ERR_LIST_FEE_RATE_EXCEEDED", data

    listed = get_success_data(api_client.list_listing_agreements(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


def test_listing_price_at_the_floor_is_admitted_with_no_commitment_for_mls_only():
    """PRD §3.6: "a `list_price_cents` below the region's minimum listing price is refused with `ERR_LIST_PRICE_OUT_OF_BAND` (HTTP 409)".
    PRD §3.6: "`service_commitment_hours` is 24 for `FULL_SERVICE`, 48 for `LIMITED_SERVICE` and 0 for `MLS_ONLY`".

    Design: Corner/validations/listing_agreement_below_the_price_floor_returns_list_price_out_of_band
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"],
                             list_price_cents=10_000_000, list_fee_rate_pct=0.0125,
                             service_tier="MLS_ONLY")
    # 10000000 * 0.0125 = 125000
    assert listing["gross_listing_fee_cents"] == 125_000, listing
    assert listing["service_commitment_hours"] == 0, listing


def test_listing_price_below_the_floor_is_refused():
    """PRD §3.6: "a `list_price_cents` below the region's minimum listing price is refused with `ERR_LIST_PRICE_OUT_OF_BAND` (HTTP 409)".

    Design: Corner/validations/listing_agreement_below_the_price_floor_returns_list_price_out_of_band
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Uma Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller["id"])
    version = region_version(region["id"])

    resp = api_client.create_listing_agreement(
        {"client_id": seller["id"], "list_price_cents": 9_999_999,
         "list_fee_rate_pct": 0.0125, "service_tier": "MLS_ONLY",
         "expected_region_version": version},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_LIST_PRICE_OUT_OF_BAND)
    assert data["error_id"] == "ERR_LIST_PRICE_OUT_OF_BAND", data


def test_listing_for_a_buy_client_is_refused():
    """PRD §3.6: "a client whose `need_kind` is not `SELL` cannot carry one, and an attempt to attach a listing to a buyer is refused with `ERR_LISTING_CLIENT_MISMATCH` (HTTP 409)".

    Design: Corner/validations/listing_agreement_for_a_buy_client_returns_listing_client_mismatch
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    buyer = create_client(full_name="Buyer Only", service_area_code="98101", need_kind="BUY")
    assign_client(buyer["id"])
    version = region_version(region["id"])

    resp = api_client.create_listing_agreement(
        {"client_id": buyer["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.0125, "service_tier": "FULL_SERVICE",
         "expected_region_version": version},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_LISTING_CLIENT_MISMATCH)
    assert data["error_id"] == "ERR_LISTING_CLIENT_MISMATCH", data
    assert data["error_id"] != "ERR_LIST_FEE_RATE_EXCEEDED", data


def test_buy_client_listing_refusal_leaves_no_agreement_row():
    """PRD §3.6: "a client whose `need_kind` is not `SELL` cannot carry one".

    Design: Corner/validations/listing_agreement_for_a_buy_client_returns_listing_client_mismatch
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    buyer = create_client(full_name="Buyer Only", service_area_code="98101", need_kind="BUY")
    assign_client(buyer["id"])
    version = region_version(region["id"])
    api_client.create_listing_agreement(
        {"client_id": buyer["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.0125, "service_tier": "FULL_SERVICE",
         "expected_region_version": version},
        make_listing_agent_headers(lead["id"]),
    )

    listed = get_success_data(api_client.list_listing_agreements(
        PLATFORM_ADMIN, params={"client_id": buyer["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows


# --- §3.6 system fields and the create response -----------------------------

def test_listing_create_ignores_supplied_system_fields_and_starts_draft():
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix and no embedded meaning".
    PRD §3.6: "A listing also carries a service-level commitment."

    Design: Corner/entities/listing_agreement_create_extra_field_status_and_posted_at_ignored_input
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Gamma Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller["id"])
    version = region_version(region["id"])

    resp = api_client.create_listing_agreement(
        {"client_id": seller["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.0125, "service_tier": "FULL_SERVICE",
         "expected_region_version": version,
         "status": "ACTIVE", "posted_at": "2020-01-01T00:00:00Z", "version": 99},
        make_listing_agent_headers(lead["id"]),
    )
    listing = validate_success(resp, expected_status=201)
    assert listing["status"] == "DRAFT", listing
    assert listing["posted_at"] is None, listing
    assert listing["version"] == 1, listing


def test_publishing_a_draft_listing_activates_it_and_stamps_posted_at():
    """PRD §3.6: "Publishing the listing is the agent's act of taking it live".

    Design: Corner/entities/listing_agreement_create_extra_field_status_and_posted_at_ignored_input
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Gamma Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller["id"])
    listing = create_listing(seller["id"], lead["id"], region["id"])

    published = publish_listing(listing["id"], lead["id"])
    assert published["status"] == "ACTIVE", published
    assert published["posted_at"] is not None, published


# --- §2.7 region OCC on listing create --------------------------------------

def test_listing_create_with_a_stale_region_version_is_refused():
    """PRD §2.7: "Creating a listing agreement requires `expected_region_version` in the request body, carrying the region's `version`. If the region's version has advanced since the caller read it, the region's derived `agent_count` and `occupancy_pct` have moved, the fee baseline the caller priced against is no longer the region's current baseline, and the create is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/listing_create_with_a_stale_region_version_returns_stale_version
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    seller_1 = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    seller_2 = create_client(full_name="Tina Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller_1["id"])
    assign_client(seller_2["id"])

    observed = region_version(region["id"])
    # Advance the region version through an unrelated agent-status write.
    get_success_data(api_client.set_agent_status(
        lead["id"],
        {"new_status": "ON_LEAVE", "expected_agent_version": agent_version(lead["id"])},
        PLATFORM_ADMIN,
    ))
    now = region_version(region["id"])
    assert now > observed, (observed, now)

    resp = api_client.create_listing_agreement(
        {"client_id": seller_1["id"], "list_price_cents": 60_000_000,
         "list_fee_rate_pct": 0.0125, "service_tier": "FULL_SERVICE",
         "expected_region_version": observed},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert data["error_id"] == "ERR_STALE_VERSION", data


def test_listing_create_with_the_fresh_region_version_succeeds():
    """PRD §2.7: "No endpoint outside these three takes a version field of this kind."

    Design: Corner/errors/listing_create_with_a_stale_region_version_returns_stale_version
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Tina Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller["id"])
    fresh = region_version(region["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"],
                             expected_region_version=fresh)
    assert listing["status"] == "DRAFT", listing

    listed = get_success_data(api_client.list_listing_agreements(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 1, rows