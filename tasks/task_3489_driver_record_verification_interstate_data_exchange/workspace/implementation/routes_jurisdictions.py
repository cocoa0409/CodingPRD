"""Jurisdiction membership lifecycle (PRD section 3.1) and its nested
listings."""
from flask import Blueprint

import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("jurisdictions", __name__, url_prefix="/driver-exchange")

FEE_TIERS = {"TIER_1", "TIER_2", "TIER_3"}
MEMBERSHIP_STATUSES = {"APPLIED", "ACTIVE", "SUSPENDED", "WITHDRAWN"}

_TRANSITIONS = {
    ("APPLIED", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "WITHDRAWN"),
    ("SUSPENDED", "WITHDRAWN"),
}


@bp.post("/jurisdictions")
def create_jurisdiction():
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    data = v.body()
    code = v.req_string(data, "code")
    name = v.req_string(data, "name")
    fee_tier = v.req_enum(data, "fee_tier", FEE_TIERS)
    for existing in store.db.jurisdictions.values():
        if existing["code"] == code:
            raise err("ERR_JURISDICTION_CODE_TAKEN",
                      "jurisdiction code '%s' is already registered" % code)
    jurisdiction = {
        "id": store.new_id(),
        "code": code,
        "name": name,
        "fee_tier": fee_tier,
        "membership_status": "APPLIED",
        "certified_systems_count": 0,
        "timeliness_score_bp": 10000,
    }
    store.stamp(jurisdiction)
    store.db.jurisdictions[jurisdiction["id"]] = jurisdiction
    return ok(serialize.jurisdiction(jurisdiction), 201)


def _jurisdiction_or_404(jid):
    jurisdiction = store.db.jurisdictions.get(jid)
    if jurisdiction is None:
        raise err("ERR_JURISDICTION_NOT_FOUND", "no jurisdiction with id %s" % jid)
    return jurisdiction


@bp.get("/jurisdictions/<jid>")
def get_jurisdiction(jid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    return ok(serialize.jurisdiction(_jurisdiction_or_404(jid)))


@bp.patch("/jurisdictions/<jid>")
def patch_jurisdiction(jid):
    """Membership transitions (PRD section 3.1). APPLIED->ACTIVE is gated on a
    CERTIFIED POINTER_NETWORK participation; ACTIVE->SUSPENDED fires the
    two-link cascade; SUSPENDED->ACTIVE restores suspended participations;
    WITHDRAWN is terminal. Each applied transition bumps version exactly once.
    """
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    jurisdiction = _jurisdiction_or_404(jid)
    data = v.body()
    target = v.req_enum(data, "status", MEMBERSHIP_STATUSES)
    current = jurisdiction["membership_status"]
    if (current, target) not in _TRANSITIONS:
        raise err("ERR_INVALID_STATE",
                  "membership transition %s -> %s is not declared" % (current, target))
    if ((current, target) == ("APPLIED", "ACTIVE")
            and not state.has_certified_participation(jid, "POINTER_NETWORK")):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "activation requires a CERTIFIED POINTER_NETWORK participation")
    jurisdiction["membership_status"] = target
    if (current, target) == ("ACTIVE", "SUSPENDED"):
        state.jurisdiction_suspend_cascade(jurisdiction)
    elif (current, target) == ("SUSPENDED", "ACTIVE"):
        state.jurisdiction_reactivate_cascade(jurisdiction)
    store.touch(jurisdiction)
    return ok(serialize.jurisdiction(jurisdiction))


@bp.get("/jurisdictions/<jid>/system-participations")
def list_system_participations(jid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    _jurisdiction_or_404(jid)
    items = [p for p in store.db.participations.values()
             if p["jurisdiction_id"] == jid]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.participation(p) for p in page], limit, offset, total)


@bp.get("/jurisdictions/<jid>/fee-invoices")
def list_jurisdiction_fee_invoices(jid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    _jurisdiction_or_404(jid)
    items = [i for i in store.db.fee_invoices.values()
             if i["jurisdiction_id"] == jid]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.fee_invoice(i) for i in page], limit, offset, total)


@bp.get("/jurisdictions/<jid>/vehicle-titles")
def list_jurisdiction_vehicle_titles(jid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    _jurisdiction_or_404(jid)
    items = [t for t in store.db.vehicle_titles.values()
             if t["holding_jurisdiction_id"] == jid]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.vehicle_title(t) for t in page], limit, offset, total)
