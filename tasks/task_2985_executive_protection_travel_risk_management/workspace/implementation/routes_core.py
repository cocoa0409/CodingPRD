"""Roster, protectee registry, intelligence feeds and the logical clock.

PRD 3.1, 3.2 (feeds), 3.9 (disclosure read), 2.5 (clock).
"""

from decimal import Decimal

from flask import Blueprint

import payload
import serializers
from auth import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_EXECUTIVE,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_ANALYST,
    ROLE_SECURITY_DIRECTOR,
    ROLE_SYSTEM_OPERATOR,
    endpoint,
    require_executive_owns,
)
from calc import (
    CONSENT_SCOPES,
    SIGNAL_TYPES,
    STAFF_ROLES,
    SURVEY_OUTCOMES,
    TIERS,
)
from derive import get_executive, recompute_public_exposure_score
from envelope import list_response, object_response
from errors import ApiError
from store import audit_row, event_row, policies_of_executive, signals_of_executive, store, touch
from util import ZERO_SCORE, parse_instant

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Security staff -- PRD 3.1
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/security-staff")
@endpoint(ROLE_SYSTEM_OPERATOR, ROLE_SECURITY_DIRECTOR)
def register_staff():
    data = payload.body()
    full_name = payload.string_field(data, "full_name", min_len=1, max_len=120,
                                     non_blank=True)
    staff_role = payload.enum_field(data, "staff_role", STAFF_ROLES)
    certification_expires_at = payload.instant_field(data, "certification_expires_at")
    hourly_rate_cents = payload.int_field(data, "hourly_rate_cents", minimum=1)

    row = audit_row({
        "full_name": full_name,
        "staff_role": staff_role,
        "certification_expires_at": certification_expires_at,
        "hourly_rate_cents": hourly_rate_cents,
        # PRD 3.1: a newly registered staff member starts with both labour
        # figures at zero.
        "committed_detail_hours": 0,
        "released_detail_hours": 0,
    })
    store.staff[row["id"]] = row
    return object_response(serializers.staff(row), 201)


@bp.get("/exec-protection/security-staff/<staff_id>")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_COMPLIANCE_OFFICER, ROLE_SYSTEM_OPERATOR)
def read_staff(staff_id):
    row = store.staff.get(staff_id)
    if row is None:
        raise ApiError("ERR_STAFF_NOT_FOUND")
    return object_response(serializers.staff(row))


# ---------------------------------------------------------------------------
# Protectee registry -- PRD 3.1
# ---------------------------------------------------------------------------


def _validate_consent_expiry(consent_scope, consent_expires_at):
    """PRD 3.1: a consent grant that has already lapsed at the moment it is
    granted is a malformed payload."""
    if consent_scope != "NONE" and consent_expires_at is not None:
        if not consent_expires_at > store.now():
            raise ApiError("ERR_INVALID_REQUEST")


@bp.post("/exec-protection/executives")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def register_executive():
    data = payload.body()
    full_name = payload.string_field(data, "full_name", min_len=1, max_len=120,
                                     non_blank=True)
    tier = payload.enum_field(data, "tier", TIERS)
    role_title = payload.string_field(data, "role_title", min_len=1, max_len=120)
    base_country_code = payload.country_field(data, "base_country_code")
    annual_security_budget_cents = payload.int_field(
        data, "annual_security_budget_cents", minimum=0)
    consent_scope = payload.enum_field(data, "consent_scope", CONSENT_SCOPES,
                                       required=False, default="NONE")
    consent_expires_at = payload.instant_field(data, "consent_expires_at",
                                               required=False, default=None,
                                               nullable=True)
    _validate_consent_expiry(consent_scope, consent_expires_at)

    row = audit_row({
        "full_name": full_name,
        "tier": tier,
        "role_title": role_title,
        "base_country_code": base_country_code,
        "annual_security_budget_cents": annual_security_budget_cents,
        "consent_scope": consent_scope,
        "consent_expires_at": consent_expires_at,
        # PRD 3.1: a newly registered protectee is entirely un-assessed and
        # entirely un-committed.
        "residential_survey_status": "PENDING",
        "residential_component": ZERO_SCORE,
        "public_exposure_score": ZERO_SCORE,
        "threat_level": "LOW",
        "committed_budget_cents": 0,
        "spent_budget_cents": 0,
        "annual_disclosed_perquisite_cents": 0,
        "business_borne_security_cents": 0,
        "open_degraded_trip_count": 0,
    })
    store.executives[row["id"]] = row
    return object_response(serializers.executive(row), 201)


@bp.get("/exec-protection/executives/<executive_id>")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_COMPLIANCE_OFFICER, ROLE_EXECUTIVE)
def read_executive(executive_id):
    row = get_executive(executive_id)
    require_executive_owns(executive_id)
    return object_response(serializers.executive(row))


