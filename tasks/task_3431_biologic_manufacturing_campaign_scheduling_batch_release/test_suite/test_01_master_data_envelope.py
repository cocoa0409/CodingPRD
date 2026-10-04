"""Master-data creation, response envelope, existence, and auth-context claims."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, NO_AUTH_HEADERS,
    validate_success, validate_error,
    create_site_payload, create_product_payload, create_campaign_payload,
    setup_master_data, set_logical_clock,
    assert_site, assert_campaign,
)


def test_site_create_returns_posture_defaults_and_envelope(api, platform_admin_headers):
    """PRD §2.9: "A site is created with posture `CLEAR` and both of its posture counters at zero."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/site_create_returns_posture_defaults_and_envelope
    """
    set_logical_clock("2026-10-01T00:00:00Z")
    resp = api.create_site(create_site_payload(), platform_admin_headers)
    data = validate_success(resp, expected_status=201)
    envelope = resp.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"]
    assert envelope["meta"]["api_request_timestamp"]
    assert_site(data)
    assert data["release_posture"] == "CLEAR"
    assert data["open_critical_deviation_count"] == 0
    assert data["open_critical_finding_count"] == 0
    assert data["version"] == 1
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_site_create_with_client_supplied_id_input_ignored(api, platform_admin_headers):
    """PRD §2.5: "`id` (string): a server-minted UUID, with no type prefix."

    Design: Corner/entities/site_create_with_client_supplied_id_input_ignored
    """
    supplied = "00000000-0000-4000-8000-000000000000"
    payload = create_site_payload(
        name="Juncos Fill-Finish", region="PR-JUN", monthly_capacity_hours=4000,
        cold_storage_capacity_units=5000000, licensed_authorities=["FDA"], id=supplied)
    data = validate_success(api.create_site(payload, platform_admin_headers), expected_status=201)
    assert data["id"] != supplied, "server-minted identity wins over a client-supplied id"


def test_product_create_missing_shelf_life_returns_invalid_request(api, platform_admin_headers):
    """PRD §3.1: "`shelf_life_hours` (a positive integer) is the product's dating period measured from process completion."
    PRD §2.6: "Other schema violations in this stage — an empty `findings` array, a `conclusion` that is inadmissible for the deviation's kind, a missing `capa_summary` on a critical close, a missing `justification` on a reopen — are rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/product_create_missing_shelf_life_returns_invalid_request
    """
    payload = create_product_payload(product_code="MAB-002")
    del payload["shelf_life_hours"]
    resp = api.create_product(payload, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_campaign_create_with_unknown_demand_type_returns_invalid_request(
        api, process_engineer_headers):
    """PRD §3.2: "the `demand_type` the campaign serves (`CLINICAL` or `COMMERCIAL`)"
    PRD §2.6: "Request well-formedness — required fields present, enum members valid, datetimes well-formed"

    Design: Corner/entities/campaign_create_with_unknown_demand_type_returns_invalid_request
    """
    env = setup_master_data()
    payload = create_campaign_payload(env["product"]["id"], demand_type="ORPHAN")
    resp = api.create_campaign(env["train"]["id"], payload, process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_campaign_create_computes_allocated_hours_and_starts_proposed(
        api, process_engineer_headers):
    """PRD §3.2: "The new campaign records its `train_id` and enters `PROPOSED`"
    PRD §3.2: "The upstream component is `upstream_hours` rounded up to a whole multiple of the eight-hour seed shift. The downstream component is `downstream_hours` rounded up to a whole multiple of the twenty-four-hour production block."
    PRD §3.2: "With no predecessor, the changeover component is zero."

    Design: Corner/entities/campaign_create_computes_allocated_hours_and_starts_proposed
    """
    env = setup_master_data()
    payload = create_campaign_payload(env["product"]["id"])
    resp = api.create_campaign(env["train"]["id"], payload, process_engineer_headers)
    data = validate_success(resp, expected_status=201)
    assert_campaign(data)
    assert data["status"] == "PROPOSED"
    assert data["allocated_hours"] == 72, "24 upstream + 48 downstream + 0 changeover"
    assert data["version"] == 1


def test_campaign_get_unknown_id_returns_not_found(api, platform_admin_headers):
    """PRD §2.6: "a missing campaign `ERR_CAMPAIGN_NOT_FOUND`"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error. The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/campaign_get_unknown_id_returns_not_found
    """
    resp = api.get_campaign(NON_EXISTENT_UUID, platform_admin_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)
    envelope = resp.json()
    assert envelope["response_type"] == "error"
    assert error_data["error_id"] == "ERR_CAMPAIGN_NOT_FOUND"
    assert error_data["message"]


def test_shipment_get_unknown_id_returns_not_found(api, platform_admin_headers):
    """PRD §2.6: "a missing shipment `ERR_SHIPMENT_NOT_FOUND`"

    Design: Corner/errors/shipment_get_unknown_id_returns_not_found
    """
    resp = api.get_shipment(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)


def test_site_create_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/campaign_create_missing_auth_headers_returns_400
    """
    payload = create_site_payload(
        name="Headerless Site", region="US-XX", monthly_capacity_hours=100,
        cold_storage_capacity_units=100, licensed_authorities=["FDA"])
    resp = api.create_site(payload, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
