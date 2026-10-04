"""Policy routes: get, cancel, renew, non-renewal notices, endorsements, certificates."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
from services import underwriting as uw
from services import policy_ops as pops
from services import serialize as ser
from services import audit as aud

bp = Blueprint("policies", __name__)

STATUTORY_MIN_DAYS = {
    "APPETITE_CHANGE": 45,
    "CARRIER_WITHDRAWAL": 60,
    "RISK_ESCALATION": 30,
}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def _get_policy_scoped(actor, pid):
    p = db.policies.get(pid)
    if p is None:
        raise errors.not_found("Policy not found")
    if actor.role == "Policyholder" and actor.user_id != p["business_account_id"]:
        raise errors.not_found("Policy not found")
    return p


def _reconcile(p):
    p["earned_premium_cents"] = pops.earned_premium(p)


@bp.get("/ins/policies/<pid>")
def get_policy(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform",
                    "ComplianceOfficer", "ClaimsAdjuster", "FinanceOfficer")
    p = _get_policy_scoped(actor, pid)
    _reconcile(p)
    return resp.ok_object(ser.public(p))


@bp.post("/ins/policies/<pid>/cancel")
def cancel_policy(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder")
    p = _get_policy_scoped(actor, pid)
    if actor.user_id != p["business_account_id"]:
        raise errors.not_found("Policy not found")
    if p["status"] not in ("BOUND", "ACTIVE"):
        raise errors.invalid_state("Policy is not BOUND or ACTIVE")
    pops.recompute_open_claims(p)
    if p["open_claim_count"] > 0:
        raise errors.open_claims_block()

    now = db.clock_now()
    term_end = db.parse_iso(p["term_end"])
    rem = pops.remaining_days(now, term_end)
    if rem < 0:
        rem = 0
    credit = pops.cancellation_credit(p["base_annual_premium_cents"], rem, p["term_day_count"])

    acct = db.business_accounts[p["business_account_id"]]
    before_p = ser.public(p)
    acct["account_credit_cents"] = max(0, acct["account_credit_cents"] + credit)
    acct["updated_at"] = db.fmt_iso(now)
    acct["version"] += 1

    p["status"] = "CANCELLED"
    p["cancelled_at"] = db.fmt_iso(now)
    p["updated_at"] = db.fmt_iso(now)
    p["version"] += 1

    # cascade: certificates ISSUED -> VOIDED; DRAFT endorsements -> VOID
    for c in db.certificates.values():
        if c["policy_id"] == p["id"] and c["status"] == "ISSUED":
            c["status"] = "VOIDED"
            aud.record(actor.role, actor.user_id, "Certificate", c["id"], "voided",
                       before={"status": "ISSUED"}, after={"status": "VOIDED"})
    for e in db.endorsements.values():
        if e["policy_id"] == p["id"] and e["status"] == "DRAFT":
            e["status"] = "VOID"
            e["updated_at"] = db.fmt_iso(now)
            e["version"] += 1
            aud.record(actor.role, actor.user_id, "Endorsement", e["id"], "void",
                       before={"status": "DRAFT"}, after={"status": "VOID"})

    aud.record(actor.role, actor.user_id, "Policy", p["id"], "cancel",
               before=before_p, after=ser.public(p))
    _reconcile(p)
    return resp.ok_object(ser.public(p))


@bp.post("/ins/policies/<pid>/renew")
def renew_policy(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder")
    p = _get_policy_scoped(actor, pid)
    body = _body()
    errors.reject_unknown_keys(body, ("expected_policy_version",))
    expected = body.get("expected_policy_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_policy_version is required")

    # The notice gate must be reachable: a policy that already carries a
    # notice is NON_RENEWAL_PENDING, so check it before the ACTIVE state gate
    # (PRD §3.6 names ERR_RENEWAL_NOTICE_ISSUED for exactly this case).
    if p["non_renewal_notice_sent_at"] is not None:
        raise errors.renewal_notice_issued()
    if p["status"] != "ACTIVE":
        raise errors.invalid_state("Policy is not ACTIVE")
    now = db.clock_now()
    rws = db.parse_iso(p["renewal_window_start"])
    te = db.parse_iso(p["term_end"])
    if not (rws <= now < te):
        raise errors.renewal_window()
    cls = db.class_codes.get(p["class_code_id"])
    if cls is None or not cls["appetite_active"]:
        raise errors.appetite_inactive()
    pops.recompute_open_claims(p)
    if p["open_claim_count"] > 0:
        raise errors.open_claims_block()
    if expected != p["version"]:
        raise errors.stale_policy_version()
    if actor.user_id != p["business_account_id"]:
        raise errors.not_found("Policy not found")

    acct = db.business_accounts[p["business_account_id"]]
    quote = db.quotes.get(p["quote_id"])
    lines = pops.policy_in_force_lines(p)
    uplift = any(e["endorsement_type"] == "COVERAGE_ADJUST" and e["status"] == "EFFECTIVE"
                 and (e.get("new_exposure_units") or 0) > (quote["exposure_units"] if quote else 0)
                 for e in pops.effective_endorsements(p["id"]))
    renewal_premium = uw.premium_cents(cls, lines, p["exposure_units"],
                                       acct["claims_free_flag"], variant="final",
                                       exposure_uplift=uplift)

    # consume account credit against renewal premium
    consumed = min(acct["account_credit_cents"], renewal_premium)
    acct["account_credit_cents"] = max(0, acct["account_credit_cents"] - consumed)
    acct["updated_at"] = db.fmt_iso(now)
    acct["version"] += 1

    successor = {
        "id": db.new_id(),
        "quote_id": p["quote_id"],
        "business_account_id": p["business_account_id"],
        "class_code_id": p["class_code_id"],
        "term_start": db.fmt_iso(te),
        "term_end": db.fmt_iso(te + timedelta(days=365)),
        "term_day_count": 365,
        "exposure_units": p["exposure_units"],
        "base_annual_premium_cents": renewal_premium,
        "earned_premium_cents": 0,
        "open_claim_count": 0,
        "renewal_window_start": db.fmt_iso(te + timedelta(days=365) - timedelta(days=120)),
        "non_renewal_notice_sent_at": None,
        "status": "BOUND",
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.policies[successor["id"]] = successor

    before_p = ser.public(p)
    p["status"] = "RENEWED"
    p["updated_at"] = db.fmt_iso(now)
    p["version"] += 1

    aud.record(actor.role, actor.user_id, "Policy", p["id"], "renew",
               before=before_p, after=ser.public(p))
    aud.record(actor.role, actor.user_id, "Policy", successor["id"], "create",
               after=ser.public(successor))
    return resp.ok_object(ser.public(successor), status=201)


@bp.post("/ins/policies/<pid>/non-renewal-notices")
def issue_non_renewal(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "ComplianceOfficer")
    p = _get_policy_scoped(actor, pid)
    body = _body()
    errors.reject_unknown_keys(body, ("reason_code",))
    reason = body.get("reason_code")
    if reason not in STATUTORY_MIN_DAYS:
        raise errors.validation("reason_code invalid")

    # A second notice is ERR_NONRENEWAL_DUPLICATE even though the first notice
    # moved the policy out of ACTIVE (PRD §3.6 names the duplicate error
    # explicitly; it must pre-empt the generic state gate).
    if p["non_renewal_notice_sent_at"] is not None:
        raise errors.nonrenewal_duplicate()
    if p["status"] != "ACTIVE":
        raise errors.invalid_state("Policy is not ACTIVE")
    now = db.clock_now()
    rws = db.parse_iso(p["renewal_window_start"])
    if now < rws:
        raise errors.renewal_window()
    te = db.parse_iso(p["term_end"])
    days_left = db.day_of(te) - db.day_of(now)
    if days_left < STATUTORY_MIN_DAYS[reason]:
        raise errors.nonrenewal_statute()

    notice = {
        "id": db.new_id(),
        "policy_id": p["id"],
        "reason_code": reason,
        "sent_at": db.fmt_iso(now),
        "days_before_term_end": days_left,
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.non_renewal_notices[notice["id"]] = notice
    before_p = ser.public(p)
    p["non_renewal_notice_sent_at"] = notice["sent_at"]
    p["status"] = "NON_RENEWAL_PENDING"
    p["updated_at"] = db.fmt_iso(now)
    p["version"] += 1
    aud.record(actor.role, actor.user_id, "NonRenewalNotice", notice["id"], "issue",
               after=ser.public(notice))
    aud.record(actor.role, actor.user_id, "Policy", p["id"], "non_renewal_pending",
               before=before_p, after=ser.public(p))
    return resp.ok_object(ser.public(notice), status=201)


@bp.get("/ins/policies/<pid>/non-renewal-notices")
def list_non_renewals(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "ComplianceOfficer", "Policyholder")
    _get_policy_scoped(actor, pid)
    items = [n for n in db.non_renewal_notices.values() if n["policy_id"] == pid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/policies/<pid>/endorsements")
def list_endorsements(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform", "Underwriter")
    _get_policy_scoped(actor, pid)
    items = [e for e in db.endorsements.values() if e["policy_id"] == pid]
    status = request.args.get("status")
    etype = request.args.get("endorsement_type")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if etype is not None:
        items = [e for e in items if e["endorsement_type"] == etype]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/policies/<pid>/endorsements")
def create_endorsement(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder", "Agent")
    p = _get_policy_scoped(actor, pid)
    body = _body()
    errors.reject_unknown_keys(body, (
        "endorsement_type", "effective_at", "expected_policy_version",
        "new_exposure_units", "added_lines", "removed_lines", "ai_holder_name",
    ))
    etype = body.get("endorsement_type")
    effective_at = body.get("effective_at")
    expected = body.get("expected_policy_version")
    new_exposure = body.get("new_exposure_units")
    added = body.get("added_lines") or []
    removed = body.get("removed_lines") or []
    ai_holder = body.get("ai_holder_name")

    if etype not in ("COVERAGE_ADJUST", "ADDITIONAL_INSURED", "LIMIT_CHANGE", "CLASS_RECODE"):
        raise errors.validation("endorsement_type invalid")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_policy_version is required")
    if not isinstance(added, list) or not isinstance(removed, list):
        raise errors.validation("added_lines/removed_lines must be arrays")

    # state
    if p["status"] != "ACTIVE":
        raise errors.invalid_state("Policy is not ACTIVE")

    now = db.clock_now()
    # temporal window: effective_at in [term_start day 00:00Z, current clock day end]
    try:
        eff = db.parse_iso(effective_at)
    except (ValueError, TypeError):
        raise errors.validation("effective_at must be an ISO8601 string")
    term_start = db.parse_iso(p["term_start"])
    if eff < db.day_start(term_start) or eff > db.day_end(now):
        raise errors.endorsement_window()

    # shape constraints
    if etype == "COVERAGE_ADJUST":
        if not isinstance(new_exposure, int) or isinstance(new_exposure, bool):
            raise errors.validation("new_exposure_units is required for COVERAGE_ADJUST")
        if new_exposure < 0:
            raise errors.exposure_negative()
    if etype == "ADDITIONAL_INSURED":
        if not isinstance(ai_holder, str) or not ai_holder:
            raise errors.validation("ai_holder_name is required for ADDITIONAL_INSURED")

    cls = db.class_codes.get(p["class_code_id"])
    eligible = set(cls["eligible_lines"])
    in_force = set(pops.policy_in_force_lines(p))
    if any(l not in uw.ALL_LINES for l in added) or any(l not in uw.ALL_LINES for l in removed):
        raise errors.line_not_eligible()
    # intersecting add/remove sets are ERR_LINE_OVERLAP (PRD §3.5 names the
    # intersection case explicitly) — check before the in-force/eligibility
    # shape checks so the overlap surfaces deterministically.
    if set(added) & set(removed):
        raise errors.line_overlap()
    # re-adding an in-force line
    if any(l in in_force for l in added):
        raise errors.line_overlap()
    # added must be eligible for class; removed must be in force
    if any(l not in eligible for l in added):
        raise errors.line_not_eligible()
    if any(l not in in_force for l in removed):
        raise errors.line_not_eligible()
    resulting = (in_force | set(added)) - set(removed)
    if len(resulting) < 1:
        raise errors.last_line_removal()

    # OCC
    if expected != p["version"]:
        raise errors.stale_policy_version()

    # compute new annual premium (final variant) with endorsement applied
    acct = db.business_accounts[p["business_account_id"]]
    eff_exposure = new_exposure if etype == "COVERAGE_ADJUST" else p["exposure_units"]
    eff_lines = sorted(resulting)
    new_annual = None
    delta = 0
    if etype in ("COVERAGE_ADJUST", "LIMIT_CHANGE", "CLASS_RECODE") or added or removed:
        uplift = False
        if etype == "COVERAGE_ADJUST":
            quote = db.quotes.get(p["quote_id"])
            base_exposure = quote["exposure_units"] if quote else p["exposure_units"]
            # uplift applies if any EFFECTIVE COVERAGE_ADJUST (incl. this one) raised exposure
            raised = new_exposure > base_exposure
            prior_raised = any(
                e["endorsement_type"] == "COVERAGE_ADJUST" and e["status"] == "EFFECTIVE"
                and (e.get("new_exposure_units") or 0) > base_exposure
                for e in pops.effective_endorsements(p["id"]))
            uplift = raised or prior_raised
        new_annual = uw.premium_cents(cls, eff_lines, eff_exposure,
                                      acct["claims_free_flag"], variant="final",
                                      exposure_uplift=uplift)
        rem = pops.remaining_days(eff, db.parse_iso(p["term_end"]))
        if rem < 0:
            rem = 0
        delta = pops.midterm_delta(new_annual, p["base_annual_premium_cents"], rem,
                                   p["term_day_count"])

    rec = {
        "id": db.new_id(),
        "policy_id": p["id"],
        "endorsement_type": etype,
        "effective_at": db.fmt_iso(eff),
        "new_exposure_units": new_exposure if etype == "COVERAGE_ADJUST" else None,
        "added_lines": list(added),
        "removed_lines": list(removed),
        "ai_holder_name": ai_holder if etype == "ADDITIONAL_INSURED" else None,
        "premium_delta_cents": delta,
        "new_annual_premium_cents": new_annual,
        "status": "EFFECTIVE",
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.endorsements[rec["id"]] = rec

    if delta < 0:
        acct["account_credit_cents"] = max(0, acct["account_credit_cents"] + abs(delta))
        acct["updated_at"] = db.fmt_iso(now)
        acct["version"] += 1

    before_p = ser.public(p)
    if etype == "COVERAGE_ADJUST":
        p["exposure_units"] = new_exposure
    p["updated_at"] = db.fmt_iso(now)
    p["version"] += 1
    _reconcile(p)

    aud.record(actor.role, actor.user_id, "Endorsement", rec["id"], "effective",
               after=ser.public(rec))
    aud.record(actor.role, actor.user_id, "Policy", p["id"], "endorsed",
               before=before_p, after=ser.public(p))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/endorsements/<eid>")
def get_endorsement(eid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform", "Underwriter")
    e = db.endorsements.get(eid)
    if e is None:
        raise errors.not_found("Endorsement not found")
    p = db.policies.get(e["policy_id"])
    if actor.role == "Policyholder" and (p is None or actor.user_id != p["business_account_id"]):
        raise errors.not_found("Endorsement not found")
    return resp.ok_object(ser.public(e))


@bp.get("/ins/endorsements/<eid>/certificates")
def endorsement_certificates(eid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform")
    e = db.endorsements.get(eid)
    if e is None:
        raise errors.not_found("Endorsement not found")
    items = [c for c in db.certificates.values() if c["endorsement_id"] == eid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------
@bp.get("/ins/policies/<pid>/certificates")
def list_certificates(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform")
    _get_policy_scoped(actor, pid)
    items = [c for c in db.certificates.values() if c["policy_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/certificates")
def issue_certificate():
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder", "Agent", "PartnerPlatform")
    body = _body()
    errors.reject_unknown_keys(body, ("policy_id", "endorsement_id"))
    policy_id = body.get("policy_id")
    endorsement_id = body.get("endorsement_id")
    if not isinstance(policy_id, str) or not isinstance(endorsement_id, str):
        raise errors.validation("policy_id and endorsement_id are required")

    p = db.policies.get(policy_id)
    if p is None:
        raise errors.not_found("Policy not found")
    if actor.role == "Policyholder" and actor.user_id != p["business_account_id"]:
        raise errors.not_found("Policy not found")
    e = db.endorsements.get(endorsement_id)
    if (e is None or e["policy_id"] != policy_id
            or e["endorsement_type"] != "ADDITIONAL_INSURED"
            or e["status"] != "EFFECTIVE"):
        raise errors.cert_endorsement_invalid()

    # policy ordinal: zero-padded creation order within its account
    account_policies = sorted(
        [x for x in db.policies.values() if x["business_account_id"] == p["business_account_id"]],
        key=lambda x: (x["created_at"], x["_seq"]))
    ordinal = next(i + 1 for i, x in enumerate(account_policies) if x["id"] == p["id"])
    n = sum(1 for c in db.certificates.values() if c["policy_id"] == p["id"]) + 1
    cert_no = f"CERT-{ordinal:04d}-{n}"

    now = db.clock_now()
    rec = {
        "id": db.new_id(),
        "policy_id": policy_id,
        "endorsement_id": endorsement_id,
        "holder_name": e["ai_holder_name"],
        "issued_at": db.fmt_iso(now),
        "certificate_no": cert_no,
        "status": "ISSUED",
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.certificates[rec["id"]] = rec
    aud.record(actor.role, actor.user_id, "Certificate", rec["id"], "issue",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/certificates/<cid>")
def get_certificate(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform")
    c = db.certificates.get(cid)
    if c is None:
        raise errors.not_found("Certificate not found")
    p = db.policies.get(c["policy_id"])
    if actor.role == "Policyholder" and (p is None or actor.user_id != p["business_account_id"]):
        raise errors.not_found("Certificate not found")
    return resp.ok_object(ser.public(c))
