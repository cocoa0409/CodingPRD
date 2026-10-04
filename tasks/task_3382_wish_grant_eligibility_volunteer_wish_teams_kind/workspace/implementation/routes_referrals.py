"""Referral intake (with child create/reuse, age bounds, duplicate detection,
territory assignment), certification, and eligibility determination."""

from flask import Blueprint, request

from auth import require_roles
from db import STORE, now, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_referral
from util import (
    body_json, req_str, opt_str, opt_int, req_enum, req_date,
    age_months, normalize_name, pagination, paginate, bad,
)

bp = Blueprint("referrals", __name__)

_SOURCE_TYPES = {"FAMILY", "MEDICAL_PROFESSIONAL", "SELF"}
_CONDITIONS = {
    "ONCOLOGY", "CARDIAC", "NEUROLOGIC", "GENETIC",
    "OTHER_PROGRESSIVE", "NON_QUALIFYING",
}
_LIVE_REFERRAL_STATES = {"PENDING_CERTIFICATION", "CERTIFIED"}

MIN_INTAKE_AGE_MONTHS = 30
MAX_INTAKE_AGE_MONTHS_EXCLUSIVE = 216
SELF_REFERRAL_MIN_AGE_MONTHS = 156
URGENT_PROGNOSIS_MONTHS = 6


def _assign_chapter(zip_code):
    """Longest matching zip prefix wins; ties break on chapter created_at ASC."""
    best = None
    best_len = -1
    for ch in sorted(STORE["chapters"].values(), key=lambda e: e["created_at"]):
        longest = -1
        for p in ch["territory_zip_prefixes"]:
            if zip_code.startswith(p) and len(p) > longest:
                longest = len(p)
        if longest < 0:
            continue
        if longest > best_len:
            best = ch
            best_len = longest
    return best


@bp.post("/wish-grant/referrals")
@require_roles("ReferralSource")
def create_referral():
    body = body_json()
    full_name = req_str(body, "child_full_name")
    dob = req_date(body, "child_date_of_birth")
    dob_s = body["child_date_of_birth"]
    zip_code = req_str(body, "child_zip_code")
    parent_email = req_str(body, "parent_email")
    diagnosis_summary = req_str(body, "diagnosis_summary")
    source_type = req_enum(body, "source_type", _SOURCE_TYPES)
    prognosis = opt_int(body, "prognosis_months")
    if prognosis is not None and prognosis < 0:
        bad("prognosis_months must be >= 0")

    today = now().date()
    m = age_months(dob, today)
    if not (MIN_INTAKE_AGE_MONTHS <= m < MAX_INTAKE_AGE_MONTHS_EXCLUSIVE):
        raise ApiError(
            "ERR_CHILD_AGE_OUT_OF_RANGE", 422,
            "Child age %d months is outside [30, 216)" % m,
        )
    if source_type == "SELF" and m < SELF_REFERRAL_MIN_AGE_MONTHS:
        raise ApiError(
            "ERR_SELF_REFERRAL_TOO_YOUNG", 422,
            "SELF referral requires age >= 156 months",
        )

    norm = normalize_name(full_name)
    child = None
    for c in STORE["children"].values():
        if c["normalized_full_name"] == norm and c["date_of_birth"] == dob_s:
            child = c
            break
    if child is not None:
        for r in STORE["referrals"].values():
            if r["child_id"] == child["id"] and r["status"] in _LIVE_REFERRAL_STATES:
                raise ApiError(
                    "ERR_DUPLICATE_REFERRAL", 409,
                    "A live referral already exists for this child",
                )

    chapter = _assign_chapter(zip_code)
    if chapter is None:
        raise ApiError(
            "ERR_NO_TERRITORY_CHAPTER", 422,
            "No chapter territory matches the child's zip code",
        )

    if child is None:
        child = new_entity(
            full_name=full_name,
            normalized_full_name=norm,
            date_of_birth=dob_s,
            zip_code=zip_code,
            parent_email=parent_email,
            diagnosis_summary=diagnosis_summary,
            chapter_id=chapter["id"],
            treatment_windows=[],
        )
        STORE["children"][child["id"]] = child

    ref = new_entity(
        child_id=child["id"],
        source_type=source_type,
        prognosis_months=prognosis,
        status="PENDING_CERTIFICATION",
        qualifying_condition=None,
        certification_note=None,
        certified_at=None,
        age_months_at_intake=m,
        denial_reason=None,
        determined_at=None,
        wish_id=None,
    )
    STORE["referrals"][ref["id"]] = ref
    return created(ser_referral(ref))


