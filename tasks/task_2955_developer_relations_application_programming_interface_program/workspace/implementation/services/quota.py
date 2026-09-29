"""Capacity pools, the provisioning calculation, entitlement lifecycle
transitions and the upgrade allocation waterfall."""
from decimal import Decimal

from constants import (
    BURST_CREDIT_MULTIPLIER,
    TIER_BASE_SUSTAINED_RPM,
    TIER_BURST_FACTOR,
    TIER_MONTHLY_CALL_CAP,
    TIER_RANK,
    UPGRADE_CEILING_FACTOR,
    trust_multiplier,
)
from db import new_id, store
from errors import ApiError

from .common import (
    ceil_int,
    floor_int,
    product_of_assignment,
    scope_factor,
)


# ---------------------------------------------------------------------- pools
def available_sustained(product):
    return product["sustained_rpm_pool"] - product["allocated_sustained_rpm"]


def available_monthly(product):
    return product["monthly_call_pool"] - product["allocated_monthly_calls"]


def reserve(product, sustained, monthly):
    product["allocated_sustained_rpm"] += sustained
    product["allocated_monthly_calls"] += monthly
    store.touch(product)


def release(product, sustained, monthly):
    product["allocated_sustained_rpm"] -= sustained
    product["allocated_monthly_calls"] -= monthly
    store.touch(product)


def tier_ceiling(tier):
    return UPGRADE_CEILING_FACTOR * TIER_BASE_SUSTAINED_RPM[tier]


def burst_from_sustained(sustained, tier):
    factor = TIER_BURST_FACTOR[tier]
    return sustained + ceil_int(Decimal(sustained) * (factor - Decimal(1)))


# --------------------------------------------------------------- provisioning
def provision(application, developer, version, product):
    """Pinned order: sustained rate, pool deduction, burst, monthly allowance."""
    tier = application["approved_tier"]
    scopes = list(application["granted_scopes"] or [])

    base = TIER_BASE_SUSTAINED_RPM[tier]
    multiplier = trust_multiplier(developer["trust_score"])
    factor = scope_factor(product, scopes)
    desired = floor_int(Decimal(base) * multiplier * factor)

    room_sustained = available_sustained(product)
    sustained = desired if desired < room_sustained else room_sustained
    if sustained <= 0:
        raise ApiError(
            "ERR_SUSTAINED_POOL_EXHAUSTED",
            "The product has no sustained rate capacity left to allocate.",
        )

    burst = burst_from_sustained(sustained, tier)
    burst_credit = burst * BURST_CREDIT_MULTIPLIER

    room_monthly = available_monthly(product)
    monthly = min(
        application["requested_monthly_calls"],
        TIER_MONTHLY_CALL_CAP[tier],
        room_monthly,
    )
    if monthly <= 0:
        raise ApiError(
            "ERR_MONTHLY_POOL_EXHAUSTED",
            "The product has no monthly call capacity left to allocate.",
        )

    now = store.now()
    assignment = {
        "id": new_id(),
        "developer_id": application["developer_id"],
        "access_application_id": application["id"],
        "pinned_api_version_id": application["target_api_version_id"],
        "tier": tier,
        "granted_scopes": scopes,
        "sustained_rpm": sustained,
        "burst_rpm": burst,
        "burst_credit_balance": burst_credit,
        "monthly_call_allowance": monthly,
        "bonus_call_credit": 0,
        "monthly_calls_consumed": 0,
        "entitlement_state": "PROVISIONED",
        "throttle_state": "NORMAL",
        "trust_multiplier_applied": multiplier,
        "activated_at": None,
        "suspended_at": None,
        "suspension_reason": None,
        "retired_at": None,
        "last_reset_at": now,
    }
    store.stamp_new(assignment)
    store.quota_assignments[assignment["id"]] = assignment
    reserve(product, sustained, monthly)
    return assignment


# ----------------------------------------------------------- upgrade requests
def pending_upgrade_requests_of(assignment_id):
    return [
        u
        for u in store.ordered(store.upgrade_requests)
        if u["quota_assignment_id"] == assignment_id and u["state"] == "PENDING"
    ]


def void_pending_upgrades(assignment, denial_reason=None):
    voided = []
    for request in pending_upgrade_requests_of(assignment["id"]):
        request["state"] = "VOIDED"
        if denial_reason is not None:
            request["denial_reason"] = denial_reason
        store.touch(request)
        voided.append(request["id"])
    return voided


