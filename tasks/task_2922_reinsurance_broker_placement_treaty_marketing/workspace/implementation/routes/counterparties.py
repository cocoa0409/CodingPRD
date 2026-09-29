"""The logical clock and the counterparty registry (PRD 3.1)."""
from flask import Blueprint

import db
import enums
import response
import serialize
import services
import validate
from errors import fail
from middleware import COMPLIANCE_OFFICER, PLATFORM_ADMIN, require
from routes._common import CEDENT_READ, REINSURER_READ, ordered_filtered, paged, q
from util import fmt_instant

bp = Blueprint("counterparties", __name__)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require((PLATFORM_ADMIN,))
    shape = validate.Shape()
    instant = shape.instant("current_utc")
    db.set_now(instant)
    return response.object_response({"current_utc": fmt_instant(instant)}, 200)


# ---------------------------------------------------------------------------
# Cedents
# ---------------------------------------------------------------------------

def _duplicate_name(collection, name):
    lowered = name.lower()
    for row in collection.values():
        if row["name"].lower() == lowered:
            return True
    return False


@bp.route("/cedents", methods=["POST"])
def create_cedent():
    require((PLATFORM_ADMIN,))
    shape = validate.Shape()
    name = shape.string("name", min_len=1, max_len=120)
    domicile_code = shape.upper_code("domicile_code", 5)
    financial_rating = shape.enum("financial_rating", enums.FINANCIAL_RATINGS)

    if _duplicate_name(db.cedents, name):
        fail("ERR_DUPLICATE_NAME", "a cedent named %s already exists" % name)

    row = db.base_row()
    row.update({
        "name": name,
        "domicile_code": domicile_code,
        "financial_rating": financial_rating,
        "status": "ACTIVE",
        "suspension_reason": None,
        "settled_receipts_minor": 0,
        "outstanding_reinstatement_premium_minor": 0,
    })
    db.cedents[row["id"]] = row
    return response.object_response(serialize.cedent(row), 201)


@bp.route("/cedents", methods=["GET"])
def list_cedents():
    require(CEDENT_READ)
    rows = ordered_filtered(db.cedents, [
        ("status", q("status")),
        ("financial_rating", q("financial_rating")),
    ])
    return paged(rows, serialize.cedent)


@bp.route("/cedents/<cedent_id>", methods=["GET"])
def read_cedent(cedent_id):
    require(CEDENT_READ)
    row = services.get_cedent(cedent_id)
    return response.object_response(serialize.cedent(row), 200)


@bp.route("/cedents/<cedent_id>/suspension", methods=["POST"])
def set_cedent_suspension(cedent_id):
    require((COMPLIANCE_OFFICER,))
    shape = validate.Shape()
    status = shape.enum("status", enums.CEDENT_STATUSES)
    suspension_reason = shape.string("suspension_reason", min_len=1, max_len=500)

    cedent = services.get_cedent(cedent_id)
    cedent["status"] = status
    cedent["suspension_reason"] = suspension_reason
    db.touch(cedent)
    return response.object_response(serialize.cedent(cedent), 200)


@bp.route("/cedents/<cedent_id>/programs", methods=["GET"])
def list_cedent_programs(cedent_id):
    require(CEDENT_READ)
    validate.pagination()
    services.get_cedent(cedent_id)
    rows = [r for r in db.ordered(db.programs) if r["cedent_id"] == cedent_id]
    rows = ordered_filtered({r["id"]: r for r in rows}, [
        ("placement_status", q("placement_status")),
        ("documentation_status", q("documentation_status")),
        ("line_of_business", q("line_of_business")),
    ])
    return paged(rows, serialize.program)


# ---------------------------------------------------------------------------
# Reinsurers
# ---------------------------------------------------------------------------

@bp.route("/reinsurers", methods=["POST"])
def create_reinsurer():
    require((PLATFORM_ADMIN,))
    shape = validate.Shape()
    name = shape.string("name", min_len=1, max_len=120)
    security_rating = shape.enum("security_rating", enums.SECURITY_RATINGS)
    capacity_limit_minor = shape.money("capacity_limit_minor", minimum=None,
                                       exclusive_min=0)
    max_line_pct = shape.percent("max_line_pct", exclusive_min=0, maximum=100)
    lead_authorised = shape.boolean("lead_authorised", required=False, default=False)

    if _duplicate_name(db.reinsurers, name):
        fail("ERR_DUPLICATE_NAME", "a reinsurer named %s already exists" % name)

    row = db.base_row()
    row.update({
        "name": name,
        "security_rating": security_rating,
        "capacity_limit_minor": capacity_limit_minor,
        "max_line_pct": max_line_pct,
        "lead_authorised": lead_authorised,
        "security_status": "APPROVED",
        "committed_capacity_minor": 0,
        "available_capacity_minor": capacity_limit_minor,
    })
    db.reinsurers[row["id"]] = row
    return response.object_response(serialize.reinsurer(row), 201)


@bp.route("/reinsurers", methods=["GET"])
def list_reinsurers():
    require(REINSURER_READ)
    rows = ordered_filtered(db.reinsurers, [
        ("security_status", q("security_status")),
        ("security_rating", q("security_rating")),
    ])
    flag = validate.query_bool("lead_authorised")
    if flag is not None:
        rows = [r for r in rows if r["lead_authorised"] is flag]
    return paged(rows, serialize.reinsurer)


@bp.route("/reinsurers/<reinsurer_id>", methods=["GET"])
def read_reinsurer(reinsurer_id):
    require(REINSURER_READ)
    row = services.get_reinsurer(reinsurer_id)
    return response.object_response(serialize.reinsurer(row), 200)


@bp.route("/reinsurers/<reinsurer_id>/security-status", methods=["POST"])
def set_security_status(reinsurer_id):
    require((COMPLIANCE_OFFICER,))
    shape = validate.Shape()
    security_status = shape.enum("security_status", enums.SECURITY_STATUSES)
    shape.string("reason", min_len=1, max_len=500)

    market = services.get_reinsurer(reinsurer_id)
    market["security_status"] = security_status
    db.touch(market)
    if security_status == "SUSPENDED":
        services.security_suspension_cascade(market)
    return response.object_response(serialize.reinsurer(market), 200)


@bp.route("/reinsurers/<reinsurer_id>/signing-lines", methods=["GET"])
def list_reinsurer_lines(reinsurer_id):
    require(REINSURER_READ)
    validate.pagination()
    services.get_reinsurer(reinsurer_id)
    rows = [r for r in db.ordered(db.signing_lines)
            if r["reinsurer_id"] == reinsurer_id]
    status = q("status")
    layer_id = q("layer_id")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if layer_id is not None:
        rows = [r for r in rows if r["layer_id"] == layer_id]
    return paged(rows, serialize.signing_line)


@bp.route("/reinsurers/<reinsurer_id>/market-submissions", methods=["GET"])
def list_reinsurer_submissions(reinsurer_id):
    require(REINSURER_READ)
    validate.pagination()
    services.get_reinsurer(reinsurer_id)
    rows = [r for r in db.ordered(db.market_submissions)
            if r["reinsurer_id"] == reinsurer_id]
    status = q("status")
    layer_id = q("layer_id")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if layer_id is not None:
        rows = [r for r in rows if r["layer_id"] == layer_id]
    return paged(rows, serialize.market_submission)
