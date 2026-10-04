"""Case and asset intake: creation defaults, round-trips, sub-resource reads,
pagination envelope, and read-after-write visibility."""

from test_helpers import (
    CLOCK_EPOCH,
    CLOCK_EPOCH_SYSTEM_STAMP,
    TEST_USERS,
    assert_asset,
    assert_custody_transfer,
    assert_expense_entry,
    assert_seizure_case,
    create_asset_payload,
    create_case,
    create_case_payload,
    create_expense_entry_payload,
    intake_asset,
    is_valid_uuid,
    post_expense,
    schedule_transfer,
    validate_action,
    validate_created,
    validate_paginated,
)


def test_case_create_returns_declared_fields_and_zeroed_pool(api):
    """PRD §3.1: "A new case's `status` stands at `OPEN`, with every proceeds
    accumulator — `gross_proceeds_cents`, `auction_fees_cents`,
    `lien_payments_cents`, `cost_reimbursements_cents`,
    `sharing_pool_gross_basis_cents`, `sharing_pool_net_basis_cents`,
    `equitable_shares_paid_cents`, and `available_proceeds_cents` — reading
    zero, and `forfeited_at` null."
    PRD §2.4: "At server startup the logical clock reads exactly
    2026-09-01T00:00:00Z, and until a client explicitly sets it the clock
    continues to read that default rather than falling back to wall-clock
    time."
    PRD §2.4: "Time inside this API is defined by a server-side logical
    clock, never by wall-clock time."
    PRD §2.5: "`version` (integer): starts at 1 when the resource is created
    and increments by exactly one on every mutation"
    PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, stamped at creation."

    Design: Corner/entities/case_create_returns_declared_fields_and_zeroed_pool
    """
    resp = api.create_case(
        create_case_payload(
            case_number="26-MJ-1001",
            judicial_district="S.D.N.Y.",
            forfeiture_type="CIVIL",
            lead_agency_code="DEA",
        ),
        TEST_USERS["case_agent_headers"],
    )
    case = validate_created(resp)
    assert_seizure_case(case)
    assert case["status"] == "OPEN", f"new case must be OPEN, got {case['status']}"
    assert case["version"] == 1, f"version must start at 1, got {case['version']}"
    assert case["created_at"] == CLOCK_EPOCH_SYSTEM_STAMP, (
        f"created_at must be the pinned logical-clock default "
        f"{CLOCK_EPOCH_SYSTEM_STAMP}, got {case['created_at']}"
    )
    for field in (
        "gross_proceeds_cents", "auction_fees_cents", "lien_payments_cents",
        "cost_reimbursements_cents", "sharing_pool_gross_basis_cents",
        "sharing_pool_net_basis_cents", "equitable_shares_paid_cents",
        "available_proceeds_cents",
    ):
        assert case[field] == 0, f"{field} must read zero on a new case"
    assert case["forfeited_at"] is None, "forfeited_at must be null until FORFEITED"


