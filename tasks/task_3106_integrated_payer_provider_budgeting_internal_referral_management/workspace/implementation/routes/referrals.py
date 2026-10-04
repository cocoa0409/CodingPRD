"""Referral endpoints (PRD 3.5)."""

from flask import Blueprint

from clock import format_iso8601, now_iso, parse_iso8601
from constants import (
    APPEAL_ROUNDS_MAX,
    EXTERNAL_CONTRACT_MAX,
    REFERRAL_EXPIRY_DAYS,
    ROLE_ACCESS_SCHEDULER,
    ROLE_UTILIZATION_REVIEWER,
)
from datetime import timedelta

from db import STORE
from domain import (
    check_member_version,
    enforce_posture_gate,
    expire_authorized_referrals,
    get_referral,
    in_network_available,
    new_record,
    rank_candidate_departments,
    recompute_region_aggregates,
    require_body_reference,
    store_row,
    touch,
    triage_window_expired,
)
from errors import (
    ERR_APPEAL_ROUNDS_EXHAUSTED,
    ERR_CROSS_REGION_REFERENCE,
    ERR_NO_IN_NETWORK_CAPACITY,
    ERR_REFERRAL_NOT_DECIDABLE,
    ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED,
    ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK,
    ERR_UNAUTHORIZED_NETWORK_EXPANSION,
    raise_error,
)
from routes._common import (
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("referrals", __name__)


def _region_of_department(department_id):
    department = STORE.departments.get(department_id)
    return department.get("region_id") if department else None


@bp.post("/referrals")
def create_referral():
    principal((ROLE_ACCESS_SCHEDULER,))
    body = payload()

    member_id = require_field(body, "member_id")
    requesting_department_id = require_field(body, "requesting_department_id")
    target_department_id = require_field(body, "target_department_id")
    service_code = require_field(body, "service_code")
    referral_type = optional_field(body, "referral_type", "INTERNAL")
    authorization_exception = bool(optional_field(
        body, "authorization_exception", False))
    exception_reason = optional_field(body, "exception_reason", None)
    external_contract_count = optional_field(body, "external_contract_count", 0)
    expected = optional_field(body, "expected_member_version")

    member = require_body_reference("members", member_id)
    requesting_department = require_body_reference(
        "departments", requesting_department_id)
    target_department = require_body_reference("departments", target_department_id)

    check_member_version(member, expected)

    region_id = member["region_id"]

    # cross-region integrity, with the OUTSIDE_NETWORK exception (PRD 2.5)
    if referral_type != "OUTSIDE_NETWORK":
        if requesting_department.get("region_id") != region_id:
            raise_error(ERR_CROSS_REGION_REFERENCE)
        if target_department.get("region_id") != region_id:
            raise_error(ERR_CROSS_REGION_REFERENCE)

    # triage window: raising a referral starts a fresh window at the clock
    # instant, so a freshly raised referral is always inside it (PRD 3.5, 3.7).

    # network availability before the external-contract ceiling (PRD 3.7)
    available = in_network_available(region_id, service_code)
    if referral_type == "INTERNAL":
        if not available:
            raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
    else:
        if not authorization_exception:
            raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
        if exception_reason not in ("SERVICE_UNAVAILABLE_IN_NETWORK", "EMERGENCY"):
            raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
        if available and exception_reason != "EMERGENCY":
            raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)

    # external-contract ceiling
    if int(external_contract_count or 0) > EXTERNAL_CONTRACT_MAX:
        raise_error(ERR_UNAUTHORIZED_NETWORK_EXPANSION)

    # candidate resolution / capacity ranking (PRD 3.5)
    resolved_target = target_department_id
    if referral_type == "INTERNAL":
        candidates = rank_candidate_departments(region_id, service_code)
        if not candidates:
            raise_error(ERR_NO_IN_NETWORK_CAPACITY)
        resolved_target = target_department_id
        if target_department.get("region_id") != region_id:
            resolved_target = candidates[0]["id"]

    enforce_posture_gate(region_id)

    row = new_record(
        member_id=member_id,
        requesting_department_id=requesting_department_id,
        target_department_id=resolved_target,
        service_code=service_code,
        referral_type=referral_type,
        external_contract_count=int(external_contract_count or 0),
        authorization_exception=authorization_exception,
        exception_reason=exception_reason,
        appeal_rounds=0,
        effective_decision_at=None,
        expires_at=None,
        status="PENDING_TRIAGE",
    )
    store_row("referrals", row)

    touch(member)
    recompute_region_aggregates(region_id, bump_version=False)
    return single_response("referrals", row, 201)


