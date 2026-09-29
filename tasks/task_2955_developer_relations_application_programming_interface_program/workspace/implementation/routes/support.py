"""Support cases: response commitments, cadence, escalation and credits."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    COMMS_BREACH_UPLIFT,
    ESCALATION_ENTITLED_TIERS,
    FIRST_RESPONSE_SLA_MINUTES,
    INCIDENT_COALESCE_MINUTES,
    MAX_ESCALATION_TIER,
    NO_BREACH_UPLIFT,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PARTNER_SUPPORT,
    ROLE_PLATFORM_ADMIN,
    SUPPORT_KINDS,
    SUPPORT_SEVERITIES,
    SUPPORT_STATES,
)
from db import new_id, store, whole_minutes_between
from errors import ApiError
from middleware import endpoint, lookup, require_not_revoked, require_owner
from response import (
    array_response,
    enum_filter,
    object_response,
    pagination,
    string_filter,
)
from serializers import support_case_out
from services import support
from validation import body

bp = Blueprint("support", __name__)


def _case(case_id):
    return lookup(store.support_cases, case_id, "ERR_SUPPORT_CASE_NOT_FOUND")


def _kind_mismatch(message):
    raise ApiError("ERR_SUPPORT_CASE_KIND_MISMATCH", message)


@bp.post("/support-cases")
@endpoint([ROLE_PARTNER_SUPPORT, ROLE_DEVELOPER])
def open_support_case():
    payload = body()
    kind = payload.string("kind", choices=SUPPORT_KINDS)
    developer_id = payload.string("developer_id", required=False)
    product_id = payload.string("api_product_id", min_len=1)
    severity = payload.string("severity", choices=SUPPORT_SEVERITIES)
    title = payload.string("title", min_len=5, max_len=200)
    started_at = payload.instant("started_at", required=False)

    developer = None
    if developer_id is not None:
        developer = lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    product = lookup(store.api_products, product_id, "ERR_API_PRODUCT_NOT_FOUND")

    if developer is not None:
        require_owner(developer["id"])
    require_not_revoked()

    # rung 26 -- an S1/S2 partner ticket needs a PARTNER or PRIVILEGED entitlement
    if kind == "PARTNER_TICKET" and developer is not None and severity in ("S1", "S2"):
        if not _has_active_on_product(developer["id"], product["id"], ESCALATION_ENTITLED_TIERS):
            raise ApiError(
                "ERR_SEVERITY_NOT_ENTITLED",
                "An %s partner ticket requires an ACTIVE PARTNER or PRIVILEGED "
                "entitlement on this product." % severity,
            )

    # rung 37 -- platform incidents are coalesced per product and severity
    if kind == "PLATFORM_INCIDENT" and started_at is not None:
        latest = support.latest_resolved_incident(product["id"], severity)
        if latest is not None:
            buffer_end = latest["resolved_at"] + timedelta(
                minutes=INCIDENT_COALESCE_MINUTES
            )
            if started_at < buffer_end:
                raise ApiError(
                    "ERR_INCIDENT_COALESCE_WINDOW",
                    "A %s incident on this product resolved less than %d minutes "
                    "before this start instant." % (severity, INCIDENT_COALESCE_MINUTES),
                )

    # rung 44 -- the kind decides which fields are required and which forbidden
    if kind == "PARTNER_TICKET":
        if developer is None:
            _kind_mismatch("A PARTNER_TICKET must name the reporting developer_id.")
        if not _has_active_on_product(developer["id"], product["id"], None):
            _kind_mismatch(
                "A PARTNER_TICKET requires an ACTIVE entitlement on the named product."
            )
        started_at = None
    else:
        if developer is not None:
            _kind_mismatch("A PLATFORM_INCIDENT must not name a developer_id.")
        if started_at is None:
            _kind_mismatch("A PLATFORM_INCIDENT must supply started_at.")

    case = {
        "id": new_id(),
        "kind": kind,
        "developer_id": developer["id"] if developer is not None else None,
        "api_product_id": product["id"],
        "severity": severity,
        "title": title,
        "started_at": None,
        "state": "OPEN",
        "escalation_tier": 0,
        "first_response_due_minutes": FIRST_RESPONSE_SLA_MINUTES[kind][severity],
        "first_response_at": None,
        "first_response_breached": False,
        "communication_count": 0,
        "last_communication_at": None,
        "max_communication_gap_minutes": 0,
        "comms_gap_breached": False,
        "resolved_at": None,
        "downtime_minutes": None,
        "credit_uplift_applied": None,
        "affected_assignment_count": 0,
        "total_credit_calls": 0,
        "resolution_note": None,
    }
    store.stamp_new(case)
    # a partner ticket's clock starts at its own creation instant
    case["started_at"] = case["created_at"] if kind == "PARTNER_TICKET" else started_at
    store.support_cases[case["id"]] = case
    return object_response(support_case_out(case), 201)


def _pinned_to_product(assignment, product_id):
    version = store.api_versions.get(assignment["pinned_api_version_id"])
    return version is not None and version["api_product_id"] == product_id


def _has_active_on_product(developer_id, product_id, tiers):
    for assignment in store.quota_assignments.values():
        if assignment["developer_id"] != developer_id:
            continue
        if assignment["entitlement_state"] != "ACTIVE":
            continue
        if not _pinned_to_product(assignment, product_id):
            continue
        if tiers is not None and assignment["tier"] not in tiers:
            continue
        return True
    return False


@bp.get("/support-cases/<case_id>")
@endpoint(
    [ROLE_DEVELOPER, ROLE_PARTNER_SUPPORT, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN]
)
def read_support_case(case_id):
    case = _case(case_id)
    require_owner(case["developer_id"])
    return object_response(support_case_out(case))


@bp.get("/support-cases")
@endpoint(
    [ROLE_DEVELOPER, ROLE_PARTNER_SUPPORT, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN]
)
def list_support_cases():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    product_id = string_filter("api_product_id")
    kind = enum_filter("kind", SUPPORT_KINDS)
    state = enum_filter("state", SUPPORT_STATES)

    records = store.ordered(store.support_cases)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if product_id is not None:
        records = [r for r in records if r["api_product_id"] == product_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if state is not None:
        records = [r for r in records if r["state"] == state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response([support_case_out(r) for r in page], total, limit, offset)


@bp.post("/support-cases/<case_id>/communications")
@endpoint([ROLE_PARTNER_SUPPORT])
def record_communication(case_id):
    payload = body()
    sent_at = payload.instant("sent_at")
    text = payload.string("body", min_len=1)

    case = _case(case_id)

    if case["state"] not in ("OPEN", "RESPONDING", "ESCALATED"):
        raise ApiError(
            "ERR_SUPPORT_CASE_STATE_INVALID",
            "A communication cannot be recorded against a %s case." % case["state"],
        )

    if sent_at < case["started_at"]:
        raise ApiError(
            "ERR_COMMUNICATION_OUT_OF_ORDER",
            "sent_at must be at or after the case's started_at.",
        )
    if case["last_communication_at"] is not None and (
        sent_at < case["last_communication_at"]
    ):
        raise ApiError(
            "ERR_COMMUNICATION_OUT_OF_ORDER",
            "sent_at must be at or after the last recorded communication.",
        )
    if sent_at > store.now():
        raise ApiError(
            "ERR_COMMUNICATION_OUT_OF_ORDER",
            "sent_at must be at or before the logical clock.",
        )

    communication = {
        "id": new_id(),
        "support_case_id": case["id"],
        "sent_at": sent_at,
        "body": text,
    }
    store.stamp_new(communication, versioned=False)
    store.communications[communication["id"]] = communication

    first = case["communication_count"] == 0
    case["communication_count"] += 1
    case["last_communication_at"] = sent_at
    if first:
        case["first_response_at"] = sent_at
        elapsed = whole_minutes_between(case["started_at"], sent_at)
        case["first_response_breached"] = elapsed > case["first_response_due_minutes"]
        if case["state"] == "OPEN":
            case["state"] = "RESPONDING"
    support.refresh_cadence(case)
    store.touch(case)
    return object_response(support_case_out(case))


@bp.post("/support-cases/<case_id>/escalate")
@endpoint([ROLE_PARTNER_SUPPORT])
def escalate_support_case(case_id):
    payload = body()
    payload.string("escalation_note", required=False)

    case = _case(case_id)

    if case["state"] not in ("RESPONDING", "ESCALATED"):
        raise ApiError(
            "ERR_SUPPORT_CASE_STATE_INVALID",
            "Only a RESPONDING or ESCALATED case may be escalated; state is %s."
            % case["state"],
        )
    if case["escalation_tier"] >= MAX_ESCALATION_TIER:
        raise ApiError(
            "ERR_SUPPORT_CASE_STATE_INVALID",
            "The escalation channel is capped at tier %d." % MAX_ESCALATION_TIER,
        )

    if case["kind"] == "PARTNER_TICKET" and case["escalation_tier"] >= 1:
        if not _has_active_on_product(
            case["developer_id"], case["api_product_id"], ESCALATION_ENTITLED_TIERS
        ):
            raise ApiError(
                "ERR_ESCALATION_NOT_ENTITLED",
                "Escalating beyond tier 1 requires an ACTIVE PARTNER or PRIVILEGED "
                "entitlement on this product.",
            )

    case["escalation_tier"] += 1
    case["state"] = "ESCALATED"
    store.touch(case)
    return object_response(support_case_out(case))


@bp.post("/support-cases/<case_id>/resolve")
@endpoint([ROLE_PARTNER_SUPPORT])
def resolve_support_case(case_id):
    payload = body()
    note = payload.string("resolution_note", min_len=1)

    case = _case(case_id)

    if case["state"] not in ("RESPONDING", "ESCALATED"):
        raise ApiError(
            "ERR_SUPPORT_CASE_STATE_INVALID",
            "Only a RESPONDING or ESCALATED case may be resolved; state is %s."
            % case["state"],
        )

    resolved_at = store.now()
    if not resolved_at > case["started_at"]:
        raise ApiError(
            "ERR_COMMUNICATION_OUT_OF_ORDER",
            "resolved_at must be strictly after the case's started_at.",
        )
    if case["communication_count"] == 0:
        raise ApiError(
            "ERR_NO_COMMUNICATION_RECORDED",
            "A case cannot be resolved before any communication is recorded.",
        )

    case["state"] = "RESOLVED"
    case["resolved_at"] = resolved_at
    case["resolution_note"] = note
    case["downtime_minutes"] = whole_minutes_between(case["started_at"], resolved_at)
    support.refresh_cadence(case)
    case["credit_uplift_applied"] = (
        COMMS_BREACH_UPLIFT if case["comms_gap_breached"] else NO_BREACH_UPLIFT
    )

    if case["kind"] == "PLATFORM_INCIDENT":
        support.apply_incident_credits(case)

    store.touch(case)
    return object_response(support_case_out(case))