@bp.patch("/exec-protection/executives/<executive_id>/consent")
@endpoint(ROLE_EXECUTIVE, ROLE_PROTECTION_MANAGER)
def revise_consent(executive_id):
    data = payload.body()
    consent_scope = payload.enum_field(data, "consent_scope", CONSENT_SCOPES)
    supplied_expiry = "consent_expires_at" in data
    consent_expires_at = payload.instant_field(data, "consent_expires_at",
                                               required=False, default=None,
                                               nullable=True)
    _validate_consent_expiry(consent_scope, consent_expires_at)

    row = get_executive(executive_id)
    require_executive_owns(executive_id)

    # PRD 3.1: revising replaces consent_scope and, when supplied,
    # consent_expires_at.  Revision is deliberately not retroactive.
    row["consent_scope"] = consent_scope
    if supplied_expiry:
        row["consent_expires_at"] = consent_expires_at
    touch(row)
    return object_response(serializers.executive(row))


@bp.post("/exec-protection/executives/<executive_id>/residential-survey")
@endpoint(ROLE_SECURITY_ANALYST)
def record_residential_survey(executive_id):
    data = payload.body()
    survey_outcome = payload.enum_field(data, "survey_outcome", SURVEY_OUTCOMES)
    residential_component = payload.score_field(data, "residential_component")

    row = get_executive(executive_id)
    # PRD 3.2: the survey write sets residential_survey_status to the supplied
    # outcome and replaces residential_component outright.
    row["residential_survey_status"] = survey_outcome
    row["residential_component"] = residential_component
    touch(row)
    return object_response(serializers.executive(row))


# ---------------------------------------------------------------------------
# Public-exposure signals -- PRD 3.2
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/executives/<executive_id>/exposure-signals")
@endpoint(ROLE_SECURITY_ANALYST)
def append_exposure_signal(executive_id):
    data = payload.body()
    signal_type = payload.enum_field(data, "signal_type", SIGNAL_TYPES)
    severity = payload.int_field(data, "severity", minimum=1, maximum=5)
    observed_at = payload.instant_field(data, "observed_at")
    source_note = payload.string_field(data, "source_note", required=False,
                                       max_len=500, default=None, nullable=True)
    # PRD 3.2: observed_at must be at or before the current logical clock.
    if observed_at > store.now():
        raise ApiError("ERR_INVALID_REQUEST")

    executive = get_executive(executive_id)
    row = event_row({
        "executive_id": executive_id,
        "signal_type": signal_type,
        "severity": severity,
        "observed_at": observed_at,
        "source_note": source_note,
    })
    store.signals[row["id"]] = row
    recompute_public_exposure_score(executive)
    touch(executive)
    return object_response(serializers.exposure_signal(row), 201)


@bp.get("/exec-protection/executives/<executive_id>/exposure-signals")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def list_exposure_signals(executive_id):
    limit, offset = payload.pagination()
    get_executive(executive_id)
    rows = signals_of_executive(executive_id)
    signal_type = payload.request.args.get("signal_type")
    if signal_type is not None:
        rows = [r for r in rows if r["signal_type"] == signal_type]
    # PRD 4: newest observed_at first.
    rows.sort(key=lambda r: (r["observed_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.exposure_signal(r) for r in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Insurance policy list and the disclosure read
# ---------------------------------------------------------------------------


@bp.get("/exec-protection/executives/<executive_id>/insurance-policies")
@endpoint(ROLE_COMPLIANCE_OFFICER, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_EXECUTIVE)
def list_insurance_policies(executive_id):
    limit, offset = payload.pagination()
    get_executive(executive_id)
    require_executive_owns(executive_id)
    rows = policies_of_executive(executive_id)
    status = payload.request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    policy_type = payload.request.args.get("policy_type")
    if policy_type is not None:
        rows = [r for r in rows if r["policy_type"] == policy_type]
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.insurance_policy(r) for r in page],
                         limit, offset, total, has_more)


@bp.get("/exec-protection/executives/<executive_id>/perquisite-disclosure")
@endpoint(ROLE_EXECUTIVE, ROLE_COMPLIANCE_OFFICER, ROLE_SECURITY_DIRECTOR)
def read_perquisite_disclosure(executive_id):
    executive = get_executive(executive_id)
    require_executive_owns(executive_id)

    closed = [t for t in store.trips.values()
              if t["executive_id"] == executive_id and t["readiness_state"] == "CLOSED"]
    total_security_cost_cents = 0
    for trip in closed:
        total_security_cost_cents += trip["total_security_cost_cents"]
    latest_rate = Decimal("0.00")
    if closed:
        # PRD 3.9: the rate pinned by the most recently closed of them.
        ordered = sorted(closed, key=lambda t: (t["closed_at"], t["_seq"]))
        latest_rate = ordered[-1]["perquisite_rate_applied"]
    data = {
        "executive_id": executive_id,
        "closed_trip_count": len(closed),
        "annual_disclosed_perquisite_cents":
            executive["annual_disclosed_perquisite_cents"],
        "business_borne_security_cents": executive["business_borne_security_cents"],
        "total_security_cost_cents": total_security_cost_cents,
        "latest_perquisite_rate_applied": latest_rate,
    }
    return object_response(data)


# ---------------------------------------------------------------------------
# The logical clock -- PRD 2.5
# ---------------------------------------------------------------------------


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
@endpoint(ROLE_SYSTEM_OPERATOR)
def set_current_utc():
    data = payload.body()
    current_utc = payload.instant_field(data, "current_utc")
    # PRD 2.5: setting the clock modifies no business entity.
    store.clock = current_utc
    from util import fmt_instant
    return object_response({"current_utc": fmt_instant(current_utc)})
