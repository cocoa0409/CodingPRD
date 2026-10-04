"""Serializers: convert stored entities (with internal datetime/Decimal fields)
into the wire representation."""

from helpers import num_out


def _fmt_dt(dt):
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + "Z"


def municipality_out(m):
    return {
        "id": m["id"],
        "legal_name": m["legal_name"],
        "population_served": m["population_served"],
        "is_host_community": m["is_host_community"],
        "priority_group": m["priority_group"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def host_agreement_out(h):
    return {
        "id": h["id"],
        "municipality_id": h["municipality_id"],
        "annual_payment_cents": h["annual_payment_cents"],
        "payment_due_month": h["payment_due_month"],
        "local_waste_priority_enabled": h["local_waste_priority_enabled"],
        "effective_start": _fmt_dt(h["effective_start"]),
        "effective_end": _fmt_dt(h["effective_end"]),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def agreement_out(a):
    return {
        "id": a["id"],
        "municipality_id": a["municipality_id"],
        "term_start": _fmt_dt(a["term_start"]),
        "term_end": _fmt_dt(a["term_end"]),
        "guaranteed_annual_tonnage": num_out(a["guaranteed_annual_tonnage"]),
        "tipping_fee_per_tonne_cents": a["tipping_fee_per_tonne_cents"],
        "put_or_pay_settlement_cadence": a["put_or_pay_settlement_cadence"],
        "state": a["state"],
        "amendment_of_agreement_id": a["amendment_of_agreement_id"],
        "cumulative_delivered_tonnes": num_out(a["cumulative_delivered_tonnes"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def delivery_out(d, projected_fee=None):
    out = {
        "id": d["id"],
        "agreement_id": d["agreement_id"],
        "manifest_ref": d["manifest_ref"],
        "tonnes": num_out(d["tonnes"]),
        "heating_value_mj_per_kg": num_out(d["heating_value_mj_per_kg"]),
        "delivered_at": _fmt_dt(d["delivered_at"]),
        "status": d["status"],
        "tipping_fee_cents": d["tipping_fee_cents"],
        "projected_fee_cents": projected_fee,
        "diversion_outage_id": d["diversion_outage_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }
    if d.get("reject_reason") is not None:
        out["reject_reason"] = d["reject_reason"]
    return out


def boiler_out(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "max_thermal_capacity_mw": num_out(b["max_thermal_capacity_mw"]),
        "max_steam_tph": num_out(b["max_steam_tph"]),
        "status": b["status"],
        "derated_capacity_mw": (num_out(b["derated_capacity_mw"])
                                 if b["derated_capacity_mw"] is not None else None),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def outage_out(o):
    return {
        "id": o["id"],
        "boiler_id": o["boiler_id"],
        "starts_at": _fmt_dt(o["starts_at"]),
        "ends_at": _fmt_dt(o["ends_at"]),
        "reason": o["reason"],
        "kind": o["kind"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def plan_out(p):
    return {
        "id": p["id"],
        "outage_id": p["outage_id"],
        "approved": p["approved"],
        "max_diversion_tpd": num_out(p["max_diversion_tpd"]),
        "planned_diverted_tonnes": num_out(p["planned_diverted_tonnes"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def leg_out(lg):
    return {
        "id": lg["id"],
        "diversion_plan_id": lg["diversion_plan_id"],
        "receiving_facility_name": lg["receiving_facility_name"],
        "planned_tonnes": num_out(lg["planned_tonnes"]),
        "executed": lg["executed"],
        "created_at": lg["created_at"],
        "updated_at": lg["updated_at"],
        "version": lg["version"],
    }


def report_out(r):
    return {
        "id": r["id"],
        "report_date": r["report_date"],
        "waste_processed_tonnes": num_out(r["waste_processed_tonnes"]),
        "avg_heating_value_mj_per_kg": num_out(r["avg_heating_value_mj_per_kg"]),
        "operating_hours": num_out(r["operating_hours"]),
        "thermal_input_mw": r["thermal_input_mw"],
        "steam_output_tph": r["steam_output_tph"],
        "ash_generated_tonnes": r["ash_generated_tonnes"],
        "capacity_check": r["capacity_check"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ppa_out(p):
    return {
        "id": p["id"],
        "counterparty_name": p["counterparty_name"],
        "kind": p["kind"],
        "energy_rate_cents_per_mwh": p["energy_rate_cents_per_mwh"],
        "capacity_payment_cents_per_mw_month": p["capacity_payment_cents_per_mw_month"],
        "contracted_mw": num_out(p["contracted_mw"]),
        "term_start": _fmt_dt(p["term_start"]),
        "term_end": _fmt_dt(p["term_end"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def energy_delivery_out(e):
    return {
        "id": e["id"],
        "ppa_id": e["ppa_id"],
        "period_start": _fmt_dt(e["period_start"]),
        "period_end": _fmt_dt(e["period_end"]),
        "delivered_mwh": num_out(e["delivered_mwh"]),
        "merchant_price_cents_per_mwh": e["merchant_price_cents_per_mwh"],
        "billed_amount_cents": e["billed_amount_cents"],
        "capacity_payment_cents": e["capacity_payment_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def metals_contract_out(c):
    return {
        "id": c["id"],
        "processor_name": c["processor_name"],
        "ferrous_recovery_pct": num_out(c["ferrous_recovery_pct"]),
        "nonferrous_recovery_pct": num_out(c["nonferrous_recovery_pct"]),
        "processing_fee_cents_per_tonne": c["processing_fee_cents_per_tonne"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def metals_batch_out(b):
    return {
        "id": b["id"],
        "contract_id": b["contract_id"],
        "ash_input_tonnes": num_out(b["ash_input_tonnes"]),
        "ferrous_price_cents_per_tonne": b["ferrous_price_cents_per_tonne"],
        "nonferrous_price_cents_per_tonne": b["nonferrous_price_cents_per_tonne"],
        "ferrous_tonnes": b["ferrous_tonnes"],
        "nonferrous_tonnes": b["nonferrous_tonnes"],
        "gross_revenue_cents": b["gross_revenue_cents"],
        "processing_fee_cents": b["processing_fee_cents"],
        "net_settlement_cents": b["net_settlement_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def landfill_out(lf):
    return {
        "id": lf["id"],
        "name": lf["name"],
        "permit_number": lf["permit_number"],
        "remaining_capacity_tonnes": num_out(lf["remaining_capacity_tonnes"]),
        "daily_receipt_limit_tonnes": num_out(lf["daily_receipt_limit_tonnes"]),
        "status": lf["status"],
        "created_at": lf["created_at"],
        "updated_at": lf["updated_at"],
        "version": lf["version"],
    }


def shipment_out(s):
    out = {
        "id": s["id"],
        "landfill_id": s["landfill_id"],
        "tonnes": num_out(s["tonnes"]),
        "shipped_on": s["shipped_on"],
        "disposal_fee_cents_per_tonne": s["disposal_fee_cents_per_tonne"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
    if s.get("reject_reason") is not None:
        out["reject_reason"] = s["reject_reason"]
    return out


def ash_test_out(t):
    return {
        "id": t["id"],
        "shipment_id": t["shipment_id"],
        "parameter": t["parameter"],
        "measured_value": num_out(t["measured_value"]),
        "limit_value": num_out(t["limit_value"]),
        "passed": t["passed"],
        "recorded_at": t["recorded_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def permit_out(p):
    return {
        "id": p["id"],
        "pollutant": p["pollutant"],
        "hourly_limit": num_out(p["hourly_limit"]),
        "daily_limit": num_out(p["daily_limit"]),
        "rolling_avg_window_hours": p["rolling_avg_window_hours"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def reading_out(r):
    return {
        "id": r["id"],
        "permit_id": r["permit_id"],
        "value": num_out(r["value"]),
        "measured_at": _fmt_dt(r["measured_at"]),
        "exceedance": r["exceedance"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
