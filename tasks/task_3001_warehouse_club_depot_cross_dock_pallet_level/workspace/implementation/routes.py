"""All /wcd route handlers, registered onto the Flask app.

Validation order per PRD §2.9: auth -> forbidden -> body shape -> field format ->
reference existence -> state -> business gates in scaffold priority order.
"""
import re
from datetime import date, timedelta

import db
import services
from helpers import (
    ApiError, bad_request, validation, not_found, invalid_state, safety_gate,
    dept_disabled, club_frozen, appt_conflict, cutoff_passed,
    constraint_violation, same_day_only, member_cap, club_capacity,
    markdown_rule, inactive_ref, referential_guard, stale_run, stale_item,
    new_entity, get_body, require_fields, is_string, is_int, is_number,
    check_hhmm, check_date_str, hhmm_to_minutes, parse_iso8601_utc,
    get_entity, touch, paginate, sort_created, now_ts, current_date,
    current_date_str, current_time_str,
)

REGION_CODE_RE = re.compile(r"^[A-Z]{2,4}$")
VENDOR_CODE_RE = re.compile(r"^V[0-9]{6}$")
SKU_RE = re.compile(r"^[0-9]{7}$")
MEMBERSHIP_RE = re.compile(r"^M[0-9]{9}$")

ALL_ROLES = ["RegionalOps", "CategoryManager", "DepotManager", "DepotPlanner",
             "MembershipDesk", "VendorRep"]


def _filters(args, allowed):
    """Build a filter function from query params. Unknown/None filters pass."""
    def fn(e):
        for key in allowed:
            v = args.get(key)
            if v is None:
                continue
            if str(e.get(key)) != v:
                return False
        return True
    return fn


def _list(store_name, args, allowed_filters, base_filter=None):
    from flask import request
    items = list(db.stores[store_name].values())
    if base_filter is not None:
        items = [e for e in items if base_filter(e)]
    fn = _filters(args, allowed_filters)
    items = [e for e in items if fn(e)]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, meta


# ================================================================ regions
def create_region(user):
    body = get_body()
    require_fields(body, ["name", "code", "avg_member_income_cents"])
    if not is_string(body["name"]):
        raise validation("name must be a string")
    if not is_string(body["code"]) or not REGION_CODE_RE.match(body["code"]):
        raise validation("code must match ^[A-Z]{2,4}$")
    if not is_int(body["avg_member_income_cents"]) or body["avg_member_income_cents"] < 0:
        raise validation("avg_member_income_cents must be an integer >= 0")
    for r in db.stores["regions"].values():
        if r["code"] == body["code"]:
            raise constraint_violation("region code already exists: %s" % body["code"])
    region = new_entity({
        "name": body["name"],
        "code": body["code"],
        "avg_member_income_cents": body["avg_member_income_cents"],
    })
    db.stores["regions"][region["id"]] = region
    return region, 201


def list_regions(user):
    from flask import request
    page, meta = _list("regions", request.args, ["code"])
    return page, 200, meta


def get_region(user, region_id):
    return get_entity("regions", region_id, "region"), 200


# ================================================================ vendors
def create_vendor(user):
    body = get_body()
    require_fields(body, ["name", "vendor_code"])
    if not is_string(body["name"]):
        raise validation("name must be a string")
    if not is_string(body["vendor_code"]) or not VENDOR_CODE_RE.match(body["vendor_code"]):
        raise validation("vendor_code must match ^V[0-9]{6}$")
    for v in db.stores["vendors"].values():
        if v["vendor_code"] == body["vendor_code"]:
            raise constraint_violation("vendor_code already exists: %s" % body["vendor_code"])
    vendor = new_entity({
        "name": body["name"],
        "vendor_code": body["vendor_code"],
        "status": "ACTIVE",
        "compliance_score_bp": 10000,
        "total_chargeback_cents": 0,
    })
    db.stores["vendors"][vendor["id"]] = vendor
    return vendor, 201


def list_vendors(user):
    from flask import request
    page, meta = _list("vendors", request.args, ["status"])
    return page, 200, meta


def get_vendor(user, vendor_id):
    return get_entity("vendors", vendor_id, "vendor"), 200


def list_vendor_appointments(user, vendor_id):
    from flask import request
    vendor = get_entity("vendors", vendor_id, "vendor")
    page, meta = _list("appointments", request.args, ["status", "delivery_date"],
                       base_filter=lambda a: a["vendor_id"] == vendor["id"])
    return page, 200, meta


def reinstate_vendor(user, vendor_id):
    vendor = get_entity("vendors", vendor_id, "vendor")
    if vendor["status"] != "SUSPENDED":
        raise invalid_state("vendor is not SUSPENDED")
    vendor["status"] = "ACTIVE"
    touch(vendor)
    return vendor, 200


def deactivate_vendor(user, vendor_id):
    vendor = get_entity("vendors", vendor_id, "vendor")
    if vendor["status"] != "SUSPENDED":
        raise invalid_state("vendor is not SUSPENDED")
    for a in db.stores["appointments"].values():
        if a["vendor_id"] == vendor["id"] and a["status"] in ("BOOKED", "CHECKED_IN"):
            raise referential_guard("vendor has open appointments")
    vendor["status"] = "DEACTIVATED"
    touch(vendor)
    return vendor, 200


# ================================================================ clubs
def create_club(user):
    body = get_body()
    require_fields(body, ["region_id", "name", "club_number", "floor_slot_capacity", "member_base"])
    if not is_string(body["region_id"]):
        raise validation("region_id must be a string")
    if not is_string(body["name"]):
        raise validation("name must be a string")
    if not is_int(body["club_number"]) or body["club_number"] <= 0:
        raise validation("club_number must be a positive integer")
    if not is_int(body["floor_slot_capacity"]) or body["floor_slot_capacity"] < 1:
        raise validation("floor_slot_capacity must be an integer >= 1")
    if not is_int(body["member_base"]) or body["member_base"] < 0:
        raise validation("member_base must be an integer >= 0")
    flags = body.get("ancillary_flags")
    if flags is None:
        flags = {"gas": False, "pharmacy": False, "optical": False}
    else:
        if not isinstance(flags, dict):
            raise validation("ancillary_flags must be an object")
        flags = {
            "gas": bool(flags.get("gas", False)),
            "pharmacy": bool(flags.get("pharmacy", False)),
            "optical": bool(flags.get("optical", False)),
        }
    get_entity("regions", body["region_id"], "region")
    for c in db.stores["clubs"].values():
        if c["club_number"] == body["club_number"]:
            raise constraint_violation("club_number already exists: %s" % body["club_number"])
    club = new_entity({
        "region_id": body["region_id"],
        "name": body["name"],
        "club_number": body["club_number"],
        "floor_slot_capacity": body["floor_slot_capacity"],
        "member_base": body["member_base"],
        "posture": "NORMAL",
        "allocated_slot_count": 0,
        "ancillary_flags": flags,
    })
    db.stores["clubs"][club["id"]] = club
    return club, 201


