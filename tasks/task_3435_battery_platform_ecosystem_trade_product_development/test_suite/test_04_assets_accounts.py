"""One-Key accounts and tracked assets: clock stamping, pagination, serial
uniqueness, OCC customization, ownership, and the tier asset limit."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    create_account,
    create_battery_asset,
    create_center,
    create_claim,
    create_pack,
    create_platform,
    create_tool,
    create_tool_asset,
    make_account_manager_headers,
    set_clock,
    tracked_asset_payload,
    transition_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_asset_first_paired_at_stamped_from_logical_clock(api):
    """PRD §3.4: "At creation the server stamps `first_paired_at` from the
    logical clock — the ACTIVATION age basis — sets `status` `ACTIVE`, leaves
    `custom_torque_limit_nm` null, `anti_theft_lock_enabled` false, and
    `is_replacement_unit` false"

    Design: Corner/entities/asset_first_paired_at_stamped_from_logical_clock
    """
    set_clock("2026-07-04T00:00:00Z")
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_pack(pf["id"], sku="P-LST")
    ac = create_account(org_name="Paginators Inc")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-CLK-1",
                                 manufactured_at="2026-01-15T00:00:00Z")
    # PRD pins the stamped instant (the logical clock), not its string
    # rendering — compare instants, not literals.
    stamped = datetime.fromisoformat(asset["first_paired_at"].replace("Z", "+00:00"))
    assert stamped == datetime(2026, 7, 4, 0, 0, 0, tzinfo=timezone.utc)
    # `manufactured_at` is the client-supplied instant (PRD §3.4); PRD pins
    # the instant, not the string rendering — compare instants.
    mfg = datetime.fromisoformat(asset["manufactured_at"].replace("Z", "+00:00"))
    assert mfg == datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert asset["status"] == "ACTIVE"
    assert asset["is_replacement_unit"] is False
    assert asset["anti_theft_lock_enabled"] is False


def test_tracked_assets_list_filters_by_account_and_paginates(api, account_manager_headers):
    """PRD §2.3: "`limit` defaults to 10 when omitted, must be at least 1, and
    may not exceed 100. `offset` defaults to 0 and must be at least 0."
    PRD §3.4: "The asset collection filters by `account_id`, `tool_model_id`,
    and `battery_pack_id`."

    Design: Corner/entities/tracked_assets_list_filters_by_account_and_paginates
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_pack(pf["id"], sku="P-LST")
    ac = create_account(org_name="Paginators Inc")
    ac2 = create_account(org_name="Empty Co")
    for i in (1, 2, 3):
        create_battery_asset(ac["id"], pk["id"], serial_number=f"SN-P-{i}")
    page1, meta1 = validate_paginated(api.list_tracked_assets(
        account_manager_headers, params={"account_id": ac["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_tracked_assets(
        account_manager_headers, params={"account_id": ac["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
    empty, meta3 = validate_paginated(api.list_tracked_assets(
        account_manager_headers, params={"account_id": ac2["id"]}))
    assert empty == [] and meta3["total_count"] == 0
    all_rows, meta4 = validate_paginated(api.list_tracked_assets(account_manager_headers))
    assert meta4["limit"] == 10 and meta4["offset"] == 0 and len(all_rows) == 3


def test_asset_create_duplicate_serial_rejected(api):
    """PRD §3.4: "`serial_number` is unique across all tracked assets, a
    collision producing `ERR_DUPLICATE_SERIAL`"

    Design: Corner/validations/asset_create_duplicate_serial_rejected
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_pack(pf["id"], sku="P-LST")
    ac = create_account(org_name="Paginators Inc")
    ac2 = create_account(org_name="Second Co")
    create_battery_asset(ac["id"], pk["id"], serial_number="SN-DUP-1",
                         manufactured_at="2026-08-01T00:00:00Z")
    resp = api.create_tracked_asset(
        tracked_asset_payload(ac2["id"], subject_type="BATTERY", battery_pack_id=pk["id"],
                              serial_number="SN-DUP-1", manufactured_at="2026-08-02T00:00:00Z"),
        make_account_manager_headers(ac2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)


def test_customize_with_stale_version_returns_412(api):
    """PRD §2.7: "Customizing a `TrackedAsset` requires
    `expected_tracked_asset_version`, matching the asset's current `version`.
    Customization is a plain field update that would otherwise legitimately
    succeed, so staleness is detected purely through the asset version; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/customize_with_stale_version_returns_412
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    tm = create_tool(pf["id"], model_code="T-IDEM")  # torque range [2, 60]
    ac = create_account(org_name="Paginators Inc")
    asset = create_tool_asset(ac["id"], tm["id"], serial_number="SN-OCC-1")
    headers = make_account_manager_headers(ac["id"])
    first = validate_success(api.customize_tracked_asset(
        asset["id"], {"custom_torque_limit_nm": 40,
                      "expected_tracked_asset_version": asset["version"]}, headers))
    assert first["custom_torque_limit_nm"] == 40
    assert first["version"] == asset["version"] + 1
    replay = api.customize_tracked_asset(
        asset["id"], {"custom_torque_limit_nm": 45,
                      "expected_tracked_asset_version": asset["version"]}, headers)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    refreshed = validate_success(api.customize_tracked_asset(
        asset["id"], {"custom_torque_limit_nm": 45,
                      "expected_tracked_asset_version": first["version"]}, headers))
    assert refreshed["custom_torque_limit_nm"] == 45


def test_account_manager_cannot_customize_other_accounts_asset(api):
    """PRD §2.8: "Entity-backed ownership: an `AccountManager`'s `X-User-ID`
    equals the target `account_id` (asset create/customize/transition; claim
    creation via the claimed asset's `account_id`) ... otherwise `ERR_FORBIDDEN`
    (403)."

    Design: Corner/rbac/account_manager_cannot_customize_other_accounts_asset
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_pack(pf["id"], sku="P-LST")
    ac = create_account(org_name="Paginators Inc")
    acb = create_account(org_name="Other Org")
    asset = create_battery_asset(acb["id"], pk["id"], serial_number="SN-OWN-1")
    resp = api.customize_tracked_asset(
        asset["id"], {"anti_theft_lock_enabled": True,
                      "expected_tracked_asset_version": asset["version"]},
        make_account_manager_headers(ac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    reread = validate_success(api.get_tracked_asset(
        asset["id"], make_account_manager_headers(acb["id"])))
    assert reread["anti_theft_lock_enabled"] is False


def _setup_standard_account_at_limit():
    """STANDARD account (limit 10) already holding 10 live battery assets."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LIM", cell_format="C18650", rated_capacity_wh=80,
                     max_charge_rate_w=150, replacement_price_cents=12000,
                     warranty_days=360, free_replacement_days=30)
    ac = create_account(org_name="Small Crew LLC", tier="STANDARD")
    assets = [create_battery_asset(ac["id"], pk["id"], serial_number=f"SN-L-{i:02d}")
              for i in range(1, 11)]
    return pf, pk, ac, assets


def test_asset_limit_allows_exactly_limit_then_rejects(api):
    """PRD §3.4: "The asset limit is an inclusive maximum: exactly `asset_limit`
    live assets may coexist, and the creation that would exceed it — the one
    attempted while `active_asset_count` already equals `asset_limit` — is
    rejected with `ERR_ASSET_LIMIT_EXCEEDED`."
    PRD §3.4: "The tier pins the account's computed `asset_limit`: 10 live
    assets for `STANDARD`, 100 for `PROFESSIONAL`, and 1000 for `FLEET`."

    Design: Difficulty/boundary_precision_check/asset_limit_inclusive_max_count_boundary
    """
    pf, pk, ac, assets = _setup_standard_account_at_limit()
    assert len(assets) == 10, "the 10th create still succeeds (inclusive maximum)"
    resp = api.create_tracked_asset(
        tracked_asset_payload(ac["id"], subject_type="BATTERY", battery_pack_id=pk["id"],
                              serial_number="SN-L-11"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_LIMIT_EXCEEDED)


def test_asset_limit_decommission_frees_exactly_one_slot(api):
    """PRD §3.4: "Decommissioning from either state recomputes the account's
    `active_asset_count`, freeing one asset-limit slot."

    Design: Difficulty/boundary_precision_check/asset_limit_inclusive_max_count_boundary
    """
    pf, pk, ac, assets = _setup_standard_account_at_limit()
    transition_asset(assets[0]["id"], ac["id"], "DECOMMISSIONED")
    eleventh = create_battery_asset(ac["id"], pk["id"], serial_number="SN-L-11R")
    assert eleventh["id"], "the freed slot admits exactly one new asset"
    full_again = api.create_tracked_asset(
        tracked_asset_payload(ac["id"], subject_type="BATTERY", battery_pack_id=pk["id"],
                              serial_number="SN-L-12"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(full_again, ApiErrorId.ERR_ASSET_LIMIT_EXCEEDED)


def test_asset_reported_lost_blocks_claim_create(api):
    """PRD §3.5: "a claim against a non-`ACTIVE` asset is `ERR_INVALID_STATE`"
    PRD §3.4: "The asset lifecycle is cyclic until retirement: `ACTIVE` →
    `REPORTED_LOST` when a unit goes missing, `REPORTED_LOST` → `ACTIVE` on
    recovery"

    Design: Corner/state_machines/asset_reported_lost_blocks_claim_create
    """
    from test_helpers import warranty_claim_payload
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_pack(pf["id"], sku="P-LST")
    create_center(code="SC-A", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    ac = create_account(org_name="Paginators Inc")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-LOST-1",
                                 manufactured_at="2026-06-01T00:00:00Z")
    transition_asset(asset["id"], ac["id"], "REPORTED_LOST")
    lost = api.create_warranty_claim(
        warranty_claim_payload(asset["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="NO_CHARGE", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(lost, ApiErrorId.ERR_INVALID_STATE)
    transition_asset(asset["id"], ac["id"], "ACTIVE")
    claim = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10",
                         fault_code="NO_CHARGE")
    assert claim["adjudication_status"] == "SUBMITTED"
