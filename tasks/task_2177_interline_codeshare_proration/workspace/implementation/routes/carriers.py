"""Carrier membership endpoints (PRD section 3.1)."""

from flask import Blueprint

from errors import ApiError
from responses import ok, ok_list
from store import db, must_find, new_row, ordered, serialize, touch
import validation as V

bp = Blueprint("carriers", __name__)


def sweep_agreements(carrier):
    """Every ACTIVE agreement naming this carrier follows it out of force."""
    for agreement in ordered(list(db.agreements.values())):
        if agreement["status"] != "ACTIVE":
            continue
        if (agreement["issuing_carrier_id"] != carrier["id"]
                and agreement["partner_carrier_id"] != carrier["id"]):
            continue
        agreement["status"] = "SUSPENDED"
        agreement["suspension_reason"] = "CARRIER_SUSPENDED"
        touch(agreement)


@bp.route("/interline/carriers", methods=["POST"])
def create_carrier():
    V.require([V.ROLE_OPERATOR])
    data = V.body()
    iata_code = V.req_str(data, "iata_code")
    name = V.req_str(data, "name")
    base_currency = V.req_enum(data, "base_currency", V.CURRENCIES)
    credit_limit = V.req_int(data, "credit_limit_minor", minimum=0)

    carrier = new_row({
        "iata_code": iata_code,
        "name": name,
        "base_currency": base_currency,
        "credit_limit_minor": credit_limit,
        "status": "ACTIVE",
        "pending_receivable_minor": 0,
        "pending_payable_minor": 0,
        "settled_receivable_minor": 0,
        "settled_payable_minor": 0,
        "net_position_minor": 0,
        "period_accrued_miles": 0,
        "period_ffp_cost_estimate_minor": 0,
        "period_ffp_cost_trued_up_minor": 0,
        "ffp_true_up_delta_minor": 0,
        "open_reproration_count": 0,
        "audit_flag": False,
    })
    db.carriers[carrier["id"]] = carrier
    return ok(serialize(carrier), 201)


@bp.route("/interline/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    V.require(V.ALL_ROLES)
    carrier = must_find("carrier", carrier_id)
    return ok(serialize(carrier))


@bp.route("/interline/carriers", methods=["GET"])
def list_carriers():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    status = V.filter_enum("status", V.CARRIER_STATUSES)
    rows = list(db.carriers.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/carriers/<carrier_id>/suspend", methods=["POST"])
def suspend_carrier(carrier_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    carrier = must_find("carrier", carrier_id)
    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_STATE_INVALID")
    carrier["status"] = "SUSPENDED"
    touch(carrier)
    sweep_agreements(carrier)
    return ok(serialize(carrier))


@bp.route("/interline/carriers/<carrier_id>/reinstate", methods=["POST"])
def reinstate_carrier(carrier_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    carrier = must_find("carrier", carrier_id)
    if carrier["status"] != "SUSPENDED":
        raise ApiError("ERR_CARRIER_STATE_INVALID")
    carrier["status"] = "ACTIVE"
    touch(carrier)
    return ok(serialize(carrier))
