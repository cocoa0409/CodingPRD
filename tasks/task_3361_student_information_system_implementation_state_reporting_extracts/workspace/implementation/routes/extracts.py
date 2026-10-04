"""ReportingExtract endpoints: create (snapshot + supersede + OCC), list, get,
validate, reopen, submit, resolve."""
from flask import Blueprint, request

from db import get_clock, new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.calc import escalation_priority_for
from services.serializers import extract_out
from validators import body, req_enum, req_int, req_str

bp = Blueprint("extracts", __name__)

OUTCOMES = {"ACCEPTED", "REJECTED"}


def _get_extract_or_404(xid):
    x = store["extracts"].get(xid)
    if not x:
        raise ApiError("ERR_EXTRACT_NOT_FOUND", 404,
                       "No reporting extract with the given id")
    return x


def _year_enrollments(school_year_id):
    return [e for e in store["enrollments"].values()
            if e["school_year_id"] == school_year_id]


@bp.post("/sis/reporting-extracts")
def create_extract():
    _uid, role = auth_context()
    data = body()
    school_year_id = req_str(data, "school_year_id")
    collection_spec_id = req_str(data, "collection_spec_id")
    expected_version = req_int(data, "expected_school_year_version")
    require_role(role, {"StateReporter"})
    year = store["school_years"].get(school_year_id)
    if not year:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "school_year_id does not reference an existing school year")
    if year["status"] != "CLOSED_FOR_REPORTING":
        raise ApiError("ERR_SOURCE_YEAR_NOT_CLOSED", 409,
                       "Extract creation requires year CLOSED_FOR_REPORTING")
    spec = store["specs"].get(collection_spec_id)
    if not spec:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "collection_spec_id does not reference an existing spec")
    if spec["status"] != "PUBLISHED":
        raise ApiError("ERR_SPEC_NOT_PUBLISHED", 409,
                       "Extract creation requires a PUBLISHED spec")
    district = store["districts"].get(year["district_id"])
    if not district or spec["state_code"] != district["state_code"]:
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "spec state_code does not match the year's district state_code")
    # OCC: the client's view of the year's extract lineage must be current.
    if expected_version != year["version"]:
        raise ApiError("ERR_STALE_SCHOOL_YEAR_VERSION", 412,
                       "expected_school_year_version does not match the school year's current version")
    # Snapshot the year's entire enrollment population (any lifecycle).
    records = _year_enrollments(school_year_id)
    record_count = len(records)
    chronic_absentee_count = sum(1 for e in records
                                 if e["absence_posture"] == "CHRONIC")
    # Round-per-record then sum (pinned order): each fte variant rounded
    # half-up to 3 decimals (already stored that way) then * 1000.
    total_fte_millis = 0
    for e in records:
        fte = e["fte_adm"] if spec["funding_method"] == "ADM" else e["fte_count_date"]
        total_fte_millis += int(fte * 1000)
    invalid_record_count = sum(
        1 for e in records
        if e["membership_days"] < spec["min_membership_days"])
    prior = [x for x in store["extracts"].values()
             if x["school_year_id"] == school_year_id
             and x["collection_spec_id"] == collection_spec_id]
    generation = 1 + len(prior)
    superseded = [x for x in prior
                  if x["status"] in ("DRAFT", "VALIDATED", "REJECTED")]
    superseded.sort(key=lambda x: (x["created_at"], x["_seq"]))
    supersedes_extract_id = superseded[-1]["id"] if superseded else None
    for x in superseded:
        x["status"] = "SUPERSEDED"
        touch(x)
    x = {"id": new_id(), "school_year_id": school_year_id,
         "collection_spec_id": collection_spec_id, "generation": generation,
         "status": "DRAFT", "record_count": record_count,
         "invalid_record_count": invalid_record_count,
         "total_fte_millis": total_fte_millis,
         "chronic_absentee_count": chronic_absentee_count,
         "escalation_priority": "NONE",
         "supersedes_extract_id": supersedes_extract_id,
         "submitted_at": None}
    stamp_new(x)
    store["extracts"][x["id"]] = x
    touch(year)
    return ok_obj(extract_out(x), 201)


