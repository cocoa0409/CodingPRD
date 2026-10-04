"""Serializers: internal record -> wire dict per PRD entity tables.

Datetimes are emitted with three fractional digits (clock.fmt). Decimals are
emitted as int when integral, else float. Batch available_to_ship_units is
derived live from the batch's shipments (PRD 3.4).
"""
from decimal import Decimal

import clock
import store
from constants import ENCUMBERING_SHIPMENT_STATUSES


def num(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _base(rec):
    return {"id": rec["id"], "created_at": clock.fmt(rec["created_at"])}


def _common(rec):
    b = _base(rec)
    b["updated_at"] = clock.fmt(rec["updated_at"])
    b["version"] = rec["version"]
    return b


def site(s):
    d = _common(s)
    d.update({
        "name": s["name"],
        "region": s["region"],
        "monthly_capacity_hours": s["monthly_capacity_hours"],
        "cold_storage_capacity_units": s["cold_storage_capacity_units"],
        "licensed_authorities": s["licensed_authorities"],
        "release_posture": s["release_posture"],
        "open_critical_deviation_count": s["open_critical_deviation_count"],
        "open_critical_finding_count": s["open_critical_finding_count"],
    })
    return d


def product(p):
    d = _common(p)
    d.update({
        "product_code": p["product_code"],
        "molecule_type": p["molecule_type"],
        "market_scope": p["market_scope"],
        "requires_cold_chain": p["requires_cold_chain"],
        "min_storage_temp_c": num(p["min_storage_temp_c"]),
        "max_storage_temp_c": num(p["max_storage_temp_c"]),
        "shelf_life_hours": p["shelf_life_hours"],
        "changeover_hours": p["changeover_hours"],
        "same_product_turnaround_hours": p["same_product_turnaround_hours"],
        "required_materials": p["required_materials"],
    })
    return d


def train(t):
    d = _common(t)
    d.update({
        "site_id": t["site_id"],
        "train_code": t["train_code"],
        "capacity_liters": t["capacity_liters"],
        "supported_molecule_types": t["supported_molecule_types"],
    })
    return d


def campaign(c):
    d = _common(c)
    d.update({
        "train_id": c["train_id"],
        "product_id": c["product_id"],
        "demand_type": c["demand_type"],
        "planned_start_utc": clock.fmt(c["planned_start_utc"]),
        "planned_end_utc": clock.fmt(c["planned_end_utc"]),
        "upstream_hours": c["upstream_hours"],
        "downstream_hours": c["downstream_hours"],
        "allocated_hours": c["allocated_hours"],
        "status": c["status"],
    })
    return d


def seed_stage(s):
    d = _common(s)
    d.update({
        "campaign_id": s["campaign_id"],
        "stage_index": s["stage_index"],
        "planned_duration_hours": s["planned_duration_hours"],
        "started_at": clock.fmt(s["started_at"]) if s["started_at"] else None,
        "completed_at": clock.fmt(s["completed_at"]) if s["completed_at"] else None,
        "status": s["status"],
    })
    return d


def batch(b):
    d = _common(b)
    d.update({
        "campaign_id": b["campaign_id"],
        "lot_number": b["lot_number"],
        "product_id": b["product_id"],
        "process_status": b["process_status"],
        "quality_status": b["quality_status"],
        "quality_hold_return_status": b["quality_hold_return_status"],
        "manufactured_by_user_id": b["manufactured_by_user_id"],
        "quantity_units": b["quantity_units"],
        "provisional_yield_units": b["provisional_yield_units"],
        "final_yield_units": b["final_yield_units"],
        "available_to_ship_units": available_to_ship(b),
        "process_completed_at": clock.fmt(b["process_completed_at"]) if b["process_completed_at"] else None,
        "expiry_utc": clock.fmt(b["expiry_utc"]) if b["expiry_utc"] else None,
    })
    return d


def available_to_ship(b):
    used = sum(
        s["quantity_units"]
        for s in store.all_recs("shipments")
        if s["batch_lot_id"] == b["id"] and s["status"] in ENCUMBERING_SHIPMENT_STATUSES
    )
    return b["quantity_units"] - used


def test(t):
    d = _common(t)
    d.update({
        "batch_lot_id": t["batch_lot_id"],
        "test_type": t["test_type"],
        "phase": t["phase"],
        "measured_value": num(t["measured_value"]),
        "unit": t["unit"],
        "spec_min": num(t["spec_min"]),
        "spec_max": num(t["spec_max"]),
        "is_in_spec": t["is_in_spec"],
        "supersedes_test_id": t["supersedes_test_id"],
        "status": t["status"],
        "recorded_by_user_id": t["recorded_by_user_id"],
        "verified_by_user_id": t["verified_by_user_id"],
    })
    return d


def deviation(v):
    d = _common(v)
    d.update({
        "batch_lot_id": v["batch_lot_id"],
        "kind": v["kind"],
        "severity": v["severity"],
        "description": v["description"],
        "linked_test_id": v["linked_test_id"],
        "status": v["status"],
        "conclusion": v["conclusion"],
        "capa_summary": v["capa_summary"],
        "opened_by_user_id": v["opened_by_user_id"],
        "closed_by_user_id": v["closed_by_user_id"],
    })
    return d


def shipment(s):
    d = _common(s)
    d.update({
        "batch_lot_id": s["batch_lot_id"],
        "destination_region": s["destination_region"],
        "market_type": s["market_type"],
        "quantity_units": s["quantity_units"],
        "status": s["status"],
        "shipped_at": clock.fmt(s["shipped_at"]) if s["shipped_at"] else None,
        "delivered_at": clock.fmt(s["delivered_at"]) if s["delivered_at"] else None,
        "excursion_evaluation": s["excursion_evaluation"],
        "evaluation_variant": s["evaluation_variant"],
    })
    return d


def reading(r):
    d = _base(r)  # readings are immutable and versionless (PRD 2.5)
    d.update({
        "shipment_id": r["shipment_id"],
        "recorded_at": clock.fmt(r["recorded_at"]) if r["recorded_at"] else None,
        "temperature_c": num(r["temperature_c"]),
    })
    return d


def study(s):
    d = _common(s)
    d.update({
        "product_id": s["product_id"],
        "change_type": s["change_type"],
        "baseline_attribute_values": [num(v) for v in s["baseline_attribute_values"]],
        "candidate_batch_ids": s["candidate_batch_ids"],
        "status": s["status"],
        "authority": s["authority"],
        "baseline_mean": num(s["baseline_mean"]) if s["baseline_mean"] is not None else None,
        "equivalence_margin": num(s["equivalence_margin"]) if s["equivalence_margin"] is not None else None,
    })
    return d


def inspection(i):
    d = _common(i)
    d.update({
        "site_id": i["site_id"],
        "authority": i["authority"],
        "status": i["status"],
        "findings": i["findings"],
        "open_critical_finding_count": i["open_critical_finding_count"],
        "response_summary": i["response_summary"],
    })
    return d


def material(m):
    d = _common(m)
    d.update({
        "site_id": m["site_id"],
        "material_name": m["material_name"],
        "is_single_source": m["is_single_source"],
        "quantity_available": num(m["quantity_available"]),
        "status": m["status"],
    })
    return d
