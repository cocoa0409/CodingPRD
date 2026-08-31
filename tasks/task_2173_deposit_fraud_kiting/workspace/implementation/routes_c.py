"""Account takeover, kiting scan, fraud cases, BSA referrals, charge-offs, clock."""
from flask import Blueprint, g

import calc
import serial
from core import (
    API_PREFIX,
    bad,
    base_row,
    body,
    db,
    endpoint,
    fail,
    get_account,
    get_bsa_referral,
    get_charge_off,
    get_fraud_case,
    now,
    ok,
    ok_list,
    opt_bool,
    opt_int,
    opt_str,
    pagination,
    paginate,
    parse_iso,
    query_enum,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_present_str,
    req_str,
    sort_rows,
    touch,
)

bp = Blueprint("c", __name__)

INDICATOR_CODES = set(calc.INDICATOR_WEIGHTS.keys())
CASE_TYPES = {"KITING", "MULE"}
CASE_STATUSES = {"OPENED", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED", "CLOSED"}
REFERRAL_STATUSES = {"DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED"}
ACTIVITY_CODES = {"KITING", "MULE_ACTIVITY", "STRUCTURING", "ACCOUNT_TAKEOVER"}
CHARGE_OFF_STATUSES = {
    "PROPOSED",
    "APPROVED",
    "BOOKED",
    "REFERRED_TO_RECOVERY",
    "RECOVERED_PARTIAL",
    "RECOVERED_FULL",
    "REVERSED",
    "SUPERSEDED",
}
LIVE_CASE_STATUSES = ("OPENED", "INVESTIGATING", "SUBSTANTIATED")
POSTURE_RANK = {"NORMAL": 0, "STEP_UP_REQUIRED": 1, "LOCKED": 2}


# --------------------------------------------------------------------------
# Account takeover
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts/<aid>/access-review")
@endpoint(["FraudAnalyst", "FraudSupervisor"])
def access_review(aid):
    acct = get_account(aid)
    data = body()
    if "indicator_codes" not in data or data["indicator_codes"] is None:
        bad("Missing required field indicator_codes.")
    codes = data["indicator_codes"]
    if not isinstance(codes, list):
        bad("indicator_codes must be an array.")
    for c in codes:
        if not isinstance(c, str) or c not in INDICATOR_CODES:
            bad("indicator_codes members must be declared indicator codes.")
    reset_posture = opt_bool(data, "reset_posture", False)

    merged = set(acct["ato_indicator_codes"]) | set(codes)
    acct["ato_indicator_codes"] = sorted(merged)
    acct["ato_score"] = calc.ato_score_for(acct["ato_indicator_codes"])

    if reset_posture and g.user_role == "FraudSupervisor" and acct["access_posture"] == "LOCKED":
        # A supervisor reset wins over everything, including the recomputed score.
        acct["access_posture"] = "STEP_UP_REQUIRED"
        acct["step_up_failure_count"] = 0
    else:
        if acct["ato_score"] >= calc.ATO_LOCK_MIN:
            target = "LOCKED"
        elif acct["ato_score"] >= calc.ATO_STEP_UP_MIN:
            target = "STEP_UP_REQUIRED"
        else:
            target = acct["access_posture"]
        # The score ladder never de-escalates a posture on its own.
        if POSTURE_RANK[target] > POSTURE_RANK[acct["access_posture"]]:
            acct["access_posture"] = target

    calc.refresh_risk(acct)
    touch(acct)
    return ok(serial.account(acct))


@bp.post(API_PREFIX + "/accounts/<aid>/step-up-response")
@endpoint(["AccountHolder"])
def step_up_response(aid):
    acct = get_account(aid)
    data = body()
    answer = req_present_str(data, "challenge_answer")

    if g.user_id != acct["customer_id"]:
        fail("ERR_NOT_ACCOUNT_OWNER", "Caller does not own this account.")
    if acct["access_posture"] == "LOCKED":
        fail("ERR_ACCOUNT_ACCESS_LOCKED", "The account's access posture is LOCKED.")
    if acct["access_posture"] != "STEP_UP_REQUIRED":
        fail("ERR_STEP_UP_NOT_REQUIRED", "No step-up challenge is outstanding.")

    customer = db.customers.get(acct["customer_id"])
    correct = customer is not None and answer == customer["tin_last4"]
    if correct:
        acct["access_posture"] = "NORMAL"
        acct["step_up_failure_count"] = 0
        acct["ato_indicator_codes"] = []
        acct["ato_score"] = 0
    else:
        acct["step_up_failure_count"] += 1
        if acct["step_up_failure_count"] >= calc.STEP_UP_MAX_FAILURES:
            acct["access_posture"] = "LOCKED"
    touch(acct)
    return ok(serial.account(acct))


# --------------------------------------------------------------------------
# Kiting scan
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts/<aid>/kiting-scan")
@endpoint(["FraudAnalyst"])
def kiting_scan(aid):
    acct = get_account(aid)
    data = body()
    mode = req_enum(data, "mode", {"STRICT", "INCLUSIVE"})
    window_start = req_dt(data, "window_start_at")
    window_end = req_dt(data, "window_end_at")

    if acct["lifecycle_status"] not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_ACCOUNT_NOT_ACTIVE", "Kiting scans require an ACTIVE or RESTRICTED account.")

    result = calc.kiting_scan(aid, mode, window_start, window_end)
    result["fraud_case_id"] = None

    if result["detected"]:
        for case in db.fraud_cases.values():
            if (
                case["primary_account_id"] == aid
                and case["case_type"] == "KITING"
                and case["status"] in LIVE_CASE_STATUSES
            ):
                fail("ERR_DUPLICATE_OPEN_CASE", "A live KITING case already exists on this account.")

        case = base_row()
        case.update(
            {
                "primary_account_id": aid,
                "case_type": "KITING",
                "status": "OPENED",
                "detection_source": "KITING_SCAN",
                "kiting_score": result["kiting_score"],
                "scan_mode": mode,
                "cycle_account_ids": list(result["cycle_account_ids"]),
                "exposure_at_risk_cents": 0,
                "disposition_note": None,
                "reopen_count": 0,
                "closed_at": None,
            }
        )
        db.fraud_cases[case["id"]] = case
        case["exposure_at_risk_cents"] = calc.compute_case_exposure(case)
        result["fraud_case_id"] = case["id"]

        if acct["lifecycle_status"] == "ACTIVE":
            acct["lifecycle_status"] = "RESTRICTED"
            touch(acct)

    return ok(result)


# --------------------------------------------------------------------------
# Fraud cases
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/fraud-cases")
@endpoint(["FraudAnalyst"])
def create_fraud_case():
    data = body()
    primary_account_id = req_id(data, "primary_account_id")
    case_type = req_enum(data, "case_type", CASE_TYPES)
    acct = get_account(primary_account_id)

    for case in db.fraud_cases.values():
        if (
            case["primary_account_id"] == primary_account_id
            and case["case_type"] == case_type
            and case["status"] in LIVE_CASE_STATUSES
        ):
            fail("ERR_DUPLICATE_OPEN_CASE", "A live case of this type already exists.")

    if acct["lifecycle_status"] not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_ACCOUNT_NOT_ACTIVE", "Cases require an ACTIVE or RESTRICTED account.")

    case = base_row()
    case.update(
        {
            "primary_account_id": primary_account_id,
            "case_type": case_type,
            "status": "OPENED",
            "detection_source": "ANALYST_MANUAL",
            "kiting_score": None,
            "scan_mode": None,
            "cycle_account_ids": [],
            "exposure_at_risk_cents": 0,
            "disposition_note": None,
            "reopen_count": 0,
            "closed_at": None,
        }
    )
    db.fraud_cases[case["id"]] = case
    case["exposure_at_risk_cents"] = calc.compute_case_exposure(case)

    if acct["lifecycle_status"] == "ACTIVE":
        acct["lifecycle_status"] = "RESTRICTED"
        touch(acct)

    return ok(serial.fraud_case(case), 201)


@bp.get(API_PREFIX + "/fraud-cases/<cid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer", "LegalCounsel"])
def read_fraud_case(cid):
    return ok(serial.fraud_case(get_fraud_case(cid)))


