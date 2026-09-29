"""Paternity establishment (PRD 3.2)."""
from decimal import Decimal

import common
import db
import middleware
import response
import serialize
import util
import validate
from common import PREFIX
from errors import ApiError
from services import cascade

METHODS = ("VOLUNTARY_ACKNOWLEDGMENT", "GENETIC_TEST", "PRESUMED_MARITAL")
RESCISSION_WINDOW_DAYS = 60
GENETIC_COST_CENTS = 48000
PATERNITY_PROBABILITY_THRESHOLD = Decimal("99.0")
MAX_RESCISSIONS = 1
MAX_SPECIMEN_REJECTIONS = 2

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "ProgramAdmin",
              "CustodialParty", "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "ProgramAdmin"]


def _case_of(action):
    return db.cases.get(action["case_id"])


def _probability(payload):
    if not validate.present(payload, "genetic_probability_pct"):
        validate.fail("genetic_probability_pct is required.")
    raw = payload["genetic_probability_pct"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        validate.fail("genetic_probability_pct must be a number.")
    value = Decimal(str(raw))
    if value < 0 or value > 100:
        validate.fail("genetic_probability_pct must be between 0 and 100.")
    return value


def register(app):
    @app.post(PREFIX + "/cases/<case_id>/paternity-actions")
    def create_paternity_action(case_id):
        middleware.authenticate(["CaseWorker"])
        case = common.case(case_id)
        payload = validate.body()
        method = validate.req_enum(payload, "method", METHODS)
        common.case_writable(case)
        if db.case_paternity_action(case["id"]) is not None:
            raise ApiError("ERR_DUPLICATE_PATERNITY_ACTION")

        status = case["case_status"]
        good_cause = case["good_cause_claim"]
        if method == "PRESUMED_MARITAL":
            if status != "OPENED":
                raise ApiError("ERR_INVALID_CASE_STATUS")
        elif status not in ("OPENED", "LOCATE"):
            # The locate gate below owns the refusal of an obligor nobody has
            # found; the case-status band only rules out states from which
            # PATERNITY_PENDING is unreachable.
            raise ApiError("ERR_INVALID_CASE_STATUS")

        ncp = db.participants[case["noncustodial_party_id"]]
        if good_cause or method == "PRESUMED_MARITAL":
            # UNLOCATABLE blocks every establishment step regardless of good cause.
            if ncp["locate_status"] == "UNLOCATABLE":
                raise ApiError("ERR_NCP_NOT_LOCATED")
        elif ncp["locate_status"] != "LOCATED":
            raise ApiError("ERR_NCP_NOT_LOCATED")

        row = db.stamp_new({
            "case_id": case["id"],
            "method": method,
            "status": "NOT_REQUIRED" if method == "PRESUMED_MARITAL" else "PENDING",
            "notary_verified": False,
            "signed_by_participant_id": None,
            "aop_signed_at": None,
            "rescission_deadline_at": None,
            "rescission_count": 0,
            "genetic_test_ordered_at": None,
            "collection_appointment_at": None,
            "specimen_collected_at": None,
            "specimen_rejection_count": 0,
            "chain_of_custody_ok": None,
            "genetic_probability_pct": None,
            "genetic_cost_cents": 0,
            "genetic_cost_liable_party": "NONE",
            "established_at": None,
            "established_method": None,
        })
        db.paternity_actions[row["id"]] = row
        case["case_status"] = ("ORDER_ESTABLISHMENT" if method == "PRESUMED_MARITAL"
                               else "PATERNITY_PENDING")
        db.touch(case)
        return response.created(serialize.paternity_action(row))

    @app.get(PREFIX + "/paternity-actions/<paternity_action_id>")
    def read_paternity_action(paternity_action_id):
        middleware.authenticate(READ_ROLES)
        row = common.paternity_action(paternity_action_id)
        common.party_guard(_case_of(row))
        return response.ok(serialize.paternity_action(row))

    @app.get(PREFIX + "/paternity-actions")
    def list_paternity_actions():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.paternity_actions.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("status", "status", "str"),
            ("method", "method", "str"),
        ])
        return response.paginate(rows, serialize.paternity_action)

    @app.post(PREFIX + "/paternity-actions/<paternity_action_id>/acknowledgment")
    def record_acknowledgment(paternity_action_id):
        middleware.authenticate(["CaseWorker"])
        action = common.paternity_action(paternity_action_id)
        case = _case_of(action)
        payload = validate.body()
        notary = validate.req_bool(payload, "notary_verified")
        signer_id = validate.req_ref(payload, "signed_by_participant_id")
        if not notary:
            validate.fail("notary_verified must be true.")
        signer = common.ref_participant(signer_id)
        if signer["id"] != case["noncustodial_party_id"]:
            validate.fail("signed_by_participant_id must be the noncustodial party.")
        common.case_writable(case)
        status = action["status"]
        if status == "PENDING":
            if action["method"] != "VOLUNTARY_ACKNOWLEDGMENT":
                raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        elif status != "AOP_RESCINDED":
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")

        signed_at = db.now()
        action["status"] = "AOP_SIGNED"
        action["notary_verified"] = True
        action["signed_by_participant_id"] = signer["id"]
        action["aop_signed_at"] = signed_at
        action["rescission_deadline_at"] = util.add_days(
            signed_at, RESCISSION_WINDOW_DAYS)
        db.touch(action)
        return response.ok(serialize.paternity_action(action))

    @app.post(PREFIX + "/paternity-actions/<paternity_action_id>/rescission")
    def rescind_acknowledgment(paternity_action_id):
        middleware.authenticate(["NoncustodialParty"])
        action = common.paternity_action(paternity_action_id)
        case = _case_of(action)
        middleware.require_case_party(case)
        common.case_writable(case)
        status = action["status"]
        if status != "AOP_SIGNED":
            if status == "ESTABLISHED" and \
                    action["established_method"] == "VOLUNTARY_ACKNOWLEDGMENT":
                raise ApiError("ERR_RESCISSION_WINDOW_CLOSED")
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        deadline = action["rescission_deadline_at"]
        if deadline is not None and db.now() > deadline:
            raise ApiError("ERR_RESCISSION_WINDOW_CLOSED")
        if action["rescission_count"] >= MAX_RESCISSIONS:
            raise ApiError("ERR_RESCISSION_LIMIT")

        action["status"] = "AOP_RESCINDED"
        action["rescission_count"] += 1
        action["aop_signed_at"] = None
        action["rescission_deadline_at"] = None
        db.touch(action)
        return response.ok(serialize.paternity_action(action))

    @app.post(PREFIX + "/paternity-actions/<paternity_action_id>/genetic-test-order")
    def order_genetic_test(paternity_action_id):
        middleware.authenticate(["SupervisingAttorney"])
        action = common.paternity_action(paternity_action_id)
        case = _case_of(action)
        payload = validate.body()
        appointment = validate.req_instant(payload, "collection_appointment_at")
        common.case_writable(case)
        status = action["status"]
        if status == "PENDING":
            if action["method"] != "GENETIC_TEST":
                raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        elif status != "AOP_RESCINDED":
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        if not (appointment > db.now()):
            raise ApiError("ERR_COLLECTION_APPOINTMENT_NOT_REACHED")

        action["status"] = "GENETIC_ORDERED"
        action["method"] = "GENETIC_TEST"
        action["collection_appointment_at"] = appointment
        action["genetic_test_ordered_at"] = db.now()
        action["genetic_cost_cents"] = GENETIC_COST_CENTS
        db.touch(action)
        return response.ok(serialize.paternity_action(action))

    @app.post(PREFIX + "/paternity-actions/<paternity_action_id>/specimen-collection")
    def collect_specimen(paternity_action_id):
        middleware.authenticate(["CaseWorker"])
        action = common.paternity_action(paternity_action_id)
        case = _case_of(action)
        payload = validate.body()
        chain_ok = validate.req_bool(payload, "chain_of_custody_ok")
        common.case_writable(case)
        if action["status"] != "GENETIC_ORDERED":
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        appointment = action["collection_appointment_at"]
        if appointment is not None and db.now() < appointment:
            raise ApiError("ERR_COLLECTION_APPOINTMENT_NOT_REACHED")
        if not chain_ok and action["specimen_rejection_count"] >= MAX_SPECIMEN_REJECTIONS:
            raise ApiError("ERR_SPECIMEN_REJECTION_LIMIT")

        action["chain_of_custody_ok"] = chain_ok
        if chain_ok:
            action["status"] = "GENETIC_COLLECTED"
            action["specimen_collected_at"] = db.now()
        else:
            action["specimen_rejection_count"] += 1
        db.touch(action)
        return response.ok(serialize.paternity_action(action))

    @app.post(PREFIX + "/paternity-actions/<paternity_action_id>/genetic-result")
    def record_genetic_result(paternity_action_id):
        middleware.authenticate(["SupervisingAttorney"])
        action = common.paternity_action(paternity_action_id)
        case = _case_of(action)
        payload = validate.body()
        probability = _probability(payload)
        common.case_writable(case)
        if action["status"] != "GENETIC_COLLECTED":
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")
        if action["chain_of_custody_ok"] is not True:
            raise ApiError("ERR_INVALID_PATERNITY_STATUS")

        action["genetic_probability_pct"] = probability
        if probability >= PATERNITY_PROBABILITY_THRESHOLD:
            action["status"] = "ESTABLISHED"
            action["established_at"] = db.now()
            action["established_method"] = "GENETIC_TEST"
            action["genetic_cost_liable_party"] = "NCP"
            db.touch(action)
            if case["case_status"] == "PATERNITY_PENDING":
                case["case_status"] = "ORDER_ESTABLISHMENT"
                db.touch(case)
        else:
            action["status"] = "EXCLUDED"
            action["genetic_cost_liable_party"] = "STATE"
            db.touch(action)
            cascade.paternity_excluded_cascade(action, case)
        return response.ok(serialize.paternity_action(action))
