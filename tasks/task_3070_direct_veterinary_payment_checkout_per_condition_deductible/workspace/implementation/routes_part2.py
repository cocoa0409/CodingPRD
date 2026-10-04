"""Route handlers, part 2: claims, payments, appeals, conditions, reports."""
from datetime import timedelta

from flask import Blueprint, request

import core
from core import (
    store, fail, ok, body, req_field, req_str, opt_version,
    require_roles, paginate, sort_items, public, new_entity, touch, now_iso,
)
import logic
from routes_part1 import (
    get_hospital_or_404, get_policy_or_404, get_record_or_404, get_report_or_404,
    RECORD_FIELDS, REPORT_FIELDS,
)

bp = Blueprint("part2", __name__)

CLAIM_FIELDS = [
    "id", "policy_id", "hospital_id", "visit_date", "claim_type", "status",
    "total_invoice_cents", "eligible_cents", "deductible_applied_cents",
    "reimbursement_cents", "member_responsibility_cents", "adjudicated_at",
    "denial_reason", "payment_id", "created_at", "updated_at", "version",
]
LINE_FIELDS = [
    "id", "claim_id", "seq", "description", "amount_cents", "category",
    "condition_code", "eligible_amount_cents", "policy_condition_id",
    "deductible_applied_cents", "reimbursement_cents", "created_at",
]
PAYMENT_FIELDS = [
    "id", "claim_id", "hospital_id", "amount_cents", "kind", "status",
    "ledger_status", "idempotency_key", "reverses_payment_id",
    "created_at", "updated_at", "version",
]
APPEAL_FIELDS = [
    "id", "claim_id", "opened_by", "reason_code", "original_adjuster_id",
    "status", "records_due_at", "resolution_note", "created_at", "updated_at", "version",
]
CONDITION_FIELDS = [
    "id", "policy_id", "condition_code", "preexisting", "deductible_target_cents",
    "deductible_accumulated_cents", "lifetime_reimbursed_cents",
    "created_at", "updated_at", "version",
]


def claim_view(c):
    logic.sweep_claim(c)
    return public(c, CLAIM_FIELDS)


def get_claim_or_404(cid):
    c = store.claims.get(cid)
    if c is None:
        fail("ERR_CLAIM_NOT_FOUND", 404, "Claim not found")
    return c


def get_appeal_or_404(aid):
    a = store.appeals.get(aid)
    if a is None:
        fail("ERR_APPEAL_NOT_FOUND", 404, "Appeal not found")
    return a


def get_payment_or_404(pid):
    p = store.payments.get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", 404, "Payment not found")
    return p


def get_condition_or_404(cid):
    c = store.conditions.get(cid)
    if c is None:
        fail("ERR_NOT_FOUND", 404, "PolicyCondition not found")
    return c


