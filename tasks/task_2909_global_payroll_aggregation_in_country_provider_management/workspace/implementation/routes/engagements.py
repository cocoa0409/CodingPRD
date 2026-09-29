"""Engagement formation, the residency decision and provider transition."""
from flask import Blueprint, g

import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    COMPLIANCE_AUDITOR,
    ENGAGEMENT_STATUSES,
    FILING_RESPONSIBILITIES,
    PAY_FREQUENCIES,
    PAYROLL_CONTROLLER,
    PLATFORM_ADMIN,
    REGIONS,
    SERVICE_SCOPES,
    ApiError,
    bad_request,
    date_str,
    now,
)
from response import created, object_response, page_response
from store import new_row, touch

bp = Blueprint("engagements", __name__)

LIVE_CYCLE_STATUSES = ("INPUTS_LOCKED", "RESULTS_APPROVED", "FUNDED")


@bp.post("/payroll/engagements")
@require(PLATFORM_ADMIN)
def create_engagement():
    body = v.json_body()
    country_id = v.req_id(body, "country_profile_id")
    provider_id = v.req_id(body, "provider_id")
    scope = v.req_enum_list(body, "service_scope", SERVICE_SCOPES, 1, 4)
    responsibility = v.req_enum(body, "filing_responsibility", FILING_RESPONSIBILITIES)
    region = v.req_enum(body, "data_residency_region", REGIONS)
    frequency = v.req_enum(body, "pay_frequency", PAY_FREQUENCIES)

    country = store.get_country(country_id)
    provider = store.get_provider(provider_id)

    if region != country["data_residency_region"] or region not in provider["data_residency_regions"]:
        raise ApiError(
            "ERR_DATA_RESIDENCY_VIOLATION",
            "The contracted residency region must match the country and be certified for the provider.",
        )
    for item in scope:
        if item not in provider["service_scope"]:
            raise ApiError(
                "ERR_SERVICE_SCOPE_NOT_COVERED",
                "The engagement scope exceeds the provider's contracted service scope.",
            )
    if responsibility == "PROVIDER" and not provider["statutory_filing_capable"]:
        raise ApiError(
            "ERR_FILING_CAPABILITY_MISSING",
            "The provider is not capable of statutory filing.",
        )
    if provider["status"] == "OFFBOARDED":
        raise ApiError(
            "ERR_PROVIDER_INVALID_STATE",
            "An offboarded provider can no longer take new work.",
        )
    for row in store.engagements.values():
        if (
            row["country_profile_id"] == country_id
            and row["provider_id"] == provider_id
            and row["status"] != "REJECTED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_ENGAGEMENT",
                "An engagement already pairs this country with this provider.",
            )

    row = new_row(
        {
            "country_profile_id": country_id,
            "provider_id": provider_id,
            "transition_incoming_provider_id": None,
            "service_scope": scope,
            "filing_responsibility": responsibility,
            "data_residency_region": region,
            "pay_frequency": frequency,
            "residency_terms_ref": None,
            "status": "DRAFT",
            "activated_at": None,
            "treasury_committed_minor": 0,
            "transition_required": False,
            "closed_cycle_count": 0,
            "transition_cutover_start_date": None,
            "transition_cutover_end_date": None,
            "transition_parallel_run_cycles": None,
        }
    )
    store.engagements[row["id"]] = row
    return created(serial.engagement(row))


@bp.get("/payroll/engagements/<ident>")
@require(*ALL_ROLES)
def read_engagement(ident):
    return object_response(serial.engagement(store.get_engagement(ident)))


