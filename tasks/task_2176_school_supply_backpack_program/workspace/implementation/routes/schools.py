"""Schools and the supply-item catalogue."""
from flask import Blueprint

import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import ALL_ROLES, PROGRAM_DIRECTOR, auth

bp = Blueprint("schools", __name__)


def new_school(data):
    rec = base_record()
    rec.update({
        "name": data["name"],
        "district_code": data["district_code"],
        "title_i_pct": data["title_i_pct"],
        "enrollment_count": data["enrollment_count"],
        "max_concurrent_seats": data["max_concurrent_seats"],
        "partnership_status": "PROSPECT",
        "target_student_count": 0,
        "students_served_interim_count": 0,
        "students_served_audited_count": 0,
        "no_show_count": 0,
        "kits_delivered_count": 0,
        "impact_index_interim": 0.00,
        "impact_index_audited": 0.00,
    })
    return rec


@bp.post("/schools")
def create_school():
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    payload = {
        "name": v.req_str(data, "name", 1, 120, non_blank=True),
        "district_code": v.req_str(data, "district_code", 1, 16),
        "title_i_pct": v.req_number(data, "title_i_pct", 0.0, 1.0),
        "enrollment_count": v.req_int(data, "enrollment_count", minimum=1),
        "max_concurrent_seats": v.req_int(data, "max_concurrent_seats", minimum=1),
    }
    rec = new_school(payload)
    db.schools[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/schools/<school_id>")
def read_school(school_id):
    auth(ALL_ROLES)
    return resp.ok(find.school(school_id))


@bp.get("/schools/<school_id>/grade-kit-specs")
def list_school_specs(school_id):
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.query_enum("status", v.SPEC_STATUSES)
    school = find.school(school_id)
    rows = [s for s in db.grade_kit_specs.values() if s["school_id"] == school["id"]]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


@bp.get("/schools/<school_id>/impact-summary")
def impact_summary(school_id):
    auth(ALL_ROLES)
    school = find.school(school_id)
    closed = sum(1 for e in derive.events_of_school(school["id"])
                 if e["status"] == "CLOSED")
    return resp.raw({
        "impact_index_interim": school["impact_index_interim"],
        "impact_index_audited": school["impact_index_audited"],
        "students_served_interim_count": school["students_served_interim_count"],
        "students_served_audited_count": school["students_served_audited_count"],
        "no_show_count": school["no_show_count"],
        "target_student_count": school["target_student_count"],
        "closed_event_count": closed,
    })


def _has_live_event(school_id):
    return any(e["status"] in ("PUBLISHED", "LOCKED")
               for e in derive.events_of_school(school_id))


def _suspension_cascade(school):
    touched_cycles = set()
    for event in derive.events_of_school(school["id"]):
        if event["status"] not in ("DRAFT", "PUBLISHED"):
            continue
        # HOP 1 — cancel the event.
        event["status"] = "CANCELLED"
        # HOP 2 / HOP 3 — withdraw its live registrations, release reservations.
        for reg in derive.registrations_of_event(event["id"]):
            if reg["eligibility_status"] not in (
                    "PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED"):
                continue
            was_confirmed = reg["eligibility_status"] == "CONFIRMED"
            reg["eligibility_status"] = "WITHDRAWN"
            if was_confirmed:
                derive.release_units(reg, event)
            touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        touched_cycles.add(event["drive_cycle_id"])
    # HOP 4 — refresh the inventory total of every cycle whose position moved.
    for cycle_id in touched_cycles:
        cycle = db.drive_cycles.get(cycle_id)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)


@bp.patch("/schools/<school_id>/partnership-status")
def move_partnership(school_id):
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)
    school = find.school(school_id)

    current = school["partnership_status"]
    if target not in v.SCHOOL_STATUSES:
        raise ApiError("ERR_INVALID_SCHOOL_STATE")

    if target == "MOU_PENDING":
        if current != "PROSPECT":
            raise ApiError("ERR_INVALID_SCHOOL_STATE")
    elif target == "ACTIVE":
        if current == "MOU_PENDING":
            if school["max_concurrent_seats"] < 1:
                raise ApiError("ERR_INVALID_SCHOOL_STATE")
        elif current != "SUSPENDED":
            raise ApiError("ERR_INVALID_SCHOOL_STATE")
    elif target == "SUSPENDED":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_SCHOOL_STATE")
    elif target == "ARCHIVED":
        if current not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_SCHOOL_STATE")
        if _has_live_event(school["id"]):
            raise ApiError("ERR_INVALID_SCHOOL_STATE")
    else:
        raise ApiError("ERR_INVALID_SCHOOL_STATE")

    school["partnership_status"] = target

    if target == "SUSPENDED":
        _suspension_cascade(school)
        derive.recompute_school(school, bump=False)
    elif target == "ARCHIVED":
        for spec in derive.specs_of_school(school["id"]):
            if spec["status"] == "PUBLISHED":
                spec["status"] = "RETIRED"
                touch(spec)
        derive.recompute_school(school, bump=False)

    touch(school)
    return resp.ok(school)


# --------------------------------------------------------------------------
# SupplyItem
# --------------------------------------------------------------------------
@bp.post("/supply-items")
def create_supply_item():
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    sku = v.req_str(data, "sku", 1, 32)
    name = v.req_str(data, "name")
    category = v.req_enum(data, "category", v.CATEGORIES)
    unit_cost_cents = v.req_int(data, "unit_cost_cents", minimum=1)
    bulk_pack_size = v.req_int(data, "bulk_pack_size", minimum=1)
    hygiene = v.opt_bool(data, "hygiene_sealed_required", False)
    active = v.opt_bool(data, "catalog_active", True)

    if any(i["sku"] == sku for i in db.supply_items.values()):
        raise ApiError("ERR_DUPLICATE_SKU")

    rec = base_record()
    rec.update({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_cost_cents": unit_cost_cents,
        "bulk_pack_size": bulk_pack_size,
        "hygiene_sealed_required": hygiene,
        "catalog_active": active,
    })
    db.supply_items[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/supply-items/<item_id>")
def read_supply_item(item_id):
    auth(ALL_ROLES)
    return resp.ok(find.supply_item(item_id))
