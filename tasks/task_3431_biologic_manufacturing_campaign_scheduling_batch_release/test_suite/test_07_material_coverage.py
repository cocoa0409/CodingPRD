"""Material coverage at seed-train start: overage, FEFO consumption, source blocking."""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_error, validate_paginated,
    setup_campaign,
    create_material_lot, create_campaign_entity,
    advance_campaign, add_seed_stage, set_logical_clock,
)

_MEDIA_PRODUCT = {
    "product_code": "MAB-MAT",
    "required_materials": [
        {"material_name": "MEDIA-X", "base_quantity": 33, "is_single_source": False}],
}
_SINGLE_SOURCE_PRODUCT = {
    "product_code": "MAB-SS",
    "required_materials": [
        {"material_name": "CHO-CDM", "base_quantity": 100, "is_single_source": True}],
}


def test_material_coverage_overage_rounding_and_fefo_consumption(api, platform_admin_headers):
    """PRD §3.3: "the required quantity for an entry is its `base_quantity` increased by a ten percent overage — that is, multiplied by 1.10 — rounded half-up to two decimal places"
    PRD §3.3: "for each entry, the matching `AVAILABLE` lots are iterated in `created_at` ascending order, each decremented by the smaller of its `quantity_available` and the remaining requirement, until the required quantity is covered."

    Design: Corner/calculations/material_coverage_overage_rounding_and_fefo_consumption
    """
    env = setup_campaign(product_overrides=_MEDIA_PRODUCT,
                         campaign_overrides={"demand_type": "CLINICAL"})
    lot1 = create_material_lot(env["site"]["id"], material_name="MEDIA-X",
                               is_single_source=False, quantity=20)
    set_logical_clock("2026-10-01T01:00:00Z")
    lot2 = create_material_lot(env["site"]["id"], material_name="MEDIA-X",
                               is_single_source=False, quantity=20)
    camp_id = env["campaign"]["id"]
    advance_campaign(camp_id, "ALLOCATED")
    add_seed_stage(camp_id, 1, 10)
    started = advance_campaign(camp_id, "SEED_IN_PROGRESS")
    assert started["status"] == "SEED_IN_PROGRESS", "20 + 20 = 40 >= 36.30 required"
    lots, _meta = validate_paginated(
        api.list_materials(env["site"]["id"], platform_admin_headers))
    by_id = {lot["id"]: lot for lot in lots}
    assert by_id[lot1["id"]]["quantity_available"] == pytest.approx(0.0, abs=1e-6)
    assert by_id[lot2["id"]]["quantity_available"] == pytest.approx(3.7, abs=1e-6), \
        "20 - 16.30 after the earlier-created lot drained first"


def test_multi_source_material_shortage_rejected(api, process_engineer_headers):
    """PRD §3.3: "this single-source check is evaluated *before* the generic shortage check, which rejects a shortfall on a multi-source entry with `ERR_MATERIAL_SHORTAGE` (HTTP 409)."

    Design: Corner/validations/multi_source_material_shortage_rejected
    """
    env = setup_campaign(product_overrides=_MEDIA_PRODUCT,
                         campaign_overrides={"demand_type": "CLINICAL"})
    create_material_lot(env["site"]["id"], material_name="MEDIA-X",
                        is_single_source=False, quantity=30)
    camp_id = env["campaign"]["id"]
    advance_campaign(camp_id, "ALLOCATED")
    add_seed_stage(camp_id, 1, 10)
    resp = api.advance_campaign(camp_id, "SEED_IN_PROGRESS", process_engineer_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_MATERIAL_SHORTAGE)
    assert error_data["error_id"] != "ERR_SINGLE_SOURCE_MATERIAL_BLOCKED", "30 < 36.30"


def _single_source_env():
    """Product needing 100x1.10 == 110.00 of single-source CHO-CDM; exactly 110 in stock."""
    env = setup_campaign(product_overrides=_SINGLE_SOURCE_PRODUCT)
    create_material_lot(env["site"]["id"], material_name="CHO-CDM",
                        is_single_source=True, quantity=110)
    camp_id = env["campaign"]["id"]
    advance_campaign(camp_id, "ALLOCATED")
    add_seed_stage(camp_id, 1, 10)
    return env


def test_single_source_exact_stock_boundary_sufficient(api, platform_admin_headers):
    """PRD §3.3: "Availability exactly equal to the requirement is sufficient."

    Design: Difficulty/cross_entity_state_dependency/seed_start_gated_by_single_source_material_stock
    """
    env = _single_source_env()
    started = advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS")
    assert started["status"] == "SEED_IN_PROGRESS"
    lots, _meta = validate_paginated(
        api.list_materials(env["site"]["id"], platform_admin_headers))
    assert lots[0]["quantity_available"] == pytest.approx(0.0, abs=1e-6), \
        "110.00 consumed = 100 x 1.10 exactly"


def test_single_source_stock_exhausted_blocks_second_campaign(api, process_engineer_headers):
    """PRD §3.3: "When the entry is single-source and availability falls short, the rejection is `ERR_SINGLE_SOURCE_MATERIAL_BLOCKED` (HTTP 409); this single-source check is evaluated *before* the generic shortage check, which rejects a shortfall on a multi-source entry with `ERR_MATERIAL_SHORTAGE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/seed_start_gated_by_single_source_material_stock
    """
    env = _single_source_env()
    advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS")  # drains the only lot to 0
    camp2 = create_campaign_entity(
        env["train"]["id"], env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-21T00:00:00Z", planned_end_utc="2026-11-05T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    advance_campaign(camp2["id"], "ALLOCATED")
    add_seed_stage(camp2["id"], 1, 10)
    set_logical_clock("2026-10-21T00:00:00Z")
    resp = api.advance_campaign(camp2["id"], "SEED_IN_PROGRESS", process_engineer_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_SINGLE_SOURCE_MATERIAL_BLOCKED)
    assert error_data["error_id"] != "ERR_MATERIAL_SHORTAGE", \
        "available 0.0 < required 110.00 on a single-source entry"
