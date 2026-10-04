"""Applicator certifications (PRD 3.9): issue and renew."""
from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from validate import (
    as_datetime,
    as_enum,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
)

bp = Blueprint("certifications", __name__)


@bp.post("/applicator-certifications")
def create_certification():
    caller = require_auth()
    require_role(caller, [constants.ROLE_CERTIFICATION_AUTHORITY])
    data = parse_body()
    reject_unknown(data, ["applicator_name", "state_code", "category", "certified_until"])
    applicator_name = as_str(data, "applicator_name", required=True)
    state_code = as_str(data, "state_code", required=True)
    category = as_enum(data, "category", constants.CERTIFICATION_CATEGORIES, required=True)
    certified_until = as_datetime(data, "certified_until", required=True)

    if certified_until <= clock.now():
        err(
            "ERR_INVALID_REQUEST",
            "certified_until must be strictly after the logical clock.",
        )

    row = new_row()
    row.update(
        {
            "applicator_name": applicator_name,
            "state_code": state_code,
            "category": category,
            "certified_until": certified_until,
            "status": "ACTIVE",
            "renewed_count": 0,
        }
    )
    store["certifications"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/applicator-certifications")
def list_certifications():
    require_auth()
    rows = list(store["certifications"].values())
    for key in ("state_code", "category", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/applicator-certifications/<certification_id>/renew")
def renew_certification(certification_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_CERTIFICATION_AUTHORITY])
    data = parse_body()
    reject_unknown(data, ["new_certified_until"])
    new_certified_until = as_datetime(data, "new_certified_until", required=True)

    cert = store["certifications"].get(certification_id)
    if cert is None:
        err("ERR_NOT_FOUND", "Applicator certification %s does not exist." % certification_id)

    if new_certified_until <= clock.now():
        err(
            "ERR_CERTIFICATION_RENEWAL_INVALID",
            "new_certified_until must be strictly after the logical clock.",
        )

    cert["certified_until"] = new_certified_until
    cert["status"] = "ACTIVE"
    cert["renewed_count"] += 1
    touch(cert)
    return ok(cert)
