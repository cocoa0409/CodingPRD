"""Temporal overlap semantics: closed windows on a site, half-open windows on a unit.

Difficulty queue A: resource_temporal_overlap.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_entitlement,
    create_manual_order,
    get_success_data,
    make_installer_headers,
    setup_approved_design,
    setup_system_with_units,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_second_system_on_the_same_site_overlapping_is_refused(api):
    """PRD §3.3: "Finally the proposed coverage window must not overlap a live coverage
    window on the same `site_address` among systems whose `warranty_status` is `ACTIVE`
    or `TRANSFERRED`; an overlap is `ERR_WARRANTY_WINDOW_OVERLAP`." PRD §3.3: "Step five
    builds the `coverage_window` as the closed interval running from `warranty_start_at`
    to `extended_warranty_end_at`, both endpoints included."

    Design: Difficulty/resource_temporal_overlap/system_coverage_window_overlap_closed_interval_same_site
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO1", unit_serials=["RO1-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO1", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2020-01-01T00:00:00Z",
        site_address="15 Romeo Way",
    )
    second_design = setup_approved_design(ctx["installer"]["id"], site_address="15 Romeo Way",
                                          site_postal_code="94015")
    payload = {
        "installer_id": ctx["installer"]["id"],
        "design_project_id": second_design["id"],
        "site_address": "15 Romeo Way",
        "site_postal_code": "94015",
        "homeowner_name": "R. Romeo",
        "homeowner_email": "r@romeo.example",
        "commissioned_at": "2045-01-01T00:00:00Z",
        "units": [{"serial_number": "RO1-U2", "model_code": "IQ8",
                   "installed_at": "2045-01-01T00:00:00Z",
                   "production_lot_code": "LOT-RO1"}],
    }
    resp = api_client.create_system_registration(
        payload, make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WARRANTY_WINDOW_OVERLAP, 409)
    systems = get_success_data(api_client.list_system_registrations(
        ADMIN, {"installer_id": ctx["installer"]["id"]}))
    assert len(systems) == 1


def test_adjacent_system_window_starting_after_the_live_window_is_accepted(api):
    """PRD §3.3: "Step five builds the `coverage_window` as the closed interval running
    from `warranty_start_at` to `extended_warranty_end_at`, both endpoints included."
    PRD §3.3: "Finally the proposed coverage window must not overlap a live coverage
    window on the same `site_address` among systems whose `warranty_status` is `ACTIVE`
    or `TRANSFERRED`; an overlap is `ERR_WARRANTY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/system_coverage_window_overlap_closed_interval_same_site
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO1B", unit_serials=["RO1B-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO1B", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2020-01-01T00:00:00Z",
        site_address="15b Romeo Way",
    )
    second_design = setup_approved_design(ctx["installer"]["id"], site_address="15b Romeo Way",
                                          site_postal_code="94015")
    payload = {
        "installer_id": ctx["installer"]["id"],
        "design_project_id": second_design["id"],
        "site_address": "15b Romeo Way",
        "site_postal_code": "94015",
        "homeowner_name": "R. Romeo",
        "homeowner_email": "r@romeo.example",
        "commissioned_at": "2055-01-02T00:00:00Z",
        "units": [{"serial_number": "RO1B-U2", "model_code": "IQ8",
                   "installed_at": "2055-01-02T00:00:00Z",
                   "production_lot_code": "LOT-RO1B"}],
    }
    created = get_success_data(api_client.create_system_registration(
        payload, make_installer_headers(ctx["installer"]["id"])), 201)
    assert created["warranty_status"] == "ACTIVE"
    systems = get_success_data(api_client.list_system_registrations(
        ADMIN, {"installer_id": ctx["installer"]["id"]}))
    assert len(systems) == 2


def test_entitlement_window_starting_where_the_previous_one_ends_is_accepted(api):
    """PRD §3.7: "The entitlement window runs from `effective_from` for exactly three
    months, and the interval is half-open: it includes its start instant and excludes
    the instant three months later, which means a window ending exactly where the next
    one begins does not overlap it".

    Design: Difficulty/resource_temporal_overlap/entitlement_window_overlap_half_open_interval_same_unit
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO2", unit_serials=["RO2-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO2", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="16 Sierra Way",
    )
    unit = ctx["units"][0]
    first = create_entitlement(unit["id"], "2026-02-01T00:00:00Z")
    assert first["effective_from"] == "2026-02-01T00:00:00.000Z"
    second = create_entitlement(unit["id"], "2026-05-01T00:00:00Z")
    assert second["unit_id"] == unit["id"], (
        "adjacency is permitted because the interval is half-open"
    )
    after = get_success_data(api_client.get_unit(unit["id"], ADMIN))
    assert after["replacement_count"] == 2


