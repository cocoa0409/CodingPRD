from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
import util
from errors import ApiError

bp = Blueprint("programs", __name__)

CHANNELS = ("BROKERED", "LISTING_SERVICE", "CORE", "RECIPROCAL_NETWORK")
PRODUCT_TYPES = ("TIME_DEPOSIT", "MONEY_MARKET", "SAVINGS", "NOW")
TITLING = ("SINGLE_FIDUCIARY_ACCOUNT", "FBO_SUBACCOUNTS", "DIRECT_TITLED")
STATE_ACTIONS = ("ATTEST_CLASSIFICATION", "SUSPEND", "RESUME",
                 "START_RECLASSIFICATION", "CLOSE")
CLEARED = ("APPROVED", "CONDITIONAL")

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_program(program_id):
    record = db.programs.get(program_id)
    if record is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return record


def _agreement_cleared(program):
    """Priority 27 as applied to a program that names a counterparty."""
    if not program.get("broker_id"):
        return
    agreement = db.broker_agreements.get(program.get("agreement_id"))
    if agreement is None or agreement["status"] not in CLEARED:
        raise ApiError("ERR_AGREEMENT_NOT_APPROVED")


@bp.post("/deposit-programs")
def create_program():
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer")
    data = mw.body()
    institution_id = mw.req_id(data, "institution_id")
    broker_id = mw.opt_id(data, "broker_id")
    agreement_id = mw.opt_id(data, "agreement_id")
    program_name = mw.req_str(data, "program_name")
    channel = mw.req_enum(data, "funding_channel_claim", CHANNELS)
    product_type = mw.req_enum(data, "product_type", PRODUCT_TYPES)
    tenor_days = mw.req_int(data, "tenor_days", minimum=0)
    offered_rate_bps = mw.req_int(data, "offered_rate_bps", minimum=0)
    local_rate = mw.opt_int(data, "local_prevailing_rate_bps", None, minimum=0)
    penalty_days = mw.req_int(data, "early_withdrawal_penalty_days", minimum=0)
    erosion = mw.opt_bool(data, "principal_erosion_allowed", False)
    pass_through = mw.opt_bool(data, "pass_through_insurance", False)
    titling = mw.req_enum(data, "titling_convention", TITLING)
    rollover = mw.opt_bool(data, "rollover_enabled", False)
    reciprocal_cents = mw.opt_int(data, "reciprocal_arrangement_cents", 0, minimum=0)
    if broker_id is not None and agreement_id is None:
        raise mw.bad("agreement_id is required whenever broker_id is present.")
    if product_type in calc.NON_MATURITY_PRODUCTS and tenor_days != 0:
        raise mw.bad("tenor_days must be 0 for a non-maturity product.")

    institution = db.institutions.get(institution_id)
    if institution is None:
        raise ApiError("ERR_INSTITUTION_NOT_FOUND")
    if broker_id is not None and broker_id not in db.brokers:
        raise ApiError("ERR_BROKER_NOT_FOUND")
    agreement = None
    if agreement_id is not None:
        agreement = db.broker_agreements.get(agreement_id)
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")

    bucket = calc.tenor_bucket(product_type, tenor_days)
    as_of = util.clock_date().isoformat()
    cap, _pub = calc.effective_cap(institution, bucket, local_rate, as_of, require=True)

    if broker_id is not None:
        broker = db.brokers[broker_id]
        if (agreement["status"] not in CLEARED
                or broker["diligence_status"] not in CLEARED):
            raise ApiError("ERR_AGREEMENT_NOT_APPROVED")
    if cap is not None and offered_rate_bps > cap:
        raise ApiError("ERR_RATE_CAP_EXCEEDED")
    if institution["concentration_posture"] == "FROZEN":
        raise ApiError("ERR_CONCENTRATION_FROZEN")
    if pass_through and (titling != "FBO_SUBACCOUNTS" or broker_id is None):
        raise ApiError("ERR_PASS_THROUGH_TITLING_INVALID")
    if channel == "RECIPROCAL_NETWORK" and reciprocal_cents <= 0:
        raise ApiError("ERR_PASS_THROUGH_TITLING_INVALID")
    if agreement is not None and (broker_id is None or agreement["broker_id"] != broker_id):
        raise ApiError("ERR_AGREEMENT_BROKER_MISMATCH")

    record = {
        "institution_id": institution_id,
        "broker_id": broker_id,
        "agreement_id": agreement_id,
        "governing_classification_id": None,
        "program_name": program_name,
        "funding_channel_claim": channel,
        "product_type": product_type,
        "tenor_days": tenor_days,
        "tenor_bucket": bucket,
        "offered_rate_bps": offered_rate_bps,
        "local_prevailing_rate_bps": local_rate,
        "effective_cap_bps": cap,
        "early_withdrawal_penalty_days": penalty_days,
        "principal_erosion_allowed": erosion,
        "pass_through_insurance": pass_through,
        "titling_convention": titling,
        "rollover_enabled": rollover,
        "reciprocal_arrangement_cents": reciprocal_cents,
        "state": "PENDING_CLASSIFICATION",
        "outstanding_principal_cents": 0,
        "prepared_by_user_id": user_id,
        "attested_by_user_id": None,
    }
    db.stamp_new(record)
    db.programs[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/deposit-programs/<program_id>")
def read_program(program_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_program(program_id)))


@bp.get("/deposit-programs")
def list_programs():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.programs.values())
    for field in ("institution_id", "broker_id", "agreement_id",
                  "governing_classification_id", "state", "funding_channel_claim"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return response.listing(db.public_list(db.by_created(rows)), limit, offset)


@bp.post("/deposit-programs/<program_id>/state-actions")
def program_state_action(program_id):
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer")
    program = find_program(program_id)
    data = mw.body()
    action = mw.req_enum(data, "action", STATE_ACTIONS)
    mw.opt_str(data, "note")
    state = program["state"]

    if action == "ATTEST_CLASSIFICATION":
        if state != "CLASSIFIED":
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        determination_id = program.get("governing_classification_id")
        if not determination_id:
            raise ApiError("ERR_CLASSIFICATION_REQUIRED")
        determination = db.classifications.get(determination_id)
        if determination is not None and user_id == determination["determined_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        _agreement_cleared(program)
        program["state"] = "OPEN_FOR_PLACEMENT"
        program["attested_by_user_id"] = user_id
        db.touch(program)

    elif action == "SUSPEND":
        if state != "OPEN_FOR_PLACEMENT":
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        program["state"] = "SUSPENDED"
        db.touch(program)
        cascades.cancel_pending_placements(program)
        calc.recompute_institution(db.institutions.get(program["institution_id"]))

    elif action == "RESUME":
        if state != "SUSPENDED":
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        _agreement_cleared(program)
        program["state"] = "OPEN_FOR_PLACEMENT"
        db.touch(program)

    elif action == "START_RECLASSIFICATION":
        if state not in ("CLASSIFIED", "OPEN_FOR_PLACEMENT"):
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        program["state"] = "RECLASSIFICATION_PENDING"
        program["attested_by_user_id"] = None
        db.touch(program)

    else:  # CLOSE
        if state not in ("PENDING_CLASSIFICATION", "CLASSIFIED", "OPEN_FOR_PLACEMENT",
                         "SUSPENDED", "RECLASSIFICATION_PENDING"):
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        program["state"] = "CLOSED"
        db.touch(program)
        cascades.cancel_pending_placements(program)
        calc.recompute_institution(db.institutions.get(program["institution_id"]))

    return response.ok(db.public(program))
