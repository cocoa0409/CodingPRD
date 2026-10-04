"""Claims: submission, adjudication, resubmission, recoupment (PRD section 3.7)."""
from flask import Blueprint, request

import constants as C
import db
import logical_clock
import response
import services
import validate as v
from errors import fail
from middleware import endpoint, require_owner

bp = Blueprint("claims", __name__)


def _validate_lines_shape(b):
    """Stage 4: service_lines present, non-empty, each line well-typed.
    Range rules (units >= 1, billed > 0) are stage-12 fiscal sanity."""
    lines = v.req_list(b, "service_lines", min_len=1)
    for line in lines:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "each service line must be an object")
        v.req_str(line, "service_code")
        v.req_enum(line, "service_category", C.SERVICE_CATEGORIES)
        v.req_int(line, "units")
        v.req_int(line, "unit_billed_cents")
    return lines


def _validate_lines_fiscal(lines):
    """Stage 12: units >= 1 and unit_billed_cents > 0 on every line."""
    for line in lines:
        if line["units"] < 1 or line["unit_billed_cents"] <= 0:
            fail("ERR_AMOUNT_INVALID",
                 "each line needs units >= 1 and unit_billed_cents > 0")


def _check_temporal_and_referential(auth, service_date):
    """Stages 9 and 11 shared by claim create and resubmit."""
    lag = (logical_clock.today() - service_date).days
    if lag > C.TIMELY_FILING_DAYS:
        fail("ERR_UNTIMELY_FILED",
             "service_date is more than %d days before the submission date"
             % C.TIMELY_FILING_DAYS)
    if not services.date_in_episode(auth, service_date):
        fail("ERR_SERVICE_DATE_OUTSIDE_EPISODE",
             "service_date is outside the half-open episode window")
    for appt in db.all_recs("appointments"):
        if (appt["referral_authorization_id"] == auth["id"]
                and appt["status"] == "COMPLETED"
                and logical_clock.parse_dt(appt["scheduled_start"]).date() == service_date):
            return
    fail("ERR_NO_MATCHING_COMPLETED_APPOINTMENT",
         "no COMPLETED appointment on this authorization matches service_date")


