"""Job announcement endpoints (PRD 3.2): construction, open period,
cancellation cascade, and FK-reverse lists."""
from flask import Blueprint

from auth import get_auth, require_roles
from calc import DEFAULT_BQ_CUT, DEFAULT_WQ_CUT
from cascade import cancel_announcement_cascade
from envelope import success_list, success_object
from errors import fail, invalid_state, not_found
from serializers import announcement_out, application_out, certificate_out
from store import DB, base_fields, now, touch
from validate import get_body, opt_int, opt_query, parse_pagination, req_dt, req_enum, req_int, req_str

bp = Blueprint("announcements", __name__)

AREAS = ["ALL_US_CITIZENS", "STATUS_CANDIDATES", "AGENCY_ONLY"]
AUTHORITIES = ["COMPETITIVE", "DIRECT_HIRE", "VEOA", "SCHEDULE_A", "NONCOMPETITIVE_SPOUSE"]
METHODS = ["CATEGORY_RATING", "UNRANKED"]


def get_announcement_or_404(announcement_id):
    row = DB.announcements.get(announcement_id)
    if row is None:
        not_found("announcement")
    return row


@bp.route("/hiring/positions/<position_id>/announcements", methods=["POST"])
def create_announcement(position_id):
    _, role = get_auth()
    require_roles(role, ["HiringManager"])
    body = get_body()
    number = req_str(body, "announcement_number")
    area = req_enum(body, "area_of_consideration", AREAS)
    authority = req_enum(body, "hiring_authority", AUTHORITIES)
    method = req_enum(body, "assessment_method", METHODS)
    open_at = req_dt(body, "open_at")
    close_at = req_dt(body, "close_at")
    if not close_at > open_at:
        fail("ERR_INVALID_REQUEST", "close_at must be strictly later than open_at")
    vacancies = req_int(body, "vacancies_count", 1)
    bq_cut = opt_int(body, "bq_cut", 70, 100)
    wq_cut = opt_int(body, "wq_cut", 70, 100)
    if bq_cut is None:
        bq_cut = DEFAULT_BQ_CUT
    if wq_cut is None:
        wq_cut = DEFAULT_WQ_CUT
    if not wq_cut < bq_cut:
        fail("ERR_INVALID_REQUEST", "wq_cut must be below bq_cut")
    validity = opt_int(body, "certificate_validity_days", 30, 90)
    if validity is None:
        validity = 60
    position = DB.positions.get(position_id)
    if position is None:
        not_found("position")
    # Priority 7 (scaffold table order): period overlap, duplicate key,
    # authority/method coherence.
    for sib in DB.announcements.values():
        if sib["position_id"] != position_id:
            continue
        if open_at < sib["close_at"] and sib["open_at"] < close_at:
            fail("ERR_ANNOUNCEMENT_PERIOD_OVERLAP",
                 "open period overlaps a sibling announcement")
    for a in DB.announcements.values():
        if a["announcement_number"] == number:
            fail("ERR_DUPLICATE_KEY", "announcement_number already exists")
    if authority == "COMPETITIVE" and method != "CATEGORY_RATING":
        fail("ERR_AUTHORITY_METHOD_MISMATCH", "COMPETITIVE requires CATEGORY_RATING")
    if authority == "DIRECT_HIRE" and method != "UNRANKED":
        fail("ERR_AUTHORITY_METHOD_MISMATCH", "DIRECT_HIRE requires UNRANKED")
    # Priority 9: position must be CLASSIFIED.
    if position["status"] != "CLASSIFIED":
        fail("ERR_POSITION_NOT_CLASSIFIED", "position is not CLASSIFIED")
    row = base_fields()
    row.update({
        "position_id": position_id, "announcement_number": number,
        "area_of_consideration": area, "hiring_authority": authority,
        "assessment_method": method, "open_at": open_at, "close_at": close_at,
        "vacancies_count": vacancies, "bq_cut": bq_cut, "wq_cut": wq_cut,
        "certificate_validity_days": validity,
        "remaining_vacancies": vacancies, "status": "DRAFT",
    })
    DB.announcements[row["id"]] = row
    return success_object(announcement_out(row), 201)


@bp.route("/hiring/announcements/<announcement_id>", methods=["GET"])
def read_announcement(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "HiringManager", "SelectingOfficial",
                         "OPMDelegate", "Applicant", "SME"])
    row = get_announcement_or_404(announcement_id)
    return success_object(announcement_out(row))


@bp.route("/hiring/positions/<position_id>/announcements", methods=["GET"])
def list_position_announcements(position_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "HiringManager", "SelectingOfficial"])
    if position_id not in DB.positions:
        not_found("position")
    limit, offset = parse_pagination()
    items = [a for a in DB.announcements.values() if a["position_id"] == position_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([announcement_out(a) for a in page], limit, offset, total)


@bp.route("/hiring/announcements/<announcement_id>/open", methods=["POST"])
def open_announcement(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HiringManager"])
    get_body()
    row = get_announcement_or_404(announcement_id)
    if row["status"] != "DRAFT":
        invalid_state("announcement is not DRAFT")
    if not now() < row["close_at"]:
        invalid_state("open period has already ended")
    row["status"] = "OPEN"
    touch(row)
    return success_object(announcement_out(row))


@bp.route("/hiring/announcements/<announcement_id>/close", methods=["POST"])
def close_announcement(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HiringManager"])
    get_body()
    row = get_announcement_or_404(announcement_id)
    if row["status"] != "OPEN":
        invalid_state("announcement is not OPEN")
    row["status"] = "CLOSED"
    touch(row)
    return success_object(announcement_out(row))


@bp.route("/hiring/announcements/<announcement_id>/cancel", methods=["POST"])
def cancel_announcement(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HiringManager"])
    get_body()
    row = get_announcement_or_404(announcement_id)
    if row["status"] not in ("DRAFT", "OPEN", "CLOSED", "CERT_ISSUED"):
        invalid_state("announcement cannot be cancelled from %s" % row["status"])
    from_status = row["status"]
    cancel_announcement_cascade(row, from_status)
    row["status"] = "CANCELLED"
    touch(row)
    return success_object(announcement_out(row))


@bp.route("/hiring/announcements/<announcement_id>/applications", methods=["GET"])
def list_announcement_applications(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = get_announcement_or_404(announcement_id)
    limit, offset = parse_pagination()
    status_filter = opt_query("status")
    items = [a for a in DB.applications.values() if a["announcement_id"] == row["id"]]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([application_out(a) for a in page], limit, offset, total)


@bp.route("/hiring/announcements/<announcement_id>/certificates", methods=["GET"])
def list_announcement_certificates(announcement_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = get_announcement_or_404(announcement_id)
    limit, offset = parse_pagination()
    items = [c for c in DB.certificates.values() if c["announcement_id"] == row["id"]]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([certificate_out(c) for c in page], limit, offset, total)
