"""Institution, agreement, reporting-period, user, and institution-scoped
dataset endpoints (PRD §3.1, §3.2, §3.9).
"""
from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import db
from auth import (
    ROLE_ANALYST,
    ROLE_CERTIFIER,
    ROLE_CLEARINGHOUSE_OPS,
    ROLE_SUBMITTER,
    authenticate,
    require_registrar_tenancy,
    require_role,
)
from core import (
    ERR_AGREEMENT_OVERLAP,
    ERR_AGREEMENT_LAPSED,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PERIOD_OVERLAP,
    ERR_VALIDATION,
    get_body,
    list_response,
    ok_object,
    raise_err,
    req_date,
    req_enum,
    req_field,
    req_str,
)

bp = Blueprint("institutions", __name__)

OPS_AND_REGISTRAR = (ROLE_CLEARINGHOUSE_OPS, ROLE_SUBMITTER, ROLE_CERTIFIER)


def _get_institution(iid):
    inst = db.store.institutions.get(iid)
    if inst is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    return inst


def _period_status_for(now, opens, due, grace):
    if now > grace:
        return "CLOSED"
    if now > due:
        return "GRACE"
    if now >= opens:
        return "OPEN"
    return "SCHEDULED"


@bp.route("/institutions", methods=["POST"])
def create_institution():
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    data = get_body()
    name = req_str(data, "name")
    ope_id = req_str(data, "ope_id")
    users_in = req_field(data, "users")
    if not isinstance(users_in, list):
        raise_err(ERR_VALIDATION, "field 'users' must be an array")
    seen_emails = set()
    for u in users_in:
        if not isinstance(u, dict):
            raise_err(ERR_VALIDATION, "each user must be an object")
        email = req_str(u, "email")
        req_enum(u, "role", ("SUBMITTER", "CERTIFIER"))
        if email in seen_emails:
            raise_err(ERR_VALIDATION, "user emails must be unique within the institution")
        seen_emails.add(email)
    for inst in db.store.institutions.values():
        if inst["ope_id"] == ope_id:
            raise_err(ERR_VALIDATION, "ope_id must be unique across institutions")

    inst = db.new_entity(
        {
            "name": name,
            "ope_id": ope_id,
            "status": "ACTIVE",
            "suspension_reason": "NONE",
            "compliance_standing": "COMPLIANT",
        }
    )
    db.store.institutions[inst["id"]] = inst
    users = []
    for u in users_in:
        iu = db.new_entity(
            {
                "institution_id": inst["id"],
                "email": u["email"],
                "role": u["role"],
                "status": "ACTIVE",
            }
        )
        db.store.users[iu["id"]] = iu
        users.append(iu)
    out = db.serialize(inst)
    # Embedded on the create response only, in input order (PRD §3.1).
    out["users"] = [db.serialize(u) for u in users]
    return ok_object(out, 201)


@bp.route("/institutions/<iid>", methods=["GET"])
def get_institution(iid):
    caller = authenticate()
    require_role(caller, *OPS_AND_REGISTRAR)
    require_registrar_tenancy(caller, iid)
    return ok_object(db.serialize(_get_institution(iid)))


