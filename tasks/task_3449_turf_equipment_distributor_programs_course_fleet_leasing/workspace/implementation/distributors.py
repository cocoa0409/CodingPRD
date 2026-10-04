"""Distributor network: distributors, compliance reviews, technicians."""
from flask import Blueprint

import calculations as calc
import clock
import helpers
from helpers import as_array, as_enum, as_int, as_iso_dt, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("distributors", __name__)

DISTRIBUTOR_CHANNELS = ("EQUIPMENT", "IRRIGATION")
CERT_LEVELS = ("APPRENTICE", "JOURNEYMAN", "MASTER")


def serialize_distributor(d):
    out = public(d)
    out["claims_paid_ytd_cents"] = calc.claims_paid_ytd(d["id"])
    return out


@bp.post("/distributors")
def create_distributor():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    b = body()
    name = as_str(req(b, "name"), "name")
    territory = as_array(req(b, "territory_codes"), "territory_codes")
    for t in territory:
        as_str(t, "territory_codes[]")
    channel = as_enum(req(b, "channel"), "channel", DISTRIBUTOR_CHANNELS)
    min_stock = as_int(req(b, "min_parts_stock_value_cents"), "min_parts_stock_value_cents")
    labor = as_int(req(b, "labor_rate_cents"), "labor_rate_cents")
    cap = as_int(req(b, "annual_claim_cap_cents"), "annual_claim_cap_cents")
    rec = new_record("distributors", {
        "name": name,
        "territory_codes": territory,
        "channel": channel,
        "min_parts_stock_value_cents": min_stock,
        "labor_rate_cents": labor,
        "annual_claim_cap_cents": cap,
        "status": "ONBOARDING",
        "fill_rate": 1.0,
        "stock_value_trailing_cents": 0,
        "committed_parts_cents": 0,
        "service_credit_balance_cents": 0,
    })
    return ok(serialize_distributor(rec), 201)


@bp.get("/distributors/<did>")
def get_distributor(did):
    role, uid = auth()
    require_role(role, ("CorporateAdmin", "DistributorManager"))
    d = helpers.get_or_404("distributors", did, "distributor")
    return ok(serialize_distributor(d))


def _cascade_c2(distributor_id):
    """Cascade C2 links 2-3: SPEC_REVIEW leases of this distributor revert to
    DRAFT (version += 1 each); on each reverted lease, appraisals in VALUED or
    DISPUTED are VOIDED and appraisals in ACCEPTED walk back to VALUED."""
    for lease in STORES["leases"].values():
        if lease["distributor_id"] == distributor_id and lease["status"] == "SPEC_REVIEW":
            lease["status"] = "DRAFT"
            touch(lease)
            for ap in STORES["appraisals"].values():
                if ap["lease_id"] != lease["id"]:
                    continue
                if ap["status"] in ("VALUED", "DISPUTED"):
                    ap["status"] = "VOIDED"
                    touch(ap)
                elif ap["status"] == "ACCEPTED":
                    ap["status"] = "VALUED"
                    touch(ap)


@bp.post("/distributors/<did>/compliance_review")
def compliance_review(did):
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    d = helpers.get_or_404("distributors", did, "distributor")
    fill_rate, stock_value, passed = calc.parts_stocking_compliance(d)
    d["fill_rate"] = fill_rate
    d["stock_value_trailing_cents"] = stock_value
    old = d["status"]
    new = old
    fire_c2 = False
    if old == "ONBOARDING":
        # Activation gate instead of the fill/stock test; failing leaves
        # status ONBOARDING and the review still returns 200.
        has_active_tech = any(
            t["distributor_id"] == did and t["cert_status"] == "CERT_ACTIVE"
            for t in STORES["technicians"].values()
        )
        if has_active_tech and len(d["territory_codes"]) > 0:
            new = "ACTIVE"
    elif old == "ACTIVE":
        if not passed:
            new = "PROBATION"
            fire_c2 = True
    elif old == "PROBATION":
        if passed:
            new = "ACTIVE"
        else:
            new = "SUSPENDED"
            fire_c2 = True
    elif old == "SUSPENDED":
        new = "ACTIVE" if passed else "TERMINATED"
    # TERMINATED: terminal; the review recomputes counters but changes nothing.
    if new != old:
        d["status"] = new
        touch(d)  # standing change increments version by 1
        if fire_c2:
            _cascade_c2(did)
    return ok(serialize_distributor(d))


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/technicians")
def create_technician():
    role, uid = auth()
    require_role(role, ("DistributorManager",))
    identity_entity(role, uid)
    b = body()
    full_name = as_str(req(b, "full_name"), "full_name")
    rec = new_record("technicians", {
        "distributor_id": uid,
        "full_name": full_name,
        "cert_level": None,
        "cert_status": "CERT_PENDING",
        "cert_expires_at": None,
        "_cert_expires_dt": None,
    })
    return ok(public(rec), 201)


@bp.get("/technicians/<tid>")
def get_technician(tid):
    role, uid = auth()
    require_role(role, ("CorporateAdmin", "DistributorManager"))
    t = helpers.get_or_404("technicians", tid, "technician")
    return ok(public(t))


@bp.get("/technicians")
def list_technicians():
    role, uid = auth()
    require_role(role, ("CorporateAdmin", "DistributorManager"))
    recs = helpers.apply_filters(sort_created(STORES["technicians"].values()),
                                 {"distributor_id": "distributor_id", "cert_status": "cert_status"})
    return helpers.paginate(recs)


@bp.post("/technicians/<tid>/certify")
def certify_technician(tid):
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    t = helpers.get_or_404("technicians", tid, "technician")
    b = body()
    level = as_enum(req(b, "level"), "level", CERT_LEVELS)
    expires_raw = req(b, "expires_at")
    expires_dt = as_iso_dt(expires_raw, "expires_at")
    # Cyclic machine: CERT_PENDING -> CERT_ACTIVE and CERT_EXPIRED -> CERT_ACTIVE.
    if t["cert_status"] not in ("CERT_PENDING", "CERT_EXPIRED"):
        fail("ERR_INVALID_STATE", "technician cannot be certified from " + t["cert_status"])
    if not (expires_dt > clock.now()):
        fail("ERR_INVALID_STATE", "expires_at must lie strictly after the current logical clock")
    t["cert_level"] = level
    t["cert_expires_at"] = expires_raw
    t["_cert_expires_dt"] = expires_dt
    t["cert_status"] = "CERT_ACTIVE"
    touch(t)
    return ok(public(t))