@bp.get("/payroll/engagements")
@require(*ALL_ROLES)
def list_engagements():
    limit, offset = v.pagination()
    status = v.query_enum("status", ENGAGEMENT_STATUSES)
    country_id = v.query_value("country_profile_id")
    provider_id = v.query_value("provider_id")
    incoming_id = v.query_value("transition_incoming_provider_id")

    rows = list(store.engagements.values())
    if country_id is not None:
        rows = [r for r in rows if r["country_profile_id"] == country_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if incoming_id is not None:
        rows = [r for r in rows if r["transition_incoming_provider_id"] == incoming_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(store.ordered(rows), serial.engagement, limit, offset)


# ---------------------------------------------------------------------------
# Residency decision
# ---------------------------------------------------------------------------
@bp.post("/payroll/engagements/<ident>/residency-decision")
@require(COMPLIANCE_AUDITOR)
def residency_decision(ident):
    body = v.json_body()
    decision = v.req_enum(body, "decision", ["APPROVE", "REJECT"])
    terms_ref = None
    note = None
    if decision == "APPROVE":
        terms_ref = v.req_str(body, "residency_terms_ref", 1, 60)
    else:
        note = v.req_str(body, "rejection_note", 1, 200)

    engagement = store.get_engagement(ident)
    if engagement["status"] != "DRAFT":
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "A residency decision is only available on a DRAFT engagement.",
        )

    if decision == "APPROVE":
        engagement["residency_terms_ref"] = terms_ref
        engagement["status"] = "ACTIVE"
        engagement["activated_at"] = now()
        touch(engagement)
        services.recompute_provider_score(store.provider_of_engagement(engagement))
    else:
        engagement["status"] = "REJECTED"
        touch(engagement)
    return object_response(serial.engagement(engagement))


# ---------------------------------------------------------------------------
# Transition plan (optimistic concurrency on the engagement)
# ---------------------------------------------------------------------------
@bp.post("/payroll/engagements/<ident>/transition-plan")
@require(PAYROLL_CONTROLLER)
def transition_plan(ident):
    body = v.json_body()
    incoming_id = v.req_id(body, "incoming_provider_id")
    start_date = v.req_date(body, "cutover_period_start_date")
    end_date = v.req_date(body, "cutover_period_end_date")
    parallel = v.req_int(body, "parallel_run_cycles", 0, 3)
    expected = v.req_int(body, "expected_engagement_version")

    engagement = store.get_engagement(ident)
    incoming = store.get_provider(incoming_id)

    if engagement["status"] not in ("ACTIVE", "REMEDIATION_REQUIRED"):
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "A transition plan requires an ACTIVE or REMEDIATION_REQUIRED engagement.",
        )
    if expected != engagement["version"]:
        raise ApiError(
            "ERR_STALE_ENGAGEMENT_VERSION",
            "The expected engagement version does not match the stored version.",
        )
    if not end_date > start_date:
        raise bad_request("cutover_period_end_date must be strictly after cutover_period_start_date.")
    if (
        incoming["id"] == engagement["provider_id"]
        or incoming["status"] != "ACTIVE"
        or engagement["data_residency_region"] not in incoming["data_residency_regions"]
    ):
        raise ApiError(
            "ERR_INCOMING_PROVIDER_INVALID",
            "The incoming provider is not a valid alternative for this engagement.",
        )

    engagement["transition_incoming_provider_id"] = incoming["id"]
    engagement["transition_cutover_start_date"] = date_str(start_date)
    engagement["transition_cutover_end_date"] = date_str(end_date)
    engagement["transition_parallel_run_cycles"] = parallel
    engagement["status"] = "TRANSITION_PLANNED"
    touch(engagement)
    return object_response(serial.engagement(engagement))


# ---------------------------------------------------------------------------
# Transition decision
# ---------------------------------------------------------------------------
@bp.post("/payroll/engagements/<ident>/transition-decision")
@require(PLATFORM_ADMIN)
def transition_decision(ident):
    body = v.json_body()
    decision = v.req_enum(body, "decision", ["APPROVE", "ABORT", "COMPLETE"])
    confirmed = v.opt_bool(body, "knowledge_transfer_confirmed", default=None)

    engagement = store.get_engagement(ident)
    if decision == "APPROVE":
        allowed = ("TRANSITION_PLANNED",)
    elif decision == "COMPLETE":
        allowed = ("TRANSITION_IN_PROGRESS",)
    else:
        allowed = ("TRANSITION_PLANNED", "TRANSITION_IN_PROGRESS")
    if engagement["status"] not in allowed:
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "This transition decision is not available from the engagement's current status.",
        )

    if decision == "APPROVE":
        engagement["status"] = "TRANSITION_IN_PROGRESS"
        touch(engagement)
        return object_response(serial.engagement(engagement))

    if decision == "ABORT":
        engagement["transition_incoming_provider_id"] = None
        engagement["transition_cutover_start_date"] = None
        engagement["transition_cutover_end_date"] = None
        engagement["transition_parallel_run_cycles"] = None
        engagement["status"] = (
            "REMEDIATION_REQUIRED" if engagement["transition_required"] else "ACTIVE"
        )
        touch(engagement)
        return object_response(serial.engagement(engagement))

    # COMPLETE
    for cycle in store.cycles_of_engagement(engagement["id"]):
        if cycle["status"] in LIVE_CYCLE_STATUSES:
            raise ApiError(
                "ERR_CYCLE_INVALID_STATE",
                "A cycle of this engagement is still mid-flight.",
            )
    if confirmed is not True:
        raise ApiError(
            "ERR_KNOWLEDGE_TRANSFER_INCOMPLETE",
            "knowledge_transfer_confirmed must be present and true to complete the transition.",
        )

    outgoing = store.provider_of_engagement(engagement)
    incoming_id = engagement["transition_incoming_provider_id"]
    engagement["provider_id"] = incoming_id
    engagement["transition_incoming_provider_id"] = None
    engagement["transition_cutover_start_date"] = None
    engagement["transition_cutover_end_date"] = None
    engagement["transition_parallel_run_cycles"] = None
    engagement["transition_required"] = False
    engagement["status"] = "ACTIVE"
    touch(engagement)

    services.offboard_if_idle(outgoing)
    if incoming_id in store.providers:
        services.recompute_provider_score(store.providers[incoming_id])
    return object_response(serial.engagement(engagement))