def test_asset_get_round_trips_stored_fields(api):
    """PRD §3.2: "A new asset begins with `custody_state` `INTAKE`,
    `legal_state` `SEIZED`, `current_condition_grade` equal to the intake
    grade, its appraised value fields null, its accumulated net holding cost
    at zero, and `retention_decision` `PENDING`."
    PRD §2.11: "Parent-child reachability is provided instead by dedicated
    read endpoints — a case exposes the list of its assets and the list of
    its distributions"

    Design: Corner/entities/asset_get_round_trips_stored_fields
    """
    case = create_case(
        case_number="26-MJ-1002", judicial_district="N.D. Cal.",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    created = intake_asset(
        case["id"], asset_type="VEHICLE", description="armored truck",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    asset = validate_action(
        api.get_asset(created["id"], TEST_USERS["court_official_headers"])
    )
    assert_asset(asset)
    assert asset["asset_type"] == "VEHICLE"
    assert asset["description"] == "armored truck"
    assert asset["seized_on"] == "2026-09-01T00:00:00Z"
    assert asset["seizure_condition_grade"] == "GOOD"
    assert asset["current_condition_grade"] == "GOOD", (
        "current_condition_grade must initialize from seizure_condition_grade"
    )
    assert asset["seizure_case_id"] == case["id"]

    rows, meta = validate_paginated(
        api.list_case_assets(case["id"], TEST_USERS["court_official_headers"])
    )
    assert len(rows) == 1 and rows[0]["id"] == asset["id"], (
        "the case's asset list must contain exactly the one asset created"
    )
    assert meta["total_count"] == 1


def test_custody_transfers_subresource_pagination(api):
    """PRD §2.3: "The `limit` parameter caps how many items a page returns;
    when omitted it defaults to 10, and it is bounded below by 1 and above by
    100. The `offset` parameter states how many items to skip and defaults
    to 0."
    PRD §2.3: "Paginated list responses carry four pagination fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/custody_transfers_subresource_pagination
    """
    case = create_case(
        case_number="26-MJ-1003", judicial_district="E.D. Va.",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    asset = intake_asset(
        case["id"], asset_type="VESSEL", description="fishing boat",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="FAIR",
    )
    for kind, src, dst in (
        ("STORAGE", "dock-1", "warehouse-1"),
        ("MAINTENANCE_SHOP", "warehouse-1", "shop-1"),
        ("STORAGE", "shop-1", "warehouse-2"),
    ):
        transfer = schedule_transfer(
            asset["id"], to_location_kind=kind,
            from_location_ref=src, to_location_ref=dst,
        )
        assert_custody_transfer(transfer)

    page1, meta1 = validate_paginated(
        api.list_asset_custody_transfers(
            asset["id"], TEST_USERS["asset_custodian_headers"],
            params={"limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2 and meta1["total_count"] == 3, (
        f"limit=2&offset=0 must return 2 of 3 rows, got {len(page1)}"
    )
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_asset_custody_transfers(
            asset["id"], TEST_USERS["asset_custodian_headers"],
            params={"limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1 and meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta3 = validate_paginated(
        api.list_asset_custody_transfers(
            asset["id"], TEST_USERS["asset_custodian_headers"]
        )
    )
    assert len(all_rows) == 3, "the parameterless call applies limit 10"
    assert meta3["limit"] == 10 and meta3["offset"] == 0


def test_expense_entry_omitted_incurred_on_defaults_to_clock(api):
    """PRD §3.4: "When `incurred_on` is omitted it defaults to the current
    logical clock time. The server stamps the entry's `source` as `MANUAL`
    and records the poster as `posted_by_user_id`."

    Design: Corner/entities/expense_entry_omitted_incurred_on_defaults_to_clock
    """
    case = create_case(
        case_number="26-MJ-1006", judicial_district="D. Or.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="moped",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="FAIR",
    )
    entry = validate_created(
        api.create_expense_entry(
            create_expense_entry_payload(
                asset["id"], entry_kind="COST", expense_type="STORAGE",
                amount_cents=5000,
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    assert_expense_entry(entry)
    assert entry["incurred_on"] == CLOCK_EPOCH, (
        f"omitted incurred_on must default to the logical clock "
        f"{CLOCK_EPOCH}, got {entry['incurred_on']}"
    )
    assert entry["source"] == "MANUAL"
    refreshed = validate_action(
        api.get_asset(asset["id"], TEST_USERS["asset_custodian_headers"])
    )
    assert refreshed["accumulated_net_holding_cost_cents"] == 5000


def test_asset_create_initializes_computed_and_state_fields(api):
    """PRD §3.2: "A new asset begins with `custody_state` `INTAKE`,
    `legal_state` `SEIZED`, `current_condition_grade` equal to the intake
    grade, its appraised value fields null, its accumulated net holding cost
    at zero, and `retention_decision` `PENDING`."
    PRD §3.3: "The final variant, `final_net_retention_value_cents`, is null
    until the first valuation is accepted"
    PRD §3.3: "The provisional variant, `provisional_net_retention_value_cents`,
    is null until at least one valuation exists in any status"

    Design: Corner/entities/asset_create_initializes_computed_and_state_fields
    """
    case = create_case(
        case_number="26-MJ-1007", judicial_district="D. Ariz.",
        forfeiture_type="ADMINISTRATIVE", lead_agency_code="CBP",
    )
    asset = validate_created(
        api.create_asset(
            create_asset_payload(
                case["id"], asset_type="REAL_PROPERTY", description="duplex",
                seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    assert_asset(asset)
    assert asset["custody_state"] == "INTAKE"
    assert asset["legal_state"] == "SEIZED"
    assert asset["retention_decision"] == "PENDING"
    assert asset["version"] == 1
    assert asset["appraised_value_cents"] is None
    assert asset["appraised_at"] is None
    assert asset["accumulated_net_holding_cost_cents"] == 0
    assert asset["provisional_net_retention_value_cents"] is None
    assert asset["final_net_retention_value_cents"] is None
    for field in (
        "returned_at", "computed_depreciation_cents",
        "dispute_claimed_depreciation_cents", "final_depreciation_cents",
    ):
        assert asset.get(field) is None, (
            f"{field} must be null on a freshly intaken asset"
        )


def test_asset_system_fields_server_stamped(api):
    """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
    unique across the system."
    PRD §2.5: "`version` (integer): starts at 1 when the resource is created
    and increments by exactly one on every mutation"
    PRD §2.4: "At server startup the logical clock reads exactly
    2026-09-01T00:00:00Z"
    PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, stamped at creation."

    Design: Corner/entities/asset_system_fields_server_stamped
    """
    case = create_case(
        case_number="26-MJ-1008", judicial_district="D. Colo.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset = validate_created(
        api.create_asset(
            create_asset_payload(
                case["id"], asset_type="AIRCRAFT",
                description="single-engine plane",
                seized_on="2026-09-01T00:00:00Z",
                seizure_condition_grade="EXCELLENT",
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    assert is_valid_uuid(asset.get("id", "")), (
        f"id must be a server-minted UUID with no type prefix, "
        f"got {asset.get('id')!r}"
    )
    assert asset["created_at"] == CLOCK_EPOCH_SYSTEM_STAMP
    assert asset["updated_at"] == CLOCK_EPOCH_SYSTEM_STAMP
    assert asset["version"] == 1


def test_read_after_write_immediate_visibility(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.9: "the server applies those propagations atomically with the
    triggering write."
    PRD §3.4: "Each posting recomputes the asset's
    `accumulated_net_holding_cost_cents`"

    Design: Corner/consistency_model/read_after_write_immediate_visibility
    """
    case = validate_created(
        api.create_case(
            create_case_payload(
                case_number="26-MJ-1038", judicial_district="S.D.N.Y.",
                forfeiture_type="CIVIL", lead_agency_code="DEA",
            ),
            TEST_USERS["case_agent_headers"],
        )
    )
    fetched = validate_action(
        api.get_case(case["id"], TEST_USERS["fund_administrator_headers"])
    )
    assert fetched["case_number"] == "26-MJ-1038"
    assert fetched["status"] == "OPEN" and fetched["version"] == 1

    asset = validate_created(
        api.create_asset(
            create_asset_payload(
                case["id"], asset_type="VEHICLE", description="sedan",
                seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    post_expense(
        asset["id"], 7000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-01T00:00:00Z",
    )
    refreshed = validate_action(
        api.get_asset(asset["id"], TEST_USERS["fund_administrator_headers"])
    )
    assert refreshed["accumulated_net_holding_cost_cents"] == 7000, (
        "the read immediately after the posting must already include the "
        "7000-cent accumulator bump"
    )
