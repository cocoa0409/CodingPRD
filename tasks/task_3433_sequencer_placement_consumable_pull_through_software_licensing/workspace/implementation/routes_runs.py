"""Run record endpoints. Gate order follows PRD 3.7's explicit enumeration
(after the generic tiers): operational -> license active -> lot usable -> lot
depleted -> cold chain -> lot expiry -> clinical clearance -> run mode ->
kit run type -> chemistry -> kit model generation -> credits."""

from flask import Blueprint, request

from auth import require_ownership, require_roles
from calc import CLOUD_CREDIT_COST, lot_available
from envelope import ok, ok_list, sort_items
from errors import ApiError, not_found
from serializers import run_json
from store import DB, new_id, now, stamp_new_run, touch
from validate import f_dt, f_enum, f_int, f_num, f_str, get_body

bp = Blueprint("runs", __name__)


@bp.post("/genomics/run-records")
def create_run():
    uid, _role = require_roles("LabOperator")
    body = get_body()
    # Priority 4 ownership anchors on the instrument; resolve it first.
    raw_instrument = body.get("instrument_id")
    instrument = None
    if isinstance(raw_instrument, str) and raw_instrument:
        instrument = DB["instruments"].get(raw_instrument)
        if instrument is None:
            raise not_found("instrument_id does not resolve")
        require_ownership(instrument["account_id"] == uid)
    # Priority 6: remaining body references.
    raw_lot = body.get("lot_id")
    if isinstance(raw_lot, str) and raw_lot and raw_lot not in DB["lots"]:
        raise not_found("lot_id does not resolve")
    raw_license = body.get("license_id")
    if isinstance(raw_license, str) and raw_license and raw_license not in DB["licenses"]:
        raise not_found("license_id does not resolve")
    # Priority 7: request shape.
    instrument_id = f_str(body, "instrument_id")
    lot_id = f_str(body, "lot_id")
    license_id = f_str(body, "license_id")
    run_at = f_dt(body, "run_at")
    run_mode = f_enum(body, "run_mode", ["STD_SHORT", "STD_LONG", "HIGH_OUTPUT"])
    analysis_mode = f_enum(body, "analysis_mode", ["LOCAL", "CLOUD_STANDARD", "CLOUD_DEEP"])
    samples_count = f_int(body, "samples_count", min_v=0)
    output_gb = f_num(body, "output_gb")
    outcome = f_enum(body, "outcome", ["SUCCESS", "PARTIAL", "FAILED"])
    if instrument is None:
        instrument = DB["instruments"].get(instrument_id)
        if instrument is None:
            raise not_found("instrument_id does not resolve")
        require_ownership(instrument["account_id"] == uid)
    lot = DB["lots"].get(lot_id)
    if lot is None:
        raise not_found("lot_id does not resolve")
    lic = DB["licenses"].get(license_id)
    if lic is None:
        raise not_found("license_id does not resolve")
    # Domain gates in the PRD 3.7 relative order.
    if instrument["install_state"] != "OPERATIONAL":
        raise ApiError(
            "ERR_INSTRUMENT_NOT_OPERATIONAL", 409, "Instrument must be OPERATIONAL"
        )
    if lic["license_state"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License must be ACTIVE")
    if lot["qc_status"] != "QC_PASSED":
        raise ApiError("ERR_LOT_NOT_USABLE", 409, "Lot has not passed QC")
    if lot_available(lot) < 1:
        raise ApiError("ERR_LOT_DEPLETED", 409, "Lot has no available units")
    if lot["cold_chain_status"] != "INTACT":
        raise ApiError("ERR_COLD_CHAIN_BREACHED", 422, "Lot cold chain is breached")
    t = now()
    if not (lot["expiry_date"] > t):
        raise ApiError("ERR_LOT_EXPIRED", 422, "Lot has expired")
    kit = DB["kits"].get(lot["kit_id"])
    if (
        instrument["regulatory_mode"] == "CLINICAL"
        and kit is not None
        and kit["regulatory_clearance"] != "IVD"
    ):
        raise ApiError(
            "ERR_CHEMISTRY_NOT_CLEARED_FOR_CLINICAL",
            422,
            "CLINICAL instruments consume only IVD-cleared kits",
        )
    if run_mode not in instrument["unlocked_run_modes"]:
        raise ApiError("ERR_RUN_MODE_LOCKED", 422, "Run mode is not unlocked on the instrument")
    if kit is not None and kit["run_type"] != run_mode:
        raise ApiError(
            "ERR_KIT_RUN_TYPE_MISMATCH", 422, "The lot's kit run_type differs from run_mode"
        )
    model = DB["models"][instrument["model_id"]]
    if kit is not None and kit["chemistry_version"] not in model["supported_chemistry_versions"]:
        raise ApiError(
            "ERR_CHEMISTRY_UNSUPPORTED",
            422,
            "The kit's chemistry is not supported by the instrument model",
        )
    if kit is not None and kit["min_model_generation"] > model["generation"]:
        raise ApiError(
            "ERR_KIT_MODEL_INCOMPATIBLE",
            422,
            "The kit requires a newer instrument generation",
        )
    # Fiscal gate: non-FAILED cloud runs need enough credits.
    cost = CLOUD_CREDIT_COST[analysis_mode] if outcome != "FAILED" else 0
    if cost > 0:
        balance = sum(e["credits"] for e in lic["credit_ledger"])
        if balance < cost:
            raise ApiError(
                "ERR_INSUFFICIENT_CREDITS", 402, "Cloud credit cost exceeds the license balance"
            )
    # Side effects: every run consumes exactly one lot unit.
    lot["consumed_units"] += 1
    touch(lot)
    credits_consumed = 0
    if outcome != "FAILED":
        lic["samples_this_period"] += samples_count
        if analysis_mode != "LOCAL":
            credits_consumed = cost
            lic["_ledger_seq"] = lic.get("_ledger_seq", 0) + 1
            lic["credit_ledger"].append(
                {
                    "entry_type": "CONSUMPTION",
                    "credits": -cost,
                    "created_at": t,
                    "_gid": lic["_ledger_seq"],
                }
            )
        touch(lic)
    run = {
        "id": new_id(),
        "instrument_id": instrument_id,
        "lot_id": lot_id,
        "license_id": license_id,
        "run_at": run_at,
        "run_mode": run_mode,
        "analysis_mode": analysis_mode,
        "samples_count": samples_count,
        "output_gb": output_gb,
        "outcome": outcome,
        "credits_consumed": credits_consumed,
    }
    stamp_new_run(run)
    DB["runs"][run["id"]] = run
    return ok(run_json(run), 201)


@bp.get("/genomics/run-records/<run_id>")
def get_run(run_id):
    uid, role = require_roles("LabOperator", "SupplyPlanner", "FinanceAdmin")
    run = DB["runs"].get(run_id)
    if run is None:
        raise not_found("RunRecord not found")
    if role == "LabOperator":
        instrument = DB["instruments"].get(run["instrument_id"])
        require_ownership(instrument is not None and instrument["account_id"] == uid)
    return ok(run_json(run))


@bp.get("/genomics/run-records")
def list_runs():
    uid, role = require_roles("LabOperator", "SupplyPlanner", "FinanceAdmin")
    items = list(DB["runs"].values())
    if role == "LabOperator":
        # Auto-scope to the caller's own account's instruments.
        own_instruments = {
            i["id"] for i in DB["instruments"].values() if i["account_id"] == uid
        }
        items = [r for r in items if r["instrument_id"] in own_instruments]
    instrument_id = request.args.get("instrument_id")
    lot_id = request.args.get("lot_id")
    license_id = request.args.get("license_id")
    if instrument_id is not None:
        items = [r for r in items if r["instrument_id"] == instrument_id]
    if lot_id is not None:
        items = [r for r in items if r["lot_id"] == lot_id]
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    return ok_list([run_json(r) for r in sort_items(items)])
