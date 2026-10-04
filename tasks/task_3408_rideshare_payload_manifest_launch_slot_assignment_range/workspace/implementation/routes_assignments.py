"""Manifest assignment routes: create (OCC-guarded), list, read, confirm,
remove, interface verifications, safety reviews."""
from decimal import Decimal

from flask import Blueprint, g, request

from calc import LIVE_ASSIGNMENT_STATUSES, integration_fee_cents, recompute_commitment
from cascade import remove_assignment
from envelope import success, success_list
from errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CONTRACT_NOT_SIGNED,
    ERR_DISPENSER_PORT_NOT_FOUND,
    ERR_INTERFACE_INCOMPATIBLE,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_GRANTED,
    ERR_MANIFEST_LOCKED,
    ERR_MASS_CAPACITY_EXCEEDED,
    ERR_MISSION_MISMATCH,
    ERR_MISSION_NOT_FOUND,
    ERR_ORBIT_MISMATCH,
    ERR_PAYLOAD_ALREADY_MANIFESTED,
    ERR_PAYLOAD_NOT_FOUND,
    ERR_PORT_OCCUPIED,
    ERR_SAFETY_REVIEW_REQUIRED,
    ERR_SOD_VIOLATION,
    ERR_STALE_MISSION_VERSION,
    ERR_VERIFICATION_INCOMPLETE,
    ERR_VOLUME_CAPACITY_EXCEEDED,
    ERR_WINDOW_INCOMPATIBLE,
    ApiError,
    conflict,
    not_found,
    stale,
    unprocessable,
)
from middleware import require_roles
from serialize import ser_assignment, ser_safety_review, ser_verification
from store import bump, db, new_append_only, new_entity
from validate import (
    as_enum,
    as_int,
    as_str,
    body_json,
    opt_enum_filter,
    opt_field,
    paginate,
    parse_pagination,
    req_field,
)

bp = Blueprint("assignments", __name__)

CHECK_TYPES = {"MECHANICAL", "ELECTRICAL"}
OUTCOMES = {"PASSED", "FAILED"}
DECISIONS = {"APPROVE", "REJECT"}
ASSIGNMENT_STATUSES = {"PROVISIONAL", "CONFIRMED", "INTEGRATED", "DEPLOYED", "REMOVED"}


def _load_assignment(aid):
    a = db["assignments"].get(aid)
    if a is None:
        raise not_found(ERR_ASSIGNMENT_NOT_FOUND, f"assignment {aid} not found")
    return a


