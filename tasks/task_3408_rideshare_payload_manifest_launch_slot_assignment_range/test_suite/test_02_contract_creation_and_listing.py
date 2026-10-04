"""Customer/contract creation shape rules and contract listing behavior."""
from test_helpers import (
    ApiErrorId,
    assert_customer,
    assert_payload,
    create_customer,
    create_signed_contract,
    payload_entry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["contract_manager_headers"]


def test_customer_create_applies_defaults_and_ignores_client_version(api):
    """PRD §3.1: "An optional `default_rebookings` count seeds the number of free
    rebooking rights each new contract of this customer receives; when omitted,
    it defaults to 1."
    PRD §2.5: "An entity's `version` starts at 1 when the entity is created"
    PRD §2.8: "Endpoints not named here do not accept a version field."

    Design: Corner/entities/customer_create_version_input_ignored_and_defaults_applied
    """
    set_clock()
    resp = api_client.create_customer(
        {"org_name": "Umbra Orbital Labs", "contact_email": "ops@umbra.example", "version": 99},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["default_rebookings"] == 1, "default_rebookings must default to 1"
    assert data["version"] == 1, "client-supplied version must be ignored; version starts at 1"
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_contract_create_missing_payloads_returns_invalid_request(api):
    """PRD §2.6: "All required fields must be present; enum values must lie in
    their declared domains; numeric domains are enforced (masses and volumes
    strictly greater than zero, license scores integers from 0 to 100 inclusive);
    every window's open must be strictly before its close; `WEATHER` windows must
    be range-scoped and `COLA` windows orbit-scoped; and license filings must
    pair `MISSION` subjects with `LAUNCH_AUTHORIZATION` and `CUSTOMER` subjects
    with `PAYLOAD_OPERATOR`, with the matching foreign key present. Violations
    surface as `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/contract_create_missing_payloads_returns_invalid_request
    """
    set_clock()
    customer = create_customer()
    resp = api_client.create_contract(
        {
            "customer_id": customer["id"],
            "pricing_mode": "MARGINAL",
            "window_open_utc": "2026-10-01T00:00:00Z",
            "window_close_utc": "2026-10-31T00:00:00Z",
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api_client.list_contracts(CM))
    assert rows == [] and meta["total_count"] == 0, "no contract row may be persisted"


def test_contract_create_with_one_invalid_payload_persists_nothing(api):
    """PRD §3.2: "The create is atomic across the array: if any single payload
    entry is invalid, the whole contract is rejected with `ERR_INVALID_REQUEST`
    and nothing is persisted."

    Design: Corner/entities/contract_create_with_one_invalid_payload_persists_nothing
    """
    set_clock()
    customer = create_customer()
    resp = api_client.create_contract(
        {
            "customer_id": customer["id"],
            "pricing_mode": "FLAT",
            "window_open_utc": "2026-10-01T00:00:00Z",
            "window_close_utc": "2026-10-31T00:00:00Z",
            "payloads": [
                payload_entry(payload_name="GoodSat", mass_kg=100),
                payload_entry(payload_name="ZeroSat", mass_kg=0, volume_m3=1.0,
                              interface_class="CUBESAT"),
            ],
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api_client.list_contracts(CM))
    assert rows == [] and meta["total_count"] == 0, (
        "atomicity: neither the contract nor the valid payload may be persisted"
    )


def test_contract_create_with_unknown_customer_rejected(api):
    """PRD §3.2: "Creation takes the contracting `customer_id` (an unknown
    customer is rejected with `ERR_CUSTOMER_NOT_FOUND`)"

    Design: Corner/errors/contract_create_with_unknown_customer_rejected
    """
    set_clock()
    resp = api_client.create_contract(
        {
            "customer_id": "00000000-0000-4000-8000-000000000030",
            "pricing_mode": "MARGINAL",
            "window_open_utc": "2026-10-01T00:00:00Z",
            "window_close_utc": "2026-10-31T00:00:00Z",
            "payloads": [payload_entry(payload_name="OrphanSat", mass_kg=10, volume_m3=0.5)],
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
    rows, meta = validate_paginated(api_client.list_contracts(CM))
    assert rows == [] and meta["total_count"] == 0


def test_payloads_listed_under_parent_contract_in_declaration_order(api):
    """PRD §3.2: "A contract's payloads are listed in exactly the order they were
    declared in the creation `payloads` array, with an optional `status` filter."

    Design: Corner/entities/payloads_listed_under_parent_contract_in_declaration_order
    """
    set_clock()
    customer = create_customer()
    contract_2pl, _ = create_signed_contract(
        customer["id"],
        [
            payload_entry(payload_name="AlphaSat", mass_kg=10, volume_m3=0.5),
            payload_entry(payload_name="BetaSat", mass_kg=20, volume_m3=0.6,
                          interface_class="CUBESAT"),
        ],
    )
    contract_1pl, _ = create_signed_contract(
        customer["id"], [payload_entry(payload_name="PL1", mass_kg=100)]
    )

    data = validate_success(
        api_client.list_contract_payloads(contract_2pl["id"], CM), 200
    )
    assert len(data) == 2, f"expected 2 payloads, got {len(data)}"
    assert data[0]["payload_name"] == "AlphaSat" and data[1]["payload_name"] == "BetaSat", (
        "declaration order must be preserved"
    )
    for row in data:
        assert_payload(row)
        assert row["contract_id"] == contract_2pl["id"]
        assert row["status"] == "REGISTERED"

    other = validate_success(
        api_client.list_contract_payloads(contract_1pl["id"], CM), 200
    )
    assert len(other) == 1 and other[0]["payload_name"] == "PL1", (
        "scoping by contract id must not leak payloads from another contract"
    )


def test_contracts_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "When omitted, `limit` defaults to 10, with a minimum of 1 and a
    maximum of 100, and `offset` defaults to 0."
    PRD §2.3: "Paginated list responses include the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/contracts_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    customer = create_customer()
    for name, mode, mass in (("K1", "MARGINAL", 10), ("K2", "FLAT", 20), ("K3", "MARGINAL", 30)):
        create_signed_contract(customer["id"], [payload_entry(payload_name=name, mass_kg=mass)], pricing_mode=mode)

    page1, meta1 = validate_paginated(
        api_client.list_contracts(CM, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_contracts(CM, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False, (
        "total_count counts the whole filtered set, not the page"
    )

    filtered, meta_f = validate_paginated(
        api_client.list_contracts(CM, params={"customer_id": customer["id"]})
    )
    assert len(filtered) == 3

    default_page, meta_d = validate_paginated(api_client.list_contracts(CM))
    assert len(default_page) == 3 and meta_d["limit"] == 10 and meta_d["offset"] == 0
