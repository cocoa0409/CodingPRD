"""Payload factories -- one per entity, input fields only.

Every factory takes `**overrides` so a test can control exactly the field under
assertion and inherit sensible values for the rest.
"""

from .constants import TEST_DEFAULTS


def create_terminal_payload(**overrides) -> dict:
    """Register a tank terminal (PRD 3.1)."""
    payload = {
        "terminal_code": "HOU",
        "name": "Houston Origin Terminal",
        "role_kind": "ORIGIN",
        "shell_capacity_bbl": TEST_DEFAULTS["ORIGIN_SHELL_BBL"],
        "min_operating_inventory_bbl": TEST_DEFAULTS["ORIGIN_MIN_OPERATING_BBL"],
        "injection_bays": TEST_DEFAULTS["ORIGIN_INJECTION_BAYS"],
    }
    payload.update(overrides)
    return payload


def origin_terminal_payload(**overrides) -> dict:
    """The canonical ORIGIN terminal used by the composite fixtures."""
    return create_terminal_payload(**overrides)


def destination_terminal_payload(**overrides) -> dict:
    """The canonical DESTINATION terminal used by the composite fixtures."""
    payload = {
        "terminal_code": "NAS",
        "name": "Nashville Destination Terminal",
        "role_kind": "DESTINATION",
        "shell_capacity_bbl": TEST_DEFAULTS["DEST_SHELL_BBL"],
        "min_operating_inventory_bbl": TEST_DEFAULTS["DEST_MIN_OPERATING_BBL"],
    }
    payload.update(overrides)
    return payload


def create_inventory_adjustment_payload(
    expected_terminal_version, adjustment_kind="INVENTORY", **overrides
) -> dict:
    """Book an inventory or linefill adjustment (PRD 3.1, OCC guard of PRD 2.6)."""
    payload = {
        "expected_terminal_version": expected_terminal_version,
        "adjustment_kind": adjustment_kind,
        "adjustment_bbl": TEST_DEFAULTS["ORIGIN_STOCK_BBL"],
        "reason": "refinery receipt",
    }
    payload.update(overrides)
    return payload


def linefill_adjustment_payload(expected_terminal_version, segment_id, **overrides) -> dict:
    """Fund a segment's linefill; requires an accompanying `segment_id` (PRD 3.1)."""
    payload = {
        "expected_terminal_version": expected_terminal_version,
        "adjustment_kind": "LINEFILL",
        "adjustment_bbl": TEST_DEFAULTS["LINEFILL_FUNDING_BBL"],
        "reason": "initial linefill",
        "segment_id": segment_id,
    }
    payload.update(overrides)
    return payload


def create_product_grade_payload(**overrides) -> dict:
    """Define a refined product grade (PRD 3.1)."""
    payload = {
        "grade_code": "ULSD",
        "name": "Ultra Low Sulfur Diesel",
        "sequence_rank": 3,
        "max_sulfur_ppm": 15,
        "max_rvp_psi": 12,
    }
    payload.update(overrides)
    return payload


def ulsd_grade_payload(**overrides) -> dict:
    return create_product_grade_payload(**overrides)


def cbob_grade_payload(**overrides) -> dict:
    payload = {
        "grade_code": "CBOB",
        "name": "Conventional Blendstock Gasoline",
        "sequence_rank": 4,
        "max_sulfur_ppm": 80,
        "max_rvp_psi": 15,
    }
    payload.update(overrides)
    return payload


def jet_grade_payload(**overrides) -> dict:
    payload = {
        "grade_code": "JET",
        "name": "Jet A Kerosene",
        "sequence_rank": 1,
        "max_sulfur_ppm": 12,
        "max_rvp_psi": 10,
    }
    payload.update(overrides)
    return payload


def transmix_grade_payload(**overrides) -> dict:
    payload = {
        "grade_code": "TRANSMIX",
        "name": "Interface Transmix Slop",
        "sequence_rank": 9,
        "max_sulfur_ppm": 5000,
        "max_rvp_psi": 20,
        "is_transmix_grade": True,
    }
    payload.update(overrides)
    return payload


def create_segment_payload(
    origin_terminal_id, destination_terminal_id, linefill_grade_id, **overrides
) -> dict:
    """Define a pipeline segment with its commercial parameters (PRD 3.1)."""
    payload = {
        "segment_code": "HOU-NAS",
        "name": "Houston to Nashville Mainline",
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "linefill_grade_id": linefill_grade_id,
        "capacity_bbl_per_cycle": TEST_DEFAULTS["SEGMENT_CAPACITY_BBL"],
        "transmix_reserve_bbl": TEST_DEFAULTS["TRANSMIX_RESERVE_BBL"],
        "transmix_cut_bbl": TEST_DEFAULTS["TRANSMIX_CUT_BBL"],
        "min_tender_bbl": TEST_DEFAULTS["MIN_TENDER_BBL"],
        "linefill_requirement_bbl": TEST_DEFAULTS["LINEFILL_REQUIREMENT_BBL"],
        "proration_policy": "HISTORY_WEIGHTED",
    }
    payload.update(overrides)
    return payload


