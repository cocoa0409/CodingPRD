"""JSON representations for every entity (PRD 2.4, 2.9)."""
from decimal import Decimal

from core import fmt_instant, r2, r3, r6


def _num(value):
    """Echo a stored number without imposing a scale."""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _m2(value):
    return None if value is None else float(r2(value))


def _m3(value):
    return None if value is None else float(r3(value))


def _m6(value):
    return None if value is None else float(r6(value))


def _whole(value):
    return None if value is None else int(Decimal(value))


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": fmt_instant(row["created_at"])}
    if versioned:
        out["updated_at"] = fmt_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def terminal_json(row):
    out = _common(row)
    out.update({
        "terminal_code": row["terminal_code"],
        "name": row["name"],
        "role_kind": row["role_kind"],
        "shell_capacity_bbl": _num(row["shell_capacity_bbl"]),
        "min_operating_inventory_bbl": _num(row["min_operating_inventory_bbl"]),
        "injection_bays": row["injection_bays"],
        "inventory_bbl": _m2(row["inventory_bbl"]),
    })
    return out


def grade_json(row):
    out = _common(row)
    out.update({
        "grade_code": row["grade_code"],
        "name": row["name"],
        "sequence_rank": row["sequence_rank"],
        "max_sulfur_ppm": _num(row["max_sulfur_ppm"]),
        "max_rvp_psi": _num(row["max_rvp_psi"]),
        "is_transmix_grade": bool(row["is_transmix_grade"]),
    })
    return out


def segment_json(row):
    out = _common(row)
    out.update({
        "segment_code": row["segment_code"],
        "origin_terminal_id": row["origin_terminal_id"],
        "destination_terminal_id": row["destination_terminal_id"],
        "linefill_grade_id": row["linefill_grade_id"],
        "capacity_bbl_per_cycle": _num(row["capacity_bbl_per_cycle"]),
        "transmix_reserve_bbl": _num(row["transmix_reserve_bbl"]),
        "transmix_cut_bbl": _num(row["transmix_cut_bbl"]),
        "min_tender_bbl": _num(row["min_tender_bbl"]),
        "linefill_requirement_bbl": _num(row["linefill_requirement_bbl"]),
        "linefill_bbl": _m2(row["linefill_bbl"]),
        "proration_policy": row["proration_policy"],
        "operational_status": row["operational_status"],
        "derate_pct": _m2(row["derate_pct"]),
        "in_transit_bbl": _m2(row["in_transit_bbl"]),
        "transmix_inventory_bbl": _m2(row["transmix_inventory_bbl"]),
        "system_loss_bbl": _m2(row["system_loss_bbl"]),
    })
    return out


def shipper_json(row):
    out = _common(row)
    out.update({
        "shipper_code": row["shipper_code"],
        "name": row["name"],
        "status": row["status"],
        "suspended_reason": row["suspended_reason"],
        "credit_limit_usd": _m2(row["credit_limit_usd"]),
        "exposure_usd": _m2(row["exposure_usd"]),
    })
    return out


def history_json(row):
    out = _common(row, versioned=False)
    out.update({
        "shipper_id": row["shipper_id"],
        "segment_id": row["segment_id"],
        "cycle_code": row["cycle_code"],
        "actual_shipped_bbl": _m2(row["actual_shipped_bbl"]),
        "cycle_end_at": fmt_instant(row["cycle_end_at"]),
        "record_status": row["record_status"],
    })
    return out


def tariff_json(row):
    out = _common(row)
    out.update({
        "segment_id": row["segment_id"],
        "grade_id": row["grade_id"],
        "base_rate_usd_per_bbl": _m3(row["base_rate_usd_per_bbl"]),
        "tier1_min_bbl": _num(row["tier1_min_bbl"]),
        "tier1_rate_usd_per_bbl": _m3(row["tier1_rate_usd_per_bbl"]),
        "tier2_min_bbl": _num(row["tier2_min_bbl"]),
        "tier2_rate_usd_per_bbl": _m3(row["tier2_rate_usd_per_bbl"]),
        "tender_minimum_bbl": _num(row["tender_minimum_bbl"]),
        "imbalance_penalty_rate_usd_per_bbl": _num(row["imbalance_penalty_rate_usd_per_bbl"]),
        "effective_from": fmt_instant(row["effective_from"]),
        "effective_to": fmt_instant(row["effective_to"]),
        "status": row["status"],
    })
    return out


