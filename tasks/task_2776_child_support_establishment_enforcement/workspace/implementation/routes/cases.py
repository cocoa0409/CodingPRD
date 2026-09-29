"""Case intake, locate referrals, ledger reads, accrual runs, closure."""
import common
import db
import middleware
import response
import serialize
import util
import validate
from common import PREFIX
from errors import ApiError
from services import cascade, interest

CASE_TYPES = ("PA_REFERRAL", "DIRECT_APPLICATION")
LOCATE_SOURCES = ("FEDERAL_PLS", "STATE_DIRECTORY_OF_NEW_HIRES",
                  "CREDIT_BUREAU", "EMPLOYER_TIP")
CLOSED_REASONS = ("ARREARS_SATISFIED", "NO_JURISDICTION", "CP_REQUEST",
                  "CHILD_EMANCIPATED")
MAX_LOCATE_ATTEMPTS = 3

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin", "CustodialParty",
              "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin"]
LEDGER_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer", "ProgramAdmin"]


def register(app):
    @app.post(PREFIX + "/cases")
    def create_case():
        middleware.authenticate(["CaseWorker"])
        payload = validate.body()
        case_type = validate.req_enum(payload, "case_type", CASE_TYPES)
        cp_id = validate.req_ref(payload, "custodial_party_id")
        ncp_id = validate.req_ref(payload, "noncustodial_party_id")
        child_count = validate.req_int(payload, "child_count", 1, 6)
        tanf = validate.req_bool(payload, "tanf_assistance")
        good_cause = validate.opt_bool(payload, "good_cause_claim", False)

        cp = common.ref_participant(cp_id)
        ncp = common.ref_participant(ncp_id)
        if cp["role_type"] != "CUSTODIAL_PARTY" \
                or ncp["role_type"] != "NONCUSTODIAL_PARTY" \
                or cp["id"] == ncp["id"]:
            raise ApiError("ERR_PARTY_ROLE_MISMATCH")
        if (case_type == "PA_REFERRAL" and not tanf) or \
                (case_type == "DIRECT_APPLICATION" and tanf):
            raise ApiError("ERR_TANF_FLAG_MISMATCH")

        row = db.stamp_new({
            "case_type": case_type,
            "custodial_party_id": cp["id"],
            "noncustodial_party_id": ncp["id"],
            "child_count": child_count,
            "tanf_assistance": tanf,
            "good_cause_claim": good_cause,
            "case_status": "OPENED",
            "enforcement_posture": "NORMAL",
            "interstate_role": "NONE",
            "locate_referral_count": 0,
            "total_charged_principal_cents": 0,
            "total_collected_principal_cents": 0,
            "interest_collected_cents": 0,
            "interest_written_off_cents": 0,
            "unapplied_credit_cents": 0,
            "closed_reason": None,
            "closed_at": None,
        })
        db.cases[row["id"]] = row
        # open_case_count is recomputed for both parties on read.
        return response.created(serialize.case(row))

    @app.get(PREFIX + "/cases/<case_id>")
    def read_case(case_id):
        middleware.authenticate(READ_ROLES)
        row = common.case(case_id)
        middleware.require_case_party(row)
        return response.ok(serialize.case(row))

    @app.get(PREFIX + "/cases")
    def list_cases():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.cases.values()))
        rows = common.apply_filters(rows, [
            ("custodial_party_id", "custodial_party_id", "str"),
            ("noncustodial_party_id", "noncustodial_party_id", "str"),
            ("case_status", "case_status", "str"),
            ("enforcement_posture", "enforcement_posture", "str"),
            ("interstate_role", "interstate_role", "str"),
            ("tanf_assistance", "tanf_assistance", "bool"),
        ])
        return response.paginate(rows, serialize.case)

    @app.post(PREFIX + "/cases/<case_id>/locate-referrals")
    def create_locate_referral(case_id):
        middleware.authenticate(["CaseWorker"])
        case = common.case(case_id)
        payload = validate.body()
        validate.req_enum(payload, "locate_source", LOCATE_SOURCES)
        common.case_writable(case)
        if case["case_status"] not in ("OPENED", "LOCATE"):
            raise ApiError("ERR_INVALID_CASE_STATUS")
        if case["good_cause_claim"]:
            raise ApiError("ERR_GOOD_CAUSE_BARS_DISCLOSURE")

        ncp = db.participants[case["noncustodial_party_id"]]
        if case["case_status"] == "OPENED":
            if ncp["locate_status"] not in ("NOT_NEEDED", "PENDING"):
                raise ApiError("ERR_LOCATE_ATTEMPTS_EXHAUSTED")
        else:
            if ncp["locate_status"] != "PENDING" \
                    or ncp["locate_attempt_count"] >= MAX_LOCATE_ATTEMPTS:
                raise ApiError("ERR_LOCATE_ATTEMPTS_EXHAUSTED")

        case["case_status"] = "LOCATE"
        case["locate_referral_count"] += 1
        db.touch(case)
        ncp["locate_attempt_count"] += 1
        if ncp["locate_attempt_count"] >= MAX_LOCATE_ATTEMPTS:
            ncp["locate_status"] = "UNLOCATABLE"
        else:
            ncp["locate_status"] = "PENDING"
        db.touch(ncp)
        return response.ok(serialize.case(case))

    @app.post(PREFIX + "/cases/<case_id>/closure")
    def close_case(case_id):
        middleware.authenticate(["SupervisingAttorney"])
        case = common.case(case_id)
        payload = validate.body()
        reason = validate.req_enum(payload, "closed_reason", CLOSED_REASONS)
        common.case_writable(case)
        status = case["case_status"]
        if status == "LOCATE":
            ncp = db.participants[case["noncustodial_party_id"]]
            if ncp["locate_status"] != "UNLOCATABLE" or reason != "NO_JURISDICTION":
                raise ApiError("ERR_INVALID_CASE_STATUS")
        elif status == "ENFORCEMENT":
            if any(a["status"] == "ACTIVE" for a in db.case_actions(case["id"])):
                raise ApiError("ERR_INVALID_CASE_STATUS")
            if any(o["status"] in ("ACCEPTED", "ACTIVE")
                   for o in db.case_offers(case["id"])):
                raise ApiError("ERR_INVALID_CASE_STATUS")
        elif status == "ORDER_ESTABLISHMENT":
            if reason not in ("CP_REQUEST", "CHILD_EMANCIPATED") \
                    or case["tanf_assistance"]:
                raise ApiError("ERR_INVALID_CASE_STATUS")
        else:
            raise ApiError("ERR_INVALID_CASE_STATUS")

        if reason == "ARREARS_SATISFIED":
            if interest.arrears_principal(case["id"]) != 0 \
                    or interest.interest_receivable(case) != 0:
                raise ApiError("ERR_ARREARS_OUTSTANDING")

        for action in db.case_actions(case["id"]):
            if action["status"] == "ACTIVE":
                cascade.release_action(action, case, "ARREARS_SATISFIED")
        cascade.close_case(case, reason)
        return response.ok(serialize.case(case))

    @app.get(PREFIX + "/cases/<case_id>/ledger")
    def read_ledger(case_id):
        middleware.authenticate(LEDGER_ROLES)
        case = common.case(case_id)
        raw = common.qp("as_of_date")
        if raw is None:
            as_of = db.now().date()
        else:
            as_of = util.parse_day(raw)
            if as_of is None:
                raise ApiError("ERR_VALIDATION",
                               "as_of_date must be a well-formed ISO 8601 date.")
        principal = interest.arrears_principal(case["id"])
        assigned = principal if case["tanf_assistance"] else 0
        aggregate = interest.aggregate_total(case["id"], as_of)
        receivable = max(0, aggregate - case["interest_written_off_cents"]
                         - case["interest_collected_cents"])
        payments = db.case_payments(case["id"])
        data = {
            "case_id": case["id"],
            "as_of_date": util.iso_date(as_of),
            "statutory_interest_cents": interest.statutory_total(case["id"], as_of),
            "aggregate_interest_cents": aggregate,
            "interest_written_off_cents": case["interest_written_off_cents"],
            "interest_collected_cents": case["interest_collected_cents"],
            "interest_receivable_cents": receivable,
            "arrears_principal_cents": principal,
            "assigned_arrears_cents": assigned,
            "unassigned_arrears_cents": principal - assigned,
            "unapplied_credit_cents": case["unapplied_credit_cents"],
            "applied_current_cents": sum(p["applied_current_cents"] for p in payments),
            "applied_medical_cents": sum(p["applied_medical_cents"] for p in payments),
            "applied_arrears_cents": sum(p["applied_arrears_cents"] for p in payments),
            "applied_interest_cents": sum(p["applied_interest_cents"] for p in payments),
            "applied_genetic_cost_cents": sum(
                p["applied_genetic_cost_cents"] for p in payments),
            "total_charged_principal_cents": case["total_charged_principal_cents"],
            "total_collected_principal_cents": case["total_collected_principal_cents"],
        }
        return response.ok(data)

    @app.post(PREFIX + "/cases/<case_id>/accrual-runs")
    def run_accrual(case_id):
        middleware.authenticate(["FinanceOfficer"])
        case = common.case(case_id)
        common.case_writable(case)
        as_of = db.now().date()
        for charge in db.case_charges(case["id"]):
            if charge["status"] != "OPEN":
                continue
            charge["interest_accrued_cents"] = interest.charge_statutory_interest(
                charge, as_of)
        db.touch(case)
        return response.ok(serialize.case(case))