@bp.get("/referrals")
def list_referrals():
    principal(READERS)
    expire_authorized_referrals()
    rows = list(STORE.referrals.values())
    rows = filter_rows(
        rows,
        member_id=arg("member_id"),
        target_department_id=arg("target_department_id"),
        requesting_department_id=arg("requesting_department_id"),
        status=arg("status"),
    )
    return list_response("referrals", rows)


@bp.get("/referrals/<referral_id>")
def get_one_referral(referral_id):
    principal(READERS)
    expire_authorized_referrals()
    return single_response("referrals", get_referral(referral_id))


def _require_decidable(referral):
    if referral.get("status") not in ("PENDING_TRIAGE", "APPEALED"):
        raise_error(ERR_REFERRAL_NOT_DECIDABLE)
    if triage_window_expired(referral):
        raise_error(ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED)


@bp.post("/referrals/<referral_id>/authorize")
def authorize_referral(referral_id):
    principal((ROLE_UTILIZATION_REVIEWER,))
    referral = get_referral(referral_id)
    _require_decidable(referral)

    region_id = _region_of_department(referral.get("target_department_id"))
    if region_id is not None:
        available = in_network_available(
            STORE.members[referral["member_id"]]["region_id"],
            referral.get("service_code"))
        if referral.get("referral_type") == "INTERNAL":
            if not available:
                raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
            target = STORE.departments.get(referral.get("target_department_id"))
            if target is None or not target.get("accepting_internal_referrals", True):
                raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
        else:
            reason = referral.get("exception_reason")
            if not referral.get("authorization_exception"):
                raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
            if reason not in ("SERVICE_UNAVAILABLE_IN_NETWORK", "EMERGENCY"):
                raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)
            if available and reason != "EMERGENCY":
                raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)

    referral["status"] = "AUTHORIZED"
    referral["effective_decision_at"] = now_iso()
    created = parse_iso8601(referral["created_at"])
    referral["expires_at"] = format_iso8601(
        created + timedelta(days=REFERRAL_EXPIRY_DAYS))
    touch(referral)
    if region_id is not None:
        recompute_region_aggregates(region_id, bump_version=False)
    return single_response("referrals", referral)


@bp.post("/referrals/<referral_id>/deny")
def deny_referral(referral_id):
    principal((ROLE_UTILIZATION_REVIEWER,))
    referral = get_referral(referral_id)
    _require_decidable(referral)
    if (referral.get("status") == "APPEALED"
            and int(referral.get("appeal_rounds") or 0) >= APPEAL_ROUNDS_MAX):
        raise_error(ERR_APPEAL_ROUNDS_EXHAUSTED)

    referral["status"] = "DENIED"
    referral["effective_decision_at"] = now_iso()
    touch(referral)

    for appointment in STORE.appointments.values():
        if appointment.get("referral_id") != referral_id:
            continue
        if appointment.get("hold_status") == "REFERRAL_HOLD":
            appointment["hold_status"] = "NONE"
            touch(appointment)

    region_id = _region_of_department(referral.get("target_department_id"))
    if region_id is not None:
        recompute_region_aggregates(region_id, bump_version=False)
    return single_response("referrals", referral)


@bp.post("/referrals/<referral_id>/appeal")
def appeal_referral(referral_id):
    principal((ROLE_UTILIZATION_REVIEWER,))
    referral = get_referral(referral_id)
    if referral.get("status") != "DENIED":
        raise_error(ERR_REFERRAL_NOT_DECIDABLE)
    if int(referral.get("appeal_rounds") or 0) >= APPEAL_ROUNDS_MAX:
        raise_error(ERR_APPEAL_ROUNDS_EXHAUSTED)
    referral["status"] = "APPEALED"
    referral["appeal_rounds"] = int(referral.get("appeal_rounds") or 0) + 1
    touch(referral)
    return single_response("referrals", referral)