@bp.get(API_PREFIX + "/accounts/<aid>/fraud-cases")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer"])
def list_account_fraud_cases(aid):
    get_account(aid)
    limit, offset = pagination()
    status = query_enum("status", CASE_STATUSES)
    case_type = query_enum("case_type", CASE_TYPES)
    rows = [c for c in db.fraud_cases.values() if c["primary_account_id"] == aid]
    if status:
        rows = [c for c in rows if c["status"] == status]
    if case_type:
        rows = [c for c in rows if c["case_type"] == case_type]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.fraud_case)
    return ok_list(items, limit, offset, total)


@bp.post(API_PREFIX + "/fraud-cases/<cid>/advance")
@endpoint(["FraudAnalyst"])
def advance_fraud_case(cid):
    case = get_fraud_case(cid)
    if case["status"] != "OPENED":
        fail("ERR_CASE_INVALID_STATE", "Advance requires status OPENED.")
    case["status"] = "INVESTIGATING"
    case["exposure_at_risk_cents"] = calc.compute_case_exposure(case)
    touch(case)
    return ok(serial.fraud_case(case))


def _other_live_case(case):
    for other in db.fraud_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["primary_account_id"] != case["primary_account_id"]:
            continue
        if other["status"] in LIVE_CASE_STATUSES:
            return True
    return False