@bp.get("/wish-grant/referrals")
@require_roles("ReferralSource", "EligibilityReviewer", "MedicalProvider", "WishCoordinator")
def list_referrals():
    limit, offset = pagination()
    items = sorted(STORE["referrals"].values(), key=lambda e: e["created_at"])
    child_id = request.args.get("child_id")
    wish_id = request.args.get("wish_id")
    status = request.args.get("status")
    if child_id is not None:
        items = [r for r in items if r["child_id"] == child_id]
    if wish_id is not None:
        items = [r for r in items if r["wish_id"] == wish_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_referral(r) for r in page], total, limit, offset, has_more)


@bp.get("/wish-grant/referrals/<rid>")
@require_roles("ReferralSource", "EligibilityReviewer", "MedicalProvider", "WishCoordinator")
def get_referral(rid):
    r = STORE["referrals"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referral not found")
    return ok(ser_referral(r))


@bp.post("/wish-grant/referrals/<rid>/certify")
@require_roles("MedicalProvider")
def certify_referral(rid):
    r = STORE["referrals"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referral not found")
    body = body_json()
    condition = req_enum(body, "qualifying_condition", _CONDITIONS)
    note = opt_str(body, "certification_note")
    if r["status"] != "PENDING_CERTIFICATION":
        raise ApiError(
            "ERR_INVALID_REFERRAL_STATE", 409,
            "certify requires PENDING_CERTIFICATION",
        )
    ts = now()
    r["certified_at"] = ts
    r["qualifying_condition"] = condition
    if note is not None:
        r["certification_note"] = note
    if condition == "NON_QUALIFYING":
        r["status"] = "DENIED"
        r["determined_at"] = ts
        r["denial_reason"] = "CONDITION_NOT_QUALIFYING"
    else:
        r["status"] = "CERTIFIED"
    touch(r)
    return ok(ser_referral(r))


@bp.post("/wish-grant/referrals/<rid>/determine")
@require_roles("EligibilityReviewer")
def determine_referral(rid):
    r = STORE["referrals"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referral not found")
    body = body_json()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    denial_reason = None
    if decision == "DENIED":
        denial_reason = req_str(body, "denial_reason")
    if r["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_REFERRAL_STATE", 409,
            "determine requires CERTIFIED",
        )
    if decision == "DENIED":
        r["status"] = "DENIED"
        r["denial_reason"] = denial_reason
        r["determined_at"] = now()
        touch(r)
        return ok(ser_referral(r))

    child = STORE["children"][r["child_id"]]
    dob = req_date(child, "date_of_birth")
    m = age_months(dob, now().date())
    if m >= MAX_INTAKE_AGE_MONTHS_EXCLUSIVE:
        raise ApiError(
            "ERR_CHILD_AGE_OUT_OF_RANGE", 422,
            "Child has reached 216 months at determination",
        )
    urgency = (
        "RAPID"
        if r["prognosis_months"] is not None and r["prognosis_months"] <= URGENT_PROGNOSIS_MONTHS
        else "STANDARD"
    )
    wish = new_entity(
        child_id=child["id"],
        chapter_id=child["chapter_id"],
        referral_id=r["id"],
        wish_type=None,
        urgency=urgency,
        status="CREATED",
        true_wish_description=None,
        determined_at=None,
        hold_return_state=None,
        granted_at=None,
    )
    STORE["wishes"][wish["id"]] = wish
    r["status"] = "APPROVED"
    r["wish_id"] = wish["id"]
    r["determined_at"] = now()
    touch(r)
    return ok(ser_referral(r))