@bp.route("/institutions/<iid>/suspend", methods=["POST"])
def suspend_institution(iid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    inst = _get_institution(iid)
    if inst["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "only an ACTIVE institution can be suspended")
    cascade.suspend_institution(inst, "OPS")
    return ok_object(db.serialize(inst))


@bp.route("/institutions/<iid>/reinstate", methods=["POST"])
def reinstate_institution(iid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    inst = _get_institution(iid)
    if inst["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "only a SUSPENDED institution can be reinstated")
    if not cascade.active_agreement_covers(iid):
        raise_err(ERR_AGREEMENT_LAPSED, "an ACTIVE agreement covering now is required to reinstate")
    inst["status"] = "ACTIVE"
    inst["suspension_reason"] = "NONE"
    db.touch(inst)
    return ok_object(db.serialize(inst))


@bp.route("/institutions/<iid>/agreements", methods=["POST"])
def create_agreement(iid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    inst = _get_institution(iid)
    data = get_body()
    effective_from = req_date(data, "effective_from")
    effective_to = req_date(data, "effective_to")
    # Overlap rule (SCAFFOLD priority 30) precedes field ordering (priority 38).
    for a in db.store.agreements.values():
        if a["institution_id"] == iid and a["status"] in ("SCHEDULED", "ACTIVE"):
            if effective_from < a["effective_to"] and effective_to > a["effective_from"]:
                raise_err(ERR_AGREEMENT_OVERLAP, "agreement window overlaps an existing agreement")
    if not effective_to > effective_from:
        raise_err(ERR_VALIDATION, "effective_to must be strictly after effective_from")
    now = db.now()
    status = "ACTIVE" if (effective_from <= now < effective_to) else "SCHEDULED"
    ag = db.new_entity(
        {
            "institution_id": iid,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": status,
        }
    )
    db.store.agreements[ag["id"]] = ag
    # Automatic recovery from agreement-lapse suspension (PRD §3.1).
    if status == "ACTIVE" and inst["status"] == "SUSPENDED" and inst["suspension_reason"] == "AGREEMENT_LAPSE":
        inst["status"] = "ACTIVE"
        inst["suspension_reason"] = "NONE"
        db.touch(inst)
    return ok_object(db.serialize(ag), 201)


@bp.route("/institutions/<iid>/agreements", methods=["GET"])
def list_agreements(iid):
    caller = authenticate()
    require_role(caller, *OPS_AND_REGISTRAR)
    require_registrar_tenancy(caller, iid)
    _get_institution(iid)
    items = db.sorted_created(a for a in db.store.agreements.values() if a["institution_id"] == iid)
    return list_response(items, db.serialize)


@bp.route("/institutions/<iid>/reporting-periods", methods=["POST"])
def create_period(iid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    _get_institution(iid)
    data = get_body()
    term_label = req_str(data, "term_label")
    term_start = req_date(data, "term_start")
    term_end = req_date(data, "term_end")
    opens = req_date(data, "submission_opens_at")
    due = req_date(data, "submission_due_at")
    # Closed-occupancy rule (priority 31) precedes field ordering (priority 38).
    for p in db.store.periods.values():
        if p["institution_id"] == iid and not (term_start > p["submission_due_at"]):
            raise_err(
                ERR_PERIOD_OVERLAP,
                "term_start must be strictly after every existing period's submission_due_at",
            )
    if not term_end > term_start:
        raise_err(ERR_VALIDATION, "term_end must be strictly after term_start")
    if not (opens >= term_start and opens < due):
        raise_err(ERR_VALIDATION, "submission_opens_at must be >= term_start and < submission_due_at")
    grace = due + timedelta(days=calc.GRACE_PERIOD_DAYS)
    status = _period_status_for(db.now(), opens, due, grace)
    period = db.new_entity(
        {
            "institution_id": iid,
            "term_label": term_label,
            "term_start": term_start,
            "term_end": term_end,
            "submission_opens_at": opens,
            "submission_due_at": due,
            "grace_ends_at": grace,
            "status": status,
            "outcome": "NONE",
            "upload_count": 0,
        }
    )
    db.store.periods[period["id"]] = period
    if status == "CLOSED":
        # Window entirely in the past: closes immediately, never certified.
        cascade.close_period(period)
    return ok_object(db.serialize(period), 201)


@bp.route("/institutions/<iid>/reporting-periods", methods=["GET"])
def list_periods(iid):
    caller = authenticate()
    require_role(caller, *OPS_AND_REGISTRAR)
    require_registrar_tenancy(caller, iid)
    _get_institution(iid)
    items = [p for p in db.store.periods.values() if p["institution_id"] == iid]
    items.sort(key=lambda p: p["_seq"])  # created_at ASC tiebreak
    items.sort(key=lambda p: p["submission_due_at"])  # stable: due ASC
    return list_response(items, db.serialize)


@bp.route("/institutions/<iid>/users", methods=["GET"])
def list_users(iid):
    caller = authenticate()
    require_role(caller, *OPS_AND_REGISTRAR)
    require_registrar_tenancy(caller, iid)
    _get_institution(iid)
    items = db.sorted_created(u for u in db.store.users.values() if u["institution_id"] == iid)
    return list_response(items, db.serialize)


@bp.route("/institutions/<iid>/research-datasets", methods=["GET"])
def list_institution_datasets(iid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS, ROLE_SUBMITTER, ROLE_CERTIFIER, ROLE_ANALYST)
    require_registrar_tenancy(caller, iid)
    _get_institution(iid)
    items = [d for d in db.store.datasets.values() if d["scope_institution_id"] == iid]
    if caller.role == ROLE_ANALYST:
        items = [d for d in items if d["created_by_analyst_id"] == caller.user_id]
    return list_response(db.sorted_created(items), db.serialize)
