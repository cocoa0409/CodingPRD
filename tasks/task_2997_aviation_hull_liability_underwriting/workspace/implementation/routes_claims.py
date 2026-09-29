"""The claim file: notification, investigation, assessment, coverage, salvage,
settlement, and the read side of the premium ledger."""

from flask import Blueprint, g, request

import auth
import calc
import constants as C
import derive
import envelope
import serialize
import services
import util
import validate as V
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("claims", __name__)

ALL = C.ALL_ROLES
NOTIFY_ROLES = ["Broker", "OperatorUser", "ClaimsAdjuster"]
ADJUSTER = ["ClaimsAdjuster"]


# --- notification -------------------------------------------------------------

@bp.route("/aviation/claims", methods=["POST"])
@auth.endpoint(NOTIFY_ROLES)
def notify_claim():
    body = V.json_body()
    policy = services.resolve_fk(body, "policy_id", services.get_policy)
    services.scope_policy(policy)
    schedule = services.resolve_fk(body, "schedule_id", services.get_schedule)

    loss_date = V.get_instant(body, "loss_date")
    loss_type = V.get_str(body, "loss_type")
    loss_description = V.get_str(body, "loss_description")
    investigator_reference = V.get_str(body, "investigator_reference", required=False)

    V.check_enum(loss_type, "loss_type", C.LOSS_TYPES)
    V.check_len(loss_description, "loss_description", 1, 500, non_blank=True)

    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")

    services.require_live_schedule(schedule)

    if loss_type == "WAR_PERIL":
        services.require_placement_covering(policy["id"], loss_date)

    if not (schedule["effective_from"] <= loss_date < schedule["effective_to"]):
        raise ApiError("ERR_LOSS_DATE_NOT_COVERED")
    if loss_date > db.clock:
        raise ApiError("ERR_LOSS_DATE_NOT_COVERED")

    if schedule["policy_id"] != policy["id"]:
        raise ApiError("ERR_SCHEDULE_POLICY_MISMATCH")

    rec = new_record(db.claims, {
        "policy_id": policy["id"],
        "schedule_id": schedule["id"],
        "loss_date": loss_date,
        "loss_type": loss_type,
        "loss_description": loss_description,
        "adjustment_status": "NOTIFIED",
        "salvage_status": "NONE",
        "cooperation_status": "PENDING",
        "investigator_reference": investigator_reference,
        "reserve_cents": 0,
        "ctl_ratio_ppm": None,
        "ctl_flag": False,
        "assessment_count": 0,
        "settlement_basis": None,
        "settlement_amount_cents": None,
        "deductible_applied_cents": None,
        "salvage_proceeds_cents": 0,
        "coverage_decided_by_user_id": None,
        "denial_reason": None,
    })
    return envelope.ok(serialize.claim(rec), 201)


@bp.route("/aviation/claims", methods=["GET"])
@auth.endpoint(ALL)
def list_claims():
    limit, offset = V.pagination()
    rows = ordered(db.claims)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "schedule_id", request.args.get("schedule_id"))
    rows = V.filter_eq(rows, "adjustment_status", request.args.get("adjustment_status"))
    rows = V.filter_eq(rows, "salvage_status", request.args.get("salvage_status"))
    rows = V.filter_eq(rows, "loss_type", request.args.get("loss_type"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.claim, window), limit, offset, total)


