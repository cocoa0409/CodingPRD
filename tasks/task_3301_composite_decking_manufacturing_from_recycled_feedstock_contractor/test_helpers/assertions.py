"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_plant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["daily_capacity_lf"], int) and data["daily_capacity_lf"] >= 1
    assert isinstance(data["lines"], int) and data["lines"] >= 1
    assert isinstance(data["resin_store"], dict)
    for key in ("VIRGIN_PE", "REPRO_PE", "PCR_FILM", "WOOD_FLOUR"):
        assert key in data["resin_store"], f"resin_store missing key {key}"
        assert isinstance(data["resin_store"][key], int)
    assert isinstance(data["fg_store"], dict)
    assert isinstance(data["reserved_fg_store"], dict)
    assert data["season_posture"] in ("PRE_SEASON", "SELLING")


def assert_supplier(data: dict):
    _assert_common(data)
    assert data["kind"] in ("COLLECTION_PROGRAM", "BROKER")
    assert data["quality_tier"] in ("STANDARD", "PREFERRED")
    assert isinstance(data["reliability_score_bp"], int)


def assert_collection_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["rebate_per_lb_cents"], int)
    assert isinstance(data["accrued_rebate_cents"], int)


def assert_feedstock_lot(data: dict):
    _assert_common(data)
    assert data["material"] in ("PCR_FILM", "WOOD_FLOUR", "REPRO_PE", "VIRGIN_PE")
    assert data["status"] in ("QUARANTINE", "RELEASED", "REJECTED")
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] >= 1


def assert_formulation(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["active_revision"], int) and data["active_revision"] >= 1


def assert_product_line(data: dict):
    _assert_common(data)
    assert data["profile"] in ("GROOVED", "SQUARE", "FASCIA")
    assert data["emboss"] in ("WOODGRAIN", "SMOOTH")
    assert data["status"] in ("ACTIVE", "DISCONTINUED", "REPAIRED_SUPPORTED", "SUNSET")
    assert isinstance(data["capped"], bool)
    assert isinstance(data["repair_support_only"], bool)


def assert_dealer(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_shipment_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "SHIPPED", "DELIVERED", "CANCELLED")
    assert isinstance(data["lf"], int) and data["lf"] >= 1


def assert_stocking_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "MET", "SHORTFALL_PENALIZED", "WAIVED")
    assert isinstance(data["committed_lf"], int) and data["committed_lf"] >= 1
    assert isinstance(data["fulfilled_lf"], int)


def assert_allocation_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CONSUMED", "RELEASED", "EXPIRED")
    assert isinstance(data["reserved_lf"], int) and data["reserved_lf"] >= 1


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "RUNNING", "COMPLETED", "CANCELLED")
    assert data["run_kind"] in ("SELLABLE", "SUPPORT_STOCK", "NULL_SLOT")
    assert isinstance(data["planned_lf"], int) and data["planned_lf"] >= 1
    assert isinstance(data["changeover_minutes"], int)
    assert isinstance(data["total_minutes"], int)


def assert_board_lot(data: dict):
    _assert_common(data)
    assert data["disposition"] in (
        "AVAILABLE", "ALLOCATED", "SHIPPED", "CONSUMED_BY_CLAIM", "SCRAPPED",
    )
    assert isinstance(data["lf"], int)
    assert isinstance(data["support_tagged"], bool)


def assert_contractor(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLIED", "IN_TRAINING", "CERTIFIED", "SUSPENDED", "LAPSED")
    assert data["tier"] in ("SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["completed_project_count"], int)
    assert isinstance(data["enhanced_warranty_count"], int)


def assert_training_module(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["required_for_tier"] in ("SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1


def assert_training_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "PASSED", "FAILED")


def assert_lead_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ASSIGNED", "EXPIRED", "DECLINED")


def assert_install_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "INSTALLED", "CANCELLED")
    assert isinstance(data["enhanced_warranty"], bool)
    assert isinstance(data["warranty_years"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["category"] in ("FADING", "STAINING", "STRUCTURAL")
    assert data["status"] in ("FILED", "SAMPLE_REQUESTED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_claim_sample(data: dict):
    _assert_common(data)
    assert data["status"] in ("AWAITING", "RECEIVED", "REVIEWED")


def assert_sample_kit(data: dict):
    _assert_common(data)
    assert data["kit_type"] in ("DISPLAY_BOARD", "CHIP_SET")
    assert data["status"] in ("ORDERED", "DELIVERED", "RETIRED")


def assert_color_chip_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "FULFILLED", "CANCELLED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_price_book(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["base_prices"], dict)
    assert isinstance(data["tier_discounts_bp"], dict)