def test_entitlement_window_overlapping_the_previous_one_is_refused(api):
    """PRD §3.7: "while any genuine overlap with an existing entitlement window on the
    same unit is refused with `ERR_ENTITLEMENT_WINDOW_OVERLAP`." PRD §3.7: "Recording
    the entitlement creates a replacement order for the unit with both `claim_id` and
    `campaign_id` left null, and increments the unit's `replacement_count`."

    Design: Difficulty/resource_temporal_overlap/entitlement_window_overlap_half_open_interval_same_unit
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO2B", unit_serials=["RO2B-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO2B", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="16b Sierra Way",
    )
    unit = ctx["units"][0]
    create_entitlement(unit["id"], "2026-02-01T00:00:00Z")
    create_entitlement(unit["id"], "2026-05-01T00:00:00Z")
    resp = api_client.create_billing_entitlement(
        {"unit_id": unit["id"], "entitlement_kind": "SERVICE_PLAN",
         "effective_from": "2026-04-01T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_WINDOW_OVERLAP, 409)
    after = get_success_data(api_client.get_unit(unit["id"], ADMIN))
    assert after["replacement_count"] == 2, "the refused window reserves no position"


def test_entitlement_replacement_order_is_unattached_to_a_claim_or_campaign(api):
    """PRD §3.7: "Recording the entitlement creates a replacement order for the unit
    with both `claim_id` and `campaign_id` left null, and increments the unit's
    `replacement_count`."

    Design: Difficulty/resource_temporal_overlap/entitlement_window_overlap_half_open_interval_same_unit
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO2C", unit_serials=["RO2C-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO2C", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="16c Sierra Way",
    )
    unit = ctx["units"][0]
    create_entitlement(unit["id"], "2026-02-01T00:00:00Z")
    orders = get_success_data(api_client.list_replacement_orders(ADMIN, {"unit_id": unit["id"]}))
    assert len(orders) == 1
    assert orders[0]["claim_id"] is None
    assert orders[0]["campaign_id"] is None
    assert orders[0]["status"] == "PENDING_DISPATCH"


def test_a_second_live_order_for_the_same_unit_is_refused(api):
    """PRD §3.7: "The same error covers the duplicate case: an order may not be created
    for a unit that already carries a live order from either source, so a unit cannot be
    double-shipped."

    Design: Difficulty/resource_temporal_overlap/entitlement_window_overlap_half_open_interval_same_unit
    """
    ctx = setup_system_with_units(
        installer_code="INST-RO2D", unit_serials=["RO2D-U1"], unit_models=["IQ8"],
        lot_code="LOT-RO2D", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="16d Sierra Way",
    )
    unit = ctx["units"][0]
    create_manual_order(unit["id"], unit["version"], model_code="IQ8")
    current = get_success_data(api_client.get_unit(unit["id"], ADMIN))
    resp = api_client.create_replacement_order(
        {"unit_id": unit["id"], "replacement_model_code": "IQ8",
         "expected_unit_version": current["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CHARGEABLE, 409)