def create_shipper_payload(**overrides) -> dict:
    """Enrol a shipper with a credit limit (PRD 3.1)."""
    payload = {
        "shipper_code": "ALPHA",
        "name": "Alpha Petroleum Marketing",
        "credit_limit_usd": TEST_DEFAULTS["CREDIT_LIMIT_USD"],
    }
    payload.update(overrides)
    return payload


def suspend_shipper_payload(**overrides) -> dict:
    payload = {"suspended_reason": "credit review pending"}
    payload.update(overrides)
    return payload


def create_shipping_history_payload(shipper_id, segment_id, **overrides) -> dict:
    """Record an immutable historical movement row (PRD 3.1)."""
    payload = {
        "shipper_id": shipper_id,
        "segment_id": segment_id,
        "cycle_code": "2026-06",
        "actual_shipped_bbl": 30000,
        "cycle_end_at": "2026-06-30T00:00:00Z",
        "record_status": "FINAL",
    }
    payload.update(overrides)
    return payload


def create_tariff_payload(segment_id, grade_id, **overrides) -> dict:
    """Draft a tariff for one segment and grade pair (PRD 3.2)."""
    payload = {
        "segment_id": segment_id,
        "grade_id": grade_id,
        "base_rate_usd_per_bbl": TEST_DEFAULTS["BASE_RATE"],
        "tier1_min_bbl": TEST_DEFAULTS["TIER1_MIN_BBL"],
        "tier1_rate_usd_per_bbl": TEST_DEFAULTS["TIER1_RATE"],
        "tier2_min_bbl": TEST_DEFAULTS["TIER2_MIN_BBL"],
        "tier2_rate_usd_per_bbl": TEST_DEFAULTS["TIER2_RATE"],
        "tender_minimum_bbl": TEST_DEFAULTS["TENDER_MINIMUM_BBL"],
        "imbalance_penalty_rate_usd_per_bbl": TEST_DEFAULTS["IMBALANCE_PENALTY_RATE"],
        "effective_from": TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(segment_id, **overrides) -> dict:
    """Open a nomination cycle on a segment (PRD 3.3)."""
    payload = {
        "cycle_code": TEST_DEFAULTS["CYCLE_CODE"],
        "segment_id": segment_id,
        "window_open_at": TEST_DEFAULTS["WINDOW_OPEN_AT"],
        "window_close_at": TEST_DEFAULTS["WINDOW_CLOSE_AT"],
        "ship_start_at": TEST_DEFAULTS["SHIP_START_AT"],
        "ship_end_at": TEST_DEFAULTS["SHIP_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_nomination_payload(
    cycle_id,
    shipper_id,
    grade_id,
    origin_terminal_id,
    destination_terminal_id,
    expected_cycle_version,
    nominated_bbl=30000,
    **overrides,
) -> dict:
    """Submit a nomination into an OPEN cycle (PRD 3.3, OCC guard of PRD 2.6)."""
    payload = {
        "cycle_id": cycle_id,
        "shipper_id": shipper_id,
        "grade_id": grade_id,
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "nominated_bbl": nominated_bbl,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def resubmit_nomination_payload(nominated_bbl, **overrides) -> dict:
    payload = {"nominated_bbl": nominated_bbl}
    payload.update(overrides)
    return payload


def inject_payload(injected_bbl, measured_sulfur_ppm=9, measured_rvp_psi=8, **overrides) -> dict:
    """Inject a batch with its measured quality and volume (PRD 3.7)."""
    payload = {
        "measured_sulfur_ppm": measured_sulfur_ppm,
        "measured_rvp_psi": measured_rvp_psi,
        "injected_bbl": injected_bbl,
    }
    payload.update(overrides)
    return payload


def deliver_payload(delivered_bbl, **overrides) -> dict:
    payload = {"delivered_bbl": delivered_bbl}
    payload.update(overrides)
    return payload


def cancel_payload(cancel_reason="operator cancelled the batch", **overrides) -> dict:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


def reschedule_window_payload(
    injection_window_start, injection_window_end, **overrides
) -> dict:
    payload = {
        "injection_window_start": injection_window_start,
        "injection_window_end": injection_window_end,
    }
    payload.update(overrides)
    return payload


def create_maintenance_event_payload(segment_id, **overrides) -> dict:
    """Plan maintenance work on a segment with its capacity derate (PRD 3.8)."""
    payload = {
        "segment_id": segment_id,
        "kind": "PIGGING",
        "window_start": "2026-09-10T00:00:00Z",
        "window_end": "2026-09-12T00:00:00Z",
        "capacity_derate_pct": 0.30,
        "notes": "scraper run",
    }
    payload.update(overrides)
    return payload


def settle_payload(basis_mode="DELIVERED", **overrides) -> dict:
    payload = {"basis_mode": basis_mode}
    payload.update(overrides)
    return payload


def invoice_payload(invoice_number="INV-2026-09-001", **overrides) -> dict:
    payload = {"invoice_number": invoice_number}
    payload.update(overrides)
    return payload


def proration_policy_payload(proration_policy, **overrides) -> dict:
    payload = {"proration_policy": proration_policy}
    payload.update(overrides)
    return payload