def get_line_or_404(lid):
    l = store.lines.get(lid)
    if l is None:
        fail("ERR_NOT_FOUND", 404, "ClaimLine not found")
    return l


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@bp.post("/claims")
def create_claim():
    uid, _ = require_roles("HospitalStaff")
    data = body()
    policy = get_policy_or_404(req_str(data, "policy_id"))
    hospital = get_hospital_or_404(req_str(data, "hospital_id"))
    if uid != hospital["id"]:
        fail(core.ERR_UNAUTHORIZED, 403, "Staff may act only for their own hospital")
    visit = core.parse_date(req_field(data, "visit_date"))
    if visit is None:
        fail(core.ERR_INVALID_REQUEST, 400, "visit_date must be an ISO date")
    ctype = req_str(data, "claim_type")
    if ctype not in ("INJURY", "ILLNESS"):
        fail(core.ERR_INVALID_REQUEST, 400, "claim_type must be INJURY or ILLNESS")
    raw_lines = req_field(data, "lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        fail(core.ERR_INVALID_REQUEST, 400, "lines must be a non-empty array")
    parsed_lines = []
    for i, ln in enumerate(raw_lines):
        if not isinstance(ln, dict):
            fail(core.ERR_INVALID_REQUEST, 400, "Each line must be an object")
        desc = ln.get("description")
        if not isinstance(desc, str):
            fail(core.ERR_INVALID_REQUEST, 400, "Line description must be a string")
        amt = ln.get("amount_cents")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            fail(core.ERR_INVALID_REQUEST, 400, "Line amount_cents must be a positive integer")
        cat = ln.get("category")
        if cat not in ("TREATMENT", "EXAM_FEE", "TAX", "OTHER_EXCLUDED"):
            fail(core.ERR_INVALID_REQUEST, 400, "Invalid line category")
        cc = ln.get("condition_code")
        if cat == "TREATMENT":
            if cc is None or not isinstance(cc, str):
                fail("ERR_CONDITION_CODE_REQUIRED", 400,
                     "TREATMENT line requires condition_code")
        else:
            if cc is not None and not isinstance(cc, str):
                fail(core.ERR_INVALID_REQUEST, 400, "condition_code must be a string")
        parsed_lines.append({
            "description": desc, "amount_cents": amt, "category": cat,
            "condition_code": cc,
        })
    if hospital["status"] != "ACTIVE":
        fail("ERR_HOSPITAL_NOT_ACTIVE", 409, "Hospital is not ACTIVE")
    logic.sweep_policy(policy)
    if policy["lifecycle_status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", 409, "Policy is not ACTIVE")
    c = new_entity()
    c.update({
        "policy_id": policy["id"],
        "hospital_id": hospital["id"],
        "visit_date": visit.isoformat(),
        "claim_type": ctype,
        "status": "SUBMITTED",
        "total_invoice_cents": 0,
        "eligible_cents": 0,
        "deductible_applied_cents": 0,
        "reimbursement_cents": 0,
        "member_responsibility_cents": 0,
        "adjudicated_at": None,
        "denial_reason": None,
        "payment_id": None,
        "paid_at": None,
        "last_adjuster_id": None,
    })
    store.claims[c["id"]] = c
    for idx, pl in enumerate(parsed_lines, start=1):
        line = {
            "id": core.new_id(),
            "created_at": now_iso(),
            "_seq": core.tick(),
            "claim_id": c["id"],
            "seq": idx,
            "description": pl["description"],
            "amount_cents": pl["amount_cents"],
            "category": pl["category"],
            "condition_code": pl["condition_code"],
            "eligible_amount_cents": 0,
            "policy_condition_id": None,
            "deductible_applied_cents": 0,
            "reimbursement_cents": 0,
            "reversed": False,
        }
        store.lines[line["id"]] = line
    return ok(claim_view(c), 201)


@bp.get("/claims")
def list_claims():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    items = list(store.claims.values())
    for c in items:
        logic.sweep_claim(c)
    pid = request.args.get("policy_id")
    hid = request.args.get("hospital_id")
    st = request.args.get("status")
    ct = request.args.get("claim_type")
    payid = request.args.get("payment_id")
    if pid is not None:
        items = [c for c in items if c["policy_id"] == pid]
    if hid is not None:
        items = [c for c in items if c["hospital_id"] == hid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    if ct is not None:
        items = [c for c in items if c["claim_type"] == ct]
    if payid is not None:
        items = [c for c in items if c["payment_id"] == payid]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(c, CLAIM_FIELDS) for c in page], 200, meta)