@bp.post("/community-care/claims")
@endpoint([C.ROLE_PROVIDER_REP])
def create_claim(user_id, role):
    b = v.body()
    auth = v.body_fk(b, "referral_authorization_id", "authorizations",
                     "referral authorization")
    service_date = v.req_date(b, "service_date")
    lines = _validate_lines_shape(b)
    auth_id = v.req_str(b, "referral_authorization_id")
    # stage 6: the caller submits as the authorization's provider
    require_owner(user_id, auth["provider_id"], "claim submission")
    # stage 7: lifecycle state gates
    if auth["status"] not in ("ACTIVE", "EXPIRED", "EXHAUSTED", "CLOSED"):
        fail("ERR_REFERRAL_NOT_ACTIVE",
             "authorization status %s cannot be billed" % auth["status"])
    tpa = db.get("tpas", auth["tpa_id"])
    if tpa is None or tpa["contract_status"] != "ACTIVE":
        fail("ERR_TPA_SUSPENDED", "the administering TPA is SUSPENDED")
    # stage 8: safety
    provider = db.get("providers", auth["provider_id"])
    if provider is None or provider["credentialing_status"] != "CREDENTIALED":
        fail("ERR_PROVIDER_NOT_CREDENTIALED", "provider is not CREDENTIALED")
    # stages 9 + 11
    _check_temporal_and_referential(auth, service_date)
    # stage 12
    _validate_lines_fiscal(lines)
    rec = db.create("claims", {
        "referral_authorization_id": auth_id,
        "provider_id": auth["provider_id"],
        "tpa_id": auth["tpa_id"],
        "service_date": service_date.isoformat(),
        "service_lines": lines,
        "billed_total_cents": services.billed_total(lines),
        "paid_amount_cents": None,
        "status": "RECEIVED",
        "denial_reason": None,
        "resubmit_count": 0,
        "reversed_reason": None,
        "submitted_at": logical_clock.now_iso(),
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/claims/<rid>")
@endpoint(C.ALL_ROLES)
def get_claim(user_id, role, rid):
    claim = v.path_entity("claims", rid, "claim")
    return response.ok(db.public(claim))


@bp.get("/community-care/claims")
@endpoint(C.ALL_ROLES)
def list_claims(user_id, role):
    preds = []
    for field in ("provider_id", "referral_authorization_id", "tpa_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            preds.append(lambda r, f=field, val=raw: r[f] == val)
    return response.list_response("claims", preds)


@bp.post("/community-care/claims/<rid>/adjudicate")
@endpoint([C.ROLE_TPA_ADMINISTRATOR])
def adjudicate_claim(user_id, role, rid):
    claim = v.path_entity("claims", rid, "claim")
    b = v.body()
    decision = v.req_enum(b, "decision", C.CLAIM_DECISIONS)
    denial_reason = v.opt_enum(b, "denial_reason", C.CLAIM_DENIAL_REASONS)
    if decision == "DENIED" and not (denial_reason or "").strip():
        fail("ERR_INVALID_REQUEST", "a DENIED decision requires a denial_reason")
    # stage 6: owning network
    require_owner(user_id, claim["tpa_id"], "claim adjudication")
    # stage 7: state
    if claim["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "only a RECEIVED claim can be adjudicated")
    # stage 8: safety
    provider = db.get("providers", claim["provider_id"])
    if provider is None or provider["credentialing_status"] != "CREDENTIALED":
        fail("ERR_PROVIDER_NOT_CREDENTIALED", "provider is not CREDENTIALED")
    tpa = db.get("tpas", claim["tpa_id"])
    if decision == "PAID":
        paid = services.price_claim_lines(claim["service_lines"], provider)
        claim["paid_amount_cents"] = paid
        claim["status"] = "PAID"
        db.touch(claim)
        provider["lifetime_paid_cents"] += paid
        provider["current_paid_cents"] += paid
        db.touch(provider)
        services.finalize_tpa_event(tpa, denied=False)
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        db.touch(claim)
        services.finalize_tpa_event(tpa, denied=True)
    return response.ok(db.public(claim))


@bp.post("/community-care/claims/<rid>/resubmit")
@endpoint([C.ROLE_PROVIDER_REP])
def resubmit_claim(user_id, role, rid):
    claim = v.path_entity("claims", rid, "claim")
    b = v.body()
    lines = _validate_lines_shape(b)
    # stage 6: own claims only
    require_owner(user_id, claim["provider_id"], "claim resubmission")
    # stage 7: state + network
    if claim["status"] != "DENIED":
        fail("ERR_INVALID_STATE", "only a DENIED claim can be resubmitted")
    tpa = db.get("tpas", claim["tpa_id"])
    if tpa is None or tpa["contract_status"] != "ACTIVE":
        fail("ERR_TPA_SUSPENDED", "the administering TPA is SUSPENDED")
    # stage 9: temporal rules re-validated at resubmission time
    auth = db.get("authorizations", claim["referral_authorization_id"])
    service_date = logical_clock.parse_date(claim["service_date"])
    if (logical_clock.today() - service_date).days > C.TIMELY_FILING_DAYS:
        fail("ERR_UNTIMELY_FILED",
             "service_date is more than %d days before the resubmission date"
             % C.TIMELY_FILING_DAYS)
    if auth is None or not services.date_in_episode(auth, service_date):
        fail("ERR_SERVICE_DATE_OUTSIDE_EPISODE",
             "service_date is outside the half-open episode window")
    # stage 10: resubmission cap
    if claim["resubmit_count"] >= C.RESUBMISSION_MAX:
        fail("ERR_RESUBMISSION_LIMIT",
             "claim has already been resubmitted %d times" % C.RESUBMISSION_MAX)
    # stage 11: referential
    matched = any(
        appt["referral_authorization_id"] == claim["referral_authorization_id"]
        and appt["status"] == "COMPLETED"
        and logical_clock.parse_dt(appt["scheduled_start"]).date() == service_date
        for appt in db.all_recs("appointments"))
    if not matched:
        fail("ERR_NO_MATCHING_COMPLETED_APPOINTMENT",
             "no COMPLETED appointment on this authorization matches service_date")
    # stage 12: fiscal sanity of the replacement lines
    _validate_lines_fiscal(lines)
    claim["service_lines"] = lines
    claim["billed_total_cents"] = services.billed_total(lines)
    claim["status"] = "RECEIVED"
    claim["denial_reason"] = None
    claim["resubmit_count"] += 1
    claim["submitted_at"] = logical_clock.now_iso()
    db.touch(claim)
    return response.ok(db.public(claim))


@bp.post("/community-care/claims/<rid>/reverse-payment")
@endpoint([C.ROLE_TPA_ADMINISTRATOR])
def reverse_payment(user_id, role, rid):
    claim = v.path_entity("claims", rid, "claim")
    b = v.body()
    reason = v.req_nonempty_str(b, "reason")
    require_owner(user_id, claim["tpa_id"], "payment reversal")
    if claim["status"] != "PAID":
        fail("ERR_INVALID_STATE", "only a PAID claim can be reversed")
    claim["status"] = "REVERSED"
    claim["reversed_reason"] = reason
    db.touch(claim)
    provider = db.get("providers", claim["provider_id"])
    if provider is not None:
        provider["current_paid_cents"] -= claim["paid_amount_cents"]
        provider["reversed_cents"] += claim["paid_amount_cents"]
        db.touch(provider)
    # A reversal is not a claim-finalization event: TPA counters do not move.
    return response.ok(db.public(claim))
