"""Partnership agreement endpoints (PRD 3.3)."""

from flask import Blueprint, request

import clock
import derive
import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("agreements", __name__)

READERS = ["ProgramAdmin", "PlacementCoordinator"]


def void_proposed_placements(agreement):
    """Suspension / termination cascade (PRD 3.3)."""
    for placement in store.placements_of_agreement(agreement["id"]):
        if placement["placement_status"] != "PROPOSED":
            continue
        placement["placement_status"] = "VOIDED"
        placement["voided_reason"] = "AGREEMENT_SUSPENDED"
        store.touch(placement)

        request_row = store.REQUESTS.get(placement["request_id"])
        if request_row is not None:
            request_row["status"] = "SUBMITTED"
            teacher_id = placement["cooperating_teacher_id"]
            if teacher_id not in request_row["excluded_cooperating_teacher_ids"]:
                request_row["excluded_cooperating_teacher_ids"].append(teacher_id)
            store.touch(request_row)
            derive.derive_request_current_placement(request_row)

        teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
        if teacher is not None:
            derive.derive_teacher_counters(teacher)
        supervisor = store.SUPERVISORS.get(placement["supervisor_id"])
        if supervisor is not None:
            derive.derive_supervisor(supervisor)
    derive.derive_agreement_ledger(agreement)


@bp.post("/epp/partnership-agreements")
@endpoint(["ProgramAdmin"])
def draft_agreement():
    body = shapes.body_of(request)
    district_id = shapes.req_str(body, "district_id", 1, None)
    term = shapes.req_enum(body, "term", shapes.TERMS)
    window_start = shapes.req_date(body, "window_start")
    window_end = shapes.req_date(body, "window_end")
    placement_cap = shapes.req_int(body, "placement_cap", 1, 50)
    rate = shapes.req_int(body, "stipend_rate_cents_per_week", 1, 100000)
    allowed_subjects = shapes.req_enum_list(body, "allowed_subjects",
                                            shapes.SUBJECTS, 1, 6)
    allowed_bands = shapes.req_enum_list(body, "allowed_grade_bands",
                                         shapes.GRADE_BANDS, 1, 4)

    district = store.get_district(district_id)

    if not window_end > window_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end must be strictly later than window_start.")

    row = store.new_row({
        "district_id": district["id"],
        "term": term,
        "window_start": window_start,
        "window_end": window_end,
        "status": "DRAFT",
        "placement_cap": placement_cap,
        "stipend_rate_cents_per_week": rate,
        "allowed_subjects": allowed_subjects,
        "allowed_grade_bands": allowed_bands,
        "seats_reserved": 0,
        "seats_committed": 0,
        "capacity_posture": "OPEN",
        "stipend_committed_cents": 0,
        "suspension_reason": None,
    })
    store.AGREEMENTS[row["id"]] = row
    return envelope.created(views.dump(row, views.AGREEMENT))


@bp.get("/epp/partnership-agreements/<agreement_id>")
@endpoint(READERS)
def read_agreement(agreement_id):
    row = store.get_agreement(agreement_id)
    derive.expire_agreement(row)
    derive.derive_agreement_ledger(row)
    return envelope.ok(views.dump(row, views.AGREEMENT))


@bp.get("/epp/partnership-agreements")
@endpoint(READERS)
def list_agreements():
    page, page_size = shapes.pagination(request.args)
    district_id = request.args.get("district_id") or None
    status = shapes.query_enum(request.args, "status",
                               shapes.AGREEMENT_STATUSES)
    term = shapes.query_enum(request.args, "term", shapes.TERMS)
    rows = []
    for row in store.all_of(store.AGREEMENTS):
        if district_id is not None and row["district_id"] != district_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if term is not None and row["term"] != term:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.AGREEMENT),
                            page, page_size, total)


def _state_invalid(message):
    return ApiError("ERR_AGREEMENT_STATE_INVALID", message)


@bp.post("/epp/partnership-agreements/<agreement_id>/activate")
@endpoint(["ProgramAdmin"])
def activate_agreement(agreement_id):
    row = store.get_agreement(agreement_id)
    derive.expire_agreement(row)
    if row["status"] != "DRAFT":
        raise _state_invalid("Only a DRAFT agreement may be activated.")
    if row["window_end"] < clock.today():
        raise _state_invalid("The agreement window has already closed.")
    row["status"] = "ACTIVE"
    store.touch(row)
    derive.derive_agreement_ledger(row)
    return envelope.ok(views.dump(row, views.AGREEMENT))


@bp.post("/epp/partnership-agreements/<agreement_id>/suspend")
@endpoint(["ProgramAdmin"])
def suspend_agreement(agreement_id):
    row = store.get_agreement(agreement_id)
    body = shapes.body_of(request)
    reason = shapes.req_str(body, "suspension_reason", 1, None)
    derive.expire_agreement(row)
    if row["status"] != "ACTIVE":
        raise _state_invalid("Only an ACTIVE agreement may be suspended.")
    row["suspension_reason"] = reason
    row["status"] = "SUSPENDED"
    store.touch(row)
    void_proposed_placements(row)
    return envelope.ok(views.dump(row, views.AGREEMENT))


@bp.post("/epp/partnership-agreements/<agreement_id>/reactivate")
@endpoint(["ProgramAdmin"])
def reactivate_agreement(agreement_id):
    row = store.get_agreement(agreement_id)
    derive.expire_agreement(row)
    if row["status"] != "SUSPENDED":
        raise _state_invalid("Only a SUSPENDED agreement may be reactivated.")
    if row["window_end"] < clock.today():
        raise _state_invalid("The agreement window has already closed.")
    row["status"] = "ACTIVE"
    row["suspension_reason"] = None
    store.touch(row)
    derive.derive_agreement_ledger(row)
    return envelope.ok(views.dump(row, views.AGREEMENT))


@bp.post("/epp/partnership-agreements/<agreement_id>/terminate")
@endpoint(["ProgramAdmin"])
def terminate_agreement(agreement_id):
    row = store.get_agreement(agreement_id)
    body = shapes.body_of(request)
    reason = shapes.req_str(body, "suspension_reason", 1, None)
    derive.expire_agreement(row)
    if row["status"] not in ("ACTIVE", "SUSPENDED"):
        raise _state_invalid(
            "Only an ACTIVE or SUSPENDED agreement may be terminated.")
    was_active = row["status"] == "ACTIVE"
    row["suspension_reason"] = reason
    row["status"] = "TERMINATED"
    store.touch(row)
    if was_active:
        void_proposed_placements(row)
    else:
        derive.derive_agreement_ledger(row)
    return envelope.ok(views.dump(row, views.AGREEMENT))