@bp.post("/rideshare/assignments")
@require_roles("MissionOps")
def create_assignment():
    body = body_json()
    mission_id = as_str(req_field(body, "mission_id"), "mission_id")
    payload_id = as_str(req_field(body, "payload_id"), "payload_id")
    port_id = as_str(req_field(body, "dispenser_port_id"), "dispenser_port_id")
    expected_version = as_int(
        req_field(body, "expected_mission_version"), "expected_mission_version"
    )

    # existence, body fields in declared input order
    mission = db["missions"].get(mission_id)
    if mission is None:
        raise not_found(ERR_MISSION_NOT_FOUND, f"mission {mission_id} not found")
    payload = db["payloads"].get(payload_id)
    if payload is None:
        raise not_found(ERR_PAYLOAD_NOT_FOUND, f"payload {payload_id} not found")
    port = db["dispenser_ports"].get(port_id)
    if port is None or port["mission_id"] != mission["id"]:
        raise not_found(
            ERR_DISPENSER_PORT_NOT_FOUND,
            f"dispenser port {port_id} not found on this mission",
        )

    # optimistic concurrency on Mission.version
    if expected_version != mission["version"]:
        raise stale(
            ERR_STALE_MISSION_VERSION,
            f"expected_mission_version {expected_version} != current {mission['version']}",
        )

    # lifecycle gates (state)
    if mission["status"] != "MANIFEST_OPEN":
        raise conflict(
            ERR_MANIFEST_LOCKED,
            f"mission is {mission['status']}, expected MANIFEST_OPEN",
        )
    if payload["status"] != "REGISTERED":
        raise conflict(
            ERR_PAYLOAD_ALREADY_MANIFESTED,
            f"payload is {payload['status']}, expected REGISTERED",
        )
    contract = db["contracts"][payload["contract_id"]]
    if contract["status"] not in ("SIGNED", "MANIFESTED"):
        raise conflict(
            ERR_CONTRACT_NOT_SIGNED,
            f"contract is {contract['status']}, expected SIGNED or MANIFESTED",
        )

    # window arithmetic: contract window must cover the mission window
    if not (
        contract["window_open_utc"] <= mission["window_open_utc"]
        and contract["window_close_utc"] >= mission["window_close_utc"]
    ):
        raise unprocessable(
            ERR_WINDOW_INCOMPATIBLE,
            "contract window does not cover the mission window",
        )

    # compatibility and uniqueness
    if payload["required_orbit"] != mission["target_orbit"]:
        raise unprocessable(
            ERR_ORBIT_MISMATCH,
            f"payload requires {payload['required_orbit']}, mission targets {mission['target_orbit']}",
        )
    if payload["interface_class"] not in port["supported_interface_classes"]:
        raise unprocessable(
            ERR_INTERFACE_INCOMPATIBLE,
            f"port does not support {payload['interface_class']}",
        )
    for other in db["assignments"].values():
        if (
            other["dispenser_port_id"] == port["id"]
            and other["status"] != "REMOVED"
        ):
            raise conflict(ERR_PORT_OCCUPIED, "dispenser port already occupied")
    if (
        contract["target_mission_id"] is not None
        and contract["target_mission_id"] != mission["id"]
    ):
        raise unprocessable(
            ERR_MISSION_MISMATCH,
            "contract is pinned to a different target mission",
        )

    # capacity, TOTAL variant, equality permitted; mass before volume
    cur_mass = Decimal("0")
    cur_vol = Decimal("0")
    for other in db["assignments"].values():
        if other["mission_id"] == mission["id"] and other["status"] in LIVE_ASSIGNMENT_STATUSES:
            p = db["payloads"][other["payload_id"]]
            cur_mass += p["mass_kg"]
            cur_vol += p["volume_m3"]
    if cur_mass + payload["mass_kg"] > mission["mass_capacity_kg"]:
        raise unprocessable(
            ERR_MASS_CAPACITY_EXCEEDED, "mission mass capacity would be exceeded"
        )
    if cur_vol + payload["volume_m3"] > mission["volume_capacity_m3"]:
        raise unprocessable(
            ERR_VOLUME_CAPACITY_EXCEEDED, "mission volume capacity would be exceeded"
        )
    if payload["mass_kg"] > port["max_mass_kg"]:
        raise unprocessable(
            ERR_MASS_CAPACITY_EXCEEDED, "payload exceeds the port's max_mass_kg"
        )

    a = new_entity()
    a.update(
        {
            "mission_id": mission["id"],
            "payload_id": payload["id"],
            "dispenser_port_id": port["id"],
            "integration_fee_cents": integration_fee_cents(payload),
            "status": "PROVISIONAL",
        }
    )
    db["assignments"][a["id"]] = a

    payload["status"] = "MANIFESTED"
    bump(payload)
    if contract["status"] == "SIGNED":
        contract["status"] = "MANIFESTED"
        bump(contract)
    recompute_commitment(mission)
    bump(mission)
    return success(ser_assignment(a), 201)


@bp.get("/rideshare/assignments")
@require_roles("MissionOps", "IntegrationEngineer", "SafetyOfficer")
def list_assignments():
    status = opt_enum_filter(request.args, "status", ASSIGNMENT_STATUSES)
    mission_id = request.args.get("mission_id")
    payload_id = request.args.get("payload_id")
    port_id = request.args.get("dispenser_port_id")
    limit, offset = parse_pagination(request.args)
    rows = list(db["assignments"].values())
    if mission_id is not None:
        rows = [a for a in rows if a["mission_id"] == mission_id]
    if payload_id is not None:
        rows = [a for a in rows if a["payload_id"] == payload_id]
    if port_id is not None:
        rows = [a for a in rows if a["dispenser_port_id"] == port_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.get("/rideshare/assignments/<aid>")
@require_roles("MissionOps", "IntegrationEngineer", "SafetyOfficer")
def get_assignment(aid):
    return success(ser_assignment(_load_assignment(aid)))


def _latest_per_check(aid, check_type):
    rows = [
        v
        for v in db["verifications"].values()
        if v["assignment_id"] == aid and v["check_type"] == check_type
    ]
    if not rows:
        return None
    return max(rows, key=lambda v: (v["created_at"], v["_seq"]))


def _latest_review(aid):
    rows = [r for r in db["safety_reviews"].values() if r["assignment_id"] == aid]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["created_at"], r["_seq"]))