@bp.post(API_PREFIX + "/fraud-cases/<cid>/disposition")
@endpoint(["FraudSupervisor"])
def dispose_fraud_case(cid):
    case = get_fraud_case(cid)
    data = body()
    decision = req_enum(data, "decision", {"SUBSTANTIATE", "UNSUBSTANTIATE", "REOPEN"})
    note = opt_str(data, "disposition_note")

    if decision in ("SUBSTANTIATE", "UNSUBSTANTIATE"):
        if case["status"] != "INVESTIGATING":
            fail("ERR_CASE_INVALID_STATE", "This disposition requires status INVESTIGATING.")
    else:
        if case["status"] != "UNSUBSTANTIATED":
            fail("ERR_CASE_INVALID_STATE", "REOPEN requires status UNSUBSTANTIATED.")

    acct = db.accounts.get(case["primary_account_id"])
    clock = now()

    if decision == "SUBSTANTIATE":
        case["status"] = "SUBSTANTIATED"
        case["disposition_note"] = note
        touch(case)
        if acct is not None:
            snap = calc.snapshot_account(acct)
            acct["lifecycle_status"] = "RESTRICTED"
            if case["case_type"] == "MULE":
                acct["closure_scheduled_at"] = clock + calc.days(calc.MULE_CLOSURE_NOTICE_DAYS)
                acct["closure_reason"] = "MULE_SUBSTANTIATED"
            calc.bump_if_dirty(acct, snap)
            if case["case_type"] == "MULE":
                for hold in calc.active_holds_for_account(acct["id"]):
                    hold["hold_type"] = "EXCEPTION_FRAUD"
                    hold["hold_release_at"] = acct["closure_scheduled_at"]
                    touch(hold)
                    calc.supersede_reviews_for_hold(hold["id"])
    elif decision == "UNSUBSTANTIATE":
        case["status"] = "UNSUBSTANTIATED"
        case["disposition_note"] = note
        touch(case)
        if acct is not None and acct["lifecycle_status"] == "RESTRICTED" and not _other_live_case(case):
            snap = calc.snapshot_account(acct)
            acct["lifecycle_status"] = "ACTIVE"
            acct["closure_scheduled_at"] = None
            acct["closure_reason"] = None
            calc.bump_if_dirty(acct, snap)
    else:
        case["status"] = "INVESTIGATING"
        case["reopen_count"] += 1
        touch(case)
        if acct is not None and acct["lifecycle_status"] == "ACTIVE":
            acct["lifecycle_status"] = "RESTRICTED"
            touch(acct)

    return ok(serial.fraud_case(case))


