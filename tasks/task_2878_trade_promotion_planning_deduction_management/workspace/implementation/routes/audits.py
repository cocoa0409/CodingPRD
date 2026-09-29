"""Contract-compliance audits (PRD 3.10)."""

from flask import Blueprint, g

import calc
import services
from calc import ZERO, q2
from db import clock_dt, db, new_row, touch
from errors import ApiError, bad_request
from response import created_response, object_response
from routes.common import (
    AUDIT_READ_ROLES,
    PREFIX,
    created_asc,
    created_desc,
    get_audit,
    get_customer,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_date,
    get_money,
    get_string,
    no_body,
    pagination,
    query_enum,
    query_value,
)

bp = Blueprint("audits", __name__)

AUDITOR = "ComplianceAuditor"
DIRECTOR = "TradeMarketingDirector"
AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED")


@bp.post(PREFIX + "/customers/<customer_id>/compliance-audits")
def open_audit(customer_id):
    authenticate([AUDITOR])
    data = body_fields(required=["scope_start", "scope_end"])
    scope_start = get_date(data, "scope_start")
    scope_end = get_date(data, "scope_end")
    if scope_end <= scope_start:
        raise bad_request("scope_end must be strictly after scope_start.")
    customer = get_customer(customer_id)
    # rung 67
    if customer["audit_status"] != "CLEAR":
        raise ApiError("ERR_AUDIT_ALREADY_OPEN")
    row = new_row()
    row.update({
        "customer_id": customer_id,
        "scope_start": scope_start,
        "scope_end": scope_end,
        "status": "SCHEDULED",
        "auditor_user_id": g.user_id,
        "findings_count": 0,
        "recovery_claim_amount": ZERO,
        "issued_at": None,
    })
    db.audits[row["id"]] = row
    customer["audit_status"] = "AUDIT_IN_PROGRESS"
    touch(customer)
    return created_response(calc.audit_out(row))


@bp.get(PREFIX + "/customers/<customer_id>/compliance-audits")
def list_customer_audits(customer_id):
    authenticate(AUDIT_READ_ROLES)
    limit, offset = pagination(["status"])
    status = query_enum("status", AUDIT_STATUSES)
    get_customer(customer_id)
    rows = calc.audits_of_customer(customer_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_asc(rows), limit, offset, calc.audit_out)


@bp.get(PREFIX + "/compliance-audits")
def list_audits():
    authenticate(AUDIT_READ_ROLES)
    limit, offset = pagination(["customer_id", "status"])
    customer_id = query_value("customer_id")
    status = query_enum("status", AUDIT_STATUSES)
    rows = list(db.audits.values())
    if customer_id is not None:
        get_customer(customer_id)
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_desc(rows), limit, offset, calc.audit_out)


@bp.get(PREFIX + "/compliance-audits/<audit_id>")
def read_audit(audit_id):
    authenticate(AUDIT_READ_ROLES)
    no_body()
    return object_response(calc.audit_out(get_audit(audit_id)))


@bp.post(PREFIX + "/compliance-audits/<audit_id>/record-finding")
def record_finding(audit_id):
    authenticate([AUDITOR])
    data = body_fields(required=["finding_code", "recovery_amount"])
    get_string(data, "finding_code", min_len=1, max_len=120)
    recovery_amount = get_money(data, "recovery_amount")
    audit = get_audit(audit_id)
    # rung 49
    if audit["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    audit["status"] = "IN_PROGRESS"
    audit["findings_count"] += 1
    audit["recovery_claim_amount"] = q2(audit["recovery_claim_amount"] + recovery_amount)
    touch(audit)
    return object_response(calc.audit_out(audit))


@bp.post(PREFIX + "/compliance-audits/<audit_id>/issue-findings")
def issue_findings(audit_id):
    authenticate([AUDITOR, DIRECTOR])
    no_body()
    audit = get_audit(audit_id)
    # rung 49
    if audit["status"] != "IN_PROGRESS" or audit["findings_count"] < 1:
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    audit["status"] = "FINDINGS_ISSUED"
    audit["issued_at"] = clock_dt()
    touch(audit)
    customer = db.customers.get(audit["customer_id"])
    if customer is not None:
        customer["audit_status"] = "FINDINGS_OPEN"
        touch(customer)
        services.rescore_customer(customer)
    return object_response(calc.audit_out(audit))
