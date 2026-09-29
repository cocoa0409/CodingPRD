from decimal import Decimal

from flask import Blueprint

import db
import services
from core import (JURISDICTION_RE, auth, body, get_bool, get_date, get_enum, get_int,
                  get_str, ok, pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("institutions", __name__)

ACCREDITATION = ("ACCREDITED", "PROVISIONAL", "SUSPENDED", "TERMINATED")


@bp.post("/institutions")
@auth("AccreditationAdmin")
def create_institution():
    b = body()
    name = get_str(b, "name", required=True)
    jurisdiction = get_str(b, "jurisdiction_code", required=True, pattern=JURISDICTION_RE)
    status = get_enum(b, "accreditation_status", ACCREDITATION, default="ACCREDITED")
    expires_on, expires_raw = get_date(b, "accreditation_expires_on", required=True)
    capacity = get_int(b, "holding_capacity_slots", required=True, minimum=0)
    policy = get_bool(b, "disposition_policy_on_file", default=False)

    rec = db.insert(db.institutions, {
        "name": name,
        "jurisdiction_code": jurisdiction,
        "accreditation_status": status,
        "accreditation_expires_on": expires_raw,
        "holding_capacity_slots": capacity,
        "disposition_policy_on_file": policy,
        "transfer_credit_balance": Decimal("0.00"),
        "compliance_points_balance": Decimal("0.00"),
    })
    return ok(services.institution_out(rec), 201)


@bp.patch("/institutions/<institution_id>")
@auth("AccreditationAdmin")
def patch_institution(institution_id):
    b = body()
    status = get_enum(b, "accreditation_status", ACCREDITATION)
    expires_on, expires_raw = get_date(b, "accreditation_expires_on")
    capacity = get_int(b, "holding_capacity_slots", minimum=0)
    policy = get_bool(b, "disposition_policy_on_file")

    rec = db.get_institution(institution_id)
    if status is not None:
        rec["accreditation_status"] = status
    if expires_raw is not None:
        rec["accreditation_expires_on"] = expires_raw
    if capacity is not None:
        rec["holding_capacity_slots"] = capacity
    if policy is not None:
        rec["disposition_policy_on_file"] = policy
    db.touch(rec)
    return ok(services.institution_out(rec))


@bp.get("/institutions/<institution_id>")
@auth()
def read_institution(institution_id):
    return ok(services.institution_out(db.get_institution(institution_id)))


@bp.get("/institutions")
@auth()
def list_institutions():
    limit, offset = pagination()
    jurisdiction = q_str("jurisdiction_code")
    status = q_enum("accreditation_status", ACCREDITATION)
    rows = list(db.institutions.values())
    if jurisdiction is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == jurisdiction]
    if status is not None:
        rows = [r for r in rows if r["accreditation_status"] == status]
    return paginate(sorted_rows(rows), limit, offset, services.institution_out)
