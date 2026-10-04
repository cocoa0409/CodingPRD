"""Credentials: issuance, renewal cycle, revocation cascade (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint, request

from cascade import auto_create_plan
from derived import ce_totals, RENEWAL_BASE_FEE_CENTS, LATE_FEE_CENTS
from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_LEARNER_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_AGE_LEVEL_MISMATCH,
    ERR_PRACTICUM_NOT_VERIFIED,
    ERR_PROGRAM_NOT_ACCREDITED,
    ERR_DUPLICATE_CREDENTIAL,
    ERR_CREDENTIAL_NOT_RENEWABLE,
    ERR_RENEWAL_WINDOW_CLOSED,
    ERR_INSUFFICIENT_CE_HOURS,
    ERR_FEE_MISMATCH,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_credential
from store import (
    db,
    new_id,
    stamp_new,
    touch,
    now_dt,
    now_date,
    now_iso,
    fmt_ts,
    active_catalog,
    add_months,
    add_months_dt,
    parse_datetime,
)
from validation import authenticate, require_role, payload, req_enum, req_int, AGE_LEVELS

bp = Blueprint("credentials", __name__)

CREDENTIAL_READ_ROLES = {
    "SocietyAdmin",
    "Registrar",
    "AccreditationReviewer",
    "AdultLearner",
    "ProgramDirector",
    "SchoolAdmin",
}
CREDENTIAL_LIST_ROLES = {"SocietyAdmin", "Registrar", "AccreditationReviewer"}


def get_credential_or_404(credential_id):
    c = db.credentials.get(credential_id)
    if c is None:
        raise ApiError(ERR_CREDENTIAL_NOT_FOUND[0], ERR_CREDENTIAL_NOT_FOUND[1],
                       "No credential with id %r." % credential_id)
    return c


@bp.route("/credentials", methods=["POST"])
def issue_credential():
    _, role = authenticate()
    require_role(role, {"Registrar"})
    body = payload()
    # Tier 3: learner_id body FK.
    learner_id = body.get("learner_id")
    learner = None
    if isinstance(learner_id, str):
        learner = db.learners.get(learner_id)
        if learner is None:
            raise ApiError(ERR_LEARNER_NOT_FOUND[0], ERR_LEARNER_NOT_FOUND[1],
                           "No adult learner with id %r." % learner_id)
    # Tier 4: shape.
    if not isinstance(learner_id, str):
        from errors import ERR_VALIDATION
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'learner_id' is required and must be a string.")
    age_level = req_enum(body, "age_level", AGE_LEVELS)
    # Tier 8: requested age level must equal the learner's own.
    if age_level != learner["age_level"]:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "Credential age level must equal the learner's.")
    # Tier 9: practicum verified, program accredited, no duplicate.
    if learner["status"] != "PRACTICUM_COMPLETE":
        raise ApiError(ERR_PRACTICUM_NOT_VERIFIED[0], ERR_PRACTICUM_NOT_VERIFIED[1],
                       "The learner's practicum has not been verified.")
    program = db.programs.get(learner["program_id"])
    if program is None or program["status"] != "ACCREDITED":
        raise ApiError(ERR_PROGRAM_NOT_ACCREDITED[0], ERR_PROGRAM_NOT_ACCREDITED[1],
                       "The learner's program is not ACCREDITED.")
    for c in db.credentials.values():
        if (c["learner_id"] == learner["id"] and c["age_level"] == age_level
                and c["status"] in ("ACTIVE", "LAPSED")):
            raise ApiError(ERR_DUPLICATE_CREDENTIAL[0], ERR_DUPLICATE_CREDENTIAL[1],
                           "An ACTIVE or LAPSED credential already exists for "
                           "this learner and age level.")
    cat = active_catalog()
    if cat is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    now = now_dt()
    cred = {
        "id": new_id(),
        "learner_id": learner["id"],
        "age_level": age_level,
        "status": "ACTIVE",
        "issued_at": fmt_ts(now),
        "cycle_start": now.date().isoformat(),
        "expires_at": fmt_ts(add_months_dt(now, int(cat["credential_validity_months"]))),
        "renewed_count": 0,
    }
    stamp_new(cred)
    db.credentials[cred["id"]] = cred
    learner["status"] = "CREDENTIALED"
    touch(learner)
    return ok(serialize_credential(cred), 201)


@bp.route("/credentials/<credential_id>", methods=["GET"])
def get_credential(credential_id):
    _, role = authenticate()
    require_role(role, CREDENTIAL_READ_ROLES)
    return ok(serialize_credential(get_credential_or_404(credential_id)), 200)


@bp.route("/credentials", methods=["GET"])
def list_credentials():
    _, role = authenticate()
    require_role(role, CREDENTIAL_LIST_ROLES)
    args = request.args
    items = list(db.credentials.values())
    for f in ("learner_id", "status", "age_level"):
        v = args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_credential)


@bp.route("/credentials/<credential_id>/renew", methods=["POST"])
def renew_credential(credential_id):
    uid, role = authenticate()
    require_role(role, {"AdultLearner", "Registrar"})
    cred = get_credential_or_404(credential_id)
    body = payload()
    # Tier 4: the single input is fee_cents.
    fee_cents = req_int(body, "fee_cents")
    # Tier 5: an AdultLearner renews only their own credential.
    if role == "AdultLearner" and uid != cred["learner_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "AdultLearner may only renew their own credential.")
    # Tier 6 (first renewal check): state — REVOKED/EXPIRED outrank window errors.
    if cred["status"] not in ("ACTIVE", "LAPSED"):
        raise ApiError(ERR_CREDENTIAL_NOT_RENEWABLE[0], ERR_CREDENTIAL_NOT_RENEWABLE[1],
                       "A %s credential cannot be renewed." % cred["status"])
    cat = active_catalog()
    if cat is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    # Tier 7 (second renewal check): inclusive renewal window around expires_at.
    exp_date = parse_datetime(cred["expires_at"]).date()
    open_date = add_months(exp_date, -int(cat["renewal_window_months"]))
    close_date = add_months(exp_date, int(cat["renewal_grace_months"]))
    today = now_date()
    if not (open_date <= today <= close_date):
        raise ApiError(ERR_RENEWAL_WINDOW_CLOSED[0], ERR_RENEWAL_WINDOW_CLOSED[1],
                       "The renewal window is closed.")
    # Tier 9 (third): CYCLE CE hours meet the catalog requirement (equality ok).
    cycle, _ = ce_totals(cred)
    if cycle < Decimal(str(cat["ce_hours_required"])):
        raise ApiError(ERR_INSUFFICIENT_CE_HOURS[0], ERR_INSUFFICIENT_CE_HOURS[1],
                       "CYCLE continuing-education hours are below the requirement.")
    # Tier 10 (fourth): exact fee (late fee when LAPSED).
    expected = RENEWAL_BASE_FEE_CENTS + (LATE_FEE_CENTS if cred["status"] == "LAPSED" else 0)
    if fee_cents != expected:
        raise ApiError(ERR_FEE_MISMATCH[0], ERR_FEE_MISMATCH[1],
                       "fee_cents must equal %d." % expected)
    now = now_dt()
    cred["status"] = "ACTIVE"
    cred["cycle_start"] = today.isoformat()
    cred["expires_at"] = fmt_ts(add_months_dt(now, int(cat["credential_validity_months"])))
    cred["renewed_count"] += 1
    cred["issued_at"] = now_iso()
    touch(cred)
    return ok(serialize_credential(cred), 200)


@bp.route("/credentials/<credential_id>/revoke", methods=["POST"])
def revoke_credential(credential_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    cred = get_credential_or_404(credential_id)
    # Tier 6: revocation only from ACTIVE or LAPSED.
    if cred["status"] not in ("ACTIVE", "LAPSED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "A %s credential cannot be revoked." % cred["status"])
    cred["status"] = "REVOKED"
    touch(cred)
    # Revocation cascade: override led classrooms, then auto-create an
    # improvement plan for each affected ACCREDITED school.
    affected_school_ids = set()
    for room in db.classrooms.values():
        if room.get("lead_credential_id") == cred["id"]:
            room["compliance_override"] = "NONCOMPLIANT_LEAD"
            touch(room)
            affected_school_ids.add(room["school_id"])
    for sid in affected_school_ids:
        school = db.schools.get(sid)
        if school is not None and school["membership_level"] == "ACCREDITED":
            auto_create_plan(
                school_id=sid,
                visit_id=None,
                required_actions=["Restore a credentialed lead teacher of matching age level"],
            )
    return ok(serialize_credential(cred), 200)
