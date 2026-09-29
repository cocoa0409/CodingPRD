"""Support-case response commitments, cadence figures and service credits."""
from decimal import Decimal

from constants import (
    COMMS_MAX_GAP_MINUTES,
    MINUTES_PER_DAY,
    SEVERITY_CREDIT_RATE,
)
from db import store, whole_minutes_between

from . import usage
from .common import round_half_up_int


def communications_of(case_id):
    records = [
        c for c in store.communications.values() if c["support_case_id"] == case_id
    ]
    records.sort(key=lambda c: (c["sent_at"], c["_seq"]))
    return records


def checkpoint_chain(case):
    chain = [case["started_at"]]
    for comm in communications_of(case["id"]):
        chain.append(comm["sent_at"])
    if case["state"] == "RESOLVED" and case["resolved_at"] is not None:
        chain.append(case["resolved_at"])
    return chain


def max_gap_minutes(case):
    chain = checkpoint_chain(case)
    if len(chain) < 2:
        return 0
    largest = 0
    for index in range(1, len(chain)):
        gap = whole_minutes_between(chain[index - 1], chain[index])
        if gap > largest:
            largest = gap
    return largest


def refresh_cadence(case):
    gap = max_gap_minutes(case)
    case["max_communication_gap_minutes"] = gap
    case["comms_gap_breached"] = gap > COMMS_MAX_GAP_MINUTES[case["severity"]]
    return gap


def latest_resolved_incident(product_id, severity):
    latest = None
    for case in store.support_cases.values():
        if (
            case["kind"] != "PLATFORM_INCIDENT"
            or case["api_product_id"] != product_id
            or case["severity"] != severity
            or case["resolved_at"] is None
        ):
            continue
        if latest is None or case["resolved_at"] > latest["resolved_at"]:
            latest = case
    return latest


def apply_incident_credits(case):
    """Per-entitlement rounding, then a sum that is never re-rounded."""
    rate = SEVERITY_CREDIT_RATE[case["severity"]]
    uplift = case["credit_uplift_applied"]
    downtime = case["downtime_minutes"]

    affected = []
    for assignment in store.ordered(store.quota_assignments):
        if assignment["entitlement_state"] != "ACTIVE":
            continue
        version = store.api_versions.get(assignment["pinned_api_version_id"])
        if version is None or version["api_product_id"] != case["api_product_id"]:
            continue
        affected.append(assignment)

    total = 0
    for assignment in affected:
        raw = (
            Decimal(assignment["monthly_call_allowance"])
            * rate
            * Decimal(uplift)
            * Decimal(downtime)
            / Decimal(MINUTES_PER_DAY)
        )
        credit = round_half_up_int(raw)
        total += credit
        assignment["bonus_call_credit"] += credit
        usage.reevaluate_throttle(assignment)
        store.touch(assignment)

    case["affected_assignment_count"] = len(affected)
    case["total_credit_calls"] = total
    return total