def cycle_json(row):
    out = _common(row)
    out.update({
        "cycle_code": row["cycle_code"],
        "segment_id": row["segment_id"],
        "window_open_at": fmt_instant(row["window_open_at"]),
        "window_close_at": fmt_instant(row["window_close_at"]),
        "ship_start_at": fmt_instant(row["ship_start_at"]),
        "ship_end_at": fmt_instant(row["ship_end_at"]),
        "status": row["status"],
        "effective_capacity_bbl": _whole(row["effective_capacity_bbl"]),
        "derate_pct_applied": _m2(row["derate_pct_applied"]),
        "nominated_total_bbl": _m2(row["nominated_total_bbl"]),
        "allocated_total_bbl": _whole(row["allocated_total_bbl"]),
        "unallocated_capacity_bbl": _whole(row["unallocated_capacity_bbl"]),
        "proration_factor": _m6(row["proration_factor"]),
        "total_transmix_bbl": _whole(row["total_transmix_bbl"]),
        "schedule_version": row["schedule_version"],
        "schedule_published_at": fmt_instant(row["schedule_published_at"]),
        "schedule_published_by_user_id": row["schedule_published_by_user_id"],
        "settled_at": fmt_instant(row["settled_at"]),
    })
    return out


def nomination_json(row):
    out = _common(row)
    out.update({
        "cycle_id": row["cycle_id"],
        "shipper_id": row["shipper_id"],
        "grade_id": row["grade_id"],
        "origin_terminal_id": row["origin_terminal_id"],
        "destination_terminal_id": row["destination_terminal_id"],
        "supersedes_nomination_id": row["supersedes_nomination_id"],
        "pinned_tariff_id": row["pinned_tariff_id"],
        "nominated_bbl": _num(row["nominated_bbl"]),
        "allocated_bbl": _whole(row["allocated_bbl"]),
        "history_base_bbl": _m2(row["history_base_bbl"]),
        "allocation_class": row["allocation_class"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "revision_count": row["revision_count"],
    })
    return out


def ticket_json(row):
    out = _common(row)
    out.update({
        "cycle_id": row["cycle_id"],
        "nomination_id": row["nomination_id"],
        "predecessor_batch_id": row["predecessor_batch_id"],
        "sequence_position": row["sequence_position"],
        "volume_bbl": _m2(row["volume_bbl"]),
        "transmix_bbl": _whole(row["transmix_bbl"]),
        "requires_flush": bool(row["requires_flush"]),
        "injection_window_start": fmt_instant(row["injection_window_start"]),
        "injection_window_end": fmt_instant(row["injection_window_end"]),
        "movement_status": row["movement_status"],
        "quality_status": row["quality_status"],
        "measured_sulfur_ppm": _num(row["measured_sulfur_ppm"]),
        "measured_rvp_psi": _num(row["measured_rvp_psi"]),
        "retest_count": row["retest_count"],
        "injected_bbl": _m2(row["injected_bbl"]),
        "delivered_bbl": _m2(row["delivered_bbl"]),
        "cancel_reason": row["cancel_reason"],
    })
    return out


def maintenance_json(row):
    out = _common(row)
    out.update({
        "segment_id": row["segment_id"],
        "kind": row["kind"],
        "window_start": fmt_instant(row["window_start"]),
        "window_end": fmt_instant(row["window_end"]),
        "capacity_derate_pct": _m2(row["capacity_derate_pct"]),
        "status": row["status"],
        "notified_at": fmt_instant(row["notified_at"]),
        "notified_shipper_count": row["notified_shipper_count"],
        "notes": row["notes"],
    })
    return out


def settlement_json(row):
    out = _common(row)
    out.update({
        "cycle_id": row["cycle_id"],
        "shipper_id": row["shipper_id"],
        "basis_mode": row["basis_mode"],
        "scheduled_bbl": _m2(row["scheduled_bbl"]),
        "delivered_bbl": _m2(row["delivered_bbl"]),
        "loss_allocation_bbl": _m2(row["loss_allocation_bbl"]),
        "imbalance_bbl": _m2(row["imbalance_bbl"]),
        "imbalance_pct": _m6(row["imbalance_pct"]),
        "imbalance_tier": row["imbalance_tier"],
        "tariff_charge_usd": _m2(row["tariff_charge_usd"]),
        "alt_basis_charge_usd": _m2(row["alt_basis_charge_usd"]),
        "basis_delta_usd": _m2(row["basis_delta_usd"]),
        "imbalance_charge_usd": _m2(row["imbalance_charge_usd"]),
        "total_billed_usd": _m2(row["total_billed_usd"]),
        "status": row["status"],
        "certified_by_user_id": row["certified_by_user_id"],
        "invoice_number": row["invoice_number"],
    })
    return out