@bp.post(API_PREFIX + "/fraud-cases/<cid>/close")
@endpoint(["FraudSupervisor"])
def close_fraud_case(cid):
    case = get_fraud_case(cid)
    if case["status"] not in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        fail("ERR_CASE_INVALID_STATE", "Close requires SUBSTANTIATED or UNSUBSTANTIATED.")

    acct = db.accounts.get(case["primary_account_id"])
    customer_id = acct["customer_id"] if acct else None
    if customer_id and calc.preservation_hold_active(customer_id):
        fail("ERR_PRESERVATION_HOLD_ACTIVE", "A record-preservation hold is active for this customer.")

    was_substantiated = case["status"] == "SUBSTANTIATED"
    if was_substantiated:
        accepted = any(
            r["fraud_case_id"] == cid and r["status"] == "ACCEPTED"
            for r in db.bsa_referrals.values()
        )
        if not accepted:
            fail("ERR_BSA_REFERRAL_REQUIRED", "An ACCEPTED BSA referral is required.")

    case["status"] = "CLOSED"
    case["closed_at"] = now()
    touch(case)

    if was_substantiated and acct is not None and acct["lifecycle_status"] == "RESTRICTED":
        snap = calc.snapshot_account(acct)
        acct["lifecycle_status"] = "CLOSED"
        acct["closure_reason"] = (
            "MULE_SUBSTANTIATED" if case["case_type"] == "MULE" else "KITING_SUBSTANTIATED"
        )
        calc.bump_if_dirty(acct, snap)

    return ok(serial.fraud_case(case))


# --------------------------------------------------------------------------
# BSA referrals
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/fraud-cases/<cid>/bsa-referrals")
@endpoint(["FraudAnalyst"])
def draft_bsa_referral(cid):
    case = get_fraud_case(cid)
    data = body()
    narrative = req_str(data, "narrative", 1, 2000)
    activity = req_enum(data, "suspected_activity_code", ACTIVITY_CODES)

    if case["status"] != "SUBSTANTIATED":
        fail("ERR_CASE_NOT_SUBSTANTIATED", "Referrals require a SUBSTANTIATED case.")

    row = base_row()
    row.update(
        {
            "fraud_case_id": cid,
            "narrative": narrative,
            "suspected_activity_code": activity,
            "aggregate_amount_cents": 0,
            "status": "DRAFT",
            "drafted_by_user_id": g.user_id,
            "adjudicated_by_user_id": None,
            "return_reason": None,
            "revision_count": 0,
            "submitted_at": None,
            "adjudicated_at": None,
        }
    )
    db.bsa_referrals[row["id"]] = row
    return ok(serial.bsa_referral(row), 201)


@bp.get(API_PREFIX + "/fraud-cases/<cid>/bsa-referrals")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer"])
def list_case_bsa_referrals(cid):
    get_fraud_case(cid)
    limit, offset = pagination()
    status = query_enum("status", REFERRAL_STATUSES)
    rows = [r for r in db.bsa_referrals.values() if r["fraud_case_id"] == cid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.bsa_referral)
    return ok_list(items, limit, offset, total)


@bp.post(API_PREFIX + "/bsa-referrals/<rid>/submit")
@endpoint(["FraudAnalyst"])
def submit_bsa_referral(rid):
    referral = get_bsa_referral(rid)
    case = db.fraud_cases.get(referral["fraud_case_id"])
    if case is None or case["status"] != "SUBSTANTIATED":
        fail("ERR_CASE_NOT_SUBSTANTIATED", "The parent case is not SUBSTANTIATED.")
    if referral["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_REFERRAL_INVALID_STATE", "Submit requires DRAFT or RETURNED.")

    was_returned = referral["status"] == "RETURNED"
    referral["status"] = "SUBMITTED"
    referral["submitted_at"] = now()
    if was_returned:
        referral["revision_count"] += 1
    referral["aggregate_amount_cents"] = calc.bsa_aggregate_amount(case)
    touch(referral)
    return ok(serial.bsa_referral(referral))


