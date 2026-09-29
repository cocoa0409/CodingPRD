"""Guideline worksheet, order entry, deviation and vacatur (PRD 3.3)."""
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
from services import cascade, controlling, guideline

ORDER_TYPES = ("CURRENT_SUPPORT", "MEDICAL_SUPPORT")
DEVIATION_REASONS = ("EXTRAORDINARY_MEDICAL", "SHARED_PARENTING",
                     "HIGH_INCOME", "HARDSHIP")
VACATE_REASONS = ("PATERNITY_EXCLUDED", "JURISDICTION_DEFECT", "CLERICAL_ERROR")
DECISIONS = ("APPROVE", "REJECT")
REVIEW_ELIGIBILITY_MONTHS = 36
MAX_DEVIATION_REJECTIONS = 2
DEVIATION_MATERIALITY_NUMERATOR = 10   # 10 percent, by integer cross-multiplication
DEVIATION_MATERIALITY_SCALE = 100

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin", "CustodialParty",
              "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin"]


def paternity_established(case):
    action = db.case_paternity_action(case["id"])
    return action is not None and action["status"] in ("ESTABLISHED", "NOT_REQUIRED")


def require_paternity(case):
    if not paternity_established(case):
        raise ApiError("ERR_PATERNITY_NOT_ESTABLISHED")


def require_located(case):
    ncp = db.participants[case["noncustodial_party_id"]]
    if case["good_cause_claim"]:
        if ncp["locate_status"] == "UNLOCATABLE":
            raise ApiError("ERR_NCP_NOT_LOCATED")
    elif ncp["locate_status"] != "LOCATED":
        raise ApiError("ERR_NCP_NOT_LOCATED")


def modification_predecessor(order):
    """The order this successor will supersede, if it came from a review."""
    for review in db.modification_reviews.values():
        if review.get("proposed_order_id") == order["id"]:
            return db.orders.get(review["order_id"])
    return None


def _overlaps(a_start, a_end, b_start, b_end):
    """Closed intervals; a null terminated_date runs to infinity."""
    if a_end is not None and b_start > a_end:
        return False
    if b_end is not None and a_start > b_end:
        return False
    return True


def require_no_interval_overlap(order, case, exclude_id=None):
    for other in db.case_orders(case["id"]):
        if other["id"] == order["id"] or other["id"] == exclude_id:
            continue
        if other["status"] != "ENTERED" or other["order_type"] != order["order_type"]:
            continue
        if _overlaps(other["effective_date"], other["terminated_date"],
                     order["effective_date"], order["terminated_date"]):
            raise ApiError("ERR_ORDER_INTERVAL_OVERLAP")


def enter_order(order, case, monthly_obligation_cents):
    """The shared ENTERED join point, plus modification supersession."""
    predecessor = modification_predecessor(order)
    order["status"] = "ENTERED"
    order["monthly_obligation_cents"] = monthly_obligation_cents
    order["next_accrual_due_date"] = order["effective_date"]
    db.touch(order)
    if predecessor is not None and predecessor["status"] == "ENTERED" \
            and predecessor["order_type"] == order["order_type"] \
            and predecessor["effective_date"] < order["effective_date"]:
        predecessor["status"] = "SUPERSEDED"
        predecessor["superseded_by_order_id"] = order["id"]
        predecessor["terminated_date"] = util.add_days(order["effective_date"], -1)
        db.touch(predecessor)
        cascade.terminate_order_iwos(predecessor, "ORDER_SUPERSEDED",
                                     from_states=("SERVED",))
    if case["case_status"] == "ORDER_ESTABLISHMENT":
        case["case_status"] = "ENFORCEMENT"
    db.touch(case)


