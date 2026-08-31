"""Grade needs lists and their item lines."""
from flask import Blueprint

import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import ALL_ROLES, SCHOOL_LIAISON, auth, school_scope

bp = Blueprint("kitspecs", __name__)


@bp.post("/grade-kit-specs")
def create_spec():
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    school_id = v.req_id(data, "school_id")
    grade_band = v.req_enum(data, "grade_band", v.GRADE_BANDS)
    student_target_count = v.req_int(data, "student_target_count", minimum=1)

    school = find.school(school_id)
    school_scope(role, user_id, school["id"])

    rec = base_record()
    rec.update({
        "school_id": school["id"],
        "grade_band": grade_band,
        "student_target_count": student_target_count,
        "status": "DRAFT",
        "kit_unit_cost_cents": 0,
        "line_count": 0,
    })
    db.grade_kit_specs[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/grade-kit-specs/<spec_id>")
def read_spec(spec_id):
    auth(ALL_ROLES)
    return resp.ok(find.spec(spec_id))


@bp.patch("/grade-kit-specs/<spec_id>/status")
def move_spec_status(spec_id):
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    target = v.target_status(data)
    spec = find.spec(spec_id)
    school = db.schools.get(spec["school_id"])
    school_scope(role, user_id, spec["school_id"])

    if target not in v.SPEC_STATUSES:
        raise ApiError("ERR_INVALID_SPEC_STATE")

    lines = derive.lines_of_spec(spec["id"])

    if target == "PUBLISHED":
        # 9 — from-state plus the at-least-one-line guard.
        if spec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_SPEC_STATE")
        if len(lines) < 1:
            raise ApiError("ERR_INVALID_SPEC_STATE")
        # 13 — governing school partnership.
        if school is None or school["partnership_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_PARTNERSHIP_INACTIVE")
        # 15 — every referenced catalogue item is active.
        for line in lines:
            item = db.supply_items.get(line["supply_item_id"])
            if item is None or not item["catalog_active"]:
                raise ApiError("ERR_ITEM_INACTIVE")
        # 22 — uniqueness of the published (school, band) pairing.
        if derive.published_spec(spec["school_id"], spec["grade_band"]) is not None:
            raise ApiError("ERR_DUPLICATE_KIT_SPEC")
        spec["status"] = "PUBLISHED"
        derive.recompute_spec(spec)
        touch(spec)
        if school is not None:
            derive.recompute_school(school, bump=False)
            touch(school)
    elif target == "RETIRED":
        if spec["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_SPEC_STATE")
        in_use = any(e["status"] in ("PUBLISHED", "LOCKED")
                     and e["grade_band"] == spec["grade_band"]
                     for e in derive.events_of_school(spec["school_id"]))
        if in_use:
            raise ApiError("ERR_INVALID_SPEC_STATE")
        if school is None or school["partnership_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_PARTNERSHIP_INACTIVE")
        spec["status"] = "RETIRED"
        touch(spec)
        if school is not None:
            derive.recompute_school(school, bump=False)
            touch(school)
    else:
        raise ApiError("ERR_INVALID_SPEC_STATE")

    return resp.ok(spec)


@bp.post("/kit-spec-lines")
def create_line():
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    spec_id = v.req_id(data, "grade_kit_spec_id")
    item_id = v.req_id(data, "supply_item_id")
    qty_per_student = v.req_int(data, "qty_per_student", minimum=1)
    substitutable = v.opt_bool(data, "substitutable", False)

    spec = find.spec(spec_id)
    item = find.supply_item(item_id)
    school_scope(role, user_id, spec["school_id"])

    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPEC_STATE")
    if not item["catalog_active"]:
        raise ApiError("ERR_ITEM_INACTIVE")

    rec = base_record()
    rec.update({
        "grade_kit_spec_id": spec["id"],
        "supply_item_id": item["id"],
        "qty_per_student": qty_per_student,
        "substitutable": substitutable,
    })
    db.kit_spec_lines[rec["id"]] = rec
    derive.recompute_spec(spec)
    touch(spec)
    return resp.ok(rec, 201)


@bp.get("/kit-spec-lines/<line_id>")
def read_line(line_id):
    auth(ALL_ROLES)
    return resp.ok(find.spec_line(line_id))


@bp.get("/kit-spec-lines")
def list_lines():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    spec_id = v.query_id("grade_kit_spec_id")
    item_id = v.query_id("supply_item_id")
    rows = list(db.kit_spec_lines.values())
    if spec_id:
        rows = [r for r in rows if r["grade_kit_spec_id"] == spec_id]
    if item_id:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    return resp.listing(sort_records(rows), limit, offset)
