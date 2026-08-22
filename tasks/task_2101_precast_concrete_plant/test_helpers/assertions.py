"""Entity assertions and plant invariant checkers."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    LEGAL_HEIGHT_FT,
    LEGAL_LENGTH_FT,
    LEGAL_WIDTH_FT,
    TRACTOR_TARE_LB,
)

# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
_TOL = {0: 0, 2: 5e-7, 3: 5e-8}


def assert_decimal(actual, expected, places: int, label: str = "value"):
    """Compare a value the PRD pins to `places` decimal places."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert actual == pytest.approx(expected, abs=10 ** (-places) / 100.0), (
        f"{label}: expected {expected} to {places} decimal places, got {actual}"
    )


def assert_whole_cents(actual, expected, label: str = "cents"):
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"
    assert isinstance(actual, int) or float(actual).is_integer(), (
        f"{label} must be a whole number of cents, got {actual}"
    )


def assert_exact_sum(actual, expected, label: str = "sum"):
    """For quantities the PRD says are exact sums with no rounding at all."""
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected the exact sum {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Common record properties
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "record"):
    """id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')}"
    )


def assert_write_once_fields(data: dict, label: str = "record"):
    """A write-once row carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_project(data: dict):
    assert_common_fields(data, "project")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jobsite_city"], str)
    assert isinstance(data["erection_start_date"], str)
    for counter in (
        "total_piece_count",
        "held_piece_count",
        "cleared_piece_count",
        "scrapped_piece_count",
        "erected_piece_count",
        "committed_cost_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"project.{counter} must be a non-negative integer, got {data.get(counter)}"
        )


def assert_mix_design(data: dict):
    assert_common_fields(data, "mix_design")
    assert data["status"] in ("DRAFT", "QUALIFIED", "SUSPENDED", "RETIRED")
    assert data["strength_class"] in ("C40", "C50", "C60", "C70")
    assert data["design_28day_psi"] > 0
    assert 0 < data["required_release_psi"] < data["design_28day_psi"]
    assert 0 < data["w_c_ratio"] <= 1
    assert data["cement_lb_per_cy"] > 0
    assert data["unit_cost_cents_per_cy"] > 0


def assert_steam_zone(data: dict):
    assert_common_fields(data, "steam_zone")
    assert data["boiler_capacity_bhp"] > 0
    assert data["therm_rate_cents_per_therm"] > 0


def assert_casting_bed(data: dict):
    assert_common_fields(data, "casting_bed")
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "DOWN")
    assert data["bed_type"] in (
        "LONG_LINE_PRESTRESS",
        "SELF_STRESSING_FORM",
        "FLAT_BED_RC",
    )
    assert data["length_ft"] > 0
    assert data["max_strand_force_kips"] > 0
    assert data["turnaround_buffer_hours"] >= 0
    assert data["committed_strand_force_kips"] >= 0
    assert data["cumulative_cycle_count"] >= 0


def assert_bed_run(data: dict):
    assert_common_fields(data, "bed_run")
    assert data["status"] in (
        "SCHEDULED",
        "BLOCKED",
        "TENSIONED",
        "CURING",
        "RELEASE_READY",
        "RELEASED",
        "STRIPPED",
    )
    assert isinstance(data["piece_count"], int) and data["piece_count"] >= 0
    assert data["scheduled_end"] > data["scheduled_start"]


def assert_untensioned_run(data: dict):
    """Every field the tensioning writes is null on a run that has not been pulled."""
    for field in (
        "strand_count",
        "strand_diameter_in",
        "measured_elongation_in",
        "theoretical_elongation_in",
        "elongation_deviation_pct",
        "computed_jacking_force_kips",
    ):
        assert data[field] is None, f"bed_run.{field} must be null, got {data[field]}"


def assert_unallocated_run(data: dict):
    """All eight cost fields are null until the run is stripped."""
    for field in (
        "concrete_cost_cents",
        "strand_cost_cents",
        "energy_cost_cents",
        "form_setup_cents",
        "direct_subtotal_cents",
        "overhead_rate_pct",
        "overhead_cents",
        "total_cost_cents",
    ):
        assert data[field] is None, f"bed_run.{field} must be null, got {data[field]}"


