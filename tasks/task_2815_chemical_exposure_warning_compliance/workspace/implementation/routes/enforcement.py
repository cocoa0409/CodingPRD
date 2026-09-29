"""Notice intake, the sixty-day cure window and settlement money (PRD 3.8)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard
from util import D, days
from routes.common import list_endpoint
from services import calc, money, posture

bp = Blueprint("enforcement", __name__)

PARTY_TYPES = ("PRIVATE_PARTY", "ATTORNEY_GENERAL", "DISTRICT_ATTORNEY")
VIOLATION_TYPES = ("FAILURE_TO_WARN", "INADEQUATE_WARNING_CONTENT", "EXPOSURE_LEVEL_DISPUTE")
CURE_WINDOW_DAYS = 60
CURE_UNIT_CEILING = 100000
READ_ROLES = ("ComplianceAnalyst", "RegulatoryCounsel", "RegistryAdmin")
NOTICE_TRIGGERS = ("EVALUATE", "ELECT_CURE", "COMPLETE_CURE", "ABANDON_CURE",
                   "ESCALATE", "DISMISS", "LITIGATE")
NOTICE_LEGAL = {
    "EVALUATE": ("RECEIVED",),
    "ELECT_CURE": ("UNDER_EVALUATION",),
    "COMPLETE_CURE": ("CURE_ELECTED",),
    "ABANDON_CURE": ("CURE_ELECTED",),
    "ESCALATE": ("UNDER_EVALUATION", "CURE_FAILED"),
    "DISMISS": ("UNDER_EVALUATION",),
    "LITIGATE": ("SETTLEMENT_NEGOTIATION",),
}
SETTLEMENT_TRIGGERS = ("COUNTER", "REVISE", "ACCEPT_EXECUTE", "VOID")
SETTLEMENT_LEGAL = {
    "COUNTER": ("PROPOSED",),
    "REVISE": ("COUNTERED",),
    "ACCEPT_EXECUTE": ("PROPOSED", "COUNTERED"),
    "VOID": ("EXECUTED",),
}
LIVE_SETTLEMENT_STATUSES = ("PROPOSED", "COUNTERED", "EXECUTED")


def _full_coverage_determination(product):
    for determination in calc.determinations_of(product["id"]):
        if determination["status"] != "APPROVED":
            continue
        required = determination.get("required_channels") or []
        if posture.covered_channel_count(determination) == len(required):
            return determination
    return None


@bp.route("/notices", methods=["POST"])
@guard("RegulatoryCounsel")
def create_notice(who):
    body = validate.body_json()
    validate.v_str(body, "product_id", required=True)
    validate.v_str(body, "chemical_id", required=True)
    party_name = validate.v_str(body, "noticing_party_name", required=True,
                                minlen=1, maxlen=160)
    party_type = validate.v_enum(body, "noticing_party_type", PARTY_TYPES, required=True)
    violation_type = validate.v_enum(body, "alleged_violation_type", VIOLATION_TYPES,
                                     required=True)
    alleged_units = validate.v_int(body, "alleged_units", required=True)
    earliest = validate.v_dt(body, "earliest_violation_date", required=True)
    served_at = validate.v_dt(body, "served_at", required=True)
    validate.v_domain(body)
    product = validate.fk("products", body, "product_id", required=True)
    chemical = validate.fk("listed_chemicals", body, "chemical_id", required=True)
    validate.v_writable(body, ("product_id", "chemical_id", "noticing_party_name",
                               "noticing_party_type", "alleged_violation_type",
                               "alleged_units", "earliest_violation_date", "served_at"))
    if earliest > served_at:
        fail("ERR_INVALID_INTERVAL", "earliest_violation_date may not be later than served_at")
    if served_at > db.now():
        fail("ERR_INVALID_INTERVAL", "served_at may not be later than the current clock")
    row = db.insert("notices", {
        "product_id": product["id"],
        "chemical_id": chemical["id"],
        "noticing_party_name": party_name,
        "noticing_party_type": party_type,
        "alleged_violation_type": violation_type,
        "alleged_units": alleged_units,
        "earliest_violation_date": earliest,
        "served_at": served_at,
        "cure_deadline_at": served_at + days(CURE_WINDOW_DAYS),
        "cure_eligible": None,
        "cure_completed_at": None,
        "cure_attempted": False,
        "status": "RECEIVED",
        "evaluation_note": None,
    })
    db.touch(product)
    posture.recompute_posture(product)
    return response.created(db.serialize("notices", row))


@bp.route("/notices/<notice_id>/transitions", methods=["POST"])
@guard("RegulatoryCounsel")
def transition_notice(who, notice_id):
    body = validate.body_json()
    action = validate.v_action(body, NOTICE_TRIGGERS)
    if action == "DISMISS":
        note = validate.v_str(body, "evaluation_note", required=True, minlen=1)
    else:
        note = validate.v_str(body, "evaluation_note")
    notice = validate.must_exist("notices", notice_id, "notice")
    if notice["status"] not in NOTICE_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, notice["status"]))
    validate.v_writable(body, ("action", "evaluation_note"))
    product = db.get("products", notice["product_id"])

    if action == "EVALUATE":
        eligible = (notice["alleged_violation_type"] == "FAILURE_TO_WARN"
                    and notice["noticing_party_type"] == "PRIVATE_PARTY"
                    and int(product["annual_units"]) <= CURE_UNIT_CEILING
                    and not money.quiet_period_settlement_exists(notice))
        notice["cure_eligible"] = bool(eligible)
        notice["status"] = "UNDER_EVALUATION"
    elif action == "ELECT_CURE":
        if not notice.get("cure_eligible"):
            fail("ERR_CURE_NOT_AVAILABLE", "this notice is not eligible for cure")
        if db.now() > notice["cure_deadline_at"]:
            fail("ERR_CURE_NOT_AVAILABLE", "the cure window has already closed")
        if money.quiet_period_settlement_exists(notice):
            fail("ERR_CURE_NOT_AVAILABLE",
                 "an executed settlement sits inside the three-year quiet period")
        notice["cure_attempted"] = True
        notice["status"] = "CURE_ELECTED"
    elif action == "COMPLETE_CURE":
        if db.now() > notice["cure_deadline_at"]:
            fail("ERR_CURE_WINDOW_CLOSED", "the cure deadline has passed")
        if _full_coverage_determination(product) is None:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "the warning is not up on every required channel")
        notice["cure_completed_at"] = db.now()
        notice["status"] = "CURED_WITHIN_WINDOW"
    elif action == "ABANDON_CURE":
        notice["status"] = "CURE_FAILED"
    elif action == "ESCALATE":
        notice["status"] = "SETTLEMENT_NEGOTIATION"
    elif action == "DISMISS":
        notice["status"] = "DISMISSED"
    else:
        if not any(int(s.get("round_count") or 0) == money.SETTLEMENT_ROUND_CEILING
                   for s in calc.settlements_of(notice["id"])):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "negotiation has not been exhausted to the round ceiling")
        for settlement in calc.settlements_of(notice["id"]):
            if settlement["status"] in ("PROPOSED", "COUNTERED"):
                settlement["status"] = "VOID"
                db.touch(settlement)
        notice["status"] = "LITIGATION"
    if note is not None:
        notice["evaluation_note"] = note
    db.touch(notice)
    db.touch(product)
    posture.recompute_posture(product)
    return response.ok(db.serialize("notices", notice))


@bp.route("/notices/<notice_id>/settlements", methods=["POST"])
@guard("RegulatoryCounsel")
def create_settlement(who, notice_id):
    body = validate.body_json()
    fees = validate.v_int(body, "requested_attorney_fees_cents", required=True)
    commitment = validate.v_bool(body, "reformulation_commitment")
    expected = validate.v_version(body, "expected_notice_version")
    validate.v_domain(body)
    notice = validate.must_exist("notices", notice_id, "notice")
    if expected != int(notice["version"]):
        fail("ERR_STALE_NOTICE_VERSION",
             "expected_notice_version %s does not match the notice version %s"
             % (expected, notice["version"]))
    validate.v_writable(body, ("requested_attorney_fees_cents",
                               "reformulation_commitment", "expected_notice_version"))
    if notice["status"] != "SETTLEMENT_NEGOTIATION":
        fail("ERR_NOTICE_NOT_NEGOTIABLE",
             "the notice is in status %s" % notice["status"])
    for other in calc.settlements_of(notice["id"]):
        if other["status"] in LIVE_SETTLEMENT_STATUSES:
            fail("ERR_OPEN_SETTLEMENT_EXISTS",
                 "this notice already holds a settlement in status %s" % other["status"])
    if fees > money.FEE_REQUEST_CEILING_CENTS:
        fail("ERR_FEE_REQUEST_EXCEEDS_CEILING",
             "requested_attorney_fees_cents exceeds the ceiling of %d"
             % money.FEE_REQUEST_CEILING_CENTS)
    window = money.violation_days(notice)
    if window <= 0:
        fail("ERR_NO_VIOLATION_WINDOW", "the computed violation window is not positive")
    product = db.get("products", notice["product_id"])
    for other in calc.settlements_of(notice["id"]):
        if other["status"] in ("PROPOSED", "COUNTERED"):
            other["status"] = "VOID"
            db.touch(other)
    row = db.insert("settlements", {
        "notice_id": notice["id"],
        "requested_attorney_fees_cents": fees,
        "reformulation_commitment": bool(commitment) if commitment is not None else False,
        "violation_days": None,
        "base_penalty_cents": None,
        "mitigation_factor": None,
        "adjusted_penalty_cents": None,
        "fee_cap_cents": None,
        "allowed_fees_cents": None,
        "state_share_cents": None,
        "noticing_party_share_cents": None,
        "total_settlement_cents": None,
        "round_count": 0,
        "status": "PROPOSED",
        "proposed_by_user_id": who.user_id,
        "executed_by_user_id": None,
        "executed_at": None,
    })
    money.compute_at_create(row, notice, product, window)
    db.touch(notice)
    return response.created(db.serialize("settlements", row))


@bp.route("/settlements/<settlement_id>/transitions", methods=["POST"])
@guard("RegulatoryCounsel")
def transition_settlement(who, settlement_id):
    body = validate.body_json()
    action = validate.v_action(body, SETTLEMENT_TRIGGERS)
    fees = validate.v_int(body, "requested_attorney_fees_cents")
    commitment = validate.v_bool(body, "reformulation_commitment")
    validate.v_domain(body)
    settlement = validate.must_exist("settlements", settlement_id, "settlement")
    if settlement["status"] not in SETTLEMENT_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, settlement["status"]))
    validate.v_writable(body, ("action", "requested_attorney_fees_cents",
                               "reformulation_commitment"))
    notice = db.get("notices", settlement["notice_id"])
    product = db.get("products", notice["product_id"]) if notice is not None else None

    if action in ("COUNTER", "REVISE"):
        if int(settlement.get("round_count") or 0) >= money.SETTLEMENT_ROUND_CEILING:
            fail("ERR_SETTLEMENT_ROUND_LIMIT",
                 "the negotiation round ceiling of %d has been reached"
                 % money.SETTLEMENT_ROUND_CEILING)
        if fees is not None:
            if fees > money.FEE_REQUEST_CEILING_CENTS:
                fail("ERR_FEE_REQUEST_EXCEEDS_CEILING",
                     "requested_attorney_fees_cents exceeds the ceiling of %d"
                     % money.FEE_REQUEST_CEILING_CENTS)
            settlement["requested_attorney_fees_cents"] = fees
        if commitment is not None:
            settlement["reformulation_commitment"] = bool(commitment)
        money.recompute_from_mitigation(settlement, notice, product)
        settlement["round_count"] = int(settlement.get("round_count") or 0) + 1
        settlement["status"] = "COUNTERED" if action == "COUNTER" else "PROPOSED"
        db.touch(settlement)
        return response.ok(db.serialize("settlements", settlement))

    if action == "ACCEPT_EXECUTE":
        if who.user_id is not None and who.user_id == settlement.get("proposed_by_user_id"):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the proposer of this settlement may not execute it")
        if settlement.get("_warranty_applied") and \
                int(settlement["adjusted_penalty_cents"]) > \
                money.available_indemnity_cents(product):
            fail("ERR_INDEMNITY_CAP_EXCEEDED",
                 "the adjusted penalty exceeds the available supplier indemnity")
        settlement["status"] = "EXECUTED"
        settlement["executed_by_user_id"] = who.user_id
        settlement["executed_at"] = db.now()
        db.touch(settlement)
        notice["status"] = "SETTLED"
        db.touch(notice)
    else:
        if settlement.get("reformulation_commitment") and _commitment_delivered(notice):
            fail("ERR_SETTLEMENT_NOT_VOIDABLE",
                 "the promised reformulation has already been delivered")
        settlement["status"] = "VOID"
        db.touch(settlement)
        notice["status"] = "SETTLEMENT_NEGOTIATION"
        db.touch(notice)
    db.touch(product)
    posture.recompute_posture(product)
    return response.ok(db.serialize("settlements", settlement))


def _commitment_delivered(notice):
    for project in db.rows("reformulation_projects"):
        if project["product_id"] != notice["product_id"]:
            continue
        if project["chemical_id"] != notice["chemical_id"]:
            continue
        if project["status"] == "COMPLETED":
            return True
    return False


@bp.route("/notices/<notice_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_notice(who, notice_id):
    notice = validate.must_exist("notices", notice_id, "notice")
    return response.ok(db.serialize("notices", notice))


@bp.route("/notices", methods=["GET"])
@guard(*READ_ROLES)
def list_notices(who):
    return list_endpoint("notices", {
        "product_id": "product_id",
        "chemical_id": "chemical_id",
        "status": "status",
        "noticing_party_type": "noticing_party_type",
    })


@bp.route("/settlements/<settlement_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_settlement(who, settlement_id):
    settlement = validate.must_exist("settlements", settlement_id, "settlement")
    return response.ok(db.serialize("settlements", settlement))


@bp.route("/settlements", methods=["GET"])
@guard(*READ_ROLES)
def list_settlements(who):
    return list_endpoint("settlements", {
        "notice_id": "notice_id",
        "status": "status",
    })
