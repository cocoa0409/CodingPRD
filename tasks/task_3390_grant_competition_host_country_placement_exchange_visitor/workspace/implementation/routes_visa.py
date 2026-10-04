"""VisaSponsorship and ResidencyLedger endpoints."""

from flask import Blueprint

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_PLATFORM_ADMIN,
    RESIDENCY_REQUIRED_DAYS,
)
from errors import ApiError
from store import STORE, stamp_new, bump, now
from timeutil import parse_iso, fmt
from validate import (
    body,
    check_unknown,
    req,
    as_bool,
    as_dt,
    as_text,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("visa", __name__)

VISA_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)
LEDGER_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_APPLICANT)
LEDGER_ACTIONS = ("REQUEST_WAIVER", "APPROVE_WAIVER", "DENY_WAIVER")


# ---------------------------------------------------------------------------
# VisaSponsorship
# ---------------------------------------------------------------------------

@bp.post("/exchange/grants/<gid>/visa-sponsorships")
def create_visa(gid):
    _, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER])
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    payload = body()
    # Priority 9: structural validation (required fields, unknown fields,
    # orientation not in the future).
    check_unknown(payload, {"subject_to_home_residency", "orientation_completed_at"})
    subject = as_bool(req(payload, "subject_to_home_residency"), "subject_to_home_residency")
    orientation = as_dt(req(payload, "orientation_completed_at"), "orientation_completed_at")
    if orientation > now():
        raise V("orientation_completed_at must not be in the future")
    # Priority 9: one sponsorship per grant.
    if domain.visa_of_grant(gid) is not None:
        raise ApiError("ERR_DUPLICATE_VISA", 409, "Grant already has a visa sponsorship")
    # Priority 10: the grant must be CONFIRMED.
    if grant["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_GRANT_NOT_CONFIRMED", 409, "Visa sponsorship requires a CONFIRMED grant"
        )
    STORE.visa_counter += 1
    visa = {
        "grant_id": gid,
        "sponsor_program_number": "EV-%06d" % STORE.visa_counter,
        "subject_to_home_residency": subject,
        "orientation_completed_at": fmt(orientation),
        "status": "ISSUED",
    }
    stamp_new(visa)
    STORE.visas[visa["id"]] = visa
    # Side effects: copy the orientation timestamp onto the grant, and create
    # the residency ledger (PENDING when subject, NOT_REQUIRED otherwise).
    grant["orientation_completed_at"] = fmt(orientation)
    bump(grant)
    ledger = {
        "visa_sponsorship_id": visa["id"],
        "status": "PENDING" if subject else "NOT_REQUIRED",
        "required_days": RESIDENCY_REQUIRED_DAYS,
        "accrued_days": 0,
        "accrual_start_date": None,
        "stays": [],
        "waiver_reason": None,
    }
    stamp_new(ledger)
    STORE.ledgers[ledger["id"]] = ledger
    return envelope.ok(serialize.visa_out(visa), 201)


@bp.get("/exchange/visa-sponsorships/<vid>")
def get_visa(vid):
    user, role = auth()
    require_roles(role, VISA_READ_ROLES)
    visa = STORE.visas.get(vid)
    if visa is None:
        raise ApiError("ERR_VISA_NOT_FOUND", 404, "No visa sponsorship with the given id")
    check_owner(role, user, domain.applicant_of_visa(visa))
    return envelope.ok(serialize.visa_out(visa))


@bp.get("/exchange/grants/<gid>/visa-sponsorships")
def list_visas_of_grant(gid):
    user, role = auth()
    require_roles(role, VISA_READ_ROLES)
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    limit, offset = pagination()
    items = [v for v in STORE.visas.values() if v["grant_id"] == gid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.visa_out(v) for v in page], total, limit, offset)


# ---------------------------------------------------------------------------
# ResidencyLedger
# ---------------------------------------------------------------------------

@bp.get("/exchange/visa-sponsorships/<vid>/residency-ledgers")
def list_ledgers_of_visa(vid):
    user, role = auth()
    require_roles(role, LEDGER_READ_ROLES)
    visa = STORE.visas.get(vid)
    if visa is None:
        raise ApiError("ERR_VISA_NOT_FOUND", 404, "No visa sponsorship with the given id")
    check_owner(role, user, domain.applicant_of_visa(visa))
    limit, offset = pagination()
    items = [led for led in STORE.ledgers.values() if led["visa_sponsorship_id"] == vid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.ledger_out(led) for led in page], total, limit, offset)


