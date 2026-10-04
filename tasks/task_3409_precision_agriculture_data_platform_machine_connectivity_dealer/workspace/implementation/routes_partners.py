"""Integration partners: certification lifecycle and metered data pulls
(PRD section 3.9)."""

from datetime import timedelta

from flask import Blueprint

from auth import (
    as_enum,
    as_pos_int,
    as_str,
    body_json,
    caller,
    find_active_grant,
    get_or_404,
    need,
    require_role,
    access_denied,
)
from constants import CERT_VALIDITY_DAYS, SCOPES
from db import STORES, now
from domain import new_record, record_count, serialize, touch
from envelope import created, ok
from errors import (
    ERR_DATA_SCOPE_NOT_GRANTED,
    ERR_PARTNER_NOT_CERTIFIED,
    ERR_PARTNER_QUOTA_EXCEEDED,
    ApiError,
    invalid_state,
)

bp = Blueprint("partners", __name__)


@bp.post("/integration-partners")
def create_partner():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    name = as_str(need(b, "name"), "name")
    quota = as_pos_int(need(b, "api_quota_calls_per_day"), "api_quota_calls_per_day")
    rec = new_record(
        {
            "name": name,
            "api_quota_calls_per_day": quota,
            "status": "REGISTERED",
            "certification_expires_on": None,
            "calls_today": 0,
            "calls_window_date": None,
        }
    )
    STORES["integration_partners"][rec["id"]] = rec
    return created(serialize(rec))


@bp.get("/integration-partners/<pid>")
def get_partner(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "PartnerApp"})
    p = get_or_404("integration_partners", pid, "integration partner")
    if role == "PartnerApp" and uid != pid:
        raise access_denied("a partner may read only its own record")
    return ok(serialize(p))


@bp.post("/integration-partners/<pid>/submit-for-certification")
def submit_for_certification(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    p = get_or_404("integration_partners", pid, "integration partner")
    if p["status"] not in ("REGISTERED", "EXPIRED"):
        raise invalid_state("partner is not REGISTERED or EXPIRED")
    p["status"] = "CERTIFICATION_REVIEW"
    touch(p)
    return ok(serialize(p))


@bp.post("/integration-partners/<pid>/decide")
def decide_certification(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    decision = as_enum(need(b, "decision"), "decision", {"CERTIFY", "FAIL"})
    p = get_or_404("integration_partners", pid, "integration partner")
    if p["status"] != "CERTIFICATION_REVIEW":
        raise invalid_state("partner is not CERTIFICATION_REVIEW")
    if decision == "CERTIFY":
        p["status"] = "CERTIFIED"
        p["certification_expires_on"] = now().date() + timedelta(days=CERT_VALIDITY_DAYS)
    else:
        # Fail-back cycle
        p["status"] = "REGISTERED"
    touch(p)
    return ok(serialize(p))


@bp.post("/integration-partners/<pid>/data-pull")
def data_pull(pid):
    uid, role = caller()
    require_role(role, {"PartnerApp"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    scope = as_enum(need(b, "scope"), "scope", SCOPES)
    p = get_or_404("integration_partners", pid, "integration partner")
    get_or_404("organizations", organization_id, "organization")
    # Self-scoping: a partner pulls only as itself
    if uid != p["id"]:
        raise access_denied("a partner may pull only as itself")
    # State gate: the partner must be CERTIFIED (HTTP 403 per PRD section 5)
    if p["status"] != "CERTIFIED":
        raise ApiError(ERR_PARTNER_NOT_CERTIFIED, 403, "partner is not CERTIFIED")
    # Compliance gate: an ACTIVE, in-window grant naming this partner must
    # cover the requested scope for the target organization
    if find_active_grant(organization_id, "PartnerApp", uid, scope) is None:
        raise ApiError(ERR_DATA_SCOPE_NOT_GRANTED, 403, "no ACTIVE grant covers the scope")
    # Quota gate, against the counter for the current UTC date
    today = now().date()
    if p["calls_window_date"] != today:
        p["calls_window_date"] = today
        p["calls_today"] = 0
    if p["calls_today"] >= p["api_quota_calls_per_day"]:
        raise ApiError(ERR_PARTNER_QUOTA_EXCEEDED, 409, "daily quota exhausted")
    p["calls_today"] += 1
    touch(p)
    return ok(
        {
            "organization_id": organization_id,
            "scope": scope,
            "record_count": record_count(organization_id, scope),
            "calls_remaining_today": p["api_quota_calls_per_day"] - p["calls_today"],
        }
    )
