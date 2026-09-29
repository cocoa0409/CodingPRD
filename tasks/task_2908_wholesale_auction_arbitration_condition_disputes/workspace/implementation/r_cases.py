"""Claim intake, the evidence file and arbitrator intake review (PRD 3.4, 3.5)."""
from flask import Blueprint

import calc
import services as S
import store as C
from authz import ALL_ROLES, authenticate
from envelope import arr, created, obj, unpaginated
from errors import fail
from store import store
from util import parse_dt, public, public_list
from validators import (json_body, opt_int, opt_str, q_enum, q_pagination, q_str,
                        req_enum, req_int, req_str)

bp = Blueprint("cases", __name__)


def _announced(sale_id, defect_class):
    if defect_class == "TITLE_MISSING":
        return False
    for row in store.announcements.values():
        if row["sale_id"] == sale_id and row["defect_class"] == defect_class:
            return True
    return False


def _duplicate_open_claim(sale_id, defect_class):
    for row in store.cases.values():
        if (row["sale_id"] == sale_id and row["defect_class"] == defect_class
                and row["status"] in C.NON_TERMINAL_CASE_STATUSES):
            return True
    return False


@bp.route("/arbitration/cases", methods=["POST"])
def file_claim():
    role, user_id = authenticate(["BuyerRep"])
    body = json_body()
    sale_id = req_str(body, "sale_id")
    defect_class = req_enum(body, "defect_class", C.DEFECT_CLASSES)
    claim_amount_cents = req_int(body, "claim_amount_cents", 0)
    odometer_at_claim = req_int(body, "odometer_at_claim", 0)
    complaint_text = req_str(body, "complaint_text", 1, 1000)
    superseded_case_id = opt_str(body, "superseded_case_id")

    sale = S.get_sale(sale_id)
    policy = S.policy_for_defect_class(defect_class)
    if policy is None:
        fail("ERR_POLICY_NOT_FOUND")
    if superseded_case_id is not None:
        prior = S.get_case(superseded_case_id)
        if (prior["sale_id"] != sale["id"] or prior["defect_class"] != defect_class
                or prior["status"] not in ("WITHDRAWN", "EXPIRED")):
            fail("ERR_INVALID_REQUEST",
                 "Field 'superseded_case_id' must name a withdrawn or expired case on the "
                 "same sale for the same defect class.")
    if sale["buyer_id"] != user_id:
        fail("ERR_NOT_SALE_BUYER")
    buyer = S.get_buyer(sale["buyer_id"])
    seller = S.get_seller(sale["seller_id"])
    if buyer["claim_privilege_status"] == "SUSPENDED":
        fail("ERR_BUYER_PRIVILEGE_SUSPENDED")
    if _announced(sale["id"], defect_class):
        fail("ERR_DEFECT_ANNOUNCED")

    inspection = S.governing_inspection(sale["id"])
    matched = inspection is not None and defect_class in inspection["findings"]
    if inspection is not None and not matched and policy["psi_clean_waives_rights"]:
        fail("ERR_PSI_WAIVED_RIGHTS")
    psi_extension = int(policy["psi_extension_hours"]) if matched else 0

    now = store.now()
    hours_elapsed = calc.hours_between(now, parse_dt(sale["hammer_time_utc"]))
    miles_driven = odometer_at_claim - int(sale["announced_odometer_miles"])
    window = calc.window_evaluation(policy, hours_elapsed, miles_driven, psi_extension)
    if not window["time_ok"]:
        fail("ERR_ARBITRATION_WINDOW_EXPIRED")
    if not window["mileage_ok"]:
        fail("ERR_MILEAGE_LIMIT_EXCEEDED")
    if _duplicate_open_claim(sale["id"], defect_class):
        fail("ERR_DUPLICATE_OPEN_CLAIM")
    if claim_amount_cents < int(policy["min_claim_amount_cents"]):
        fail("ERR_CLAIM_BELOW_MINIMUM")

    row = {
        "sale_id": sale["id"],
        "claimant_buyer_id": sale["buyer_id"],
        "policy_id": policy["id"],
        "policy_version_at_intake": int(policy["version"]),
        "superseded_case_id": superseded_case_id,
        "defect_class": defect_class,
        "claim_amount_cents": claim_amount_cents,
        "odometer_at_claim": odometer_at_claim,
        "complaint_text": complaint_text,
        "claimed_at_utc": store.now_iso(),
        "hours_elapsed_at_claim": float(hours_elapsed),
        "miles_driven_at_claim": miles_driven,
        "psi_extension_applied_hours": psi_extension,
        "effective_window_hours": window["effective_window_hours"],
        "window_eligible": window["window_eligible"],
        "status": "SUBMITTED",
        "review_opened_at_utc": None,
        "intake_arbitrator_user_id": None,
        "seller_conceded": False,
        "seller_response_timed_out": False,
        "fault_party": "NONE",
        "current_round_index": 0,
        "latest_verified_estimate_cents": 0,
        "verified_true_mileage": None,
    }
    store.insert("cases", row, mutable=True)
    S.open_claim_increment(sale, buyer, seller)
    return created(public(row))


