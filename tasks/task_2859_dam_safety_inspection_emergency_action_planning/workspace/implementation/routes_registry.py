"""Owners, engineers, river reaches and dams (PRD Section 3.1)."""

from flask import Blueprint, request

import calc
import guards
import services
from common import (
    ApiError, INVALID, body_dict, ok, ok_list, pagination, q_bool, q_enum, q_str,
    v_dt, v_enum, v_enum_list, v_int, v_num, v_string,
)
from derive import (
    compliance_summary, dam_available_storage_acre_ft, dam_committed_drawdown_acre_ft,
    dam_deficiencies, dam_drawdowns, dam_eap_required, dam_hazard_class,
    dam_inspection_overdue, dam_safety_status, engineer_license_status, ledger_replay,
    next_ledger_sequence_no, owner_delinquency_status, paginate, serialize_dam,
    serialize_engineer, serialize_ledger_entry, serialize_owner, serialize_reach,
)
from store import db, insert, insertion_order, owner_entries, touch

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# Owners
# ---------------------------------------------------------------------------

@bp.route("/owners", methods=["POST"])
def create_owner():
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    legal_name = v_string(body, "legal_name", min_len=1, max_len=160, trim_nonempty=True)
    owner_type = v_enum(body, "owner_type", calc.OWNER_TYPES)
    contact_email = v_string(body, "contact_email", min_len=1)
    if "@" not in contact_email:
        raise ApiError(INVALID, "field 'contact_email' must contain '@'")
    bond = v_int(body, "financial_assurance_bond_cents", required=False, minimum=0, default=0)
    owner = insert(db.owners, {
        "legal_name": legal_name,
        "owner_type": owner_type,
        "contact_email": contact_email,
        "financial_assurance_bond_cents": bond,
    })
    return ok(serialize_owner(owner), 201)


@bp.route("/owners/<owner_id>", methods=["GET"])
def read_owner(owner_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "DamOwner"))
    owner = guards.get_owner(owner_id)
    guards.check_identity(user_id, role)
    return ok(serialize_owner(owner))


@bp.route("/owners", methods=["GET"])
def list_owners():
    guards.authenticate(request, ("ProgramAdmin",))
    limit, offset = pagination()
    owner_type = q_enum("owner_type", calc.OWNER_TYPES)
    delinquency_status = q_enum("delinquency_status", calc.DELINQUENCY_STATUSES)
    rows = list(db.owners.values())
    if owner_type is not None:
        rows = [r for r in rows if r["owner_type"] == owner_type]
    if delinquency_status is not None:
        rows = [r for r in rows if owner_delinquency_status(r["id"]) == delinquency_status]
    data, total = paginate(rows, limit, offset, serialize_owner)
    return ok_list(data, limit, offset, total)