def list_clubs(user):
    from flask import request
    page, meta = _list("clubs", request.args, ["region_id", "posture"])
    return page, 200, meta


def get_club(user, club_id):
    return get_entity("clubs", club_id, "club"), 200


def list_club_members(user, club_id):
    from flask import request
    club = get_entity("clubs", club_id, "club")
    page, meta = _list("members", request.args, ["status"],
                       base_filter=lambda m: m["club_id"] == club["id"])
    return page, 200, meta


def list_club_allocations(user, club_id):
    from flask import request
    club = get_entity("clubs", club_id, "club")
    page, meta = _list("allocations", request.args, ["status"],
                       base_filter=lambda a: a["club_id"] == club["id"])
    return page, 200, meta


def list_club_department_sales(user, club_id):
    from flask import request
    club = get_entity("clubs", club_id, "club")
    page, meta = _list("department_sales", request.args, ["department", "sold_on"],
                       base_filter=lambda s: s["club_id"] == club["id"])
    return page, 200, meta


def list_club_purchases(user, club_id):
    from flask import request
    club = get_entity("clubs", club_id, "club")
    page, meta = _list("purchases", request.args, ["status", "cap_window"],
                       base_filter=lambda p: p["club_id"] == club["id"])
    return page, 200, meta


# ================================================================ items
def create_item(user):
    body = get_body()
    require_fields(body, ["vendor_id", "sku", "description", "case_pack_qty",
                          "pallet_length_in", "pallet_width_in", "cases_per_layer",
                          "max_layers", "item_type"])
    if not is_string(body["vendor_id"]):
        raise validation("vendor_id must be a string")
    if not is_string(body["sku"]) or not SKU_RE.match(body["sku"]):
        raise validation("sku must match ^[0-9]{7}$")
    if not is_string(body["description"]):
        raise validation("description must be a string")
    for f in ("case_pack_qty", "cases_per_layer", "max_layers"):
        if not is_int(body[f]) or body[f] < 1:
            raise validation("%s must be an integer >= 1" % f)
    for f in ("pallet_length_in", "pallet_width_in"):
        if not is_number(body[f]) or body[f] <= 0:
            raise validation("%s must be a number > 0" % f)
    if body["item_type"] not in ("REGULAR", "TREASURE_HUNT"):
        raise validation("item_type must be REGULAR or TREASURE_HUNT")
    cap = body.get("member_purchase_cap", 0)
    if not is_int(cap) or cap < 0:
        raise validation("member_purchase_cap must be an integer >= 0")
    target = body.get("sell_through_target_pct", 80)
    if not is_int(target) or target <= 0 or target > 100:
        raise validation("sell_through_target_pct must be an integer in (0, 100]")
    exit_window = body.get("exit_window_date")
    if body["item_type"] == "TREASURE_HUNT":
        if exit_window is None:
            raise validation("exit_window_date is required for TREASURE_HUNT items")
        check_date_str(exit_window, "exit_window_date")
    else:
        if exit_window is not None:
            check_date_str(exit_window, "exit_window_date")
    get_entity("vendors", body["vendor_id"], "vendor")
    for i in db.stores["items"].values():
        if i["sku"] == body["sku"]:
            raise constraint_violation("sku already exists: %s" % body["sku"])
    item = new_entity({
        "vendor_id": body["vendor_id"],
        "sku": body["sku"],
        "description": body["description"],
        "case_pack_qty": body["case_pack_qty"],
        "pallet_length_in": body["pallet_length_in"],
        "pallet_width_in": body["pallet_width_in"],
        "cases_per_layer": body["cases_per_layer"],
        "max_layers": body["max_layers"],
        "item_type": body["item_type"],
        "status": "DRAFT",
        "member_purchase_cap": cap,
        "sell_through_target_pct": target,
        "exit_window_date": exit_window,
        "complaint_weighted_score": 0,
        "complaint_count": 0,
    })
    services.compute_pallet_fields(item)
    db.stores["items"][item["id"]] = item
    return item, 201


def list_items(user):
    from flask import request
    page, meta = _list("items", request.args, ["status", "item_type", "vendor_id"])
    return page, 200, meta


def get_item(user, item_id):
    return get_entity("items", item_id, "item"), 200


def activate_item(user, item_id):
    item = get_entity("items", item_id, "item")
    if item["status"] != "DRAFT":
        raise invalid_state("item is not DRAFT")
    if not (item["case_pack_qty"] >= 1 and item["cases_per_layer"] >= 1 and item["max_layers"] >= 1):
        raise invalid_state("item pallet design fields must each be >= 1")
    services.compute_pallet_fields(item)
    item["status"] = "ACTIVE"
    touch(item)
    return item, 200


def request_deletion(user, item_id):
    item = get_entity("items", item_id, "item")
    body = get_body()
    decision = body.get("decision")
    if decision is None:
        if item["status"] != "ACTIVE":
            raise invalid_state("opening deletion review requires ACTIVE item")
        services.recompute_item_complaints(item)
        item["status"] = "DELETION_REVIEW"
        touch(item)
        return item, 200
    if not is_string(decision) or decision not in ("APPROVE", "REJECT"):
        raise validation("decision must be APPROVE or REJECT")
    if item["status"] != "DELETION_REVIEW":
        raise invalid_state("resolving deletion review requires DELETION_REVIEW item")
    if decision == "REJECT":
        item["status"] = "ACTIVE"
        touch(item)
        return item, 200
    # APPROVE
    if item["complaint_weighted_score"] < services.COMPLAINT_DISCONTINUE_THRESHOLD:
        raise referential_guard("complaint_weighted_score below discontinue threshold")
    item["status"] = "DISCONTINUED"
    touch(item)
    services.discontinue_item_cascade(item)
    return item, 200


