"""Entity assertions — field presence/type checks against PRD §2.5 and §3."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def _assert_immutable_record_fields(data: dict):
    """Quality audits and consumption records carry only id + created_at among
    system fields; updated_at and version are absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "immutable records must not carry version"
    assert "updated_at" not in data, "immutable records must not carry updated_at"


def assert_brand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("PLATFORM_OWNED", "LICENSED", "UNLICENSED_COMPATIBLE")
    assert isinstance(data["home_region"], str) and data["home_region"]


def assert_license_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_id"], str) and data["brand_id"]
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    tiers = data["royalty_tiers"]
    assert isinstance(tiers, list) and len(tiers) >= 1
    for tier in tiers:
        assert tier["up_to_units"] is None or isinstance(tier["up_to_units"], int)
        assert isinstance(tier["millicents_per_pod"], int)
    assert isinstance(data["quality_min_cup_score"], int)
    assert isinstance(data["exclusive"], bool)
    assert data["amendment_of_id"] is None or isinstance(data["amendment_of_id"], str)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED", "SUPERSEDED")


def assert_quality_audit(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["agreement_id"], str) and data["agreement_id"]
    assert is_iso8601_timestamp(data["audited_at"])
    assert isinstance(data["cup_score"], int) and 0 <= data["cup_score"] <= 100
    assert isinstance(data["defect_rate_ppm"], int) and data["defect_rate_ppm"] >= 0
    assert data["result"] in ("PASS", "FAIL")


def assert_pod_variety(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_id"], str) and data["brand_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["roast_level"] in ("LIGHT", "MEDIUM", "DARK")
    assert data["flavor_family"] in ("UNFLAVORED", "FLAVORED")
    assert data["material"] in ("CONVENTIONAL", "RECYCLABLE")
    assert isinstance(data["wholesale_price_cents"], int)
    assert isinstance(data["margin_cents"], int)
    assert isinstance(data["education_notices_sent"], int)
    assert isinstance(data["velocity_units_90d"], int)
    assert isinstance(data["slow_mover"], bool)
    assert data["status"] in ("ACTIVE", "PHASE_OUT", "DELISTED", "SUPPLY_BLOCKED")


def assert_brewer_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["firmware_compat"] in ("OPEN", "RESTRICTIVE")
    assert isinstance(data["warranty_months"], int)
    assert isinstance(data["descale_interval_brews"], int)
    assert isinstance(data["msrp_cents"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["subsidy_cents"], int)
    assert isinstance(data["margin_cents"], int)


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("OWNED", "PARTNER")
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["total_capacity_pods_per_day"], int)
    assert data["total_capacity_pods_per_day"] >= 0


def assert_filling_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["facility_id"], str) and data["facility_id"]
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["supported_roast"] in ("LIGHT", "MEDIUM", "DARK", "UNIVERSAL")
    assert isinstance(data["supports_flavored"], bool)
    assert data["material_capability"] in ("CONVENTIONAL", "RECYCLABLE", "BOTH")
    assert isinstance(data["capacity_pods_per_day"], int)
    assert isinstance(data["changeover_hours"], int)


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_id"], str) and data["line_id"]
    assert isinstance(data["variety_id"], str) and data["variety_id"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["planned_units"], int)
    assert data["actual_units"] is None or isinstance(data["actual_units"], int)
    assert data["status"] in ("RESERVED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["size"], int) and data["size"] >= 1
    assert isinstance(data["installed_brewers"], int) and data["installed_brewers"] >= 0
    assert data["engagement"] in ("ENGAGED", "LAPSED", "CHURNED")
    assert isinstance(data["trailing_avg_pods"], (int, float))
    assert isinstance(data["expected_monthly_pods"], (int, float))


def assert_brewer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert isinstance(data["model_id"], str) and data["model_id"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert is_iso8601_timestamp(data["registered_at"])
    assert isinstance(data["brew_count"], int) and data["brew_count"] >= 0
    assert is_iso8601_timestamp(data["last_brew_at"])
    assert isinstance(data["last_descaled_brew_count"], int)
    assert isinstance(data["descale_overdue"], bool)
    assert data["warranty_status"] in ("IN_WARRANTY", "EXPIRED", "VOID")
    assert data["operational"] in ("ACTIVE", "DORMANT", "DECOMMISSIONED")


def assert_consumption_record(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["pods_brewed"], int) and data["pods_brewed"] >= 0


def assert_service_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brewer_id"], str) and data["brewer_id"]
    assert data["kind"] in ("WARRANTY_CLAIM", "DESCALING", "REPLACEMENT")
    assert data["status"] in ("OPEN", "RESOLVED", "DENIED")
    assert data["resolution"] is None or data["resolution"] in (
        "APPROVED", "DENIED", "MISUSE_CONFIRMED", "AUTO_DENIED_DESCALE")
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])


def assert_retail_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["shelf_slots_total"], int)
    assert isinstance(data["productivity_floor_cents"], int)


def assert_assortment_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    slots = data["slots"]
    assert isinstance(slots, list) and len(slots) >= 1
    for slot in slots:
        assert isinstance(slot["variety_id"], str) and slot["variety_id"]
        assert isinstance(slot["facings"], int) and slot["facings"] >= 1
        assert isinstance(slot["clearance_flag"], bool)
    assert data["productivity_cents"] is None or isinstance(data["productivity_cents"], int)
    assert data["status"] in (
        "DRAFT", "PROPOSED", "APPROVED", "LOCKED", "CANCELLED", "SUPERSEDED")


def assert_royalty_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str) and data["agreement_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["sell_in_units"], int)
    assert isinstance(data["sell_through_units"], int)
    assert isinstance(data["unlicensed_share_pct"], int)
    assert 0 <= data["unlicensed_share_pct"] <= 100
    assert isinstance(data["provisional_royalty_cents"], int)
    assert data["final_royalty_cents"] is None or isinstance(
        data["final_royalty_cents"], int)
    assert isinstance(data["dispute_count"], int) and data["dispute_count"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "SETTLED")