def register(app):
    @app.post(PREFIX + "/cases/<case_id>/orders")
    def draft_order(case_id):
        middleware.authenticate(["CaseWorker"])
        case = common.case(case_id)
        payload = validate.body()
        order_type = validate.req_enum(payload, "order_type", ORDER_TYPES)
        origin = validate.opt_str(payload, "origin_state_code", db.HOME_STATE_CODE)
        if origin not in db.STATE_CODES:
            validate.fail("origin_state_code must be one of %s."
                          % ", ".join(db.STATE_CODES))
        effective_date = validate.req_day(payload, "effective_date")
        medical = validate.opt_money(payload, "medical_support_monthly_cents", 0)
        requested = validate.opt_money(payload, "requested_monthly_cents")
        # A drafting attempt rejects only a CLOSED case on case-status grounds;
        # any other unready case answers ERR_PATERNITY_NOT_ESTABLISHED (PRD 2.9).
        common.case_writable(case)
        require_paternity(case)
        require_located(case)

        row = db.stamp_new({
            "case_id": case["id"],
            "order_type": order_type,
            "origin_state_code": origin,
            "status": "DRAFT",
            "effective_date": effective_date,
            "terminated_date": None,
            "requested_monthly_cents": requested,
            "medical_support_monthly_cents": medical,
            "guideline_monthly_cents": None,
            "guideline_cp_income_cents": None,
            "guideline_ncp_income_cents": None,
            "guideline_basic_obligation_cents": None,
            "guideline_ncp_share_ratio": None,
            "multi_family_credit_cents": 0,
            "imputation_applied": False,
            "monthly_obligation_cents": None,
            "deviation_applied": False,
            "deviation_requested_cents": None,
            "deviation_reason": None,
            "deviation_rejection_count": 0,
            "drafted_by_user_id": None,
            "findings_approved_by_user_id": None,
            "superseded_by_order_id": None,
            "next_accrual_due_date": None,
            "vacate_reason": None,
        })
        db.orders[row["id"]] = row
        return response.created(serialize.order(row))

    @app.get(PREFIX + "/orders/<order_id>")
    def read_order(order_id):
        middleware.authenticate(READ_ROLES)
        row = common.order(order_id)
        common.party_guard(common.case_of_order(row))
        return response.ok(serialize.order(row))

    @app.get(PREFIX + "/orders")
    def list_orders():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.orders.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("status", "status", "str"),
            ("order_type", "order_type", "str"),
            ("origin_state_code", "origin_state_code", "str"),
            ("superseded_by_order_id", "superseded_by_order_id", "str"),
        ])
        return response.paginate(rows, serialize.order)

    @app.post(PREFIX + "/orders/<order_id>/guideline-calculation")
    def calculate_guideline(order_id):
        middleware.authenticate(["CaseWorker"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        common.case_writable(case)
        if case["case_status"] not in ("ORDER_ESTABLISHMENT", "ENFORCEMENT"):
            raise ApiError("ERR_INVALID_CASE_STATUS")
        if order["status"] == "CALCULATED":
            if order["deviation_applied"]:
                raise ApiError("ERR_INVALID_ORDER_STATUS")
        elif order["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        require_paternity(case)

        cp = db.participants[case["custodial_party_id"]]
        ncp = db.participants[case["noncustodial_party_id"]]
        result = guideline.compute(cp, ncp, case["child_count"])
        order.update(result)
        order["status"] = "CALCULATED"
        order["drafted_by_user_id"] = middleware.user_id()
        db.touch(order)
        return response.ok(serialize.order(order))

    @app.post(PREFIX + "/orders/<order_id>/deviation-request")
    def request_deviation(order_id):
        middleware.authenticate(["CaseWorker"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        requested = validate.req_money(payload, "deviation_requested_cents")
        reason = validate.req_enum(payload, "deviation_reason", DEVIATION_REASONS)
        common.case_writable(case)
        if order["status"] != "CALCULATED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        baseline = order["guideline_monthly_cents"] or 0
        difference = abs(requested - baseline)
        if difference * DEVIATION_MATERIALITY_SCALE < baseline * DEVIATION_MATERIALITY_NUMERATOR:
            raise ApiError("ERR_DEVIATION_BELOW_MIN_PCT")

        order["status"] = "PENDING_DEVIATION_FINDINGS"
        order["deviation_requested_cents"] = requested
        order["deviation_reason"] = reason
        db.touch(order)
        return response.ok(serialize.order(order))

    @app.post(PREFIX + "/orders/<order_id>/deviation-findings")
    def decide_deviation(order_id):
        middleware.authenticate(["SupervisingAttorney"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        decision = validate.req_enum(payload, "decision", DECISIONS)
        common.case_writable(case)
        if order["status"] != "PENDING_DEVIATION_FINDINGS":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        if middleware.user_id() == order["drafted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        if decision == "APPROVE":
            order["deviation_applied"] = True
            order["findings_approved_by_user_id"] = middleware.user_id()
            enter_order(order, case, order["deviation_requested_cents"])
        else:
            if order["deviation_rejection_count"] >= MAX_DEVIATION_REJECTIONS:
                raise ApiError("ERR_DEVIATION_REJECTION_LIMIT")
            order["status"] = "CALCULATED"
            order["deviation_rejection_count"] += 1
            order["deviation_requested_cents"] = None
            order["deviation_reason"] = None
            db.touch(order)
        return response.ok(serialize.order(order))

    @app.post(PREFIX + "/orders/<order_id>/entry")
    def enter(order_id):
        middleware.authenticate(["SupervisingAttorney"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        common.case_writable(case)
        if order["status"] != "CALCULATED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        if order["guideline_monthly_cents"] is None:
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        controlling.enforce_cej(case)
        predecessor = modification_predecessor(order)
        require_no_interval_overlap(
            order, case,
            exclude_id=predecessor["id"] if predecessor is not None else None)
        enter_order(order, case, order["guideline_monthly_cents"])
        return response.ok(serialize.order(order))

    @app.post(PREFIX + "/orders/<order_id>/vacatur")
    def vacate(order_id):
        middleware.authenticate(["SupervisingAttorney"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        reason = validate.req_enum(payload, "vacate_reason", VACATE_REASONS)
        common.case_writable(case)
        if order["status"] == "DRAFT":
            order["status"] = "VACATED"
            order["vacate_reason"] = reason
            db.touch(order)
        elif order["status"] == "ENTERED":
            if any(o["status"] in ("ACCEPTED", "ACTIVE")
                   for o in db.case_offers(case["id"])):
                raise ApiError("ERR_ACTIVE_OFFER_EXISTS")
            cascade.vacate_entered_order(order, case, reason)
        else:
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        return response.ok(serialize.order(order))
