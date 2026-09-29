"""Teacher intake: drafting, submitting, revising and triage (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("requests", __name__)


@bp.post("/application-requests")
def draft_request():
    user_id, _role = auth.actor("Teacher")
    data = validate.body([
        F("application_id", "str"),
        F("requester_teacher_id", "str"),
        F("instructional_justification", "str", lo=1, hi=2000),
        F("requested_data_elements", "enum_array", members=set(logic.ELEMENT_CODES)),
        F("student_count_estimate", "int", lo=1, hi=50000),
        F("grade_band_low", "int", lo=0, hi=12),
        F("grade_band_high", "int", lo=0, hi=12),
    ])
    validate.grade_band(data, "grade_band_low", "grade_band_high")
    application = auth.need("application", data["application_id"])
    teacher = auth.need("teacher", data["requester_teacher_id"])
    auth.owner_or_403(user_id == teacher["id"])

    row = store.new_row({
        "application_id": application["id"],
        "requester_teacher_id": teacher["id"],
        "instructional_justification": data["instructional_justification"],
        "requested_data_elements": data["requested_data_elements"],
        "student_count_estimate": data["student_count_estimate"],
        "grade_band_low": data["grade_band_low"],
        "grade_band_high": data["grade_band_high"],
        "status": "DRAFT",
        "revision_round": 0,
        "priority_score": Decimal("0.00"),
        "priority_band": "LOW",
        "submitted_at": None,
        "triage_note": None,
    })
    store.requests[row["id"]] = row
    return envelope.created(serialize.request(row))


@bp.get("/application-requests")
def list_requests():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    filters = envelope.query_filters({
        "application_id": None,
        "requester_teacher_id": None,
        "status": set(logic.REQUEST_STATUSES),
        "priority_band": set(logic.PRIORITY_BANDS),
    })
    rows = list(store.requests.values())
    for key in ("application_id", "requester_teacher_id", "status", "priority_band"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.request)


@bp.get("/application-requests/<request_id>")
def read_request(request_id):
    user_id, role = auth.actor("Teacher", "PrivacyAnalyst", "PrivacyOfficeAdmin")
    row = auth.need("request", request_id)
    if role == "Teacher":
        auth.owner_or_403(user_id == row["requester_teacher_id"])
    return envelope.ok(serialize.request(row))


@bp.post("/application-requests/<request_id>/submit")
def submit_request(request_id):
    user_id, _role = auth.actor("Teacher")
    data = validate.body([
        F("instructional_justification", "str", required=False, lo=1, hi=2000),
        F("requested_data_elements", "enum_array", required=False,
          members=set(logic.ELEMENT_CODES)),
        F("student_count_estimate", "int", required=False, lo=1, hi=50000),
    ])
    row = auth.need("request", request_id)
    auth.owner_or_403(user_id == row["requester_teacher_id"])

    if row["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    application = store.applications[row["application_id"]]
    vendor = store.vendors[application["vendor_id"]]
    if vendor["privacy_posture"] == "FROZEN":
        raise ApiError("ERR_VENDOR_POSTURE_FROZEN")

    # Supplied values are effective before any check or calculation (PRD 3.2).
    justification = data.get("instructional_justification", row["instructional_justification"])
    elements = data.get("requested_data_elements", row["requested_data_elements"])
    estimate = data.get("student_count_estimate", row["student_count_estimate"])

    if len(justification) < logic.JUSTIFICATION_MIN_CHARS:
        raise ApiError("ERR_JUSTIFICATION_TOO_SHORT")
    if len(elements) < 1:
        raise ApiError("ERR_NO_DATA_ELEMENTS")
    if row["revision_round"] >= logic.REVISION_ROUND_MAX:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")

    was_returned = row["status"] == "RETURNED"
    row["instructional_justification"] = justification
    row["requested_data_elements"] = elements
    row["student_count_estimate"] = estimate
    row["status"] = "SUBMITTED"
    row["submitted_at"] = store.clock()
    if was_returned:
        row["revision_round"] = row["revision_round"] + 1

    score, band = logic.request_priority_score(
        row["grade_band_low"], row["grade_band_high"], estimate, justification)
    row["priority_score"] = score
    row["priority_band"] = band
    store.bump(row)

    logic.recount_teacher_requests(store.teachers[row["requester_teacher_id"]])
    return envelope.ok(serialize.request(row))


@bp.post("/application-requests/<request_id>/triage")
def triage_request(request_id):
    auth.actor("PrivacyAnalyst", "PrivacyOfficeAdmin")
    data = validate.body([
        F("disposition", "enum", members={"ACCEPT_FOR_REVIEW", "RETURN", "DENY"}),
        F("triage_note", "str", required=False),
    ])
    row = auth.need("request", request_id)
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    disposition = data["disposition"]
    row["status"] = {
        "ACCEPT_FOR_REVIEW": "TRIAGED_FOR_REVIEW",
        "RETURN": "RETURNED",
        "DENY": "DENIED",
    }[disposition]
    if "triage_note" in data:
        row["triage_note"] = data["triage_note"]
    store.bump(row)

    if disposition == "ACCEPT_FOR_REVIEW":
        application = store.applications[row["application_id"]]
        if application["status"] == "CANDIDATE":
            store.apply(application, {"status": "IN_REVIEW"})

    logic.recount_teacher_requests(store.teachers[row["requester_teacher_id"]])
    return envelope.ok(serialize.request(row))
