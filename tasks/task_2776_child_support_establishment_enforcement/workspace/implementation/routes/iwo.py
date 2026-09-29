"""Income withholding orders: issuance, service, amendment, remittance,
lapse and termination (PRD 3.4).
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
from services import cascade, payments, withholding

SERVICE_DAYS = 14
TERMINATION_REASONS = ("EMPLOYMENT_ENDED", "ORDER_VACATED", "ORDER_SUPERSEDED",
                       "SUPERSEDED_BY_NEW_IWO", "CASE_CLOSED")
MAX_MISSED_REMITTANCES = 2

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "ProgramAdmin", "EmployerAgent", "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "ProgramAdmin", "EmployerAgent"]


def register(app):
    @app.post(PREFIX + "/orders/<order_id>/withholding-orders")
    def issue_iwo(order_id):
        middleware.authenticate(["CaseWorker"])
        order = common.order(order_id)
        case = common.case_of_order(order)
        payload = validate.body()
        employer_id = validate.req_ref(payload, "employer_id")
        expected_version = validate.req_int(payload, "expected_order_version")
        reported = validate.opt_money(payload, "reported_disposable_income_cents")
        employer = common.ref_employer(employer_id)
        # Optimistic concurrency sits above every state check (PRD 2.9).
        if expected_version != order["version"]:
            raise ApiError("ERR_STALE_ORDER_VERSION")
        common.case_writable(case)
        if order["status"] != "ENTERED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")

        ncp = db.participants[case["noncustodial_party_id"]]
        computed = withholding.compute(order, case, ncp, employer, reported)
        row = db.stamp_new(dict({
            "order_id": order["id"],
            "employer_id": employer["id"],
            "service_status": "ISSUED",
            "remittance_status": "NOT_DUE",
            "jurisdiction_state_code": employer["state_code"],
            "served_at": None,
            "first_withholding_due_at": None,
            "next_remittance_due_at": None,
            "missed_remittance_count": 0,
            "terminated_reason": None,
        }, **computed))
        withholding.enforce_aggregate_cap(ncp["id"], row)
        if row["withholding_amount_cents"] == 0:
            raise ApiError("ERR_WITHHOLDING_CAP_EXHAUSTED")

        db.withholding_orders[row["id"]] = row
        db.touch(order)
        return response.created(serialize.iwo(row))

    @app.get(PREFIX + "/withholding-orders/<iwo_id>")
    def read_iwo(iwo_id):
        middleware.authenticate(READ_ROLES)
        row = common.iwo(iwo_id)
        middleware.require_employer_self(row["employer_id"])
        common.party_guard(common.case_of_iwo(row))
        return response.ok(serialize.iwo(row))

    @app.get(PREFIX + "/withholding-orders")
    def list_iwos():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.withholding_orders.values()))
        if middleware.user_role() == "EmployerAgent":
            rows = [r for r in rows if r["employer_id"] == middleware.user_id()]
        rows = common.apply_filters(rows, [
            ("order_id", "order_id", "str"),
            ("employer_id", "employer_id", "str"),
            ("service_status", "service_status", "str"),
            ("remittance_status", "remittance_status", "str"),
            ("jurisdiction_state_code", "jurisdiction_state_code", "str"),
        ])
        return response.paginate(rows, serialize.iwo)

    @app.post(PREFIX + "/withholding-orders/<iwo_id>/service")
    def serve_iwo(iwo_id):
        middleware.authenticate(["CaseWorker"])
        iwo = common.iwo(iwo_id)
        order = db.orders[iwo["order_id"]]
        case = common.case_of_iwo(iwo)
        common.case_writable(case)
        if iwo["service_status"] != "ISSUED":
            raise ApiError("ERR_INVALID_IWO_STATUS")
        if order["status"] != "ENTERED":
            raise ApiError("ERR_INVALID_ORDER_STATUS")
        if iwo["withholding_amount_cents"] <= 0:
            raise ApiError("ERR_WITHHOLDING_CAP_EXHAUSTED")

        served_at = db.now()
        first_due = util.add_days(served_at, SERVICE_DAYS)
        iwo["service_status"] = "SERVED"
        iwo["served_at"] = served_at
        iwo["first_withholding_due_at"] = first_due
        iwo["next_remittance_due_at"] = first_due
        db.touch(iwo)
        employer = db.employers[iwo["employer_id"]]
        employer["active_iwo_count"] += 1
        db.touch(employer)
        return response.ok(serialize.iwo(iwo))

    @app.post(PREFIX + "/withholding-orders/<iwo_id>/amendment")
    def amend_iwo(iwo_id):
        middleware.authenticate(["CaseWorker"])
        iwo = common.iwo(iwo_id)
        order = db.orders[iwo["order_id"]]
        case = common.case_of_iwo(iwo)
        payload = validate.body()
        reported = validate.req_money(payload, "reported_disposable_income_cents")
        common.case_writable(case)
        if iwo["service_status"] not in ("SERVED", "AMENDED"):
            raise ApiError("ERR_INVALID_IWO_STATUS")
        if reported == iwo["reported_disposable_income_cents"]:
            validate.fail("reported_disposable_income_cents must differ from the "
                          "stored figure.")

        ncp = db.participants[case["noncustodial_party_id"]]
        employer = db.employers[iwo["employer_id"]]
        computed = withholding.compute(order, case, ncp, employer, reported)
        candidate = dict(iwo)
        candidate.update(computed)
        withholding.enforce_aggregate_cap(ncp["id"], candidate)

        iwo.update(computed)
        iwo["service_status"] = "AMENDED"
        db.touch(iwo)
        return response.ok(serialize.iwo(iwo))

    @app.post(PREFIX + "/withholding-orders/<iwo_id>/remittances")
    def remit(iwo_id):
        middleware.authenticate(["EmployerAgent"])
        iwo = common.iwo(iwo_id)
        middleware.require_employer_self(iwo["employer_id"])
        case = common.case_of_iwo(iwo)
        payload = validate.body()
        amount = validate.req_money(payload, "amount_cents")
        common.case_writable(case)
        if iwo["service_status"] not in ("SERVED", "AMENDED"):
            raise ApiError("ERR_INVALID_IWO_STATUS")
        if iwo["remittance_status"] == "DEFAULTED":
            raise ApiError("ERR_IWO_DEFAULTED")

        iwo["remittance_status"] = "CURRENT"
        iwo["missed_remittance_count"] = 0
        if iwo["next_remittance_due_at"] is not None:
            iwo["next_remittance_due_at"] = util.add_months_dt(
                iwo["next_remittance_due_at"], 1)
        db.touch(iwo)
        row = payments.post(case, "INCOME_WITHHOLDING", amount, iwo_id=iwo["id"])
        return response.created(serialize.payment(row))

    @app.post(PREFIX + "/withholding-orders/<iwo_id>/lapse")
    def lapse(iwo_id):
        middleware.authenticate(["FinanceOfficer"])
        iwo = common.iwo(iwo_id)
        case = common.case_of_iwo(iwo)
        common.case_writable(case)
        if iwo["service_status"] == "TERMINATED" \
                or iwo["remittance_status"] == "DEFAULTED":
            raise ApiError("ERR_INVALID_IWO_STATUS")
        due = iwo["next_remittance_due_at"]
        if due is None or not (db.now() > due):
            raise ApiError("ERR_REMITTANCE_NOT_YET_DUE")

        iwo["missed_remittance_count"] += 1
        if iwo["remittance_status"] == "DELINQUENT" \
                and iwo["missed_remittance_count"] >= MAX_MISSED_REMITTANCES:
            iwo["remittance_status"] = "DEFAULTED"
        else:
            iwo["remittance_status"] = "DELINQUENT"
        db.touch(iwo)
        return response.ok(serialize.iwo(iwo))

    @app.post(PREFIX + "/withholding-orders/<iwo_id>/termination")
    def terminate(iwo_id):
        middleware.authenticate(["CaseWorker"])
        iwo = common.iwo(iwo_id)
        case = common.case_of_iwo(iwo)
        payload = validate.body()
        reason = validate.req_enum(payload, "terminated_reason", TERMINATION_REASONS)
        common.case_writable(case)
        if iwo["service_status"] not in ("ISSUED", "SERVED", "AMENDED"):
            raise ApiError("ERR_INVALID_IWO_STATUS")
        cascade.terminate_iwo(iwo, reason)
        return response.ok(serialize.iwo(iwo))
