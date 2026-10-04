"""Warranty claim creation: type matching, service-date rule, deterministic
center selection, ownership, capacity, and validation priority."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_battery_asset,
    create_center,
    create_certified_pack,
    create_claim,
    create_platform,
    get_claim,
    make_account_manager_headers,
    make_service_agent_headers,
    set_clock,
    transition_asset,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)


def _setup_battery_claim_world(center_capabilities=("BATTERY_SERVICE",), center_capacity=5,
                               clock_iso="2026-09-01T00:00:00Z", center_code="SC-A"):
    """Platform, CERTIFIED pack, one center, one account with one battery asset."""
    set_clock(clock_iso)
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_certified_pack(pf["id"], sku="P-LST")
    sc = create_center(code=center_code, capabilities=list(center_capabilities),
                       daily_capacity=center_capacity)
    ac = create_account(org_name="Paginators Inc")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-W-1",
                                 manufactured_at="2026-06-01T00:00:00Z")
    return pf, pk, sc, ac, asset


def test_claim_create_type_mismatch_rejected(api):
    """PRD §3.5: "The `claim_type` must match the asset's `subject_type` —
    `TOOL_REPAIR` for a `TOOL` asset, `BATTERY_REPLACEMENT` for a `BATTERY`
    asset — with a mismatch rejected as `ERR_CLAIM_TYPE_MISMATCH`."

    Design: Corner/validations/claim_create_type_mismatch_rejected
    """
    pf, pk, sc, ac, asset = _setup_battery_claim_world()
    resp = api.create_warranty_claim(
        warranty_claim_payload(asset["id"], claim_type="TOOL_REPAIR",
                               fault_code="F1", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_TYPE_MISMATCH)


def test_claim_create_with_past_service_date_rejected(api):
    """PRD §3.5: "The requested `service_date` must fall on or after the logical
    clock's current date; an earlier date is `ERR_SERVICE_DATE_PAST`."

    Design: Corner/validations/claim_create_with_past_service_date_rejected
    """
    pf, pk, sc, ac, asset = _setup_battery_claim_world(clock_iso="2026-09-10T00:00:00Z")
    past = api.create_warranty_claim(
        warranty_claim_payload(asset["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="F1", service_date="2026-09-09"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(past, ApiErrorId.ERR_SERVICE_DATE_PAST)
    same_day = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10")
    assert same_day["service_date"] == "2026-09-10"


def test_claim_create_auto_assigns_least_booked_center_with_created_at_tiebreak(api):
    """PRD §3.5: "Among eligible centers the least booked wins, ties break by
    earliest `created_at` (never by id), and an empty pool rejects the claim
    with `ERR_NO_SERVICE_CAPACITY`."
    PRD §3.5: "The filer never chooses a center: `service_center_id` is
    auto-selected at creation by a waterfall over all service centers."

    Design: Corner/entities/claim_create_auto_assigns_least_booked_center_with_created_at_tiebreak
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_certified_pack(pf["id"], sku="P-LST")
    sca = create_center(code="SC-A", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    scb = create_center(code="SC-B", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    ac = create_account(org_name="Paginators Inc")
    assets = [create_battery_asset(ac["id"], pk["id"], serial_number=f"SN-S-{i}",
                                   manufactured_at="2026-06-01T00:00:00Z")
              for i in (1, 2, 3)]
    c1 = create_claim(assets[0]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F1")
    c2 = create_claim(assets[1]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F2")
    c3 = create_claim(assets[2]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F3")
    assert c1["service_center_id"] == sca["id"], "tie at 0-0 breaks to earliest created_at"
    assert c2["service_center_id"] == scb["id"], "SC-A leads 1-0, so SC-B wins"
    assert c3["service_center_id"] == sca["id"], "tie at 1-1 breaks to earliest created_at"


def test_service_agent_cannot_adjudicate_other_centers_claim(api):
    """PRD §3.5: "the agent's `X-User-ID` must equal the claim's
    `service_center_id` (`ERR_FORBIDDEN`) — the center that owns the booking
    decides its own claims."

    Design: Corner/rbac/service_agent_cannot_adjudicate_other_centers_claim
    """
    set_clock()
    pf = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                         backward_commitment_years=8)
    pk = create_certified_pack(pf["id"], sku="P-LST")
    sca = create_center(code="SC-A", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    scb = create_center(code="SC-B", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    ac = create_account(org_name="Paginators Inc")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-RBAC-2",
                                 manufactured_at="2026-06-01T00:00:00Z")
    claim = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10")
    assert claim["service_center_id"] == sca["id"]
    resp = api.adjudicate_warranty_claim(claim["id"], {"decision": "APPROVED"},
                                         make_service_agent_headers(scb["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_claim(claim["id"])["adjudication_status"] == "SUBMITTED"


def _setup_capacity_world():
    """Platform, CERTIFIED pack, one BATTERY_SERVICE center with capacity 2,
    account with three battery assets."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-CAP")
    sc = create_center(code="SC-CAP2", capabilities=["BATTERY_SERVICE"], daily_capacity=2)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    assets = [create_battery_asset(ac["id"], pk["id"], serial_number=f"SN-CAP-{i}",
                                   manufactured_at="2026-06-01T00:00:00Z")
              for i in (1, 2, 3)]
    return pf, pk, sc, ac, assets


def test_service_center_daily_capacity_fills_then_rejects(api, account_manager_headers):
    """PRD §3.5: "A center is eligible when its `capabilities` contain the
    capability the claim type requires (`TOOL_REPAIR` claims need `TOOL_REPAIR`,
    `BATTERY_REPLACEMENT` claims need `BATTERY_SERVICE`) AND its booked count
    for the requested `service_date` is below its `daily_capacity`"
    PRD §3.5: "an empty pool rejects the claim with `ERR_NO_SERVICE_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/service_center_daily_capacity_aggregate_semantics
    """
    pf, pk, sc, ac, assets = _setup_capacity_world()
    c1 = create_claim(assets[0]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F1")
    c2 = create_claim(assets[1]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F2")
    assert c1["service_center_id"] == sc["id"]
    assert c2["service_center_id"] == sc["id"]
    full = api.create_warranty_claim(
        warranty_claim_payload(assets[2]["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="F3", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(full, ApiErrorId.ERR_NO_SERVICE_CAPACITY)


def test_service_center_daily_capacity_is_per_calendar_day(api, account_manager_headers):
    """PRD §3.5: "`daily_capacity` of at least 1 — the maximum number of claims
    the center may have booked per service day."
    PRD §3.5: "The claims collection filters by `tracked_asset_id` and
    `service_center_id`."

    Design: Difficulty/resource_temporal_overlap/service_center_daily_capacity_aggregate_semantics
    """
    pf, pk, sc, ac, assets = _setup_capacity_world()
    create_claim(assets[0]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F1")
    create_claim(assets[1]["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F2")
    full = api.create_warranty_claim(
        warranty_claim_payload(assets[2]["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="F3", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(full, ApiErrorId.ERR_NO_SERVICE_CAPACITY)
    next_day = create_claim(assets[2]["id"], ac["id"], "BATTERY_REPLACEMENT",
                            "2026-09-11", "F3")
    assert next_day["service_center_id"] == sc["id"]
    rows, meta = validate_paginated(api.list_warranty_claims(
        account_manager_headers, params={"service_center_id": sc["id"]}))
    assert meta["total_count"] == 3


def _setup_state_vs_capacity():
    """Center capacity 1 fully booked for 2026-09-10 by asset A1; asset A2 is
    DECOMMISSIONED. Returns (sc, ac, a1, a2)."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-PR1")
    sc = create_center(code="SC-CAP1", capabilities=["BATTERY_SERVICE"], daily_capacity=1)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    a1 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-PR1-A",
                              manufactured_at="2026-06-01T00:00:00Z")
    a2 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-PR1-B",
                              manufactured_at="2026-06-01T00:00:00Z")
    create_claim(a1["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "NO_CHARGE")
    transition_asset(a2["id"], ac["id"], "DECOMMISSIONED")
    return sc, ac, a1, a2


def test_claim_create_state_error_beats_capacity_fiscal_error(api):
    """PRD §2.8: "the server evaluates the following checks in the fixed
    priority order below and reports the violation with the LOWEST priority
    number — earlier checks mask later ones."
    PRD §2.8: "6. State validity: ... the asset is `ACTIVE` for claim creation
    and customization ... otherwise `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/claim_create_state_error_beats_capacity_fiscal_error
    """
    sc, ac, a1, a2 = _setup_state_vs_capacity()
    resp = api.create_warranty_claim(
        warranty_claim_payload(a2["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="NO_CHARGE", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    # The center is provably full for 2026-09-10 (priority 21), yet the state
    # violation (priority 6) is reported.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_claim_create_state_error_creates_no_claim_row(api, account_manager_headers):
    """PRD §2.8: "the server evaluates the following checks in the fixed
    priority order below and reports the violation with the LOWEST priority
    number — earlier checks mask later ones."
    PRD §3.5: "The claims collection filters by `tracked_asset_id` and
    `service_center_id`."

    Design: Difficulty/priority_pair_validation_conflict/claim_create_state_error_beats_capacity_fiscal_error
    """
    sc, ac, a1, a2 = _setup_state_vs_capacity()
    resp = api.create_warranty_claim(
        warranty_claim_payload(a2["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="NO_CHARGE", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_NO_SERVICE_CAPACITY
    rows, meta = validate_paginated(api.list_warranty_claims(
        account_manager_headers, params={"tracked_asset_id": a2["id"]}))
    assert rows == [] and meta["total_count"] == 0