@bp.get("/claims/<claimId>")
def get_claim(claimId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    return ok(claim_view(get_claim_or_404(claimId)))


@bp.get("/claims/<claimId>/lines")
def list_claim_lines(claimId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    c = get_claim_or_404(claimId)
    items = logic.claim_lines_sorted(c["id"])
    page, meta = paginate(items)
    return ok([public(l, LINE_FIELDS) for l in page], 200, meta)


@bp.post("/claims/<claimId>/flag-preexisting-review")
def flag_review(claimId):
    require_roles("ClaimsAdjuster")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    if c["status"] != "SUBMITTED":
        fail(core.ERR_INVALID_STATE, 409, "Claim is not SUBMITTED")
    c["status"] = "PREEXISTING_REVIEW"
    touch(c)
    return ok(claim_view(c))


@bp.post("/claims/<claimId>/clear-preexisting-review")
def clear_review(claimId):
    require_roles("ClaimsAdjuster")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    if c["status"] != "PREEXISTING_REVIEW":
        fail(core.ERR_INVALID_STATE, 409, "Claim is not PREEXISTING_REVIEW")
    c["status"] = "SUBMITTED"
    touch(c)
    return ok(claim_view(c))


@bp.post("/claims/<claimId>/adjudicate")
def adjudicate(claimId):
    uid, _ = require_roles("ClaimsAdjuster")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    data = body()
    expected = opt_version(data, "expected_claim_version")
    if c["status"] not in ("SUBMITTED", "PREEXISTING_REVIEW"):
        fail("ERR_CLAIM_NOT_ADJUDICATABLE", 409,
             "Claim must be SUBMITTED or PREEXISTING_REVIEW to adjudicate")
    hospital = store.hospitals.get(c["hospital_id"])
    if hospital is None or hospital["status"] != "ACTIVE":
        fail("ERR_HOSPITAL_NOT_ACTIVE", 409, "Hospital is not ACTIVE")
    policy = store.policies.get(c["policy_id"])
    logic.sweep_policy(policy)
    if policy["lifecycle_status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", 409, "Policy is not ACTIVE")
    wait_end = policy["_inj_end"] if c["claim_type"] == "INJURY" else policy["_ill_end"]
    if store.clock < wait_end:
        fail("ERR_WAITING_PERIOD_ACTIVE", 409, "Waiting period has not elapsed")
    if expected != c["version"]:
        fail("ERR_STALE_CLAIM_VERSION", 412, "Stale claim version")
    logic.run_adjudication(c, policy)
    c["status"] = "ADJUDICATED"
    c["last_adjuster_id"] = uid
    touch(c)
    return ok(claim_view(c))


@bp.post("/claims/<claimId>/deny")
def deny_claim(claimId):
    uid, _ = require_roles("ClaimsAdjuster")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    if c["status"] not in ("SUBMITTED", "PREEXISTING_REVIEW"):
        fail(core.ERR_INVALID_STATE, 409,
             "Claim must be SUBMITTED or PREEXISTING_REVIEW to deny")
    data = body()
    reason = req_str(data, "denial_reason")
    c["status"] = "DENIED"
    c["denial_reason"] = reason
    c["last_adjuster_id"] = uid
    touch(c)
    return ok(claim_view(c))


@bp.post("/claims/<claimId>/checkout-pay")
def checkout_pay(claimId):
    uid, _ = require_roles("HospitalStaff")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    data = body()
    key = req_str(data, "idempotency_key")
    simulate = data.get("simulate_outcome")
    # Idempotency first: same key on this claim returns the existing payment
    for p in store.payments.values():
        if p["claim_id"] == c["id"] and p.get("idempotency_key") == key:
            return ok(public(p, PAYMENT_FIELDS))
    if c["status"] not in ("ADJUDICATED", "PAYMENT_FAILED"):
        fail("ERR_CLAIM_NOT_PAYABLE", 409,
             "Claim must be ADJUDICATED (or PAYMENT_FAILED retry) to pay")
    if uid != c["hospital_id"]:
        fail(core.ERR_UNAUTHORIZED, 403, "Staff may pay only their own hospital's claims")
    hospital = store.hospitals.get(c["hospital_id"])
    # Retry path: exclude prior FAILED payments of this claim
    if c["status"] == "PAYMENT_FAILED":
        for p in store.payments.values():
            if p["claim_id"] == c["id"] and p["status"] == "FAILED":
                p["ledger_status"] = "EXCLUDED"
                touch(p)
    if simulate == "FAILED":
        pay = new_entity()
        pay.update({
            "claim_id": c["id"],
            "hospital_id": c["hospital_id"],
            "amount_cents": c["reimbursement_cents"],
            "kind": "DIRECT_PAY",
            "status": "FAILED",
            "ledger_status": "PENDING_POST",
            "idempotency_key": key,
            "reverses_payment_id": None,
        })
        store.payments[pay["id"]] = pay
        c["payment_id"] = pay["id"]
        c["status"] = "PAYMENT_FAILED"
        touch(c)
        return ok(public(pay, PAYMENT_FIELDS))
    # Success path
    pay = new_entity()
    pay.update({
        "claim_id": c["id"],
        "hospital_id": c["hospital_id"],
        "amount_cents": c["reimbursement_cents"],
        "kind": "DIRECT_PAY",
        "status": "SETTLED",
        "ledger_status": "POSTED",
        "idempotency_key": key,
        "reverses_payment_id": None,
    })
    store.payments[pay["id"]] = pay
    c["payment_id"] = pay["id"]
    c["status"] = "PAID"
    c["paid_at"] = store.clock
    # Increment lifetime reimbursement per condition from this claim's lines
    for line in logic.claim_lines_sorted(c["id"]):
        if line["category"] == "TREATMENT" and line.get("policy_condition_id"):
            cond = store.conditions.get(line["policy_condition_id"])
            if cond is not None:
                cond["lifetime_reimbursed_cents"] += line["reimbursement_cents"]
                touch(cond)
    if hospital is not None:
        hospital["running_ledger_balance_cents"] += pay["amount_cents"]
        touch(hospital)
    touch(c)
    return ok(public(pay, PAYMENT_FIELDS))


# ---------------------------------------------------------------------------
# Payments (read paths)
# ---------------------------------------------------------------------------


@bp.get("/payments")
def list_payments():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    items = list(store.payments.values())
    cid = request.args.get("claim_id")
    hid = request.args.get("hospital_id")
    st = request.args.get("status")
    ls = request.args.get("ledger_status")
    rpid = request.args.get("reverses_payment_id")
    if cid is not None:
        items = [p for p in items if p["claim_id"] == cid]
    if hid is not None:
        items = [p for p in items if p["hospital_id"] == hid]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    if ls is not None:
        items = [p for p in items if p["ledger_status"] == ls]
    if rpid is not None:
        items = [p for p in items if p["reverses_payment_id"] == rpid]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(p, PAYMENT_FIELDS) for p in page], 200, meta)


