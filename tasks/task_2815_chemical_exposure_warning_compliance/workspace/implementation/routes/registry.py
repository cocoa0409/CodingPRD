"""The listed-chemical registry (PRD 3.1)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard, READ_ALL_BUT_SUPPLIER
from util import D, days, out_num
from routes.common import list_endpoint
from services import cascade

bp = Blueprint("registry", __name__)

ENDPOINT_TYPES = ("CANCER", "REPRODUCTIVE_MALE", "REPRODUCTIVE_FEMALE", "DEVELOPMENTAL")
BASES = ("NSRL", "MADL", "NONE")
GRACE_PERIOD_DAYS = 365
TRIGGERS = ("LIST", "WITHDRAW", "DELIST", "RELIST", "REVISE_SAFE_HARBOR")
LEGAL = {
    "LIST": ("PROPOSED",),
    "WITHDRAW": ("PROPOSED",),
    "DELIST": ("LISTED",),
    "RELIST": ("DELISTED",),
    "REVISE_SAFE_HARBOR": ("LISTED",),
}
CREATE_FIELDS = ("chemical_name", "cas_number", "endpoint_type", "safe_harbor_basis",
                 "safe_harbor_level_ug_per_day")


def harm_class(endpoint_type):
    return "CANCER" if endpoint_type == "CANCER" else "REPRODUCTIVE"


def check_basis_level(basis, level):
    """Priority 8: the arithmetic coherence rule."""
    if basis in ("NSRL", "MADL") and level is None:
        fail("ERR_SAFE_HARBOR_BASIS_MISMATCH",
             "a %s basis requires a safe_harbor_level_ug_per_day" % basis)
    if basis == "NONE" and level is not None:
        fail("ERR_SAFE_HARBOR_BASIS_MISMATCH",
             "a NONE basis may not carry a safe_harbor_level_ug_per_day")


def check_basis_endpoint(endpoint_type, basis):
    """Priority 9: the toxicological alignment rule, at registration only."""
    if endpoint_type == "CANCER" and basis == "MADL":
        fail("ERR_SAFE_HARBOR_BASIS_MISMATCH", "a CANCER endpoint may not carry a MADL basis")
    if endpoint_type in ("REPRODUCTIVE_MALE", "REPRODUCTIVE_FEMALE", "DEVELOPMENTAL") \
            and basis == "NSRL":
        fail("ERR_SAFE_HARBOR_BASIS_MISMATCH",
             "a %s endpoint may not carry an NSRL basis" % endpoint_type)


@bp.route("/listed-chemicals", methods=["POST"])
@guard("RegistryAdmin")
def create_chemical(who):
    body = validate.body_json()
    name = validate.v_str(body, "chemical_name", required=True, minlen=1, maxlen=120)
    cas = validate.v_str(body, "cas_number", required=True, minlen=1, maxlen=20)
    endpoint_type = validate.v_enum(body, "endpoint_type", ENDPOINT_TYPES, required=True)
    basis = validate.v_enum(body, "safe_harbor_basis", BASES, required=True)
    level = validate.v_num(body, "safe_harbor_level_ug_per_day")
    validate.v_level_domain(body)
    validate.v_cas(cas)
    check_basis_level(basis, level)
    check_basis_endpoint(endpoint_type, basis)
    for existing in db.rows("listed_chemicals"):
        if existing["chemical_name"] == name:
            fail("ERR_DUPLICATE_RESOURCE", "chemical_name is already registered")
    validate.v_writable(body, CREATE_FIELDS)
    row = db.insert("listed_chemicals", {
        "chemical_name": name,
        "cas_number": cas,
        "endpoint_type": endpoint_type,
        "harm_class": harm_class(endpoint_type),
        "safe_harbor_basis": basis,
        "safe_harbor_level_ug_per_day": level,
        "listing_effective_date": None,
        "warning_required_from": None,
        "status": "PROPOSED",
        "revision_count": 0,
    })
    return response.created(db.serialize("listed_chemicals", row))


@bp.route("/listed-chemicals/<chemical_id>/transitions", methods=["POST"])
@guard("RegistryAdmin")
def transition_chemical(who, chemical_id):
    body = validate.body_json()
    action = validate.v_action(body, TRIGGERS)
    effective_date = None
    basis = None
    level = None
    if action in ("LIST", "RELIST"):
        effective_date = validate.v_dt(body, "listing_effective_date", required=True)
    if action == "REVISE_SAFE_HARBOR":
        basis = validate.v_enum(body, "safe_harbor_basis", BASES, required=True)
        level = validate.v_num(body, "safe_harbor_level_ug_per_day")
        validate.v_level_domain(body)
        check_basis_level(basis, level)
    chemical = validate.must_exist("listed_chemicals", chemical_id, "chemical")
    if chemical["status"] not in LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, chemical["status"]))
    validate.v_writable(body, ("action", "listing_effective_date", "safe_harbor_basis",
                               "safe_harbor_level_ug_per_day"))

    if action == "LIST" or action == "RELIST":
        chemical["status"] = "LISTED"
        chemical["listing_effective_date"] = effective_date
        chemical["warning_required_from"] = effective_date + days(GRACE_PERIOD_DAYS)
        db.touch(chemical)
        cascade.chemical_data_changed(chemical)
    elif action == "WITHDRAW":
        chemical["status"] = "WITHDRAWN"
        db.touch(chemical)
    elif action == "DELIST":
        chemical["status"] = "DELISTED"
        db.touch(chemical)
        cascade.supersede_finals_for_chemical(chemical)
        cascade.chemical_data_changed(chemical)
    else:
        chemical["safe_harbor_basis"] = basis
        chemical["safe_harbor_level_ug_per_day"] = level
        chemical["revision_count"] = int(chemical["revision_count"]) + 1
        db.touch(chemical)
        cascade.supersede_finals_for_chemical(chemical)
        cascade.chemical_data_changed(chemical)
    return response.ok(db.serialize("listed_chemicals", chemical))


@bp.route("/listed-chemicals/<chemical_id>", methods=["GET"])
@guard(*READ_ALL_BUT_SUPPLIER)
def read_chemical(who, chemical_id):
    chemical = validate.must_exist("listed_chemicals", chemical_id, "chemical")
    return response.ok(db.serialize("listed_chemicals", chemical))


@bp.route("/listed-chemicals", methods=["GET"])
@guard(*READ_ALL_BUT_SUPPLIER)
def list_chemicals(who):
    return list_endpoint("listed_chemicals",
                         {"status": "status", "harm_class": "harm_class"})