@bp.route("/aviation/claims/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_claim(row_id):
    rec = services.get_claim(row_id)
    services.scope_claim(rec)
    return envelope.ok(serialize.claim(rec))


# --- investigation ------------------------------------------------------------

@bp.route("/aviation/claims/<row_id>/investigations", methods=["POST"])
@auth.endpoint(ADJUSTER)
def record_investigation(row_id):
    rec = services.get_claim(row_id)
    body = V.json_body()
    cooperation_status = V.get_str(body, "cooperation_status")
    investigator_reference = V.get_str(body, "investigator_reference")
    V.check_enum(cooperation_status, "cooperation_status",
                 ("COOPERATING", "NON_COOPERATION"))

    if rec["adjustment_status"] not in ("NOTIFIED", "INVESTIGATING"):
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    schedule = db.schedules[rec["schedule_id"]]
    if schedule["coverage_status"] == "REMOVED":
        raise ApiError("ERR_SCHEDULE_NOT_LIVE")

    rec["cooperation_status"] = cooperation_status
    rec["investigator_reference"] = investigator_reference
    if rec["adjustment_status"] == "NOTIFIED":
        rec["adjustment_status"] = ("INVESTIGATING" if cooperation_status == "COOPERATING"
                                    else "COVERAGE_REFERRED")
    touch(rec)
    return envelope.ok(serialize.claim(rec))


# --- damage assessments -------------------------------------------------------

@bp.route("/aviation/damage-assessments", methods=["POST"])
@auth.endpoint(ADJUSTER)
def append_assessment():
    body = V.json_body()
    claim = services.resolve_fk(body, "claim_id", services.get_claim)
    services.scope_claim(claim)

    repair_cost_estimate_cents = V.get_int(body, "repair_cost_estimate_cents")
    assessor_reference = V.get_str(body, "assessor_reference")
    assessed_at = V.get_instant(body, "assessed_at")

    V.check_range(repair_cost_estimate_cents, "repair_cost_estimate_cents", 0)
    V.check_len(assessor_reference, "assessor_reference", 1, 80, non_blank=True)

    if claim["adjustment_status"] not in ("NOTIFIED", "INVESTIGATING", "RESERVED"):
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    if assessed_at < claim["loss_date"] or assessed_at > db.clock:
        raise ApiError("ERR_ASSESSED_AT_OUT_OF_RANGE")

    schedule = db.schedules[claim["schedule_id"]]
    ratio = calc.ctl_ratio_ppm(repair_cost_estimate_cents, schedule["agreed_value_cents"])
    verdict = ("CONSTRUCTIVE_TOTAL_LOSS" if ratio >= C.CTL_THRESHOLD_PPM else "REPAIRABLE")

    rec = new_record(db.assessments, {
        "claim_id": claim["id"],
        "repair_cost_estimate_cents": repair_cost_estimate_cents,
        "assessor_reference": assessor_reference,
        "assessed_at": assessed_at,
        "ctl_ratio_ppm": ratio,
        "verdict": verdict,
    }, versioned=False)

    services.recompute_claim_ctl(claim)
    touch(claim)
    return envelope.ok(serialize.assessment(rec), 201)


@bp.route("/aviation/damage-assessments", methods=["GET"])
@auth.endpoint(ALL)
def list_assessments():
    limit, offset = V.pagination()
    rows = ordered(db.assessments)
    visible = services.visible_policy_ids()
    if visible is not None:
        allowed = set(c["id"] for c in db.claims.values() if c["policy_id"] in visible)
        rows = [r for r in rows if r["claim_id"] in allowed]
    rows = V.filter_eq(rows, "claim_id", request.args.get("claim_id"))
    rows = V.filter_eq(rows, "verdict", request.args.get("verdict"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.assessment, window), limit, offset, total)


@bp.route("/aviation/damage-assessments/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_assessment(row_id):
    rec = services.get_assessment(row_id)
    services.scope_assessment(rec)
    return envelope.ok(serialize.assessment(rec))


# --- the coverage decision ----------------------------------------------------

@bp.route("/aviation/claims/<row_id>/coverage-decision", methods=["POST"])
@auth.endpoint(ADJUSTER)
def decide_coverage(row_id):
    rec = services.get_claim(row_id)
    body = V.json_body()
    decision = V.get_str(body, "decision")
    reserve_cents = V.get_int(body, "reserve_cents", required=False)
    denial_reason = V.get_str(body, "denial_reason", required=False)

    V.check_enum(decision, "decision", ("COVERED", "DENIED"))
    V.check_range(reserve_cents, "reserve_cents", 0)

    if rec["adjustment_status"] not in ("INVESTIGATING", "COVERAGE_REFERRED"):
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    if decision == "COVERED" and reserve_cents is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "reserve_cents is mandatory for a decision of COVERED.")
    if decision == "DENIED" and denial_reason is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "denial_reason is mandatory for a decision of DENIED.")

    if decision == "DENIED":
        rec["adjustment_status"] = "DENIED"
        rec["denial_reason"] = denial_reason
        rec["reserve_cents"] = 0
        rec["coverage_decided_by_user_id"] = g.user_id
        touch(rec)
        return envelope.ok(serialize.claim(rec))

    schedule = db.schedules[rec["schedule_id"]]
    services.require_live_schedule(schedule)

    if rec["cooperation_status"] == "NON_COOPERATION":
        raise ApiError("ERR_INVESTIGATION_COOPERATION_MISSING")

    if rec["loss_type"] in C.HULL_LOSS_TYPES:
        ceiling = schedule["agreed_value_cents"]
    else:
        ceiling = db.policies[rec["policy_id"]]["liability_limit_cents"]
    if reserve_cents > ceiling:
        raise ApiError("ERR_RESERVE_EXCEEDS_LIMIT")

    rec["adjustment_status"] = "RESERVED"
    rec["reserve_cents"] = reserve_cents
    rec["coverage_decided_by_user_id"] = g.user_id
    touch(rec)
    return envelope.ok(serialize.claim(rec))


# --- salvage disposition ------------------------------------------------------

_SALVAGE_TARGET = {
    ("NONE", "RETAIN"): "RETAINED_BY_INSURED",
    ("NONE", "TENDER"): "TENDERED",
    ("TENDERED", "SELL"): "SOLD",
    ("TENDERED", "ABANDON"): "ABANDONED",
}