@bp.get("/payments/<paymentId>")
def get_payment(paymentId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    return ok(public(get_payment_or_404(paymentId), PAYMENT_FIELDS))


@bp.get("/claims/<claimId>/payments")
def list_claim_payments(claimId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    c = get_claim_or_404(claimId)
    items = [p for p in store.payments.values() if p["claim_id"] == c["id"]]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(p, PAYMENT_FIELDS) for p in page], 200, meta)


@bp.get("/hospitals/<hospitalId>/payments")
def list_hospital_payments(hospitalId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    h = get_hospital_or_404(hospitalId)
    items = [p for p in store.payments.values() if p["hospital_id"] == h["id"]]
    st = request.args.get("status")
    ls = request.args.get("ledger_status")
    rpid = request.args.get("reverses_payment_id")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    if ls is not None:
        items = [p for p in items if p["ledger_status"] == ls]
    if rpid is not None:
        items = [p for p in items if p["reverses_payment_id"] == rpid]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(p, PAYMENT_FIELDS) for p in page], 200, meta)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------


@bp.post("/claims/<claimId>/appeals")
def open_appeal(claimId):
    require_roles("PetOwner")
    c = get_claim_or_404(claimId)
    logic.sweep_claim(c)
    data = body()
    reason = req_str(data, "reason_code")
    if reason not in ("PREEXISTING_DISPUTE", "CONDITION_DEFINITION",
                      "COVERAGE_DENIAL", "LINE_CATEGORIZATION"):
        fail(core.ERR_INVALID_REQUEST, 400, "Invalid reason_code")
    if c["status"] not in ("DENIED", "SETTLED"):
        fail("ERR_APPEAL_NOT_OPENABLE", 409,
             "Appeals may be opened only on DENIED or SETTLED claims")
    a = new_entity()
    a.update({
        "claim_id": c["id"],
        "opened_by": "PET_OWNER",
        "reason_code": reason,
        "original_adjuster_id": c.get("last_adjuster_id"),
        "status": "OPEN",
        "records_due_at": None,
        "resolution_note": None,
    })
    store.appeals[a["id"]] = a
    return ok(public(a, APPEAL_FIELDS), 201)


