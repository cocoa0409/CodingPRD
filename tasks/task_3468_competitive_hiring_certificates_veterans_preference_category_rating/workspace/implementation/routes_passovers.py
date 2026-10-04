"""Certificate entry reads and pass-over requests (PRD 3.8)."""
from flask import Blueprint

from auth import get_auth, require_roles
from cascade import auto_close_certificate, eval_certificate
from envelope import success_list, success_object
from errors import fail, not_found
from serializers import entry_out, pass_over_out
from store import DB, base_fields, touch
from validate import get_body, opt_str, parse_pagination, req_enum, req_str

bp = Blueprint("passovers", __name__)

REASON_CODES = ["INADEQUATE_EXPERIENCE", "MISCONDUCT", "OTHER"]


@bp.route("/hiring/entries/<entry_id>", methods=["GET"])
def read_entry(entry_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = DB.entries.get(entry_id)
    if row is None:
        not_found("certificate entry")
    return success_object(entry_out(row))


@bp.route("/hiring/entries/<entry_id>/pass-over-requests", methods=["GET"])
def list_entry_pass_overs(entry_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial", "OPMDelegate"])
    row = DB.entries.get(entry_id)
    if row is None:
        not_found("certificate entry")
    limit, offset = parse_pagination()
    items = [p for p in DB.pass_overs.values()
             if p["certificate_entry_id"] == row["id"] or p["desired_entry_id"] == row["id"]]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pass_over_out(p) for p in page], limit, offset, total)


@bp.route("/hiring/entries/<entry_id>/pass-over-requests", methods=["POST"])
def create_pass_over(entry_id):
    _, role = get_auth()
    require_roles(role, ["SelectingOfficial"])
    body = get_body()
    desired_entry_id = req_str(body, "desired_entry_id")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    justification = req_str(body, "justification")
    target = DB.entries.get(entry_id)
    if target is None:
        not_found("certificate entry")
    desired = DB.entries.get(desired_entry_id)
    if desired is None:
        not_found("desired certificate entry")
    cert = DB.certificates[target["certificate_id"]]
    eval_certificate(cert)
    if cert["status"] != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
    if not target["preference_eligible"] \
            or desired["preference_eligible"] \
            or not target["rank_position"] < desired["rank_position"]:
        fail("ERR_NOT_PREFERENCE_ELIGIBLE",
             "target must be preference-eligible and rank above a "
             "non-preference-eligible desired entry")
    row = base_fields()
    row.update({
        "certificate_entry_id": target["id"], "desired_entry_id": desired["id"],
        "reason_code": reason_code, "justification": justification,
        "adjudicated_by": None, "adjudication_note": None, "status": "PENDING",
    })
    DB.pass_overs[row["id"]] = row
    return success_object(pass_over_out(row), 201)


@bp.route("/hiring/pass-over-requests/<request_id>/adjudicate", methods=["POST"])
def adjudicate_pass_over(request_id):
    user_id, role = get_auth()
    require_roles(role, ["OPMDelegate"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["APPROVED", "DENIED"])
    note = opt_str(body, "adjudication_note")
    row = DB.pass_overs.get(request_id)
    if row is None:
        not_found("pass-over request")
    if row["status"] != "PENDING":
        fail("ERR_PASS_OVER_NOT_PENDING", "pass-over request is not PENDING")
    row["status"] = outcome
    row["adjudicated_by"] = user_id
    row["adjudication_note"] = note
    touch(row)
    if outcome == "APPROVED":
        target = DB.entries.get(row["certificate_entry_id"])
        if target is not None and target["status"] == "REFERRED":
            target["status"] = "PASSED_OVER"
            touch(target)
            cert = DB.certificates.get(target["certificate_id"])
            if cert is not None:
                auto_close_certificate(cert)
    return success_object(pass_over_out(row))