def discontinue_item(user, item_id):
    item = get_entity("items", item_id, "item")
    if item["status"] != "ACTIVE":
        raise invalid_state("direct discontinue requires ACTIVE item")
    if item["item_type"] != "TREASURE_HUNT":
        raise invalid_state("direct discontinue is only for TREASURE_HUNT items")
    if not services.has_markdown_decision(item["id"]):
        raise referential_guard("no MARKDOWN decision exists for this item")
    item["status"] = "DISCONTINUED"
    touch(item)
    services.discontinue_item_cascade(item)
    return item, 200


def list_markdown_decisions(user, item_id):
    from flask import request
    item = get_entity("items", item_id, "item")
    page, meta = _list("markdown_decisions", request.args, [],
                       base_filter=lambda d: d["item_id"] == item["id"])
    return page, 200, meta


def create_markdown_decision(user, item_id):
    item = get_entity("items", item_id, "item")
    body = get_body()
    require_fields(body, ["decision", "expected_item_version"])
    if not is_string(body["decision"]) or body["decision"] not in ("SELL_THROUGH", "MARKDOWN"):
        raise validation("decision must be SELL_THROUGH or MARKDOWN")
    if not is_int(body["expected_item_version"]):
        raise validation("expected_item_version must be an integer")
    md_pct = body.get("markdown_pct")
    if body["decision"] == "MARKDOWN":
        if md_pct is None:
            raise markdown_rule("markdown_pct is required when decision is MARKDOWN")
        if not is_int(md_pct) or md_pct <= 0 or md_pct >= 100:
            raise markdown_rule("markdown_pct must be an integer in (0, 100)")
    else:
        if md_pct is not None:
            raise markdown_rule("markdown_pct must be omitted unless decision is MARKDOWN")
    note = body.get("note", "")
    if not is_string(note):
        raise validation("note must be a string")
    # OCC
    if body["expected_item_version"] != item["version"]:
        raise stale_item("expected_item_version does not match the item's current version")
    sell_through = services.compute_sell_through_pct(item["id"])
    # mandatory markdown rule
    exit_date = item.get("exit_window_date")
    if (body["decision"] == "SELL_THROUGH" and exit_date is not None
            and current_date_str() >= exit_date
            and sell_through < item["sell_through_target_pct"]):
        raise markdown_rule("SELL_THROUGH rejected at/after exit window below target")
    decision = new_entity({
        "item_id": item["id"],
        "decision": body["decision"],
        "markdown_pct": md_pct,
        "note": note,
        "sell_through_pct": sell_through,
        "decided_by_role": user["role"],
        "decided_at": now_ts(),
    })
    db.stores["markdown_decisions"][decision["id"]] = decision
    touch(item)
    return decision, 201


def list_item_complaints(user, item_id):
    from flask import request
    item = get_entity("items", item_id, "item")
    page, meta = _list("complaints", request.args, ["status", "category"],
                       base_filter=lambda c: c["item_id"] == item["id"])
    return page, 200, meta


# ================================================================ depots
def create_depot(user):
    body = get_body()
    require_fields(body, ["region_id", "name", "dock_count", "dock_hours_open",
                          "dock_hours_close", "slot_length_minutes"])
    if not is_string(body["region_id"]):
        raise validation("region_id must be a string")
    if not is_string(body["name"]):
        raise validation("name must be a string")
    if not is_int(body["dock_count"]) or body["dock_count"] < 1:
        raise validation("dock_count must be an integer >= 1")
    check_hhmm(body["dock_hours_open"], "dock_hours_open")
    check_hhmm(body["dock_hours_close"], "dock_hours_close")
    if not is_int(body["slot_length_minutes"]) or body["slot_length_minutes"] < 15 or 60 % body["slot_length_minutes"] != 0:
        raise validation("slot_length_minutes must divide 60 and be >= 15")
    if hhmm_to_minutes(body["dock_hours_close"]) <= hhmm_to_minutes(body["dock_hours_open"]):
        raise validation("dock_hours_close must be after dock_hours_open")
    get_entity("regions", body["region_id"], "region")
    depot = new_entity({
        "region_id": body["region_id"],
        "name": body["name"],
        "dock_count": body["dock_count"],
        "dock_hours_open": body["dock_hours_open"],
        "dock_hours_close": body["dock_hours_close"],
        "slot_length_minutes": body["slot_length_minutes"],
    })
    db.stores["depots"][depot["id"]] = depot
    return depot, 201


def list_depots(user):
    from flask import request
    page, meta = _list("depots", request.args, ["region_id"])
    return page, 200, meta


def get_depot(user, depot_id):
    return get_entity("depots", depot_id, "depot"), 200


def list_depot_appointments(user, depot_id):
    from flask import request
    depot = get_entity("depots", depot_id, "depot")
    page, meta = _list("appointments", request.args, ["delivery_date", "status", "vendor_id"],
                       base_filter=lambda a: a["depot_id"] == depot["id"])
    return page, 200, meta


def list_depot_runs(user, depot_id):
    from flask import request
    depot = get_entity("depots", depot_id, "depot")
    page, meta = _list("runs", request.args, ["run_date", "status"],
                       base_filter=lambda r: r["depot_id"] == depot["id"])
    return page, 200, meta


