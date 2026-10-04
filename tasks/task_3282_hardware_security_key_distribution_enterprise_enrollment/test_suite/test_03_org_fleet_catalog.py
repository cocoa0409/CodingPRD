"""Organization onboarding, catalog, fleet-fit report, and bulk pre-registration."""
from test_helpers import (
    LOG,
    PA,
    PROC,
    SA,
    ApiErrorId,
    api_client,
    assert_organization,
    create_approved_order,
    create_device,
    create_model,
    create_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_organization_creation_defaults_applied():
    """PRD §3.1: "Two optional inputs complete the organization's posture:
    `approved_firmware_versions`, a list of firmware version strings approved
    for attestation which defaults to an empty list, and `backup_key_minimum`,
    the minimum number of registered keys each identity account must hold,
    which defaults to 2 and must be at least 1. A new organization starts with
    `status` set to `ACTIVE` (the only other lifecycle value is `SUSPENDED`)."

    Design: Corner/entities/organization_creation_defaults_applied
    """
    resp = api_client.create_organization(
        {"legal_name": "Default Org", "assurance_tier": "STANDARD",
         "authentication_policy": "STANDARD", "idp_protocols": ["FIDO2"]},
        PA,
    )
    org = validate_success(resp, expected_status=201)
    assert_organization(org)
    assert org["backup_key_minimum"] == 2
    assert org["approved_firmware_versions"] == []
    assert org["status"] == "ACTIVE"
    assert org["version"] == 1


def test_key_model_duplicate_model_code_rejected():
    """PRD §3.1: "Each model carries a `model_code` (a vendor code such as
    YK5C-NFC, unique across the entire catalog — a duplicate is
    `ERR_DUPLICATE`)".

    Design: Corner/entities/key_model_duplicate_model_code_rejected
    """
    validate_success(api_client.create_key_model(
        {"model_code": "M-Z", "connectors": ["USB_C"], "protocols": ["FIDO2"],
         "form_factor": "KEYCHAIN", "unit_price_cents": 100}, PA), expected_status=201)
    resp = api_client.create_key_model(
        {"model_code": "M-Z", "connectors": ["USB_A"], "protocols": ["U2F"],
         "form_factor": "NANO", "unit_price_cents": 200}, PA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_security_key_bulk_duplicate_serial_rejected():
    """PRD §3.6: "Each element carries its `serial_number` — globally unique
    across all keys, duplicates rejected with `ERR_DUPLICATE` — and its
    `firmware_version` string."

    Design: Corner/entities/security_key_bulk_duplicate_serial_rejected
    """
    org = create_org(legal_name="Serial Org")
    m = create_model(model_code="M-X", unit_price_cents=100)
    po = create_approved_order(org["id"],
                               [{"model_code": m["model_code"], "quantity": 3}])
    validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "DUP-1", "firmware_version": "5.4.3"}]},
        LOG,
    ), expected_status=201)
    resp = api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "DUP-1", "firmware_version": "5.4.3"}]},
        LOG,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_bulk_keys_partial_invalid_rejected_atomically():
    """PRD §2.5: "Well-formedness comes first: required fields present, enum
    values valid, no unknown fields, and bulk elements structurally valid — a
    malformed body is rejected with `ERR_INVALID_REQUEST` before anything else
    is examined."

    Design: Corner/endpoints/bulk_keys_partial_invalid_rejected_atomically
    """
    org = create_org(legal_name="Bulk Org")
    m = create_model(model_code="M-E1", unit_price_cents=100)
    po = create_approved_order(org["id"],
                               [{"model_code": m["model_code"], "quantity": 3}])
    resp = api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "E-OK", "firmware_version": "5.4.3"},
                  {"serial_number": "", "firmware_version": "5.4.3"}]},
        LOG,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(api_client.list_security_keys(
        org["id"], SA, params={"purchase_order_id": po["id"]}))
    assert meta["total_count"] == 0


def test_fleet_fit_report_counts_and_uncovered_list():
    """PRD §3.2: "The report returns `coverage_pct` — the count of fit devices
    divided by the total count of devices, expressed as an integer percent
    rounded half up — together with `total_devices` and
    `uncovered_device_ids`, the ids of the non-fit devices ordered by
    `created_at` ascending with ties broken by `asset_tag` ascending."

    Design: Corner/calculations/fleet_fit_report_counts_and_uncovered_list
    """
    org = create_org(legal_name="Fit Org")
    m = create_model(model_code="M-F1", connectors=["USB_C"], protocols=["FIDO2"],
                     unit_price_cents=100)
    create_device(org["id"], asset_tag="D-1", platform="WINDOWS",
                  connectors=["USB_C"], protocol_capability=["FIDO2"])
    create_device(org["id"], asset_tag="D-2", platform="MACOS",
                  connectors=["USB_C", "NFC"], protocol_capability=["FIDO2"])
    d3 = create_device(org["id"], asset_tag="D-3", platform="IOS",
                       connectors=["LIGHTNING"], protocol_capability=["U2F"])
    create_device(org["id"], asset_tag="D-4", platform="LINUX",
                  connectors=["LIGHTNING"], protocol_capability=["U2F"],
                  lifecycle_status="RETIRED")
    report = validate_success(api_client.get_fleet_fit(org["id"], "M-F1", SA))
    assert report["total_devices"] == 3
    assert report["coverage_pct"] == 67
    assert report["uncovered_device_ids"] == [d3["id"]]


def test_fleet_fit_empty_fleet_rejected():
    """PRD §3.2: "Given a `model_code`, the report considers every `ACTIVE`
    device of the organization — if there are none, the request is rejected
    with `ERR_EMPTY_FLEET`."

    Design: Corner/calculations/fleet_fit_empty_fleet_rejected
    """
    org = create_org(legal_name="Empty Org")
    create_model(model_code="M-F2")
    resp = api_client.get_fleet_fit(org["id"], "M-F2", SA)
    validate_error(resp, ApiErrorId.ERR_EMPTY_FLEET)


def test_fleet_fit_unknown_model_returns_not_found():
    """PRD §3.2: "A `model_code` that matches no catalog entry is
    `ERR_NOT_FOUND`."

    Design: Corner/endpoints/fleet_fit_unknown_model_returns_not_found
    """
    org = create_org(legal_name="Fit2 Org")
    resp = api_client.get_fleet_fit(org["id"], "NOPE", SA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_pagination_limit_offset_has_more():
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
    defaults to 0. List responses order results by `created_at` ascending. The
    `meta` object of a list response carries `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/endpoints/pagination_limit_offset_has_more
    """
    org = create_org(legal_name="Page Org")
    m = create_model(model_code="M-E2", unit_price_cents=100)
    po = create_approved_order(org["id"],
                               [{"model_code": m["model_code"], "quantity": 3}])
    validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "PG-1", "firmware_version": "5.4.3"},
                  {"serial_number": "PG-2", "firmware_version": "5.4.3"},
                  {"serial_number": "PG-3", "firmware_version": "5.4.3"}]},
        LOG,
    ), expected_status=201)
    page1, meta1 = validate_paginated(api_client.list_security_keys(
        org["id"], SA, params={"purchase_order_id": po["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api_client.list_security_keys(
        org["id"], SA, params={"purchase_order_id": po["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
