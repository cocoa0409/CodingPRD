"""Allocated-hours component rounding and the firm capacity waterfall with preemption."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, validate_paginated,
    setup_master_data, set_logical_clock,
    create_product_entity, create_train_entity, create_campaign_entity,
    advance_campaign,
)


def _rounding_env():
    env = setup_master_data()
    product2 = create_product_entity(
        product_code="FSN-002", molecule_type="FUSION_PROTEIN", market_scope="BOTH",
        requires_cold_chain=True, min_storage_temp_c=2.0, max_storage_temp_c=8.0,
        shelf_life_hours=1440, changeover_hours=10, same_product_turnaround_hours=4,
        required_materials=[])
    train2 = create_train_entity(
        env["site"]["id"], train_code="TR-9", capacity_liters=1500,
        supported_molecule_types=["MONOCLONAL_ANTIBODY", "FUSION_PROTEIN"])
    campaign_a = create_campaign_entity(
        train2["id"], env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-01T00:00:00Z", planned_end_utc="2026-10-10T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    return env, product2, train2, campaign_a


def test_allocated_hours_first_campaign_no_changeover_component(api):
    """PRD §3.2: "The upstream component is `upstream_hours` rounded up to a whole multiple of the eight-hour seed shift. The downstream component is `downstream_hours` rounded up to a whole multiple of the twenty-four-hour production block."
    PRD §3.2: "With no predecessor, the changeover component is zero."

    Design: Difficulty/combinatorial_formula/allocated_hours_per_component_rounding_order
    """
    _env, _p2, _train2, campaign_a = _rounding_env()
    assert campaign_a["allocated_hours"] == 72, "ceil(20/8)*8 + ceil(30/24)*24 + 0"


def test_allocated_hours_changeover_rounded_before_summation(api):
    """PRD §2.7: "Each component of the calculation is rounded *up* to its own block granularity before the components are summed — rounding the raw sum once is non-conformant."
    PRD §3.2: "When the predecessor manufactures the same product, the gap is this product's `same_product_turnaround_hours`; otherwise the gap is the larger of the two products' `changeover_hours`. The changeover component is that gap rounded up to a whole multiple of four hours."

    Design: Difficulty/combinatorial_formula/allocated_hours_per_component_rounding_order
    """
    _env, product2, train2, _campaign_a = _rounding_env()
    campaign_b = create_campaign_entity(
        train2["id"], product2["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-10T14:00:00Z", planned_end_utc="2026-10-25T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    assert campaign_b["allocated_hours"] == 88, \
        "24 + 48 + ceil(max(14, 10)/4)*4 == 88; rounding the raw sum once would give 64"


def _capacity_env():
    env = setup_master_data(site_overrides={
        "name": "Breda Pilot Plant", "region": "NL-BRE", "monthly_capacity_hours": 100,
        "cold_storage_capacity_units": 10000000, "licensed_authorities": ["EMA"]})
    train_a = create_train_entity(env["site"]["id"], train_code="TR-A", capacity_liters=2000,
                                  supported_molecule_types=["MONOCLONAL_ANTIBODY"])
    train_b = create_train_entity(env["site"]["id"], train_code="TR-B", capacity_liters=2000,
                                  supported_molecule_types=["MONOCLONAL_ANTIBODY"])
    c1 = create_campaign_entity(
        train_a["id"], env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-01T00:00:00Z", planned_end_utc="2026-10-10T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    c2 = create_campaign_entity(
        train_b["id"], env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-05T00:00:00Z", planned_end_utc="2026-10-15T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    advance_campaign(c1["id"], "ALLOCATED")
    return env, c1, c2


def test_deallocation_frees_firm_hours_for_reuse(api, process_engineer_headers):
    """PRD §3.2: "A `COMMERCIAL` candidate that does not fit is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409) immediately, with no preemption attempted."
    PRD §2.11: "Hours are released when a campaign leaves the consuming set — by de-allocation back to `PROPOSED`, by preemption, or by completion."

    Design: Difficulty/compensating_invariant/allocate_deallocate_roundtrip_conserves_capacity_hours
    """
    _env, c1, c2 = _capacity_env()
    resp = api.advance_campaign(c2["id"], "ALLOCATED", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    advance_campaign(c1["id"], "PROPOSED")
    data = validate_success(api.advance_campaign(c2["id"], "ALLOCATED", process_engineer_headers))
    assert data["status"] == "ALLOCATED", "the freed 72 hours are exactly and fully reusable"


def test_deallocated_campaign_keeps_stored_charge(api, platform_admin_headers,
                                                  process_engineer_headers):
    """PRD §2.11: "A campaign charges its `allocated_hours` against the calendar month (in UTC) that contains its `planned_start_utc`, but only while the campaign holds `ALLOCATED`, `SEED_IN_PROGRESS`, or `PRODUCTION_IN_PROGRESS` status; campaigns in `PROPOSED`, `COMPLETED`, or `PREEMPTED` consume nothing."

    Design: Difficulty/compensating_invariant/allocate_deallocate_roundtrip_conserves_capacity_hours
    """
    env, c1, c2 = _capacity_env()
    validate_error(api.advance_campaign(c2["id"], "ALLOCATED", process_engineer_headers),
                   ApiErrorId.ERR_CAPACITY_EXCEEDED)
    advance_campaign(c1["id"], "PROPOSED")
    advance_campaign(c2["id"], "ALLOCATED")
    c1_after = validate_success(api.get_campaign(c1["id"], platform_admin_headers))
    assert c1_after["status"] == "PROPOSED" and c1_after["allocated_hours"] == 72
    rows, meta = validate_paginated(api.list_campaigns(
        platform_admin_headers, params={"site_id": env["site"]["id"], "status": "ALLOCATED"}))
    assert meta["total_count"] == 1 and rows[0]["id"] == c2["id"]


def test_clinical_allocation_preempts_latest_starting_commercial_first(
        api, platform_admin_headers, process_engineer_headers):
    """PRD §3.2: "If it does not fit and the candidate is `CLINICAL`, the waterfall preempts: among the site's `COMMERCIAL` campaigns in `ALLOCATED` whose `planned_start_utc` falls in the same month, candidates are taken one at a time in order of latest `planned_start_utc` first, ties broken by earliest `created_at`, each moved from `ALLOCATED` to `PREEMPTED` with its firm hours released, and availability recomputed after each preemption, until the candidate fits or the candidates are exhausted."

    Design: Corner/complexity_layers/clinical_allocation_preempts_latest_starting_commercial_first
    """
    env = setup_master_data(site_overrides={
        "name": "Breda Pilot Plant", "region": "NL-BRE", "monthly_capacity_hours": 150,
        "cold_storage_capacity_units": 10000000, "licensed_authorities": ["EMA"]})
    prod_id = env["product"]["id"]
    trains = {code: create_train_entity(
        env["site"]["id"], train_code=code, capacity_liters=2000,
        supported_molecule_types=["MONOCLONAL_ANTIBODY"]) for code in ("TR-A", "TR-B", "TR-C")}
    ca1 = create_campaign_entity(trains["TR-A"]["id"], prod_id, demand_type="COMMERCIAL",
                                 planned_start_utc="2026-10-05T00:00:00Z",
                                 planned_end_utc="2026-10-15T00:00:00Z",
                                 upstream_hours=20, downstream_hours=30)
    advance_campaign(ca1["id"], "ALLOCATED")
    set_logical_clock("2026-10-01T01:00:00Z")
    ca2 = create_campaign_entity(trains["TR-B"]["id"], prod_id, demand_type="COMMERCIAL",
                                 planned_start_utc="2026-10-20T00:00:00Z",
                                 planned_end_utc="2026-10-30T00:00:00Z",
                                 upstream_hours=20, downstream_hours=30)
    advance_campaign(ca2["id"], "ALLOCATED")
    cl1 = create_campaign_entity(trains["TR-C"]["id"], prod_id, demand_type="CLINICAL",
                                 planned_start_utc="2026-10-12T00:00:00Z",
                                 planned_end_utc="2026-10-22T00:00:00Z",
                                 upstream_hours=20, downstream_hours=30)
    data = validate_success(api.advance_campaign(cl1["id"], "ALLOCATED", process_engineer_headers))
    assert data["status"] == "ALLOCATED"
    assert validate_success(api.get_campaign(ca2["id"], platform_admin_headers))["status"] == "PREEMPTED"
    assert validate_success(api.get_campaign(ca1["id"], platform_admin_headers))["status"] == "ALLOCATED"