@bp.route("/aviation/claims/<row_id>/salvage-disposition", methods=["POST"])
@auth.endpoint(ADJUSTER)
def dispose_salvage(row_id):
    rec = services.get_claim(row_id)
    body = V.json_body()
    salvage_action = V.get_str(body, "salvage_action")
    salvage_proceeds_cents = V.get_int(body, "salvage_proceeds_cents", required=False)

    V.check_enum(salvage_action, "salvage_action", C.SALVAGE_ACTIONS)
    V.check_range(salvage_proceeds_cents, "salvage_proceeds_cents", 1)

    if salvage_action in ("RETAIN", "TENDER"):
        if rec["adjustment_status"] not in ("INVESTIGATING", "COVERAGE_REFERRED", "RESERVED"):
            raise ApiError("ERR_CLAIM_INVALID_STATE")

    target = _SALVAGE_TARGET.get((rec["salvage_status"], salvage_action))
    if target is None:
        raise ApiError("ERR_SALVAGE_INVALID_STATE")

    if salvage_action == "TENDER" and not rec["ctl_flag"]:
        raise ApiError("ERR_SALVAGE_INVALID_STATE",
                       "Only a constructive total loss produces a wreck worth tendering.")

    if salvage_action == "SELL" and salvage_proceeds_cents is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "salvage_proceeds_cents is mandatory for an action of SELL.")

    rec["salvage_status"] = target
    if salvage_action == "SELL":
        rec["salvage_proceeds_cents"] = salvage_proceeds_cents
    touch(rec)
    return envelope.ok(serialize.claim(rec))


# --- settlement ---------------------------------------------------------------

def _gross_for_basis(claim, schedule, basis):
    if basis == "AGREED_VALUE":
        return schedule["agreed_value_cents"]
    if basis == "DEPRECIATED_VALUE":
        aircraft = db.aircraft[schedule["aircraft_id"]]
        depreciated = calc.depreciated_hull_value(aircraft, claim["loss_date"].year)
        return min(schedule["agreed_value_cents"], depreciated)
    selected = services.select_assessment(claim["id"])
    return selected["repair_cost_estimate_cents"] if selected is not None else 0


def _basis_permitted(claim, schedule, basis):
    if claim["assessment_count"] < 1:
        return False
    if basis == "AGREED_VALUE":
        return bool(claim["ctl_flag"]) and schedule["warranty_status"] == "COMPLIANT"
    if basis == "DEPRECIATED_VALUE":
        return bool(claim["ctl_flag"])
    return not claim["ctl_flag"]


@bp.route("/aviation/claims/<row_id>/settlement", methods=["POST"])
@auth.endpoint(ADJUSTER)
def settle_claim(row_id):
    rec = services.get_claim(row_id)
    body = V.json_body()
    settlement_basis = V.get_str(body, "settlement_basis")
    V.check_enum(settlement_basis, "settlement_basis", C.SETTLEMENT_BASES)

    if rec["adjustment_status"] != "RESERVED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    policy = db.policies[rec["policy_id"]]
    schedule = db.schedules[rec["schedule_id"]]

    if schedule["warranty_status"] == "BREACHED":
        raise ApiError("ERR_PILOT_WARRANTY_BREACHED")

    if rec["loss_type"] == "WAR_PERIL":
        services.require_placement_covering(policy["id"], rec["loss_date"])

    if g.user_id == rec["coverage_decided_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if not _basis_permitted(rec, schedule, settlement_basis):
        raise ApiError("ERR_SETTLEMENT_BASIS_NOT_PERMITTED")

    if settlement_basis in C.TOTAL_LOSS_BASES and rec["salvage_status"] == "NONE":
        raise ApiError("ERR_SALVAGE_DISPOSITION_REQUIRED")

    gross = _gross_for_basis(rec, schedule, settlement_basis)
    deductible = calc.deductible_on_gross(gross, policy["hull_deductible_ppm"])
    credit = rec["salvage_proceeds_cents"] if rec["salvage_status"] == "SOLD" else 0
    net = gross - deductible - credit
    if net < 0:
        net = 0

    if derive.paid_hull(policy["id"]) + net > policy["hull_aggregate_limit_cents"]:
        raise ApiError("ERR_HULL_AGGREGATE_EXCEEDED")

    rec["settlement_basis"] = settlement_basis
    rec["deductible_applied_cents"] = deductible
    rec["settlement_amount_cents"] = net
    rec["reserve_cents"] = 0
    rec["adjustment_status"] = "SETTLED"
    touch(rec)

    if settlement_basis in C.TOTAL_LOSS_BASES:
        schedule["coverage_status"] = "TOTAL_LOSS_SETTLED"
        touch(schedule)
        unearned = calc.settlement_return(schedule["hull_premium_cents"], rec["loss_date"],
                                          policy["effective_to"], policy["term_days"])
        services.append_transaction(policy["id"], "SETTLEMENT_RETURN", -unearned,
                                    rec["loss_date"], "PRO_RATA",
                                    "settlement of claim %s" % rec["id"])
    return envelope.ok(serialize.claim(rec))


# --- the premium ledger, read side --------------------------------------------

@bp.route("/aviation/premium-transactions", methods=["GET"])
@auth.endpoint(ALL)
def list_transactions():
    limit, offset = V.pagination()
    rows = ordered(db.transactions)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "endorsement_id", request.args.get("endorsement_id"))
    rows = V.filter_eq(rows, "txn_type", request.args.get("txn_type"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.transaction, window), limit, offset, total)


@bp.route("/aviation/premium-transactions/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_transaction(row_id):
    rec = services.get_transaction(row_id)
    services.scope_via_policy(rec["policy_id"])
    return envelope.ok(serialize.transaction(rec))