@bp.get("/claims/<claimId>/appeals")
def list_claim_appeals(claimId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner", "HospitalStaff")
    c = get_claim_or_404(claimId)
    items = [a for a in store.appeals.values() if a["claim_id"] == c["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(a, APPEAL_FIELDS) for a in page], 200, meta)


@bp.get("/appeals")
def list_appeals():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner", "HospitalStaff")
    items = list(store.appeals.values())
    cid = request.args.get("claim_id")
    st = request.args.get("status")
    if cid is not None:
        items = [a for a in items if a["claim_id"] == cid]
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(a, APPEAL_FIELDS) for a in page], 200, meta)


@bp.get("/appeals/<appealId>")
def get_appeal(appealId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner", "HospitalStaff")
    return ok(public(get_appeal_or_404(appealId), APPEAL_FIELDS))


@bp.post("/appeals/<appealId>/request-records")
def request_records(appealId):
    require_roles("ClaimsAdjuster")
    a = get_appeal_or_404(appealId)
    if a["status"] != "OPEN":
        fail(core.ERR_INVALID_STATE, 409, "Appeal is not OPEN")
    a["status"] = "RECORDS_REQUESTED"
    due = store.clock + timedelta(days=logic.RECORDS_WINDOW_DAYS)
    a["records_due_at"] = core.fmt_ts(due)
    a["_records_due_dt"] = due
    touch(a)
    return ok(public(a, APPEAL_FIELDS))


@bp.post("/appeals/<appealId>/submit-records")
def submit_records(appealId):
    require_roles("HospitalStaff")
    a = get_appeal_or_404(appealId)
    data = body()
    ids = req_field(data, "medical_record_ids")
    if not isinstance(ids, list):
        fail(core.ERR_INVALID_REQUEST, 400, "medical_record_ids must be an array")
    c = store.claims.get(a["claim_id"])
    # Referential checks first (priority 8 in scaffold)
    for rid in ids:
        r = store.records.get(rid) if isinstance(rid, str) else None
        if r is None or c is None or r["policy_id"] != c["policy_id"]:
            fail("ERR_RECORD_NOT_FOUND", 404,
                 "A medical record does not exist or does not belong to the claim's policy")
        if r.get("appeal_id"):
            fail("ERR_RECORD_ALREADY_ATTACHED", 409,
                 "A medical record is already attached to another appeal")
    if a["status"] != "RECORDS_REQUESTED":
        fail(core.ERR_INVALID_STATE, 409, "Appeal is not RECORDS_REQUESTED")
    due = a.get("_records_due_dt")
    if due is not None and store.clock > due:
        fail("ERR_APPEAL_WINDOW_EXPIRED", 409, "Records window has expired")
    for rid in ids:
        store.records[rid]["appeal_id"] = a["id"]
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return ok(public(a, APPEAL_FIELDS))


@bp.post("/appeals/<appealId>/resolve")
def resolve_appeal(appealId):
    uid, _ = require_roles("ClaimsAdjuster")
    a = get_appeal_or_404(appealId)
    data = body()
    outcome = req_str(data, "outcome")
    if outcome not in ("UPHELD", "OVERTURNED"):
        fail(core.ERR_INVALID_REQUEST, 400, "outcome must be UPHELD or OVERTURNED")
    note = req_str(data, "resolution_note")
    if a["status"] not in ("OPEN", "UNDER_REVIEW"):
        fail("ERR_APPEAL_NOT_RESOLVABLE", 409,
             "Appeal must be OPEN or UNDER_REVIEW to resolve")
    if outcome == "UPHELD":
        a["status"] = "UPHELD"
        a["resolution_note"] = note
        touch(a)
        return ok(public(a, APPEAL_FIELDS))
    # OVERTURNED: segregation of duties
    if a.get("original_adjuster_id") is not None and uid == a["original_adjuster_id"]:
        fail("ERR_SELF_RESOLUTION_FORBIDDEN", 403,
             "The resolving adjuster must differ from the original adjuster")
    a["status"] = "OVERTURNED"
    a["resolution_note"] = note
    touch(a)
    c = store.claims.get(a["claim_id"])
    if c is not None:
        logic.sweep_claim(c)
        if c["status"] in ("SETTLED", "DENIED"):
            logic.overturn_cascade(c)
    return ok(public(a, APPEAL_FIELDS))


@bp.get("/appeals/<appealId>/medical-records")
def list_appeal_records(appealId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    a = get_appeal_or_404(appealId)
    items = [r for r in store.records.values() if r.get("appeal_id") == a["id"]]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, RECORD_FIELDS) for r in page], 200, meta)


# ---------------------------------------------------------------------------
# Policy conditions / claim lines (read paths)
# ---------------------------------------------------------------------------


@bp.get("/policies/<policyId>/conditions")
def list_policy_conditions(policyId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner")
    p = get_policy_or_404(policyId)
    items = [c for c in store.conditions.values() if c["policy_id"] == p["id"]]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(c, CONDITION_FIELDS) for c in page], 200, meta)


@bp.get("/policy-conditions/<conditionId>")
def get_condition(conditionId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner")
    return ok(public(get_condition_or_404(conditionId), CONDITION_FIELDS))


@bp.get("/policy-conditions")
def list_conditions():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner")
    items = list(store.conditions.values())
    pid = request.args.get("policy_id")
    cc = request.args.get("condition_code")
    if pid is not None:
        items = [c for c in items if c["policy_id"] == pid]
    if cc is not None:
        items = [c for c in items if c["condition_code"] == cc]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(c, CONDITION_FIELDS) for c in page], 200, meta)


