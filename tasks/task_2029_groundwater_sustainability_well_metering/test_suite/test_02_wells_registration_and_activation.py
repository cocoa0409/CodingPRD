"""Well registration, conditional threshold field, metering paths, and activation gates
(PRD §3.1, §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    activate_well,
    assert_well,
    create_account,
    create_well,
    create_well_payload,
    get_success_data,
    install_meter,
    make_state_regulator_headers,
    make_well_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_well_creation_monitoring_missing_threshold_returns_invalid_request(api):
    """PRD §3.1: "The threshold field is required if and only if the well is `MONITORING`, and it must be absent for `PRODUCTION` and `DOMESTIC` wells; presenting it on the wrong type is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/well_creation_monitoring_missing_threshold_returns_invalid_request
    """
    account = create_account(holder_name="Agency Monitor", account_type="MUNICIPAL",
                             base_allocation_af=1000.000)
    owner = make_well_owner_headers(account["id"])

    resp_missing = api.create_well(
        create_well_payload(account["id"], well_type="MONITORING",
                            location_description="MW-no-threshold"),
        owner,
    )
    validate_error(resp_missing, ApiErrorId.ERR_INVALID_REQUEST)

    resp_forbidden = api.create_well(
        create_well_payload(account["id"], well_type="PRODUCTION",
                            location_description="PW-with-threshold",
                            minimum_threshold_ft=100.0),
        owner,
    )
    validate_error(resp_forbidden, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_well_returns_persisted_fields(api, water_master_headers):
    """PRD §3.1: "Newly registered wells start in `REGISTERED` status with `meter_serial` unset (null)."

    Design: Corner/entities/get_well_returns_persisted_fields
    """
    account = create_account(holder_name="Pumper WR")
    well = create_well(account["id"], "PRODUCTION", "Parcel WR")

    data = validate_success(api.get_well(well["id"], water_master_headers))
    assert_well(data)
    assert data["id"] == well["id"]
    assert data["well_type"] == "PRODUCTION"
    assert data["status"] == "REGISTERED", f"new well must be REGISTERED, got {data['status']}"
    assert data["account_id"] == account["id"]
    assert data["meter_serial"] is None, f"meter_serial must be null before install, got {data['meter_serial']!r}"


def test_list_wells_paginates_with_limit_offset(api, water_master_headers):
    """PRD §2.3: "Every list response sorts by `created_at` ascending; ties are broken by request-arrival order — that is, the order in which the server accepted the create calls."
    PRD §2.3: "`limit` sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets the number of items skipped and defaults to 0."

    Design: Corner/entities/list_wells_paginates_with_limit_offset
    """
    account = create_account(holder_name="Pumper WP")
    wells = [
        create_well(account["id"], "PRODUCTION", f"P-{i}") for i in (1, 2, 3)
    ]

    page1, meta1 = validate_paginated(
        api.list_wells(water_master_headers,
                       params={"account_id": account["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 must hold 2 wells, got {len(page1)}"
    assert [w["id"] for w in page1] == [wells[0]["id"], wells[1]["id"]], (
        "default sort is created_at ASC with request-arrival tie-break"
    )
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_wells(water_master_headers,
                       params={"account_id": account["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1 and page2[0]["id"] == wells[2]["id"]
    assert meta2["total_count"] == 3 and meta2["has_more"] is False


def test_domestic_well_activates_without_meter(api, water_master_headers):
    """PRD §3.2: "For `DOMESTIC` and `MONITORING` wells — which are exempt from the metering requirement — activation moves directly from `REGISTERED` to `ACTIVE` with no meter installed; attempting to activate a `PRODUCTION` well straight from `REGISTERED` is rejected with `ERR_INVALID_WELL_STATE`."

    Design: Corner/state_machines/domestic_well_activates_without_meter
    """
    account = create_account(holder_name="Household WD", account_type="DOMESTIC",
                             base_allocation_af=2.000)
    well = create_well(account["id"], "DOMESTIC", "Home parcel")

    data = validate_success(api.activate_well(well["id"], water_master_headers))
    assert data["status"] == "ACTIVE", (
        f"DOMESTIC well must activate directly from REGISTERED, got {data['status']}"
    )
    assert data["meter_serial"] is None, "the exemption path never stamps a meter_serial"


def test_production_well_activate_without_meter_rejected(api, water_master_headers):
    """PRD §3.2: "For a `PRODUCTION` well, activation requires the well to be in `METER_INSTALLED` and advances it to `ACTIVE`."
    PRD §3.2: "attempting to activate a `PRODUCTION` well straight from `REGISTERED` is rejected with `ERR_INVALID_WELL_STATE`."

    Design: Corner/state_machines/production_well_activate_without_meter_rejected
    """
    account = create_account(holder_name="Pumper WM")
    well = create_well(account["id"], "PRODUCTION", "Parcel WM")

    resp = api.activate_well(well["id"], water_master_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_WELL_STATE)


def test_suspended_account_cannot_register_well(api, water_master_headers):
    """PRD §3.1: "The owning account must be `ACTIVE`, or registration fails with `ERR_ACCOUNT_NOT_ACTIVE`."
    PRD §3.8: "An `ACTIVE` account may be suspended (`ACTIVE` → `SUSPENDED`) and later reinstated (`SUSPENDED` → `ACTIVE`); either transition increments the account's `version` by 1."

    Design: Corner/state_machines/suspended_account_cannot_register_well
    """
    account = create_account(holder_name="Pumper WS")
    patched = validate_success(
        api.update_account(
            account["id"],
            {"status": "SUSPENDED", "expected_account_version": account["version"]},
            water_master_headers,
        )
    )
    assert patched["status"] == "SUSPENDED"

    resp = api.create_well(
        create_well_payload(account["id"], well_type="PRODUCTION",
                            location_description="Parcel WS"),
        make_well_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)


def test_state_regulator_cannot_register_well(api, state_regulator_headers):
    """PRD §2.1: "A request whose role is well-formed but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /wells lists only the WellOwner role.

    Design: Corner/validations/state_regulator_cannot_register_well
    """
    account = create_account(holder_name="Pumper SR-1")
    resp = api.create_well(
        create_well_payload(account["id"], well_type="PRODUCTION",
                            location_description="Parcel SR"),
        state_regulator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_wellowner_cannot_meter_anothers_well(api):
    """PRD §2.1: "A `WellOwner`-scoped write whose target resource's owning account does not match the caller's `X-User-ID` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This ownership rule applies to registering a well, installing a meter, decommissioning a well as its owner, submitting or resubmitting an extraction report, proposing a transfer, accepting or cancelling a transfer as the counterparty owner, and paying or appealing a penalty assessment."

    Design: Corner/validations/wellowner_cannot_meter_anothers_well
    """
    owner_a = create_account(holder_name="Owner A")
    owner_b = create_account(holder_name="Owner B")
    well_a = create_well(owner_a["id"], "PRODUCTION", "Parcel OA")

    resp = api.install_meter(
        well_a["id"], {"meter_serial": "M-HACK"}, make_well_owner_headers(owner_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
