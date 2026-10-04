"""Entity serializers: internal dicts -> JSON-safe public representations.

Computed fields are derived at serialization time so reads always observe
state as of the current logical clock.
"""

import calc
import store


def _num(v):
    if v is None:
        return None
    return calc.num(v)


def serialize_project(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "region_code": p["region_code"],
        "floors": p["floors"],
        "rows_per_floor": p["rows_per_floor"],
        "positions_per_row": p["positions_per_row"],
        "construction_lag_months": p["construction_lag_months"],
        "planned_annual_distillation_liters": p["planned_annual_distillation_liters"],
        "state": p["state"],
        "approved_at": store.fmt_ts(p["approved_at"]),
        "commissioned_at": store.fmt_ts(p["commissioned_at"]),
        "created_at": store.fmt_ts(p["created_at"]),
        "updated_at": store.fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def serialize_rickhouse(r):
    return {
        "id": r["id"],
        "expansion_project_id": r["expansion_project_id"],
        "name": r["name"],
        "region_code": r["region_code"],
        "floors": r["floors"],
        "rows_per_floor": r["rows_per_floor"],
        "positions_per_row": r["positions_per_row"],
        "total_slots": calc.total_slots(r),
        "occupied_slots": calc.occupied_slots(r),
        "posture": calc.posture(r),
        "created_at": store.fmt_ts(r["created_at"]),
        "updated_at": store.fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_slot(s):
    return {
        "id": s["id"],
        "rickhouse_id": s["rickhouse_id"],
        "floor_index": s["floor_index"],
        "row_index": s["row_index"],
        "position_index": s["position_index"],
        "heat_factor": s["heat_factor"],
        "created_at": store.fmt_ts(s["created_at"]),
        "updated_at": store.fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def serialize_occupancy(o):
    return {
        "id": o["id"],
        "barrel_id": o["barrel_id"],
        "slot_id": o["slot_id"],
        "move_reason": o["move_reason"],
        "start_at": store.fmt_ts(o["start_at"]),
        "end_at": store.fmt_ts(o["end_at"]),
        "status": "OPEN" if o["end_at"] is None else "CLOSED",
        "created_at": store.fmt_ts(o["created_at"]),
    }


def serialize_barrel(b):
    calc.refresh_barrel(b)
    now = store.now()
    return {
        "id": b["id"],
        "wood_origin": b["wood_origin"],
        "seasoning_months": b["seasoning_months"],
        "char_level": b["char_level"],
        "spirit_type": b["spirit_type"],
        "fill_proof": b["fill_proof"],
        "fill_volume_liters": _num(b["fill_volume_liters"]),
        "min_maturation_months": b["min_maturation_months"],
        "fill_date": store.fmt_ts(b["fill_date"]),
        "maturation_status": b["maturation_status"],
        "custody_status": b["custody_status"],
        "current_volume_ledger_liters": _num(calc.ledger_at(b)),
        "current_volume_statutory_liters": _num(calc.statutory_at(b, now)),
        "current_slot_id": calc.current_slot_id(b),
        "withdrawn_at": store.fmt_ts(b["withdrawn_at"]),
        "withdrawn_volume_liters": _num(b["withdrawn_volume_liters"]),
        "created_at": store.fmt_ts(b["created_at"]),
        "updated_at": store.fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "barrel_id": a["barrel_id"],
        "kind": a["kind"],
        "measured_volume_liters": _num(a["measured_volume_liters"]),
        "sample_draw_liters": _num(a["sample_draw_liters"]),
        "quality_score": a["quality_score"],
        "assessed_at": store.fmt_ts(a["assessed_at"]),
        "created_at": store.fmt_ts(a["created_at"]),
    }


def serialize_label(lbl):
    return {
        "id": lbl["id"],
        "name": lbl["name"],
        "age_statement_years": lbl["age_statement_years"],
        "spirit_type": lbl["spirit_type"],
        "state": lbl["state"],
        "created_at": store.fmt_ts(lbl["created_at"]),
        "updated_at": store.fmt_ts(lbl["updated_at"]),
        "version": lbl["version"],
    }


def serialize_batch(batch):
    return {
        "id": batch["id"],
        "label_id": batch["label_id"],
        "scheduled_bottling_date": store.fmt_ts(batch["scheduled_bottling_date"]),
        "state": batch["state"],
        "validated_at": store.fmt_ts(batch["validated_at"]),
        "committed_at": store.fmt_ts(batch["committed_at"]),
        "final_blend_volume_liters": _num(batch["final_blend_volume_liters"]),
        "created_at": store.fmt_ts(batch["created_at"]),
        "updated_at": store.fmt_ts(batch["updated_at"]),
        "version": batch["version"],
    }


def serialize_component(c):
    return {
        "id": c["id"],
        "blend_batch_id": c["blend_batch_id"],
        "barrel_id": c["barrel_id"],
        "drawn_volume_liters": _num(c["drawn_volume_liters"]),
        "created_at": store.fmt_ts(c["created_at"]),
        "updated_at": store.fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def serialize_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "spirit_type": p["spirit_type"],
        "min_quality_score": p["min_quality_score"],
        "required_barrel_count": p["required_barrel_count"],
        "reservation_window_days": p["reservation_window_days"],
        "state": p["state"],
        "available_slots": calc.available_slots(p),
        "created_at": store.fmt_ts(p["created_at"]),
        "updated_at": store.fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def serialize_reservation(r):
    calc.refresh_reservation(r)
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "barrel_id": r["barrel_id"],
        "state": r["state"],
        "expires_at": store.fmt_ts(r["expires_at"]),
        "created_at": store.fmt_ts(r["created_at"]),
        "updated_at": store.fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_report(rep):
    return {
        "id": rep["id"],
        "period_start": store.fmt_ts(rep["period_start"]),
        "period_end": store.fmt_ts(rep["period_end"]),
        "opening_inventory_liters": _num(rep["opening_inventory_liters"]),
        "period_fills_liters": _num(rep["period_fills_liters"]),
        "period_withdrawals_liters": _num(rep["period_withdrawals_liters"]),
        "loss_actual_liters": _num(rep["loss_actual_liters"]),
        "loss_statutory_liters": _num(rep["loss_statutory_liters"]),
        "reported_loss_liters": _num(rep["reported_loss_liters"]),
        "closing_inventory_liters": _num(rep["closing_inventory_liters"]),
        "state": rep["state"],
        "prepared_by_user_id": rep["prepared_by_user_id"],
        "filed_by_user_id": rep["filed_by_user_id"],
        "decided_by_user_id": rep["decided_by_user_id"],
        "created_at": store.fmt_ts(rep["created_at"]),
        "updated_at": store.fmt_ts(rep["updated_at"]),
        "version": rep["version"],
    }
