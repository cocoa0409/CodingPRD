"""Entity assertions and domain invariant checkers.

Every function here takes an **already unwrapped** resource dict (what
``validate_success`` / ``validate_paginated`` returned) — the response envelope
is never unwrapped twice.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import parse_instant

# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------
MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
EVENT_COMMON_FIELDS = ("id", "created_at")


def round_half_up(value, places: int = 2) -> float:
    """Round half-up to ``places`` decimals, the rule PRD §2.7 pins."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """id + created_at + updated_at + version, for the twelve mutable aggregates."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"


def assert_event_record_fields(data: dict, label: str = "event") -> None:
    """id + created_at only; updated_at and version must be absent entirely."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, \
        f"{label} is an immutable event record: updated_at must be absent, not null"
    assert "version" not in data, \
        f"{label} is an immutable event record: version must be absent, not null"


def assert_three_fractional_digits(value: str, label: str = "timestamp") -> None:
    """PRD §2.4 renders every server-stamped instant with exactly three
    fractional digits."""
    assert isinstance(value, str) and value, f"{label} must be a string instant"
    assert "." in value, f"{label} must carry fractional digits, got {value!r}"
    fraction = value.split(".", 1)[1]
    digits = fraction.rstrip("Z").split("+")[0]
    assert len(digits) == 3, \
        f"{label} must carry exactly three fractional digits, got {value!r}"


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 instants as instants, not as strings, so a differing
    fractional-second width never fails a comparison of equal moments."""
    assert parse_instant(actual) == parse_instant(expected), \
        f"{label}: expected instant {expected}, got {actual}"