@bp.get("/exchange/residency-ledgers/<lid>")
def get_ledger(lid):
    user, role = auth()
    require_roles(role, LEDGER_READ_ROLES)
    ledger = STORE.ledgers.get(lid)
    if ledger is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", 404, "No residency ledger with the given id")
    check_owner(role, user, domain.applicant_of_ledger(ledger))
    return envelope.ok(serialize.ledger_out(ledger))


@bp.post("/exchange/residency-ledgers/<lid>/stays")
def add_stay(lid):
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT])
    ledger = STORE.ledgers.get(lid)
    if ledger is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", 404, "No residency ledger with the given id")
    check_owner(role, user, domain.applicant_of_ledger(ledger))
    # Priority 6: stays are recorded only while ACCRUING.
    if ledger["status"] != "ACCRUING":
        raise ApiError(
            "ERR_RESIDENCY_NOT_ACCRUING", 409, "Residency ledger is not ACCRUING"
        )
    payload = body()
    start = as_dt(req(payload, "start_date"), "start_date").date()
    end = as_dt(req(payload, "end_date"), "end_date").date()
    # Priority 8: the stay must not precede the accrual start.
    accrual_start = parse_iso(ledger["accrual_start_date"]).date()
    if start < accrual_start:
        raise ApiError(
            "ERR_STAY_BEFORE_ACCRUAL_START",
            409,
            "Stay start_date precedes the ledger's accrual_start_date",
        )
    # Priority 9: structural + closed-interval overlap (touching endpoints count).
    check_unknown(payload, {"start_date", "end_date"})
    if end < start:
        raise V("Stay end_date must not precede its start_date")
    for existing in ledger["stays"]:
        e_start = parse_iso(existing["start_date"]).date()
        e_end = parse_iso(existing["end_date"]).date()
        if not (end < e_start or start > e_end):
            raise ApiError(
                "ERR_STAY_OVERLAP",
                409,
                "Stay overlaps an existing stay (touching endpoints count as overlap)",
            )
    day_count = (end - start).days + 1  # both endpoints inclusive
    ledger["stays"].append(
        {
            "start_date": payload["start_date"],
            "end_date": payload["end_date"],
            "day_count": day_count,
        }
    )
    ledger["accrued_days"] = sum(s["day_count"] for s in ledger["stays"])
    if ledger["accrued_days"] >= ledger["required_days"]:
        ledger["status"] = "FULFILLED"
    bump(ledger)
    return envelope.ok(serialize.ledger_out(ledger), 201)


@bp.post("/exchange/residency-ledgers/<lid>/transition")
def ledger_transition(lid):
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT, ROLE_PROGRAM_OFFICER])
    payload = body()
    action = payload.get("action")
    # Priority 2: action-family role binding for known actions.
    if isinstance(action, str):
        if action == "REQUEST_WAIVER":
            if role != ROLE_APPLICANT:
                raise ApiError("ERR_UNAUTHORIZED", 403, "REQUEST_WAIVER is an Applicant action")
        elif action in ("APPROVE_WAIVER", "DENY_WAIVER"):
            if role != ROLE_PROGRAM_OFFICER:
                raise ApiError("ERR_UNAUTHORIZED", 403, "%s is a ProgramOfficer action" % action)

    # Priority 3: path existence precedes every other domain check (PRD 2.9).
    ledger = STORE.ledgers.get(lid)
    if ledger is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", 404, "No residency ledger with the given id")
    check_owner(role, user, domain.applicant_of_ledger(ledger))

    if action is None:
        raise V("Missing required field: action")
    check_unknown(payload, {"action", "waiver_reason"})
    if action not in LEDGER_ACTIONS:
        raise V("Unknown action for residency ledger transition: %r" % action)
    if action == "REQUEST_WAIVER":
        # Priority 6 special guard: waiver requests require ACCRUING.
        if ledger["status"] != "ACCRUING":
            raise ApiError(
                "ERR_RESIDENCY_NOT_ACCRUING", 409, "Residency ledger is not ACCRUING"
            )
        ledger["status"] = "WAIVER_PENDING"
        reason = payload.get("waiver_reason")
        if reason is not None:
            ledger["waiver_reason"] = as_text(reason, "waiver_reason")
    elif action == "APPROVE_WAIVER":
        if ledger["status"] != "WAIVER_PENDING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Only a WAIVER_PENDING ledger can be approved"
            )
        ledger["status"] = "WAIVED"
    else:  # DENY_WAIVER
        if ledger["status"] != "WAIVER_PENDING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Only a WAIVER_PENDING ledger can be denied"
            )
        ledger["status"] = "ACCRUING"
    bump(ledger)
    return envelope.ok(serialize.ledger_out(ledger))
