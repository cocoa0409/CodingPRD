"""Record -> JSON dict serializers. Logical timestamps use the shop clock format;
kg quantities at 2dp; ledger records carry only id + created_at."""

from helpers import format_logical, kg_out, pct_out
from db import db


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _ledger(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def shop_out(s):
    out = _common(s)
    out.update({
        "shop_name": s["shop_name"],
        "aws_d1_1_revision": s["aws_d1_1_revision"],
        "repair_rate_limit_pct": s["repair_rate_limit_pct"],
        "current_utc": format_logical(s["current_utc"]),
    })
    return out


def welder_out(w):
    out = _common(w)
    out.update({
        "shop_id": w["shop_id"],
        "stencil": w["stencil"],
        "full_name": w["full_name"],
        "status": w["status"],
    })
    return out


def ndt_vendor_out(v):
    out = _common(v)
    out.update({
        "shop_id": v["shop_id"],
        "vendor_name": v["vendor_name"],
        "supported_methods": list(v["supported_methods"]),
        "hourly_capacity": v["hourly_capacity"],
        "status": v["status"],
    })
    return out


def oven_out(o):
    out = _common(o)
    out.update({
        "shop_id": o["shop_id"],
        "oven_code": o["oven_code"],
        "holding_temp_c": o["holding_temp_c"],
        "capacity_electrodes_kg": o["capacity_electrodes_kg"],
        "status": o["status"],
    })
    return out


def pqr_out(p):
    out = _common(p)
    out.update({
        "shop_id": p["shop_id"],
        "pqr_number": p["pqr_number"],
        "process": p["process"],
        "base_metal_spec": p["base_metal_spec"],
        "thickness_range_min_mm": p["thickness_range_min_mm"],
        "thickness_range_max_mm": p["thickness_range_max_mm"],
        "test_report_id": p["test_report_id"],
        "reviewed_by_user_id": p["reviewed_by_user_id"],
        "status": p["status"],
    })
    return out


def wps_out(w):
    out = _common(w)
    out.update({
        "shop_id": w["shop_id"],
        "wps_number": w["wps_number"],
        "revision": w["revision"],
        "pqr_id": w["pqr_id"],
        "pinned_pqr_version": w["pinned_pqr_version"],
        "process": w["process"],
        "base_metal_spec": w["base_metal_spec"],
        "thickness_min_mm": w["thickness_min_mm"],
        "thickness_max_mm": w["thickness_max_mm"],
        "superseded_by_id": w["superseded_by_id"],
        "approved_by_user_id": w["approved_by_user_id"],
        "status": w["status"],
    })
    return out


def qualification_out(q):
    out = _common(q)
    out.update({
        "shop_id": q["shop_id"],
        "welder_id": q["welder_id"],
        "wps_id": q["wps_id"],
        "process": q["process"],
        "qualified_at_utc": format_logical(q["qualified_at_utc"]),
        "last_weld_at_utc": format_logical(q["last_weld_at_utc"]),
        "continuity_expires_at_utc": format_logical(q["continuity_expires_at_utc"]),
        "status": q["status"],
    })
    return out


def lot_out(lot):
    out = _common(lot)
    out.update({
        "shop_id": lot["shop_id"],
        "oven_id": lot["oven_id"],
        "lot_number": lot["lot_number"],
        "filler_spec": lot["filler_spec"],
        "process": lot["process"],
        "received_kg": kg_out(lot["received_kg"]),
        "remaining_kg": kg_out(lot["remaining_kg"]),
        "exposed_minutes_total": lot["exposed_minutes_total"],
        "rebake_count": lot["rebake_count"],
        "status": lot["status"],
    })
    return out


def issue_out(issue):
    out = _ledger(issue)
    # exposure: stored at return; while OPEN/VOID reckoned against the shop clock
    if issue["status"] == "RETURNED":
        exposure = issue["exposure_minutes"]
    else:
        shop = db.shops.get(issue["shop_id"])
        now = shop["current_utc"] if shop else issue["issued_at_utc"]
        exposure = max(0, int((now - issue["issued_at_utc"]).total_seconds() // 60))
    out.update({
        "shop_id": issue["shop_id"],
        "lot_id": issue["lot_id"],
        "oven_id": issue["oven_id"],
        "issued_to_welder_id": issue["issued_to_welder_id"],
        "issued_kg": kg_out(issue["issued_kg"]),
        "issued_at_utc": format_logical(issue["issued_at_utc"]),
        "returned_at_utc": format_logical(issue["returned_at_utc"]),
        "exposure_minutes": exposure,
        "status": issue["status"],
    })
    return out


def fixture_out(f):
    out = _common(f)
    out.update({
        "shop_id": f["shop_id"],
        "fixture_code": f["fixture_code"],
        "capacity_weldments": f["capacity_weldments"],
        "owner_party": f["owner_party"],
        "status": f["status"],
    })
    return out


def order_out(o):
    out = _common(o)
    out.update({
        "shop_id": o["shop_id"],
        "po_number": o["po_number"],
        "customer_name": o["customer_name"],
        "promised_ship_date_utc": format_logical(o["promised_ship_date_utc"]),
        "status": o["status"],
    })
    return out


def weldment_out(w):
    out = _common(w)
    out.update({
        "shop_id": w["shop_id"],
        "shop_order_id": w["shop_order_id"],
        "weldment_serial": w["weldment_serial"],
        "fixture_id": w["fixture_id"],
        "drawing_revision": w["drawing_revision"],
        "posture": w["posture"],
        "repair_pass_count": w["repair_pass_count"],
        "total_pass_count": w["total_pass_count"],
        "repair_rate_pct": pct_out(w["repair_rate_pct"]),
        "distortion_count": w["distortion_count"],
        "signed_off_at_utc": format_logical(w["signed_off_at_utc"]),
    })
    return out


def joint_out(j):
    out = _common(j)
    out.update({
        "shop_id": j["shop_id"],
        "weldment_id": j["weldment_id"],
        "joint_number": j["joint_number"],
        "wps_id": j["wps_id"],
        "base_metal_thickness_mm": j["base_metal_thickness_mm"],
        "required_ndt_methods": list(j["required_ndt_methods"]),
        "fabrication_status": j["fabrication_status"],
        "inspection_status": j["inspection_status"],
        "repair_cycle_count": j["repair_cycle_count"],
    })
    return out


def weld_pass_out(p):
    out = _ledger(p)
    out.update({
        "shop_id": p["shop_id"],
        "joint_id": p["joint_id"],
        "welder_id": p["welder_id"],
        "qualification_id": p["qualification_id"],
        "consumable_lot_id": p["consumable_lot_id"],
        "consumable_used_kg": kg_out(p["consumable_used_kg"]),
        "is_repair": p["is_repair"],
        "welded_at_utc": format_logical(p["welded_at_utc"]),
    })
    return out


def distortion_report_out(r):
    out = _ledger(r)
    out.update({
        "shop_id": r["shop_id"],
        "weldment_id": r["weldment_id"],
        "joint_id": r["joint_id"],
        "measured_deviation_mm": r["measured_deviation_mm"],
        "tolerance_mm": r["tolerance_mm"],
        "reported_by_user_id": r["reported_by_user_id"],
        "reported_at_utc": format_logical(r["reported_at_utc"]),
        "disposition": r["disposition"],
    })
    return out


def inspection_out(i):
    out = _ledger(i)
    out.update({
        "shop_id": i["shop_id"],
        "joint_id": i["joint_id"],
        "method": i["method"],
        "inspector_user_id": i["inspector_user_id"],
        "scheduled_start_utc": format_logical(i["scheduled_start_utc"]),
        "scheduled_end_utc": format_logical(i["scheduled_end_utc"]),
        "vendor_id": i["vendor_id"],
        "result": i["result"],
        "result_code": i["result_code"],
        "resulted_at_utc": format_logical(i["resulted_at_utc"]),
        "hold_point_released": i["hold_point_released"],
    })
    return out


def sign_off_out(s):
    out = _ledger(s)
    out.update({
        "shop_id": s["shop_id"],
        "weldment_id": s["weldment_id"],
        "step_code": s["step_code"],
        "signed_by_user_id": s["signed_by_user_id"],
        "signed_at_utc": format_logical(s["signed_at_utc"]),
        "notes": s["notes"],
    })
    return out
