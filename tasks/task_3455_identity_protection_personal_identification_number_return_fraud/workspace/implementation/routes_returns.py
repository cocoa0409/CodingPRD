"""TaxReturn routes: intake (validations -> claims/conflicts -> scoring ->
scheme scans), release-refund, confirm-fraud, sublists; plus the disbursement
release handshake."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from auth import require_roles
from domain import (active_pin, create_hold, disbursement_for_return,
                    fraud_cascade, get_disbursement, get_return, new_record,
                    pub, touch, verified_case_for_return, velocity_scans)
from envelope import created, list_response, ok
from errors import err as raise_err
from store import DB, fmt_ts
from validate import (body, invalid, is_int, is_tin, opt_enum, opt_str, page,
                      pagination, req_field, req_int, req_str)

bp = Blueprint("returns", __name__)

FILING_STATUSES = ("SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD")
BANK_PRODUCTS = ("NONE", "REFUND_TRANSFER")
RELATIONSHIPS = ("CHILD", "STEPCHILD", "SIBLING", "PARENT", "OTHER")
RETURN_TERMINAL = ("REFUND_RELEASED", "FRAUD_CONFIRMED")


def _own_return(uid, role, ret):
    """Priority 3 ownership for entity-backed callers on a return resource."""
    if role == "Taxpayer" and ret["taxpayer_id"] != uid:
        raise_err("ERR_UNAUTHORIZED")
    if role == "TaxPreparer" and ret["preparer_id"] != uid:
        raise_err("ERR_UNAUTHORIZED")


@bp.post("/identity-protection/tax-returns")
def file_return():
    uid, role = require_roles(["Taxpayer", "TaxPreparer"])
    b = body()
    # Priority 3: entity-backed ownership on the filing payload.
    if role == "Taxpayer":
        if b.get("taxpayer_id") != uid:
            raise_err("ERR_UNAUTHORIZED")
    else:  # TaxPreparer files only returns carrying their own preparer_id
        if b.get("preparer_id") != uid:
            raise_err("ERR_UNAUTHORIZED")
    # Priority 4: body-carried identifiers must resolve.
    taxpayer = None
    tid = b.get("taxpayer_id")
    if tid is not None:
        taxpayer = DB.taxpayers.get(tid)
        if taxpayer is None:
            raise_err("ERR_TAXPAYER_NOT_FOUND")
    preparer = None
    pid = b.get("preparer_id")
    if pid is not None:
        preparer = DB.preparers.get(pid)
        if preparer is None:
            raise_err("ERR_PREPARER_NOT_FOUND")
    # Priority 7: filing gate — IP PIN and preparer suspension.
    tax_year = b.get("tax_year")
    if taxpayer is not None and taxpayer["ip_pin_enrollment"] == "ENROLLED":
        submitted = b.get("ip_pin_submitted")
        if submitted is None:
            raise_err("ERR_IP_PIN_REQUIRED")
        pin = active_pin(taxpayer["id"], tax_year) if is_int(tax_year) else None
        if pin is None or pin["pin_value"] != submitted:
            raise_err("ERR_IP_PIN_MISMATCH")
    if preparer is not None and preparer["status"] == "SUSPENDED":
        raise_err("ERR_PREPARER_SUSPENDED")
    # Priority 8: uniqueness / exclusivity.
    if taxpayer is not None and is_int(tax_year):
        for r in DB.returns.values():
            if (r["taxpayer_id"] == taxpayer["id"] and r["tax_year"] == tax_year
                    and r["status"] not in RETURN_TERMINAL):
                # Duplicate filings still auto-create a DUPLICATE_DETECTION report.
                new_record(DB.reports, {
                    "taxpayer_id": taxpayer["id"],
                    "source": "DUPLICATE_DETECTION",
                    "description": "",
                    "created_by_user_id": "system",
                    "confirmed_tax_year": None,
                    "status": "SUBMITTED",
                })
                raise_err("ERR_DUPLICATE_RETURN")
    dependents = b.get("dependents")
    if isinstance(dependents, list) and is_int(tax_year):
        for d in dependents:
            if not isinstance(d, dict):
                continue
            dtin = d.get("dependent_tin")
            if not isinstance(dtin, str):
                continue
            for cf in DB.conflicts.values():
                if (cf["status"] == "OPEN" and cf["dependent_tin"] == dtin
                        and cf["tax_year"] == tax_year):
                    raise_err("ERR_DEPENDENT_CONFLICT_OPEN")
    # Priority 11: exactly one ACTIVE filter model config is required.
    cfg = calc.active_config()
    if cfg is None:
        raise_err("ERR_CONFIG_NOT_ACTIVE")
    # Priority 14: payload shape.
    tid = req_str(b, "taxpayer_id")
    if taxpayer is None:
        raise_err("ERR_TAXPAYER_NOT_FOUND")
    if pid is not None and not isinstance(pid, str):
        invalid("preparer_id must be a string")
    tax_year = req_int(b, "tax_year")
    if tax_year != 2026:
        invalid("tax_year must be 2026")
    filing_status = req_field(b, "filing_status")
    if filing_status not in FILING_STATUSES:
        invalid("filing_status must be one of SINGLE, MARRIED_JOINT, HEAD_OF_HOUSEHOLD")
    claimed = req_int(b, "claimed_refund_cents")
    if claimed < 0:
        invalid("claimed_refund_cents must be >= 0")
    pin_submitted = b.get("ip_pin_submitted")
    if pin_submitted is not None and not isinstance(pin_submitted, str):
        invalid("ip_pin_submitted must be a string")
    bank_product = opt_enum(b, "bank_product", BANK_PRODUCTS, "NONE")
    fingerprint = opt_str(b, "bank_account_fingerprint")
    if bank_product == "NONE":
        fingerprint = None
    dep_specs = []
    if dependents is not None:
        if not isinstance(dependents, list):
            invalid("dependents must be an array")
        for d in dependents:
            if not isinstance(d, dict):
                invalid("dependents entries must be objects")
            dtin = d.get("dependent_tin")
            if not is_tin(dtin):
                invalid("dependent_tin must be exactly 9 digits")
            rel = d.get("relationship")
            if rel not in RELATIONSHIPS:
                invalid("relationship must be one of CHILD, STEPCHILD, SIBLING, PARENT, OTHER")
            dep_specs.append({"dependent_tin": dtin, "relationship": rel})
    # Create the return (RECEIVED is transient; scoring happens below).
    ret = new_record(DB.returns, {
        "taxpayer_id": tid,
        "preparer_id": pid,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "claimed_refund_cents": claimed,
        "ip_pin_submitted": pin_submitted,
        "bank_product": bank_product,
        "bank_account_fingerprint": fingerprint,
        "received_at": DB.now_iso(),
        "risk_score": 0,
        "scoring_model_version": cfg["model_version"],
        "adjustment_cents": 0,
        "status": "RECEIVED",
    })
    # Dependent claims, then conflict detection (flips feed the score).
    my_claims = []
    for spec in dep_specs:
        my_claims.append(new_record(DB.claims, {
            "return_id": ret["id"],
            "dependent_tin": spec["dependent_tin"],
            "relationship": spec["relationship"],
            "credit_cents": calc.DEPENDENT_CREDIT_CENTS,
            "status": "CLAIMED",
        }))
    for cl in my_claims:
        for other in list(DB.claims.values()):
            if other["id"] == cl["id"] or other["status"] != "CLAIMED":
                continue
            if other["dependent_tin"] != cl["dependent_tin"]:
                continue
            other_ret = DB.returns.get(other["return_id"])
            if other_ret is None or other_ret["id"] == ret["id"]:
                continue
            if other_ret["tax_year"] != ret["tax_year"]:
                continue
            other["status"] = "CONTESTED"
            touch(other)
            cl["status"] = "CONTESTED"
            touch(cl)
            if (other_ret["received_at"], other_ret["created_at"], other_ret["_seq"]) <= \
               (ret["received_at"], ret["created_at"], ret["_seq"]):
                ret_a, ret_b = other_ret, ret
            else:
                ret_a, ret_b = ret, other_ret
            new_record(DB.conflicts, {
                "dependent_tin": cl["dependent_tin"],
                "tax_year": ret["tax_year"],
                "return_a_id": ret_a["id"],
                "return_b_id": ret_b["id"],
                "evidence_window_ends_at": fmt_ts(
                    DB.now() + timedelta(days=calc.EVIDENCE_WINDOW_DAYS)),
                "evidence_a_submitted": False,
                "evidence_b_submitted": False,
                "resolution": None,
                "resolved_reason": None,
                "status": "OPEN",
            })
            break
    # Intake scoring with the single ACTIVE config.
    score, reasons = calc.compute_risk_score(ret, taxpayer, cfg)
    ret["risk_score"] = score
    if score >= cfg["hold_threshold"]:
        ret["status"] = "FILTER_HELD"
        create_hold(ret, "FULL", reasons)
    elif score >= cfg["gray_zone_threshold"]:
        ret["status"] = "FILTER_HELD"
        create_hold(ret, "GRAY", reasons)
    else:
        ret["status"] = "FILTER_PASSED"
    if preparer is not None:
        preparer["filed_return_count"] += 1
        touch(preparer)
    velocity_scans(ret)
    return created(pub(ret))


@bp.get("/identity-protection/tax-returns")
def list_returns():
    require_roles(["FraudAnalyst", "SystemAdmin", "VerificationAgent"])
    limit, offset = pagination()
    rows = list(DB.returns.values())
    for param in ("taxpayer_id", "preparer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if r.get(param) == v]
    items, total = page(rows, limit, offset)
    return list_response([pub(r) for r in items], total, limit, offset)


@bp.get("/identity-protection/tax-returns/<string:return_id>")
def read_return(return_id):
    uid, role = require_roles(
        ["Taxpayer", "TaxPreparer", "FraudAnalyst", "VerificationAgent",
         "TaxpayerAdvocate", "SystemAdmin"])
    ret = get_return(return_id)
    _own_return(uid, role, ret)
    return ok(pub(ret))


@bp.post("/identity-protection/tax-returns/<string:return_id>/release-refund")
def release_refund(return_id):
    require_roles(["FraudAnalyst"])
    ret = get_return(return_id)
    if ret["status"] in RETURN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL")
    if ret["status"] == "REFUND_SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Refund is already scheduled.")
    if ret["status"] == "FILTER_HELD":
        # Priority 11: held returns require a VERIFIED linked case.
        if verified_case_for_return(ret["id"]) is None:
            raise_err("ERR_VERIFICATION_INCOMPLETE")
    base = ret["claimed_refund_cents"] + ret["adjustment_cents"]
    provisional = calc.provisional_interest(ret, base, DB.now_iso())
    disb = new_record(DB.disbursements, {
        "return_id": ret["id"],
        "base_cents": base,
        "provisional_interest_cents": provisional,
        "final_interest_cents": None,
        "amount_cents": base + provisional,
        "scheduled_at": DB.now_iso(),
        "released_at": None,
        "status": "SCHEDULED",
    })
    disb["_sched_base"] = base
    disb["_adj_events"] = []
    ret["status"] = "REFUND_SCHEDULED"
    touch(ret)
    return created(pub(disb))


@bp.post("/identity-protection/tax-returns/<string:return_id>/confirm-fraud")
def confirm_fraud(return_id):
    require_roles(["FraudAnalyst"])
    ret = get_return(return_id)
    if ret["status"] in RETURN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL")
    if ret["status"] not in ("FILTER_HELD", "REFUND_SCHEDULED"):
        raise_err("ERR_INVALID_STATE",
                  "Fraud can be confirmed only from FILTER_HELD or REFUND_SCHEDULED.")
    was_scheduled = ret["status"] == "REFUND_SCHEDULED"
    ret["status"] = "FRAUD_CONFIRMED"
    touch(ret)
    fraud_cascade(ret)
    if was_scheduled:
        d = disbursement_for_return(ret["id"])
        if d is not None and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            touch(d)
    return ok(pub(ret))


@bp.get("/identity-protection/tax-returns/<string:return_id>/dependent-claims")
def list_claims(return_id):
    uid, role = require_roles(["Taxpayer", "TaxPreparer", "FraudAnalyst", "SystemAdmin"])
    ret = get_return(return_id)
    _own_return(uid, role, ret)
    limit, offset = pagination()
    rows = [c for c in DB.claims.values() if c["return_id"] == ret["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(c) for c in items], total, limit, offset)


@bp.get("/identity-protection/tax-returns/<string:return_id>/filter-holds")
def list_holds(return_id):
    uid, role = require_roles(
        ["Taxpayer", "FraudAnalyst", "VerificationAgent", "TaxpayerAdvocate", "SystemAdmin"])
    ret = get_return(return_id)
    if role == "Taxpayer" and ret["taxpayer_id"] != uid:
        raise_err("ERR_UNAUTHORIZED")
    limit, offset = pagination()
    rows = [h for h in DB.holds.values() if h["return_id"] == ret["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(h) for h in items], total, limit, offset)


@bp.get("/identity-protection/tax-returns/<string:return_id>/refund-disbursements")
def list_disbursements(return_id):
    uid, role = require_roles(["Taxpayer", "FraudAnalyst", "SystemAdmin", "TaxpayerAdvocate"])
    ret = get_return(return_id)
    if role == "Taxpayer" and ret["taxpayer_id"] != uid:
        raise_err("ERR_UNAUTHORIZED")
    limit, offset = pagination()
    rows = [d for d in DB.disbursements.values() if d["return_id"] == ret["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(d) for d in items], total, limit, offset)


@bp.post("/identity-protection/refund-disbursements/<string:disbursement_id>/release")
def release_disbursement(disbursement_id):
    require_roles(["SystemAdmin"])
    d = get_disbursement(disbursement_id)
    if d["status"] in ("RELEASED", "CANCELLED"):
        raise_err("ERR_ALREADY_TERMINAL")
    ret = get_return(d["return_id"])
    final = calc.final_interest(ret, d, DB.now())
    # Priority 12: money-consistency handshake.
    b = body()
    expected = b.get("expected_amount_cents")
    if expected is not None and expected != d["base_cents"] + final:
        raise_err("ERR_DISBURSEMENT_AMOUNT_MISMATCH")
    # Priority 14: payload shape.
    expected = req_int(b, "expected_amount_cents")
    if expected != d["base_cents"] + final:
        raise_err("ERR_DISBURSEMENT_AMOUNT_MISMATCH")
    d["final_interest_cents"] = final
    d["amount_cents"] = d["base_cents"] + final
    d["released_at"] = DB.now_iso()
    d["status"] = "RELEASED"
    touch(d)
    ret["status"] = "REFUND_RELEASED"
    touch(ret)
    return ok(pub(d))
