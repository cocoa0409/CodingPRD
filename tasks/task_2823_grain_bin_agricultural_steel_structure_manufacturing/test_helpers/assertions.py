"""Entity assertions and domain invariant checkers for the grain bin API."""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COMPONENT_ORDER,
    CREDIT_PARTICIPATING_STATES,
    CREW_MAX_DIAMETER_M,
    TRAILER_MAX_CUBE_M3,
    TRAILER_MAX_WEIGHT_KG,
)

# ---------------------------------------------------------------------------
# Timestamp canonicalisation
# ---------------------------------------------------------------------------


def canonical_instant(value):
    """Reduce an ISO-8601 UTC instant to a precision-independent form.

    The PRD fixes a three-fractional-digit rendering for stored timestamps, but
    instants a test supplied itself (crew expiry, line windows, clock moves) may
    come back with a different sub-second width.  Comparisons in this suite go
    through this helper so that `2026-08-01T00:00:00Z`,
    `2026-08-01T00:00:00.000Z` and `2026-08-01T00:00:00+00:00` all compare
    equal, while a genuinely different instant still differs.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text


def assert_instant_equals(actual, expected, what="instant"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {what} {expected!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Envelope-level shape rules (PRD 2.5)
# ---------------------------------------------------------------------------


def assert_immutable_config_shape(data: dict, entity_name: str):
    """Immutable reference/derived rows carry ONLY `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    assert (
        "updated_at" not in data
    ), f"{entity_name} must not emit updated_at (immutable configuration)"
    assert (
        "version" not in data
    ), f"{entity_name} must not emit version (immutable configuration)"


def assert_versioned_shape(data: dict, entity_name: str):
    """Mutable rows carry id, created_at, updated_at and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an int"
    assert data["version"] >= 1, f"{entity_name}.version begins at 1"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_jurisdiction(data: dict):
    assert_immutable_config_shape(data, "Jurisdiction")
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 16
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seal_required"], bool)
    assert 80 <= data["min_design_wind_speed_mph"] <= 200
    assert data["seismic_design_category"] in ("A", "B", "C", "D")
    assert 0 <= data["permit_review_days"] <= 90


def assert_grain_profile(data: dict):
    assert_immutable_config_shape(data, "GrainProfile")
    assert isinstance(data["grain_code"], str) and data["grain_code"]
    assert 300 <= data["bulk_density_kg_per_m3"] <= 1400
    assert 0.20 <= data["janssen_k_ratio"] <= 0.70
    assert 8.0 <= data["max_safe_moisture_pct"] <= 20.0
    assert 0.5 <= data["aeration_cfm_per_m3_base"] <= 6.0
    assert 1.0 <= data["drying_multiplier"] <= 8.0


def assert_coating_spec(data: dict):
    assert_immutable_config_shape(data, "CoatingSpec")
    assert isinstance(data["coating_code"], str) and data["coating_code"]
    assert 150 <= data["zinc_mass_g_per_m2"] <= 900
    assert 0 <= data["coating_cost_per_kg_cents"] <= 500
    assert 0 <= data["changeover_minutes"] <= 480
    assert 8.0 <= data["max_ambient_moisture_pct"] <= 24.0
    assert data["corrosion_class"] in ("C2", "C3", "C4", "C5")


def assert_roll_forming_line(data: dict):
    assert_immutable_config_shape(data, "RollFormingLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert 0.8 <= data["max_gauge_mm"] <= 6.0


def assert_kit_line(data: dict):
    assert_immutable_config_shape(data, "KitLine")
    assert is_valid_uuid(data["dealer_order_id"])
    assert data["component_code"] in COMPONENT_ORDER
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_cents"], int)
    assert data["extended_cents"] == data["quantity"] * data["unit_price_cents"], (
        "extended_cents is quantity multiplied by unit_price_cents"
    )
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["cube_m3"], (int, float))


def assert_engineer(data: dict):
    assert_versioned_shape(data, "Engineer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["licensed_jurisdiction_codes"], list)
    assert data["licensed_jurisdiction_codes"], "licensed_jurisdiction_codes is non-empty"
    assert data["status"] in ("ACTIVE", "LAPSED")


def assert_dealer(data: dict):
    assert_versioned_shape(data, "Dealer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_committed_cents"], int)
    assert isinstance(data["credit_available_cents"], int)
    assert data["program_tier"] in ("BASE", "PREFERRED", "ELITE")
    assert 1 <= data["staging_slots"] <= 20
    assert isinstance(data["staged_kit_count"], int) and data["staged_kit_count"] >= 0
    assert isinstance(data["high_cube_access"], bool)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert_dealer_ledger_invariants(data)


def assert_bin_design(data: dict):
    assert_versioned_shape(data, "BinDesign")
    for fk in ("dealer_id", "jurisdiction_id", "grain_profile_id", "coating_spec_id"):
        assert is_valid_uuid(data[fk]), f"BinDesign.{fk} must be a UUID"
    assert is_valid_uuid(data["author_engineer_id"])
    assert 4.0 <= data["diameter_m"] <= 30.0
    assert 3.2 <= data["eave_height_m"] <= 24.0
    assert data["roof_pitch_deg"] in (25, 30, 35)
    assert 80 <= data["design_wind_speed_mph"] <= 200
    assert 8.0 <= data["moisture_pct"] <= 24.0
    assert data["design_method"] in ("ASD", "LRFD")
    assert isinstance(data["seal_required"], bool)
    assert data["governing_load_case"] in (
        "GRAIN_LATERAL",
        "WIND_UPLIFT",
        "SEISMIC_BASE_SHEAR",
    )
    assert 4 <= data["required_stiffener_count"] <= 24
    assert data["sheet_gauge_mm"] in (1.0, 1.3, 1.6, 2.0, 2.5, 3.0)
    assert isinstance(data["roof_ring_required"], bool)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["status"] in (
        "DRAFT",
        "UNDER_REVIEW",
        "REVISION_REQUIRED",
        "SEALED",
        "RECALLED",
    )
    assert data["governing_demand_kpa"] == max(
        data["grain_demand_kpa"], data["wind_demand_kpa"], data["seismic_demand_kpa"]
    ), "governing_demand_kpa is the largest of the three rounded demands"


def assert_design_analysis(data: dict):
    assert_versioned_shape(data, "DesignAnalysis")
    assert is_valid_uuid(data["bin_design_id"])
    assert isinstance(data["analysis_index"], int) and data["analysis_index"] >= 1
    assert data["design_method"] in ("ASD", "LRFD")
    assert data["allowable_kpa_m"] == pytest.approx(
        90.0 if data["design_method"] == "ASD" else 101.25
    )
    assert data["verdict"] in ("PASS", "FAIL")
    assert isinstance(data["superseded"], bool)
    expected_verdict = "PASS" if data["utilization_ratio"] <= 1.0 else "FAIL"
    assert data["verdict"] == expected_verdict, (
        "verdict is PASS when the utilization_ratio is at or below 1.0"
    )


def assert_coil_lot(data: dict):
    assert_versioned_shape(data, "CoilLot")
    assert is_valid_uuid(data["coating_spec_id"])
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert 0.8 <= data["gauge_mm"] <= 6.0
    assert 100.0 <= data["received_kg"] <= 200000.0
    assert data["status"] in ("AVAILABLE", "DEPLETED", "QUARANTINED")
    assert_coil_mass_conservation(data)


def assert_roll_forming_run(data: dict):
    assert_versioned_shape(data, "RollFormingRun")
    for fk in ("roll_forming_line_id", "coil_lot_id", "dealer_order_id"):
        assert is_valid_uuid(data[fk]), f"RollFormingRun.{fk} must be a UUID"
    assert isinstance(data["coating_code"], str) and data["coating_code"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert 1.0 <= data["planned_kg"] <= 200000.0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "VOIDED")


def assert_dealer_order(data: dict):
    assert_versioned_shape(data, "DealerOrder")
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["bin_design_id"])
    assert data["order_season"] in ("PRESEASON", "HARVEST_PEAK", "OFFSEASON")
    assert data["aeration_package"] in ("NONE", "AERATION", "DRYING_FULL")
    assert data["unload_system"] in ("GRAVITY", "SWEEP_AUGER", "POWER_SWEEP")
    assert data["production_status"] in (
        "DRAFT",
        "QUEUED",
        "KITTED",
        "SHIPPED",
        "HOLD_CREDIT",
        "HOLD_ENGINEERING",
        "CANCELLED",
    )
    assert data["financial_status"] in (
        "AWAITING_DEPOSIT",
        "DEPOSIT_PAID",
        "RELEASED",
        "VOIDED",
    )
    assert data["installation_readiness"] in ("UNASSIGNED", "ASSIGNED", "BLOCKED")
    for money in (
        "kit_subtotal_cents",
        "season_uplift_cents",
        "program_discount_cents",
        "net_subtotal_cents",
        "freight_surcharge_cents",
        "total_cents",
        "required_deposit_cents",
        "deposit_paid_cents",
        "credit_hold_cents",
        "allocated_freight_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be a whole-cent integer"
    assert_order_price_buildup(data)


def assert_order_price_buildup(data: dict):
    """The pinned relations between the order's money fields (PRD 3.4)."""
    assert (
        data["net_subtotal_cents"]
        == data["kit_subtotal_cents"]
        + data["season_uplift_cents"]
        - data["program_discount_cents"]
    ), "net_subtotal_cents is kit_subtotal plus season uplift minus program discount"
    assert (
        data["total_cents"]
        == data["net_subtotal_cents"] + data["freight_surcharge_cents"]
    ), "total_cents is net_subtotal_cents plus freight_surcharge_cents"
    assert (
        data["credit_hold_cents"] == 0
        or data["credit_hold_cents"]
        == data["total_cents"] - data["required_deposit_cents"]
    ), "credit_hold_cents is total_cents minus required_deposit_cents"


def assert_freight_load(data: dict):
    assert_versioned_shape(data, "FreightLoad")
    assert is_valid_uuid(data["dealer_id"])
    assert data["trailer_type"] in ("FLATBED", "HIGH_CUBE_VAN", "STEP_DECK")
    assert data["allocation_basis"] in ("WEIGHT", "CUBE")
    assert data["max_cube_m3"] == pytest.approx(TRAILER_MAX_CUBE_M3[data["trailer_type"]])
    assert data["max_weight_kg"] == TRAILER_MAX_WEIGHT_KG[data["trailer_type"]]
    assert data["status"] in ("PLANNED", "DISPATCHED", "DELIVERED", "CANCELLED")
    assert isinstance(data["order_count"], int) and data["order_count"] >= 0
    assert isinstance(data["linehaul_cost_cents"], int)


def assert_installation_crew(data: dict):
    assert_versioned_shape(data, "InstallationCrew")
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert data["certification_tier"] in ("T1", "T2", "T3")
    assert data["max_diameter_m"] == pytest.approx(
        CREW_MAX_DIAMETER_M[data["certification_tier"]]
    ), "max_diameter_m follows from the certification tier"
    assert is_iso8601_timestamp(data["certified_until"])
    assert data["status"] in ("CERTIFIED", "PROBATION", "REVOKED")


def assert_field_failure(data: dict):
    assert_versioned_shape(data, "FieldFailure")
    assert is_valid_uuid(data["dealer_order_id"])
    assert is_valid_uuid(data["bin_design_id"])
    assert data["failure_mode"] in (
        "SIDEWALL_BUCKLE",
        "ROOF_COLLAPSE",
        "CORROSION_PERFORATION",
        "ANCHOR_PULLOUT",
    )
    assert 0.0 <= data["observed_load_kpa"] <= 500.0
    assert 0.0 <= data["measured_coating_loss_pct"] <= 100.0
    assert 0.0 <= data["service_years"] <= 60.0
    assert data["status"] in ("INTAKE", "ANALYSIS_IN_PROGRESS", "DETERMINED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_dealer_ledger_invariants(dealer: dict):
    """`credit_available_cents` is the limit minus the committed sum, and the
    status follows the sign of the available figure (PRD 3.6)."""
    assert (
        dealer["credit_available_cents"]
        == dealer["credit_limit_cents"] - dealer["credit_committed_cents"]
    ), (
        "credit_available_cents is credit_limit_cents minus credit_committed_cents "
        f"(limit {dealer['credit_limit_cents']}, committed "
        f"{dealer['credit_committed_cents']}, available "
        f"{dealer['credit_available_cents']})"
    )
    expected_status = "CREDIT_HOLD" if dealer["credit_available_cents"] < 0 else "ACTIVE"
    assert dealer["status"] == expected_status, (
        f"Dealer status must be {expected_status} at available "
        f"{dealer['credit_available_cents']}, got {dealer['status']}"
    )


def assert_credit_conservation(dealer: dict, orders: list):
    """The stored committed figure equals the sum of `credit_hold_cents` over the
    dealership's orders in the five participating production states."""
    expected = sum(
        order["credit_hold_cents"]
        for order in orders
        if order["production_status"] in CREDIT_PARTICIPATING_STATES
    )
    assert dealer["credit_committed_cents"] == expected, (
        f"credit_committed_cents {dealer['credit_committed_cents']} must equal the "
        f"sum of credit_hold_cents over participating orders ({expected})"
    )
    assert (
        dealer["credit_limit_cents"]
        == dealer["credit_committed_cents"] + dealer["credit_available_cents"]
    )


def assert_coil_mass_conservation(lot: dict):
    """`received_kg` equals remaining + reserved + consumed + scrap (PRD 3.7)."""
    total = (
        lot["remaining_kg"] + lot["reserved_kg"] + lot["consumed_kg"] + lot["scrap_kg"]
    )
    assert total == pytest.approx(lot["received_kg"], abs=0.005), (
        f"Coil lot conservation identity broken: received {lot['received_kg']} vs "
        f"remaining {lot['remaining_kg']} + reserved {lot['reserved_kg']} + "
        f"consumed {lot['consumed_kg']} + scrap {lot['scrap_kg']} = {total}"
    )


def assert_coil_lot_status_follows_ledger(lot: dict):
    if lot["status"] == "QUARANTINED":
        return
    expected = "DEPLETED" if lot["remaining_kg"] == 0 else "AVAILABLE"
    assert lot["status"] == expected, (
        f"Lot with remaining_kg {lot['remaining_kg']} must read {expected}, "
        f"got {lot['status']}"
    )


def assert_freight_allocation_invariant(load: dict, attached_orders: list):
    """The allocated shares sum to the linehaul exactly (PRD 3.8)."""
    total = sum(order["allocated_freight_cents"] for order in attached_orders)
    assert total == load["linehaul_cost_cents"], (
        f"Sum of allocated_freight_cents {total} must equal linehaul_cost_cents "
        f"{load['linehaul_cost_cents']}"
    )
    assert load["order_count"] == len(attached_orders)


def assert_freight_sequence_dense(attached_orders: list):
    """Attached orders carry `freight_sequence` 1 through N with no hole."""
    sequences = sorted(order["freight_sequence"] for order in attached_orders)
    assert sequences == list(range(1, len(attached_orders) + 1)), (
        f"freight_sequence must be 1..N with no hole, got {sequences}"
    )


def assert_detached_order(order: dict):
    assert order["freight_load_id"] is None, "a detached order has no freight_load_id"
    assert order["allocated_freight_cents"] == 0
    assert order["freight_sequence"] is None


def assert_kit_lines_in_component_order(lines: list):
    """Kit lines come back in the fixed component order of PRD 3.4."""
    positions = [COMPONENT_ORDER.index(line["component_code"]) for line in lines]
    assert positions == sorted(positions), (
        "kit lines must be returned in the fixed component order, got "
        f"{[line['component_code'] for line in lines]}"
    )
    assert all(
        line["quantity"] >= 1 for line in lines
    ), "a kit line is emitted only for components whose quantity is 1 or more"


def assert_empty_load_totals(load: dict):
    assert load["order_count"] == 0
    assert load["assigned_cube_m3"] == pytest.approx(0)
    assert load["assigned_weight_kg"] == pytest.approx(0)
    assert load["cube_utilization_pct"] == pytest.approx(0)
    assert load["linehaul_cost_cents"] == 0


def assert_no_such_field(data: dict, field: str):
    assert field not in data, f"response must not carry a {field} field"


def assert_version_advanced_by(new: dict, old: dict, delta: int = 1, what="row"):
    assert new["version"] == old["version"] + delta, (
        f"{what} version must advance by exactly {delta}: "
        f"{old['version']} -> {new['version']}"
    )
