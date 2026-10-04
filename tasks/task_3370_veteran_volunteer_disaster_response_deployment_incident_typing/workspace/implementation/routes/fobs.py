"""Forward operating base endpoints: establish and list per operation."""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain

bp = Blueprint("fob_sites", __name__)

FOB_READ_ROLES = ("SystemAdmin", "OperationsLead", "IncidentCommander", "SafetyOfficer")


@bp.post("/vdr/operations/<oid>/fob-sites")
def create_fob_site(oid):
    body = V.get_body()
    V.check_unknown(body, {"name", "bunks_total", "nightly_rate_cents"})
    name = V.req_str(body, "name")
    bunks_total = V.req_int(body, "bunks_total", lo=1)
    nightly_rate = V.req_int(body, "nightly_rate_cents", lo=0)
    auth.require_roles("OperationsLead")
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    fob = db.mint("fob_sites", {
        "operation_id": oid,
        "name": name,
        "bunks_total": bunks_total,
        "nightly_rate_cents": nightly_rate,
        "bunks_occupied": 0,
        "lodging_cost_cents": 0,
    })
    return envelope.ok(domain.public(fob), 201)


@bp.get("/vdr/operations/<oid>/fob-sites")
def list_fob_sites(oid):
    auth.require_roles(*FOB_READ_ROLES)
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    items = [f for f in db.all_of("fob_sites") if f["operation_id"] == oid]
    return envelope.paginate(domain.public_list(items))
