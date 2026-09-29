"""Obligation charges and payment collections (PRD 3.5)."""
import common
import db
import middleware
import response
import serialize
import util
import validate
from common import PREFIX
from errors import ApiError
from services import cascade, payments

CHARGE_TYPES = ("CURRENT_SUPPORT", "MEDICAL_SUPPORT", "ARREARS_JUDGMENT",
                "GENETIC_TEST_COST")
PAYMENT_SOURCES = ("DIRECT_PAY", "TAX_REFUND_INTERCEPT", "LIEN_LEVY",
                   "COMPROMISE_INSTALLMENT", "REVERSAL", "INCOME_WITHHOLDING")

PARTY_READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
                    "ProgramAdmin", "CustodialParty", "NoncustodialParty"]
STAFF_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer", "ProgramAdmin"]

DEFAULT_AMOUNT_FIELD = {
    "CURRENT_SUPPORT": "monthly_obligation_cents",
    "MEDICAL_SUPPORT": "medical_support_monthly_cents",
}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intervals; abutment is not an overlap."""
    return a_start < b_end and b_start < a_end


def register(app):
    @app.post(PREFIX + "/orders/<order_id>/charges")
    def post_charge(order_id):
        middleware.authenticate(["FinanceOfficer"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        charge_type = validate.req_enum(payload, "charge_type", CHARGE_TYPES)
        period_start = validate.req_day(payload, "period_start_date")
        period_end = validate.req_day(payload, "period_end_date")
        due_date = validate.req_day(payload, "due_date")
        amount = validate.opt_money(payload, "amount_cents")
        if not (period_start < period_end):
            validate.fail("period_end_date must be after period_start_date.")
        # The due_date lives in the half-open window [start, end).
        if not (period_start <= due_date < period_end):
            validate.fail("due_date must satisfy period_start_date <= due_date < "
                          "period_end_date.")
        if amount is None:
            field = DEFAULT_AMOUNT_FIELD.get(charge_type)
            amount = order[field] if field else None
            if amount is None:
                validate.fail("amount_cents is required for a %s charge."
                              % charge_type)

        common.case_writable(case)
        if order["status"] != "ENTERED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")

        for other in db.order_charges(order["id"]):
            if other["status"] == "VOID" or other["charge_type"] != charge_type:
                continue
            if _overlaps(period_start, period_end,
                         other["period_start_date"], other["period_end_date"]):
                raise ApiError("ERR_CHARGE_PERIOD_OVERLAP")

        row = db.stamp_new_immutable({
            "case_id": case["id"],
            "order_id": order["id"],
            "charge_type": charge_type,
            "period_start_date": period_start,
            "period_end_date": period_end,
            "due_date": due_date,
            "amount_cents": amount,
            "paid_cents": 0,
            "unpaid_balance_cents": amount,
            "interest_accrued_cents": 0,
            "status": "OPEN",
        })
        db.charges[row["id"]] = row
        case["total_charged_principal_cents"] += amount
        anchor = order["next_accrual_due_date"] or due_date
        order["next_accrual_due_date"] = util.add_months_date(anchor, 1)
        db.touch(case)
        db.touch(order)
        return response.created(serialize.charge(row))

    @app.get(PREFIX + "/charges/<charge_id>")
    def read_charge(charge_id):
        middleware.authenticate(PARTY_READ_ROLES)
        row = common.charge(charge_id)
        common.party_guard(db.cases[row["case_id"]])
        return response.ok(serialize.charge(row))

    @app.get(PREFIX + "/charges")
    def list_charges():
        middleware.authenticate(STAFF_ROLES)
        response.page_params()
        rows = db.ordered(list(db.charges.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("order_id", "order_id", "str"),
            ("status", "status", "str"),
            ("charge_type", "charge_type", "str"),
        ])
        return response.paginate(rows, serialize.charge)

    @app.post(PREFIX + "/charges/<charge_id>/voidance")
    def void_charge(charge_id):
        middleware.authenticate(["FinanceOfficer"])
        row = common.charge(charge_id)
        case = db.cases[row["case_id"]]
        common.case_writable(case)
        if row["status"] != "OPEN" and row["paid_cents"] == 0:
            raise ApiError("ERR_INVALID_CASE_STATUS",
                           "Only an OPEN charge may be voided.")
        # The manual path refuses a charge that has taken money.
        if row["paid_cents"] != 0:
            raise ApiError("ERR_CHARGE_PARTIALLY_PAID")
        cascade.void_charge(row, case, refund_paid=False)
        db.touch(case)
        return response.ok(serialize.charge(row))

    @app.post(PREFIX + "/cases/<case_id>/payments")
    def post_payment(case_id):
        middleware.authenticate(["FinanceOfficer"])
        case = common.case(case_id)
        payload = validate.body()
        source = validate.req_enum(payload, "source", PAYMENT_SOURCES)
        amount = validate.req_int(payload, "amount_cents")
        offer_id = validate.opt_ref(payload, "compromise_offer_id")
        if source == "REVERSAL":
            if amount == 0:
                validate.fail("amount_cents must not be zero.")
        elif amount <= 0:
            validate.fail("amount_cents must be strictly positive for source %s."
                          % source)
        offer = None
        if offer_id is not None:
            offer = common.ref_offer(offer_id)
            if offer["case_id"] != case["id"]:
                raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")

        common.case_writable(case)
        if source == "COMPROMISE_INSTALLMENT":
            if offer is None:
                validate.fail("compromise_offer_id is required for a "
                              "COMPROMISE_INSTALLMENT payment.")
            if offer["status"] not in ("ACCEPTED", "ACTIVE"):
                raise ApiError("ERR_INVALID_OFFER_STATUS")
            if amount < payments.required_installment_cents(offer):
                raise ApiError("ERR_PAYMENT_BELOW_INSTALLMENT")

        row = payments.post(case, source, amount, offer=offer)
        return response.created(serialize.payment(row))

    @app.get(PREFIX + "/payments/<payment_id>")
    def read_payment(payment_id):
        middleware.authenticate(PARTY_READ_ROLES)
        row = common.payment(payment_id)
        common.party_guard(db.cases[row["case_id"]])
        return response.ok(serialize.payment(row))

    @app.get(PREFIX + "/payments")
    def list_payments():
        middleware.authenticate(STAFF_ROLES)
        response.page_params()
        rows = db.ordered(list(db.payments.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("iwo_id", "iwo_id", "str"),
            ("compromise_offer_id", "compromise_offer_id", "str"),
            ("source", "source", "str"),
        ])
        return response.paginate(rows, serialize.payment)
