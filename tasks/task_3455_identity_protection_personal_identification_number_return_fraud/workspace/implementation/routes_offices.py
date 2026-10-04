"""ServiceOffice and VerificationAppointment routes, including the half-open
interval overlap-capacity gate on booking."""
from flask import Blueprint

from auth import require_roles
from domain import get_case, get_office, new_record, pub
from envelope import created, list_response, ok
from errors import err
from store import DB, fmt_ts, parse_ts
from validate import body, invalid, page, pagination, req_datetime, req_int, req_str

bp = Blueprint("offices", __name__)


@bp.post("/identity-protection/service-offices")
def create_office():
    require_roles(["SystemAdmin"])
    b = body()
    # Priority 8: office_code uniqueness (ERR_INVALID_REQUEST per catalog).
    code = b.get("office_code")
    if isinstance(code, str):
        for o in DB.offices.values():
            if o["office_code"] == code:
                invalid("office_code must be unique")
    # Priority 14: payload shape.
    code = req_str(b, "office_code")
    name = req_str(b, "name")
    capacity = req_int(b, "capacity")
    if capacity < 1:
        invalid("capacity must be >= 1")
    rec = new_record(DB.offices, {
        "office_code": code,
        "name": name,
        "capacity": capacity,
    })
    return created(pub(rec))


@bp.get("/identity-protection/service-offices/<string:office_id>")
def read_office(office_id):
    require_roles(["SystemAdmin", "VerificationAgent", "FraudAnalyst"])
    return ok(pub(get_office(office_id)))


@bp.post("/identity-protection/service-offices/<string:office_id>/appointments")
def book_appointment(office_id):
    require_roles(["VerificationAgent"])
    office = get_office(office_id)
    b = body()
    # Priority 4: body-carried case_id must resolve.
    case = None
    cid = b.get("case_id")
    if cid is not None:
        case = get_case(cid)
    start = parse_ts(b.get("start_at"))
    end = parse_ts(b.get("end_at"))
    if start is not None and end is not None and start < end:
        # Priority 9: capacity — reject when any instant in the half-open
        # [start_at, end_at) would make overlapping BOOKED appointments at the
        # office reach its capacity (adding the new one would exceed it).
        existing = [a for a in DB.appointments.values()
                    if a["office_id"] == office["id"] and a["status"] == "BOOKED"]
        instants = {start}
        for a in existing:
            a_start = parse_ts(a["start_at"])
            if start <= a_start < end:
                instants.add(a_start)
        for t in instants:
            overlapping = 0
            for a in existing:
                if parse_ts(a["start_at"]) <= t < parse_ts(a["end_at"]):
                    overlapping += 1
            if overlapping >= office["capacity"]:
                err("ERR_APPOINTMENT_CAPACITY_EXCEEDED")
    # Priority 11: the case must be an IN_PERSON case.
    if case is not None and case["channel"] != "IN_PERSON":
        err("ERR_CHANNEL_NOT_ALLOWED")
    # Priority 14: payload shape.
    cid = req_str(b, "case_id")
    if case is None:
        err("ERR_CASE_NOT_FOUND")
    start = req_datetime(b, "start_at")
    end = req_datetime(b, "end_at")
    if end <= start:
        invalid("end_at must be strictly after start_at")
    rec = new_record(DB.appointments, {
        "office_id": office["id"],
        "case_id": cid,
        "start_at": fmt_ts(start),
        "end_at": fmt_ts(end),
        "status": "BOOKED",
    })
    return created(pub(rec))


@bp.get("/identity-protection/service-offices/<string:office_id>/appointments")
def list_office_appointments(office_id):
    require_roles(["VerificationAgent", "FraudAnalyst", "SystemAdmin"])
    office = get_office(office_id)
    limit, offset = pagination()
    rows = [a for a in DB.appointments.values() if a["office_id"] == office["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(a) for a in items], total, limit, offset)
