"""Routes: accounts, identity verifications, appeals, suspension, clock."""
from datetime import timedelta
from flask import Blueprint, request
from core import (DB, CLOCK, ok, paginate, err, new_record, touch, authenticate,
                  require_role, check_ownership, _parse_iso, new_id, req_ts)
from services import (serialize, lazy_account, suspend_account_cascade,
                      resume_account_cascade, recompute_eligible_ad_count)

bp = Blueprint("accounts", __name__)

COUNTRY_ENUM_OK = lambda s: isinstance(s, str) and len(s) == 2 and s.isupper() and s.isalpha()


def get_account_or_404(account_id):
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    return account


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_role(caller, "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        err("ERR_VALIDATION", "to_iso8601 required")
    try:
        new_value = CLOCK.set(to_iso)
    except Exception:
        err("ERR_VALIDATION", "to_iso8601 is not a valid ISO 8601 timestamp")
    return ok({"current_utc": new_value}, 200)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@bp.post("/advertiser-accounts")
def create_account():
    # Anonymous endpoint: no auth check
    body = request.get_json(silent=True) or {}
    business_name = body.get("business_name")
    country_code = body.get("country_code")
    if not isinstance(business_name, str) or not business_name:
        err("ERR_VALIDATION", "business_name required")
    if not COUNTRY_ENUM_OK(country_code):
        err("ERR_VALIDATION", "country_code must be exactly 2 uppercase letters")
    account = new_record({
        "business_name": business_name,
        "country_code": country_code,
        "status": "PENDING_VERIFICATION",
        "suspension_reason_code": None,
        "suspended_at": None,
        "upheld_appeal_count": 0,
        "verified_business_name": None,
        "disclosure_text": None,
        "lifetime_valid_served_cents": 0,
        "lifetime_billed_cents": 0,
        "lifetime_overdelivery_credit_cents": 0,
        "lifetime_invalid_click_credit_cents": 0,
    })
    DB.accounts[account["id"]] = account
    return ok(serialize("account", account), 201)


@bp.get("/advertiser-accounts/<account_id>")
def get_account(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin", "BillingAdmin", "PolicyReviewer")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    lazy_account(account)
    return ok(serialize("account", account), 200)


@bp.post("/advertiser-accounts/<account_id>/suspend")
def suspend_account(account_id):
    caller = authenticate()
    require_role(caller, "PlatformAdmin")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason_code")
    if reason not in ("POLICY_VIOLATION", "CIRCUMVENTION", "BILLING_DELINQUENCY"):
        err("ERR_VALIDATION", "reason_code must be POLICY_VIOLATION, CIRCUMVENTION, or BILLING_DELINQUENCY")
    if account["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Only an ACTIVE account can be suspended")
    account["status"] = "SUSPENDED"
    account["suspension_reason_code"] = reason
    account["suspended_at"] = CLOCK.now_iso()
    account["upheld_appeal_count"] = 0
    touch(account)
    suspend_account_cascade(account)
    return ok(serialize("account", account), 200)


# ---------------------------------------------------------------------------
# Identity verifications
# ---------------------------------------------------------------------------

@bp.post("/advertiser-accounts/<account_id>/identity-verifications")
def submit_verification(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    body = request.get_json(silent=True) or {}
    legal = body.get("legal_business_name")
    reg = body.get("registration_number")
    dtype = body.get("document_type")
    consent = body.get("disclosure_consent")
    expected = body.get("expected_account_version")
    if not isinstance(legal, str) or not legal:
        err("ERR_VALIDATION", "legal_business_name required")
    if not isinstance(reg, str) or not reg:
        err("ERR_VALIDATION", "registration_number required")
    if dtype not in ("BUSINESS_LICENSE", "TAX_CERTIFICATE", "GOVERNMENT_ID"):
        err("ERR_VALIDATION", "document_type invalid")
    if not isinstance(consent, bool):
        err("ERR_VALIDATION", "disclosure_consent must be a boolean")
    if expected is None or not isinstance(expected, int):
        err("ERR_VALIDATION", "expected_account_version required")
    # OCC (priority 5)
    if expected != account["version"]:
        err("ERR_STALE_VERSION", "expected_account_version does not match current version")
    # pending-window occupation (priority 8)
    for v in DB.verifications.values():
        if v["account_id"] == account["id"] and v["status"] == "SUBMITTED":
            err("ERR_DUPLICATE_VERIFICATION_PENDING", "A SUBMITTED verification already exists")
    supersedes = None
    rejected = [v for v in DB.verifications.values()
                if v["account_id"] == account["id"] and v["status"] == "REJECTED"]
    if rejected:
        rejected.sort(key=lambda v: (v["created_at"], v.get("_seq", 0)))
        supersedes = rejected[-1]["id"]
    ver = new_record({
        "account_id": account["id"],
        "legal_business_name": legal,
        "registration_number": reg,
        "document_type": dtype,
        "disclosure_consent": consent,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "supersedes_id": supersedes,
    })
    DB.verifications[ver["id"]] = ver
    touch(account)  # submission mutates the account dossier
    return ok(serialize("verification", ver), 201)


@bp.get("/advertiser-accounts/<account_id>/identity-verifications")
def list_verifications(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    items = [v for v in DB.verifications.values() if v["account_id"] == account["id"]]
    items.sort(key=lambda v: (v["created_at"], v.get("_seq", 0), v["id"]))
    page, meta = paginate(items)
    return ok([serialize("verification", v) for v in page], 200, meta)


@bp.post("/identity-verifications/<verification_id>/decide")
def decide_verification(verification_id):
    caller = authenticate()
    require_role(caller, "PlatformAdmin")
    ver = DB.verifications.get(verification_id)
    if ver is None:
        err("ERR_NOT_FOUND", "IdentityVerification not found")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    rejection_reason = body.get("rejection_reason")
    if outcome not in ("APPROVED", "REJECTED"):
        err("ERR_VALIDATION", "outcome must be APPROVED or REJECTED")
    if outcome == "REJECTED" and (not isinstance(rejection_reason, str) or not rejection_reason):
        err("ERR_VALIDATION", "rejection_reason required for REJECTED")
    if ver["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Verification already decided")
    account = DB.accounts.get(ver["account_id"])
    if outcome == "APPROVED":
        ver["status"] = "APPROVED"
        touch(ver)
        if account is not None:
            account["verified_business_name"] = ver["legal_business_name"]
            account["disclosure_text"] = "Ads by " + ver["legal_business_name"]
            if account["status"] == "PENDING_VERIFICATION":
                account["status"] = "ACTIVE"
            touch(account)
    else:
        ver["status"] = "REJECTED"
        ver["rejection_reason"] = rejection_reason
        touch(ver)
    return ok(serialize("verification", ver), 200)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

@bp.post("/advertiser-accounts/<account_id>/appeals")
def file_appeal(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    body = request.get_json(silent=True) or {}
    argument_text = body.get("argument_text")
    if not isinstance(argument_text, str) or not argument_text:
        err("ERR_VALIDATION", "argument_text required")
    # lazy SUSPENDED_FINAL evaluation on filing attempt
    lazy_account(account)
    # uniqueness: an open appeal means APPEAL_PENDING — the conflict rule of
    # §2.11 must be reachable, so it is checked before the state gate.
    for a in DB.appeals.values():
        if a["account_id"] == account["id"] and a["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            err("ERR_APPEAL_ALREADY_OPEN", "An appeal is already open for this account")
    # appeal window (priority 9): PRD requires ERR_APPEAL_WINDOW_CLOSED even
    # when the lazy evaluation above already moved the account to
    # SUSPENDED_FINAL, so the window check precedes the state gate.
    if account["suspended_at"]:
        suspended_at = _parse_iso(account["suspended_at"])
        now = CLOCK.now()
        if now >= suspended_at + timedelta(days=30):
            err("ERR_APPEAL_WINDOW_CLOSED", "Appeal window closed")
    if account["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Appeals may only be filed while the account is SUSPENDED")
    now = CLOCK.now()
    # cooling-off: last UPHELD appeal decided_at + 14 days
    upheld = [a for a in DB.appeals.values()
              if a["account_id"] == account["id"] and a["status"] == "UPHELD"]
    if upheld:
        upheld.sort(key=lambda a: (a["decided_at"] or "", a.get("_seq", 0)))
        last = upheld[-1]
        last_decided = _parse_iso(last["decided_at"])
        if now < last_decided + timedelta(days=14):
            err("ERR_APPEAL_COOLDOWN", "Appeal cooling-off period not elapsed")
    appeal = new_record({
        "account_id": account["id"],
        "argument_text": argument_text,
        "challenges_suspended_at": account["suspended_at"],
        "status": "SUBMITTED",
        "decided_at": None,
        "reviewer_note": None,
    })
    DB.appeals[appeal["id"]] = appeal
    account["status"] = "APPEAL_PENDING"
    touch(account)
    # automatic intake: SUBMITTED -> UNDER_REVIEW
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return ok(serialize("appeal", appeal), 201)


@bp.get("/advertiser-accounts/<account_id>/appeals")
def list_appeals(account_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account["id"])
    items = [a for a in DB.appeals.values() if a["account_id"] == account["id"]]
    items.sort(key=lambda a: (a["created_at"], a.get("_seq", 0), a["id"]))
    page, meta = paginate(items)
    return ok([serialize("appeal", a) for a in page], 200, meta)


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    caller = authenticate()
    require_role(caller, "PlatformAdmin")
    appeal = DB.appeals.get(appeal_id)
    if appeal is None:
        err("ERR_NOT_FOUND", "Appeal not found")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    note = body.get("reviewer_note")
    if outcome not in ("UPHELD", "OVERTURNED"):
        err("ERR_VALIDATION", "outcome must be UPHELD or OVERTURNED")
    if appeal["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Appeal already decided")
    account = DB.accounts.get(appeal["account_id"])
    appeal["decided_at"] = CLOCK.now_iso()
    if isinstance(note, str):
        appeal["reviewer_note"] = note
    if outcome == "OVERTURNED":
        appeal["status"] = "OVERTURNED"
        touch(appeal)
        if account is not None:
            account["status"] = "ACTIVE"
            account["suspension_reason_code"] = None
            touch(account)
            resume_account_cascade(account)
    else:  # UPHELD
        appeal["status"] = "UPHELD"
        touch(appeal)
        if account is not None:
            account["upheld_appeal_count"] = account.get("upheld_appeal_count", 0) + 1
            if account["upheld_appeal_count"] >= 2:
                account["status"] = "SUSPENDED_FINAL"
            else:
                account["status"] = "SUSPENDED"
            touch(account)
    return ok(serialize("appeal", appeal), 200)
