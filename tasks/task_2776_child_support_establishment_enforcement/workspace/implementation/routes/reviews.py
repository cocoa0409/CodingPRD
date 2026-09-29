"""Modification review, the substantial-change test and the successor order
(PRD 3.8).
"""
import common
import db
import middleware
import response
import serialize
import util
import validate
from common import PREFIX
from errors import ApiError
from services import guideline

TRIGGER_TYPES = ("PARTY_REQUEST", "PERIODIC_36_MONTH", "PA_MANDATORY")
INCOME_SOURCES = ("VERIFIED_WAGE_RECORD", "SELF_REPORTED", "NONE")
REVIEW_ELIGIBILITY_MONTHS = 36
INFO_REQUEST_LIMIT = 2
RELATIVE_GATE_NUMERATOR = 1500      # 15.00 percent, by cross-multiplication
RELATIVE_GATE_SCALE = 10000
ABSOLUTE_GATE_CENTS = 5000

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "ProgramAdmin",
              "CustodialParty", "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "ProgramAdmin"]


def _verified(participant):
    return participant.get("income_verification_source") == "VERIFIED_WAGE_RECORD"


def _substantial_change(trigger_type, variance, snapshot):
    """Relative gate by integer cross-multiplication; absolute gate in cents."""
    absolute_met = variance >= ABSOLUTE_GATE_CENTS
    if trigger_type == "PERIODIC_36_MONTH":
        # The three-year cycle waives the percentage requirement entirely.
        return absolute_met
    relative_met = (variance * RELATIVE_GATE_SCALE
                    >= RELATIVE_GATE_NUMERATOR * snapshot)
    return relative_met and absolute_met


