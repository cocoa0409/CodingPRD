"""Enrollment routes with OCC, waitlist waterfall, drops, transfers."""
from flask import Blueprint, request
from store import store, fresh, stamp, logical_now, parse_dt
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_SECTION_FULL, ERR_DEADLINE_PASSED,
)
from services import (
    check_prerequisites, recompute_section_counts, seat_allocation, issue_invoice,
    invoice_for_enrollment, refund_invoice_full, refund_invoice_tiered, is_early,
    refund_pct_for,
)

bp = Blueprint("enrollments", __name__)

ROLES = ["ProgramDirector", "Registrar", "Student"]


def _get_enrollment(eid):
    e = store.enrollments.get(eid)
    if not e:
        not_found("enrollment not found")
    return e


def _can_access(user_id, role, enrollment):
    if role == "Student":
        require_student_owner(user_id, role, enrollment["student_id"])


@bp.post("/enrollments")
def create_enrollment():
    user_id, role = auth(["Registrar", "Student"])
    body = json_body()
    require_fields(body, ["student_id", "section_id", "expected_section_version"])
    if role == "Student":
        require_student_owner(user_id, role, body["student_id"])
    student = store.students.get(body["student_id"])
    if not student:
        not_found("student not found")
    section = store.sections.get(body["section_id"])
    if not section:
        not_found("section not found")
    esv = body["expected_section_version"]
    if not isinstance(esv, int) or isinstance(esv, bool):
        invalid_request("expected_section_version must be an integer")
    # §2.7: the target's state gate runs before temporal and business rules;
    # enrollment is only possible while the section accepts enrollments
    if section["status"] not in ("OPEN",):
        raise_err(ERR_INVALID_STATE, "section does not accept enrollments")
    if esv != section["version"]:
        raise_err(ERR_STALE_VERSION, "expected_section_version does not match current section version")
    priority = body.get("priority_tier", "NEW")
    if priority not in ("RETURNING", "NEW"):
        invalid_request("priority_tier must be RETURNING or NEW")
    level = store.levels.get(section["level_id"])
    if level:
        check_prerequisites(student, level)
    recompute_section_counts(section)
    if section["enrolled_count"] >= section["capacity"]:
        status = "WAITLISTED"
    else:
        status = "REGISTERED"
    enrollment = fresh({
        "student_id": body["student_id"],
        "section_id": section["id"],
        "priority_tier": priority,
        "origin_enrollment_id": body.get("origin_enrollment_id"),
        "status": status,
        "graded_showcase_id": None,
    })
    store.enrollments[enrollment["id"]] = enrollment
    issue_invoice(student["id"], enrollment["id"], section["tuition_cents"])
    stamp(section)
    recompute_section_counts(section)
    return success_obj(enrollment, 201)