@bp.post(API_PREFIX + "/bsa-referrals/<rid>/adjudicate")
@endpoint(["BsaOfficer"])
def adjudicate_bsa_referral(rid):
    referral = get_bsa_referral(rid)
    data = body()
    decision = req_enum(data, "decision", {"ACCEPT", "RETURN"})
    return_reason = opt_str(data, "return_reason")
    if decision == "RETURN" and return_reason is None:
        bad("return_reason is required when decision is RETURN.")

    if referral["status"] != "SUBMITTED":
        fail("ERR_REFERRAL_INVALID_STATE", "Adjudication requires status SUBMITTED.")

    if decision == "ACCEPT":
        referral["status"] = "ACCEPTED"
    else:
        referral["status"] = "RETURNED"
        referral["return_reason"] = return_reason
    referral["adjudicated_by_user_id"] = g.user_id
    referral["adjudicated_at"] = now()
    touch(referral)
    return ok(serial.bsa_referral(referral))


# --------------------------------------------------------------------------
# Charge-offs
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts/<aid>/charge-offs")
@endpoint(["FraudAnalyst"])
def create_charge_off(aid):
    acct = get_account(aid)
    data = body()
    gross = req_int(data, "gross_loss_cents", 1, None)
    offset_cents = opt_int(data, "collateral_offset_cents", 0, None, 0)
    expected_version = req_int(data, "expected_account_version", None, None)

    if expected_version != acct["version"]:
        fail("ERR_STALE_ACCOUNT_VERSION", "The account has been modified since it was read.")

    base_net = gross - offset_cents
    if base_net <= 0:
        fail("ERR_NO_NET_LOSS", "gross_loss_cents must exceed collateral_offset_cents.")

    fee_rate = calc.fee_rate_for(base_net)
    from core import bps as _bps

    fee = _bps(base_net, fee_rate)
    net = base_net + fee

    for other in db.charge_offs.values():
        if other["account_id"] == aid and other["status"] == "PROPOSED":
            other["status"] = "SUPERSEDED"
            touch(other)

    row = base_row()
    row.update(
        {
            "account_id": aid,
            "gross_loss_cents": gross,
            "collateral_offset_cents": offset_cents,
            "base_net_cents": base_net,
            "recovery_fee_cents": fee,
            "net_charge_off_cents": net,
            "principal_recovered_cents": 0,
            "fee_recovered_cents": 0,
            "status": "PROPOSED",
            "approved_by_user_id": None,
            "booked_by_user_id": None,
            "ledger_balance_before_book_cents": None,
            "booked_at": None,
            "reversed_at": None,
        }
    )
    db.charge_offs[row["id"]] = row
    touch(acct)
    return ok(serial.charge_off(row), 201)


@bp.get(API_PREFIX + "/accounts/<aid>/charge-offs")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def list_account_charge_offs(aid):
    get_account(aid)
    limit, offset = pagination()
    status = query_enum("status", CHARGE_OFF_STATUSES)
    rows = [c for c in db.charge_offs.values() if c["account_id"] == aid]
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.charge_off)
    return ok_list(items, limit, offset, total)