@bp.get("/claim-lines/<lineId>")
def get_line(lineId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    return ok(public(get_line_or_404(lineId), LINE_FIELDS))


@bp.get("/claim-lines")
def list_lines():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff", "PetOwner")
    items = list(store.lines.values())
    cid = request.args.get("claim_id")
    pcid = request.args.get("policy_condition_id")
    if cid is not None:
        items = [l for l in items if l["claim_id"] == cid]
    if pcid is not None:
        items = [l for l in items if l["policy_condition_id"] == pcid]
    items = sorted(items, key=lambda l: (l.get("created_at") or "", l.get("_seq", 0), l.get("seq", 0)))
    page, meta = paginate(items)
    return ok([public(l, LINE_FIELDS) for l in page], 200, meta)


# ---------------------------------------------------------------------------
# Reconciliation reports
# ---------------------------------------------------------------------------


@bp.post("/hospitals/<hospitalId>/reconciliation-reports")
def create_report(hospitalId):
    require_roles("PlatformAdmin")
    h = get_hospital_or_404(hospitalId)
    data = body()
    ps = core.parse_date(req_field(data, "period_start"))
    pe = core.parse_date(req_field(data, "period_end"))
    if ps is None or pe is None:
        fail(core.ERR_INVALID_REQUEST, 400, "period_start/period_end must be ISO dates")
    start_dt = core.midnight(ps)
    end_dt = core.midnight(pe)
    in_window = []
    for p in store.payments.values():
        if p["hospital_id"] != h["id"]:
            continue
        if p["ledger_status"] != "POSTED":
            continue
        pdt = core.parse_dt(p["created_at"])
        if pdt is not None and start_dt <= pdt < end_dt:
            in_window.append(p)
    expected = sum(p["amount_cents"] for p in in_window)
    replay = sorted(in_window, key=lambda p: (p["created_at"], p["_seq"]))
    actual = sum(p["amount_cents"] for p in replay)
    r = {
        "id": core.new_id(),
        "created_at": now_iso(),
        "_seq": core.tick(),
        "hospital_id": h["id"],
        "period_start": ps.isoformat(),
        "period_end": pe.isoformat(),
        "expected_cents": expected,
        "actual_cents": actual,
        "discrepancy_cents": expected - actual,
        "status": "GENERATED",
    }
    store.reports[r["id"]] = r
    return ok(public(r, REPORT_FIELDS), 201)


@bp.get("/hospitals/<hospitalId>/reconciliation-reports")
def list_hospital_reports(hospitalId):
    require_roles("PlatformAdmin", "ClaimsAdjuster")
    h = get_hospital_or_404(hospitalId)
    items = [r for r in store.reports.values() if r["hospital_id"] == h["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, REPORT_FIELDS) for r in page], 200, meta)


@bp.get("/reconciliation-reports/<reportId>")
def get_report(reportId):
    require_roles("PlatformAdmin", "ClaimsAdjuster")
    return ok(public(get_report_or_404(reportId), REPORT_FIELDS))


@bp.get("/reconciliation-reports")
def list_reports():
    require_roles("PlatformAdmin", "ClaimsAdjuster")
    items = list(store.reports.values())
    hid = request.args.get("hospital_id")
    st = request.args.get("status")
    if hid is not None:
        items = [r for r in items if r["hospital_id"] == hid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, REPORT_FIELDS) for r in page], 200, meta)


@bp.post("/reconciliation-reports/<reportId>/acknowledge")
def acknowledge_report(reportId):
    require_roles("PlatformAdmin")
    r = get_report_or_404(reportId)
    if r["status"] != "GENERATED":
        fail(core.ERR_INVALID_STATE, 409, "Report is not GENERATED")
    r["status"] = "ACKNOWLEDGED"
    return ok(public(r, REPORT_FIELDS))


@bp.post("/reconciliation-reports/<reportId>/dispute")
def dispute_report(reportId):
    require_roles("HospitalStaff")
    r = get_report_or_404(reportId)
    if r["status"] != "GENERATED":
        fail(core.ERR_INVALID_STATE, 409, "Report is not GENERATED")
    r["status"] = "DISPUTED"
    return ok(public(r, REPORT_FIELDS))