def assert_paginated_meta(meta: dict, expected_limit: Optional[int] = None,
                          expected_offset: Optional[int] = None,
                          expected_total: Optional[int] = None,
                          expected_has_more: Optional[bool] = None) -> None:
    """Every list endpoint in this API is paginated and populates all four
    pagination fields inside meta (PRD §2.3)."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta.{key} must be present on a list response"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, \
            f"meta.limit should echo {expected_limit}, got {meta['limit']}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, \
            f"meta.offset should echo {expected_offset}, got {meta['offset']}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, \
            f"meta.total_count should be {expected_total}, got {meta['total_count']}"
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, \
            f"meta.has_more should be {expected_has_more}, got {meta['has_more']}"


def assert_sorted_by_created_at(rows: Iterable[dict]) -> None:
    """List results are sorted by created_at ascending unless a subsection of
    the PRD states a different ordering (PRD §2.3)."""
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), "list rows must be ordered by created_at ascending"


def assert_absent_or_none(data: dict, field: str, label: str = "resource") -> None:
    assert data.get(field) is None, \
        f"{label}.{field} should still be null, got {data.get(field)!r}"


# ---------------------------------------------------------------------------
# Raw material qualification
# ---------------------------------------------------------------------------
def assert_material_specification(data: dict) -> None:
    assert_common_fields(data, "material_specification")
    code = data["material_code"]
    assert isinstance(code, str) and 3 <= len(code) <= 32, \
        f"material_code must be 3-32 characters, got {code!r}"
    assert data["material_type"] in ("ANTIBODY", "ENZYME",
                                    "CALIBRATOR_MATERIAL", "BUFFER")
    assert isinstance(data["is_critical"], bool)
    assert data["potency_min_pct"] > 0
    assert data["potency_min_pct"] < data["potency_max_pct"]
    assert data["endotoxin_max_eu_per_ml"] > 0
    assert isinstance(data["required_test_codes"], list) and data["required_test_codes"]
    for code in data["required_test_codes"]:
        assert code in ("POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"), \
            f"unexpected required test code {code!r}"
    assert data["acceptance_mode"] in ("ALL_PASS", "WEIGHTED_SCORE")
    assert isinstance(data["max_retests"], int) and data["max_retests"] >= 0
    assert isinstance(data["retest_window_days"], int)


def assert_material_lot(data: dict) -> None:
    assert_common_fields(data, "material_lot")
    assert is_valid_uuid(data["material_specification_id"])
    assert isinstance(data["vendor_lot_code"], str) and data["vendor_lot_code"]
    assert data["received_quantity_units"] > 0
    assert data["qualification_status"] in (
        "RECEIVED", "UNDER_TEST", "OOS_INVESTIGATION",
        "QUALIFIED", "REJECTED", "QUARANTINED")
    assert isinstance(data["retest_count"], int) and data["retest_count"] >= 0
    assert is_iso8601_timestamp(data["expiry_date"])
    assert_material_quantity_conservation(data)


def assert_material_quantity_conservation(lot: dict) -> None:
    """received_quantity_units always equals available_quantity_units plus
    consumed_quantity_units (PRD §2.8), with no drift at rounding scale."""
    received = lot["received_quantity_units"]
    available = lot["available_quantity_units"]
    consumed = lot["consumed_quantity_units"]
    assert consumed >= 0, f"consumed_quantity_units must not go negative: {consumed}"
    if lot.get("qualification_status") in ("REJECTED", "QUARANTINED"):
        assert available == 0, (
            "a rejected or quarantined raw material lot has "
            f"available_quantity_units forced to 0, got {available}")
        return
    assert round_half_up(available + consumed, 2) == round_half_up(received, 2), (
        f"raw material ledger broken: received {received} != available {available} "
        f"+ consumed {consumed}")


# ---------------------------------------------------------------------------
# Design control
# ---------------------------------------------------------------------------
def assert_product_specification(data: dict) -> None:
    assert_common_fields(data, "product_specification")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["reference_material_code"], str)
    assert isinstance(data["required_material_codes"], list) \
        and data["required_material_codes"]
    assert isinstance(data["release_test_codes"], list) and data["release_test_codes"]
    for code in data["release_test_codes"]:
        assert code in ("ACTIVITY", "CALIBRATION_SLOPE", "PRECISION", "LINEARITY")
    assert data["shelf_life_months_claim"] > 0
    assert data["storage_condition"] in ("TWO_TO_EIGHT_C", "MINUS_TWENTY_C")
    assert data["clearance_status"] in ("DESIGN", "CLEARED", "WITHDRAWN")
    assert isinstance(data["design_trace_complete"], bool)
    assert isinstance(data["min_shelf_life_days_at_ship"], int)


def assert_design_control_record(data: dict) -> None:
    assert_common_fields(data, "design_control_record")
    assert is_valid_uuid(data["product_specification_id"])
    assert data["record_type"] in ("DESIGN_INPUT", "DESIGN_OUTPUT",
                                  "VERIFICATION", "VALIDATION")
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]
    depth = data["trace_depth"]
    assert isinstance(depth, int) and depth >= 1
    if data["record_type"] == "DESIGN_INPUT":
        assert data.get("traces_to_record_id") is None, \
            "traces_to_record_id must be null exactly when record_type is DESIGN_INPUT"
        assert depth == 1, f"a DESIGN_INPUT sits at trace_depth 1, got {depth}"
    else:
        assert data.get("traces_to_record_id") is not None, \
            "a non-input record must carry traces_to_record_id"
        if data["record_type"] == "DESIGN_OUTPUT":
            assert depth == 2, f"a DESIGN_OUTPUT sits at trace_depth 2, got {depth}"
        else:
            assert depth == 3, \
                f"a {data['record_type']} sits at trace_depth 3, got {depth}"


# ---------------------------------------------------------------------------
# Finished lots
# ---------------------------------------------------------------------------
def assert_reagent_lot(data: dict) -> None:
    assert_common_fields(data, "reagent_lot")
    assert is_valid_uuid(data["product_specification_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["planned_units"] > 0
    assert data["disposition_status"] in (
        "PLANNED", "IN_PROCESS", "FILLED", "UNDER_RELEASE_TEST",
        "RELEASED", "REJECTED", "RECALLED")
    assert data["distribution_status"] in ("WITHHELD", "AVAILABLE", "BLOCKED")
    for field in ("filled_units", "available_units", "allocated_units",
                  "shipped_units", "quarantined_units"):
        assert isinstance(data[field], int), \
            f"reagent_lot.{field} must be an integer, got {data[field]!r}"
    assert isinstance(data["em_excursion_count"], int)
    assert isinstance(data["bridging_required"], bool)
    assert_reagent_lot_unit_conservation(data)


def assert_reagent_lot_unit_conservation(lot: dict) -> None:
    """filled_units always equals available_units plus allocated_units plus
    shipped_units plus quarantined_units (PRD §2.8)."""
    if lot.get("disposition_status") in ("REJECTED",):
        assert lot["available_units"] == 0, (
            "a rejected finished lot has available_units forced to 0, "
            f"got {lot['available_units']}")
        return
    total = (lot["available_units"] + lot["allocated_units"]
             + lot["shipped_units"] + lot["quarantined_units"])
    assert lot["filled_units"] == total, (
        f"finished-goods ledger broken: filled_units {lot['filled_units']} != "
        f"available {lot['available_units']} + allocated {lot['allocated_units']} "
        f"+ shipped {lot['shipped_units']} + quarantined {lot['quarantined_units']}")


def assert_lot_component(data: dict) -> None:
    assert_common_fields(data, "lot_component")
    assert is_valid_uuid(data["reagent_lot_id"])
    assert is_valid_uuid(data["material_lot_id"])
    assert data["component_role"] in ("ANTIBODY", "ENZYME",
                                     "CALIBRATOR_MATERIAL", "BUFFER")
    assert data["quantity_used"] > 0
    assert data["status"] in ("CONSUMED", "RETURNED")
    assert isinstance(data["material_code_snapshot"], str) \
        and data["material_code_snapshot"]
    assert isinstance(data["vendor_lot_code_snapshot"], str) \
        and data["vendor_lot_code_snapshot"]


# ---------------------------------------------------------------------------
# Filling and monitoring
# ---------------------------------------------------------------------------
def assert_fill_run(data: dict) -> None:
    assert_common_fields(data, "fill_run")
    assert is_valid_uuid(data["reagent_lot_id"])
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["formulation_batch_code"], str)
    assert parse_instant(data["scheduled_end"]) > parse_instant(data["scheduled_start"])
    assert data["planned_fill_units"] > 0
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")
    assert data["environmental_state"] in ("CONFORMING", "EXCURSION", "DISQUALIFIED")
    assert isinstance(data["minor_excursion_count"], int)
    assert isinstance(data["major_excursion_count"], int)


def assert_monitoring_sample(data: dict) -> None:
    assert_event_record_fields(data, "monitoring_sample")
    assert is_valid_uuid(data["fill_run_id"])
    assert data["sample_type"] in ("VIABLE_AIR", "SURFACE",
                                  "NONVIABLE_PARTICLE", "BIOBURDEN_BULK")
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert data["result_value"] >= 0
    assert is_iso8601_timestamp(data["sampled_at"])
    assert data["limit_value"] > 0
    assert isinstance(data["excursion"], bool)
    assert data["excursion_grade"] in ("NONE", "MINOR", "MAJOR")
    expected_excursion = data["result_value"] > data["limit_value"]
    assert data["excursion"] is expected_excursion, (
        "excursion is true exactly when result_value is strictly greater than "
        f"limit_value: {data['result_value']} vs {data['limit_value']}")


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
def assert_test_result(data: dict) -> None:
    assert_event_record_fields(data, "test_result")
    assert data["subject_type"] in ("MATERIAL_LOT", "REAGENT_LOT",
                                   "STABILITY_TIMEPOINT")
    assert isinstance(data["test_code"], str) and data["test_code"]
    assert data["outcome"] in ("PASS", "FAIL")
    assert isinstance(data["performed_by_user_id"], str) \
        and data["performed_by_user_id"]
    assert is_iso8601_timestamp(data["performed_at"])
    if data["subject_type"] == "MATERIAL_LOT":
        assert is_valid_uuid(data["material_lot_id"])
        assert data.get("bias_pct") is None, \
            "bias_pct is not applicable to a MATERIAL_LOT measurement"
        assert data.get("recovery_pct") is None, \
            "recovery_pct is not applicable to a MATERIAL_LOT measurement"
    elif data["subject_type"] == "REAGENT_LOT":
        assert is_valid_uuid(data["reagent_lot_id"])
        assert data["reference_measured_value"] > 0
        assert data["bias_pct"] is not None, \
            "a REAGENT_LOT measurement carries a computed bias_pct"
        assert data.get("recovery_pct") is None, \
            "recovery_pct is not applicable to a REAGENT_LOT measurement"
    else:
        assert is_valid_uuid(data["stability_study_id"])
        assert isinstance(data["month_index"], int)
        assert data["recovery_pct"] is not None, \
            "a STABILITY_TIMEPOINT measurement carries a computed recovery_pct"
        assert data.get("bias_pct") is None, \
            "bias_pct is not applicable to a STABILITY_TIMEPOINT measurement"


# ---------------------------------------------------------------------------
# Stability and bridging
# ---------------------------------------------------------------------------
def assert_stability_study(data: dict) -> None:
    assert_common_fields(data, "stability_study")
    assert is_valid_uuid(data["product_specification_id"])
    assert is_valid_uuid(data["reagent_lot_id"])
    assert data["study_type"] in ("REAL_TIME", "ACCELERATED")
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert parse_instant(data["protocol_end"]) > parse_instant(data["protocol_start"])
    months = data["planned_timepoints_months"]
    assert isinstance(months, list) and months, \
        "planned_timepoints_months must be non-empty"
    assert months[0] == 0, "planned_timepoints_months must begin at 0"
    assert all(b > a for a, b in zip(months, months[1:])), \
        "planned_timepoints_months must be strictly increasing"
    assert data["baseline_value"] > 0
    assert data["status"] in ("PROTOCOL_DRAFT", "APPROVED", "IN_PROGRESS",
                             "COMPLETE", "ABORTED")
    assert isinstance(data["timepoint_count"], int)
    if data.get("shelf_life_method") is not None:
        assert data["shelf_life_method"] in ("REAL_TIME_LAST_CONFORMING",
                                            "ACCELERATED_Q10")


def assert_bridging_study(data: dict) -> None:
    assert_common_fields(data, "bridging_study")
    assert is_valid_uuid(data["predicate_lot_id"])
    assert is_valid_uuid(data["candidate_lot_id"])
    assert is_valid_uuid(data["changed_material_lot_id"])
    assert isinstance(data["paired_test_codes"], list) and data["paired_test_codes"]
    assert data["status"] in ("DRAFT", "APPROVED", "FAILED")
    assert data["equivalence_verdict"] in ("PENDING", "EQUIVALENT", "NOT_EQUIVALENT")


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------
def assert_complaint(data: dict) -> None:
    assert_common_fields(data, "complaint")
    assert is_valid_uuid(data["reagent_lot_id"])
    assert isinstance(data["complaint_code"], str) and data["complaint_code"]
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert isinstance(data["device_related_death_or_injury"], bool)
    assert is_iso8601_timestamp(data["received_at"])
    assert data["status"] in ("RECEIVED", "TRIAGED", "MALFUNCTION_REPORTED",
                             "FIELD_ACTION_DECIDED", "CLOSED")
    if data.get("severity") is not None:
        assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    if data.get("field_action") is not None:
        assert data["field_action"] in ("NONE", "ADVISORY", "CORRECTION", "REMOVAL")


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
def assert_distribution_order(data: dict) -> None:
    assert_common_fields(data, "distribution_order")
    assert is_valid_uuid(data["product_specification_id"])
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert data["requested_units"] > 0
    assert data["required_min_shelf_life_days"] >= 0
    assert is_iso8601_timestamp(data["ship_by"])
    assert data["allocation_policy"] in ("FEFO_STRICT", "FEFO_WITH_SHORTFALL")
    assert data["status"] in ("DRAFT", "ALLOCATED", "PARTIALLY_ALLOCATED",
                             "SHIPPED", "CLOSED", "CANCELLED")
    assert isinstance(data["planner_user_id"], str) and data["planner_user_id"]
    assert_order_shortfall_consistent(data)


def assert_order_shortfall_consistent(order: dict) -> None:
    """PRD §3.9: "Orders are created in `status` `DRAFT` with `allocated_units`
    and `shortfall_units` both 0"; and, once the allocation waterfall has run,
    "an order's `allocated_units` is the sum of `allocated_units` over its
    reservations whose `status` is `RESERVED`, `SHIPPED` or `DELIVERED`, and its
    `shortfall_units` is `requested_units` minus that sum floored at 0."

    A `DRAFT` order has by definition never been allocated (allocation always
    leaves `DRAFT` for `ALLOCATED` or `PARTIALLY_ALLOCATED`), so the explicit
    creation rule governs it: both counters read 0 whatever `requested_units`
    asks for. The derived rule applies from the first allocation onwards.
    """
    if order["status"] == "DRAFT":
        assert order["allocated_units"] == 0 and order["shortfall_units"] == 0, (
            "a DRAFT order is created with allocated_units and shortfall_units "
            f"both 0, got {order['allocated_units']} and "
            f"{order['shortfall_units']}")
        return
    expected = max(order["requested_units"] - order["allocated_units"], 0)
    assert order["shortfall_units"] == expected, (
        f"shortfall_units should be {expected} for requested "
        f"{order['requested_units']} and allocated {order['allocated_units']}, "
        f"got {order['shortfall_units']}")


def assert_allocation(data: dict) -> None:
    assert_common_fields(data, "allocation")
    assert is_valid_uuid(data["distribution_order_id"])
    assert is_valid_uuid(data["reagent_lot_id"])
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] > 0
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert data["status"] in ("RESERVED", "SHIPPED", "DELIVERED",
                             "CANCELLED", "QUARANTINED")
    assert data["cumulative_excursion_minutes"] >= 0
    assert data["cold_chain_status"] in ("INTACT", "EXCURSION_ACCEPTABLE",
                                        "EXCURSION_REJECTED")