def register(app):
    @app.post(PREFIX + "/orders/<order_id>/modification-reviews")
    def open_review(order_id):
        middleware.authenticate(["CaseWorker"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        trigger = validate.req_enum(payload, "trigger_type", TRIGGER_TYPES)
        common.case_writable(case)
        if order["status"] != "ENTERED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        eligible = util.add_months_date(order["effective_date"],
                                        REVIEW_ELIGIBILITY_MONTHS)
        if trigger == "PERIODIC_36_MONTH" and db.now().date() < eligible:
            raise ApiError("ERR_REVIEW_NOT_YET_ELIGIBLE")

        row = db.stamp_new({
            "case_id": case["id"],
            "order_id": order["id"],
            "trigger_type": trigger,
            "status": "REQUESTED",
            "current_obligation_snapshot_cents": order["monthly_obligation_cents"],
            "recalculated_guideline_cents": None,
            "variance_numerator_cents": None,
            "substantial_change_met": None,
            "info_request_count": 0,
            "info_requested_reason": None,
            "review_eligible_date": eligible,
            "screened_at": None,
            "proposed_order_id": None,
        })
        db.modification_reviews[row["id"]] = row
        return response.created(serialize.review(row))

    @app.get(PREFIX + "/modification-reviews/<modification_review_id>")
    def read_review(modification_review_id):
        middleware.authenticate(READ_ROLES)
        row = common.review(modification_review_id)
        common.party_guard(db.cases[row["case_id"]])
        return response.ok(serialize.review(row))

    @app.get(PREFIX + "/modification-reviews")
    def list_reviews():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.modification_reviews.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("order_id", "order_id", "str"),
            ("proposed_order_id", "proposed_order_id", "str"),
            ("status", "status", "str"),
            ("trigger_type", "trigger_type", "str"),
        ])
        return response.paginate(rows, serialize.review)

    @app.post(PREFIX + "/modification-reviews/<modification_review_id>/screening")
    def screen(modification_review_id):
        middleware.authenticate(["CaseWorker"])
        review = common.review(modification_review_id)
        case = db.cases[review["case_id"]]
        common.case_writable(case)
        if review["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_REVIEW_STATUS")

        cp = db.participants[case["custodial_party_id"]]
        ncp = db.participants[case["noncustodial_party_id"]]
        # The obligor is checked before the custodial party.
        reason = None
        if not _verified(ncp):
            reason = "NCP_INCOME_UNVERIFIED"
        elif not _verified(cp):
            reason = "CP_INCOME_UNVERIFIED"
        if reason is not None:
            review["status"] = "INFO_PENDING"
            review["info_request_count"] += 1
            review["info_requested_reason"] = reason
            db.touch(review)
            return response.ok(serialize.review(review))

        worksheet = guideline.compute(cp, ncp, case["child_count"])
        recalculated = worksheet["guideline_monthly_cents"]
        snapshot = review["current_obligation_snapshot_cents"] or 0
        variance = abs(recalculated - snapshot)
        met = _substantial_change(review["trigger_type"], variance, snapshot)
        review["recalculated_guideline_cents"] = recalculated
        review["variance_numerator_cents"] = variance
        review["substantial_change_met"] = met
        review["screened_at"] = db.now()
        review["status"] = "THRESHOLD_MET" if met else "THRESHOLD_NOT_MET"
        db.touch(review)
        return response.ok(serialize.review(review))

    @app.post(PREFIX + "/modification-reviews/<modification_review_id>/information")
    def supply_information(modification_review_id):
        middleware.authenticate(["CaseWorker"])
        review = common.review(modification_review_id)
        case = db.cases[review["case_id"]]
        payload = validate.body()
        participant_id = validate.req_ref(payload, "participant_id")
        income = validate.req_money(payload, "monthly_gross_income_cents")
        source = validate.req_enum(payload, "income_verification_source",
                                   INCOME_SOURCES)
        participant = common.ref_participant(participant_id)
        common.case_writable(case)
        if review["status"] != "INFO_PENDING":
            raise ApiError("ERR_INVALID_REVIEW_STATUS")
        if participant["id"] not in (case["custodial_party_id"],
                                    case["noncustodial_party_id"]):
            raise ApiError("ERR_PARTY_ROLE_MISMATCH")
        if review["info_request_count"] > INFO_REQUEST_LIMIT:
            raise ApiError("ERR_INFO_REQUEST_LIMIT")

        participant["monthly_gross_income_cents"] = income
        participant["income_verification_source"] = source
        db.touch(participant)
        review["status"] = "REQUESTED"
        review["info_requested_reason"] = None
        db.touch(review)
        return response.ok(serialize.review(review))

    @app.post(PREFIX + "/modification-reviews/<modification_review_id>"
                       "/proposed-order")
    def propose_order(modification_review_id):
        middleware.authenticate(["SupervisingAttorney"])
        review = common.review(modification_review_id)
        case = db.cases[review["case_id"]]
        reviewed = db.orders[review["order_id"]]
        payload = validate.body()
        effective_date = validate.req_day(payload, "effective_date")
        common.case_writable(case)
        if review["status"] != "THRESHOLD_MET":
            raise ApiError("ERR_INVALID_REVIEW_STATUS")
        if case["interstate_role"] == "RESPONDING":
            foreign = [r for r in db.case_referrals(case["id"])
                       if r["status"] in ("REGISTERED", "ENFORCING")
                       and r["controlling_order_state_code"] is not None
                       and r["controlling_order_state_code"] != db.HOME_STATE_CODE]
            if foreign:
                raise ApiError("ERR_NO_CONTROLLING_ORDER_JURISDICTION")
        if not (effective_date > reviewed["effective_date"]):
            raise ApiError("ERR_MODIFICATION_EFFECTIVE_DATE_NOT_LATER")

        successor = db.stamp_new({
            "case_id": case["id"],
            "order_type": reviewed["order_type"],
            "origin_state_code": reviewed["origin_state_code"],
            "status": "CALCULATED",
            "effective_date": effective_date,
            "terminated_date": None,
            "requested_monthly_cents": None,
            "medical_support_monthly_cents":
                reviewed["medical_support_monthly_cents"],
            "guideline_monthly_cents": review["recalculated_guideline_cents"],
            "guideline_cp_income_cents": reviewed["guideline_cp_income_cents"],
            "guideline_ncp_income_cents": reviewed["guideline_ncp_income_cents"],
            "guideline_basic_obligation_cents":
                reviewed["guideline_basic_obligation_cents"],
            "guideline_ncp_share_ratio": reviewed["guideline_ncp_share_ratio"],
            "multi_family_credit_cents": reviewed["multi_family_credit_cents"],
            "imputation_applied": reviewed["imputation_applied"],
            "monthly_obligation_cents": None,
            "deviation_applied": False,
            "deviation_requested_cents": None,
            "deviation_reason": None,
            "deviation_rejection_count": 0,
            "drafted_by_user_id": middleware.user_id(),
            "findings_approved_by_user_id": None,
            "superseded_by_order_id": None,
            "next_accrual_due_date": None,
            "vacate_reason": None,
        })
        db.orders[successor["id"]] = successor
        review["proposed_order_id"] = successor["id"]
        review["status"] = "ORDER_PROPOSED"
        db.touch(review)
        return response.ok(serialize.review(review))