# ------------------------------------------------------- lifecycle movements
def suspend(assignment, reason, standing_cascade=False):
    product = product_of_assignment(assignment)
    assignment["entitlement_state"] = "SUSPENDED"
    assignment["suspended_at"] = store.now()
    assignment["suspension_reason"] = reason
    store.touch(assignment)
    if product is not None:
        release(product, assignment["sustained_rpm"], assignment["monthly_call_allowance"])
    return void_pending_upgrades(
        assignment, "STANDING_BLOCKED" if standing_cascade else None
    )


def retire(assignment):
    """Release is idempotent across the suspension boundary."""
    previous = assignment["entitlement_state"]
    product = product_of_assignment(assignment)
    assignment["entitlement_state"] = "RETIRED"
    assignment["retired_at"] = store.now()
    store.touch(assignment)
    if previous in ("PROVISIONED", "ACTIVE") and product is not None:
        release(product, assignment["sustained_rpm"], assignment["monthly_call_allowance"])
    return void_pending_upgrades(assignment)


def restore(assignment):
    """Reinstatement cascade from an appeal dismissal."""
    product = product_of_assignment(assignment)
    assignment["entitlement_state"] = "ACTIVE"
    assignment["suspended_at"] = None
    assignment["suspension_reason"] = None
    store.touch(assignment)
    if product is not None:
        reserve(product, assignment["sustained_rpm"], assignment["monthly_call_allowance"])


# --------------------------------------------------------- allocation run
def _queue_sort_key(request):
    assignment = store.quota_assignments[request["quota_assignment_id"]]
    return (
        -TIER_RANK.get(assignment["tier"], 0),
        request["requested_delta_rpm"],
        request["created_at"],
        request["_seq"],
    )


def allocation_run(product):
    product_id = product["id"]
    candidates = []
    for request in store.ordered(store.upgrade_requests):
        if request["state"] != "PENDING":
            continue
        assignment = store.quota_assignments.get(request["quota_assignment_id"])
        if assignment is None:
            continue
        version = store.api_versions.get(assignment["pinned_api_version_id"])
        if version is None or version["api_product_id"] != product_id:
            continue
        candidates.append(request)

    if not candidates:
        raise ApiError(
            "ERR_NO_PENDING_UPGRADE_REQUESTS",
            "No pending upgrade request exists for this product.",
        )

    queue = []
    for request in candidates:
        assignment = store.quota_assignments[request["quota_assignment_id"]]
        if assignment["entitlement_state"] != "ACTIVE":
            continue
        developer = store.developers.get(assignment["developer_id"])
        if developer is None or developer["standing"] != "GOOD_STANDING":
            continue
        queue.append(request)

    queue.sort(key=_queue_sort_key)

    remaining = available_sustained(product)
    now = store.now()
    granted_count = 0
    partial_count = 0
    deferred_count = 0
    total_delta = 0
    sequence = 0

    for request in queue:
        sequence += 1
        request["run_sequence"] = sequence
        request["decided_at"] = now
        if remaining == 0:
            request["state"] = "DEFERRED"
            request["denial_reason"] = "POOL_EXHAUSTED"
            deferred_count += 1
            store.touch(request)
            continue
        assignment = store.quota_assignments[request["quota_assignment_id"]]
        headroom = tier_ceiling(assignment["tier"]) - assignment["sustained_rpm"]
        grant = min(request["requested_delta_rpm"], remaining, headroom)
        if grant < 0:
            grant = 0
        request["granted_delta_rpm"] = grant
        if grant == request["requested_delta_rpm"]:
            request["state"] = "GRANTED"
            granted_count += 1
        else:
            request["state"] = "PARTIALLY_GRANTED"
            partial_count += 1
        store.touch(request)
        if grant > 0:
            assignment["sustained_rpm"] += grant
            assignment["burst_rpm"] = burst_from_sustained(
                assignment["sustained_rpm"], assignment["tier"]
            )
            store.touch(assignment)
            product["allocated_sustained_rpm"] += grant
            store.touch(product)
            remaining -= grant
            total_delta += grant

    return {
        "run_sequence_count": sequence,
        "granted_count": granted_count,
        "partially_granted_count": partial_count,
        "deferred_count": deferred_count,
        "allocated_sustained_rpm_delta": total_delta,
        "available_sustained_rpm_after": available_sustained(product),
    }