@bp.get(API_PREFIX + "/charge-offs/<coid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def read_charge_off(coid):
    return ok(serial.charge_off(get_charge_off(coid)))


@bp.post(API_PREFIX + "/charge-offs/<coid>/approve")
@endpoint(["FraudSupervisor"])
def approve_charge_off(coid):
    co = get_charge_off(coid)
    if co["status"] != "PROPOSED":
        fail("ERR_CHARGE_OFF_INVALID_STATE", "Approval requires status PROPOSED.")
    co["status"] = "APPROVED"
    co["approved_by_user_id"] = g.user_id
    touch(co)
    return ok(serial.charge_off(co))


@bp.post(API_PREFIX + "/charge-offs/<coid>/book")
@endpoint(["OperationsAdmin"])
def book_charge_off(coid):
    co = get_charge_off(coid)
    if co["status"] != "APPROVED":
        fail("ERR_CHARGE_OFF_INVALID_STATE", "Booking requires status APPROVED.")
    acct = db.accounts.get(co["account_id"])
    if acct is None or acct["lifecycle_status"] != "CLOSED":
        fail("ERR_ACCOUNT_NOT_CLOSED", "Booking requires a CLOSED account.")

    co["status"] = "BOOKED"
    co["booked_by_user_id"] = g.user_id
    co["booked_at"] = now()
    co["ledger_balance_before_book_cents"] = acct["ledger_balance_cents"]

    snap = calc.snapshot_account(acct)
    acct["ledger_balance_cents"] += co["net_charge_off_cents"]
    acct["available_balance_cents"] += co["net_charge_off_cents"]
    acct["charged_off_amount_cents"] = co["net_charge_off_cents"]
    acct["lifecycle_status"] = "CHARGED_OFF"
    calc.bump_if_dirty(acct, snap)

    if co["net_charge_off_cents"] >= calc.RECOVERY_REFERRAL_MIN_CENTS:
        co["status"] = "REFERRED_TO_RECOVERY"
    touch(co)
    return ok(serial.charge_off(co))


@bp.post(API_PREFIX + "/charge-offs/<coid>/recovery-postings")
@endpoint(["OperationsAdmin"])
def recovery_posting(coid):
    co = get_charge_off(coid)
    data = body()
    amount = req_int(data, "amount_cents", 1, None)

    if co["status"] not in ("REFERRED_TO_RECOVERY", "RECOVERED_PARTIAL"):
        fail(
            "ERR_CHARGE_OFF_INVALID_STATE",
            "Recovery postings require REFERRED_TO_RECOVERY or RECOVERED_PARTIAL.",
        )

    remaining = amount
    fee_room = co["recovery_fee_cents"] - co["fee_recovered_cents"]
    applied_fee = min(remaining, fee_room)
    remaining -= applied_fee
    principal_room = co["base_net_cents"] - co["principal_recovered_cents"]
    applied_principal = min(remaining, principal_room)
    remaining -= applied_principal
    if remaining > 0:
        fail("ERR_RECOVERY_EXCEEDS_LOSS", "The posting exceeds the remaining loss.")

    co["fee_recovered_cents"] += applied_fee
    co["principal_recovered_cents"] += applied_principal
    acct = db.accounts.get(co["account_id"])
    if acct is not None:
        snap = calc.snapshot_account(acct)
        acct["charged_off_amount_cents"] -= applied_fee + applied_principal
        calc.bump_if_dirty(acct, snap)
    co["status"] = "RECOVERED_FULL" if calc.outstanding_loss(co) == 0 else "RECOVERED_PARTIAL"
    touch(co)
    return ok(serial.charge_off(co))


@bp.post(API_PREFIX + "/charge-offs/<coid>/reverse")
@endpoint(["FraudSupervisor"])
def reverse_charge_off(coid):
    co = get_charge_off(coid)
    data = body()
    req_present_str(data, "reversal_reason")

    if co["status"] not in (
        "BOOKED",
        "REFERRED_TO_RECOVERY",
        "RECOVERED_PARTIAL",
        "RECOVERED_FULL",
    ):
        fail("ERR_CHARGE_OFF_INVALID_STATE", "This charge-off cannot be reversed.")
    if co["principal_recovered_cents"] != 0 or co["fee_recovered_cents"] != 0:
        fail("ERR_RECOVERY_ALREADY_POSTED", "A recovery posting has already been applied.")

    co["status"] = "REVERSED"
    co["reversed_at"] = now()
    touch(co)

    acct = db.accounts.get(co["account_id"])
    if acct is not None:
        snap = calc.snapshot_account(acct)
        if co["ledger_balance_before_book_cents"] is not None:
            acct["ledger_balance_cents"] = co["ledger_balance_before_book_cents"]
        acct["available_balance_cents"] -= co["net_charge_off_cents"]
        acct["charged_off_amount_cents"] = 0
        if acct["lifecycle_status"] == "CHARGED_OFF":
            acct["lifecycle_status"] = "CLOSED"
        calc.bump_if_dirty(acct, snap)

    return ok(serial.charge_off(co))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/_clock/set_current_utc")
@endpoint(["OperationsAdmin"])
def set_clock():
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        bad("Missing required field to_iso8601.")
    parsed = parse_iso(data["to_iso8601"])
    if parsed is None:
        bad("to_iso8601 must be an ISO 8601 UTC timestamp.")
    db.clock = parsed
    from core import iso as _iso

    return ok({"current_utc": _iso(parsed)})
