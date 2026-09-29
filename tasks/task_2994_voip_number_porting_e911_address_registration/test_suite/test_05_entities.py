"""Entity-contract breadth coverage.

Every test in this module probes one entity-shape claim of the PRD: the fields a
creation returns, the defaults it applies, the values a read echoes back, the
server-generated and computed fields a client may not set, the immutable
records that carry neither `updated_at` nor `version`, the shape and enum
constraints of a request body, the pagination envelope of a list, and the
not-found errors that guard a missing row or a missing parent.
"""
from test_helpers import (
    CLOCK_DEFAULT_ISO,
    DEFAULT_INTL_DAILY_CAP_CENTS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_block_census,
    assert_cents_equal,
    assert_common_fields,
    assert_immutable_common_fields,
    assert_instant,
    assert_instant_format,
    assert_null,
    assert_pagination_meta,
    assert_version,
    expected_e164,
    is_valid_uuid,
    make_account_admin_headers,
    make_account_payload,
    make_billing_admin_headers,
    make_carrier_payload,
    make_device_payload,
    make_numbering_admin_headers,
    make_phone_number_payload,
    make_platform_admin_headers,
    make_port_request_payload,
    make_porting_specialist_headers,
    seed_account,
    seed_carrier,
    seed_jurisdiction,
    seed_number_block,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ----------------------------------------------------------------------
# Local envelope helpers (PRD §2.2). Kept private to this module.
# ----------------------------------------------------------------------
def _assert_success_envelope(response, expected_type: str = "object") -> dict:
    """Assert the standard success envelope of PRD §2.2 and return the body."""
    body = response.json()
    meta = body["meta"]
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must be a string starting with 'req_', got {request_id!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")
    assert body["response_type"] == expected_type, (
        f"response_type expected {expected_type!r}, got {body['response_type']!r}"
    )
    return body


def _assert_error_envelope(response) -> dict:
    """Assert the standard error envelope of PRD §2.2 and return the body."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"response_type expected 'error', got {body['response_type']!r}"
    )
    message = body["data"].get("message")
    assert isinstance(message, str) and message.strip() != "", (
        f"error data.message must be a non-empty string, got {message!r}"
    )
    return body


def test_create_account_returns_201_with_every_declared_field(api):
    """Three fields are computed and are never accepted as input: `e911_compliance_posture` starts at `COMPLIANT` and may become `AT_RISK` or `BLOCKED`, `fee_liability_cents` starts at 0, and `ported_number_count` starts at 0.

    Design: Corner/entities/create_account_returns_201_with_every_declared_field
    """
    set_clock(CLOCK_DEFAULT_ISO)

    response = api.create_account(
        make_account_payload(
            account_number="ACCT1001",
            billing_name="AURORA LLC",
            service_state_code="CA",
            status="ACTIVE",
            intl_calling_enabled=True,
            intl_daily_cap_cents=5000,
        ),
        make_platform_admin_headers(),
    )
    account = validate_success(response, 201)
    _assert_success_envelope(response, "object")

    assert account["account_number"] == "ACCT1001"
    assert account["billing_name"] == "AURORA LLC"
    assert account["service_state_code"] == "CA"

    assert account["status"] == "ACTIVE"
    assert account["intl_calling_enabled"] is True
    assert_cents_equal(account["intl_daily_cap_cents"], 5000, "intl_daily_cap_cents")

    assert account["e911_compliance_posture"] == "COMPLIANT"
    assert_cents_equal(account["fee_liability_cents"], 0, "fee_liability_cents")
    assert account["ported_number_count"] == 0

    assert_common_fields(account, "Account")
    assert is_valid_uuid(account["id"]), f"Account.id must be a UUID, got {account['id']!r}"
    assert_version(account, 1, "Account")
    assert_instant(account["created_at"], CLOCK_DEFAULT_ISO, "Account.created_at")


def test_get_jurisdiction_by_id_returns_the_stored_row(api):
    """Three fields are derived from the fee ledger and start out empty: `pending_fee_cents` at 0, `remitted_fee_cents` at 0, and `last_remitted_period` at null until the first remittance run for that jurisdiction completes.

    Design: Corner/entities/get_jurisdiction_by_id_returns_the_stored_row
    """
    set_clock(CLOCK_DEFAULT_ISO)
    jurisdiction = seed_jurisdiction(
        state_code="TX",
        county_fips="48453",
        fee_type="PER_LOCATION",
        monthly_fee_cents=250,
        remit_day_of_month=12,
    )

    response = api.get_jurisdiction(jurisdiction["id"], make_billing_admin_headers())
    stored = validate_success(response, 200)
    _assert_success_envelope(response, "object")

    assert stored["id"] == jurisdiction["id"]
    assert stored["state_code"] == "TX"
    assert stored["county_fips"] == "48453"
    assert stored["fee_type"] == "PER_LOCATION"

    assert_cents_equal(stored["monthly_fee_cents"], 250, "monthly_fee_cents")
    assert stored["remit_day_of_month"] == 12

    assert_cents_equal(stored["pending_fee_cents"], 0, "pending_fee_cents")
    assert_cents_equal(stored["remitted_fee_cents"], 0, "remitted_fee_cents")
    assert_null(stored["last_remitted_period"], "Jurisdiction.last_remitted_period")

    assert_common_fields(stored, "Jurisdiction")
    assert_instant(stored["created_at"], CLOCK_DEFAULT_ISO, "Jurisdiction.created_at")


def test_list_number_blocks_returns_pagination_envelope_fields(api):
    """`total_count` is the number of records matching the filters before the page window is applied, and `has_more` is true when records remain beyond the current window.

    Design: Corner/entities/list_number_blocks_returns_pagination_envelope_fields
    """
    set_clock(CLOCK_DEFAULT_ISO)
    jurisdiction = seed_jurisdiction(
        state_code="CA",
        county_fips="06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )
    for npa_nxx in ("415601", "415602", "415603"):
        seed_number_block(
            jurisdiction["id"],
            npa_nxx=npa_nxx,
            total_capacity=10,
            max_concurrent_reservations=2,
        )

    headers = make_numbering_admin_headers()

    first_response = api.list_number_blocks(
        headers, params={"jurisdiction_id": jurisdiction["id"], "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    _assert_success_envelope(first_response, "array")
    assert len(first_rows) == 2, f"expected exactly 2 rows on the first page, got {len(first_rows)}"
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_response = api.list_number_blocks(
        headers, params={"jurisdiction_id": jurisdiction["id"], "limit": 2, "offset": 2}
    )
    second_rows, second_meta = validate_paginated(second_response)
    _assert_success_envelope(second_response, "array")
    assert len(second_rows) == 1, f"expected exactly 1 row on the second page, got {len(second_rows)}"
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    windowed = [row["npa_nxx"] for row in first_rows] + [row["npa_nxx"] for row in second_rows]
    assert len(windowed) == len(set(windowed)), f"a block was repeated across the pages: {windowed}"
    assert set(windowed) == {"415601", "415602", "415603"}, (
        f"the union of both pages must be every block, got {sorted(windowed)}"
    )


def test_get_phone_number_with_unknown_id_returns_not_found(api):
    """Every other referenced id resolves — a `Carrier`, `Jurisdiction`, `NumberBlock`, `PhoneNumber`, `NumberReservation`, `CutoverSlot`, `TemporaryBridge`, `E911Registration` or `FeeAssessment` — `ERR_RESOURCE_NOT_FOUND` (404), on every endpoint.

    No phone number has ever been minted, so the catch-all existence rule is what
    answers rather than the account-specific or device-specific not-found error.

    Design: Corner/entities/get_phone_number_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_DEFAULT_ISO)

    response = api.get_phone_number(NON_EXISTENT_UUID, make_numbering_admin_headers())
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
    _assert_error_envelope(response)


def test_create_carrier_missing_required_ocn_returns_invalid_request(api):
    """Request-body shape: every required field present, of its declared JSON type, and inside its declared constraint — enum membership, string length, character set, numeric range, ISO 8601 instant syntax, `YYYY-MM` period syntax, non-empty array — `ERR_INVALID_REQUEST` (400), on every endpoint with a request body.

    The PRD also states that nothing is persisted when a check fails, so the same
    name may afterwards be registered successfully once the `ocn` is supplied.

    Design: Corner/entities/create_carrier_missing_required_ocn_returns_invalid_request
    """
    set_clock(CLOCK_DEFAULT_ISO)

    payload = make_carrier_payload(
        name="Ochre Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    payload.pop("ocn")
    response = api.create_carrier(payload, make_platform_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _assert_error_envelope(response)

    retry = api.create_carrier(
        make_carrier_payload(
            name="Ochre Legacy",
            ocn="OC01",
            csr_match_policy="STRICT",
            porting_buffer_minutes=30,
            foc_business_days=2,
        ),
        make_platform_admin_headers(),
    )
    carrier = validate_success(retry, 201)
    assert carrier["ocn"] == "OC01"
    assert carrier["name"] == "Ochre Legacy"
    assert_immutable_common_fields(carrier, "Carrier")


def test_create_account_omitting_optionals_applies_declared_defaults(api):
    """`status` may be given as `ACTIVE`, `SUSPENDED` or `CLOSED` and defaults to `ACTIVE`; it is fixed at creation and is never mutated afterwards, so a suspended or closed account is one that was registered that way.

    The PRD gives the other two omitted optionals their own defaults in the same
    paragraph: `intl_calling_enabled` defaults to false and `intl_daily_cap_cents`
    defaults to 2000.

    Design: Corner/entities/create_account_omitting_optionals_applies_declared_defaults
    """
    set_clock(CLOCK_DEFAULT_ISO)

    payload = make_account_payload(
        account_number="ACCT1002",
        billing_name="BIRCH INC",
        service_state_code="NV",
    )
    assert "status" not in payload
    assert "intl_calling_enabled" not in payload
    assert "intl_daily_cap_cents" not in payload

    response = api.create_account(payload, make_platform_admin_headers())
    account = validate_success(response, 201)

    assert account["status"] == "ACTIVE"
    assert account["intl_calling_enabled"] is False
    assert_cents_equal(
        account["intl_daily_cap_cents"],
        DEFAULT_INTL_DAILY_CAP_CENTS,
        "intl_daily_cap_cents",
    )

    assert account["e911_compliance_posture"] == "COMPLIANT"
    assert_cents_equal(account["fee_liability_cents"], 0, "fee_liability_cents")
    assert_common_fields(account, "Account")


def test_phone_number_e164_is_computed_from_block_npa_nxx_and_line(api):
    """The server derives `e164` by concatenating the literal `+1`, the block's `npa_nxx`, and the `line_number` — a derivation that deliberately reaches across the block boundary, so the same `line_number` in two different blocks yields two different E.164 strings.

    Design: Corner/entities/phone_number_e164_is_computed_from_block_npa_nxx_and_line
    """
    set_clock(CLOCK_DEFAULT_ISO)
    jurisdiction = seed_jurisdiction(
        state_code="CA",
        county_fips="06001",
        fee_type="PER_LINE",
        monthly_fee_cents=175,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415569",
        total_capacity=10,
        max_concurrent_reservations=2,
    )

    response = api.mint_phone_number(
        block["id"],
        make_phone_number_payload(line_number="1501"),
        make_numbering_admin_headers(),
    )
    number = validate_success(response, 201)

    assert number["e164"] == expected_e164("415569", "1501")
    assert number["e164"] == "+14155691501"

    assert number["status"] == "AVAILABLE"
    assert_null(number["assigned_account_id"], "PhoneNumber.assigned_account_id")
    assert_null(number["parked_until"], "PhoneNumber.parked_until")
    assert number["park_cycle_count"] == 0
    assert number["block_id"] == block["id"]
    assert number["line_number"] == "1501"
    assert_common_fields(number, "PhoneNumber")

    refreshed_block = validate_success(
        api.get_number_block(block["id"], make_numbering_admin_headers()), 200
    )
    assert_block_census(refreshed_block, minted=1, available=1)


def test_account_system_fields_are_server_generated_and_client_input_ignored(api):
    """Every resource the API mints carries an `id`: a server-generated UUID, with no type prefix and no client control over its value.

    Design: Corner/entities/account_system_fields_are_server_generated_and_client_input_ignored
    """
    set_clock(CLOCK_DEFAULT_ISO)

    response = api.create_account(
        make_account_payload(
            account_number="ACCT1003",
            billing_name="CEDAR AG",
            service_state_code="CA",
            id="client-supplied-id",
            created_at="1999-01-01T00:00:00.000Z",
            updated_at="1999-01-01T00:00:00.000Z",
            version=99,
        ),
        make_platform_admin_headers(),
    )
    account = validate_success(response, 201)

    assert account["id"] != "client-supplied-id", (
        "the client-supplied id must be ignored in favour of a server-minted one"
    )
    assert is_valid_uuid(account["id"]), f"Account.id must be a UUID, got {account['id']!r}"

    assert_instant(account["created_at"], CLOCK_DEFAULT_ISO, "Account.created_at")
    assert_instant(account["updated_at"], CLOCK_DEFAULT_ISO, "Account.updated_at")
    assert_version(account, 1, "Account")
    assert_common_fields(account, "Account")


def test_create_device_with_invalid_device_type_enum_returns_invalid_request(api):
    """Either the subscriber's own `AccountAdmin` or a `PlatformAdmin` registers one, supplying `account_id` for the owning account, a `mac_address` of exactly twelve characters drawn from digits and the uppercase letters A through F and unique across all devices, and a `device_type` of `BASE_STATION`, `HANDSET` or `SOFTPHONE`.

    `ROUTER` is outside the three-member enumeration and a ten-character
    `mac_address` is outside the declared length, so both bodies fail the same
    shape check.

    Design: Corner/entities/create_device_with_invalid_device_type_enum_returns_invalid_request
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT1004", billing_name="DOGWOOD SA", service_state_code="CA", status="ACTIVE"
    )
    owner_headers = make_account_admin_headers(account["id"])

    bad_enum = api.create_device(
        make_device_payload(
            account["id"], mac_address="AABBCC001001", device_type="ROUTER"
        ),
        owner_headers,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _assert_error_envelope(bad_enum)

    bad_mac = api.create_device(
        make_device_payload(
            account["id"], mac_address="AABBCC0010", device_type="HANDSET"
        ),
        owner_headers,
    )
    validate_error(bad_mac, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _assert_error_envelope(bad_mac)

    rows, _meta = validate_paginated(
        api.list_devices(make_platform_admin_headers(), params={"account_id": account["id"]})
    )
    assert rows == [], f"no Device row may be persisted by a refused registration, got {rows}"


def test_carrier_is_immutable_and_exposes_no_version_field(api):
    """A `Carrier` is created once and never edited — it has no update operation, and its response body contains `id` and `created_at` but no `updated_at` and no `version`.

    Design: Corner/entities/carrier_is_immutable_and_exposes_no_version_field
    """
    set_clock(CLOCK_DEFAULT_ISO)
    created = seed_carrier(
        "EL06",
        name="Elm Legacy",
        csr_match_policy="RELAXED",
        porting_buffer_minutes=0,
        foc_business_days=1,
    )

    response = api.get_carrier(created["id"], make_porting_specialist_headers())
    carrier = validate_success(response, 200)
    _assert_success_envelope(response, "object")

    assert "version" not in carrier, f"Carrier must not carry version, got {carrier!r}"
    assert "updated_at" not in carrier, f"Carrier must not carry updated_at, got {carrier!r}"
    assert_immutable_common_fields(carrier, "Carrier")

    assert carrier["name"] == "Elm Legacy"
    assert carrier["ocn"] == "EL06"
    assert carrier["csr_match_policy"] == "RELAXED"
    assert carrier["porting_buffer_minutes"] == 0
    assert carrier["foc_business_days"] == 1
    assert_instant(carrier["created_at"], CLOCK_DEFAULT_ISO, "Carrier.created_at")


def test_minting_a_phone_number_under_an_unknown_block_returns_not_found(api):
    """Every other referenced id resolves — a `Carrier`, `Jurisdiction`, `NumberBlock`, `PhoneNumber`, `NumberReservation`, `CutoverSlot`, `TemporaryBridge`, `E911Registration` or `FeeAssessment` — `ERR_RESOURCE_NOT_FOUND` (404), on every endpoint.

    The block is the parent path segment of the minting route, and the PRD
    resolves path identifiers strictly left to right, so the missing parent
    answers before the body is considered at all.

    Design: Corner/entities/minting_a_phone_number_under_an_unknown_block_returns_not_found
    """
    set_clock(CLOCK_DEFAULT_ISO)

    response = api.mint_phone_number(
        NON_EXISTENT_UUID,
        make_phone_number_payload(line_number="1601"),
        make_numbering_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
    _assert_error_envelope(response)

    rows, _meta = validate_paginated(api.list_phone_numbers(make_numbering_admin_headers()))
    assert rows == [], f"no PhoneNumber may be minted under a missing block, got {rows}"


def test_port_request_cross_aggregate_ids_are_validated_left_to_right(api):
    """Every referenced `Account` id resolves, evaluated left to right with path segments before body fields — `ERR_ACCOUNT_NOT_FOUND` (404), on reading an account and on creating a port request, a number reservation, a device or a fee assessment.

    With a resolvable account but an unknown losing carrier, the carrier falls to
    the later catch-all existence rule and answers `ERR_RESOURCE_NOT_FOUND`
    instead.

    Design: Corner/entities/port_request_cross_aggregate_ids_are_validated_left_to_right
    """
    set_clock(CLOCK_DEFAULT_ISO)
    account = seed_account(
        "ACCT1005", billing_name="FIRTH OY", service_state_code="CA", status="ACTIVE"
    )
    carrier = seed_carrier(
        "FL07",
        name="Firth Legacy",
        csr_match_policy="RELAXED",
        porting_buffer_minutes=30,
        foc_business_days=2,
    )
    claims = {
        "requested_numbers": ["+14155551601"],
        "claimed_account_number": "CSR-1005",
        "claimed_pin": "1005",
        "claimed_billing_name": "FIRTH OY",
        "claimed_address_line1": "5 FIRTH WAY",
        "claimed_zip": "94577",
    }
    headers = make_porting_specialist_headers()

    unknown_account = api.create_port_request(
        make_port_request_payload(NON_EXISTENT_UUID, carrier["id"], **claims), headers
    )
    validate_error(unknown_account, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)
    _assert_error_envelope(unknown_account)

    unknown_carrier = api.create_port_request(
        make_port_request_payload(account["id"], NON_EXISTENT_UUID, **claims), headers
    )
    validate_error(unknown_carrier, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
    _assert_error_envelope(unknown_carrier)

    rows, _meta = validate_paginated(
        api.list_port_requests(headers, params={"account_id": account["id"]})
    )
    assert rows == [], f"no PortRequest may be persisted by a refused filing, got {rows}"