@bp.route("/arbitration/cases/<case_id>", methods=["GET"])
def read_case(case_id):
    authenticate(ALL_ROLES)
    return obj(public(S.get_case(case_id)))


@bp.route("/arbitration/cases", methods=["GET"])
def list_cases():
    authenticate(ALL_ROLES)
    limit, offset = q_pagination()
    filters = [("sale_id", q_str("sale_id")), ("claimant_buyer_id", q_str("claimant_buyer_id")),
               ("policy_id", q_str("policy_id")),
               ("superseded_case_id", q_str("superseded_case_id")),
               ("status", q_enum("status", C.CASE_STATUSES))]
    rows = store.rows("cases")
    for field, value in filters:
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    total = len(rows)
    page = rows[offset:offset + limit]
    return arr(public_list(page), limit, offset, total)


@bp.route("/arbitration/cases/<case_id>/evidence", methods=["POST"])
def file_evidence(case_id):
    role, user_id = authenticate(["BuyerRep", "Inspector"])
    body = json_body()
    evidence_type = req_enum(body, "evidence_type", C.EVIDENCE_TYPES)
    provider_name = req_str(body, "provider_name", 1, 120)
    document_reference = req_str(body, "document_reference", 1, 120)
    repair_estimate_cents = opt_int(body, "repair_estimate_cents", 0)
    odometer_reading = opt_int(body, "odometer_reading", 0)
    case = S.get_case(case_id)
    if role == "BuyerRep" and case["claimant_buyer_id"] != user_id:
        fail("ERR_NOT_CASE_OWNER")
    if case["status"] not in C.NON_TERMINAL_CASE_STATUSES:
        fail("ERR_INVALID_CASE_STATE")
    S.touch(case)
    row = {
        "case_id": case["id"],
        "evidence_type": evidence_type,
        "provider_name": provider_name,
        "document_reference": document_reference,
        "repair_estimate_cents": repair_estimate_cents,
        "odometer_reading": odometer_reading,
        "submitted_by_role": role,
        "submitted_by_user_id": user_id,
        "verified": evidence_type in C.VERIFIED_EVIDENCE_TYPES,
        "recorded_at_utc": store.now_iso(),
        "case_version_after": int(case["version"]),
    }
    store.insert("evidence", row, mutable=False)
    S.refresh_case_evidence_readings(case)
    return created(public(row))


@bp.route("/arbitration/cases/<case_id>/evidence", methods=["GET"])
def list_evidence(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("evidence", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/open-review", methods=["POST"])
def open_review(case_id):
    role, user_id = authenticate(["Arbitrator"])
    case = S.get_case(case_id)
    if case["status"] != "SUBMITTED":
        fail("ERR_INVALID_CASE_STATE")
    policy = S.get_policy(case["policy_id"])
    rows = S.children("evidence", "case_id", case["id"])
    types = [r["evidence_type"] for r in rows]
    if case["defect_class"] in C.TITLE_DEFECT_CLASSES:
        if "TITLE_DOCUMENT" not in types:
            fail("ERR_TITLE_CLAIM_REQUIRES_TITLE_EVIDENCE")
    elif "INSPECTION_REPORT" not in types:
        fail("ERR_MISSING_INSPECTION_REPORT")
    if policy["requires_third_party_verification"]:
        verified = [r for r in rows
                    if r["evidence_type"] == "THIRD_PARTY_VERIFICATION" and r["verified"]]
        if not verified:
            fail("ERR_THIRD_PARTY_VERIFICATION_REQUIRED")
    case["status"] = "UNDER_REVIEW"
    case["review_opened_at_utc"] = store.now_iso()
    case["intake_arbitrator_user_id"] = user_id
    S.touch(case)
    return obj(public(case))
