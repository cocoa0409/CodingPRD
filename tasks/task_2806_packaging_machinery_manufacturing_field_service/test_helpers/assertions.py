"""Entity assertions and domain invariant checkers for the packaging OEM API."""

from typing import Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict) -> None:
    """Every persisted row carries a UUID `id` and an ISO 8601 `created_at`,
    and almost every entity also carries `updated_at` and `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_append_only_fields(data: dict) -> None:
    """Warranty claim cost lines are immutable: they carry only `id` and
    `created_at`, with no `updated_at` and no `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "an immutable claim line has no updated_at field"
    assert "version" not in data, "an immutable claim line has no version field"


def assert_customer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert data["region_code"] in ["NA", "EU", "APAC", "LATAM"]
    assert 0.00 <= float(data["product_variation_pct"]) <= 40.00
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["open_order_count"], int) and data["open_order_count"] >= 0


def assert_machine_model(data: dict) -> None:
    assert_common_fields(data)
    assert 3 <= len(data["model_code"]) <= 32
    assert data["machine_family"] in ["FILLER", "CAPPER", "LABELER", "CARTONER"]
    assert data["nameplate_rate_cpm"] >= 1
    assert 50.00 <= float(data["guarantee_efficiency_pct"]) <= 100.00
    assert data["base_price_cents"] >= 0
    assert data["min_container_diameter_mm"] >= 1
    assert data["max_container_diameter_mm"] >= data["min_container_diameter_mm"]
    assert data["lifecycle_status"] in ["ACTIVE", "OBSOLETE"]
    assert data["open_defect_review_count"] >= 0


def assert_production_line(data: dict) -> None:
    assert_common_fields(data)
    assert 2 <= len(data["line_code"]) <= 24
    assert data["machine_family"] in ["FILLER", "CAPPER", "LABELER", "CARTONER"]
    assert data["changeover_buffer_days"] >= 0
    assert data["capacity_days_per_quarter"] >= 1
    assert data["status"] in ["OPEN", "MAINTENANCE"]
    assert data["committed_slot_days"] >= 0


def assert_field_engineer(data: dict) -> None:
    assert_common_fields(data)
    assert 1 <= len(data["full_name"]) <= 80
    assert data["region_code"] in ["NA", "EU", "APAC", "LATAM"]
    assert isinstance(data["certifications"], list)
    assert data["status"] in ["AVAILABLE", "ON_LEAVE"]


def assert_product_trial(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "TESTING", "RETEST_REQUIRED", "PASSED", "REJECTED"]
    assert data["config_recommendation"] in ["PENDING", "STANDARD", "HEAVY_DUTY", "NOT_FEASIBLE"]
    assert 0 <= data["retest_count"] <= 2
    assert data["container_diameter_mm"] >= 1


def assert_machine_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["fulfillment_status"] in [
        "DRAFT",
        "ENGINEERED",
        "SLOTTED",
        "IN_BUILD",
        "FAT_PASSED",
        "FAT_FAILED",
        "SHIPPED",
        "INSTALLED",
        "ACCEPTED",
        "CANCELLED",
    ]
    assert data["commercial_status"] in [
        "QUOTED",
        "PO_RECEIVED",
        "INVOICED",
        "PAID",
        "WRITTEN_OFF",
    ]
    assert data["discount_tier"] in ["NONE", "T1", "T2", "T3"]
    assert data["guarantee_basis"] in ["NAMEPLATE", "PRODUCT_ADJUSTED"]
    assert data["equipment_price_cents"] >= 0
    assert data["change_parts_price_cents"] >= 0
    assert data["rework_days"] >= 0
    assert data["fat_failure_count"] >= 0
    assert_whole_cents(data["commissioning_fee_cents"])
    assert_whole_cents(data["order_total_cents"])


def assert_long_lead_component(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["PLANNED", "ON_ORDER", "RECEIVED"]
    assert data["lead_time_days"] >= 0


def assert_build_slot(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in [
        "RESERVED",
        "CONFIRMED",
        "IN_BUILD",
        "REWORK_HOLD",
        "RELEASED",
        "DISPLACED",
        "COMPLETED",
    ]
    assert data["slot_days"] >= 1


def assert_acceptance_test(data: dict) -> None:
    assert_common_fields(data)
    assert data["kind"] in ["FAT", "SAT"]
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED"]
    assert isinstance(data["guarantee_met"], bool)
    assert 0.00 <= float(data["measured_efficiency_pct"]) <= 100.00
    assert float(data["attainment_pct"]) >= 0.00


def assert_installed_machine(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["INSTALLED", "ACCEPTED"]
    assert 4 <= len(data["serial_number"]) <= 32
    assert isinstance(data["remote_diagnostics_enabled"], bool)
    assert data["open_claim_count"] >= 0


def assert_format_kit(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "QUOTED", "ORDERED", "DELIVERED"]
    assert data["component_count"] >= 0
    assert 0 <= data["quoted_lead_time_days"] <= 180
    assert_whole_cents(data["price_cents"])


def assert_service_contract(data: dict) -> None:
    assert_common_fields(data)
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert data["coverage_posture"] in ["OPEN", "RESTRICTED", "BUDGET_EXHAUSTED"]
    assert data["pm_visits_included"] >= 0
    assert_goodwill_ledger_invariants(data)


def assert_pm_visit(data: dict) -> None:
    assert_common_fields(data)
    assert data["visit_type"] in ["PM", "REMOTE_DIAGNOSTIC", "CORRECTIVE"]
    assert data["status"] in ["SCHEDULED", "BILLABLE_HOLD", "COMPLETED", "CANCELLED"]
    assert isinstance(data["billable"], bool)
    assert data["findings_code"] in ["NONE", "OK", "WEAR_FOUND", "FAULT_FOUND"]


def assert_warranty_claim(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED",
        "PRODUCT_VARIATION_REVIEW",
        "DEFECT_REVIEW",
        "ADJUDICATED",
        "REJECTED",
        "VOID",
    ]
    assert data["cause"] in ["UNDETERMINED", "MACHINE_DEFECT", "PRODUCT_VARIATION", "MIXED"]
    assert isinstance(data["product_variation_review_done"], bool)
    assert isinstance(data["defect_review_done"], bool)
    for field in ("claimed_cost_cents", "oem_share_cents", "customer_share_cents", "goodwill_charged_cents"):
        assert_whole_cents(data[field])


def assert_warranty_claim_line(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["amount_cents"] >= 1
    assert 0.00 <= float(data["defect_attribution_pct"]) <= 100.00
    assert_whole_cents(data["oem_line_share_cents"])


def assert_stocking_recommendation(data: dict) -> None:
    assert_common_fields(data)
    assert data["criticality"] in ["A", "B", "C"]
    assert data["basis"] in ["LEAD_TIME_DEMAND", "SERVICE_LEVEL"]
    assert data["obsolescence_status"] in [
        "ACTIVE",
        "NOTICE_ISSUED",
        "LAST_TIME_BUY",
        "OBSOLETE",
    ]
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["recommended_qty"], int) and data["recommended_qty"] >= 0


# --- Domain invariant checkers ------------------------------------------


def assert_whole_cents(amount) -> None:
    """All monetary amounts are integers denominated in cents (PRD §2.6)."""
    assert isinstance(amount, int) and not isinstance(amount, bool), (
        f"money must be an integer number of cents, got {amount!r}"
    )


def assert_two_decimal_pct(value) -> None:
    """All percentages are decimal numbers carried to two decimal places (PRD §2.6)."""
    assert round(float(value), 2) == float(value), (
        f"percentage must carry at most two decimals, got {value!r}"
    )


def assert_goodwill_ledger_invariants(contract: dict) -> None:
    """`goodwill_budget_cents` may reach exactly 0 but must never become
    negative, and never exceeds the initial pot (PRD §2.9)."""
    assert_whole_cents(contract["goodwill_budget_cents"])
    assert_whole_cents(contract["goodwill_budget_initial_cents"])
    assert contract["goodwill_budget_cents"] >= 0, "the goodwill pot must never go negative"
    assert contract["goodwill_budget_cents"] <= contract["goodwill_budget_initial_cents"]


def assert_committed_slot_days(line: dict, slots: List[dict]) -> None:
    """`committed_slot_days` is the sum of `slot_days` over the line's slots in
    RESERVED, CONFIRMED, IN_BUILD or REWORK_HOLD (PRD §2.9)."""
    committed_states = {"RESERVED", "CONFIRMED", "IN_BUILD", "REWORK_HOLD"}
    expected = sum(s["slot_days"] for s in slots if s["status"] in committed_states)
    assert line["committed_slot_days"] == expected, (
        f"committed_slot_days {line['committed_slot_days']} != sum of committed slot_days {expected}"
    )


def assert_claim_shares_add_back(claim: dict) -> None:
    """`customer_share_cents` is the exact residual, so the two shares always
    add back to `claimed_cost_cents` (PRD §3.9)."""
    assert claim["oem_share_cents"] + claim["customer_share_cents"] == claim["claimed_cost_cents"]


def assert_coverage_posture(contract: dict) -> None:
    """Posture reads BUDGET_EXHAUSTED at exactly 0, RESTRICTED above 0 and up to
    50,000 cents, OPEN otherwise (PRD §3.8)."""
    pot = contract["goodwill_budget_cents"]
    if pot == 0:
        expected = "BUDGET_EXHAUSTED"
    elif pot <= 50_000:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert contract["coverage_posture"] == expected, (
        f"pot {pot} implies posture {expected}, got {contract['coverage_posture']}"
    )


def assert_meta_envelope(body: dict) -> None:
    """`api_request_id` starts with `req_` and `api_request_timestamp` is an ISO
    8601 UTC timestamp with three fractional digits (PRD §2.2)."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), "api_request_id must start with req_"
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_ascending_created_at(rows: List[dict]) -> None:
    """List results are returned in ascending `created_at` order (PRD §2.3)."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows must be oldest-first, got {stamps}"


def assert_version_bumped_by(before: dict, after: dict, delta: int = 1) -> None:
    """`version` increments by exactly 1 on every mutation of the row (PRD §2.4)."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )
