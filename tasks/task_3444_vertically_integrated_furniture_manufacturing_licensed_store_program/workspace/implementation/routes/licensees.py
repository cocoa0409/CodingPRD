"""Licensees (PRD §3.2): onboarding, OCC terms, admin status machine, cascade."""
from flask import Blueprint

from constants import (
    DEFAULT_AUDIT_SCORE, DEFAULT_MERCH_STANDARD, DEFAULT_ROYALTY_RATE,
    LICENSEE_STATUSES,
)
from db import store
from errors import err
from middleware import auth, require_role
from services.engine import terminate_licensee
from util import (
    get_body, new_record, ok_list, ok_object, opt_int, opt_number, opt_str,
    paginate, req_enum, req_int, req_str, serialize, touch,
)

bp = Blueprint("licensees", __name__)

# Admin-driven edges (PRD §3.2); system edges (PROBATION etc.) are not admin-callable.
_LICENSEE_EDGES = {
    ("APPLICANT", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("APPLICANT", "TERMINATED"),
    ("ACTIVE", "TERMINATED"),
    ("PROBATION", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


def get_licensee(lid):
    lic = store.licensees.get(lid)
    if lic is None:
        err("ERR_LICENSEE_NOT_FOUND", "unknown licensee id")
    return lic


@bp.route("/api/licensees", methods=["POST"])
def create_licensee():
    _uid, role = auth()
    data = get_body()
    business_name = req_str(data, "business_name")
    royalty_rate = opt_number(data, "royalty_rate", DEFAULT_ROYALTY_RATE)
    msv = opt_str(data, "merchandising_standard_version", DEFAULT_MERCH_STANDARD)
    audit = opt_int(data, "latest_audit_score", DEFAULT_AUDIT_SCORE, minimum=0, maximum=100)
    require_role(role, ["PlatformAdmin"])
    rec = new_record()
    rec.update({
        "business_name": business_name,
        "royalty_rate": royalty_rate,
        "merchandising_standard_version": msv,
        "latest_audit_score": audit,
        "status": "APPLICANT",
        "last_cycle_score": None,
        "seasoned_score": None,
        "royalty_accrued_cents": 0,
        "chargeback_cents": 0,
        "net_royalty_cents": 0,
    })
    store.licensees[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/licensees/<lid>", methods=["GET"])
def fetch_licensee(lid):
    auth()
    return ok_object(serialize(get_licensee(lid)), 200)


@bp.route("/api/licensees/<lid>/terms", methods=["PUT"])
def update_terms(lid):
    _uid, role = auth()
    data = get_body()
    expected = req_int(data, "expected_licensee_version")
    royalty_rate = opt_number(data, "royalty_rate", None)
    msv = opt_str(data, "merchandising_standard_version", None)
    audit = opt_int(data, "latest_audit_score", None, minimum=0, maximum=100)
    require_role(role, ["PlatformAdmin"])
    lic = get_licensee(lid)
    if expected != lic["version"]:
        err("ERR_STALE_LICENSEE_VERSION", "expected_licensee_version is stale")
    bumped = set()
    if royalty_rate is not None:
        lic["royalty_rate"] = royalty_rate
    if msv is not None:
        lic["merchandising_standard_version"] = msv
    if audit is not None:
        lic["latest_audit_score"] = audit
    touch(lic, bumped)
    return ok_object(serialize(lic), 200)


@bp.route("/api/licensees/<lid>/transition", methods=["POST"])
def transition_licensee(lid):
    _uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", LICENSEE_STATUSES)
    require_role(role, ["PlatformAdmin"])
    lic = get_licensee(lid)
    if (lic["status"], to_state) not in _LICENSEE_EDGES:
        err("ERR_INVALID_TRANSITION", "licensee cannot move %s -> %s" % (lic["status"], to_state))
    bumped = set()
    lic["status"] = to_state
    touch(lic, bumped)
    if to_state == "TERMINATED":
        terminate_licensee(lic, bumped)
    return ok_object(serialize(lic), 200)


@bp.route("/api/licensees/<lid>/territories", methods=["GET"])
def list_licensee_territories(lid):
    auth()
    get_licensee(lid)
    items = [t for t in store.territories.values() if t["assigned_licensee_id"] == lid]
    page, pagination = paginate(items)
    return ok_list([serialize(t) for t in page], pagination)