@bp.get("/enrollments")
def list_enrollments():
    auth(ROLES)
    limit, offset = pagination_params()
    items = list(store.enrollments.values())
    for f in ("student_id", "section_id", "status", "origin_enrollment_id", "graded_showcase_id"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    user_id, role = auth(ROLES)
    e = _get_enrollment(eid)
    _can_access(user_id, role, e)
    return success_obj(e)


@bp.post("/enrollments/<eid>/confirm")
def confirm(eid):
    user_id, role = auth(["Student", "Registrar"])
    e = _get_enrollment(eid)
    _can_access(user_id, role, e)
    if e["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "enrollment must be REGISTERED")
    section = store.sections.get(e["section_id"])
    if not section:
        not_found("section not found")
    if section["status"] not in ("OPEN", "LOCKED"):
        raise_err(ERR_INVALID_STATE, "section must be OPEN or LOCKED")
    recompute_section_counts(section)
    # a seat is held only by CONFIRMED enrollments; confirming into a section
    # whose CONFIRMED count already reached capacity fails (§3.3)
    if section["enrolled_count"] >= section["capacity"]:
        raise_err(ERR_SECTION_FULL, "section is full")
    e["status"] = "CONFIRMED"
    stamp(e)
    stamp(section)
    recompute_section_counts(section)
    return success_obj(e)


@bp.post("/enrollments/<eid>/drop")
def drop(eid):
    user_id, role = auth(["Student", "Registrar"])
    e = _get_enrollment(eid)
    _can_access(user_id, role, e)
    if e["status"] not in ("REGISTERED", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, "only REGISTERED or CONFIRMED enrollments may be dropped")
    section = store.sections.get(e["section_id"])
    term = store.terms.get(section["term_id"]) if section else None
    if not term:
        not_found("term not found")
    early = is_early(term)
    if not early and e["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "only CONFIRMED enrollments may drop after the deadline")
    inv = invoice_for_enrollment(e["id"])
    if e["status"] == "REGISTERED":
        # early-only path; invoice voided
        e["status"] = "DROPPED_EARLY"
        if inv and inv["status"] not in ("VOID", "REFUNDED", "TRANSFERRED"):
            inv["status"] = "VOID"
            stamp(inv)
    else:  # CONFIRMED
        if early:
            e["status"] = "DROPPED_EARLY"
            if inv and inv["status"] not in ("VOID", "REFUNDED", "TRANSFERRED"):
                refund_invoice_full(inv)
        else:
            e["status"] = "DROPPED_LATE"
            if inv and inv["status"] not in ("VOID", "REFUNDED", "TRANSFERRED"):
                refund_invoice_tiered(inv, refund_pct_for(term))
    stamp(e)
    stamp(section)
    recompute_section_counts(section)
    # the waterfall promotes the waitlist head without occupying the freed seat:
    # recompute again after promotion so waitlist_count falls while
    # enrolled_count stays put until the promoted student confirms (§3.3)
    seat_allocation(section)
    recompute_section_counts(section)
    stamp(section)
    return success_obj(e)


@bp.post("/enrollments/<eid>/transfer")
def transfer(eid):
    user_id, role = auth(["Student", "Registrar"])
    e = _get_enrollment(eid)
    _can_access(user_id, role, e)
    if e["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "only CONFIRMED enrollments may transfer")
    body = json_body()
    require_fields(body, ["target_section_id"])
    source = store.sections.get(e["section_id"])
    target = store.sections.get(body["target_section_id"])
    if not target:
        not_found("target section not found")
    term = store.terms.get(source["term_id"])
    # temporal check before business rules per §2.7
    if not is_early(term):
        raise_err(ERR_DEADLINE_PASSED, "transfer deadline has passed")
    if target["term_id"] != source["term_id"] or target["level_id"] != source["level_id"]:
        invalid_request("target section must be same term and same level")
    recompute_section_counts(target)
    if target["enrolled_count"] >= target["capacity"]:
        raise_err(ERR_SECTION_FULL, "target section is full")
    # source enrollment out
    e["status"] = "TRANSFERRED_OUT"
    stamp(e)
    source_inv = invoice_for_enrollment(e["id"])
    carried = 0
    if source_inv and source_inv["status"] not in ("VOID", "REFUNDED", "TRANSFERRED"):
        carried = source_inv["paid_cents"]
        source_inv["status"] = "TRANSFERRED"
        stamp(source_inv)
    new_enrollment = fresh({
        "student_id": e["student_id"],
        "section_id": target["id"],
        "priority_tier": e.get("priority_tier", "NEW"),
        "origin_enrollment_id": e["id"],
        "status": "REGISTERED",
        "graded_showcase_id": None,
    })
    store.enrollments[new_enrollment["id"]] = new_enrollment
    issue_invoice(e["student_id"], new_enrollment["id"], target["tuition_cents"], carried_paid=carried)
    stamp(source)
    stamp(target)
    recompute_section_counts(source)
    recompute_section_counts(target)
    seat_allocation(source)
    recompute_section_counts(source)
    stamp(source)
    return success_obj(e)