@bp.post("/rideshare/assignments/<aid>/confirm")
@require_roles("MissionOps")
def confirm_assignment(aid):
    a = _load_assignment(aid)
    if a["status"] != "PROVISIONAL":
        raise conflict(
            ERR_INVALID_STATE, f"assignment is {a['status']}, expected PROVISIONAL"
        )
    mech = _latest_per_check(aid, "MECHANICAL")
    elec = _latest_per_check(aid, "ELECTRICAL")
    if (
        mech is None
        or mech["outcome"] != "PASSED"
        or elec is None
        or elec["outcome"] != "PASSED"
    ):
        raise conflict(
            ERR_VERIFICATION_INCOMPLETE,
            "latest MECHANICAL and ELECTRICAL verifications must both be PASSED",
        )
    review = _latest_review(aid)
    if review is None or review["decision"] != "APPROVE":
        raise conflict(
            ERR_SAFETY_REVIEW_REQUIRED,
            "latest safety review must be APPROVE",
        )
    payload = db["payloads"][a["payload_id"]]
    contract = db["contracts"][payload["contract_id"]]
    granted = any(
        lic["subject_type"] == "CUSTOMER"
        and lic["customer_id"] == contract["customer_id"]
        and lic["kind"] == "PAYLOAD_OPERATOR"
        and lic["status"] == "GRANTED"
        for lic in db["licenses"].values()
    )
    if not granted:
        raise unprocessable(
            ERR_LICENSE_NOT_GRANTED,
            "customer holds no GRANTED PAYLOAD_OPERATOR license",
        )
    a["status"] = "CONFIRMED"
    bump(a)
    # firm_mass_kg moves; derived refresh only — no mission version bump
    recompute_commitment(db["missions"][a["mission_id"]])
    return success(ser_assignment(a))


@bp.post("/rideshare/assignments/<aid>/remove")
@require_roles("MissionOps")
def remove_assignment_route(aid):
    body = body_json()
    reason = opt_field(body, "reason_code", None)
    if reason is not None:
        as_str(reason, "reason_code")
    a = _load_assignment(aid)
    if a["status"] not in ("PROVISIONAL", "CONFIRMED"):
        raise conflict(
            ERR_INVALID_STATE,
            f"manual remove is allowed only from PROVISIONAL or CONFIRMED, not {a['status']}",
        )
    remove_assignment(a)
    return success(ser_assignment(a))


@bp.post("/rideshare/assignments/<aid>/verifications")
@require_roles("IntegrationEngineer")
def create_verification(aid):
    body = body_json()
    check_type = as_enum(req_field(body, "check_type"), "check_type", CHECK_TYPES)
    outcome = as_enum(req_field(body, "outcome"), "outcome", OUTCOMES)
    notes = opt_field(body, "notes", None)
    if notes is not None:
        notes = as_str(notes, "notes")
    a = _load_assignment(aid)
    v = new_append_only()
    v.update(
        {
            "assignment_id": a["id"],
            "check_type": check_type,
            "outcome": outcome,
            "notes": notes,
            "created_by_user_id": g.user_id,
        }
    )
    db["verifications"][v["id"]] = v
    return success(ser_verification(v), 201)


@bp.get("/rideshare/assignments/<aid>/verifications")
@require_roles("IntegrationEngineer", "SafetyOfficer", "MissionOps")
def list_verifications(aid):
    a = _load_assignment(aid)
    check_type = opt_enum_filter(request.args, "check_type", CHECK_TYPES)
    outcome = opt_enum_filter(request.args, "outcome", OUTCOMES)
    limit, offset = parse_pagination(request.args)
    rows = [v for v in db["verifications"].values() if v["assignment_id"] == a["id"]]
    if check_type is not None:
        rows = [v for v in rows if v["check_type"] == check_type]
    if outcome is not None:
        rows = [v for v in rows if v["outcome"] == outcome]
    rows.sort(key=lambda v: (v["created_at"], v["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_verification(v) for v in page], limit, offset, total)


@bp.post("/rideshare/assignments/<aid>/safety-reviews")
@require_roles("SafetyOfficer")
def create_safety_review(aid):
    body = body_json()
    decision = as_enum(req_field(body, "decision"), "decision", DECISIONS)
    rationale = opt_field(body, "rationale", None)
    if rationale is not None:
        rationale = as_str(rationale, "rationale")
    a = _load_assignment(aid)
    # segregation of duties: the reviewer must not have recorded any PASSED
    # verification on this same assignment
    for v in db["verifications"].values():
        if (
            v["assignment_id"] == a["id"]
            and v["outcome"] == "PASSED"
            and v["created_by_user_id"] == g.user_id
        ):
            raise ApiError(
                ERR_SOD_VIOLATION,
                "reviewer recorded a PASSED verification on this assignment",
                403,
            )
    r = new_append_only()
    r.update(
        {
            "assignment_id": a["id"],
            "decision": decision,
            "rationale": rationale,
            "created_by_user_id": g.user_id,
        }
    )
    db["safety_reviews"][r["id"]] = r
    return success(ser_safety_review(r), 201)


@bp.get("/rideshare/assignments/<aid>/safety-reviews")
@require_roles("SafetyOfficer", "MissionOps")
def list_safety_reviews(aid):
    a = _load_assignment(aid)
    decision = opt_enum_filter(request.args, "decision", DECISIONS)
    limit, offset = parse_pagination(request.args)
    rows = [r for r in db["safety_reviews"].values() if r["assignment_id"] == a["id"]]
    if decision is not None:
        rows = [r for r in rows if r["decision"] == decision]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_safety_review(r) for r in page], limit, offset, total)
