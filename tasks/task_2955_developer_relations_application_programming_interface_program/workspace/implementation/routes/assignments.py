"""Entitlements: provisioning, lifecycle, usage windows and upgrade requests."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    ENTITLEMENT_STATES,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PARTNER_SUPPORT,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRUST_SAFETY,
    THROTTLE_STATES,
    UPGRADE_JUSTIFICATION_FLOOR,
    UPGRADE_STATES,
)
from db import new_id, store
from errors import ApiError, invalid
from middleware import endpoint, lookup, require_not_revoked, require_owner
from response import (
    array_response,
    enum_filter,
    object_response,
    pagination,
    string_filter,
)
from serializers import quota_assignment_out, upgrade_request_out, usage_window_out
from services import quota, usage
from services.common import (
    product_of_assignment,
    product_of_version,
    require_docs_acknowledged,
    require_good_standing,
    require_tos_current,
    require_version_grantable,
    require_version_not_sunset,
)
from validation import body

bp = Blueprint("assignments", __name__)


def _assignment(assignment_id):
    return lookup(
        store.quota_assignments, assignment_id, "ERR_QUOTA_ASSIGNMENT_NOT_FOUND"
    )


@bp.post("/quota-assignments")
@endpoint([ROLE_PLATFORM_ADMIN])
def provision_assignment():
    payload = body()
    application_id = payload.string("access_application_id", min_len=1)
    expected_version = payload.integer("expected_api_product_version", minimum=1)

    application = lookup(
        store.access_applications, application_id, "ERR_ACCESS_APPLICATION_NOT_FOUND"
    )
    version = store.api_versions[application["target_api_version_id"]]
    product = product_of_version(version)

    # rung 9 -- optimistic concurrency on the product's pools
    if expected_version != product["version"]:
        raise ApiError(
            "ERR_STALE_PRODUCT_VERSION",
            "The product has moved to version %d since it was read."
            % product["version"],
        )

    if application["state"] != "APPROVED":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Only an APPROVED application may be provisioned; state is %s."
            % application["state"],
        )

    developer = store.developers[application["developer_id"]]
    require_good_standing(developer)
    require_tos_current(developer, product)
    require_docs_acknowledged(developer)
    require_version_grantable(version, application["approved_tier"])

    for existing in store.quota_assignments.values():
        if existing["access_application_id"] == application["id"]:
            raise ApiError(
                "ERR_ASSIGNMENT_ALREADY_EXISTS",
                "This application already backs an entitlement.",
            )

    assignment = quota.provision(application, developer, version, product)
    return object_response(quota_assignment_out(assignment), 201)


@bp.get("/quota-assignments/<assignment_id>")
@endpoint(
    [
        ROLE_DEVELOPER,
        ROLE_DEVREL_MANAGER,
        ROLE_PLATFORM_ADMIN,
        ROLE_TRUST_SAFETY,
        ROLE_PARTNER_SUPPORT,
    ]
)
def read_assignment(assignment_id):
    assignment = _assignment(assignment_id)
    require_owner(assignment["developer_id"])
    return object_response(quota_assignment_out(assignment))


@bp.get("/quota-assignments")
@endpoint(
    [ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN, ROLE_TRUST_SAFETY]
)
def list_assignments():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    application_id = string_filter("access_application_id")
    version_id = string_filter("pinned_api_version_id")
    state = enum_filter("entitlement_state", ENTITLEMENT_STATES)
    throttle = enum_filter("throttle_state", THROTTLE_STATES)

    records = store.ordered(store.quota_assignments)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if application_id is not None:
        records = [r for r in records if r["access_application_id"] == application_id]
    if version_id is not None:
        records = [r for r in records if r["pinned_api_version_id"] == version_id]
    if state is not None:
        records = [r for r in records if r["entitlement_state"] == state]
    if throttle is not None:
        records = [r for r in records if r["throttle_state"] == throttle]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response(
        [quota_assignment_out(r) for r in page], total, limit, offset
    )


@bp.post("/quota-assignments/<assignment_id>/activate")
@endpoint([ROLE_PLATFORM_ADMIN])
def activate_assignment(assignment_id):
    body()
    assignment = _assignment(assignment_id)

    if assignment["entitlement_state"] != "PROVISIONED":
        raise ApiError(
            "ERR_ASSIGNMENT_STATE_INVALID",
            "Only a PROVISIONED entitlement may be activated; state is %s."
            % assignment["entitlement_state"],
        )

    developer = store.developers[assignment["developer_id"]]
    require_good_standing(developer)
    require_version_not_sunset(
        store.api_versions.get(assignment["pinned_api_version_id"])
    )

    assignment["entitlement_state"] = "ACTIVE"
    assignment["activated_at"] = store.now()
    store.touch(assignment)

    if developer["onboarding_state"] == "SANDBOX_VALIDATED":
        developer["onboarding_state"] = "PRODUCTION_ACTIVE"
        store.touch(developer)

    return object_response(quota_assignment_out(assignment))


@bp.post("/quota-assignments/<assignment_id>/suspend")
@endpoint([ROLE_PLATFORM_ADMIN])
def suspend_assignment(assignment_id):
    payload = body()
    reason = payload.string("suspension_reason", min_len=1)

    assignment = _assignment(assignment_id)
    if assignment["entitlement_state"] != "ACTIVE":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACTIVE",
            "Only an ACTIVE entitlement may be suspended; state is %s."
            % assignment["entitlement_state"],
        )

    quota.suspend(assignment, reason)
    return object_response(quota_assignment_out(assignment))


@bp.post("/quota-assignments/<assignment_id>/reinstate")
@endpoint([ROLE_PLATFORM_ADMIN])
def reinstate_assignment(assignment_id):
    body()
    assignment = _assignment(assignment_id)

    if assignment["entitlement_state"] != "SUSPENDED":
        raise ApiError(
            "ERR_ASSIGNMENT_STATE_INVALID",
            "Only a SUSPENDED entitlement may be reinstated; state is %s."
            % assignment["entitlement_state"],
        )

    developer = store.developers[assignment["developer_id"]]
    require_good_standing(developer)
    require_version_not_sunset(
        store.api_versions.get(assignment["pinned_api_version_id"])
    )

    product = product_of_assignment(assignment)
    if quota.available_sustained(product) < assignment["sustained_rpm"]:
        raise ApiError(
            "ERR_SUSTAINED_POOL_EXHAUSTED",
            "The product cannot cover this entitlement's sustained rate.",
        )
    if quota.available_monthly(product) < assignment["monthly_call_allowance"]:
        raise ApiError(
            "ERR_MONTHLY_POOL_EXHAUSTED",
            "The product cannot cover this entitlement's monthly allowance.",
        )

    quota.restore(assignment)
    return object_response(quota_assignment_out(assignment))


# ------------------------------------------------------------- usage windows
@bp.post("/quota-assignments/<assignment_id>/usage-windows")
@endpoint([ROLE_PLATFORM_ADMIN, ROLE_DEVREL_MANAGER])
def ingest_usage_window(assignment_id):
    payload = body()
    window_start = payload.instant("window_start")
    total_calls = payload.integer("total_calls", minimum=0)
    burst_calls = payload.integer("burst_calls", minimum=0)
    if burst_calls > total_calls:
        invalid("burst_calls may not exceed total_calls.")

    assignment = _assignment(assignment_id)

    if assignment["entitlement_state"] != "ACTIVE":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACTIVE",
            "Usage may only be ingested against an ACTIVE entitlement; state is %s."
            % assignment["entitlement_state"],
        )

    # rung 30 -- hour alignment
    if (
        window_start.minute != 0
        or window_start.second != 0
        or window_start.microsecond != 0
    ):
        raise ApiError(
            "ERR_WINDOW_NOT_ALIGNED",
            "window_start must be exactly hour-aligned.",
        )

    window_end = window_start + timedelta(minutes=60)

    # rung 31 -- no future traffic
    if window_end > store.now():
        raise ApiError(
            "ERR_WINDOW_IN_FUTURE",
            "window_end must be at or before the logical clock.",
        )

    # rung 32 -- non-decreasing chronological order
    latest = usage.latest_window_start(assignment["id"])
    if latest is not None and window_start < latest:
        raise ApiError(
            "ERR_WINDOW_OUT_OF_ORDER",
            "window_start must be at or after the most recent recorded window.",
        )

    # rung 33 -- one window per start instant
    if usage.window_exists(assignment["id"], window_start):
        raise ApiError(
            "ERR_WINDOW_DUPLICATE",
            "A window with that window_start already exists for this entitlement.",
        )

    developer = store.developers[assignment["developer_id"]]
    window = usage.ingest_window(
        assignment, developer, window_start, total_calls, burst_calls
    )
    return object_response(usage_window_out(window), 201)


@bp.get("/quota-assignments/<assignment_id>/usage-windows")
@endpoint(
    [ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN, ROLE_TRUST_SAFETY]
)
def list_usage_windows(assignment_id):
    limit, offset = pagination()
    assignment = _assignment(assignment_id)
    require_owner(assignment["developer_id"])
    records = usage.windows_of(assignment["id"])
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([usage_window_out(r) for r in page], total, limit, offset)


# ----------------------------------------------------------- upgrade requests
@bp.post("/quota-assignments/<assignment_id>/upgrade-requests")
@endpoint([ROLE_DEVELOPER])
def create_upgrade_request(assignment_id):
    payload = body()
    requested = payload.integer("requested_sustained_rpm", minimum=1)
    justification = payload.string("justification_text", min_len=1)
    expected_version = payload.integer("expected_quota_assignment_version", minimum=1)

    assignment = _assignment(assignment_id)
    require_owner(assignment["developer_id"])

    # rung 10 -- optimistic concurrency on the entitlement
    if expected_version != assignment["version"]:
        raise ApiError(
            "ERR_STALE_ASSIGNMENT_VERSION",
            "The entitlement has moved to version %d since it was read."
            % assignment["version"],
        )

    if assignment["entitlement_state"] != "ACTIVE":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACTIVE",
            "Only an ACTIVE entitlement may be upgraded; state is %s."
            % assignment["entitlement_state"],
        )

    require_not_revoked()

    if len(justification) < UPGRADE_JUSTIFICATION_FLOOR:
        raise ApiError(
            "ERR_JUSTIFICATION_INSUFFICIENT",
            "justification_text must be at least %d characters."
            % UPGRADE_JUSTIFICATION_FLOOR,
        )

    if requested <= assignment["sustained_rpm"]:
        raise ApiError(
            "ERR_UPGRADE_NOT_AN_INCREASE",
            "requested_sustained_rpm must exceed the current sustained rate of %d."
            % assignment["sustained_rpm"],
        )

    ceiling = quota.tier_ceiling(assignment["tier"])
    if assignment["sustained_rpm"] >= ceiling:
        raise ApiError(
            "ERR_TIER_CEILING_REACHED",
            "The entitlement is already at its tier ceiling of %d." % ceiling,
        )

    for prior in quota.pending_upgrade_requests_of(assignment["id"]):
        prior["state"] = "SUPERSEDED"
        store.touch(prior)

    request_record = {
        "id": new_id(),
        "quota_assignment_id": assignment["id"],
        "requested_sustained_rpm": requested,
        "justification_text": justification,
        "requested_delta_rpm": requested - assignment["sustained_rpm"],
        "granted_delta_rpm": 0,
        "state": "PENDING",
        "denial_reason": None,
        "run_sequence": None,
        "decided_at": None,
    }
    store.stamp_new(request_record)
    store.upgrade_requests[request_record["id"]] = request_record
    store.touch(assignment)
    return object_response(upgrade_request_out(request_record), 201)


@bp.get("/quota-assignments/<assignment_id>/upgrade-requests")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_upgrade_requests(assignment_id):
    limit, offset = pagination()
    state = enum_filter("state", UPGRADE_STATES)
    assignment = _assignment(assignment_id)
    require_owner(assignment["developer_id"])
    records = [
        u
        for u in store.ordered(store.upgrade_requests)
        if u["quota_assignment_id"] == assignment["id"]
    ]
    if state is not None:
        records = [r for r in records if r["state"] == state]
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([upgrade_request_out(r) for r in page], total, limit, offset)


@bp.get("/upgrade-requests/<request_id>")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_upgrade_request(request_id):
    record = lookup(store.upgrade_requests, request_id, "ERR_UPGRADE_REQUEST_NOT_FOUND")
    assignment = store.quota_assignments.get(record["quota_assignment_id"])
    if assignment is not None:
        require_owner(assignment["developer_id"])
    return object_response(upgrade_request_out(record))