@bp.get("/sis/reporting-extracts")
def list_extracts():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    school_year_id = request.args.get("school_year_id")
    collection_spec_id = request.args.get("collection_spec_id")
    supersedes_extract_id = request.args.get("supersedes_extract_id")
    status = request.args.get("status")
    items = [x for x in store["extracts"].values()
             if (school_year_id is None or x["school_year_id"] == school_year_id)
             and (collection_spec_id is None or x["collection_spec_id"] == collection_spec_id)
             and (supersedes_extract_id is None or x["supersedes_extract_id"] == supersedes_extract_id)
             and (status is None or x["status"] == status)]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([extract_out(x) for x in page], total, limit, offset)


@bp.get("/sis/reporting-extracts/<xid>")
def get_extract(xid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(extract_out(_get_extract_or_404(xid)))


@bp.post("/sis/reporting-extracts/<xid>/validate")
def validate_extract(xid):
    _uid, role = auth_context()
    require_role(role, {"StateReporter"})
    x = _get_extract_or_404(xid)
    if x["status"] != "DRAFT":
        raise ApiError("ERR_EXTRACT_NOT_DRAFT", 409,
                       "Validate requires extract DRAFT")
    spec = store["specs"].get(x["collection_spec_id"])
    min_days = spec["min_membership_days"] if spec else 10
    # Validate recomputes exactly one number against current enrollment data.
    records = _year_enrollments(x["school_year_id"])
    x["invalid_record_count"] = sum(
        1 for e in records if e["membership_days"] < min_days)
    x["status"] = "VALIDATED"
    touch(x)
    return ok_obj(extract_out(x))


@bp.post("/sis/reporting-extracts/<xid>/reopen")
def reopen_extract(xid):
    _uid, role = auth_context()
    require_role(role, {"StateReporter"})
    x = _get_extract_or_404(xid)
    if x["status"] not in ("VALIDATED", "REJECTED"):
        raise ApiError("ERR_EXTRACT_NOT_DRAFT", 409,
                       "Reopen requires extract VALIDATED or REJECTED")
    x["status"] = "DRAFT"
    x["escalation_priority"] = "NONE"
    touch(x)
    return ok_obj(extract_out(x))


@bp.post("/sis/reporting-extracts/<xid>/submit")
def submit_extract(xid):
    _uid, role = auth_context()
    require_role(role, {"StateReporter"})
    x = _get_extract_or_404(xid)
    if x["status"] != "VALIDATED":
        raise ApiError("ERR_EXTRACT_NOT_VALIDATED", 409,
                       "Submit requires extract VALIDATED")
    spec = store["specs"].get(x["collection_spec_id"])
    clk = get_clock()
    # Half-open submission window: [opens_at, closes_at); a reading exactly
    # at the close is already outside.
    if spec is None or not (spec["submission_window_opens_at"] <= clk
                            < spec["submission_window_closes_at"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", 409,
                       "Logical clock outside the half-open submission window")
    if x["invalid_record_count"] != 0:
        raise ApiError("ERR_EXTRACT_HAS_ERRORS", 409,
                       "Submit blocked while invalid_record_count > 0")
    x["status"] = "SUBMITTED"
    x["submitted_at"] = clk
    touch(x)
    return ok_obj(extract_out(x))


@bp.post("/sis/reporting-extracts/<xid>/resolve")
def resolve_extract(xid):
    _uid, role = auth_context()
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    require_role(role, {"StateReporter"})
    x = _get_extract_or_404(xid)
    if x["status"] != "SUBMITTED":
        raise ApiError("ERR_EXTRACT_NOT_SUBMITTED", 409,
                       "Resolve requires extract SUBMITTED")
    x["status"] = outcome
    if outcome == "REJECTED":
        spec = store["specs"].get(x["collection_spec_id"])
        x["escalation_priority"] = escalation_priority_for(
            spec["submission_window_closes_at"])
    touch(x)
    return ok_obj(extract_out(x))
