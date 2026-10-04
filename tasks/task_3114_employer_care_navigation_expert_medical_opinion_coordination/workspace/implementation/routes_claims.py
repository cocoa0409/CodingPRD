"""Routes: claims, billing cases, plan authorizations, cost-share estimate, utilization report."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_dt
from errors import fail
from common import (envelope, paginate, body, auth, require_role,
                    check_member_scope, active_consent, touch,
                    cascade_auth_denied, cascade_auth_approved)
from helpers import new_entity, get_or_404, req_str, req_int, req_enum
from calcs import claim_repricing, deductible_application, cost_share_estimate

bp = Blueprint("claims", __name__)


# ---- claims --------------------------------------------------------------------

@bp.post("/care/claims")
def create_claim():
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlanAdministrator"})
    data = body()
    member_id = req_str(data, "member_id")
    provider_id = req_str(data, "provider_id")
    service_date = req_str(data, "service_date")
    billed = req_int(data, "billed_amount_cents")
    allowed = req_int(data, "allowed_amount_cents")
    lines = data.get("lines")
    if not isinstance(lines, list):
        fail("ERR_INVALID_REQUEST", "lines must be an array")
    for line in lines:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "each line must be an object")
        if not isinstance(line.get("line_code"), str):
            fail("ERR_INVALID_REQUEST", "line.line_code is required")
        if isinstance(line.get("billed_cents"), bool) or not isinstance(line.get("billed_cents"), int):
            fail("ERR_INVALID_REQUEST", "line.billed_cents must be an integer")
        if isinstance(line.get("schedule_rate"), bool) or not isinstance(line.get("schedule_rate"), (int, float)):
            fail("ERR_INVALID_REQUEST", "line.schedule_rate must be a number")
        if line.get("error_flag") not in ("NONE", "DUPLICATE", "UPCODING"):
            fail("ERR_INVALID_REQUEST", "line.error_flag must be NONE, DUPLICATE, or UPCODING")
    get_or_404(db.members, member_id, "member")
    get_or_404(db.providers, provider_id, "provider")
    error_line_count = sum(1 for l in lines if l["error_flag"] != "NONE")
    claim = new_entity({
        "member_id": member_id,
        "provider_id": provider_id,
        "service_date": service_date,
        "billed_amount_cents": billed,
        "allowed_amount_cents": allowed,
        "lines": lines,
        "repriced_total_cents": None,
        "error_line_count": error_line_count,
        "deductible_applied_cents": None,
        "member_responsibility_cents": None,
        "status": "RECEIVED",
    })
    db.claims[claim["id"]] = claim
    return envelope(claim, status=201)


@bp.get("/care/claims/<cid>")
def get_claim(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "PlanAdministrator", "BillingAdvocate", "Member"})
    claim = get_or_404(db.claims, cid, "claim")
    check_member_scope(claim["member_id"], user_id, role)
    return envelope(claim)


@bp.get("/care/claims")
def list_claims():
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "PlanAdministrator", "BillingAdvocate"})
    items = list(db.claims.values())
    pid = request.args.get("provider_id")
    if pid is not None:
        items = [c for c in items if c["provider_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/members/<mid>/claims")
def list_member_claims(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "PlanAdministrator", "BillingAdvocate", "Member"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [c for c in db.claims.values() if c["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlanAdministrator"})
    claim = get_or_404(db.claims, cid, "claim")
    if claim["status"] != "RECEIVED":
        fail("ERR_CLAIM_ALREADY_ADJUDICATED", "claim is not RECEIVED")
    member = db.members[claim["member_id"]]
    # step 1: repricing
    claim["repriced_total_cents"] = claim_repricing(claim["lines"])
    # step 2: deductible application
    ded_applied, member_resp = deductible_application(member, claim["allowed_amount_cents"])
    claim["deductible_applied_cents"] = ded_applied
    claim["member_responsibility_cents"] = member_resp
    claim["status"] = "ADJUDICATED"
    touch(claim)
    member["deductible_used_cents"] += ded_applied
    member["oop_used_cents"] += member_resp
    touch(member)
    return envelope(claim)


@bp.post("/care/claims/<cid>/void")
def void_claim(cid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlanAdministrator"})
    claim = get_or_404(db.claims, cid, "claim")
    if claim["status"] != "ADJUDICATED":
        fail("ERR_INVALID_STATE", "claim is not ADJUDICATED")
    member = db.members[claim["member_id"]]
    member["deductible_used_cents"] -= claim["deductible_applied_cents"]
    member["oop_used_cents"] -= claim["member_responsibility_cents"]
    claim["status"] = "VOID"
    touch(claim)
    touch(member)
    for bc in list(db.billing_cases.values()):
        if bc["claim_id"] == cid and bc["status"] in ("OPENED", "ERROR_IDENTIFIED", "NEGOTIATING", "SETTLEMENT_PROPOSED"):
            bc["status"] = "VOIDED"
            bc["provisional_savings_cents"] = None
            bc["final_savings_cents"] = None
            touch(bc)
    return envelope(claim)


# ---- billing cases ---------------------------------------------------------------

def _billing_case(bid):
    return get_or_404(db.billing_cases, bid, "billing case")


@bp.post("/care/members/<mid>/billing-cases")
def create_billing_case(mid):
    user_id, role = auth()
    require_role(role, {"BillingAdvocate"})
    data = body()
    claim_id = req_str(data, "claim_id")
    m = get_or_404(db.members, mid, "member")
    claim = db.claims.get(claim_id)
    if claim is None:
        fail("ERR_NOT_FOUND", "claim not found")
    if claim["member_id"] != mid:
        fail("ERR_NOT_FOUND", "claim does not belong to this member")
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    if active_consent(mid, "BILLING_ADVOCACY") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE BILLING_ADVOCACY consent")
    bc = new_entity({
        "member_id": mid,
        "claim_id": claim_id,
        "status": "OPENED",
        "provisional_savings_cents": None,
        "counter_offer_cents": None,
        "settled_amount_cents": None,
        "final_savings_cents": None,
        "proposal_count": 0,
    })
    db.billing_cases[bc["id"]] = bc
    return envelope(bc, status=201)


@bp.get("/care/billing-cases/<bid>")
def get_billing_case(bid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "BillingAdvocate", "Member"})
    bc = _billing_case(bid)
    check_member_scope(bc["member_id"], user_id, role)
    return envelope(bc)


@bp.get("/care/members/<mid>/billing-cases")
def list_member_billing_cases(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "BillingAdvocate", "Member"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [b for b in db.billing_cases.values() if b["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    items.sort(key=lambda b: b["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/claims/<cid>/billing-cases")
def list_claim_billing_cases(cid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "BillingAdvocate"})
    get_or_404(db.claims, cid, "claim")
    items = [b for b in db.billing_cases.values() if b["claim_id"] == cid]
    items.sort(key=lambda b: b["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/billing-cases/<bid>/identify-errors")
def identify_errors(bid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"BillingAdvocate"})
    bc = _billing_case(bid)
    if bc["status"] != "OPENED":
        fail("ERR_INVALID_STATE", "billing case is not OPENED")
    claim = db.claims[bc["claim_id"]]
    if claim["status"] != "ADJUDICATED":
        fail("ERR_CLAIM_NOT_ADJUDICATED", "linked claim is not ADJUDICATED")
    if claim["error_line_count"] < 1:
        fail("ERR_NO_LINE_ERRORS", "claim has no error-flagged lines")
    bc["provisional_savings_cents"] = claim["billed_amount_cents"] - claim["repriced_total_cents"]
    bc["status"] = "ERROR_IDENTIFIED"
    touch(bc)
    return envelope(bc)


@bp.post("/care/billing-cases/<bid>/propose-settlement")
def propose_settlement(bid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"BillingAdvocate"})
    data = body()
    offer = data.get("counter_offer_cents")
    if offer is None or isinstance(offer, bool) or not isinstance(offer, int):
        fail("ERR_INVALID_REQUEST", "counter_offer_cents is required")
    bc = _billing_case(bid)
    if bc["status"] not in ("ERROR_IDENTIFIED", "NEGOTIATING"):
        fail("ERR_INVALID_STATE", "billing case is not ERROR_IDENTIFIED or NEGOTIATING")
    claim = db.claims[bc["claim_id"]]
    if bc["proposal_count"] >= 3:
        fail("ERR_NEGOTIATION_ROUND_EXCEEDED", "proposal cap of 3 reached")
    if offer >= claim["billed_amount_cents"]:
        fail("ERR_SETTLEMENT_EXCEEDS_BILLED", "counter offer must be below billed amount")
    bc["counter_offer_cents"] = offer
    bc["proposal_count"] += 1
    bc["status"] = "SETTLEMENT_PROPOSED"
    touch(bc)
    return envelope(bc)


@bp.post("/care/billing-cases/<bid>/accept-settlement")
def accept_settlement(bid):
    user_id, role = auth()
    require_role(role, {"Member"})
    bc = _billing_case(bid)
    check_member_scope(bc["member_id"], user_id, role)
    if bc["status"] != "SETTLEMENT_PROPOSED":
        fail("ERR_INVALID_STATE", "billing case is not SETTLEMENT_PROPOSED")
    claim = db.claims[bc["claim_id"]]
    bc["settled_amount_cents"] = bc["counter_offer_cents"]
    bc["final_savings_cents"] = claim["billed_amount_cents"] - bc["settled_amount_cents"]
    bc["status"] = "RESOLVED_ACCEPTED"
    touch(bc)
    return envelope(bc)


@bp.post("/care/billing-cases/<bid>/reject-settlement")
def reject_settlement(bid):
    user_id, role = auth()
    require_role(role, {"Member"})
    bc = _billing_case(bid)
    check_member_scope(bc["member_id"], user_id, role)
    if bc["status"] != "SETTLEMENT_PROPOSED":
        fail("ERR_INVALID_STATE", "billing case is not SETTLEMENT_PROPOSED")
    bc["status"] = "NEGOTIATING"
    touch(bc)
    return envelope(bc)


@bp.post("/care/billing-cases/<bid>/abandon")
def abandon_billing_case(bid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"BillingAdvocate"})
    bc = _billing_case(bid)
    if bc["status"] != "NEGOTIATING":
        fail("ERR_INVALID_STATE", "billing case is not NEGOTIATING")
    bc["status"] = "RESOLVED_NO_CHANGE"
    bc["final_savings_cents"] = 0
    touch(bc)
    return envelope(bc)


@bp.post("/care/billing-cases/<bid>/close")
def close_billing_case(bid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"BillingAdvocate"})
    bc = _billing_case(bid)
    if bc["status"] not in ("RESOLVED_ACCEPTED", "RESOLVED_NO_CHANGE"):
        fail("ERR_INVALID_STATE", "billing case is not resolved")
    bc["status"] = "CLOSED"
    touch(bc)
    return envelope(bc)


# ---- plan authorizations -----------------------------------------------------------

def _authorization(aid):
    return get_or_404(db.authorizations, aid, "authorization")


@bp.post("/care/members/<mid>/authorizations")
def create_authorization(mid):
    user_id, role = auth()
    require_role(role, {"Member", "NurseNavigator"})
    data = body()
    service_code = req_enum(data, "service_code", {"EXPERT_MEDICAL_OPINION", "PROCEDURE", "IMAGING"})
    units = data.get("units")
    if units is None or isinstance(units, bool) or not isinstance(units, int) or units < 1:
        fail("ERR_INVALID_REQUEST", "units must be an integer >= 1")
    m = get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    for a in db.authorizations.values():
        if a["member_id"] == mid and a["service_code"] == service_code and a["status"] in ("REQUESTED", "APPEALED"):
            fail("ERR_DUPLICATE_AUTHORIZATION", "non-terminal authorization already exists for this service code")
    a = new_entity({
        "member_id": mid,
        "service_code": service_code,
        "units": units,
        "status": "REQUESTED",
        "denial_reason": None,
        "decided_at": None,
    })
    db.authorizations[a["id"]] = a
    return envelope(a, status=201)


@bp.get("/care/authorizations/<aid>")
def get_authorization(aid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "PlanAdministrator", "Member", "NurseNavigator"})
    a = _authorization(aid)
    check_member_scope(a["member_id"], user_id, role)
    return envelope(a)


@bp.get("/care/members/<mid>/authorizations")
def list_member_authorizations(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "PlanAdministrator", "Member", "NurseNavigator"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [a for a in db.authorizations.values() if a["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/authorizations/<aid>/approve")
def approve_authorization(aid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlanAdministrator"})
    a = _authorization(aid)
    if a["status"] not in ("REQUESTED", "APPEALED"):
        fail("ERR_INVALID_STATE", "authorization is not REQUESTED or APPEALED")
    from common import clock_iso
    a["status"] = "APPROVED"
    a["decided_at"] = clock_iso()
    touch(a)
    if a["service_code"] == "EXPERT_MEDICAL_OPINION":
        cascade_auth_approved(a["member_id"])
    return envelope(a)


@bp.post("/care/authorizations/<aid>/deny")
def deny_authorization(aid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlanAdministrator"})
    data = body()
    reason = req_str(data, "denial_reason")
    a = _authorization(aid)
    if a["status"] not in ("REQUESTED", "APPEALED"):
        fail("ERR_INVALID_STATE", "authorization is not REQUESTED or APPEALED")
    from common import clock_iso
    a["denial_reason"] = reason
    a["decided_at"] = clock_iso()
    if a["status"] == "REQUESTED":
        a["status"] = "DENIED"
    else:
        a["status"] = "DENIED_FINAL"
    touch(a)
    if a["service_code"] == "EXPERT_MEDICAL_OPINION":
        cascade_auth_denied(a["member_id"])
    return envelope(a)


@bp.post("/care/authorizations/<aid>/appeal")
def appeal_authorization(aid):
    user_id, role = auth()
    require_role(role, {"Member"})
    a = _authorization(aid)
    check_member_scope(a["member_id"], user_id, role)
    if a["status"] != "DENIED":
        fail("ERR_INVALID_STATE", "authorization is not DENIED")
    deadline = _parse_dt(a["decided_at"]) + timedelta(days=30)
    if db.clock > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "appeal window has closed")
    a["status"] = "APPEALED"
    touch(a)
    return envelope(a)


# ---- computed reads -----------------------------------------------------------------

@bp.get("/care/members/<mid>/cost-share-estimate")
def get_cost_share_estimate(mid):
    user_id, role = auth()
    require_role(role, {"Member", "CareAdvocate", "NurseNavigator", "PlanAdministrator"})
    provider_id = request.args.get("provider_id")
    if not provider_id:
        fail("ERR_INVALID_REQUEST", "provider_id query parameter is required")
    raw = request.args.get("allowed_amount_cents")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "allowed_amount_cents query parameter is required")
    try:
        allowed = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "allowed_amount_cents must be an integer")
    m = get_or_404(db.members, mid, "member")
    provider = get_or_404(db.providers, provider_id, "provider")
    check_member_scope(mid, user_id, role)
    resp, ded, coins, capped = cost_share_estimate(m, provider, allowed)
    return envelope({
        "member_responsibility_cents": resp,
        "deductible_portion_cents": ded,
        "coinsurance_portion_cents": coins,
        "oop_capped": capped,
    })


@bp.get("/care/employers/<eid>/utilization-report")
def utilization_report(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"EmployerAdmin", "PlatformAdmin"})
    employer = get_or_404(db.employers, eid, "employer")
    member_ids = {m["id"] for m in db.members.values() if m["employer_id"] == eid}
    members_active = sum(1 for m in db.members.values()
                         if m["employer_id"] == eid and m["eligibility_status"] == "ACTIVE")
    nav_cases = [c for c in db.navigation_cases.values() if c["member_id"] in member_ids]
    nav_total = len(nav_cases)
    nav_closed = sum(1 for c in nav_cases if c["status"] == "CLOSED")
    emos_delivered = sum(1 for o in db.expert_opinions.values()
                         if o["member_id"] in member_ids and o["status"] == "DELIVERED")
    prov_total = 0
    final_total = 0
    for bc in db.billing_cases.values():
        if bc["member_id"] not in member_ids:
            continue
        claim = db.claims.get(bc["claim_id"])
        claim_void = claim is not None and claim["status"] == "VOID"
        if bc["status"] in ("ERROR_IDENTIFIED", "NEGOTIATING", "SETTLEMENT_PROPOSED",
                            "RESOLVED_ACCEPTED", "CLOSED") and not claim_void:
            prov_total += bc["provisional_savings_cents"] or 0
        if bc["status"] in ("RESOLVED_ACCEPTED", "CLOSED"):
            final_total += bc["final_savings_cents"] or 0
    delta = employer["avg_in_out_cost_delta_cents"]
    base_count = 0
    redirected_count = 0
    for a in db.appointments.values():
        if a["member_id"] not in member_ids:
            continue
        if a["status"] not in ("BOOKED", "COMPLETED"):
            continue
        if a.get("navigation_case_id") is None:
            continue
        provider = db.providers.get(a["provider_id"])
        if provider is None or provider["network_status"] != "IN_NETWORK":
            continue
        base_count += 1
        if a.get("redirected_from_out_of_network"):
            redirected_count += 1
    naive = base_count * delta
    counter = redirected_count * delta
    return envelope({
        "members_active": members_active,
        "navigation_cases_total": nav_total,
        "navigation_cases_closed": nav_closed,
        "emos_delivered": emos_delivered,
        "billing_savings_provisional_cents": prov_total,
        "billing_savings_final_cents": final_total,
        "steerage_naive_cents": naive,
        "steerage_counterfactual_cents": counter,
        "total_attributed_savings_cents": final_total + counter,
    })
