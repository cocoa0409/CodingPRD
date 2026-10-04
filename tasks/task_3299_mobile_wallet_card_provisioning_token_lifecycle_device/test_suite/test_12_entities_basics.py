"""Corner: entity creation, listing, not-found, required fields, defaults."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_cardholder,
    create_agreement_payload,
    create_card_account_payload,
    create_device_payload,
    create_issuer_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_cardholder_headers,
    reset_clock,
    setup_cardholder,
    setup_issuer_active,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cardholder_create_returns_declared_fields_and_active_status(api):
    """PRD section 3.2: "Anyone may register a cardholder — the endpoint is
    unauthenticated by design — supplying legal_name, a contact email that must
    be unique across cardholders, and a contact phone in E.164 format. A new
    Cardholder is born with status ACTIVE". PRD section 2.4: "Every persisted
    entity in the system carries an id that is a server-minted UUID".

    Design: Corner/entities/cardholder_create_returns_declared_fields_and_active_status
    """
    reset_clock(api)
    resp = api.create_cardholder(
        {"legal_name": "Ada Byers", "email": "ada@example.com",
         "phone": "+15550001001"},
        None,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert_cardholder(data)
    assert isinstance(data["version"], int)


def test_device_list_paginates_and_filters_by_cardholder(api):
    """PRD section 2.3: "The limit parameter sets the maximum number of items
    returned in one page; when omitted it defaults to 10 ... The offset
    parameter sets how many items to skip before the page begins and defaults
    to 0 ... Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    Design: Corner/entities/device_list_paginates_and_filters_by_cardholder
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    headers = make_cardholder_headers(ch["id"])
    get_success_data(api.create_device(
        create_device_payload(ch["id"], device_serial="SN-1"), headers))
    get_success_data(api.create_device(
        create_device_payload(ch["id"], device_serial="SN-2"), headers))
    rows, meta = validate_paginated(
        api.list_cardholder_devices(ch["id"], params={"limit": 1, "offset": 0})
    )
    assert len(rows) == 1 and meta["total_count"] == 2 and meta["has_more"] is True
    rows, meta = validate_paginated(
        api.list_cardholder_devices(ch["id"], params={"limit": 1, "offset": 1})
    )
    assert len(rows) == 1 and meta["has_more"] is False
    rows, meta = validate_paginated(api.list_cardholder_devices(ch["id"]))
    assert len(rows) == 2


def test_token_get_unknown_id_returns_token_not_found(api):
    """PRD section 2.6: "The 404 is entity-specific where a specific code
    exists: ... ERR_TOKEN_NOT_FOUND for a payment token". An unallocated token
    id yields 404 ERR_TOKEN_NOT_FOUND, not a generic error.

    Design: Corner/entities/token_get_unknown_id_returns_token_not_found
    """
    reset_clock(api)
    resp = api.get_payment_token(NON_EXISTENT_UUID)
    err = validate_error(resp, ApiErrorId.ERR_TOKEN_NOT_FOUND)
    assert isinstance(err["message"], str) and err["message"]


def test_device_create_missing_serial_returns_validation(api):
    """PRD section 3.2: "A Cardholder registers a device by supplying the
    owning cardholder_id ..., a device_serial that is unique across all
    devices, a device_model string, and an os_version string." PRD section
    2.10 priority 3: "Payload schema — required fields present, enum members
    valid, integers non-negative where required. Failure: ERR_VALIDATION."

    Design: Corner/entities/device_create_missing_serial_returns_validation
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    headers = make_cardholder_headers(ch["id"])
    resp = api.create_device(
        {"cardholder_id": ch["id"], "device_model": "Phone X",
         "os_version": "26.0"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, meta = validate_paginated(api.list_cardholder_devices(ch["id"]))
    assert rows == [] and meta["total_count"] == 0


def test_agreement_create_omitting_fee_floor_defaults_to_zero(api):
    """PRD section 3.1: "an optional fee_floor_cents floor that defaults to 0
    when omitted" and "New agreements are born PENDING."

    Design: Corner/entities/agreement_create_omitting_fee_floor_defaults_to_zero
    """
    reset_clock(api)
    issuer = get_success_data(api.create_issuer(
        create_issuer_payload(issuer_name="Default Bank"), ADMIN))
    payload = create_agreement_payload(issuer["id"], fee_bps=100,
                                       fee_cap_cents=900,
                                       express_transit_supported=False)
    del payload["fee_floor_cents"]
    agreement = get_success_data(api.create_agreement(payload, ADMIN))
    assert agreement["fee_floor_cents"] == 0
    assert agreement["status"] == "PENDING"


def test_card_account_create_with_out_of_enum_product_returns_validation(api):
    """PRD section 3.3: "a card_product drawn from exactly CREDIT, DEBIT,
    PREPAID, or TRANSIT" and section 2.10 priority 3: "Payload schema —
    required fields present, enum members valid ... Failure: ERR_VALIDATION."
    CHARGE is outside the enum and is rejected 400.

    Design: Corner/entities/card_account_create_with_out_of_enum_product_returns_validation
    """
    reset_clock(api)
    from test_helpers import OPERATOR
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    resp = api.create_card_account(
        create_card_account_payload(ch["id"], issuer["id"], card_product="CHARGE"),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, meta = validate_paginated(
        api.list_card_accounts(params={"cardholder_id": ch["id"]})
    )
    assert rows == []
