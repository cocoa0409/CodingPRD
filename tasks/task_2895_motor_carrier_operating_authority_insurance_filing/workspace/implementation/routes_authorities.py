"""Operating authorities, activation and process-agent designations (PRD 3.4, 3.6)."""

from flask import Blueprint, request

import calc
import clock
import domain
import envelope
import helpers
import store
from errors import ApiError, invalid
from validation import Body, authenticate

bp = Blueprint("authorities", __name__)

ALL_ROLES = ("CarrierRep", "InsuranceFiler", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")
DESIGNATION_READ_ROLES = ("CarrierRep", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")
PROCEEDING_READ_ROLES = ("CarrierRep", "InsuranceFiler", "ComplianceOfficer", "RegistryAdmin")


@bp.get("/operating-authorities/<authority_id>")
def read_authority(authority_id):
    authenticate(ALL_ROLES)
    return helpers.one(helpers.need_authority(authority_id))


@bp.get("/operating-authorities")
def list_authorities():
    authenticate(ALL_ROLES)
    return helpers.listing(store.all_of(store.AUTHORITIES), {
        "carrier_id": "carrier_id",
        "application_id": "application_id",
        "authority_status": "authority_status",
        "insurance_status": "insurance_status",
    })


@bp.get("/operating-authorities/<authority_id>/revocation-proceedings")
def list_proceedings(authority_id):
    authenticate(PROCEEDING_READ_ROLES)
    helpers.need_authority(authority_id)
    return helpers.listing(store.proceedings_of_authority(authority_id), {"status": "status"})


# ------------------------------------------------------------------ activation

@bp.post("/operating-authorities/<authority_id>/activate")
def activate(authority_id):
    uid, _role = authenticate(("ComplianceOfficer",))
    authority = helpers.need_authority(authority_id)

    if authority["authority_status"] != "PENDING":
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")

    app = store.APPLICATIONS.get(authority["application_id"])
    if app is not None and app["published_by_user_id"] is not None \
            and app["published_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    now = clock.now()
    if now < authority["activation_eligible_at"]:
        raise ApiError("ERR_WAITING_PERIOD_NOT_ELAPSED")

    if not authority["designation_coverage_complete"]:
        raise ApiError("ERR_PROCESS_AGENT_COVERAGE_INCOMPLETE")

    # rung 27 then rung 28: existence of each required primary filing, then its limit
    primary = []
    if authority["required_bipd_limit_cents"] > 0:
        primary.append(("BIPD", authority["required_bipd_limit_cents"]))
    if authority["required_cargo_limit_cents"] > 0:
        primary.append(("CARGO", authority["required_cargo_limit_cents"]))
    holders = []
    for filing_type, minimum in primary:
        holder = domain.slot_holder(authority, (filing_type,), minimum, require_minimum=False)
        if holder is None:
            raise ApiError("ERR_INSURANCE_NOT_ON_FILE")
        holders.append((holder, minimum))
    for holder, minimum in holders:
        if holder["coverage_limit_cents"] < minimum:
            raise ApiError("ERR_INSURANCE_BELOW_MINIMUM")

    # rung 29: the broker / freight-forwarder bond
    if authority["required_bond_limit_cents"] > 0:
        bond = domain.slot_holder(authority, domain.BOND_TYPES,
                                  authority["required_bond_limit_cents"])
        if bond is None:
            raise ApiError("ERR_BOND_FILING_REQUIRED")

    carrier = store.CARRIERS[authority["carrier_id"]]
    if carrier["biennial_delinquent"]:
        raise ApiError("ERR_BIENNIAL_UPDATE_DELINQUENT")

    if carrier["fee_balance_cents"] > 0:
        raise ApiError("ERR_FILING_FEE_OUTSTANDING")

    # ---- all eight gates cleared
    authority["authority_status"] = "ACTIVE"
    authority["activated_at"] = now
    authority["insurance_status"] = "FILED"

    if app is not None:
        app["status"] = "GRANTED"
        domain.touch(app)

    carrier["unified_registration_status"] = "REGISTERED"
    carrier["active_authority_count"] += 1
    carrier["compliance_risk_score"] = calc.self_reported_risk_score(carrier)
    carrier["compliance_risk_variant"] = "SELF_REPORTED"
    domain.touch(carrier)

    if carrier["entrant_status"] == "NEW_ENTRANT":
        window = calc.new_entrant_audit_window(now)
        authority["new_entrant_audit_status"] = "PENDING"
        authority["new_entrant_audit_deadline_at"] = window
        audit = store.base_record()
        audit.update({
            "carrier_id": carrier["id"],
            "audit_window_opens_at": now,
            "audit_deadline_at": window,
            "status": "SCHEDULED",
            "result_recorded_at": None,
            "audited_oos_rate_pct": None,
            "audited_driver_violation_count": None,
            "audited_vehicle_defect_count": None,
            "acute_violation_count": None,
            "audit_score": None,
        })
        store.insert(store.AUDITS, audit)

    domain.touch(authority)

    if app is not None and app["application_kind"] == "SUCCESSOR_IN_INTEREST":
        predecessor = store.AUTHORITIES.get(app["predecessor_authority_id"])
        if predecessor is not None:
            domain.rescind(predecessor)

    return helpers.one(authority)


# -------------------------------------------------------------- designations

def _designation_admits_create(authority):
    status = authority["authority_status"]
    if status in ("PENDING", "ACTIVE"):
        return True
    if status == "SUSPENDED" and authority["suspension_reason"] == "DESIGNATION_GAP":
        return True
    return False


def _conflicts(authority_id, state_code, low, high):
    """Closed intervals expanded by the one-day transition buffer on each end."""
    for row in store.designations_of_authority(authority_id):
        if row["status"] != "ACTIVE" or row["state_code"] != state_code:
            continue
        existing_low = clock.add_days(row["effective_from"], -calc.DESIGNATION_TRANSITION_BUFFER_DAYS)
        existing_high = (None if row["effective_to"] is None
                         else clock.add_days(row["effective_to"],
                                             calc.DESIGNATION_TRANSITION_BUFFER_DAYS))
        low_before_existing_high = existing_high is None or low <= existing_high
        high_after_existing_low = high is None or high >= existing_low
        if low_before_existing_high and high_after_existing_low:
            return True
    return False


@bp.post("/operating-authorities/<authority_id>/process-agent-designations")
def create_designations(authority_id):
    uid, role = authenticate(("CarrierRep",))
    authority = helpers.need_authority(authority_id)
    helpers.require_carrier_owner(role, uid, authority["carrier_id"])

    raw = request.get_json(silent=True)
    raw = raw if isinstance(raw, dict) else {}
    agent_ref = raw.get("process_agent_id")
    if isinstance(agent_ref, str):
        helpers.resolve_body_ref(store.PROCESS_AGENTS, agent_ref)

    body = Body()
    agent_id = body.req_str("process_agent_id", min_len=None)
    state_codes = body.req_state_list("state_codes", min_n=1, max_n=51)
    effective_from = body.req_instant("effective_from")
    effective_to = body.opt_instant("effective_to", default=None)
    if effective_to is not None and effective_to < effective_from:
        raise invalid("Field 'effective_to' must not be earlier than 'effective_from'.")
    agent = store.PROCESS_AGENTS[agent_id]

    if not _designation_admits_create(authority):
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")

    # rung 21: interval conflict, evaluated for every requested state before any write
    for state_code in state_codes:
        if _conflicts(authority["id"], state_code, effective_from, effective_to):
            raise ApiError("ERR_DESIGNATION_INTERVAL_CONFLICT")

    # rung 22: the agent must cover every requested state
    for state_code in state_codes:
        if not domain.agent_covers(agent, state_code):
            raise ApiError("ERR_PROCESS_AGENT_STATE_NOT_COVERED")

    created = []
    for state_code in state_codes:
        rec = store.base_record()
        rec.update({
            "authority_id": authority["id"],
            "process_agent_id": agent["id"],
            "state_code": state_code,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
            "revoked_at": None,
        })
        store.insert(store.DESIGNATIONS, rec)
        created.append(rec)

    domain.recompute_coverage(authority)
    domain.try_restore(authority)
    return envelope.array(store.serialize_all(created), None, 201)


@bp.get("/process-agent-designations/<designation_id>")
def read_designation(designation_id):
    authenticate(DESIGNATION_READ_ROLES)
    return helpers.one(helpers.need_ref(store.DESIGNATIONS, designation_id))


@bp.get("/process-agent-designations")
def list_designations():
    authenticate(DESIGNATION_READ_ROLES)
    return helpers.listing(store.all_of(store.DESIGNATIONS), {
        "authority_id": "authority_id",
        "process_agent_id": "process_agent_id",
        "state_code": "state_code",
        "status": "status",
    })


@bp.post("/process-agent-designations/<designation_id>/revoke")
def revoke_designation(designation_id):
    uid, role = authenticate(("CarrierRep",))
    designation = helpers.need_ref(store.DESIGNATIONS, designation_id)
    authority = store.AUTHORITIES.get(designation["authority_id"])
    helpers.require_carrier_owner(role, uid,
                                  None if authority is None else authority["carrier_id"])

    if authority is None or authority["authority_status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")
    if designation["status"] != "ACTIVE":
        raise ApiError("ERR_AUTHORITY_INVALID_STATE",
                       "The designation has already been revoked.")

    designation["status"] = "REVOKED"
    designation["revoked_at"] = clock.now()
    domain.touch(designation)

    domain.recompute_coverage(authority)
    if not authority["designation_coverage_complete"] and authority["authority_status"] == "ACTIVE":
        domain.suspend(authority, "DESIGNATION_GAP")
    return helpers.one(designation)
