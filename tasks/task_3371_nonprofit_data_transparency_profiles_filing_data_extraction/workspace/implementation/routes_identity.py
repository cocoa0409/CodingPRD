"""Identity resolution cases and the admin logical-clock capability (PRD 3.8, 2.4)."""

from flask import Blueprint

import auth
import clock
import response
import store
import svc
import webutil
from errors import (
    ApiError,
    ERR_IDENTITY_CASE_INVALID,
    ERR_INVALID_STATE,
    ERR_MERGE_CYCLE_DETECTED,
)

bp = Blueprint("identity", __name__)

CASE_TYPES = ("MERGE", "DISSOLUTION", "NAME_CHANGE")
RESOLUTION_DECISIONS = ("FINALIZE", "WITHDRAW")

CASE_FIELDS = (
    "subject_organization_id", "case_type", "effective_date",
    "surviving_organization_id", "new_legal_name", "resolution_note",
)


def _validate_combination(case_type, subject, surviving_id, new_legal_name):
    if case_type == "MERGE":
        if not surviving_id or surviving_id == subject["id"]:
            raise ApiError(
                ERR_IDENTITY_CASE_INVALID,
                "A MERGE requires a surviving_organization_id that differs from the subject.",
            )
    elif case_type == "DISSOLUTION":
        if surviving_id:
            raise ApiError(
                ERR_IDENTITY_CASE_INVALID,
                "A DISSOLUTION requires surviving_organization_id to be null.",
            )
    elif case_type == "NAME_CHANGE":
        if surviving_id:
            raise ApiError(
                ERR_IDENTITY_CASE_INVALID,
                "A NAME_CHANGE requires surviving_organization_id to be null.",
            )
        if not new_legal_name or new_legal_name == subject.get("legal_name"):
            raise ApiError(
                ERR_IDENTITY_CASE_INVALID,
                "A NAME_CHANGE requires a new_legal_name that differs from the current one.",
            )


@bp.route("/nonprofits/identity-cases", methods=["POST"])
def create_identity_case():
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    data = webutil.body()
    webutil.reject_unknown(data, CASE_FIELDS)

    subject_organization_id = webutil.as_string(data, "subject_organization_id")
    case_type = webutil.as_enum(data, "case_type", CASE_TYPES)
    effective_date = webutil.as_datetime(data, "effective_date")
    surviving_organization_id = webutil.as_string(
        data, "surviving_organization_id", required=False
    )
    new_legal_name = webutil.as_string(data, "new_legal_name", required=False)
    resolution_note = webutil.as_string(data, "resolution_note", required=False)

    subject = svc.get_organization(subject_organization_id)
    if surviving_organization_id is not None:
        svc.get_organization(surviving_organization_id)

    _validate_combination(case_type, subject, surviving_organization_id, new_legal_name)

    case = store.new_row(
        subject_organization_id=subject_organization_id,
        surviving_organization_id=surviving_organization_id,
        case_type=case_type,
        new_legal_name=new_legal_name,
        effective_date=effective_date,
        status="OPEN",
        resolution_note=resolution_note,
        reassigned_grant_count=0,
        finalized_at=None,
    )
    store.insert("identity_cases", case)
    store.touch(subject)
    return response.ok(svc.ser_identity_case(case), status=201)


def _would_cycle(subject_id, surviving_id):
    """Follow successor_organization_id outward; arriving at the subject is a cycle."""
    seen = set()
    cursor = surviving_id
    while cursor is not None and cursor not in seen:
        if cursor == subject_id:
            return True
        seen.add(cursor)
        row = store.find("organizations", cursor)
        if row is None:
            return False
        cursor = row.get("successor_organization_id")
    return False


@bp.route("/nonprofits/identity-cases/<case_id>/finalize", methods=["POST"])
def finalize_identity_case(case_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    case = svc.get_identity_case(case_id)

    data = webutil.body()
    webutil.reject_unknown(data, ("resolution_decision",))
    decision = webutil.as_enum(data, "resolution_decision", RESOLUTION_DECISIONS)

    if case.get("status") != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE,
            "A case in %s status cannot be finalized." % case.get("status"),
        )

    if decision == "WITHDRAW":
        case["status"] = "WITHDRAWN"
        store.touch(case)
        return response.ok(svc.ser_identity_case(case))

    subject = svc.get_organization(case.get("subject_organization_id"))
    case_type = case.get("case_type")
    surviving_id = case.get("surviving_organization_id")

    _validate_combination(case_type, subject, surviving_id, case.get("new_legal_name"))
    if case_type == "MERGE" and _would_cycle(subject["id"], surviving_id):
        raise ApiError(
            ERR_MERGE_CYCLE_DETECTED,
            "Finalizing this merge would create a cycle in the successor graph.",
        )

    if case_type == "MERGE":
        surviving = svc.get_organization(surviving_id)
        reassigned = 0
        for grant in store.rows("grants"):
            changed = False
            if grant.get("recipient_organization_id") == subject["id"]:
                grant["recipient_organization_id"] = surviving_id
                changed = True
            if grant.get("funder_organization_id") == subject["id"]:
                grant["funder_organization_id"] = surviving_id
                changed = True
            if changed:
                store.touch(grant)
                reassigned += 1
        case["reassigned_grant_count"] = reassigned
        subject["profile_status"] = "MERGED"
        subject["successor_organization_id"] = surviving_id
        svc.revoke_active_seals(subject)
        for license_row in store.where("licenses", licensee_organization_id=subject["id"]):
            if license_row.get("status") == "ACTIVE":
                svc.expire_license(license_row)
        svc.recompute_counters(subject)
        svc.recompute_counters(surviving)
        svc.recompute_seal_mirror(subject)
        store.touch(subject)
        store.touch(surviving)

    elif case_type == "DISSOLUTION":
        subject["profile_status"] = "DISSOLVED"
        subject["dissolution_date"] = case.get("effective_date")
        svc.revoke_active_seals(subject)
        for license_row in store.where("licenses", licensee_organization_id=subject["id"]):
            if license_row.get("status") == "ACTIVE":
                svc.expire_license(license_row)
        svc.recompute_counters(subject)
        svc.recompute_seal_mirror(subject)
        store.touch(subject)

    else:  # NAME_CHANGE
        former = list(subject.get("former_legal_names") or [])
        former.append(subject.get("legal_name"))
        subject["former_legal_names"] = former
        subject["legal_name"] = case.get("new_legal_name")
        store.touch(subject)

    case["status"] = "FINALIZED"
    case["finalized_at"] = clock.fmt_dt(clock.now())
    store.touch(case)
    return response.ok(svc.ser_identity_case(case))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    data = webutil.body()
    webutil.reject_unknown(data, ("current_utc",))

    raw = webutil.as_string(data, "current_utc")
    instant = clock.parse_dt(raw)
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 timestamp.")

    clock.set_now(instant, raw)
    svc.apply_clock_effects()
    return response.ok({"current_utc": raw})