def assert_curing_cycle(data: dict):
    assert_common_fields(data, "curing_cycle")
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED")
    assert data["planned_end"] > data["planned_start"]
    assert data["ramp_rate_f_per_hr"] > 0
    assert data["soak_temp_f"] > 60
    assert data["soak_hours"] > 0
    assert data["steam_demand_bhp"] > 0
    assert isinstance(data["variance_flagged"], bool)


def assert_cylinder_set(data: dict):
    assert_common_fields(data, "cylinder_set")
    assert data["purpose"] in ("RELEASE", "ACCEPTANCE_28DAY", "INFORMATION")
    assert 2 <= data["specimen_count"] <= 6
    assert isinstance(data["cured_with_member"], bool)
    assert data["status"] in ("CAST", "TESTING", "RELEASE_MET", "RELEASE_NOT_MET")
    assert is_iso8601_timestamp(data["cast_at"])
    assert isinstance(data["recorded_break_count"], int)
    assert isinstance(data["valid_break_count"], int)
    assert isinstance(data["recorded_by_user_ids"], list)


def assert_cylinder_break(data: dict):
    assert_common_fields(data, "cylinder_break")
    assert data["load_lbf"] > 0
    assert data["diameter_in"] in (4.00, 6.00)
    assert isinstance(data["computed_psi"], int)
    assert data["inclusion_status"] in ("VALID", "DISCARDED_OUTLIER")
    assert is_iso8601_timestamp(data["break_at"])
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_piece(data: dict):
    assert_common_fields(data, "piece")
    assert data["production_status"] in (
        "PLANNED",
        "SCHEDULED",
        "CAST",
        "STRIPPED",
        "YARDED",
        "LOADED",
        "SHIPPED",
        "ERECTED",
        "SCRAPPED",
    )
    assert data["qc_status"] in (
        "PENDING",
        "HOLD",
        "CLEARED",
        "NONCONFORMING",
        "REPAIRED",
        "REJECTED",
    )
    assert data["qc_hold_reason"] in (
        None,
        "AWAITING_RELEASE_STRENGTH",
        "MIX_SUSPENDED",
        "OPEN_NCR",
    )
    assert isinstance(data["requires_haul_permit"], bool)
    assert data["erection_sequence_no"] > 0
    for dim in ("length_ft", "width_ft", "height_ft", "weight_lb", "concrete_volume_cy"):
        assert data[dim] > 0, f"piece.{dim} must be greater than zero"
    assert isinstance(data["repair_count"], int) and data["repair_count"] >= 0
    assert_piece_qc_hold_reason_invariant(data)


def assert_piece_qc_hold_reason_invariant(data: dict):
    """qc_hold_reason is populated only while the piece is HOLD or NONCONFORMING."""
    if data["qc_status"] not in ("HOLD", "NONCONFORMING"):
        assert data["qc_hold_reason"] is None, (
            f"piece.qc_hold_reason must be null while qc_status is "
            f"{data['qc_status']}, got {data['qc_hold_reason']}"
        )


def assert_requires_haul_permit(data: dict):
    """requires_haul_permit is derived from the piece's own dimensions alone."""
    expected = (
        data["width_ft"] > LEGAL_WIDTH_FT
        or data["height_ft"] > LEGAL_HEIGHT_FT
        or data["length_ft"] > LEGAL_LENGTH_FT
    )
    assert data["requires_haul_permit"] is expected, (
        f"piece.requires_haul_permit should be {expected} for "
        f"{data['length_ft']} x {data['width_ft']} x {data['height_ft']} ft"
    )


def assert_yard_slot(data: dict):
    assert_common_fields(data, "yard_slot")
    assert data["status"] in ("EMPTY", "PARTIAL", "FULL", "BLOCKED")
    assert data["capacity_weight_lb"] > 0
    assert data["max_stack_count"] >= 1
    assert data["occupied_weight_lb"] >= 0
    assert data["stacked_count"] >= 0