# ================================================================ appointments
def _window_overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection."""
    return a_start < b_end and b_start < a_end


def create_appointment(user):
    body = get_body()
    require_fields(body, ["depot_id", "vendor_id", "delivery_date", "start_time",
                          "end_time", "pallet_count"])
    if not is_string(body["depot_id"]):
        raise validation("depot_id must be a string")
    if not is_string(body["vendor_id"]):
        raise validation("vendor_id must be a string")
    check_date_str(body["delivery_date"], "delivery_date")
    check_hhmm(body["start_time"], "start_time")
    check_hhmm(body["end_time"], "end_time")
    if not is_int(body["pallet_count"]) or body["pallet_count"] < 1:
        raise validation("pallet_count must be an integer >= 1")
    # existence (body FKs left-to-right)
    depot = get_entity("depots", body["depot_id"], "depot")
    vendor = get_entity("vendors", body["vendor_id"], "vendor")
    # VendorRep entity-backed identity check
    if user["role"] == "VendorRep" and user["user_id"] != vendor["id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "VendorRep may only book for their own vendor")
    # appointment window checks -> ERR_APPOINTMENT_CONFLICT
    open_min = hhmm_to_minutes(depot["dock_hours_open"])
    close_min = hhmm_to_minutes(depot["dock_hours_close"])
    start_min = hhmm_to_minutes(body["start_time"])
    end_min = hhmm_to_minutes(body["end_time"])
    slot = depot["slot_length_minutes"]
    if start_min >= end_min:
        raise appt_conflict("end_time must be after start_time")
    if start_min < open_min or end_min > close_min:
        raise appt_conflict("window outside depot dock hours")
    if (start_min - open_min) % slot != 0 or (end_min - open_min) % slot != 0:
        raise appt_conflict("window misaligned to depot slot grid")
    if body["delivery_date"] < current_date_str():
        raise validation("delivery_date must be on or after the current logical date")
    if vendor["status"] != "ACTIVE":
        raise inactive_ref("vendor is not ACTIVE")
    # dock door assignment: lowest-numbered free door
    assigned = None
    for door in range(1, depot["dock_count"] + 1):
        conflict = False
        for a in db.stores["appointments"].values():
            if a["depot_id"] != depot["id"] or a.get("dock_door") != door:
                continue
            if a["status"] in ("CANCELLED", "NO_SHOW"):
                continue
            if a["delivery_date"] != body["delivery_date"]:
                continue
            if _window_overlaps(start_min, end_min,
                                hhmm_to_minutes(a["start_time"]), hhmm_to_minutes(a["end_time"])):
                conflict = True
                break
        if not conflict:
            assigned = door
            break
    if assigned is None:
        raise appt_conflict("no dock door free for the requested window")
    appt = new_entity({
        "depot_id": depot["id"],
        "vendor_id": vendor["id"],
        "delivery_date": body["delivery_date"],
        "start_time": body["start_time"],
        "end_time": body["end_time"],
        "pallet_count": body["pallet_count"],
        "status": "BOOKED",
        "checked_in_at": None,
        "unload_fee_cents": 0,
        "chargeback_cents": 0,
        "dock_door": assigned,
    })
    db.stores["appointments"][appt["id"]] = appt
    return appt, 201


def get_appointment(user, appt_id):
    return get_entity("appointments", appt_id, "appointment"), 200


def check_in_appointment(user, appt_id):
    appt = get_entity("appointments", appt_id, "appointment")
    if appt["status"] != "BOOKED":
        raise invalid_state("only BOOKED appointments can check in")
    if current_date_str() != appt["delivery_date"]:
        raise appt_conflict("check-in is only allowed on the delivery date")
    if current_time_str() > appt["end_time"]:
        raise appt_conflict("check-in after window end_time")
    appt["checked_in_at"] = now_ts()
    appt["status"] = "CHECKED_IN"
    touch(appt)
    # late check-in chargeback
    start_min = hhmm_to_minutes(appt["start_time"])
    now_min = hhmm_to_minutes(current_time_str())
    if now_min > start_min + services.LATE_GRACE_MINUTES:
        amount = services.compute_chargeback_amount("LATE_CHECKIN", appt, 0)
        services.create_chargeback(appt["vendor_id"], appt["id"], "LATE_CHECKIN", amount)
        appt["chargeback_cents"] += amount
        touch(appt)
    return appt, 200


def complete_appointment(user, appt_id):
    appt = get_entity("appointments", appt_id, "appointment")
    if appt["status"] != "CHECKED_IN":
        raise invalid_state("only CHECKED_IN appointments can be completed")
    received = [p for p in db.stores["pallets"].values() if p["appointment_id"] == appt["id"]]
    if len(received) != appt["pallet_count"]:
        raise invalid_state("received pallet count does not equal booked pallet_count")
    appt["unload_fee_cents"] = services.compute_unload_fee(appt["pallet_count"])
    if len(received) > appt["pallet_count"]:
        amount = services.compute_chargeback_amount("OVER_PALLET_COUNT", appt, len(received))
        services.create_chargeback(appt["vendor_id"], appt["id"], "OVER_PALLET_COUNT", amount)
        appt["chargeback_cents"] += amount
    appt["status"] = "COMPLETED"
    touch(appt)
    return appt, 200


def cancel_appointment(user, appt_id):
    appt = get_entity("appointments", appt_id, "appointment")
    if user["role"] == "VendorRep" and user["user_id"] != appt["vendor_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "VendorRep may only cancel their own vendor's appointments")
    if appt["status"] != "BOOKED":
        raise invalid_state("only BOOKED appointments can be cancelled")
    window_start = "%s %s" % (appt["delivery_date"], appt["start_time"])
    now_str = "%s %s" % (current_date_str(), current_time_str())
    if now_str >= window_start:
        raise appt_conflict("appointment window has already started")
    appt["status"] = "CANCELLED"
    touch(appt)
    return appt, 200


def list_appointment_pallets(user, appt_id):
    from flask import request
    appt = get_entity("appointments", appt_id, "appointment")
    page, meta = _list("pallets", request.args, ["status"],
                       base_filter=lambda p: p["appointment_id"] == appt["id"])
    return page, 200, meta


# ================================================================ pallets
def create_pallet(user):
    body = get_body()
    require_fields(body, ["appointment_id", "item_id", "unit_qty"])
    if not is_string(body["appointment_id"]):
        raise validation("appointment_id must be a string")
    if not is_string(body["item_id"]):
        raise validation("item_id must be a string")
    if not is_int(body["unit_qty"]) or body["unit_qty"] < 1:
        raise validation("unit_qty must be an integer >= 1")
    appt = get_entity("appointments", body["appointment_id"], "appointment")
    item = get_entity("items", body["item_id"], "item")
    if appt["status"] != "CHECKED_IN":
        raise invalid_state("pallets may only be received under a CHECKED_IN appointment")
    if body["unit_qty"] != item["pallet_qty_units"]:
        raise constraint_violation("unit_qty must equal item.pallet_qty_units")
    if services.has_markdown_decision(item["id"]):
        raise markdown_rule("treasure-hunt reorder rejected: MARKDOWN decision exists for item")
    vendor = db.stores["vendors"][appt["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise inactive_ref("vendor is not ACTIVE")
    if item["status"] != "ACTIVE":
        raise inactive_ref("item is not ACTIVE")
    pallet = new_entity({
        "appointment_id": appt["id"],
        "item_id": item["id"],
        "unit_qty": body["unit_qty"],
        "received_at": now_ts(),
        "received_date": current_date_str(),
        "status": "RECEIVED",
    })
    db.stores["pallets"][pallet["id"]] = pallet
    return pallet, 201


def list_pallets(user):
    from flask import request
    page, meta = _list("pallets", request.args, ["status", "item_id", "appointment_id", "received_date"])
    return page, 200, meta


def get_pallet(user, pallet_id):
    return get_entity("pallets", pallet_id, "pallet"), 200


def reconcile_pallet(user, pallet_id):
    pallet = get_entity("pallets", pallet_id, "pallet")
    if pallet["status"] != "STRANDED":
        raise invalid_state("only STRANDED pallets can be reconciled")
    pallet["status"] = "RECONCILED"
    touch(pallet)
    return pallet, 200


# ================================================================ cross-dock runs & allocations
def create_run(user):
    body = get_body()
    require_fields(body, ["depot_id", "run_date", "cutoff_time"])
    if not is_string(body["depot_id"]):
        raise validation("depot_id must be a string")
    check_date_str(body["run_date"], "run_date")
    check_hhmm(body["cutoff_time"], "cutoff_time")
    get_entity("depots", body["depot_id"], "depot")
    run = new_entity({
        "depot_id": body["depot_id"],
        "run_date": body["run_date"],
        "cutoff_time": body["cutoff_time"],
        "status": "OPEN",
        "committed_at": None,
    })
    db.stores["runs"][run["id"]] = run
    return run, 201


def get_run(user, run_id):
    return get_entity("runs", run_id, "cross-dock run"), 200


def create_allocation(user, run_id):
    run = get_entity("runs", run_id, "cross-dock run")
    body = get_body()
    require_fields(body, ["pallet_id", "club_id", "expected_cross_dock_run_version"])
    if not is_string(body["pallet_id"]):
        raise validation("pallet_id must be a string")
    if not is_string(body["club_id"]):
        raise validation("club_id must be a string")
    if not is_int(body["expected_cross_dock_run_version"]):
        raise validation("expected_cross_dock_run_version must be an integer")
    regional_ops_approved = body.get("regional_ops_approved", False)
    if not isinstance(regional_ops_approved, bool):
        raise validation("regional_ops_approved must be a boolean")
    # existence
    pallet = get_entity("pallets", body["pallet_id"], "pallet")
    club = get_entity("clubs", body["club_id"], "club")
    # state
    if run["status"] != "OPEN":
        raise invalid_state("cross-dock run is not OPEN")
    if pallet["status"] != "RECEIVED":
        raise invalid_state("pallet is not RECEIVED")
    # OCC
    if body["expected_cross_dock_run_version"] != run["version"]:
        raise stale_run("expected_cross_dock_run_version does not match the run's current version")
    # safety gates: CONSTRAINED requires approval; FROZEN rejected outright
    if club["posture"] == "CONSTRAINED" and not regional_ops_approved:
        raise safety_gate("allocation to a CONSTRAINED club requires regional_ops_approved")
    if club["posture"] == "FROZEN":
        raise club_frozen("destination club is FROZEN")
    # cutoff (equality allowed); only evaluated on the run date
    if current_date_str() == run["run_date"] and current_time_str() > run["cutoff_time"]:
        raise cutoff_passed("run cutoff_time has passed")
    # same-day cross-dock
    if pallet["received_date"] != run["run_date"]:
        raise same_day_only("pallet.received_date must equal run.run_date")
    # capacity
    item = db.stores["items"][pallet["item_id"]]
    slots = item["pallets_per_slot"]
    if club["allocated_slot_count"] + slots > club["floor_slot_capacity"]:
        raise club_capacity("allocation would exceed club floor slot capacity")
    score = services.compute_allocation_score(club, item, run["run_date"])
    run["version"] += 1
    run["updated_at"] = now_ts()
    allocation = new_entity({
        "cross_dock_run_id": run["id"],
        "pallet_id": pallet["id"],
        "club_id": club["id"],
        "allocation_score": score,
        "floor_slots_reserved": slots,
        "run_version": run["version"],
        "status": "PROPOSED",
        "void_reason": "",
    })
    db.stores["allocations"][allocation["id"]] = allocation
    pallet["status"] = "ALLOCATED"
    touch(pallet)
    club["allocated_slot_count"] += slots
    services.recompute_club_posture(club)
    touch(club)
    return allocation, 201


def list_run_allocations(user, run_id):
    from flask import request
    run = get_entity("runs", run_id, "cross-dock run")
    page, meta = _list("allocations", request.args, ["status", "club_id"],
                       base_filter=lambda a: a["cross_dock_run_id"] == run["id"])
    return page, 200, meta


def list_allocations(user):
    from flask import request
    page, meta = _list("allocations", request.args,
                       ["status", "pallet_id", "club_id", "cross_dock_run_id"])
    return page, 200, meta


def get_allocation(user, allocation_id):
    return get_entity("allocations", allocation_id, "allocation"), 200


def void_allocation(user, allocation_id):
    allocation = get_entity("allocations", allocation_id, "allocation")
    body = get_body()
    reason = body.get("void_reason", "")
    if reason is None:
        reason = ""
    if not is_string(reason):
        raise validation("void_reason must be a string")
    if allocation["status"] != "PROPOSED":
        raise invalid_state("only PROPOSED allocations can be voided")
    services.void_allocation(allocation, reason, strand_pallet=False, bump_run=True)
    return allocation, 200


def commit_run(user, run_id):
    run = get_entity("runs", run_id, "cross-dock run")
    if run["status"] != "OPEN":
        raise invalid_state("cross-dock run is not OPEN")
    if current_date_str() == run["run_date"] and current_time_str() > run["cutoff_time"]:
        raise cutoff_passed("run cutoff_time has passed")
    proposed = [a for a in db.stores["allocations"].values()
                if a["cross_dock_run_id"] == run["id"] and a["status"] == "PROPOSED"]
    # phase 1 preflight: frozen-club gate fails the whole commit atomically
    for a in proposed:
        club = db.stores["clubs"][a["club_id"]]
        if club["posture"] == "FROZEN":
            raise club_frozen("a destination club is FROZEN; commit aborted")
    # phase 1: PROPOSED -> COMMITTED
    for a in proposed:
        a["status"] = "COMMITTED"
        touch(a)
    # phase 2: COMMITTED -> SHIPPED in allocation_score DESC, created_at ASC
    ordered = sort_created(proposed)
    ordered.sort(key=lambda a: -a["allocation_score"])
    touched_clubs = {}
    for a in ordered:
        a["status"] = "SHIPPED"
        touch(a)
        pallet = db.stores["pallets"][a["pallet_id"]]
        pallet["status"] = "SHIPPED"
        touch(pallet)
        # allocated_slot_count sums only PROPOSED/COMMITTED allocations, so a
        # shipped allocation releases its reserved slots at the destination club.
        club = db.stores["clubs"][a["club_id"]]
        club["allocated_slot_count"] -= a["floor_slots_reserved"]
        touched_clubs[club["id"]] = club
    for club in touched_clubs.values():
        services.recompute_club_posture(club)
        touch(club)
    run["status"] = "COMMITTED"
    run["committed_at"] = now_ts()
    touch(run)
    return run, 200


def cancel_run(user, run_id):
    run = get_entity("runs", run_id, "cross-dock run")
    if run["status"] != "OPEN":
        raise invalid_state("cross-dock run is not OPEN")
    proposed = [a for a in db.stores["allocations"].values()
                if a["cross_dock_run_id"] == run["id"] and a["status"] == "PROPOSED"]
    for a in sort_created(proposed):
        services.void_allocation(a, "RUN_CANCELLED", strand_pallet=False, bump_run=False)
    run["status"] = "CANCELLED"
    touch(run)
    return run, 200


# ================================================================ members
def create_member(user):
    body = get_body()
    require_fields(body, ["club_id", "membership_number", "tier"])
    if not is_string(body["club_id"]):
        raise validation("club_id must be a string")
    if not is_string(body["membership_number"]) or not MEMBERSHIP_RE.match(body["membership_number"]):
        raise validation("membership_number must match ^M[0-9]{9}$")
    if body["tier"] not in ("GOLD_STAR", "EXECUTIVE"):
        raise validation("tier must be GOLD_STAR or EXECUTIVE")
    household = body.get("household_size", 1)
    if not is_int(household) or household < 1:
        raise validation("household_size must be an integer >= 1")
    get_entity("clubs", body["club_id"], "club")
    for m in db.stores["members"].values():
        if m["membership_number"] == body["membership_number"]:
            raise constraint_violation("membership_number already exists: %s" % body["membership_number"])
    member = new_entity({
        "club_id": body["club_id"],
        "membership_number": body["membership_number"],
        "tier": body["tier"],
        "household_size": household,
        "status": "ACTIVE",
    })
    db.stores["members"][member["id"]] = member
    return member, 201


def list_members(user):
    from flask import request
    page, meta = _list("members", request.args, ["club_id", "status", "tier"])
    return page, 200, meta


def get_member(user, member_id):
    return get_entity("members", member_id, "member"), 200


def suspend_member(user, member_id):
    member = get_entity("members", member_id, "member")
    if member["status"] != "ACTIVE":
        raise invalid_state("only ACTIVE members can be suspended")
    member["status"] = "SUSPENDED"
    touch(member)
    return member, 200


def list_member_purchases(user, member_id):
    from flask import request
    member = get_entity("members", member_id, "member")
    page, meta = _list("purchases", request.args, ["item_id", "cap_window", "status"],
                       base_filter=lambda p: p["member_id"] == member["id"])
    return page, 200, meta


def list_member_complaints(user, member_id):
    from flask import request
    member = get_entity("members", member_id, "member")
    page, meta = _list("complaints", request.args, ["status", "item_id"],
                       base_filter=lambda c: c["member_id"] == member["id"])
    return page, 200, meta


def list_member_department_sales(user, member_id):
    from flask import request
    member = get_entity("members", member_id, "member")
    page, meta = _list("department_sales", request.args, ["department"],
                       base_filter=lambda s: s["member_id"] == member["id"])
    return page, 200, meta


# ================================================================ purchases
def create_purchase(user):
    body = get_body()
    require_fields(body, ["member_id", "club_id", "item_id", "unit_qty"])
    if not is_string(body["member_id"]):
        raise validation("member_id must be a string")
    if not is_string(body["club_id"]):
        raise validation("club_id must be a string")
    if not is_string(body["item_id"]):
        raise validation("item_id must be a string")
    if not is_int(body["unit_qty"]) or body["unit_qty"] < 1:
        raise validation("unit_qty must be an integer >= 1")
    member = get_entity("members", body["member_id"], "member")
    club = get_entity("clubs", body["club_id"], "club")
    item = get_entity("items", body["item_id"], "item")
    if member["status"] != "ACTIVE":
        raise safety_gate("suspended member cannot purchase")
    if item["status"] != "ACTIVE":
        raise inactive_ref("item is not ACTIVE")
    if item["member_purchase_cap"] > 0:
        window = current_date_str()
        used = sum(p["unit_qty"] for p in db.stores["purchases"].values()
                   if p["member_id"] == member["id"] and p["item_id"] == item["id"]
                   and p["cap_window"] == window and p["status"] == "COMPLETED")
        if used + body["unit_qty"] > item["member_purchase_cap"]:
            raise member_cap("per-membership purchase cap would be exceeded")
    purchase = new_entity({
        "member_id": member["id"],
        "club_id": club["id"],
        "item_id": item["id"],
        "unit_qty": body["unit_qty"],
        "purchased_at": now_ts(),
        "cap_window": current_date_str(),
        "status": "COMPLETED",
    })
    db.stores["purchases"][purchase["id"]] = purchase
    return purchase, 201


def list_purchases(user):
    from flask import request
    page, meta = _list("purchases", request.args,
                       ["member_id", "club_id", "item_id", "cap_window", "status"])
    return page, 200, meta


def get_purchase(user, purchase_id):
    return get_entity("purchases", purchase_id, "purchase"), 200


def refund_purchase(user, purchase_id):
    purchase = get_entity("purchases", purchase_id, "purchase")
    if purchase["status"] != "COMPLETED":
        raise invalid_state("only COMPLETED purchases can be refunded")
    purchase["status"] = "REFUNDED"
    touch(purchase)
    return purchase, 200


# ================================================================ complaints
def create_complaint(user):
    body = get_body()
    require_fields(body, ["member_id", "item_id", "category"])
    if not is_string(body["member_id"]):
        raise validation("member_id must be a string")
    if not is_string(body["item_id"]):
        raise validation("item_id must be a string")
    if body["category"] not in ("QUALITY", "AVAILABILITY", "PRICING", "SAFETY"):
        raise validation("category must be one of QUALITY, AVAILABILITY, PRICING, SAFETY")
    member = get_entity("members", body["member_id"], "member")
    item = get_entity("items", body["item_id"], "item")
    if member["status"] != "ACTIVE":
        raise safety_gate("suspended member cannot file complaints")
    weight = services.WEIGHT_BY_CATEGORY[body["category"]] * member["household_size"]
    complaint = new_entity({
        "member_id": member["id"],
        "item_id": item["id"],
        "category": body["category"],
        "created_on": current_date_str(),
        "weight": weight,
        "status": "OPEN",
    })
    db.stores["complaints"][complaint["id"]] = complaint
    services.recompute_item_complaints(item)
    touch(item)
    return complaint, 201


def get_complaint(user, complaint_id):
    return get_entity("complaints", complaint_id, "complaint"), 200


def resolve_complaint(user, complaint_id):
    complaint = get_entity("complaints", complaint_id, "complaint")
    if complaint["status"] != "OPEN":
        raise invalid_state("only OPEN complaints can be resolved")
    complaint["status"] = "RESOLVED"
    touch(complaint)
    item = db.stores["items"][complaint["item_id"]]
    services.recompute_item_complaints(item)
    touch(item)
    return complaint, 200


# ================================================================ chargebacks
def list_chargebacks(user):
    from flask import request
    page, meta = _list("chargebacks", request.args,
                       ["vendor_id", "appointment_id", "status", "reason"])
    return page, 200, meta


def get_chargeback(user, chargeback_id):
    return get_entity("chargebacks", chargeback_id, "chargeback"), 200


def appeal_chargeback(user, chargeback_id):
    cb = get_entity("chargebacks", chargeback_id, "chargeback")
    if user["role"] == "VendorRep" and user["user_id"] != cb["vendor_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "VendorRep may only appeal their own vendor's chargebacks")
    if cb["status"] != "ASSESSED":
        raise invalid_state("only ASSESSED chargebacks can be appealed")
    cb["status"] = "APPEALED"
    touch(cb)
    return cb, 200


def resolve_chargeback(user, chargeback_id):
    cb = get_entity("chargebacks", chargeback_id, "chargeback")
    body = get_body()
    require_fields(body, ["outcome"])
    if not is_string(body["outcome"]) or body["outcome"] not in ("CONFIRM", "WAIVE"):
        raise validation("outcome must be CONFIRM or WAIVE")
    if cb["status"] != "APPEALED":
        raise invalid_state("only APPEALED chargebacks can be resolved")
    if body["outcome"] == "CONFIRM":
        services.confirm_chargeback(cb)
    else:
        cb["status"] = "WAIVED"
        touch(cb)
        vendor = db.stores["vendors"][cb["vendor_id"]]
        services.recompute_vendor_compliance(vendor)
    return cb, 200


# ================================================================ department sales
def create_department_sale(user):
    body = get_body()
    require_fields(body, ["club_id", "member_id", "department", "amount_cents"])
    if not is_string(body["club_id"]):
        raise validation("club_id must be a string")
    if not is_string(body["member_id"]):
        raise validation("member_id must be a string")
    if body["department"] not in ("GAS", "PHARMACY", "OPTICAL"):
        raise validation("department must be GAS, PHARMACY, or OPTICAL")
    if not is_int(body["amount_cents"]) or body["amount_cents"] < 1:
        raise validation("amount_cents must be an integer >= 1")
    club = get_entity("clubs", body["club_id"], "club")
    member = get_entity("members", body["member_id"], "member")
    if member["status"] != "ACTIVE":
        raise safety_gate("suspended member cannot purchase ancillary services")
    flags = club.get("ancillary_flags") or {}
    if not flags.get(body["department"].lower(), False):
        raise dept_disabled("department %s is disabled at this club" % body["department"])
    sale = new_entity({
        "club_id": club["id"],
        "member_id": member["id"],
        "department": body["department"],
        "amount_cents": body["amount_cents"],
        "sold_on": current_date_str(),
    })
    db.stores["department_sales"][sale["id"]] = sale
    return sale, 201


def get_department_sale(user, sale_id):
    return get_entity("department_sales", sale_id, "department sale"), 200


# ================================================================ logical clock
def set_clock(user):
    body = get_body()
    require_fields(body, ["to_iso8601"])
    target = parse_iso8601_utc(body["to_iso8601"])
    if target < db.get_clock():
        raise validation("logical clock must not move backwards")
    db.set_clock(target)
    triggered = services.fire_due_transitions()
    return {"current_utc": now_ts(), "triggered_transitions": triggered}, 200


# ================================================================ route table
# (method, path, handler, roles)
ROUTES = [
    ("POST", "/wcd/regions", create_region, ["RegionalOps"]),
    ("GET", "/wcd/regions", list_regions, ALL_ROLES),
    ("GET", "/wcd/regions/<region_id>", get_region, ALL_ROLES),

    ("POST", "/wcd/vendors", create_vendor, ["RegionalOps"]),
    ("GET", "/wcd/vendors", list_vendors, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep", "CategoryManager"]),
    ("GET", "/wcd/vendors/<vendor_id>", get_vendor, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep", "CategoryManager"]),
    ("GET", "/wcd/vendors/<vendor_id>/appointments", list_vendor_appointments, ["RegionalOps", "DepotManager", "VendorRep"]),
    ("POST", "/wcd/vendors/<vendor_id>/reinstate", reinstate_vendor, ["DepotManager"]),
    ("POST", "/wcd/vendors/<vendor_id>/deactivate", deactivate_vendor, ["DepotManager"]),

    ("POST", "/wcd/clubs", create_club, ["RegionalOps"]),
    ("GET", "/wcd/clubs", list_clubs, ALL_ROLES),
    ("GET", "/wcd/clubs/<club_id>", get_club, ALL_ROLES),
    ("GET", "/wcd/clubs/<club_id>/members", list_club_members, ["RegionalOps", "MembershipDesk", "CategoryManager"]),
    ("GET", "/wcd/clubs/<club_id>/allocations", list_club_allocations, ["RegionalOps", "DepotPlanner", "DepotManager"]),
    ("GET", "/wcd/clubs/<club_id>/department-sales", list_club_department_sales, ["RegionalOps", "MembershipDesk", "CategoryManager"]),
    ("GET", "/wcd/clubs/<club_id>/purchases", list_club_purchases, ["RegionalOps", "MembershipDesk", "CategoryManager"]),

    ("POST", "/wcd/items", create_item, ["CategoryManager"]),
    ("GET", "/wcd/items", list_items, ALL_ROLES),
    ("GET", "/wcd/items/<item_id>", get_item, ALL_ROLES),
    ("POST", "/wcd/items/<item_id>/activate", activate_item, ["CategoryManager"]),
    ("POST", "/wcd/items/<item_id>/request-deletion", request_deletion, ["CategoryManager"]),
    ("POST", "/wcd/items/<item_id>/discontinue", discontinue_item, ["CategoryManager"]),
    ("GET", "/wcd/items/<item_id>/markdown-decisions", list_markdown_decisions, ["CategoryManager", "RegionalOps"]),
    ("POST", "/wcd/items/<item_id>/markdown-decisions", create_markdown_decision, ["CategoryManager"]),
    ("GET", "/wcd/items/<item_id>/complaints", list_item_complaints, ["CategoryManager", "MembershipDesk", "RegionalOps"]),

    ("POST", "/wcd/depots", create_depot, ["DepotManager"]),
    ("GET", "/wcd/depots", list_depots, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep"]),
    ("GET", "/wcd/depots/<depot_id>", get_depot, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep"]),
    ("GET", "/wcd/depots/<depot_id>/appointments", list_depot_appointments, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep"]),
    ("GET", "/wcd/depots/<depot_id>/cross-dock-runs", list_depot_runs, ["RegionalOps", "DepotManager", "DepotPlanner"]),

    ("POST", "/wcd/appointments", create_appointment, ["VendorRep"]),
    ("GET", "/wcd/appointments/<appt_id>", get_appointment, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep"]),
    ("POST", "/wcd/appointments/<appt_id>/check-in", check_in_appointment, ["DepotManager"]),
    ("POST", "/wcd/appointments/<appt_id>/complete", complete_appointment, ["DepotManager"]),
    ("POST", "/wcd/appointments/<appt_id>/cancel", cancel_appointment, ["VendorRep"]),
    ("GET", "/wcd/appointments/<appt_id>/pallets", list_appointment_pallets, ["RegionalOps", "DepotManager", "DepotPlanner", "VendorRep"]),

    ("POST", "/wcd/pallets", create_pallet, ["DepotManager"]),
    ("GET", "/wcd/pallets", list_pallets, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("GET", "/wcd/pallets/<pallet_id>", get_pallet, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("POST", "/wcd/pallets/<pallet_id>/reconcile", reconcile_pallet, ["DepotManager"]),

    ("POST", "/wcd/cross-dock-runs", create_run, ["DepotPlanner"]),
    ("GET", "/wcd/cross-dock-runs/<run_id>", get_run, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("POST", "/wcd/cross-dock-runs/<run_id>/allocations", create_allocation, ["DepotPlanner"]),
    ("GET", "/wcd/cross-dock-runs/<run_id>/allocations", list_run_allocations, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("POST", "/wcd/cross-dock-runs/<run_id>/commit", commit_run, ["DepotPlanner"]),
    ("POST", "/wcd/cross-dock-runs/<run_id>/cancel", cancel_run, ["DepotPlanner"]),

    ("GET", "/wcd/allocations", list_allocations, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("GET", "/wcd/allocations/<allocation_id>", get_allocation, ["RegionalOps", "DepotManager", "DepotPlanner"]),
    ("POST", "/wcd/allocations/<allocation_id>/void", void_allocation, ["DepotPlanner"]),

    ("POST", "/wcd/members", create_member, ["MembershipDesk"]),
    ("GET", "/wcd/members", list_members, ["MembershipDesk", "RegionalOps", "CategoryManager"]),
    ("GET", "/wcd/members/<member_id>", get_member, ["MembershipDesk", "RegionalOps", "CategoryManager"]),
    ("POST", "/wcd/members/<member_id>/suspend", suspend_member, ["MembershipDesk"]),
    ("GET", "/wcd/members/<member_id>/purchases", list_member_purchases, ["MembershipDesk", "RegionalOps", "CategoryManager"]),
    ("GET", "/wcd/members/<member_id>/complaints", list_member_complaints, ["MembershipDesk", "CategoryManager", "RegionalOps"]),
    ("GET", "/wcd/members/<member_id>/department-sales", list_member_department_sales, ["MembershipDesk", "RegionalOps", "CategoryManager"]),

    ("POST", "/wcd/purchases", create_purchase, ["MembershipDesk"]),
    ("GET", "/wcd/purchases", list_purchases, ["MembershipDesk", "RegionalOps", "CategoryManager"]),
    ("GET", "/wcd/purchases/<purchase_id>", get_purchase, ["MembershipDesk", "RegionalOps", "CategoryManager"]),
    ("POST", "/wcd/purchases/<purchase_id>/refund", refund_purchase, ["MembershipDesk"]),

    ("POST", "/wcd/complaints", create_complaint, ["MembershipDesk"]),
    ("GET", "/wcd/complaints/<complaint_id>", get_complaint, ["MembershipDesk", "CategoryManager", "RegionalOps"]),
    ("POST", "/wcd/complaints/<complaint_id>/resolve", resolve_complaint, ["MembershipDesk"]),

    ("GET", "/wcd/chargebacks", list_chargebacks, ["RegionalOps", "DepotManager", "VendorRep"]),
    ("GET", "/wcd/chargebacks/<chargeback_id>", get_chargeback, ["RegionalOps", "DepotManager", "VendorRep"]),
    ("POST", "/wcd/chargebacks/<chargeback_id>/appeal", appeal_chargeback, ["VendorRep"]),
    ("POST", "/wcd/chargebacks/<chargeback_id>/resolve", resolve_chargeback, ["DepotManager"]),

    ("POST", "/wcd/department-sales", create_department_sale, ["MembershipDesk"]),
    ("GET", "/wcd/department-sales/<sale_id>", get_department_sale, ["MembershipDesk", "RegionalOps", "CategoryManager"]),

    ("POST", "/wcd/_clock/set_current_utc", set_clock, ["RegionalOps"]),
]