@bp.route("/owners/<owner_id>/fee-adjustments", methods=["POST"])
def create_fee_adjustment(owner_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    entry_type = v_enum(body, "entry_type", calc.LEDGER_TYPES)
    amount_cents = v_int(body, "amount_cents", nonzero=True)
    source_ref = v_string(body, "source_ref", required=False)
    memo = v_string(body, "memo", required=False)
    owner = guards.get_owner(owner_id)
    # Rung 40: ledger sign agreement
    if not services.ledger_sign_agrees(entry_type, amount_cents):
        raise ApiError("ERR_LEDGER_SIGN_MISMATCH",
                       "amount_cents sign disagrees with entry_type %s" % entry_type)
    entry = services.post_ledger_entry(owner["id"], entry_type, amount_cents, user_id,
                                       source_ref=source_ref, memo=memo)
    return ok(serialize_ledger_entry(entry), 201)


@bp.route("/owners/<owner_id>/fee-ledger-entries", methods=["GET"])
def list_fee_ledger_entries(owner_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "DamOwner"))
    limit, offset = pagination()
    entry_type = q_enum("entry_type", calc.LEDGER_TYPES)
    owner = guards.get_owner(owner_id)
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, owner["id"])
    rows = owner_entries(owner["id"])
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    running = ledger_replay(owner["id"])[0]
    ordered = insertion_order(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serialize_ledger_entry(r, running) for r in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Engineers
# ---------------------------------------------------------------------------

@bp.route("/engineers", methods=["POST"])
def create_engineer():
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    full_name = v_string(body, "full_name", min_len=1, trim_nonempty=True)
    license_number = v_string(body, "license_number", min_len=1, max_len=40, trim_nonempty=True)
    license_expires_at = v_dt(body, "license_expires_at")
    certified = v_enum_list(body, "certified_hazard_classes", calc.CERTIFIABLE_CLASSES, min_items=1)
    # Rung 39: license_number uniqueness
    for existing in db.engineers.values():
        if existing["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER",
                           "license_number '%s' is already registered" % license_number)
    engineer = insert(db.engineers, {
        "full_name": full_name,
        "license_number": license_number,
        "license_expires_at": license_expires_at,
        "certified_hazard_classes": certified,
    })
    return ok(serialize_engineer(engineer), 201)


@bp.route("/engineers/<engineer_id>", methods=["GET"])
def read_engineer(engineer_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer"))
    engineer = guards.get_engineer(engineer_id)
    guards.check_identity(user_id, role)
    return ok(serialize_engineer(engineer))


@bp.route("/engineers", methods=["GET"])
def list_engineers():
    user_id, role = guards.authenticate(request, ("ProgramAdmin",))
    limit, offset = pagination()
    license_status = q_enum("license_status", calc.LICENSE_STATUSES)
    rows = list(db.engineers.values())
    if license_status is not None:
        rows = [r for r in rows if engineer_license_status(r) == license_status]
    data, total = paginate(rows, limit, offset, serialize_engineer)
    return ok_list(data, limit, offset, total)


# ---------------------------------------------------------------------------
# River reaches
# ---------------------------------------------------------------------------

@bp.route("/river-reaches", methods=["POST"])
def create_reach():
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    name = v_string(body, "name", min_len=1, trim_nonempty=True)
    capacity = v_int(body, "channel_capacity_cfs", minimum=1)
    community = v_string(body, "downstream_community", min_len=1)
    reach = insert(db.reaches, {
        "name": name,
        "channel_capacity_cfs": capacity,
        "downstream_community": community,
    })
    return ok(serialize_reach(reach), 201)


@bp.route("/river-reaches/<reach_id>", methods=["GET"])
def read_reach(reach_id):
    guards.authenticate(request, ("ProgramAdmin", "EmergencyCoordinator"))
    reach = guards.get_reach(reach_id)
    return ok(serialize_reach(reach))


@bp.route("/river-reaches", methods=["GET"])
def list_reaches():
    guards.authenticate(request, ("ProgramAdmin", "EmergencyCoordinator"))
    limit, offset = pagination()
    rows = list(db.reaches.values())
    data, total = paginate(rows, limit, offset, serialize_reach)
    return ok_list(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Dams
# ---------------------------------------------------------------------------

@bp.route("/dams", methods=["POST"])
def create_dam():
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    owner_id = v_string(body, "owner_id", min_len=1)
    river_reach_id = v_string(body, "river_reach_id", min_len=1)
    name = v_string(body, "name", min_len=1, trim_nonempty=True)
    nid_code = v_string(body, "nid_code", min_len=1, max_len=20, trim_nonempty=True)
    height_ft = v_num(body, "height_ft", exclusive_min=0)
    gross_storage_acre_ft = v_num(body, "gross_storage_acre_ft", exclusive_min=0)
    crest_elevation_ft = v_num(body, "crest_elevation_ft")
    normal_pool_elevation_ft = v_num(body, "normal_pool_elevation_ft")
    year_completed = v_int(body, "year_completed", minimum=1700, maximum=2100)
    registered_at = v_dt(body, "registered_at")
    from common import dec
    if dec(normal_pool_elevation_ft) >= dec(crest_elevation_ft):
        raise ApiError(INVALID, "normal_pool_elevation_ft must be strictly below crest_elevation_ft")
    # Rung 5: body references resolved in the order the fields are declared
    owner = guards.get_owner(owner_id)
    reach = guards.get_reach(river_reach_id)
    # Rung 38: nid_code uniqueness
    for existing in db.dams.values():
        if existing["nid_code"] == nid_code:
            raise ApiError("ERR_DUPLICATE_NID_CODE", "nid_code '%s' is already registered" % nid_code)
    dam = insert(db.dams, {
        "owner_id": owner["id"],
        "river_reach_id": reach["id"],
        "name": name,
        "nid_code": nid_code,
        "height_ft": height_ft,
        "gross_storage_acre_ft": gross_storage_acre_ft,
        "crest_elevation_ft": crest_elevation_ft,
        "normal_pool_elevation_ft": normal_pool_elevation_ft,
        "year_completed": year_completed,
        "registered_at": registered_at,
        "regulatory_status": "REGISTERED",
    })
    touch(owner)
    return ok(serialize_dam(dam), 201)


@bp.route("/dams/<dam_id>", methods=["GET"])
def read_dam(dam_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    dam = guards.get_dam(dam_id)
    guards.check_identity(user_id, role)
    return ok(serialize_dam(dam))


@bp.route("/dams", methods=["GET"])
def list_dams():
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    owner_id = q_str("owner_id")
    river_reach_id = q_str("river_reach_id")
    hazard_class = q_enum("hazard_class", calc.HAZARD_CLASSES)
    safety_status = q_enum("safety_status", calc.SAFETY_STATUSES)
    regulatory_status = q_enum("regulatory_status", calc.REGULATORY_STATUSES)
    overdue = q_bool("inspection_overdue")
    guards.check_identity(user_id, role)
    rows = list(db.dams.values())
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if river_reach_id is not None:
        rows = [r for r in rows if r["river_reach_id"] == river_reach_id]
    if hazard_class is not None:
        rows = [r for r in rows if dam_hazard_class(r) == hazard_class]
    if safety_status is not None:
        rows = [r for r in rows if dam_safety_status(r) == safety_status]
    if regulatory_status is not None:
        rows = [r for r in rows if r["regulatory_status"] == regulatory_status]
    if overdue is not None:
        rows = [r for r in rows if dam_inspection_overdue(r) == overdue]
    data, total = paginate(rows, limit, offset, serialize_dam)
    return ok_list(data, limit, offset, total)


@bp.route("/dams/<dam_id>/compliance-summary", methods=["GET"])
def read_compliance_summary(dam_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    dam = guards.get_dam(dam_id)
    guards.check_identity(user_id, role)
    return ok(compliance_summary(dam))


@bp.route("/dams/<dam_id>/state-intervention", methods=["POST"])
def dam_state_intervention(dam_id):
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    intervention_type = v_enum(body, "intervention_type", calc.INTERVENTION_TYPES)
    v_string(body, "justification", min_len=1)
    dam = guards.get_dam(dam_id)
    posture = dam["regulatory_status"]
    if intervention_type == "BREACH_ORDER":
        if posture not in ("REGISTERED", "UNDER_ENFORCEMENT", "STATE_INTERVENTION"):
            raise ApiError("ERR_DAM_NOT_OPERABLE",
                           "a breach order cannot be issued against a %s dam" % posture)
        dam["regulatory_status"] = "BREACHED"
        for deficiency in dam_deficiencies(dam["id"]):
            if deficiency["status"] != "CLOSED_VERIFIED":
                deficiency["status"] = "CLOSED_VERIFIED"
                deficiency["closed_at"] = db.clock
                touch(deficiency)
        touch(dam)
    else:
        if posture not in ("REGISTERED", "UNDER_ENFORCEMENT"):
            raise ApiError("ERR_DAM_NOT_OPERABLE",
                           "state intervention cannot be recorded against a %s dam" % posture)
        dam["regulatory_status"] = "STATE_INTERVENTION"
        touched_reaches = set()
        for order in insertion_order(dam_drawdowns(dam["id"])):
            if order["status"] in ("REQUESTED", "COORDINATED", "ACTIVE"):
                released = services.cancel_drawdown(order, "STATE_INTERVENTION")
                if released:
                    touched_reaches.add(order["river_reach_id"])
        for reach_id in touched_reaches:
            reach = db.reaches.get(reach_id)
            if reach is not None:
                touch(reach)
        touch(dam)
    return ok(serialize_dam(dam))
