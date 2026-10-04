"""Entity-surface tests: creation defaults, retrieval, listing, computed fields.

Every test translates exactly one non-stub Corner/entities instance.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_congestion_complaint,
    assert_spectrum_block,
    create_complaint,
    create_franchise_area,
    create_node,
    create_service_group,
    get_success_data,
    set_clock,
    setup_service_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def test_franchise_area_create_returns_defaults_and_computed_progress():
    """PRD §3.1: "A new area starts with `homes_built_progress` at 0."
    PRD §2.10: "Blackout windows default to an empty list when not supplied at
    franchise-area creation."

    Design: Corner/entities/franchise_area_create_returns_defaults_and_computed_progress
    """
    resp = api_client.create_franchise_area(
        {
            "name": "Bay Franchise",
            "region_code": "BF",
            "obligation_homes_required": 12000,
            "obligation_deadline": "2027-12-31T00:00:00Z",
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["blackout_windows"] == [], "blackout_windows must default to []"
    assert data["homes_built_progress"] == 0
    assert data["version"] == 1
    assert data.get("id"), "response data must carry a non-null id"
    assert data.get("created_at"), "response data must carry created_at"
    assert data.get("updated_at"), "response data must carry updated_at"


def test_optical_node_retrieval_round_trips_stored_fields():
    """PRD §3.1: "an initial `upstream_config` of `LEGACY`, `MID_SPLIT`, or
    `HIGH_SPLIT` — if the planner does not specify one, the node starts `LEGACY`"
    and "A node's `status` is `ACTIVE` from creation".

    Design: Corner/entities/optical_node_retrieval_round_trips_stored_fields
    """
    fa = create_franchise_area()
    node = create_node(
        fa["id"],
        node_code="NE-RTRV",
        homes_passed=450,
        downstream_spectrum_mhz=96,
        upstream_config="MID_SPLIT",
    )
    resp = api_client.get_optical_node(node["id"], ADMIN)
    data = validate_success(resp)
    assert data["node_code"] == "NE-RTRV"
    assert data["homes_passed"] == 450
    assert data["downstream_spectrum_mhz"] == 96
    assert data["upstream_config"] == "MID_SPLIT"
    assert data["status"] == "ACTIVE"


def test_spectrum_block_list_pagination_envelope():
    """PRD §2.3: "The `meta` object of a list response always carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/spectrum_block_list_pagination_envelope
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-PG", homes_passed=100, downstream_spectrum_mhz=96)
    api_client.create_spectrum_block(node["id"], {"block_type": "LEGACY_VIDEO", "mhz": 24}, ENGINEER)
    api_client.create_spectrum_block(node["id"], {"block_type": "LEGACY_VIDEO", "mhz": 24}, ENGINEER)
    api_client.create_spectrum_block(node["id"], {"block_type": "DATA", "mhz": 48}, ENGINEER)

    resp = api_client.list_spectrum_blocks(node["id"], ADMIN, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 entries on the first page, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_get_missing_optical_node_returns_not_found():
    """PRD §2.8: "A request whose outermost identifier does not resolve is
    rejected with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_missing_optical_node_returns_not_found
    """
    resp = api_client.get_optical_node(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_service_group_create_missing_required_field_rejected():
    """PRD §2.8: "then basic request shape — parseable body, required fields
    present, enum values legal (`ERR_VALIDATION`, HTTP 400)".
    PRD §3.1: service-group creation takes "a `warn_threshold_pct` and a
    `critical_threshold_pct`, and a `utilization_method`".

    Design: Corner/entities/service_group_create_missing_required_field_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-RF", homes_passed=100, downstream_spectrum_mhz=48)
    resp = api_client.create_service_group(
        node["id"],
        {
            "sg_code": "SG-RF",
            "homes_passed": 100,
            "warn_threshold_pct": 70,
            "utilization_method": "PEAK_PCT95",
        },
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_complaint_reopen_count_default_zero():
    """PRD §3.9: "A complaint starts `INVESTIGATING` with `reopen_count` 0 and
    its scores and `cause_category` unset."

    Design: Corner/entities/complaint_reopen_count_default_zero
    """
    ctx = setup_service_group(sg_code="SG-DF", sg_homes=100, node_homes=100, node_code="NE-DF")
    premise_resp = api_client.create_customer_premise(
        ctx["sg"]["id"], {"premise_ref": "P-DF1", "address": "1 Default Way"}, PROVISIONING
    )
    cp = get_success_data(premise_resp)
    cc = create_complaint(cp["id"], description="slow evenings", plant=50, home=30, destination=20)
    assert_congestion_complaint(cc)
    assert cc["reopen_count"] == 0
    assert cc["status"] == "INVESTIGATING"
    assert cc["cause_category"] is None


def test_spectrum_block_computed_channels_and_capacity():
    """PRD §2.9: "a block's `capacity_mbps` is its channel count multiplied by
    38 while the block is `DATA_ACTIVE`, and 0 while the block is `VIDEO_ACTIVE`
    or `RECLAIM_PENDING`" and "the block's width in MHz is divided by 6 and
    truncated down to a whole channel count, per block".

    Design: Corner/entities/spectrum_block_computed_channels_and_capacity
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-CMP", homes_passed=100, downstream_spectrum_mhz=98)
    bd_resp = api_client.create_spectrum_block(node["id"], {"block_type": "DATA", "mhz": 25}, ENGINEER)
    bd = get_success_data(bd_resp)
    bv_resp = api_client.create_spectrum_block(node["id"], {"block_type": "LEGACY_VIDEO", "mhz": 25}, ENGINEER)
    bv = get_success_data(bv_resp)

    resp = api_client.get_spectrum_block(bd["id"], ADMIN)
    data_block = validate_success(resp)
    assert_spectrum_block(data_block)
    assert data_block["channels"] == 4
    assert data_block["capacity_mbps"] == 152
    assert data_block["status"] == "DATA_ACTIVE"

    resp = api_client.get_spectrum_block(bv["id"], ADMIN)
    video_block = validate_success(resp)
    assert video_block["channels"] == 4
    assert video_block["capacity_mbps"] == 0
    assert video_block["status"] == "VIDEO_ACTIVE"


def test_utilization_sample_is_append_only_without_version_field():
    """PRD §2.5: "a `UtilizationSample` is an append-only telemetry record and
    carries only `id` and `created_at`. Both `updated_at` and `version` are
    absent on samples."

    Design: Corner/entities/utilization_sample_is_append_only_without_version_field
    """
    set_clock("2026-10-01T00:00:00Z")
    ctx = setup_service_group(sg_code="SG-IM", sg_homes=100, node_homes=100, node_code="NE-IM", clock=None)
    api_client.create_utilization_sample(
        ctx["sg"]["id"],
        {"measured_at": "2026-09-30T18:00:00Z", "downstream_mbps": 100, "upstream_mbps": 5},
        ADMIN,
    )
    resp = api_client.list_utilization_samples(ctx["sg"]["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    sample = data[0]
    for field in ("id", "created_at", "service_group_id", "measured_at", "downstream_mbps", "upstream_mbps"):
        assert field in sample, f"sample must carry {field}"
    assert "version" not in sample, "sample must not carry version"
    assert "updated_at" not in sample, "sample must not carry updated_at"


def test_node_split_project_requires_existing_parent_action():
    """PRD §2.8: "A request whose outermost identifier does not resolve is
    rejected with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/node_split_project_requires_existing_parent_action
    """
    resp = api_client.create_node_split_project(
        NON_EXISTENT_UUID,
        {"child_count": 2, "min_homes_per_child": 100, "max_homes_per_child": 300},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_invalid_enum_value_on_block_type_rejected():
    """PRD §3.1: "Each block is created with a `block_type` of `LEGACY_VIDEO` or
    `DATA`" and §2.8: "enum values legal (`ERR_VALIDATION`, HTTP 400)".

    Design: Corner/entities/invalid_enum_value_on_block_type_rejected
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-EN", homes_passed=100, downstream_spectrum_mhz=48)
    resp = api_client.create_spectrum_block(node["id"], {"block_type": "SATELLITE", "mhz": 24}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
