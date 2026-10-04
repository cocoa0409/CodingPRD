"""Entity -> JSON serializers. Computed fields are derived here; internal
keys (leading underscore) and raw datetimes never leak."""

from calc import committed_total_cents, lot_available
from store import DB
from timeutil import iso
from validate import account_credit_hold


def _common(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def account_json(a):
    out = _common(a)
    out.update(
        {
            "name": a["name"],
            "regulatory_class": a["regulatory_class"],
            "region": a["region"],
            "credit_hold": account_credit_hold(a),
            "credit_balance_cents": a["credit_balance_cents"],
        }
    )
    return out


def model_json(m):
    out = _common(m)
    out.update(
        {
            "model_code": m["model_code"],
            "generation": m["generation"],
            "base_price_cents": m["base_price_cents"],
            "supported_chemistry_versions": list(m["supported_chemistry_versions"]),
            "base_run_modes": list(m["base_run_modes"]),
            "support_status": m["support_status"],
        }
    )
    return out


def kit_json(k):
    out = _common(k)
    out.update(
        {
            "kit_code": k["kit_code"],
            "run_type": k["run_type"],
            "flow_cell_version": k["flow_cell_version"],
            "chemistry_version": k["chemistry_version"],
            "regulatory_clearance": k["regulatory_clearance"],
            "shelf_life_days": k["shelf_life_days"],
            "cold_chain_class": k["cold_chain_class"],
            "price_cents": k["price_cents"],
            "samples_per_kit": k["samples_per_kit"],
            "min_model_generation": k["min_model_generation"],
            "capacity_gb": k["capacity_gb"],
        }
    )
    return out


def update_json(u):
    out = _common(u)
    out.update(
        {
            "update_version": u["update_version"],
            "min_model_generation": u["min_model_generation"],
            "unlocks_run_modes": list(u["unlocks_run_modes"]),
            "clinical_validation_status": u["clinical_validation_status"],
            "release_state": u["release_state"],
        }
    )
    return out


def instrument_json(i):
    out = _common(i)
    out.update(
        {
            "account_id": i["account_id"],
            "model_id": i["model_id"],
            "serial_number": i["serial_number"],
            "regulatory_mode": i["regulatory_mode"],
            "installed_at": iso(i["installed_at"]) if i["installed_at"] else None,
            "install_state": i["install_state"],
            "software_version": i["software_version"],
            "applied_update_ids": list(i["applied_update_ids"]),
            "unlocked_run_modes": list(i["unlocked_run_modes"]),
            "service_windows": [
                {
                    "opened_at": iso(w["opened_at"]),
                    "closed_at": iso(w["closed_at"]) if w["closed_at"] else None,
                }
                for w in i["service_windows"]
            ],
            "decommissioned_at": iso(i["decommissioned_at"]) if i["decommissioned_at"] else None,
        }
    )
    return out


def program_json(p):
    out = _common(p)
    pend = p.get("pending_amendment")
    out.update(
        {
            "account_id": p["account_id"],
            "term_months": p["term_months"],
            "committed_annual_reagent_cents": p["committed_annual_reagent_cents"],
            "subsidy_pct": p["subsidy_pct"],
            "hardware_lines": [dict(ln) for ln in p["hardware_lines"]],
            "program_state": p["program_state"],
            "subsidy_pool_cents": p["subsidy_pool_cents"],
            "pinned_kit_prices": dict(p["pinned_kit_prices"]) if p["pinned_kit_prices"] is not None else None,
            "committed_total_cents": committed_total_cents(p),
            "delivered_spend_cents": p["delivered_spend_cents"],
            "pipeline_spend_cents": p["pipeline_spend_cents"],
            "shortfall_flag": p["shortfall_flag"],
            "penalty_cents": p["penalty_cents"],
            "period_index": p["period_index"],
            "created_by_user_id": p["created_by_user_id"],
            "approved_by_user_id": p["approved_by_user_id"],
            "pending_amendment": dict(pend) if pend is not None else None,
        }
    )
    return out


def lot_json(lot):
    out = _common(lot)
    out.update(
        {
            "kit_id": lot["kit_id"],
            "lot_number": lot["lot_number"],
            "manufacture_date": iso(lot["manufacture_date"]),
            "quantity_units": lot["quantity_units"],
            "qc_status": lot["qc_status"],
            "cold_chain_status": lot["cold_chain_status"],
            "expiry_date": iso(lot["expiry_date"]),
            "reserved_units": lot["reserved_units"],
            "consumed_units": lot["consumed_units"],
            "available_units": lot_available(lot),
        }
    )
    return out


def order_json(o):
    out = _common(o)
    out.update(
        {
            "account_id": o["account_id"],
            "program_id": o["program_id"],
            "lines": [dict(ln) for ln in o["lines"]],
            "order_state": o["order_state"],
            "total_cents": o["total_cents"],
            "attributed_total_cents": o["attributed_total_cents"],
            "line_reservations": [dict(r) for r in o["line_reservations"]],
            "submitted_at": iso(o["submitted_at"]) if o["submitted_at"] else None,
            "delivered_at": iso(o["delivered_at"]) if o["delivered_at"] else None,
        }
    )
    return out


def contract_json(c):
    out = _common(c)
    out.update(
        {
            "account_id": c["account_id"],
            "instrument_id": c["instrument_id"],
            "coverage_start": iso(c["coverage_start"]),
            "coverage_end": iso(c["coverage_end"]),
            "committed_uptime_percent": c["committed_uptime_percent"],
            "monthly_fee_cents": c["monthly_fee_cents"],
            "annual_credit_cap_cents": c["annual_credit_cap_cents"],
            "reagent_guarantee": c["reagent_guarantee"],
            "contract_state": c["contract_state"],
            "credits_issued_ytd_cents": c["credits_issued_ytd_cents"],
            "last_reconciliation_end": iso(c["last_reconciliation_end"]) if c["last_reconciliation_end"] else None,
            "terminated_reason": c["terminated_reason"],
        }
    )
    return out


def ledger_entry_json(e):
    out = {"entry_type": e["entry_type"], "credits": e["credits"]}
    if e["entry_type"] in ("GRANT", "PURCHASE"):
        out["granted_on"] = e["granted_on"]
    out["created_at"] = iso(e["created_at"])
    return out


def license_json(lic):
    out = _common(lic)
    out.update(
        {
            "account_id": lic["account_id"],
            "license_state": lic["license_state"],
            "activated_at": iso(lic["activated_at"]) if lic["activated_at"] else None,
            "pinned_sample_rate_cents": dict(lic["pinned_sample_rate_cents"])
            if lic["pinned_sample_rate_cents"] is not None
            else None,
            "credit_ledger": [ledger_entry_json(e) for e in lic["credit_ledger"]],
            "credits_balance": sum(e["credits"] for e in lic["credit_ledger"]),
            "samples_this_period": lic["samples_this_period"],
            "period_index": lic["period_index"],
        }
    )
    return out


def run_json(r):
    # Run records: id + created_at only (no updated_at, no version) per PRD 2.5.
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "instrument_id": r["instrument_id"],
        "lot_id": r["lot_id"],
        "license_id": r["license_id"],
        "run_at": iso(r["run_at"]),
        "run_mode": r["run_mode"],
        "analysis_mode": r["analysis_mode"],
        "samples_count": r["samples_count"],
        "output_gb": r["output_gb"],
        "outcome": r["outcome"],
        "credits_consumed": r["credits_consumed"],
    }


def transition_json(t):
    out = _common(t)
    out.update(
        {
            "account_id": t["account_id"],
            "old_instrument_id": t["old_instrument_id"],
            "new_model_id": t["new_model_id"],
            "enrollment_window_end": iso(t["enrollment_window_end"]),
            "program_state": t["program_state"],
            "provisional_credit_cents": t["provisional_credit_cents"],
            "condition_flags": list(t["condition_flags"]),
            "final_credit_cents": t["final_credit_cents"],
            "created_by_user_id": t["created_by_user_id"],
            "appraised_by_user_id": t["appraised_by_user_id"],
            "appraised_at": iso(t["appraised_at"]) if t["appraised_at"] else None,
        }
    )
    return out


def forecast_json(f, variance_lines=None):
    out = _common(f)
    out.update(
        {
            "account_id": f["account_id"],
            "lines": [
                {"kit_code": ln["kit_code"], "week_start": iso(ln["week_start"]), "quantity": ln["quantity"]}
                for ln in f["lines"]
            ],
            "forecast_state": f["forecast_state"],
            "variance_lines": variance_lines if variance_lines is not None else [],
        }
    )
    return out
