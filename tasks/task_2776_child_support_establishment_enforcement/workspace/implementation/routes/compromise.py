"""Arrears compromise offers: construction, acceptance and default (PRD 3.9)."""
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
from services import cascade, interest, risk

INSTALLMENT_MIN = 3
INSTALLMENT_MAX = 36
ARREARS_MINIMUM_CENTS = 100000

# The first band whose ceiling is at least the pre-waiver total wins.
WAIVER_BANDS = [
    (500000, Decimal("0.25")),
    (2000000, Decimal("0.50")),
    (None, Decimal("0.75")),
]

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "ProgramAdmin", "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "ProgramAdmin"]


def waiver_tier_pct(pre_waiver_total_cents):
    for ceiling, rate in WAIVER_BANDS:
        if ceiling is None or pre_waiver_total_cents <= ceiling:
            return rate
    return WAIVER_BANDS[-1][1]


def _live_offer(case, exclude_id=None):
    for offer in db.case_offers(case["id"]):
        if offer["id"] == exclude_id:
            continue
        if offer["status"] in ("ACCEPTED", "ACTIVE"):
            return offer
    return None


def register(app):
    @app.post(PREFIX + "/cases/<case_id>/compromise-offers")
    def create_offer(case_id):
        middleware.authenticate(["FinanceOfficer"])
        case = common.case(case_id)
        payload = validate.body()
        installment_count = validate.req_int(payload, "installment_count",
                                            INSTALLMENT_MIN, INSTALLMENT_MAX)
        expected_version = validate.req_int(payload, "expected_case_version")
        # Optimistic concurrency sits above every state check (PRD 2.9).
        if expected_version != case["version"]:
            raise ApiError("ERR_STALE_CASE_VERSION")
        common.case_writable(case)
        if _live_offer(case) is not None:
            raise ApiError("ERR_ACTIVE_OFFER_EXISTS")
        if case["tanf_assistance"]:
            raise ApiError("ERR_ASSIGNED_ARREARS_NOT_COMPROMISABLE")
        ncp = db.participants[case["noncustodial_party_id"]]
        _e, _et, _c, compromise_tier = risk.scores(ncp)
        if compromise_tier == "HIGH":
            raise ApiError("ERR_COMPROMISE_RISK_TOO_HIGH")
        principal = interest.arrears_principal(case["id"])
        if principal < ARREARS_MINIMUM_CENTS:
            raise ApiError("ERR_ARREARS_BELOW_COMPROMISE_MINIMUM")

        as_of = db.now().date()
        interest_due = interest.aggregate_total(case["id"], as_of)
        pre_waiver = principal + interest_due
        tier = waiver_tier_pct(pre_waiver)
        waiver = util.mul_round_half_up(interest_due, tier)
        settlement = pre_waiver - waiver
        monthly = settlement // installment_count
        final = settlement - monthly * (installment_count - 1)

        # A newer offer displaces any PROPOSED predecessor on the case.
        for other in db.case_offers(case["id"]):
            if other["status"] == "PROPOSED":
                other["status"] = "SUPERSEDED"
                db.touch(other)

        row = db.stamp_new({
            "case_id": case["id"],
            "status": "PROPOSED",
            "principal_due_snapshot_cents": principal,
            "interest_due_snapshot_cents": interest_due,
            "pre_waiver_total_cents": pre_waiver,
            "waiver_tier_pct": tier,
            "interest_waiver_cents": waiver,
            "settlement_total_cents": settlement,
            "installment_count": installment_count,
            "monthly_installment_cents": monthly,
            "final_installment_cents": final,
            "accepted_at": None,
            "next_installment_due_date": None,
            "compliance_payment_count": 0,
            "defaulted_at": None,
            "completed_at": None,
        })
        db.compromise_offers[row["id"]] = row
        db.touch(case)
        return response.created(serialize.offer(row))

    @app.get(PREFIX + "/compromise-offers/<compromise_offer_id>")
    def read_offer(compromise_offer_id):
        middleware.authenticate(READ_ROLES)
        row = common.offer(compromise_offer_id)
        common.party_guard(db.cases[row["case_id"]])
        return response.ok(serialize.offer(row))

    @app.get(PREFIX + "/compromise-offers")
    def list_offers():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.compromise_offers.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("status", "status", "str"),
        ])
        return response.paginate(rows, serialize.offer)

    @app.post(PREFIX + "/compromise-offers/<compromise_offer_id>/acceptance")
    def accept(compromise_offer_id):
        middleware.authenticate(["NoncustodialParty"])
        offer = common.offer(compromise_offer_id)
        case = db.cases[offer["case_id"]]
        middleware.require_case_party(case)
        common.case_writable(case)
        # Displacement by a newer offer is the specific reason (PRD 2.9).
        if offer["status"] == "SUPERSEDED":
            raise ApiError("ERR_OFFER_SUPERSEDED")
        if offer["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_OFFER_STATUS")
        if _live_offer(case, exclude_id=offer["id"]) is not None:
            raise ApiError("ERR_ACTIVE_OFFER_EXISTS")
        if interest.arrears_principal(case["id"]) \
                != offer["principal_due_snapshot_cents"]:
            raise ApiError("ERR_OFFER_SNAPSHOT_STALE")

        accepted_at = db.now()
        offer["status"] = "ACCEPTED"
        offer["accepted_at"] = accepted_at
        offer["next_installment_due_date"] = util.add_months_date(
            accepted_at.date(), 1)
        db.touch(offer)
        case["interest_written_off_cents"] += offer["interest_waiver_cents"]
        for action in db.case_actions(case["id"]):
            if action["status"] == "ACTIVE":
                cascade.release_action(action, case, "COMPROMISE_ACCEPTED",
                                       restore_posture=False)
            elif action["status"] == "NOTICE_SENT":
                cascade.release_noticed_action(action, case,
                                               "COMPROMISE_ACCEPTED")
        # The stay is set after the releases so it is not settled back to NORMAL.
        case["enforcement_posture"] = "STAYED"
        db.touch(db.participants[case["noncustodial_party_id"]])
        db.touch(case)
        return response.ok(serialize.offer(offer))

    @app.post(PREFIX + "/compromise-offers/<compromise_offer_id>"
                       "/default-declaration")
    def declare_default(compromise_offer_id):
        middleware.authenticate(["FinanceOfficer"])
        offer = common.offer(compromise_offer_id)
        case = db.cases[offer["case_id"]]
        common.case_writable(case)
        if offer["status"] not in ("ACCEPTED", "ACTIVE"):
            raise ApiError("ERR_INVALID_OFFER_STATUS")
        due = offer["next_installment_due_date"]
        if due is None or not (db.now().date() > due):
            raise ApiError("ERR_INSTALLMENT_NOT_YET_LATE")

        offer["status"] = "DEFAULTED"
        offer["defaulted_at"] = db.now()
        db.touch(offer)
        # Only the waiver is reversed; installments already paid stay applied.
        case["interest_written_off_cents"] -= offer["interest_waiver_cents"]
        case["enforcement_posture"] = "ESCALATED"
        db.touch(case)
        return response.ok(serialize.offer(offer))