def assert_yard_placement(data: dict):
    assert_common_fields(data, "yard_placement")
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert data["stack_level"] >= 1
    assert is_iso8601_timestamp(data["placed_at"])
    if data["status"] == "ACTIVE":
        assert data["released_at"] is None
        assert data["release_reason"] is None
    else:
        assert data["release_reason"] in ("LOAD", "SCRAP", "RESTACK")


def assert_haul_permit(data: dict):
    assert_common_fields(data, "haul_permit")
    assert data["status"] in ("APPLIED", "ISSUED", "ACTIVE", "CONSUMED", "EXPIRED")
    assert data["valid_to"] > data["valid_from"]
    assert data["escort_count"] >= 0
    for field in (
        "max_width_ft",
        "max_height_ft",
        "max_length_ft",
        "max_gross_weight_lb",
    ):
        assert data[field] > 0


def assert_shipment(data: dict):
    assert_common_fields(data, "shipment")
    assert data["status"] in ("BUILDING", "DISPATCHED", "DELIVERED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["is_oversize"], bool)
    assert data["gross_weight_lb"] >= TRACTOR_TARE_LB
    assert data["permit_fee_cents"] >= 0


def assert_shipment_line(data: dict):
    assert_write_once_fields(data, "shipment_line")
    assert data["load_position"] >= 1
    assert isinstance(data["line_surcharge_cents"], int)
    assert is_iso8601_timestamp(data["loaded_at"])


def assert_repair_disposition(data: dict):
    assert_common_fields(data, "repair_disposition")
    assert data["status"] in (
        "OPEN",
        "DISPOSITIONED",
        "REPAIR_IN_PROGRESS",
        "REINSPECTION",
        "CLOSED_ACCEPTED",
        "REJECTED_RECAST",
        "SUPERSEDED",
    )
    assert data["defect_type"] in ("SPALL", "HONEYCOMB", "CRACK", "DIMENSIONAL", "FINISH")
    assert data["severity"] in ("MINOR", "MAJOR", "STRUCTURAL")
    assert data["disposition"] in (
        None,
        "PATCH_MINOR",
        "STRUCTURAL_REPAIR",
        "USE_AS_IS",
        "REJECT_RECAST",
    )
    assert isinstance(data["reinspection_fail_count"], int)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


# --------------------------------------------------------------------------
# Cross-entity invariants
# --------------------------------------------------------------------------
def assert_slot_occupancy(slot: dict, expected_weight, expected_count, expected_status):
    """The slot's occupancy is recomputed from its ACTIVE placements alone."""
    assert_exact_sum(slot["occupied_weight_lb"], expected_weight, "yard_slot.occupied_weight_lb")
    assert slot["stacked_count"] == expected_count, (
        f"yard_slot.stacked_count: expected {expected_count}, got {slot['stacked_count']}"
    )
    assert slot["status"] == expected_status, (
        f"yard_slot.status: expected {expected_status}, got {slot['status']}"
    )


def assert_piece_dimensions_status(piece: dict, production_status, qc_status, qc_hold_reason=None):
    """The two piece dimensions are independent; assert both at once."""
    assert piece["production_status"] == production_status, (
        f"piece.production_status: expected {production_status}, "
        f"got {piece['production_status']}"
    )
    assert piece["qc_status"] == qc_status, (
        f"piece.qc_status: expected {qc_status}, got {piece['qc_status']}"
    )
    assert piece["qc_hold_reason"] == qc_hold_reason, (
        f"piece.qc_hold_reason: expected {qc_hold_reason}, got {piece['qc_hold_reason']}"
    )


def assert_project_counters(project: dict, **expected):
    for counter, value in expected.items():
        assert project[counter] == value, (
            f"project.{counter}: expected {value}, got {project[counter]}"
        )


def assert_cost_allocation_is_exact(pieces, total_cost_cents: int):
    """The run total is split across the sharing pieces exactly, with no residue."""
    allocated = sum(p["allocated_cost_cents"] for p in pieces)
    assert allocated == total_cost_cents, (
        f"allocated shares sum to {allocated}, expected the run total {total_cost_cents}"
    )
